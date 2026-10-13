"""CSO (Ireland): monthly value of exports of medicinal and pharmaceutical products (SITC 54) by destination
country, table TSM10, in euro thousand. One row per month and country (long format).
"""

import json

from ..http import fetch

KEY = "cso_pharma_exports"
FIELDS = ["month", "country_code", "country", "exports_eur_thousand"]
URL = "https://ws.cso.ie/public/api.jsonrpc"
QUERY = {"jsonrpc": "2.0", "method": "PxStat.Data.Cube_API.ReadDataset", "id": 1, "params": {
    "class": "query", "id": ["STATISTIC", "C02487V03011"],
    "dimension": {"STATISTIC": {"category": {"index": ["TSM10C02"]}}, "C02487V03011": {"category": {"index": ["006004"]}}},
    "extension": {"pivot": None, "codes": False, "language": {"code": "en"}, "format": {"type": "JSON-stat", "version": "2.0"},
                  "matrix": "TSM10"}, "version": "2.0"}}


def fetch_raw() -> bytes:
    return fetch(URL, timeout=180, data=json.dumps(QUERY).encode("utf-8"), headers={"Content-Type": "application/json"})


def _codes(dim):
    idx = dim["category"]["index"]
    return list(idx) if isinstance(idx, list) else [k for k, _ in sorted(idx.items(), key=lambda kv: kv[1])]


def parse(raw: bytes) -> list:
    r = json.loads(raw)["result"]
    ids, size, values = r["id"], r["size"], r["value"]
    unit = r["dimension"]["STATISTIC"]["category"].get("unit", {}).get("TSM10C02", {}).get("label", "")
    if unit != "Euro Thousand":
        raise RuntimeError(f"unexpected unit {unit!r}")
    codes = {d: _codes(r["dimension"][d]) for d in ids}
    labels = {d: r["dimension"][d]["category"].get("label", {}) for d in ids}
    stride, mul = {}, 1
    for k in range(len(ids) - 1, -1, -1):
        stride[ids[k]] = mul
        mul *= size[k]
    if isinstance(values, dict):  # JSON-stat may send a sparse object
        values = [values.get(str(i)) for i in range(mul)]
    if len(values) != mul:
        raise RuntimeError(f"CSO cube has {len(values)} values, expected {mul}")
    tdim, cdim = "TLIST(M1)", "C03409V04104"
    out = []
    for ti, month in enumerate(codes[tdim]):
        for ci, cc in enumerate(codes[cdim]):
            v = values[ti * stride[tdim] + ci * stride[cdim]]
            out.append({"month": f"{month[:4]}-{month[4:]}", "country_code": cc, "country": labels[cdim].get(cc, cc),
                        "exports_eur_thousand": "" if v is None else v})
    return out
