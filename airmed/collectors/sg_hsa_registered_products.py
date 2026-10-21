"""Singapore Health Sciences Authority (HSA): Listing of Registered Therapeutic Products, from data.gov.sg.

One record per product licence, with the licence holder, every manufacturer and its country of manufacture
(the publisher joins several with '&&'; they are split into lists in the same order), so products made in
Ireland can be counted directly (made_in_ireland). Approval dates are published as D/M/YYYY and are written
here as YYYY-MM-DD. The dataset's own contact metadata is not kept.
"""

import json

from ..http import fetch

KEY = "sg_hsa_registered_products"
FIELDS = ["licence_no", "product_name", "licence_holder", "approval_date", "forensic_classification", "atc_code",
          "dosage_form", "route", "manufacturers", "manufacturer_countries", "made_in_ireland", "active_ingredients",
          "strengths"]
DATASET = "d_767279312753558cbf19d48344577084"
URL = f"https://data.gov.sg/api/action/datastore_search?resource_id={DATASET}&limit=20000"
NEEDED = ["LicenceNo", "Productname", "Licenseholder", "Approvaldate", "Forensicclassification", "ATCCode",
          "Dosageform", "RouteofAdministration", "Manufacturer", "Countryofmanufacturer", "Activeingredients", "Strength"]


def fetch_raw() -> bytes:
    return fetch(URL, timeout=300)


def _split(s) -> list:
    return [p.strip() for p in (s or "").split("&&") if p.strip()]


def _iso(d: str) -> str:
    d = (d or "").strip()
    if not d:
        return ""
    day, month, year = (int(x) for x in d.split("/"))
    if not (1 <= day <= 31 and 1 <= month <= 12 and 1900 < year < 2100):
        raise RuntimeError(f"unexpected HSA approval date {d!r}")
    return f"{year:04d}-{month:02d}-{day:02d}"


def parse(raw: bytes) -> list:
    reply = json.loads(raw)
    if not reply.get("success"):
        raise RuntimeError("data.gov.sg reply was not successful")
    res = reply["result"]
    fields = [f["id"] for f in res.get("fields", [])]
    missing = [c for c in NEEDED if c not in fields]
    if missing:
        raise RuntimeError(f"HSA listing is missing columns {missing}")
    rows = res["records"]
    if len(rows) != res.get("total"):
        raise RuntimeError(f"HSA listing returned {len(rows)} of {res.get('total')} rows; refusing a partial dataset")
    out, seen = [], set()
    for r in rows:
        lic = (r.get("LicenceNo") or "").strip()
        if not lic or lic in seen:
            raise RuntimeError(f"missing or duplicate HSA licence number {lic!r}")
        seen.add(lic)
        countries = _split(r.get("Countryofmanufacturer"))
        out.append({"licence_no": lic, "product_name": (r.get("Productname") or "").strip(),
                    "licence_holder": (r.get("Licenseholder") or "").strip(), "approval_date": _iso(r.get("Approvaldate")),
                    "forensic_classification": (r.get("Forensicclassification") or "").strip(),
                    "atc_code": (r.get("ATCCode") or "").strip(), "dosage_form": (r.get("Dosageform") or "").strip(),
                    "route": (r.get("RouteofAdministration") or "").strip(),
                    "manufacturers": _split(r.get("Manufacturer")), "manufacturer_countries": countries,
                    "made_in_ireland": "yes" if any(c.upper() == "IRELAND" for c in countries) else "no",
                    "active_ingredients": _split(r.get("Activeingredients")), "strengths": _split(r.get("Strength"))})
    out.sort(key=lambda x: x["licence_no"])
    return out
