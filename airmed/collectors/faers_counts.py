"""FDA Adverse Event Reporting System (FAERS) via openFDA: AGGREGATE report counts only, never case-level data.

For each year since 2015 (by the date FDA received the report):
  - one `year_total` row: all reports, serious reports, and reports flagged with each seriousness outcome;
  - `drug` rows for the TOP_N generic names named most often in that year's reports, with how many of those reports
    were serious or flagged as death.
Only openFDA `count=` queries are used; no individual report is downloaded.

Counts are reports, not proven side effects. Read the FDA disclaimer kept in the registry entry.
"""

import datetime
import json
import time

from ..http import fetch

KEY = "faers_counts"
FIELDS = ["year", "row_type", "rank", "drug_generic_name", "reports", "serious_reports", "death_reports",
          "hospitalisation_reports", "life_threatening_reports", "disabling_reports", "congenital_anomaly_reports",
          "other_serious_reports", "source_last_updated"]
FIRST_YEAR = 2015
TOP_N = 100
CUTOFF = 500        # per-year serious/death drug lists; openFDA refuses count limits of 1,000+ without an API key
DRUG = "patient.drug.openfda.generic_name.exact"
API = "https://api.fda.gov/drug/event.json?search={search}"
FLAGS = {"death_reports": "seriousnessdeath", "hospitalisation_reports": "seriousnesshospitalization",
         "life_threatening_reports": "seriousnesslifethreatening", "disabling_reports": "seriousnessdisabling",
         "congenital_anomaly_reports": "seriousnesscongenitalanomali", "other_serious_reports": "seriousnessother"}
EXTRA_PAUSE = 0.5   # on top of http.PAUSE_SECONDS: openFDA without a key allows 240 calls/min, 1,000/day


def _get(search: str, tail: str) -> dict:
    time.sleep(EXTRA_PAUSE)
    try:
        return json.loads(fetch(API.format(search=search) + tail, timeout=120))
    except Exception as e:   # openFDA answers 404 when a count has no matches
        if getattr(e, "code", None) == 404:
            return {"results": [], "meta": {"results": {"total": 0}}}
        raise


def _count_map(j: dict) -> dict:
    return {str(r["term"]): r["count"] for r in j.get("results", [])}


def fetch_raw(last_year: int = None) -> bytes:
    """About 11 openFDA calls per year (about 130 in all)."""
    last_year = last_year or datetime.date.today().year
    years, last_updated = {}, ""
    for y in range(FIRST_YEAR, last_year + 1):
        rng = f"receivedate:%5B{y}0101+TO+{y}1231%5D"
        total = _get(rng, "&limit=1")
        last_updated = total.get("meta", {}).get("last_updated", last_updated)
        yr = {"total": total.get("meta", {}).get("results", {}).get("total", 0),
              "serious": _count_map(_get(rng, "&count=serious")),
              "flags": {k: _count_map(_get(rng, f"&count={f}")).get("1", 0) for k, f in FLAGS.items()},
              "drugs": _get(rng, f"&count={DRUG}&limit={TOP_N}").get("results", []),
              "drugs_serious": _count_map(_get(rng + "+AND+serious:1", f"&count={DRUG}&limit={CUTOFF}")),
              "drugs_death": _count_map(_get(rng + "+AND+seriousnessdeath:1", f"&count={DRUG}&limit={CUTOFF}"))}
        years[str(y)] = yr
    return json.dumps({"last_updated": last_updated, "years": years}).encode("utf-8")


def parse(raw: bytes) -> list:
    data = json.loads(raw)
    updated = data.get("last_updated", "")
    out = []
    for year, yr in sorted(data.get("years", {}).items()):
        serious = yr.get("serious", {})
        # reports are coded serious=1 or serious=2; a handful lack the code, so the two must add up to the year's
        # total within 2% (0.7% uncoded in 2025; a bigger gap means a truncated or broken reply)
        coded, total = sum(serious.values()), yr.get("total") or 0
        if total and not (0 <= total - coded <= total * 0.02):
            raise RuntimeError(f"FAERS {year}: serious counts {coded} do not match total {total}")
        if not yr.get("total"):
            continue
        row = {f: "" for f in FIELDS}
        row.update({"year": int(year), "row_type": "year_total", "rank": "", "reports": yr["total"],
                    "serious_reports": serious.get("1", 0), "source_last_updated": updated, **yr.get("flags", {})})
        out.append(row)
        for i, d in enumerate(yr.get("drugs", [])[:TOP_N], start=1):
            name = str(d["term"])
            row = {f: "" for f in FIELDS}
            # a drug outside the top CUTOFF for serious/death in that year gets "" (count below that cut-off, not 0)
            row.update({"year": int(year), "row_type": "drug", "rank": i, "drug_generic_name": name,
                        "reports": d["count"], "serious_reports": yr.get("drugs_serious", {}).get(name, ""),
                        "death_reports": yr.get("drugs_death", {}).get(name, ""), "source_last_updated": updated})
            out.append(row)
    out.sort(key=lambda r: (r["year"], r["row_type"] != "year_total", r["rank"] or 0, r["drug_generic_name"]))
    return out
