"""US CMS NADAC (National Average Drug Acquisition Cost): the latest weekly NADAC file, one row per NDC.

NADAC is CMS's weekly survey-based average price US retail pharmacies pay to acquire a drug, per pricing unit.
data.medicaid.gov publishes one dataset per calendar year, each holding every weekly file of that year (2026 alone is
over 1.2 million rows, about 30,000 NDCs a week). 52 weeks would be about 1.6 million rows (well over the 40 MB size
rule), so this collector keeps the most recent weekly file only: the current NADAC for every NDC CMS prices, with
the date that price took effect (`effective_date`), so recent price changes stay visible.

The newest yearly dataset is found through the data.medicaid.gov catalogue search; if it has no rows yet (early
January), the previous year's dataset is used.
"""

import json
import re
import urllib.parse

from ..http import fetch

KEY = "nadac_prices"
FIELDS = ["ndc", "ndc_description", "nadac_per_unit", "pricing_unit", "effective_date", "pharmacy_type_indicator", "otc",
          "classification_for_rate_setting", "explanation_code", "corresponding_generic_drug_nadac_per_unit",
          "corresponding_generic_drug_effective_date", "as_of_date"]
SEARCH = "https://data.medicaid.gov/api/1/search?" + urllib.parse.urlencode(
    {"fulltext": "NADAC National Average Drug Acquisition Cost", "page-size": "50"})
QUERY = "https://data.medicaid.gov/api/1/datastore/query/{id}/0?"
TITLE = re.compile(r"^NADAC \(National Average Drug Acquisition Cost\) (\d{4})$")
PAGE = 2000


def _yearly_datasets() -> list:
    """[(year, dataset_id)] newest first."""
    res = json.loads(fetch(SEARCH)).get("results", {})
    items = res.values() if isinstance(res, dict) else res
    found = []
    for d in items:
        m = TITLE.match((d.get("title") or "").strip())
        if m and d.get("identifier"):
            found.append((int(m.group(1)), d["identifier"]))
    if not found:
        raise RuntimeError("data.medicaid.gov search found no yearly NADAC dataset")
    return sorted(found, reverse=True)


def _query(dataset_id: str, params: dict) -> dict:
    return json.loads(fetch(QUERY.format(id=dataset_id) + urllib.parse.urlencode(params), timeout=120))


def _latest_as_of(dataset_id: str) -> str:
    j = _query(dataset_id, {"limit": "1", "results": "true", "count": "false", "schema": "false", "properties[0]": "as_of_date",
                            "sorts[0][property]": "as_of_date", "sorts[0][order]": "desc"})
    rows = j.get("results", [])
    return rows[0]["as_of_date"] if rows else ""


def fetch_raw() -> bytes:
    """The latest weekly file as one JSON document {"dataset": id, "year": y, "as_of_date": d, "count": n, "rows": [...]}."""
    for year, dataset_id in _yearly_datasets()[:2]:
        as_of = _latest_as_of(dataset_id)
        if as_of:
            break
    else:
        raise RuntimeError("the newest NADAC datasets hold no rows")
    rows, total = [], None
    for page in range(100):
        j = _query(dataset_id, {"limit": str(PAGE), "offset": str(page * PAGE), "count": "true", "results": "true",
                                "schema": "false", "keys": "true",
                                "conditions[0][property]": "as_of_date", "conditions[0][value]": as_of,
                                "conditions[0][operator]": "=",
                                "sorts[0][property]": "ndc", "sorts[0][order]": "asc"})
        if total is None:
            total = j.get("count")
        batch = j.get("results", [])
        rows.extend(batch)
        if not batch or len(rows) >= (total or 0):
            break
    if total is None or len(rows) != total:
        raise RuntimeError(f"NADAC returned {len(rows)} of {total} rows for {as_of}; refusing a partial dataset")
    return json.dumps({"dataset": dataset_id, "year": year, "as_of_date": as_of, "count": total, "rows": rows}).encode("utf-8")


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def parse(raw: bytes) -> list:
    data = json.loads(raw)
    rows = data.get("rows", [])
    if data.get("count") is not None and data["count"] != len(rows):
        raise RuntimeError(f"NADAC file says {data['count']} rows but holds {len(rows)}")
    out, seen = [], set()
    for r in rows:
        ndc = _s(r.get("ndc"))
        key = tuple(sorted((k, _s(v)) for k, v in r.items()))   # drop only exact repeats, never a differing price
        if not ndc or key in seen:
            continue
        seen.add(key)
        out.append({
            "ndc": ndc,
            "ndc_description": _s(r.get("ndc_description")),
            "nadac_per_unit": _s(r.get("nadac_per_unit")),
            "pricing_unit": _s(r.get("pricing_unit")),
            "effective_date": _s(r.get("effective_date")),
            "pharmacy_type_indicator": _s(r.get("pharmacy_type_indicator")),
            "otc": _s(r.get("otc")),
            "classification_for_rate_setting": _s(r.get("classification_for_rate_setting")),
            "explanation_code": _s(r.get("explanation_code")),
            "corresponding_generic_drug_nadac_per_unit": _s(r.get("corresponding_generic_drug_nadac_per_unit")),
            "corresponding_generic_drug_effective_date": _s(r.get("corresponding_generic_drug_effective_date")),
            "as_of_date": _s(r.get("as_of_date")),
        })
    out.sort(key=lambda x: (x["ndc_description"].lower(), x["ndc"], x["pharmacy_type_indicator"], x["pricing_unit"]))
    return out
