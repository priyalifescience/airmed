"""OECD Health Statistics (System of Health Accounts, dataflow DSD_SHA@DF_SHA): spending on pharmaceuticals
by country and year, in long format.

Functions: HC51 pharmaceuticals and other medical non-durable goods (the OECD "pharmaceutical spending"
indicator), and its parts HC511 prescribed medicines, HC512 over-the-counter medicines, HC513 other medical
non-durables. Financing: total, government/compulsory schemes (HF1), voluntary schemes (HF2), household
out-of-pocket (HF3). Units: % of current health expenditure, % of GDP, US dollars per person (PPP), national
currency (millions). All providers combined (PROVIDER=_T).
"""

import csv
import io

from ..http import fetch

KEY = "oecd_pharma_spending"
FIELDS = ["country_code", "country", "function_code", "function", "financing_code", "financing", "unit_code", "unit",
          "price_base", "base_year", "unit_multiplier", "year", "value", "flags"]
# key order: REF_AREA.FREQ.MEASURE.UNIT_MEASURE.FINANCING_SCHEME.FINANCING_SCHEME_REV.FUNCTION.MODE_PROVISION.
#            PROVIDER.FACTOR_PROVISION.ASSET_TYPE.PRICE_BASE
URL = ("https://sdmx.oecd.org/public/rest/data/OECD.ELS.HD,DSD_SHA@DF_SHA,/"
       ".A.EXP_HEALTH.PT_EXP_HLTH+PT_B1GQ+USD_PPP_PS+XDC._T+HF1+HF2+HF3..HC51+HC511+HC512+HC513.._T...."
       "?format=csvfilewithlabels")
FUNCTIONS = {"HC51", "HC511", "HC512", "HC513"}
NEEDED = ["REF_AREA", "Reference area", "FREQ", "MEASURE", "UNIT_MEASURE", "Unit of measure", "FINANCING_SCHEME",
          "Financing scheme", "FUNCTION", "Health function", "PROVIDER", "PRICE_BASE", "Price base", "TIME_PERIOD",
          "OBS_VALUE", "BASE_PER", "Unit multiplier", "OBS_STATUS", "OBS_STATUS2", "OBS_STATUS3"]


def fetch_raw() -> bytes:
    return fetch(URL, timeout=300)


def _num(s: str):
    if s == "":
        return ""
    f = float(s)
    return int(f) if f.is_integer() and "." not in s and "e" not in s.lower() else f


def parse(raw: bytes) -> list:
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    missing = [c for c in NEEDED if c not in (reader.fieldnames or [])]
    if missing:
        raise RuntimeError(f"OECD CSV is missing columns {missing}")
    out, seen = [], set()
    for r in reader:
        if r["FREQ"] != "A" or r["MEASURE"] != "EXP_HEALTH" or r["PROVIDER"] != "_T" or r["FUNCTION"] not in FUNCTIONS:
            raise RuntimeError(f"unexpected OECD row {r['REF_AREA']} {r['FUNCTION']} {r['PROVIDER']}")
        key = (r["REF_AREA"], r["FUNCTION"], r["FINANCING_SCHEME"], r["UNIT_MEASURE"], r["PRICE_BASE"], r["TIME_PERIOD"])
        if key in seen:
            raise RuntimeError(f"duplicate OECD observation {key}")
        seen.add(key)
        flags = ";".join(f for f in (r["OBS_STATUS"], r["OBS_STATUS2"], r["OBS_STATUS3"]) if f)
        out.append({"country_code": r["REF_AREA"], "country": r["Reference area"], "function_code": r["FUNCTION"],
                    "function": r["Health function"], "financing_code": r["FINANCING_SCHEME"],
                    "financing": r["Financing scheme"], "unit_code": r["UNIT_MEASURE"], "unit": r["Unit of measure"],
                    "price_base": r["Price base"], "base_year": r["BASE_PER"], "unit_multiplier": r["Unit multiplier"],
                    "year": r["TIME_PERIOD"], "value": _num(r["OBS_VALUE"]), "flags": flags})
    out.sort(key=lambda x: (x["country_code"], x["function_code"], x["financing_code"], x["unit_code"],
                            x["price_base"], x["year"]))
    return out
