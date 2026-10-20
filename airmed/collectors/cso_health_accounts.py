"""CSO (Ireland): System of Health Accounts (SHA), PxStat tables SHA01-SHA15, in tidy long format.

The CSO compiles Ireland's health accounts to the OECD/Eurostat/WHO System of Health Accounts 2011 manual. The
tables give current health care expenditure (Euro million) cross-classified by health care function (ICHA-HC,
e.g. HC.5.1 "Pharmaceuticals and other medical non-durable goods"), provider (ICHA-HP) and financing scheme
(ICHA-HF), plus SHA07 (revised totals and shares of GDP/GNI*), SHA08 (reconciliation of HSE gross expenditure)
and SHA09 (revenues of financing schemes, ICHA-FS).

One row per table, statistic, year and combination of breakdown categories. Each SHA breakdown has its own pair
of columns (function, provider, financing_scheme, revenue, item), empty when the table has no such breakdown;
the codes are CSO's category codes, the labels are CSO's (the ICHA code is part of most labels).

Choices:
- all 15 tables are kept; the older series SHA01-SHA06 (2013-2022 releases) and the current series SHA09-SHA15
  overlap in years and may differ after revisions: keep the table code with every figure;
- cells CSO publishes as empty (mostly impossible function x provider combinations) are left out;
- labels are trimmed of surrounding spaces; values are as published.
"""

import itertools
import json

from ..http import fetch

KEY = "cso_health_accounts"
FIELDS = ["table", "table_title", "statistic_code", "statistic", "unit", "year",
          "function_code", "function", "provider_code", "provider", "financing_scheme_code", "financing_scheme",
          "revenue_code", "revenue", "item_code", "item", "value", "status"]
URL = "https://ws.cso.ie/public/api.restful/PxStat.Data.Cube_API.ReadDataset/{}/JSON-stat/2.0/en"
TABLES = [f"SHA{i:02d}" for i in range(1, 16)]
CONFIDENTIAL = -99999999
# CSO dimension id -> column prefix
DIMS = {
    "C03314V03998": "function",           # Health Care Function (ICHA-HC)
    "C03315V03999": "provider",           # Provider (ICHA-HP)
    "C03313V03997": "financing_scheme",   # Type of Financing Scheme (ICHA-HF)
    "C03313V03997B": "financing_scheme",  # Type of Financing Scheme (ICHA-HF), SHA09
    "C03313V03997A": "revenue",           # Revenue of Financing Scheme (ICHA-FS), SHA09
    "C03316V04001": "item",               # Reconciliation line, SHA08
}


def fetch_raw() -> bytes:
    """All tables as one JSON object {table code: JSON-stat 2.0 cube}."""
    return json.dumps({t: json.loads(fetch(URL.format(t), timeout=180)) for t in TABLES}).encode("utf-8")


def _codes(dim):
    idx = dim["category"]["index"]
    return list(idx) if isinstance(idx, list) else [k for k, _ in sorted(idx.items(), key=lambda kv: kv[1])]


def _cells(table: str, r: dict):
    """Yield ({dimension id: category code}, value) for every cell of a JSON-stat 2.0 cube (row-major order)."""
    ids, size, values = r["id"], r["size"], r["value"]
    n = 1
    for s in size:
        n *= s
    if isinstance(values, dict):  # JSON-stat may send a sparse object
        values = [values.get(str(i)) for i in range(n)]
    if len(values) != n:
        raise RuntimeError(f"CSO {table}: cube has {len(values)} values, expected {n}")
    codes = [_codes(r["dimension"][d]) for d in ids]
    if [len(c) for c in codes] != list(size):
        raise RuntimeError(f"CSO {table}: dimension sizes do not match the category lists")
    for combo, v in zip(itertools.product(*codes), values):
        yield dict(zip(ids, combo)), v


def _cube_rows(table: str, r: dict) -> list:
    ids = r["id"]
    time_dims = [d for d in ids if d.startswith("TLIST(")]
    if time_dims != ["TLIST(A1)"] or "STATISTIC" not in ids:
        raise RuntimeError(f"CSO {table}: unexpected dimensions {ids}")
    for d in ids:
        if d not in DIMS and d not in ("STATISTIC", "TLIST(A1)") and len(_codes(r["dimension"][d])) != 1:
            raise RuntimeError(f"CSO {table}: unknown breakdown {d} ({r['dimension'][d].get('label')})")
    labels = {d: r["dimension"][d]["category"].get("label", {}) for d in ids}
    units = r["dimension"]["STATISTIC"]["category"].get("unit", {})
    title = r.get("label", "").strip()
    out = []
    for c, v in _cells(table, r):
        if v is None:
            continue
        status = ""
        if v == CONFIDENTIAL:
            v, status = "", "confidential"
        sc = c["STATISTIC"]
        row = {"table": table, "table_title": title, "statistic_code": sc,
               "statistic": labels["STATISTIC"].get(sc, sc).strip(), "unit": units.get(sc, {}).get("label", ""),
               "year": c["TLIST(A1)"]}
        for col in ("function", "provider", "financing_scheme", "revenue", "item"):
            row[col + "_code"], row[col] = "", ""
        for d, col in DIMS.items():
            if d in c:
                row[col + "_code"], row[col] = c[d], labels[d].get(c[d], c[d]).strip()
        row["value"], row["status"] = v, status
        out.append({k: row[k] for k in FIELDS})
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
