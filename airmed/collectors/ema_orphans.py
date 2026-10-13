"""EMA: EU orphan designations (medicines for rare diseases), all statuses."""

import json

from ..http import fetch
from ..util import iso_date

KEY = "ema_orphans"
FIELDS = ["eu_designation_number", "medicine_name", "active_substance", "intended_use", "status",
          "designation_date", "related_ema_product_number", "url", "last_updated"]
URL = "https://www.ema.europa.eu/en/documents/report/medicines-output-orphan_designations-json-report_en.json"
MIN_RECORDS = 2000


def fetch_raw() -> bytes:
    return fetch(URL, timeout=180)


def parse(raw: bytes, min_records: int = MIN_RECORDS) -> list:
    data = json.loads(raw)
    rows = data.get("data", [])
    expected = data.get("meta", {}).get("total_records")
    if expected is not None and expected != len(rows):
        raise RuntimeError(f"EMA file says {expected} records but holds {len(rows)}")
    out = [{
        "eu_designation_number": r.get("eu_designation_number", ""),
        "medicine_name": r.get("medicine_name", ""),
        "active_substance": r.get("active_substance", ""),
        "intended_use": r.get("intended_use", ""),
        "status": r.get("status", ""),
        "designation_date": iso_date(r.get("date_of_designation_or_refusal", "")),
        "related_ema_product_number": r.get("related_ema_product_number", ""),
        "url": r.get("orphan_designation_url", ""),
        "last_updated": iso_date(r.get("last_updated_date", "")),
    } for r in rows]
    if len(out) < min_records:
        raise RuntimeError(f"only {len(out)} orphan designations; refusing a partial dataset")
    out.sort(key=lambda r: (r["eu_designation_number"], r["url"]))
    return out
