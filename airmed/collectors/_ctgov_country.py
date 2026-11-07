"""Shared code for ClinicalTrials.gov collectors that select studies by site country (ctgov_india, ctgov_china).

Same kept fields and sponsor rule as ctgov_ireland, plus `countries`: every country with at least one site, as
ClinicalTrials.gov names it, so a reader can tell national studies from multinational ones. For locations only the
country is requested, so facility names, cities, contacts, investigators and coordinates are never downloaded.
"""

import json
import urllib.parse

from ..http import fetch
from . import ctgov_ireland

FIELDS = list(ctgov_ireland.FIELDS) + ["countries"]
API = ctgov_ireland.API
API_FIELDS = ctgov_ireland.API_FIELDS + ",LocationCountry"
PAGE_SIZE = 500


def filter_for(countries: tuple) -> str:
    return "AREA[LocationCountry](" + " OR ".join(f'"{c}"' for c in countries) + ")"


def page_url(countries: tuple, token: str = "") -> str:
    q = {"filter.advanced": filter_for(countries), "fields": API_FIELDS, "pageSize": str(PAGE_SIZE), "countTotal": "true"}
    if token:
        q["pageToken"] = token
    return API + "?" + urllib.parse.urlencode(q)


def fetch_raw(countries: tuple, max_pages: int = 400) -> bytes:
    """All pages, combined into one JSON document {"totalCount": n, "studies": [...]}."""
    studies, total, token = [], None, ""
    for _ in range(max_pages):
        page = json.loads(fetch(page_url(countries, token), timeout=120))
        if total is None:
            total = page.get("totalCount")
        studies.extend(page.get("studies", []))
        token = page.get("nextPageToken", "")
        if not token:
            break
    else:
        raise RuntimeError(f"ClinicalTrials.gov paging did not finish within {max_pages} pages")
    if total is not None and len(studies) != total:
        raise RuntimeError(f"ClinicalTrials.gov returned {len(studies)} of {total} studies; refusing a partial dataset")
    return json.dumps({"totalCount": total, "studies": studies}).encode("utf-8")


def _all_countries(study: dict) -> list:
    locs = study.get("protocolSection", {}).get("contactsLocationsModule", {}).get("locations", [])
    return sorted({loc.get("country", "") for loc in locs} - {""})


def parse(raw: bytes, countries: tuple) -> list:
    data = json.loads(raw)
    studies = data.get("studies", [])
    total = data.get("totalCount")
    if total is not None and total != len(studies):
        raise RuntimeError(f"file says {total} studies but holds {len(studies)}")
    by_id = {}
    for s in studies:
        nct = s.get("protocolSection", {}).get("identificationModule", {}).get("nctId", "")
        by_id[nct] = _all_countries(s)
    out = ctgov_ireland.parse(raw)  # same kept fields, sponsor rule and deterministic sort (by NCT id)
    if len({r["nct_id"] for r in out}) != len(out):
        raise RuntimeError("duplicate NCT ids in the download (the result set changed while paging); run again")
    wanted = set(countries)
    missing = [r["nct_id"] for r in out if not wanted & set(by_id.get(r["nct_id"], []))]
    if missing:
        raise RuntimeError(f"{len(missing)} studies have no site in {sorted(wanted)}, e.g. {missing[:5]}")
    for r in out:
        r["countries"] = by_id[r["nct_id"]]
    return out
