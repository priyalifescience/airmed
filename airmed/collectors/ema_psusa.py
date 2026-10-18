"""EMA: outcomes of periodic safety update report single assessments (PSUSAs), from EMA's JSON report."""

import json

from ..http import fetch
from ..util import iso_date

KEY = "ema_psusa"
FIELDS = ["procedure_number", "active_substances_in_scope", "active_substance", "related_medicines",
          "regulatory_outcome", "url", "first_published", "last_updated"]
URL = ("https://www.ema.europa.eu/en/documents/report/"
       "medicines-output-periodic_safety_update_report_single_assessments-output-json-report_en.json")
MIN_RECORDS = 2000


def fetch_raw() -> bytes:
    return fetch(URL, timeout=120)


def parse(raw: bytes, min_records: int = MIN_RECORDS) -> list:
    data = json.loads(raw)
    rows = data.get("data", [])
    expected = data.get("meta", {}).get("total_records")
    if expected is not None and expected != len(rows):
        raise RuntimeError(f"EMA file says {expected} records but holds {len(rows)}")
    out = []
    for r in rows:
        if r.get("category") not in ("Human", "", None):    # PSUSAs are a human-medicines procedure
            continue
        out.append({
            "procedure_number": r.get("procedure_number", ""),
            "active_substances_in_scope": r.get("active_substances_in_scope_of_procedure", ""),
            "active_substance": r.get("active_substance", ""),
            "related_medicines": r.get("related_medicines", ""),
            "regulatory_outcome": r.get("regulatory_outcome", ""),
            "url": r.get("psusa_url", ""),
            "first_published": iso_date(r.get("first_published_date", "")),
            "last_updated": iso_date(r.get("last_updated_date", "")),
        })
    if len(out) < min_records:
        raise RuntimeError(f"only {len(out)} PSUSA outcomes; refusing a partial dataset")
    out.sort(key=lambda r: (r["procedure_number"], r["url"]))
    return out
