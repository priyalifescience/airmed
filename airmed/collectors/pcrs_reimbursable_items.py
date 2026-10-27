"""Ireland (HSE-PCRS): items reimbursed under the State schemes, with the reimbursement price and reference price.

Source: the HSE Primary Care Reimbursement Service "Search Reimbursable Items" page (https://www.sspcrs.ie/druglist/pub).
The page's Download button exports each list as CSV from /druglist/search/category/{n}.csv; this collector reads the
same files, with no login, cookie or token: the full list ("All Items", category 0) and the eight lists it is split
into (Drugs, Diagnostic Agents, Dressings, Clinical Nutritional Products, Ostomy Appliances, Urinary Appliances,
Syringes Needles and Lancets, High Tech Drugs).

One row per PCRS item code, from the full list, with `categories` naming every list the code appears on (an item can be
on more than one: nearly every High Tech drug is also on the Drugs list). About 2% of items are on the full list only;
their `categories` is empty.

Prices are in euro as published. The High Tech Drugs list publishes no price (it shows 0.0): those medicines are paid
for through the separate High Tech arrangement, so a published 0.0 is kept as blank, never as a price of zero. A
reference price of 0.0 (the item is not reference priced) is also kept as blank.

The lists hold no personal data. Permission: PCRS wrote on 6 October 2026 that the data may be downloaded from its
website and published, provided the source is referenced; PCRS takes no responsibility for what is published.
"""

import csv
import io
import json
import re

from ..http import fetch

KEY = "pcrs_reimbursable_items"
FIELDS = ["code", "item", "name", "pack_size", "strength", "inn", "reimbursement_price_eur", "reference_price_eur",
          "reference_priced", "dental", "categories"]
URL = "https://www.sspcrs.ie/druglist/search/category/{}.csv"
ALL = 0
CATEGORIES = {1: "Drugs", 3: "Diagnostic Agents", 4: "Dressings", 5: "Clinical Nutritional Products",
              6: "Ostomy Appliances", 7: "Urinary Appliances", 8: "Syringes, Needles and Lancets", 9: "High Tech Drugs"}
COLUMNS = ["Code", "Drug Name", "Pack Size", "Strength Measure", "Name", "Reimbursement Price", "Non Proprietary Name",
           "Ref Price", "Dental", "Reference Priced", "INN"]
MIN_ROWS = 6000


def fetch_raw() -> bytes:
    """The full list and each category list as one JSON object {category number: CSV text}."""
    return json.dumps({str(c): fetch(URL.format(c), timeout=180).decode("utf-8-sig")
                       for c in [ALL, *CATEGORIES]}).encode("utf-8")


def _rows(text: str, label: str) -> list:
    rows = list(csv.DictReader(io.StringIO(text)))
    if rows and list(rows[0]) != COLUMNS:
        raise RuntimeError(f"PCRS {label}: unexpected columns {list(rows[0])}")
    return rows


def _price(v: str) -> str:
    v = (v or "").strip()
    if not v:
        return ""
    if not re.fullmatch(r"\d+(\.\d+)?", v):
        raise RuntimeError(f"PCRS: unexpected price {v!r}")
    return "" if float(v) == 0 else v   # as published, except 0.0 (no price on this list)


def _yn(v: str) -> str:
    v = (v or "").strip().upper()
    return {"Y": "yes", "N": "no"}.get(v, v.lower())


def parse(raw: bytes, min_rows: int = MIN_ROWS) -> list:
    lists = json.loads(raw)
    missing = [str(c) for c in [ALL, *CATEGORIES] if str(c) not in lists]
    if missing:
        raise RuntimeError(f"PCRS: lists missing from download: {missing}")
    member = {}
    for c, name in CATEGORIES.items():
        for r in _rows(lists[str(c)], name):
            member.setdefault(r["Code"].strip(), []).append(name)
    out, seen = [], set()
    for r in _rows(lists[str(ALL)], "All Items"):
        code = r["Code"].strip()
        if not re.fullmatch(r"\d{2,7}", code):
            raise RuntimeError(f"PCRS: unexpected item code {code!r}")
        if code in seen:
            continue
        seen.add(code)
        out.append({
            "code": code,
            "item": r["Drug Name"].strip(),
            "name": r["Name"].strip(),
            "pack_size": r["Pack Size"].strip(),
            "strength": r["Strength Measure"].strip(),
            "inn": r["INN"].strip(),
            "reimbursement_price_eur": _price(r["Reimbursement Price"]),
            "reference_price_eur": _price(r["Ref Price"]),
            "reference_priced": _yn(r["Reference Priced"]),
            "dental": _yn(r["Dental"]),
            "categories": "; ".join(sorted(member.get(code, []), key=list(CATEGORIES.values()).index)),
        })
    if len(out) < min_rows:
        raise RuntimeError(f"PCRS: only {len(out)} items (expected at least {min_rows}); broken download?")
    out.sort(key=lambda x: (x["item"].lower(), x["code"]))
    return out
