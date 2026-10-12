"""ClinicalTrials.gov API v2: every study with a site in Ireland (all statuses).

Only the fields below are requested from the API, so contacts, investigators and site addresses are never downloaded.
"""

import json
import urllib.parse

from ..http import fetch

KEY = "ctgov_ireland"
FIELDS = ["nct_id", "title", "phases", "overall_status", "lead_sponsor", "conditions", "start_date", "last_update"]
API = "https://clinicaltrials.gov/api/v2/studies"
API_FIELDS = "NCTId,BriefTitle,Phase,OverallStatus,LeadSponsorName,Condition,StartDate,LastUpdatePostDate"


def _page_url(token: str = "") -> str:
    q = {"filter.advanced": "AREA[LocationCountry]Ireland", "fields": API_FIELDS, "pageSize": "1000", "countTotal": "true"}
    if token:
        q["pageToken"] = token
    return API + "?" + urllib.parse.urlencode(q)


def fetch_raw(max_pages: int = 50) -> bytes:
    """All pages, combined into one JSON document {"totalCount": n, "studies": [...]}."""
    studies, total, token = [], None, ""
    for _ in range(max_pages):
        page = json.loads(fetch(_page_url(token)))
        if total is None:
            total = page.get("totalCount")
        studies.extend(page.get("studies", []))
        token = page.get("nextPageToken", "")
        if not token:
            break
    if total is not None and len(studies) != total:
        raise RuntimeError(f"ClinicalTrials.gov returned {len(studies)} of {total} studies; refusing a partial dataset")
    return json.dumps({"totalCount": total, "studies": studies}).encode("utf-8")


def parse(raw: bytes) -> list:
    data = json.loads(raw)
    out = []
    for s in data.get("studies", []):
        p = s.get("protocolSection", {})
        ident, status = p.get("identificationModule", {}), p.get("statusModule", {})
        out.append({
            "nct_id": ident.get("nctId", ""),
            "title": ident.get("briefTitle", ""),
            "phases": p.get("designModule", {}).get("phases", []),
            "overall_status": status.get("overallStatus", ""),
            "lead_sponsor": p.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {}).get("name", ""),
            "conditions": p.get("conditionsModule", {}).get("conditions", []),
            "start_date": status.get("startDateStruct", {}).get("date", ""),
            "last_update": status.get("lastUpdatePostDateStruct", {}).get("date", ""),
        })
    out.sort(key=lambda r: r["nct_id"])
    return out
