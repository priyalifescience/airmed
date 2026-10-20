"""Build a publishable release folder from collected datasets.

    python -m airmed run all --out out
    python -m airmed release --src out --dist dist/v1

The release folder holds, per dataset, the CSV, the JSON and its datapackage.json, plus:
  catalog.json        machine-readable index of every dataset (this is the simple API)
  DATA_DICTIONARY.md  every field of every dataset, described
  README.md           how to use and cite the release
  CHANGELOG.md        record counts compared with the previous release

Safety: the release is refused if any approved source is missing, if a dataset fails its privacy re-check, or if a
dataset shrank by more than MAX_SHRINK compared with the previous catalog (usually a broken download, not news).
Sources on hold (registry status "pending") are left out, even if an older copy is still in the source folder.

Licences: there is no single licence for the release. Each dataset carries its own source's licence, attribution and
licence notes, refreshed from the current registry at release time (so a licence correction reaches every copy
without waiting for the next collection).
"""

import datetime as dt
import hashlib
import json
import shutil
from pathlib import Path

from . import __version__
from .collectors import ALL
from .output import licence_metadata
from .privacy import EMAIL_RE, PHONE_RE
from .registry import approved_source, held_sources

LICENCE_SUMMARY = ("Multiple licences: each dataset keeps the licence of its source (see its datapackage.json and "
                   "catalog.json); they are not all CC BY 4.0.")

BASE_URL = "https://priyalifescience.com/opendata/airmid/v1/"
MAX_SHRINK = 0.20


class ReleaseRefused(Exception):
    pass


# Served with the files on the website: static only, no site rewrites, no directory listing, readable by other apps.
HTACCESS = """# Static open-data files (Airmid Éireann release)
RewriteEngine Off
Options -Indexes
DirectoryIndex index.html
AddType text/csv .csv
AddType text/markdown .md
AddType application/x-bibtex .bib
AddType application/x-research-info-systems .ris
AddCharset utf-8 .csv .json .md .html .bib .ris
<IfModule mod_headers.c>
  Header set Access-Control-Allow-Origin "*"
  Header set Cache-Control "public, max-age=3600"
  Header set X-Content-Type-Options "nosniff"
</IfModule>
"""


def _index_html(datasets: list, now: str) -> str:
    """A plain, script-free page listing the release for people who open the folder in a browser."""
    import html
    rows = "".join(
        f'<tr><td><b>{html.escape(d["title"])}</b><br><small>{html.escape(d["attribution"])}</small></td>'
        f'<td>{d["records"]:,}</td>'
        f'<td><a href="{d["key"]}/{d["key"]}.csv">CSV</a> · <a href="{d["key"]}/{d["key"]}.json">JSON</a> · '
        f'<a href="{d["key"]}/datapackage.json">datapackage</a></td>'
        f'<td><a href="{html.escape(d["licence_url"])}">{html.escape(d["licence"])}</a></td>'
        f'<td><a href="{html.escape(d.get("browse_url", ""))}">Browse</a></td></tr>'
        for d in datasets)
    return (
        '<!doctype html><html lang="en-IE"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Airmid Éireann open data, v1</title><link rel="canonical" href="https://priyalifescience.com/airmed">'
        '<style>body{font:15px/1.6 system-ui,sans-serif;max-width:1100px;margin:40px auto;padding:0 16px;color:#0B3D1E;background:#F1F3EE}'
        'table{width:100%;border-collapse:collapse}td,th{padding:10px;border-bottom:1px dashed #9bb3a2;text-align:left;vertical-align:top}'
        'a{color:#1F6B35}small{color:#4a6b55}</style></head><body>'
        f'<h1>Airmid Éireann · open data v1</h1><p>Release {html.escape(now)}. Machine-readable index: '
        '<a href="catalog.json">catalog.json</a> · <a href="DATA_DICTIONARY.md">data dictionary</a> · '
        '<a href="CHANGELOG.md">changelog</a> · <a href="https://priyalifescience.com/airmed">about the project</a> · '
        'cite: <a href="citation.bib">BibTeX</a> · <a href="citation.ris">RIS</a></p>'
        f'<p>{html.escape(LICENCE_SUMMARY)} Some carry extra conditions or disclaimers (see the README and each '
        'datapackage.json). Credit the source and “Airmid Éireann, Priya Life Science”. Not medical advice.</p>'
        f'<table><tr><th>Dataset</th><th>Records</th><th>Files</th><th>Licence</th><th>On the website</th></tr>{rows}</table></body></html>')


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _recheck(records: list, key: str) -> None:
    """Second, independent privacy pass over what is about to be published."""
    for r in records:
        for k, v in r.items():
            for s in (v if isinstance(v, list) else [v]):
                if isinstance(s, str) and (EMAIL_RE.search(s) or (not s.startswith("http") and PHONE_RE.search(s))):
                    raise ReleaseRefused(f"{key}.{k}: contact-like value found at release time")


