"""EMA medicine shortages (human medicines), from the EMA website data in JSON."""

import json

from ..http import fetch

KEY = "ema_shortages"
FIELDS = ["medicine", "inn", "status", "therapeutic_area", "forms", "strengths", "alternatives_available",
          "start_date", "expected_resolution", "first_published", "last_updated", "url"]
URL = "https://www.ema.europa.eu/en/documents/report/shortages-output-json-report_en.json"


def fetch_raw() -> bytes:
    return fetch(URL)


def parse(raw: bytes) -> list:
    data = json.loads(raw)
    rows = data.get("data", [])
    expected = data.get("meta", {}).get("total_records")
    if expected is not None and expected != len(rows):
        raise RuntimeError(f"EMA file says {expected} records but holds {len(rows)}")
    out = []
    for r in rows:
        if r.get("category", "Human") != "Human":
            continue
        out.append({
            "medicine": r.get("medicine_affected", ""),
            "inn": r.get("international_non_proprietary_name_inn_or_common_name", ""),
            "status": r.get("supply_shortage_status", ""),
            "therapeutic_area": [t.strip() for t in (r.get("therapeutic_area_mesh") or "").split(";") if t.strip()],
            "forms": r.get("pharmaceutical_forms_affected", ""),
            "strengths": r.get("strengths_affected", ""),
            "alternatives_available": r.get("availability_of_alternatives", ""),
            "start_date": r.get("start_of_shortage_date", ""),
            "expected_resolution": r.get("expected_resolution_date") or r.get("expected_resolution", ""),
            "first_published": r.get("first_published_date", ""),
            "last_updated": r.get("last_updated_date", ""),
            "url": r.get("shortage_url", ""),
        })
    out.sort(key=lambda r: (r["medicine"].lower(), r["url"]))
    return out
