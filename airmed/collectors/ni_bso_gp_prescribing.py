"""Northern Ireland GP prescribing: Northern Ireland totals per month by BNF chemical substance and formulation,
latest 36 published months.

Source: Business Services Organisation (HSC NI), dataset "GP Prescribing Data" on OpenDataNI (CKAN,
https://admin.opendatani.gov.uk/dataset/gp-prescribing-data), one CSV per month since April 2013 (~450,000 rows,
~63 MB each): practice x product (VTM / VMP / AMP names, presentation, strength, 15-character BNF code) with total
items, total quantity, gross cost and actual cost.

Size choice (measured on the August 2026 file): practice-level rows for 12 months would be ~2 GB of JSON, NI totals
per BNF code (product level) ~3.7 MB a month (~134 MB for 36 months), NI totals per VMP (generic product and
strength) ~52 MB for 36 months. All are over the 30 MB budget, so each month is summed to
  BNF chapter / section / paragraph + BNF chemical substance (first 9 characters of the 15-character BNF code)
  + VTM name (the substance as published) + presentation (Tablet, Capsule, Oral solution ...),
which gives ~2,000 rows a month and ~20 MB for 36 months. Strengths and brands of the same substance and
formulation are added together; "products" counts the distinct VMPs summed and "practices" the distinct practices
that prescribed it. Products the source publishes without a VTM ("-": multi-ingredient brands, dressings,
appliances) keep their 9-character BNF chemical substance code with an empty substance name; dressings and
appliances with an 11-digit appliance code (BNF chapters 20-23) are summed per BNF paragraph and presentation with
an empty substance code.

Quantity is the sum of the published Total Quantity (tablets, ml, grams, packs ... as the product is dispensed);
it is only comparable within one substance and presentation (the BSO notes that from August 2021 some inhalers,
sprays and solutions are counted in doses rather than devices). Gross Cost is, in the BSO's words, "the basic price
of a drug, i.e. the price listed in the National Drug Tariff, concessionary price list, or in standard price
lists"; Actual Cost is kept as published (definition in the BSO user guidance, https://gpdatasets.hscni.net/).
The per-month CSV is checked: every data row must carry the month in the resource name, and the summed groups
must add up to the file's own totals.

Practice numbers are organisation codes, but they are not kept at all in this aggregate; no prescriber names exist
in the source.
"""

import collections
import csv
import io
import json
import re

from ..http import fetch

KEY = "ni_bso_gp_prescribing"
FIELDS = ["year", "year_month", "bnf_chapter", "bnf_section", "bnf_paragraph", "bnf_chemical_substance_code",
          "substance", "presentation", "products", "practices", "items", "total_quantity", "gross_cost_gbp",
          "actual_cost_gbp"]
PACKAGE_URL = "https://admin.opendatani.gov.uk/api/3/action/package_show?id=gp-prescribing-data"
MONTHS_KEPT = 36
MIN_GROUPS = 1000      # a real month has ~2,000 groups
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
               "November", "December"]
MONTHS = {m: i for i, m in enumerate(MONTH_NAMES, 1)}
_NAME_RE = re.compile(r"GP Prescribing\W+Northern Ireland\W+(" + "|".join(MONTH_NAMES) + r")\s+(\d{4})\s*$", re.I)


def months_available() -> dict:
    """{'YYYY-MM': download URL} for every monthly CSV in the dataset."""
    j = json.loads(fetch(PACKAGE_URL, timeout=90))
    out = {}
    for r in j.get("result", {}).get("resources", []):
        m = _NAME_RE.search(str(r.get("name") or "").strip())
        if not m or not str(r.get("url", "")).lower().endswith(".csv"):
            continue
        ym = f"{m[2]}-{MONTHS[m[1].capitalize()]:02d}"
        if ym in out and out[ym] != r["url"]:
            raise RuntimeError(f"OpenDataNI lists two GP prescribing files for {ym}")
        out[ym] = r["url"]
    return dict(sorted(out.items()))


def _col(header: list, prefix: str) -> str:
    for h in header:
        if h.strip().lower().startswith(prefix.lower()):
            return h
    raise RuntimeError(f"GP prescribing CSV has no '{prefix}' column: {header}")


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252")     # the BSO files are Windows-1252 ("Gross Cost (£)" is byte 0xA3)


