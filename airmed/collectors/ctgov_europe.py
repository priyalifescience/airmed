"""ClinicalTrials.gov API v2: studies with at least one site in Europe (EU-27, UK, Norway, Iceland, Switzerland,
Liechtenstein) that started on or after 1 January 2015.

Why the 2015 window: all European studies (about 169,000 in Oct 2026) come to about 38 MB of CSV, right at the
project's ~40 MB limit, and growing. Studies starting from 2015 (about 113,000; about 25 MB) cover the modern era of
European trials (the EU Clinical Trials Regulation 536/2014 and everything since) and leave room to grow. Studies with
no start date on record are not matched by the date filter. Ireland's full history stays in ctgov_ireland.

Only the fields below are requested. For locations only the country is requested, so facility names, contacts,
investigators and addresses are never downloaded. The kept `countries` field lists only the European countries.
"""

import json
import urllib.parse

from ..http import fetch
from . import ctgov_ireland

KEY = "ctgov_europe"
FIELDS = list(ctgov_ireland.FIELDS) + ["countries"]
API = ctgov_ireland.API
API_FIELDS = ctgov_ireland.API_FIELDS + ",LocationCountry"
START_FROM = "2015-01-01"
PAGE_SIZE = 500

# Names exactly as ClinicalTrials.gov writes them. "Czech Republic" is kept as an alias in case older records use it.
EUROPE = (
    "Austria", "Belgium", "Bulgaria", "Croatia", "Cyprus", "Czechia", "Czech Republic", "Denmark", "Estonia", "Finland",
    "France", "Germany", "Greece", "Hungary", "Ireland", "Italy", "Latvia", "Lithuania", "Luxembourg", "Malta",
    "Netherlands", "Poland", "Portugal", "Romania", "Slovakia", "Slovenia", "Spain", "Sweden",
    "United Kingdom", "Norway", "Iceland", "Switzerland", "Liechtenstein",
)
_EUROPE_SET = set(EUROPE)


def _filter() -> str:
    countries = " OR ".join(f'"{c}"' for c in EUROPE)
    return f"AREA[LocationCountry]({countries}) AND AREA[StartDate]RANGE[{START_FROM},MAX]"


def _page_url(token: str = "") -> str:
    q = {"filter.advanced": _filter(), "fields": API_FIELDS, "pageSize": str(PAGE_SIZE), "countTotal": "true"}
    if token:
        q["pageToken"] = token
    return API + "?" + urllib.parse.urlencode(q)


def fetch_raw(max_pages: int = 600) -> bytes:
    """All pages, combined into one JSON document {"totalCount": n, "studies": [...]}."""
    studies, total, token = [], None, ""
    for _ in range(max_pages):
        page = json.loads(fetch(_page_url(token), timeout=120))
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


def _countries(study: dict) -> list:
    locs = study.get("protocolSection", {}).get("contactsLocationsModule", {}).get("locations", [])
    found = {loc.get("country", "") for loc in locs}
    return sorted(("Czechia" if c == "Czech Republic" else c) for c in found if c in _EUROPE_SET)


def parse(raw: bytes) -> list:
    data = json.loads(raw)
    studies = data.get("studies", [])
    total = data.get("totalCount")
    if total is not None and total != len(studies):
        raise RuntimeError(f"file says {total} studies but holds {len(studies)}")
    countries = {}
    for s in studies:
        nct = s.get("protocolSection", {}).get("identificationModule", {}).get("nctId", "")
        countries[nct] = _countries(s)
    out = ctgov_ireland.parse(raw)  # same kept fields and the same deterministic sort (by NCT id)
    if len({r["nct_id"] for r in out}) != len(out):
        raise RuntimeError("duplicate NCT ids in the download (the result set changed while paging); run again")
    missing = [r["nct_id"] for r in out if not countries.get(r["nct_id"])]
    if missing:
        raise RuntimeError(f"{len(missing)} studies have no recognised European country, e.g. {missing[:5]}; "
                           "check the country names in EUROPE")
    for r in out:
        r["countries"] = countries[r["nct_id"]]
    return out
