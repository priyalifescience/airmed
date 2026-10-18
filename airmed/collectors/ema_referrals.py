"""EMA: referral procedures for human medicines (safety, efficacy and harmonisation referrals), from EMA's JSON report.

Veterinary referrals in the same file are left out, as in the other EMA collectors.
"""

import json

from ..http import fetch
from ..util import iso_date

KEY = "ema_referrals"
FIELDS = ["reference_number", "referral_name", "inn", "referral_type", "safety_referral", "status",
          "authorisation_model", "therapeutic_class", "prac_recommendation", "centrally_authorised_medicines",
          "procedure_start_date", "prac_recommendation_date", "cmdh_position_date", "chmp_opinion_date",
          "ec_decision_date", "url", "first_published", "last_updated"]
URL = "https://www.ema.europa.eu/en/documents/report/referrals-output-json-report_en.json"
MIN_RECORDS = 350


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
        if r.get("category") != "Human":
            continue
        cls = (r.get("class") or "").strip()
        out.append({
            "reference_number": r.get("reference_number", ""),
            "referral_name": r.get("referral_name", ""),
            "inn": r.get("international_non_proprietary_name_inn_common_name", ""),
            "referral_type": r.get("referral_type", ""),
            "safety_referral": (r.get("safety_referral") or "").strip().lower(),
            "status": r.get("current_status", ""),
            "authorisation_model": r.get("authorisation_model", ""),
            "therapeutic_class": "" if cls == "-" else cls,
            "prac_recommendation": r.get("prac_recommendation", ""),
            "centrally_authorised_medicines": r.get("associated_names_centrally_authorised_medicines", ""),
            "procedure_start_date": iso_date(r.get("procedure_start_date", "")),
            "prac_recommendation_date": iso_date(r.get("prac_recommendation_date", "")),
            "cmdh_position_date": iso_date(r.get("cmdh_position_date", "")),
            "chmp_opinion_date": iso_date(r.get("chmp_cvmp_opinion_date", "")),
            "ec_decision_date": iso_date(r.get("european_commission_decision_date", "")),
            "url": r.get("referral_url", ""),
            "first_published": iso_date(r.get("first_published_date", "")),
            "last_updated": iso_date(r.get("last_updated_date", "")),
        })
    if len(out) < min_records:
        raise RuntimeError(f"only {len(out)} human referrals; refusing a partial dataset")
    out.sort(key=lambda r: (r["reference_number"], r["url"]))
    return out
