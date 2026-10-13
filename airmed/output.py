"""Write a dataset as CSV and JSON, plus a datapackage.json (Frictionless Data) describing source and licence."""

import csv
import datetime as dt
import hashlib
import json
from pathlib import Path


def _cell(v):
    return "; ".join(str(x) for x in v) if isinstance(v, list) else ("" if v is None else v)


def write_dataset(key: str, source: dict, fields: list, records: list, out_dir: Path, stats: dict) -> dict:
    out = Path(out_dir) / key
    out.mkdir(parents=True, exist_ok=True)
    retrieved = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()

    csv_path = out / f"{key}.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="raise")
        w.writeheader()
        for r in records:
            w.writerow({k: _cell(r.get(k)) for k in fields})

    json_path = out / f"{key}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"source": source["name"], "attribution": source["attribution"], "licence": source["licence"],
                   "retrieved": retrieved, "count": len(records), "records": records}, f, ensure_ascii=False, indent=1)

    def sha(p):
        return hashlib.sha256(p.read_bytes()).hexdigest()

    package = {
        "name": key.replace("_", "-"),
        "title": source["name"],
        "description": f"Collected by Airmid Éireann from {source['publisher']}. {source['attribution']}",
        "homepage": "https://priyalifescience.com/airmed",
        "created": retrieved,
        "sources": [{"title": source["publisher"], "path": source["endpoint"]}],
        "licenses": [{"title": source["licence"], "path": source["licence_url"]}],
        "contributors": [{"title": "Priya Life Science (Airmid Éireann)", "role": "publisher"}],
        "resources": [
            {"name": key.replace("_", "-") + "-csv", "path": csv_path.name, "format": "csv", "mediatype": "text/csv",
             "encoding": "utf-8", "hash": "sha256:" + sha(csv_path),
             "schema": {"fields": [{"name": n, "type": "string"} for n in fields]}},
            {"name": key.replace("_", "-") + "-json", "path": json_path.name, "format": "json", "mediatype": "application/json",
             "hash": "sha256:" + sha(json_path)},
        ],
        "airmed": {"records": len(records), "values_blanked_by_privacy_guard": stats.get("blanked", 0),
                   "blanked_by_field": stats.get("by_field", {})},
    }
    with open(out / "datapackage.json", "w", encoding="utf-8") as f:
        json.dump(package, f, ensure_ascii=False, indent=1)
    return {"dir": str(out), "records": len(records), "blanked": stats.get("blanked", 0), "by_field": stats.get("by_field", {})}
