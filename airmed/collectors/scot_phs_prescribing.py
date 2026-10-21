"""Scotland community prescribing: Scotland totals per month by BNF chemical substance, latest 36 published months.

Source: Public Health Scotland, dataset "Prescriptions in the Community" on the NHS Scotland Open Data platform (CKAN,
https://www.opendata.nhs.scot/dataset/prescriptions-in-the-community). One "Data by Prescriber Location" table per
month (~1.2 million rows: prescriber location x BNF item x dm+d product x prescribed type, with paid items, paid
quantity and gross ingredient cost). In PHS's words the file "contains details of items dispensed in the community at
prescribing location code level for General Practice data and aggregated by NHS Board for other prescriber location
types".

Size choice: practice-level rows are ~1.2 million a month, and even Scotland totals per BNF item (15-character
presentation code) would be ~25,000 rows a month (~150 MB of JSON for 36 months). So each month is summed on the
server with one datastore SQL GROUP BY to
  BNF chapter / section / paragraph + BNF chemical substance (first 9 characters of the 15-character BNF code),
which gives ~2,000 rows a month and ~20 MB for 36 months, the same grain as ni_bso_gp_prescribing and
nhs_prescription_costs (join on bnf_chemical_substance_code). PHS publishes no substance name and no structured
formulation (only the free-text BNF item description, e.g. "ATORVASTATIN 20MG TABLETS"), so neither is kept; the
substance name comes from the join. A second SQL query per month gets the table's own totals, and the parser refuses
the month if the groups do not add up to them, or if the table holds rows for another month.

Dressings and appliances (BNF chapters 20-23) carry an 11-digit appliance code: they are summed per BNF chapter,
section and paragraph (the first 6 digits) with an empty substance code. Rows PHS publishes without any BNF item code
are kept as one row per month with all BNF fields empty, so the monthly totals stay complete.

Caveats from PHS (dataset notes): data from May 2023 come from a new payment system and "may not be directly
comparable to data published previously"; paid quantity for some formulations (e.g. inhalers) is counted in doses
from May 2023; gross ingredient cost drops for some BNF sections from May 2023 ("identified as anomalous").
Gross ingredient cost is the cost of the medicines before any discount, as published.

Prescriber location codes are organisation codes and are not kept (only the count of distinct locations); the source
holds no prescriber or patient names.
"""

import json
import re
import time
import urllib.parse

from ..http import fetch

KEY = "scot_phs_prescribing"
FIELDS = ["year", "year_month", "bnf_chapter", "bnf_section", "bnf_paragraph", "bnf_chemical_substance_code",
          "bnf_presentations", "prescriber_locations", "items", "paid_quantity", "gross_ingredient_cost_gbp"]
PORTAL = "https://www.opendata.nhs.scot/api/3/action/"
PACKAGE = "prescriptions-in-the-community"
MONTHS_KEPT = 36
MIN_GROUPS = 1000      # a real month has ~2,000 groups
EXTRA_PAUSE = 0.5      # on top of http.PAUSE_SECONDS
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
               "November", "December"]
MONTHS = {m: i for i, m in enumerate(MONTH_NAMES, 1)}
_NAME_RE = re.compile(r"^Data by Prescri(?:ber|bing) Location\W+(" + "|".join(MONTH_NAMES) + r")\s+(\d{4})\s*$", re.I)
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

# BNF code 15 characters: chapter(2) section(2) paragraph(2) sub-paragraph(1) chemical(2) product... ;
# appliances 11 digits: chapter(2) section(2) paragraph(2) ...
GROUP_SQL = ('SELECT CASE WHEN length("BNFItemCode") = 15 THEN left("BNFItemCode", 9) ELSE \'\' END s, '
             'left("BNFItemCode", 2) ch, substr("BNFItemCode", 3, 2) sec, substr("BNFItemCode", 5, 2) par, '
             'count(DISTINCT "BNFItemCode") p, count(DISTINCT "GPPractice") pr, sum("NumberOfPaidItems") i, '
             'sum("PaidQuantity") q, sum("GrossIngredientCost") g FROM "{t}" GROUP BY 1, 2, 3, 4')
TOTAL_SQL = ('SELECT count(*) n, sum("NumberOfPaidItems") i, sum("PaidQuantity") q, sum("GrossIngredientCost") g, '
             'min("PaidDateMonth") a, max("PaidDateMonth") b FROM "{t}"')


