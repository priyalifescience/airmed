"""Switzerland (FOPH/BAG): the Specialities List (Spezialitaetenliste), medicines paid for by compulsory health insurance.

Source: the public API behind https://www.sl.bag.admin.ch (no login, cookie or token). Paged, 100 trademarks a page.

One row per listed pack, with its ex-factory and retail price in Swiss francs as published. The limitation texts
(long rules on who may be prescribed a medicine) are not kept, only whether a limitation applies.

Permission: Co-Head Section Medicines Law (Pharma Pricing), FOPH, wrote on 4 November 2026 that the list holds
no personal data, that it is not protected by copyright as a published official document (Article 5 of the Swiss
Copyright Act) and that the data are freely available for use for Airmid.
"""

import json

from ..http import fetch

KEY = "ch_specialities_list"
FIELDS = ["trademark", "dosage_form_strength", "substances", "atc", "marketing_authorisation_holder", "product_type",
          "it_code", "it_group", "cost_share_pct", "pack_size", "gtin", "ex_factory_price_chf", "retail_price_chf",
          "supply_category", "list_type", "limitation", "first_listed", "valid_from", "valid_to", "last_price_change",
          "last_price_change_type", "marketing_authorisation_numbers", "foph_dossier_number"]
URL = "https://epl.bag.admin.ch/api/sl/public/medicinal-products?page={}&size=100"
MIN_ROWS = 7000


def fetch_raw() -> bytes:
    items, page = [], 1
    while True:
        reply = json.loads(fetch(URL.format(page), timeout=120))
        items.extend(reply["items"])
        if not reply["items"] or len(items) >= reply["total"]:
            total = reply["total"]
            break
        page += 1
    if len(items) != total:
        raise RuntimeError(f"BAG: {len(items)} trademarks downloaded, the API says {total}")
    return json.dumps({"total": total, "items": items}, ensure_ascii=False).encode("utf-8")


def _text(v) -> str:
    return "" if v is None else str(v).strip()


def _yes_no(v) -> str:
    return {True: "yes", False: "no"}.get(v, "")


def _holder(v) -> str:
    return _text(v.get("name")) if isinstance(v, dict) else _text(v)


def _substance(v) -> str:
    return _text(v.get("substance") or v.get("name")) if isinstance(v, dict) else _text(v)


def parse(raw: bytes, min_rows: int = MIN_ROWS) -> list:
    out = []
    for item in json.loads(raw)["items"]:
        for mp in item["medicinalProducts"]:
            code = mp.get("itCode") or {}
            names = [_substance(s) for s in mp.get("ingredients") or []] or [_substance(s) for s in item.get("substances") or []]
            for pack in mp["packagedMedicinalProducts"]:
                out.append({
                    "trademark": _text(mp.get("trademark") or item.get("trademark")),
                    "dosage_form_strength": _text(mp.get("dosageFormAndStrength")),
                    "substances": "; ".join(dict.fromkeys(n for n in names if n)),
                    "atc": _text(item.get("atcCode")),
                    "marketing_authorisation_holder": _holder(item.get("marketingAuthorisationHolder")),
                    "product_type": _text(mp.get("productType")),
                    "it_code": _text(code.get("code")),
                    "it_group": _text(code.get("description")),
                    "cost_share_pct": _text(mp.get("costShare")),
                    "pack_size": _text(pack.get("packSize")),
                    "gtin": _text(pack.get("gtin")),
                    "ex_factory_price_chf": _text(pack.get("exFactoryPrice")),
                    "retail_price_chf": _text(pack.get("retailPrice")),
                    "supply_category": _text(pack.get("legalStatusOfSupply")),
                    "list_type": _text(pack.get("listType")),
                    "limitation": _yes_no(pack.get("limitation")),
                    "first_listed": _text(pack.get("firstListed")),
                    "valid_from": _text(pack.get("validFrom")),
                    "valid_to": _text(pack.get("validTo")),
                    "last_price_change": _text(pack.get("lastPriceChange")),
                    "last_price_change_type": _text(pack.get("lastPriceChangeType")),
                    "marketing_authorisation_numbers": "; ".join(_text(n) for n in pack.get("marketingAuthorisationNumbers") or []),
                    "foph_dossier_number": _text(pack.get("fophDossierNumber")),
                })
    if len(out) < min_rows:
        raise RuntimeError(f"BAG: only {len(out)} packs (expected at least {min_rows}); broken download?")
    out.sort(key=lambda r: (r["trademark"].lower(), r["dosage_form_strength"], r["pack_size"], r["gtin"]))
    return out
