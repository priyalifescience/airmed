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
"""

import datetime as dt
import hashlib
import json
import shutil
from pathlib import Path

from . import __version__
from .collectors import ALL
from .privacy import EMAIL_RE, PHONE_RE
from .registry import approved_source

BASE_URL = "https://priyalifescience.com/opendata/airmid/v1/"
MAX_SHRINK = 0.20


class ReleaseRefused(Exception):
    pass


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _recheck(records: list, key: str) -> None:
    """Second, independent privacy pass over what is about to be published."""
    for r in records:
        for k, v in r.items():
            for s in (v if isinstance(v, list) else [v]):
                if isinstance(s, str) and (EMAIL_RE.search(s) or (not s.startswith("http") and PHONE_RE.search(s))):
                    raise ReleaseRefused(f"{key}.{k}: contact-like value found at release time")


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

    for key, mod in ALL.items():
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
        datasets.append({
            "key": key,
            "title": source["name"],
            "publisher": source["publisher"],
            "licence": source["licence"],
            "licence_url": source["licence_url"],
            "attribution": source["attribution"],
            "source_endpoint": source["endpoint"],
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
        "note": "Each dataset keeps the licence of its source. Credit the source and Airmid Éireann. Not medical advice.",
        "datasets": datasets,
    }
    (staged / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=1), encoding="utf-8")

    dd = ["# Airmid Éireann: data dictionary", "", f"Release {now}. Every field of every dataset.", ""]
    for d in datasets:
        dd += [f"## `{d['key']}`: {d['title']}", "", f"Publisher: {d['publisher']}. Licence: [{d['licence']}]({d['licence_url']}).",
               f"Attribution: {d['attribution']}", f"Records: {d['records']:,}", "", "| Field | Description |", "|---|---|"]
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
        "Each dataset keeps the licence of its source, listed in `catalog.json`. Please credit the original source and",
        '"Airmid Éireann, Priya Life Science". Nothing here is medical advice.', "", "## Cite", "",
        f"Priya Life Science ({now[:4]}). Airmid Éireann: Ireland's Open Pharma Data Project. {base_url}catalog.json", "",
    ]
    (staged / "README.md").write_text("\n".join(readme), encoding="utf-8")
    (staged / "CHANGELOG.md").write_text("\n".join([f"# Release {now}", "", "| Dataset | Previous records | Records |", "|---|---|---|", *changes, ""]),
                                         encoding="utf-8")

    if dist.exists():
        shutil.rmtree(dist)
    staged.rename(dist)
    return {"dist": str(dist), "datasets": len(datasets), "records": sum(d["records"] for d in datasets)}
