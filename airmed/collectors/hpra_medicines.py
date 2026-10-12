"""HPRA list of human medicines authorised in Ireland (XML, CC BY 4.0)."""

import xml.etree.ElementTree as ET

from ..http import fetch

KEY = "hpra_medicines"
FIELDS = ["licence_number", "product_name", "holder", "authorised_date", "product_type", "market_status",
          "registration_status", "dosage_form", "atc_codes", "active_substances", "routes", "dispensing_status",
          "supply_status", "legal_basis"]
URL = "https://assets.hpra.ie/products/xml/latestHumanlist.xml"
MIN_PRODUCTS = 5000  # the list has ~10,000 products; far fewer means a broken download


def fetch_raw() -> bytes:
    return fetch(URL, timeout=180)


def _iso(d: str) -> str:
    # HPRA dates are dd/mm/yyyy
    parts = d.split("/")
    return f"{parts[2]}-{parts[1]}-{parts[0]}" if len(parts) == 3 else d


def parse(raw: bytes, min_products: int = MIN_PRODUCTS) -> list:
    root = ET.fromstring(raw)  # the stdlib parser does not fetch external entities
    ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""

    def t(el, name):
        x = el.find(ns + name)
        return (x.text or "").strip() if x is not None and x.text else ""

    def many(el, path):
        return [x.text.strip() for x in el.findall(_ns_path(ns, path)) if x.text and x.text.strip()]

    out = []
    for p in root.findall(ns + "Product"):
        out.append({
            "licence_number": t(p, "LicenceNumber"),
            "product_name": t(p, "ProductName"),
            "holder": t(p, "PAHolder"),
            "authorised_date": _iso(t(p, "AuthorisedDate")),
            "product_type": t(p, "ProductType"),
            "market_status": t(p, "MarketInfo"),
            "registration_status": t(p, "RegistrationStatus"),
            "dosage_form": t(p, "DosageForm"),
            "atc_codes": many(p, "ATCs/ATC"),
            "active_substances": many(p, "ActiveSubstances/ActiveSubstance"),
            "routes": many(p, "RoutesOfAdministration/RoutesOfAdministration"),
            "dispensing_status": many(p, "DispensingLegalStatus/Status"),
            "supply_status": t(p, "SupplyLegalStatus"),
            "legal_basis": t(p, "LegalBasis"),
        })
    if len(out) < min_products:
        raise RuntimeError(f"HPRA list holds only {len(out)} products; refusing a partial dataset")
    out.sort(key=lambda r: r["licence_number"])
    return out


def _ns_path(ns: str, path: str) -> str:
    return "/".join(ns + part for part in path.split("/"))
