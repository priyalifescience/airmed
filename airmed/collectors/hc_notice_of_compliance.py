"""Health Canada Notice of Compliance (NOC) database: every human-medicine NOC since 1994, for all four submission
types (NDS new drugs, SNDS supplements such as new indications, ANDS generics, SANDS generic supplements), with
brand names, DINs, medicinal ingredients with strengths, the supplement reason and, for generics, the Canadian
reference product.

This is the full history behind hc_approvals (which keeps only NDS approvals since 2016). Administrative NOCs
(for example a manufacturer name change) and veterinary products are left out.
"""

import json

from ..http import fetch

KEY = "hc_notice_of_compliance"
FIELDS = ["noc_number", "noc_date", "company", "submission_type", "is_supplement", "submission_class", "product_type",
          "therapeutic_class", "reason_supplement", "reason_submission", "with_conditions", "brand_names", "dins",
          "ingredients", "reference_product", "reference_company", "reference_country"]
BASE = "https://health-products.canada.ca/api/notice-of-compliance/"
TYPES = {"New Drug Submission (NDS)": "NDS", "Supplement to a New Drug Submission (SNDS)": "SNDS",
         "Abbreviated New Drug Submission (ANDS)": "ANDS",
         "Supplement to an Abbreviated New Drug Submission (SANDS)": "SANDS"}


def fetch_raw() -> bytes:
    parts = {}
    for name in ("noticeofcompliancemain", "drugproduct", "medicinalingredient"):
        parts[name] = json.loads(fetch(f"{BASE}{name}/?lang=en&type=json", timeout=300))
    return json.dumps(parts).encode("utf-8")


def _s(v) -> str:
    return (v or "").strip() if isinstance(v, str) else ("" if v is None else str(v))


def _strength(i: dict) -> str:
    s = i.get("noc_pi_strength")
    if s in (None, ""):
        return ""
    if isinstance(s, float) and s.is_integer():
        s = int(s)
    unit = _s(i.get("noc_pi_unit"))
    per = _s(i.get("noc_pi_basic_unit"))
    return " ".join(x for x in (str(s), unit) if x) + (f" per {per}" if per else "")


def parse(raw: bytes) -> list:
    parts = json.loads(raw)
    keep = {}
    for r in parts["noticeofcompliancemain"]:
        if r.get("noc_is_admin") == "Y" or r.get("noc_product_type") == "Veterinary":
            continue
        t = r.get("noc_on_submission_type")
        if t not in TYPES:
            raise RuntimeError(f"unknown NOC submission type {t!r}")
        n = int(r["noc_number"])
        keep[n] = {"noc_number": n, "noc_date": _s(r.get("noc_date")), "company": _s(r.get("noc_manufacturer_name")),
                   "submission_type": TYPES[t], "is_supplement": "yes" if r.get("noc_is_suppliment") == "Y" else "no",
                   "submission_class": _s(r.get("noc_submission_class")), "product_type": _s(r.get("noc_product_type")),
                   "therapeutic_class": _s(r.get("noc_therapeutic_class")),
                   "reason_supplement": _s(r.get("noc_reason_supplement")),
                   "reason_submission": _s(r.get("noc_reason_submission")),
                   "with_conditions": "yes" if r.get("noc_status_with_conditions") == "Y" else "no",
                   "brand_names": [], "dins": [], "ingredients": [],
                   "reference_product": _s(r.get("noc_crp_product_name")),
                   "reference_company": _s(r.get("noc_crp_company_name")),
                   "reference_country": _s(r.get("noc_crp_country_name"))}
    for p in parts["drugproduct"]:
        n = int(p.get("noc_number") or 0)
        if n not in keep:
            continue
        b, din = _s(p.get("noc_br_brandname")), _s(p.get("noc_br_din"))
        if b and b not in keep[n]["brand_names"]:
            keep[n]["brand_names"].append(b)
        if din and din not in keep[n]["dins"]:
            keep[n]["dins"].append(din)
    for i in parts["medicinalingredient"]:
        n = int(i.get("noc_number") or 0)
        g = _s(i.get("noc_pi_medic_ingr_name"))
        if n not in keep or not g:
            continue
        s = _strength(i)
        g = f"{g} {s}" if s else g
        if g not in keep[n]["ingredients"]:
            keep[n]["ingredients"].append(g)
    if len(parts["noticeofcompliancemain"]) > 1000 and len(keep) < 20000:
        raise RuntimeError(f"only {len(keep)} NOCs; refusing a partial dataset")
    for r in keep.values():
        r["dins"].sort()
    return sorted(keep.values(), key=lambda r: (r["noc_date"], r["noc_number"]), reverse=True)
