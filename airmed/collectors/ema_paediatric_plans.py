"""EMA: decisions on paediatric investigation plans (PIPs), waivers and modifications, from EMA's JSON report.

The source's "contact for public enquiries" field mixes a company name with email addresses and phone numbers.
Only the leading organisation name is kept, and only when it is clearly a company or institution; e-mails,
phone numbers and anything that might be a person are never kept.
"""

import json
import re

from ..http import fetch
from ..util import iso_date

KEY = "ema_paediatric_plans"
FIELDS = ["decision_number", "pip_number", "active_substance", "invented_name", "condition_indication",
          "therapeutic_area", "pharmaceutical_forms", "routes_of_administration", "decision_type_code",
          "decision_type", "decision_date", "compliance_outcome", "compliance_opinion_date",
          "compliance_procedure_number", "organisation", "url", "first_published", "last_updated"]
URL = "https://www.ema.europa.eu/en/documents/report/medicines-output-paediatric_investigation_plans-output-json-report_en.json"
MIN_RECORDS = 2500

# where the organisation name ends in the free-text enquiries field
_STOP = re.compile(
    r"\s*(?:;|,?\s*(?:E-?\s?mail|Email|Tel\b|Tel\.|Telephone|Phone|Fax|Country|Address|Web|www\.|c/o\b)"
    r"|(?:^|(?<=[\s;,]))[^\s;,]+@|\+\s?\d|&nbsp)", re.I)
# the name must carry a company / institution marker to be kept
_ORG = re.compile(
    r"(?<![\w])(?:ltd|limited|gmbh|mbh|inc|ag|a/s|asa|as|ab|bv|b\.v\.?|nv|n\.v\.?|s\.?a\.?|sas|s\.?p\.?a\.?|"
    r"s\.?r\.?l\.?|plc|llc|llp|lp|eeig|kg|kgaa|oy|oyj|aps|uab|corp|corporation|company|co\.|pharma\w*|laborat\w*|"
    r"therapeutics|bio\w*|institut\w*|universit\w*|foundation|fondazione|stiftung|group|groupe|holding|holdings|"
    r"dac|ulc|s\.l\.u?|sl|k\.k\.?|pty|pte|sarl|gesmbh|se|d\.d\.|d\.o\.o\.?|a\.s\.|zrt|hospital|research|sciences?|"
    r"medical|healthcare|vaccines|regulatory|consult\w*|services|industrie|recherche|alliance|m[ée]dicament)(?![\w])",
    re.I)


def fetch_raw() -> bytes:
    return fetch(URL, timeout=180)


def organisation_or_blank(enquiries: str) -> str:
    """Leading organisation name from the enquiries text, or '' when it is not clearly an organisation."""
    raw = (enquiries or "").replace("\xa0", " ").strip()
    m = _STOP.search(raw)
    name = re.sub(r"\s+", " ", raw[:m.start()] if m else raw).strip(" ;,-:")
    if not name or len(name) > 120 or re.search(r"@|\d{4,}|https?:|www\.", name, re.I):
        return ""
    return name if _ORG.search(name) else ""


def parse(raw: bytes, min_records: int = MIN_RECORDS) -> list:
    data = json.loads(raw)
    rows = data.get("data", [])
    expected = data.get("meta", {}).get("total_records")
    if expected is not None and expected != len(rows):
        raise RuntimeError(f"EMA file says {expected} records but holds {len(rows)}")
    out = []
    for r in rows:
        dtype = (r.get("decision_type") or "").strip()
        code = dtype.split(":", 1)[0].strip() if ":" in dtype else ""
        out.append({
            "decision_number": r.get("decision_number", ""),
            "pip_number": r.get("pip_number", ""),
            "active_substance": r.get("active_substance", ""),
            "invented_name": r.get("invented_name", ""),
            "condition_indication": r.get("condition_indication", ""),
            "therapeutic_area": r.get("therapeutic_area", ""),
            "pharmaceutical_forms": r.get("pharmaceutical_forms", ""),
            "routes_of_administration": r.get("routes_of_administration", ""),
            "decision_type_code": code,
            "decision_type": dtype,
            "decision_date": iso_date(r.get("decision_date", "")),
            "compliance_outcome": r.get("compliance_outcome", ""),
            "compliance_opinion_date": iso_date(r.get("compliance_opinion_date", "")),
            "compliance_procedure_number": r.get("compliance_procedure_number", ""),
            "organisation": organisation_or_blank(r.get("contact_for_public_enquiries", "")),
            "url": r.get("pip_url", ""),
            "first_published": iso_date(r.get("first_published_date", "")),
            "last_updated": iso_date(r.get("last_updated_date", "")),
        })
    if len(out) < min_records:
        raise RuntimeError(f"only {len(out)} PIP decisions; refusing a partial dataset")
    out.sort(key=lambda r: (r["decision_number"], r["pip_number"], r["decision_date"], r["url"]))
    return out