def _sql(sql: str) -> dict:
    time.sleep(EXTRA_PAUSE)
    j = json.loads(fetch(PORTAL + "datastore_search_sql?" + urllib.parse.urlencode({"sql": sql}), timeout=300))
    if not j.get("success"):
        raise RuntimeError("PHS datastore SQL failed")
    res = j["result"]
    if res.get("records_truncated"):
        raise RuntimeError("PHS datastore SQL: reply truncated")
    return res


def months_available() -> dict:
    """{'YYYY-MM': resource id} for every monthly "Data by Prescriber Location" table that is live in the datastore."""
    j = json.loads(fetch(PORTAL + "package_show?id=" + PACKAGE, timeout=90))
    out = {}
    for r in j.get("result", {}).get("resources", []):
        m = _NAME_RE.search(str(r.get("name") or "").strip())
        if not m or not r.get("datastore_active") or not _UUID_RE.match(str(r.get("id", ""))):
            continue
        ym = f"{m[2]}-{MONTHS[m[1].capitalize()]:02d}"
        if ym in out and out[ym] != r["id"]:
            raise RuntimeError(f"PHS lists two prescriber-location tables for {ym}")
        out[ym] = r["id"]
    return dict(sorted(out.items()))


def fetch_raw(months_kept: int = MONTHS_KEPT) -> bytes:
    """Two SQL queries per month (grouped rows + table totals): 72 calls for 36 months, ~15 s each."""
    avail = months_available()
    if not avail:
        raise RuntimeError("PHS lists no prescriber-location months")
    out = {}
    for ym in list(avail)[-months_kept:]:
        t = avail[ym]
        groups = _sql(GROUP_SQL.format(t=t)).get("records", [])
        totals = (_sql(TOTAL_SQL.format(t=t)).get("records") or [{}])[0]
        out[ym] = {"resource_id": t, "totals": totals, "records": groups}
    return json.dumps({"months": out}).encode("utf-8")


def _next(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:])
    return f"{y + 1}-01" if m == 12 else f"{y}-{m + 1:02d}"


def _num(v) -> float:
    return float(v) if v not in (None, "") else 0.0


def _strip0(v: str) -> str:
    """'02' -> '2', '00' -> '0' (the NI BSO style); non-digits unchanged."""
    v = (v or "").strip()
    return str(int(v)) if v.isdigit() else v


def parse(raw: bytes, min_groups: int = MIN_GROUPS) -> list:
    months = json.loads(raw).get("months", {})
    if not months:
        raise RuntimeError("no PHS prescribing months in the download")
    keys = sorted(months)
    for a, b in zip(keys, keys[1:]):
        if _next(a) != b:
            raise RuntimeError(f"PHS prescribing months are not contiguous: {a} then {b}")
    out = []
    for ym in keys:
        mo = months[ym]
        recs, tot = mo.get("records") or [], mo.get("totals") or {}
        if len(recs) < min_groups:
            raise RuntimeError(f"PHS prescribing {ym}: only {len(recs)} groups")
        want = int(ym.replace("-", ""))
        if int(_num(tot.get("a"))) != want or int(_num(tot.get("b"))) != want:
            raise RuntimeError(f"PHS prescribing {ym}: table holds months {tot.get('a')}-{tot.get('b')}")
        items = sum(int(_num(r["i"])) for r in recs)
        gic = sum(_num(r["g"]) for r in recs)
        qty = sum(_num(r["q"]) for r in recs)
        if (items != int(_num(tot.get("i")) or -1) or abs(gic - _num(tot.get("g"))) > 1.0
                or abs(qty - _num(tot.get("q"))) > max(1.0, 1e-9 * qty)):
            raise RuntimeError(f"PHS prescribing {ym}: groups do not add up to the table totals")
        for r in recs:
            q = round(_num(r["q"]), 3)
            out.append({
                "year": int(ym[:4]),
                "year_month": ym,
                "bnf_chapter": _strip0(r["ch"]),
                "bnf_section": _strip0(r["sec"]),
                "bnf_paragraph": _strip0(r["par"]),
                "bnf_chemical_substance_code": str(r["s"] or "").strip(),
                "bnf_presentations": int(_num(r["p"])),
                "prescriber_locations": int(_num(r["pr"])),
                "items": int(_num(r["i"])),
                "paid_quantity": int(q) if q == int(q) else q,
                "gross_ingredient_cost_gbp": round(_num(r["g"]), 2),
            })
    out.sort(key=lambda r: (r["year_month"], r["bnf_chemical_substance_code"], r["bnf_chapter"].zfill(2),
                            r["bnf_section"].zfill(2), r["bnf_paragraph"].zfill(2)))
    return out
