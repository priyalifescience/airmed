"""Eurostat (Comext): trade in medicinal and pharmaceutical products (SITC 54), value in euro, by reporting
EU member state, partner, flow and period. Dataset DS-059331 "International trade of EU and non-EU countries
since 2002 by SITC".

Two parts, both long format:
- annual (freq A): every EU27 reporter (plus the EU27 aggregate) against every partner Eurostat lists
  (countries and groupings such as WORLD, EXT_EU27_2020, INT_EU27_2020), 2002 to the latest year;
- monthly (freq M): the same reporters against WORLD, EXT_EU27_2020 and INT_EU27_2020 only (keeps the file small).

Reporters are limited to EU member states: Eurostat's reuse notice excludes, for commercial reuse, data declared
by countries outside the EU/EFTA/candidate group and SITC trade data declared by Switzerland and Liechtenstein.
"""

import datetime as dt
import json
import urllib.parse

from ..http import fetch

KEY = "eurostat_pharma_trade"
FIELDS = ["freq", "period", "reporter_code", "reporter", "partner_code", "partner", "flow", "value_eur"]
API = "https://ec.europa.eu/eurostat/api/comext/dissemination/statistics/1.0/data/DS-059331"
REPORTERS = ["EU27_2020", "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR", "HR", "HU", "IE",
             "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK"]
MONTHLY_PARTNERS = ["WORLD", "EXT_EU27_2020", "INT_EU27_2020"]
FIRST_YEAR = 2002
FLOWS = {"1": "import", "2": "export"}


def _url(freq: str, extra: list) -> str:
    q = [("format", "JSON"), ("lang", "EN"), ("product", "54"), ("indicators", "VALUE_EUR"), ("freq", freq)]
    q += [("reporter", r) for r in REPORTERS] + extra
    return API + "?" + urllib.parse.urlencode(q)


def fetch_raw(last_year: int = None) -> bytes:
    """One request per year (annual, all partners) and one per 4-year block (monthly, 3 partner aggregates)."""
    last_year = last_year or dt.date.today().year
    annual, monthly = [], []
    for y in range(FIRST_YEAR, last_year + 1):
        annual.append(json.loads(fetch(_url("A", [("time", str(y))]), timeout=180)))
    for y in range(FIRST_YEAR, last_year + 1, 4):
        extra = [("partner", p) for p in MONTHLY_PARTNERS]
        extra += [("sinceTimePeriod", f"{y}-01"), ("untilTimePeriod", f"{min(y + 3, last_year)}-12")]
        monthly.append(json.loads(fetch(_url("M", extra), timeout=180)))
    return json.dumps({"annual": annual, "monthly": monthly}).encode("utf-8")


def decode_jsonstat(doc: dict):
    """Yield (codes, labels, value, status) for every cell of a JSON-stat 2.0 dataset that has a value or a status.

    codes/labels are dicts keyed by dimension id. Missing cells (no value and no status) are skipped.
    """
    ids, size = doc["id"], doc["size"]
    total = 1
    for s in size:
        total *= s
    cats = []
    for d in ids:
        c = doc["dimension"][d]["category"]
        idx = c["index"]
        order = list(idx) if isinstance(idx, list) else [k for k, _ in sorted(idx.items(), key=lambda kv: kv[1])]
        if len(order) != size[ids.index(d)]:
            raise RuntimeError(f"dimension {d}: {len(order)} codes but size {size[ids.index(d)]}")
        cats.append((order, c.get("label", {})))
    values, status = doc.get("value", {}), doc.get("status", {}) or {}
    if isinstance(values, list):
        values = {str(i): v for i, v in enumerate(values) if v is not None}
    if isinstance(status, list):
        status = {str(i): s for i, s in enumerate(status) if s}
    for k in set(values) | set(status):
        if not 0 <= int(k) < total:
            raise RuntimeError(f"cell index {k} outside cube of {total} cells")
    for key in sorted(set(values) | set(status), key=int):
        rest, codes, labels = int(key), {}, {}
        for d, n, (order, lab) in reversed(list(zip(ids, size, cats))):
            rest, pos = divmod(rest, n)
            codes[d] = order[pos]
            labels[d] = lab.get(order[pos], order[pos])
        yield codes, labels, values.get(key), status.get(key, "")


def parse(raw: bytes) -> list:
    data = json.loads(raw)
    out = []
    for part, freq in (("annual", "A"), ("monthly", "M")):
        for doc in data.get(part, []):
            if doc.get("id") != ["freq", "reporter", "partner", "product", "flow", "indicators", "time"]:
                raise RuntimeError(f"unexpected Comext dimensions {doc.get('id')}")
            for codes, labels, value, _status in decode_jsonstat(doc):
                if codes["product"] != "54" or codes["indicators"] != "VALUE_EUR" or codes["freq"] != freq:
                    raise RuntimeError(f"unexpected cell {codes}")
                if codes["reporter"] not in REPORTERS:
                    continue  # never publish reporters outside the EU (see module docstring)
                if value is None:
                    continue
                out.append({"freq": freq, "period": codes["time"], "reporter_code": codes["reporter"],
                            "reporter": labels["reporter"], "partner_code": codes["partner"],
                            "partner": labels["partner"], "flow": FLOWS[codes["flow"]], "value_eur": value})
    out.sort(key=lambda r: (r["freq"], r["reporter_code"], r["partner_code"], r["flow"], r["period"]))
    seen = set()
    for r in out:
        k = (r["freq"], r["reporter_code"], r["partner_code"], r["flow"], r["period"])
        if k in seen:
            raise RuntimeError(f"duplicate cell {k}")
        seen.add(k)
    return out
