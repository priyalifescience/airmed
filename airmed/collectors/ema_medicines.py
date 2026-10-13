"""EMA: human medicines evaluated by the European Medicines Agency (centralised procedure), all statuses.

Product information text (indications, SmPC) is deliberately not collected: it belongs to its publishers.
"""

import json

from ..http import fetch
from ..util import iso_date, split_list, yes

KEY = "ema_medicines"
FIELDS = ["ema_product_number", "medicine_name", "inn", "active_substance", "status", "holder", "atc_code",
          "therapeutic_area", "authorisation_date", "orphan", "biosimilar", "generic", "conditional_approval",
          "exceptional_circumstances", "accelerated_assessment", "prime", "advanced_therapy", "additional_monitoring",
          "url", "last_updated"]
URL = "https://www.ema.europa.eu/en/documents/report/medicines-output-medicines_json-report_en.json"
MIN_RECORDS = 1500


def fetch_raw() -> bytes:
    return fetch(URL, timeout=180)


def parse(raw: bytes, min_records: int = MIN_RECORDS) -> list:
    data = json.loads(raw)
    rows = data.get("data", [])
    expected = data.get("meta", {}).get("total_records")
    if expected is not None and expected != len(rows):
        raise RuntimeError(f"EMA file says {expected} records but holds {len(rows)}")
    out = []
    for r in rows:
        if r.get("category") != "Human":
            continue
        out.append({
            "ema_product_number": r.get("ema_product_number", ""),
            "medicine_name": r.get("name_of_medicine", ""),
            "inn": r.get("international_non_proprietary_name_common_name", ""),
            "active_substance": r.get("active_substance", ""),
            "status": r.get("medicine_status", ""),
            "holder": r.get("marketing_authorisation_developer_applicant_holder", ""),
            "atc_code": r.get("atc_code_human", ""),
            "therapeutic_area": split_list(r.get("therapeutic_area_mesh", "")),
            "authorisation_date": iso_date(r.get("marketing_authorisation_date", "")),
            "orphan": yes(r.get("orphan_medicine")),
            "biosimilar": yes(r.get("biosimilar")),
            "generic": yes(r.get("generic")),
            "conditional_approval": yes(r.get("conditional_approval")),
            "exceptional_circumstances": yes(r.get("exceptional_circumstances")),
            "accelerated_assessment": yes(r.get("accelerated_assessment")),
            "prime": yes(r.get("prime_priority_medicine")),
            "advanced_therapy": yes(r.get("advanced_therapy")),
            "additional_monitoring": yes(r.get("additional_monitoring")),
            "url": r.get("medicine_url", ""),
            "last_updated": iso_date(r.get("last_updated_date", "")),
        })
    if len(out) < min_records:
        raise RuntimeError(f"only {len(out)} human medicines; refusing a partial dataset")
    out.sort(key=lambda r: (r["ema_product_number"], r["medicine_name"]))
    return out
