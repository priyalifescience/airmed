"""Package a release as one zip for a citable DATA deposit (Zenodo "dataset"), separate from the software DOI.

    python tools/data_archive.py --dist dist/v1 --out archives

Writes archives/airmid-eireann-data-<YYYY-MM-DD>.zip containing every dataset's CSV + datapackage.json, the
catalog, data dictionary, changelog, README, citation files, DCAT metadata and the medicine cross-reference, plus
archives/zenodo-data-metadata-<date>.json: the deposit description to paste (or send through the Zenodo API) by
the account owner. JSON copies and the search index are left out: they are derived from the CSVs.
"""

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

DOCS = ["catalog.json", "DATA_DICTIONARY.md", "CHANGELOG.md", "README.md", "citation.bib", "citation.ris",
        "dcat.jsonld", "dcat.ttl", "links/medicine_links.csv", "links/medicine_links.json"]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", default="dist/v1")
    ap.add_argument("--out", default="archives")
    a = ap.parse_args(argv)
    dist, out = Path(a.dist), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    catalog = json.loads((dist / "catalog.json").read_text(encoding="utf-8"))
    day = catalog["release"][:10]
    zpath = out / f"airmid-eireann-data-{day}.zip"
    manifest = []
    with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for d in catalog["datasets"]:
            for name in (f"{d['key']}.csv", "datapackage.json"):
                p = dist / d["key"] / name
                if p.exists():
                    z.write(p, f"{d['key']}/{name}")
                    manifest.append((f"{d['key']}/{name}", hashlib.sha256(p.read_bytes()).hexdigest()))
        for rel in DOCS:
            p = dist / rel
            if p.exists():
                z.write(p, rel)
                manifest.append((rel, hashlib.sha256(p.read_bytes()).hexdigest()))
        z.writestr("SHA256SUMS.txt", "".join(f"{h}  {n}\n" for n, h in manifest))
    total = sum(int(d.get("records", 0)) for d in catalog["datasets"])
    sources = sorted({d["publisher"].split(",")[0].split(" (")[0] for d in catalog["datasets"]})
    meta = {"metadata": {
        "upload_type": "dataset",
        "title": f"Airmid Éireann open pharma data, release of {day}",
        "creators": [{"name": "Priya Life Science"}],
        "description": (
            f"<p>{len(catalog['datasets'])} open datasets ({total:,} records) on medicines, clinical trials, approvals, "
            "shortages, safety, trade, spending and research for Ireland and Europe, collected from official publishers "
            "and released with their source licences, a data dictionary, checksums and DCAT-AP metadata.</p>"
            "<p>Each dataset keeps the licence of its source (listed in catalog.json and each datapackage.json); "
            "Priya Life Science's own compilation and cross-reference are CC BY 4.0. No personal names or contact "
            "details are included.</p><p>Sources: " + "; ".join(sources) + ".</p>"
            "<p>Live, weekly-updated copy: https://priyalifescience.com/opendata/airmid/v1/ . "
            "Code (software DOI 10.5281/zenodo.23336432): https://github.com/priyalifescience/airmed</p>"),
        "license": "cc-by-4.0",
        "notes": "Mixed licences: CC BY 4.0 applies to the compilation; each dataset's own source licence applies to "
                 "its records (see catalog.json). Not medical advice.",
        "keywords": ["open data", "pharmaceuticals", "medicines", "clinical trials", "Ireland", "Europe",
                     "drug shortages", "regulatory approvals"],
        "related_identifiers": [
            {"identifier": "10.5281/zenodo.23336432", "relation": "isSupplementedBy", "scheme": "doi"},
            {"identifier": "https://priyalifescience.com/airmed", "relation": "isDocumentedBy", "scheme": "url"}],
        "publication_date": day,
        "version": day,
        "language": "eng",
    }}
    mpath = out / f"zenodo-data-metadata-{day}.json"
    mpath.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"archive: {zpath} ({zpath.stat().st_size / 1e6:.1f} MB, {len(manifest)} files); metadata: {mpath}")


if __name__ == "__main__":
    main()
