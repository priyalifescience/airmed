"""US FDA drug shortages (openFDA). One row per affected package.

The source's company phone field (`contact_info`) is never requested or kept.
"""

import json

from ..http import fetch
from ..util import us_date

KEY = "fda_shortages"
FIELDS = ["package_ndc", "generic_name", "company_name", "presentation", "dosage_form", "therapeutic_category",
          "status", "availability", "shortage_reason", "initial_posting_date", "update_date", "discontinued_date"]
API = "https://api.fda.gov/drug/shortages.json?limit=1000&skip={skip}"


def fetch_raw(max_pages: int = 20) -> bytes:
    results, total = [], None
    for page in range(max_pages):
        j = json.loads(fetch(API.format(skip=page * 1000), timeout=120))
        if total is None:
            total = j["meta"]["results"]["total"]
        results.extend(j.get("results", []))
        if len(results) >= total:
            break
    if len(results) != total:
        raise RuntimeError(f"openFDA returned {len(results)} of {total} shortage records")
    return json.dumps({"total": total, "results": results}).encode("utf-8")


def parse(raw: bytes) -> list:
    data = json.loads(raw)
    out = [{
        "package_ndc": r.get("package_ndc", ""),
        "generic_name": r.get("generic_name", ""),
        "company_name": r.get("company_name", ""),
        "presentation": r.get("presentation", ""),
        "dosage_form": r.get("dosage_form") or "",
        "therapeutic_category": list(r.get("therapeutic_category") or []),
        "status": r.get("status", ""),
        "availability": r.get("availability") or "",
        "shortage_reason": r.get("shortage_reason") or "",
        "initial_posting_date": us_date(r.get("initial_posting_date", "")),
        "update_date": us_date(r.get("update_date", "")),
        "discontinued_date": us_date(r.get("discontinued_date") or ""),
    } for r in data.get("results", [])]
    out.sort(key=lambda r: (r["generic_name"].lower(), r["package_ndc"]))
    return out
