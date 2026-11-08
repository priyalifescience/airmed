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
# ResponsiblePartyType (only the type, never the investigator's name) tells us when the sponsor is the investigator.
API_FIELDS = ("NCTId,BriefTitle,Phase,OverallStatus,LeadSponsorName,LeadSponsorClass,ResponsiblePartyType,Condition,"
              "StartDate,LastUpdatePostDate")

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
    r"national|county|region|\buz\b|\bumc\b|\bchu\b|\bchru\b|\bihu\b|\birccs\b|"
    r"initiative|islamia|neglected disease|\bpath\b|\bdndi\b|\baiims\b|\bpgims\b|\bpgimer\b|\bicmr\b|aurolab|"
    r"sangath|columbia asia", re.I)


# 1.6.1 (audit 9 Nov 2026): the sponsor class is not reliable. Investigators who sponsor their own study are often
# classed OTHER_GOV or even INDUSTRY ("Katarina Hedin", "Prof. Dr. Thomas Forst"), so the class alone let names
# through. Three extra rules, checked before the class:
#  - a degree after a comma or semicolon ("Maja Kovacevic, MD", "Qinghua Xia,Prof", "X; PhD") is a person;
#  - a personal title (Dr, Prof, Mr, Ms...) with no organisation word is a person ("Dr Eoin R Hyde");
#  - when ClinicalTrials.gov says the responsible party is a SPONSOR_INVESTIGATOR, the sponsor is that person
#    unless the name carries an organisation word.
# Company names that contain a title are kept (BRANDS), as is any title followed by an organisation word
# ("Dr. Rajendra Prasad Government Medical College").
DEGREE_AFTER = re.compile(r"[,;]\s*(?:m\.?\s?d\b|ph\.?\s?d\b|mph\b|mbbs\b|frc[sp]\w*|pharm\.?\s?d\b|dds\b|"
                          r"prof\b|professor\b|chief physician\b|associate professor\b)", re.I)
PERSON_TITLE = re.compile(r"(?:^|[\s(,;])(?:dr|prof|professor|assoc\.?\s*prof|ass\.?\s*prof|asst\.?\s*prof|mr|mrs|ms|"
                          r"miss)\.?\s", re.I)
BRANDS = re.compile(r"dr\.?\s*reddy|dr\.?\s*falk|md anderson|dr\.?\s*willmar|dr\.?\s*august wolff|dr\.?\s*gerhard mann",
                    re.I)


def sponsor_or_blank(name: str, cls: str, responsible_party_type: str = "") -> str:
    name = (name or "").strip()
    if not name:
        return ""
    if BRANDS.search(name):
        return name
    if DEGREE_AFTER.search(name):
        return ""
    org_word = bool(ORG_WORDS.search(name))
    if PERSON_TITLE.search(" " + name) and not org_word:
        return ""
    if (responsible_party_type or "").upper() == "SPONSOR_INVESTIGATOR" and not org_word:
        return ""
    if (cls or "").upper() in ORG_CLASSES or org_word:
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
        scm = p.get("sponsorCollaboratorsModule", {})
        lead = scm.get("leadSponsor", {})
        rp_type = (scm.get("responsibleParty") or {}).get("type", "")
        out.append({
            "nct_id": ident.get("nctId", ""),
            "title": ident.get("briefTitle", ""),
            "phases": p.get("designModule", {}).get("phases", []),
            "overall_status": status.get("overallStatus", ""),
            "lead_sponsor": sponsor_or_blank(lead.get("name", ""), lead.get("class", ""), rp_type),
            "conditions": p.get("conditionsModule", {}).get("conditions", []),
            "start_date": status.get("startDateStruct", {}).get("date", ""),
            "last_update": status.get("lastUpdatePostDateStruct", {}).get("date", ""),
        })
    out.sort(key=lambda r: r["nct_id"])
    return out
