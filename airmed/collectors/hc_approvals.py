"""Health Canada Notice of Compliance: approvals of New Drug Submissions (NDS) for human medicines since 2016,
with the brand names and medicinal ingredients of each.
"""

import json

from ..http import fetch

KEY = "hc_approvals"
FIELDS = ["noc_number", "noc_date", "company", "submission_type", "submission_class", "product_type",
          "therapeutic_class", "brand_names", "ingredients", "with_conditions"]
BASE = "https://health-products.canada.ca/api/notice-of-compliance/"
SINCE = "2016-01-01"


def fetch_raw() -> bytes:
    parts = {}
    for name in ("noticeofcompliancemain", "drugproduct", "medicinalingredient"):
        parts[name] = json.loads(fetch(f"{BASE}{name}/?lang=en&type=json", timeout=300))
    return json.dumps(parts).encode("utf-8")


def parse(raw: bytes) -> list:
    parts = json.loads(raw)
    keep = {}
    for r in parts["noticeofcompliancemain"]:
        if r.get("noc_is_admin") == "Y" or r.get("noc_product_type") == "Veterinary":
            continue
        if r.get("noc_on_submission_type") != "New Drug Submission (NDS)" or (r.get("noc_date") or "") < SINCE:
            continue
        n = int(r["noc_number"])
        keep[n] = {"noc_number": n, "noc_date": r.get("noc_date", ""), "company": (r.get("noc_manufacturer_name") or "").strip(),
                   "submission_type": "NDS", "submission_class": r.get("noc_submission_class", ""),
                   "product_type": r.get("noc_product_type", ""), "therapeutic_class": (r.get("noc_therapeutic_class") or "").strip(),
                   "brand_names": [], "ingredients": [], "with_conditions": "yes" if r.get("noc_status_with_conditions") == "Y" else "no"}
    for p in parts["drugproduct"]:
        n = int(p.get("noc_number", 0))
        b = (p.get("noc_br_brandname") or "").strip()
        if n in keep and b and b not in keep[n]["brand_names"]:
            keep[n]["brand_names"].append(b)
    for i in parts["medicinalingredient"]:
        n = int(i.get("noc_number", 0))
        g = (i.get("noc_pi_medic_ingr_name") or "").strip()
        if n in keep and g and g not in keep[n]["ingredients"]:
            keep[n]["ingredients"].append(g)
    if len(keep) < 300:
        raise RuntimeError(f"only {len(keep)} NDS approvals since {SINCE}; refusing a partial dataset")
    return sorted(keep.values(), key=lambda r: (r["noc_date"], r["noc_number"]), reverse=True)
