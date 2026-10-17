"""NHS England Prescription Cost Analysis (PCA), monthly, summed by BNF chemical substance and unit of measure.

Source: NHSBSA Open Data Portal (CKAN), dataset "Prescription Cost Analysis (PCA) Monthly Administrative Data", one
datastore table per month (PCA_YYYYMM). One server-side SQL GROUP BY per month returns about 2,600 rows instead of
the ~530,000 region/ICB/presentation rows in the table; a second SQL query per month gets the table's own totals,
and the parser refuses the month if the grouped rows do not add up to them.

Window: January of (current year - 3) to the latest published month, i.e. the last three full years plus the current
year to date (NHSBSA publishes with a two-month lag).

Gotchas carried over from the Priya Life Science /drug-spending builder:
  - the SQL table name is the resource NAME in backticks (`PCA_202607`), and resource_id is that name too; the
    resource UUID answers "not found";
  - the portal nests the CKAN result one level deeper than stock CKAN (result.result.records);
  - BNF codes are strings with leading zeros; an all-digit code ("040201060") must never become a number;
  - the BNF re-codes substances now and then (January 2026 split "BeclometDiprop/Formoterol" out of
    "Beclometasone dipropionate"), so a code's monthly series can start or stop mid-window. Rows are kept as
    published; nothing is re-mapped.
Quantity is only additive within one unit of measure (tablets, ml, grams ...), which is why the unit is part of the
grouping. NIC is the basic list price before discounts, not the net cost to the NHS.
"""

import datetime
import json
import re
import time
import urllib.parse

from ..http import fetch

KEY = "nhs_prescription_costs"
FIELDS = ["year", "year_month", "bnf_chemical_substance_code", "bnf_chemical_substance", "bnf_chapter_code",
          "bnf_chapter", "unit_of_measure", "items", "total_quantity", "nic_gbp"]
PORTAL = "https://opendata.nhsbsa.net/api/3/action/"
PACKAGE = "prescription-cost-analysis-pca-monthly-data"
YEARS_BACK = 3          # full years kept before the current one
MIN_ROWS = 500          # a month with fewer grouped rows is a broken reply (a real month has ~2,600)
EXTRA_PAUSE = 0.5       # on top of http.PAUSE_SECONDS


def _sql(table: str, sql: str) -> dict:
    time.sleep(EXTRA_PAUSE)
    url = PORTAL + "datastore_search_sql?" + urllib.parse.urlencode({"resource_id": table, "sql": sql})
    j = json.loads(fetch(url, timeout=240))
    if not j.get("success"):
        raise RuntimeError(f"NHSBSA SQL on {table} failed")
    res = j["result"].get("result", j["result"])   # the portal wraps the CKAN result one level deeper
    if res.get("records_truncated"):
        raise RuntimeError(f"NHSBSA SQL on {table}: reply truncated")
    return res


def months_available() -> dict:
    """{'YYYYMM': resource name} for every monthly table that is live in the datastore."""
    j = json.loads(fetch(PORTAL + "package_show?id=" + PACKAGE, timeout=90))
    out = {}
    for r in j.get("result", {}).get("resources", []):
        m = re.fullmatch(r"PCA_(\d{6})", str(r.get("name", "")))
        if m and r.get("datastore_active"):
            out[m.group(1)] = m.group(0)
    return dict(sorted(out.items()))


def fetch_raw(first_year: int = None) -> bytes:
    """Two SQL queries per month (grouped rows + table totals): about 90 calls for 3.6 years."""
    first_year = first_year or datetime.date.today().year - YEARS_BACK
    months = {ym: t for ym, t in months_available().items() if int(ym[:4]) >= first_year}
    if not months:
        raise RuntimeError("NHSBSA lists no PCA months in the window")
    out = {}
    for ym, table in months.items():
        rows = _sql(table, "SELECT BNF_CHEMICAL_SUBSTANCE_CODE c, BNF_CHEMICAL_SUBSTANCE n, BNF_CHAPTER_CODE chc, "
                           "BNF_CHAPTER ch, UNIT_OF_MEASURE u, sum(ITEMS) items, sum(TOTAL_QUANTITY) q, sum(NIC) nic "
                           f"FROM `{table}` GROUP BY 1,2,3,4,5")
        totals = _sql(table, f"SELECT count(*) n, sum(ITEMS) items, sum(TOTAL_QUANTITY) q, sum(NIC) nic FROM `{table}`")
        out[ym] = {"table": table, "totals": (totals.get("records") or [{}])[0], "records": rows.get("records", [])}
    return json.dumps({"first_year": first_year, "months": out}).encode("utf-8")


def _months_between(a: str, b: str) -> list:
    y, m, out = int(a[:4]), int(a[4:]), []
    while f"{y}{m:02d}" <= b:
        out.append(f"{y}{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def parse(raw: bytes, min_rows: int = MIN_ROWS) -> list:
    data = json.loads(raw)
    months = data.get("months", {})
    if not months:
        raise RuntimeError("no PCA months in the download")
    keys = sorted(months)
    if keys != _months_between(keys[0], keys[-1]):
        raise RuntimeError(f"PCA months are not contiguous: {keys}")   # a gap would understate a year
    out = []
    for ym in keys:
        mo = months[ym]
        recs, tot = mo.get("records", []), mo.get("totals", {})
        if len(recs) < min_rows:
            raise RuntimeError(f"PCA {ym}: only {len(recs)} grouped rows")
        items = sum(int(r["items"] or 0) for r in recs)
        nic = sum(float(r["nic"] or 0) for r in recs)
        qty = sum(float(r["q"] or 0) for r in recs)
        # the grouped rows must add up to the table's own totals (items exactly; money and quantity to rounding)
        if (items != int(tot.get("items") or -1) or abs(nic - float(tot.get("nic") or 0)) > 1.0
                or abs(qty - float(tot.get("q") or 0)) > max(1.0, 1e-9 * qty)):
            raise RuntimeError(f"PCA {ym}: grouped rows do not match the table totals")
        for r in recs:
            q = float(r["q"] or 0)
            out.append({
                "year": int(ym[:4]),
                "year_month": f"{ym[:4]}-{ym[4:]}",
                "bnf_chemical_substance_code": str(r["c"] or "").strip(),
                "bnf_chemical_substance": str(r["n"] or "").strip(),
                "bnf_chapter_code": str(r["chc"] or "").strip(),
                "bnf_chapter": str(r["ch"] or "").strip(),
                "unit_of_measure": str(r["u"] or "").strip(),
                "items": int(r["items"] or 0),
                "total_quantity": int(q) if q == int(q) else round(q, 3),
                "nic_gbp": round(float(r["nic"] or 0), 2),
            })
    out.sort(key=lambda r: (r["year_month"], r["bnf_chemical_substance_code"], r["unit_of_measure"],
                            r["bnf_chemical_substance"]))
    return out
