"""Eurostat: the pharmaceutical manufacturing industry (NACE Rev. 2 C21, manufacture of basic pharmaceutical
products and pharmaceutical preparations) by country and year, in long format.

Three Eurostat tables, each row tagged with its table code:
- sbs_na_ind_r2: structural business statistics for industry, 2005-2020 (enterprises, persons employed,
  turnover, production value, value added, personnel costs, investment and ratios);
- sbs_sc_ovw: enterprise statistics from 2021 (size class "Total" only). 2021 is a break in series
  (new EBS regulation), so the two SBS tables are kept apart rather than joined;
- sts_inpr_a: annual industrial production index (volume) for C21.

Countries are limited to those whose data Eurostat allows for commercial reuse (EU, EFTA, candidate
countries and EU/euro-area aggregates); see the Eurostat copyright notice.
"""

import json
import urllib.parse

from ..http import fetch
from .eurostat_pharma_trade import decode_jsonstat

KEY = "eurostat_pharma_industry"
FIELDS = ["dataset", "country_code", "country", "indicator_code", "indicator", "unit", "year", "value", "flags"]
API = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
TABLES = {
    "sbs_na_ind_r2": [("nace_r2", "C21")],
    "sbs_sc_ovw": [("nace_r2", "C21"), ("size_emp", "TOTAL")],
    "sts_inpr_a": [("nace_r2", "C21")],
}
EU = ["AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI", "FR", "HR", "HU", "IE", "IT", "LT", "LU",
      "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK"]
EFTA = ["IS", "LI", "NO", "CH"]
CANDIDATES = ["AL", "BA", "GE", "MD", "ME", "MK", "RS", "TR", "UA"]
ALLOWED_GEO = set(EU + EFTA + CANDIDATES)


def _geo_allowed(code: str) -> bool:
    return code in ALLOWED_GEO or code.startswith(("EU", "EA"))


def fetch_raw() -> bytes:
    docs = {}
    for table, filters in TABLES.items():
        q = [("format", "JSON"), ("lang", "EN")] + filters
        docs[table] = json.loads(fetch(API + table + "?" + urllib.parse.urlencode(q), timeout=180))
    return json.dumps(docs).encode("utf-8")


def _split_unit(label: str):
    """'Turnover ... - million euro' -> ('Turnover ...', 'million euro'); no suffix -> (label, '')."""
    if " - " in label:
        head, tail = label.rsplit(" - ", 1)
        return head, tail
    return label, ""


def parse(raw: bytes) -> list:
    docs = json.loads(raw)
    out = []
    for table in TABLES:
        doc = docs[table]
        for codes, labels, value, status in decode_jsonstat(doc):
            if codes.get("nace_r2") != "C21" or codes.get("freq") != "A":
                raise RuntimeError(f"{table}: unexpected cell {codes}")
            geo = codes["geo"]
            if not _geo_allowed(geo):
                continue
            if table == "sts_inpr_a":
                ind_code = f"{codes['indic_bt']}_{codes['s_adj']}"
                ind = f"{labels['indic_bt']}; {labels['s_adj']}"
                unit = labels["unit"]
                ind_code += f"_{codes['unit']}"
            else:
                dim = "indic_sb" if table == "sbs_na_ind_r2" else "indic_sbs"
                if table == "sbs_sc_ovw" and codes["size_emp"] != "TOTAL":
                    raise RuntimeError(f"{table}: unexpected size class {codes['size_emp']}")
                ind_code = codes[dim]
                ind, unit = _split_unit(labels[dim])
            out.append({"dataset": table, "country_code": geo, "country": labels["geo"], "indicator_code": ind_code,
                        "indicator": ind, "unit": unit, "year": codes["time"],
                        "value": "" if value is None else value, "flags": status or ""})
    out.sort(key=lambda r: (r["dataset"], r["country_code"], r["indicator_code"], r["year"]))
    return out