def _refresh_licence(out: Path, key: str, source: dict, payload: dict, lic: dict) -> None:
    """Re-stamp a copied dataset with the registry's current name, publisher, licence and attribution.

    Only the metadata changes: the records are written back unchanged and the JSON hash in datapackage.json is
    recomputed."""
    if (payload.get("source"), payload.get("attribution"), payload.get("licence")) != (source["name"], lic["attribution"], lic["licence"]):
        payload.update(source=source["name"], attribution=lic["attribution"], licence=lic["licence"])
        with open(out / f"{key}.json", "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    pkg_path = out / "datapackage.json"
    pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
    pkg.update(title=source["name"], description=lic["description"], licenses=lic["licenses"],
               licence_notes=lic["licence_notes"], sources=[{"title": source["publisher"], "path": source["endpoint"]}])
    for res in pkg.get("resources", []):
        if res.get("format") == "json" and (out / res.get("path", "")).is_file():
            res["hash"] = "sha256:" + _sha(out / res["path"])
    with open(pkg_path, "w", encoding="utf-8") as f:
        json.dump(pkg, f, ensure_ascii=False, indent=1)


def build(src: Path, dist: Path, base_url: str = BASE_URL) -> dict:
    src, dist = Path(src), Path(dist)
    previous = {}
    old_cat = dist / "catalog.json"
    if old_cat.exists():
        previous = {d["key"]: d for d in json.loads(old_cat.read_text(encoding="utf-8")).get("datasets", [])}

    staged = dist.with_name(dist.name + ".staging")
    if staged.exists():
        shutil.rmtree(staged)
    staged.mkdir(parents=True)
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    datasets, changes = [], []
    held = held_sources()

    for key, mod in ALL.items():
        if key in held:  # licence awaiting confirmation: never released, even from an older copy in src
            continue
        source = approved_source(key)
        folder = src / key
        files = [folder / f"{key}.csv", folder / f"{key}.json", folder / "datapackage.json"]
        if not all(f.exists() for f in files):
            raise ReleaseRefused(f"{key}: not collected (run `python -m airmed run all` first)")
        payload = json.loads(files[1].read_text(encoding="utf-8"))
        records = payload["records"]
        _recheck(records, key)
        n = len(records)
        if key in previous and previous[key]["records"] and n < previous[key]["records"] * (1 - MAX_SHRINK):
            raise ReleaseRefused(f"{key}: {n} records, down from {previous[key]['records']} (more than {int(MAX_SHRINK*100)}% smaller)")
        out = staged / key
        out.mkdir()
        for f in files:
            shutil.copy2(f, out / f.name)
        lic = licence_metadata(source, payload.get("retrieved", ""))
        _refresh_licence(out, key, source, payload, lic)
        datasets.append({
            "key": key,
            "title": source["name"],
            "publisher": source["publisher"],
            "licence": source["licence"],
            "licence_url": source["licence_url"],
            "attribution": lic["attribution"],
            "licence_notes": lic["licence_notes"],
            "source_endpoint": source["endpoint"],
            "browse_url": source.get("browse_url", "https://priyalifescience.com/airmed"),
            "records": n,
            "retrieved": payload.get("retrieved", ""),
            "fields": [{"name": f, "description": source.get("field_docs", {}).get(f, "")} for f in mod.FIELDS],
            "files": [{"format": fmt, "url": f"{base_url}{key}/{name}", "sha256": _sha(out / name), "bytes": (out / name).stat().st_size}
                      for fmt, name in (("csv", f"{key}.csv"), ("json", f"{key}.json"), ("datapackage", "datapackage.json"))],
        })
        before = previous.get(key, {}).get("records")
        changes.append(f"| `{key}` | {before if before is not None else 'new'} | {n} |")

    catalog = {
        "name": "Airmid Éireann: Ireland's Open Pharma Data Project",
        "publisher": "Priya Life Science",
        "homepage": "https://priyalifescience.com/airmed",
        "release": now,
        "generator": f"airmed {__version__}",
        "api_version": "v1",
        "note": LICENCE_SUMMARY + " Credit the source and Airmid Éireann. Not medical advice.",
        "licence": "multiple licences, see each dataset",
        "datasets": datasets,
    }
    (staged / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=1), encoding="utf-8")

    dd = ["# Airmid Éireann: data dictionary", "", f"Release {now}. Every field of every dataset.", ""]
    for d in datasets:
        dd += [f"## `{d['key']}`: {d['title']}", "", f"Publisher: {d['publisher']}. Licence: [{d['licence']}]({d['licence_url']}).",
               f"Attribution: {d['attribution']}", *(f"Licence note: {n}" for n in d["licence_notes"]),
               f"Records: {d['records']:,}", "", "| Field | Description |", "|---|---|"]
        dd += [f"| `{f['name']}` | {f['description']} |" for f in d["fields"]]
        dd.append("")
    (staged / "DATA_DICTIONARY.md").write_text("\n".join(dd), encoding="utf-8")

    readme = [
        "# Airmid Éireann: Ireland's Open Pharma Data Project", "",
        "Open datasets on medicines, clinical trials, approvals, shortages and the pharma industry, collected by",
        "[Priya Life Science](https://priyalifescience.com/airmed) from official public sources.", "",
        f"Release: {now}", "", "## Files", "",
        "- `catalog.json`: every dataset with its source, licence, record count, fields and file links (the simple API)",
        "- `<dataset>/<dataset>.csv` and `.json`: the data", "- `<dataset>/datapackage.json`: Frictionless Data descriptor",
        "- `DATA_DICTIONARY.md`: every field described", "", "## Licence and credit", "",
        LICENCE_SUMMARY + " The licence, its link and the attribution to use are listed for every dataset in",
        "`catalog.json`, `DATA_DICTIONARY.md` and the dataset's `datapackage.json`. Please credit the original source and",
        '"Airmid Éireann, Priya Life Science". Nothing here is medical advice.', "",
        *(["## Licence conditions and disclaimers", "",
           "These datasets carry conditions or notices that their publishers require to be passed on with the data:", ""]
          + [line for d in datasets if d["licence_notes"]
             for line in (f"### `{d['key']}`: {d['title']}", "", *(f"- {n}" for n in d["licence_notes"]), "")]
          if any(d["licence_notes"] for d in datasets) else []),
        "## Cite", "",
        f"Priya Life Science ({now[:4]}). Airmid Éireann: Ireland's Open Pharma Data Project. {base_url}catalog.json", "",
    ]
    (staged / "README.md").write_text("\n".join(readme), encoding="utf-8")
    (staged / "CHANGELOG.md").write_text("\n".join([f"# Release {now}", "", "| Dataset | Previous records | Records |", "|---|---|---|", *changes, ""]),
                                         encoding="utf-8")

    # Citation files for reference managers (Zotero, Mendeley, EndNote, LaTeX).
    year, day = now[:4], now[:10]
    (staged / "citation.bib").write_text(
        "@misc{airmid_eireann_" + day.replace("-", "") + ",\n"
        "  author       = {{Priya Life Science}},\n"
        "  title        = {Airmid {\\'E}ireann: Ireland's Open Pharma Data Project},\n"
        f"  year         = {{{year}}},\n"
        f"  version      = {{v1, release {day}}},\n"
        "  howpublished = {Dataset},\n"
        f"  url          = {{{base_url}catalog.json}},\n"
        f"  urldate      = {{{day}}},\n"
        "  note         = {Open datasets on medicines, clinical trials, approvals, shortages and the pharma industry; each dataset keeps the licence of its source}\n"
        "}\n", encoding="utf-8")
    (staged / "citation.ris").write_text("\r\n".join([
        "TY  - DATA", "AU  - Priya Life Science", "TI  - Airmid Éireann: Ireland's Open Pharma Data Project",
        f"PY  - {year}", f"DA  - {day.replace('-', '/')}", f"ET  - v1, release {day}", "PB  - Priya Life Science",
        "CY  - Ireland", f"UR  - {base_url}catalog.json", "LA  - en",
        "AB  - Open datasets on medicines, clinical trials, approvals, shortages and the pharma industry, collected from official public sources. Each dataset keeps the licence of its source.",
        "KW  - open data", "KW  - pharmaceuticals", "KW  - clinical trials", "KW  - Ireland", "ER  - ", ""]), encoding="utf-8")

    (staged / "index.html").write_text(_index_html(datasets, now), encoding="utf-8")
    (staged / ".htaccess").write_text(HTACCESS, encoding="utf-8")

    if dist.exists():
        shutil.rmtree(dist)
    staged.rename(dist)
    return {"dist": str(dist), "datasets": len(datasets), "records": sum(d["records"] for d in datasets),
            "held": sorted(k for k in held if k in ALL)}
