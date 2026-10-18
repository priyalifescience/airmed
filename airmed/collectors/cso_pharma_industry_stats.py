"""CSO (Ireland): statistics on the Irish pharmaceutical industry from PxStat, in tidy long format.

Tables (one row per table, statistic, period and breakdown category):
- MIM05 (monthly) and MIA05 (annual): industrial production volume and turnover indices, base year 2021=100.
  CSO publishes no values for NACE 21 in these tables (nor for NACE 20 or "Chemicals and pharmaceuticals"),
  so the CSO "Modern sector" (NACE 18.2, 20, 21, 26, 27, 32.5), in which pharma is the largest part, is kept;
  NACE 21 rows are kept only where CSO publishes a value (none at present);
- EHQ15 (NACE Rev. 2, from 2008) and EHQ58 (NACE Rev. 2.1, from 2018): average weekly and hourly earnings and
  weekly paid hours of all employees, quarterly, NACE 21 / C21 only;
- AIA30: Census of Industrial Production, industrial enterprises in NACE 21 (enterprises, persons engaged,
  labour costs, turnover, purchases, stocks, capital additions, value added), annual. CSO's confidentiality
  marker (-99999999) is turned into an empty value with status "confidential";
- PMMA01-PMMA07, PMMA10, PMMA11, PMMA13: the CSO frontier series "Pharmaceutical and Medical Manufacturing in
  Ireland" (employees, wage bill, earnings, assets, liabilities). Note: CSO defines this sector more widely than
  NACE 21 (it also includes NACE 20.14, 26.60, 32.50, 46.46 and 47.74; see the release's background notes).

Exports of medicinal and pharmaceutical products are in the separate dataset cso_pharma_exports (TSM10).
"""

import json

from ..http import fetch

KEY = "cso_pharma_industry_stats"
FIELDS = ["table", "table_title", "statistic_code", "statistic", "period", "breakdown", "category_code", "category",
          "unit", "value", "status"]
URL = "https://ws.cso.ie/public/api.restful/PxStat.Data.Cube_API.ReadDataset/{}/JSON-stat/2.0/en"
CONFIDENTIAL = -99999999
# table -> (categories kept on the breakdown dimension, or None for all; categories kept only when non-empty)
TABLES = {
    "MIM05": (["21", "W0780"], ["21"]),
    "MIA05": (["21", "W0780"], ["21"]),
    "EHQ15": (["21"], []),
    "EHQ58": (["C21"], []),
    "AIA30": (["21"], []),
    "PMMA01": (None, []), "PMMA02": (None, []), "PMMA03": (None, []), "PMMA04": (None, []), "PMMA05": (None, []),
    "PMMA06": (None, []), "PMMA07": (None, []), "PMMA10": (None, []), "PMMA11": (None, []), "PMMA13": (None, []),
}


def fetch_raw() -> bytes:
    """All tables as one JSON object {table code: JSON-stat 2.0 cube}."""
    return json.dumps({t: json.loads(fetch(URL.format(t), timeout=180)) for t in TABLES}).encode("utf-8")


def _codes(dim):
    idx = dim["category"]["index"]
    return list(idx) if isinstance(idx, list) else [k for k, _ in sorted(idx.items(), key=lambda kv: kv[1])]


def _period(code: str) -> str:
    if len(code) == 6 and code.isdigit():           # TLIST(M1): 201501 -> 2015-01
        return f"{code[:4]}-{code[4:]}"
    if len(code) == 5 and code.isdigit():           # TLIST(Q1): 20251 -> 2025-Q1
        return f"{code[:4]}-Q{code[4]}"
    return code


def _cube_rows(table: str, r: dict) -> list:
    ids, size, values = r["id"], r["size"], r["value"]
    mul = 1
    for s in size:
        mul *= s
    if isinstance(values, dict):  # JSON-stat may send a sparse object
        values = [values.get(str(i)) for i in range(mul)]
    if len(values) != mul:
        raise RuntimeError(f"CSO {table}: cube has {len(values)} values, expected {mul}")
    time_dims = [d for d in ids if d.startswith("TLIST(")]
    other = [d for d in ids if d != "STATISTIC" and d not in time_dims]
    if len(time_dims) != 1 or len(other) != 1 or "STATISTIC" not in ids:
        raise RuntimeError(f"CSO {table}: unexpected dimensions {ids}")
    tdim, bdim = time_dims[0], other[0]
    stride, m = {}, 1
    for k in range(len(ids) - 1, -1, -1):
        stride[ids[k]] = m
        m *= size[k]
    codes = {d: _codes(r["dimension"][d]) for d in ids}
    labels = {d: r["dimension"][d]["category"].get("label", {}) for d in ids}
    units = r["dimension"]["STATISTIC"]["category"].get("unit", {})
    wanted, only_filled = TABLES[table]
    keep = codes[bdim]
    if wanted is not None:
        lost = [c for c in wanted if c not in keep]
        if lost:
            raise RuntimeError(f"CSO {table}: categories {lost} not found")
        keep = wanted
    out = []
    for sc in codes["STATISTIC"]:
        for tc in codes[tdim]:
            for bc in keep:
                v = values[codes["STATISTIC"].index(sc) * stride["STATISTIC"] + codes[tdim].index(tc) * stride[tdim]
                           + codes[bdim].index(bc) * stride[bdim]]
                if bc in only_filled and v is None:
                    continue
                status = ""
                if v == CONFIDENTIAL:
                    v, status = None, "confidential"
                out.append({"table": table, "table_title": r.get("label", ""), "statistic_code": sc,
                            "statistic": labels["STATISTIC"].get(sc, sc), "period": _period(tc),
                            "breakdown": r["dimension"][bdim].get("label", bdim), "category_code": bc,
                            "category": labels[bdim].get(bc, bc), "unit": units.get(sc, {}).get("label", ""),
                            "value": "" if v is None else v, "status": status})
    return out


def parse(raw: bytes) -> list:
    cubes = json.loads(raw)
    missing = [t for t in TABLES if t not in cubes]
    if missing:
        raise RuntimeError(f"CSO tables missing from reply: {missing}")
    out = []
    for t in TABLES:
        out.extend(_cube_rows(t, cubes[t]))
    return out
