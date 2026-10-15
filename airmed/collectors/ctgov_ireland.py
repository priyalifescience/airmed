"""ClinicalTrials.gov API v2: every study with a site in Ireland (all statuses).

Only the fields below are requested from the API, so contacts, investigators and site addresses are never downloaded.
"""

import json
import re
import urllib.parse

from ..http import fetch

KEY = "ctgov_ireland"
FIELDS = ["nct_id", "title", "phases", "overall_status", "lead_sponsor", "conditions", "start_date", "last_update"]
API = "https://clinicaltrials.gov/api/v2/studies"
API_FIELDS = "NCTId,BriefTitle,Phase,OverallStatus,LeadSponsorName,LeadSponsorClass,Condition,StartDate,LastUpdatePostDate"

# Investigator-led studies often name a PERSON as lead sponsor, and Airmid never publishes personal names. Keep the
# sponsor only when ClinicalTrials.gov classes it as industry/government/network, or its name reads as an
# organisation; otherwise blank it. Over-blanking a small organisation is the accepted cost of never naming a person.
ORG_CLASSES = {"INDUSTRY", "NIH", "FED", "OTHER_GOV", "NETWORK"}
ORG_WORDS = re.compile(
    r"univers|hospital|h[oô]pital|ospedal|krankenhaus|klinik|clinic|kliniek|institut|istitut|trust|foundation|"
    r"fondation|fondazione|fundaci|stiftung|stichting|centre|center|centro|zentrum|council|minist|agency|agence|"
    r"department|college|school|faculty|group|gruppo|grupo|society|soci[eé]t|association|asociaci|network|"
    r"consorti|laborator|pharma|therapeut|bio|medic|health|sant[eé]|care|cancer|oncolog|research|science|service|"
    r"collaborat|alliance|federation|academ|nhs|\bhse\b|inserm|cnrs|ap-hp|assistance publique|charit[eé]|"
    r"karolinska|hospices|rigshospital|sjukhus|sykehus|ziekenhuis|szpital|nemocnic|ltd|limited|\binc\b|gmbh|"
    r"\bag\b|s\.?p\.?a\b|\bs\.?a\.?\b|\bsas\b|\bbv\b|b\.v\.|\bab\b|\bas\b|\boy\b|\bplc\b|\bllc\b|\bcorp|company|"
    r"\bnv\b|s\.?r\.?l\b|sarl|\bkft\b|\bdac\b|technolog|diagnost|device|system|solution|innovation|regional|"
    r"national|county|region|\buz\b|\bumc\b|\bchu\b|\bchru\b|\bihu\b|\birccs\b", re.I)


def sponsor_or_blank(name: str, cls: str) -> str:
    name = (name or "").strip()
    if not name:
        return ""
    if (cls or "").upper() in ORG_CLASSES or ORG_WORDS.search(name):
        return name
    return ""


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
        lead = p.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {})
        out.append({
            "nct_id": ident.get("nctId", ""),
            "title": ident.get("briefTitle", ""),
            "phases": p.get("designModule", {}).get("phases", []),
            "overall_status": status.get("overallStatus", ""),
            "lead_sponsor": sponsor_or_blank(lead.get("name", ""), lead.get("class", "")),
            "conditions": p.get("conditionsModule", {}).get("conditions", []),
            "start_date": status.get("startDateStruct", {}).get("date", ""),
            "last_update": status.get("lastUpdatePostDateStruct", {}).get("date", ""),
        })
    out.sort(key=lambda r: r["nct_id"])
    return out