def group_month(raw: bytes, year_month: str) -> dict:
    """One monthly CSV -> {"rows", "totals", "groups"}; every data row must belong to year_month."""
    rd = csv.DictReader(io.StringIO(_decode(raw), newline=""))
    hdr = rd.fieldnames or []
    c_items, c_qty = _col(hdr, "Total Items"), _col(hdr, "Total Quantity")
    c_gross, c_actual = _col(hdr, "Gross Cost"), _col(hdr, "Actual Cost")
    c_code, c_vtm, c_vmp = _col(hdr, "BNF Code"), _col(hdr, "VTM_NM"), _col(hdr, "VMP_NM")
    c_ch, c_sec, c_par = _col(hdr, "BNF Chapter"), _col(hdr, "BNF Section"), _col(hdr, "BNF Paragraph")
    c_pres, c_prac, c_y, c_m = _col(hdr, "Presentation"), _col(hdr, "Practice"), _col(hdr, "Year"), _col(hdr, "Month")
    want_y, want_m = int(year_month[:4]), int(year_month[5:])
    groups = collections.defaultdict(lambda: [0, 0.0, 0.0, 0.0, set(), set()])
    n, t_items, t_qty, t_gross, t_actual = 0, 0, 0.0, 0.0, 0.0
    for r in rd:
        if not any((v or "").strip() for v in r.values() if isinstance(v, str)):
            continue                                    # the files end with blank rows
        if int(r[c_y]) != want_y or int(r[c_m]) != want_m:
            raise RuntimeError(f"GP prescribing {year_month}: row for {r[c_y]}-{r[c_m]}")
        items, qty = int(r[c_items]), float(r[c_qty] or 0)
        gross, actual = float(r[c_gross] or 0), float(r[c_actual] or 0)
        code, vtm = (r[c_code] or "").strip(), (r[c_vtm] or "").strip()
        key = (r[c_ch].strip(), r[c_sec].strip(), r[c_par].strip(), code[:9] if len(code) == 15 else "",
               "" if vtm == "-" else vtm, (r[c_pres] or "").strip())
        g = groups[key]
        g[0] += items
        g[1] += qty
        g[2] += gross
        g[3] += actual
        g[4].add((r[c_vmp] or "").strip())
        g[5].add((r[c_prac] or "").strip())
        n += 1
        t_items += items
        t_qty += qty
        t_gross += gross
        t_actual += actual
    return {"rows": n,
            "totals": {"items": t_items, "quantity": round(t_qty, 3), "gross": round(t_gross, 3),
                       "actual": round(t_actual, 3)},
            "groups": [list(k) + [g[0], round(g[1], 3), round(g[2], 3), round(g[3], 3), len(g[4]), len(g[5])]
                       for k, g in sorted(groups.items())]}


def fetch_raw(months_kept: int = MONTHS_KEPT) -> bytes:
    """Downloads the latest `months_kept` monthly CSVs one at a time (~63 MB each) and keeps only the monthly sums."""
    avail = months_available()
    if not avail:
        raise RuntimeError("OpenDataNI lists no GP prescribing months")
    keys = list(avail)[-months_kept:]
    out = {}
    for ym in keys:
        out[ym] = {"url": avail[ym], **group_month(fetch(avail[ym], timeout=600), ym)}
    return json.dumps({"months": out}).encode("utf-8")


def _next(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:])
    return f"{y + 1}-01" if m == 12 else f"{y}-{m + 1:02d}"


def parse(raw: bytes, min_groups: int = MIN_GROUPS) -> list:
    months = json.loads(raw).get("months", {})
    if not months:
        raise RuntimeError("no GP prescribing months in the download")
    keys = sorted(months)
    for a, b in zip(keys, keys[1:]):
        if _next(a) != b:
            raise RuntimeError(f"GP prescribing months are not contiguous: {a} then {b}")
    out = []
    for ym in keys:
        mo = months[ym]
        groups, tot = mo.get("groups") or [], mo.get("totals") or {}
        if len(groups) < min_groups:
            raise RuntimeError(f"GP prescribing {ym}: only {len(groups)} groups")
        if (sum(g[6] for g in groups) != tot.get("items")
                or abs(sum(g[9] for g in groups) - float(tot.get("actual") or 0)) > 1.0
                or abs(sum(g[8] for g in groups) - float(tot.get("gross") or 0)) > 1.0):
            raise RuntimeError(f"GP prescribing {ym}: groups do not add up to the file totals")
        for ch, sec, par, code, vtm, pres, items, qty, gross, actual, products, practices in groups:
            out.append({
                "year": int(ym[:4]),
                "year_month": ym,
                "bnf_chapter": ch,
                "bnf_section": sec,
                "bnf_paragraph": par,
                "bnf_chemical_substance_code": code,
                "substance": vtm,
                "presentation": pres,
                "products": products,
                "practices": practices,
                "items": items,
                "total_quantity": int(qty) if qty == int(qty) else qty,
                "gross_cost_gbp": round(gross, 2),
                "actual_cost_gbp": round(actual, 2),
            })
    return out
