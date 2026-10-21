"""World Bank World Development Indicators (WDI, source 2): a focused set of health and economy indicators for
every country and World Bank aggregate, years 2000 onwards, in long format (one row per indicator, economy and
year with a value).

Indicators:
  SH.XPD.CHEX.GD.ZS  Current health expenditure (% of GDP)
  SH.XPD.CHEX.PC.CD  Current health expenditure per capita (current US$)
  SP.POP.TOTL        Population, total
  SP.POP.65UP.TO.ZS  Population ages 65 and above (% of total population)
  SP.DYN.LE00.IN     Life expectancy at birth, total (years)
  NY.GDP.PCAP.CD     GDP per capita (current US$)
  TX.VAL.TECH.MF.ZS  High-technology exports (% of manufactured exports)

Each indicator's own WDI metadata must say License_Type "CC BY-4.0"; an indicator with any other licence is
refused, so a licence change at the World Bank stops the run instead of being copied. Empty values are left out.
"""

import json

from ..http import fetch

KEY = "worldbank_health_indicators"
FIELDS = ["indicator_code", "indicator", "country_code", "country", "is_aggregate", "region", "income_level", "year",
          "value", "obs_status", "last_updated"]
INDICATORS = ["SH.XPD.CHEX.GD.ZS", "SH.XPD.CHEX.PC.CD", "SP.POP.TOTL", "SP.POP.65UP.TO.ZS", "SP.DYN.LE00.IN",
              "NY.GDP.PCAP.CD", "TX.VAL.TECH.MF.ZS"]
API = "https://api.worldbank.org/v2/"
FIRST_YEAR = 2000
LICENCE = "CC BY-4.0"


def fetch_raw() -> bytes:
    parts = {"countries": json.loads(fetch(f"{API}country?format=json&per_page=1000", timeout=120)),
             "data": {}, "meta": {}}
    for code in INDICATORS:
        parts["meta"][code] = json.loads(fetch(f"{API}sources/2/series/{code}/metadata?format=json", timeout=120))
        parts["data"][code] = json.loads(fetch(
            f"{API}country/all/indicator/{code}?format=json&source=2&date={FIRST_YEAR}:2100&per_page=30000", timeout=300))
    return json.dumps(parts).encode("utf-8")


def _meta(reply) -> dict:
    out = {}
    for v in reply["source"][0]["concept"][0]["variable"]:
        for m in v["metatype"]:
            out[m["id"]] = m["value"]
    return out


def parse(raw: bytes) -> list:
    parts = json.loads(raw)
    head, countries = parts["countries"]
    if len(countries) != int(head["total"]):
        raise RuntimeError("World Bank country list is incomplete")
    econ = {c["id"]: c for c in countries}
    by_iso2 = {c["iso2Code"]: c for c in countries}
    out = []
    for code in INDICATORS:
        meta = _meta(parts["meta"][code])
        if meta.get("License_Type") != LICENCE:
            raise RuntimeError(f"{code}: WDI licence is {meta.get('License_Type')!r}, not {LICENCE!r}; refused")
        page, rows = parts["data"][code]
        if int(page["pages"]) != 1 or len(rows) != int(page["total"]):
            raise RuntimeError(f"{code}: World Bank reply is paged or incomplete")
        for r in rows:
            if r["indicator"]["id"] != code:
                raise RuntimeError(f"unexpected indicator {r['indicator']['id']} in {code} reply")
            if r["value"] is None or int(r["date"]) < FIRST_YEAR:
                continue
            # income-group aggregates (High income etc.) come with an empty ISO3 code; match them by their 2-letter id
            c = econ.get(r["countryiso3code"]) or by_iso2.get(r["country"]["id"])
            iso3 = c["id"] if c else r["countryiso3code"]
            if c is None:
                raise RuntimeError(f"{code}: economy {iso3!r} not in the World Bank country list")
            agg = c["region"]["id"] == "NA"
            out.append({"indicator_code": code, "indicator": r["indicator"]["value"], "country_code": iso3,
                        "country": r["country"]["value"], "is_aggregate": "yes" if agg else "no",
                        "region": "" if agg else c["region"]["value"].strip(),
                        "income_level": "" if agg else c["incomeLevel"]["value"].strip(), "year": int(r["date"]),
                        "value": r["value"], "obs_status": r.get("obs_status") or "",
                        "last_updated": page.get("lastupdated", "")})
    if len(out) < 20000 and len(parts["data"]) == len(INDICATORS) and len(countries) > 200:
        raise RuntimeError(f"only {len(out)} World Bank values; refusing a partial dataset")
    out.sort(key=lambda x: (x["indicator_code"], x["country_code"], x["year"]))
    return out
