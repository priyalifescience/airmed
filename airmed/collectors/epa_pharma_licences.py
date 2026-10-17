"""EPA Ireland: industrial emissions (IE), IPPC and IPC licences for pharmaceutical manufacturing, from the EPA LEAP
open data API (https://data.epa.ie/leap/swagger).

One row per licence profile (the EPA's site-level record, e.g. P0004; each profile holds one or more licence
versions, e.g. P0004-01 ... P0004-06).

Filter (exact, applied to the profile's published activity fields):
  licence type is one of "Industrial Emissions Licence", "Integrated Pollution Prevention Control Licence",
  "Integrated Pollution Control Licence", AND
    major_class_of_activity is class 5.16 of the First Schedule to the EPA Act 1992 (as amended),
      "The production of pharmaceutical products including intermediates", OR class 5.6 (pre-2013 IPC wording),
      "The manufacture of pesticides, pharmaceuticals or veterinary products and their intermediates", OR
    ied_activity is Industrial Emissions Directive Annex I activity 4.5,
      "Production of pharmaceutical products including intermediates".
Biotech / biologics plants (WuXi Biologics, Regeneron, Amgen, MSD Biotech ...) are licensed under class 5.16; the
EPA publishes no separate biotechnology class. Class 5.6 also covers pesticide and veterinary manufacture.

Not downloaded: street address lines, full Eircodes (only the 3-character routing key is kept), financial
provision figures, documents, compliance records.
"""

import json
import re
import urllib.parse

from ..http import fetch
from ..util import iso_date

KEY = "epa_pharma_licences"
FIELDS = ["licence_profile", "licence_number", "licence_type", "licence_status", "licence_substatus", "licensee",
          "site_name", "county", "town", "eircode_routing_key", "sector", "activity_class", "activity_description",
          "ied_activity_class", "ied_activity_description", "nace_code", "first_licence_date",
          "current_licence_date", "licence_versions", "url"]
API = "https://data.epa.ie/leap/api/v1"
LICENCE_TYPES = ("Industrial Emissions Licence", "Integrated Pollution Prevention Control Licence",
                 "Integrated Pollution Control Licence")
PER_PAGE = 200
PHARMA_CLASSES = {"5.16", "5.6"}     # EPA Act First Schedule
PHARMA_IED = {"4.5"}                 # IED Annex I
PROFILE_URL = "https://leap.epa.ie/licence-profile/"

_CLASS_RE = re.compile(r"^\s*(\d+(?:\.\d+)*(?:\s*\([a-z]+\))*(?:\([ivx]+\))*)\.?\s*(.*)$", re.S)
_EIRCODE_RE = re.compile(r"^\s*([AC-FHKNPRTV-Y]\d{2}|D6W)\s?[0-9AC-FHKNPRTV-Y]{4}\s*$", re.I)
_TITLE_RE = re.compile(r"(^|[\s,&])(mr|mrs|ms|miss|dr|prof)\.?\s", re.I)
_ORG_WORDS = re.compile(
    r"limited|\bltd\b|unlimited|\buc\b|\bdac\b|\bplc\b|\binc\b|gmbh|\bb\.?v\b|\bs\.?a\b|\bag\b|\bllc\b|company|"
    r"teoranta|\bteo\b|corporation|\bcorp\b|partners|group|pharma|chemical|laborator|biolog|biotech|vaccin|"
    r"health|scien|technolog|manufactur|international|industr|ireland|irish|operations|trading as|\bt/a\b", re.I)


def split_class(text: str) -> tuple:
    """'5.16. The production of ...' -> ('5.16', 'The production of ...'); 'n/a' or empty -> ('', '')."""
    t = (text or "").strip()
    if not t or t.lower() == "n/a":
        return "", ""
    m = _CLASS_RE.match(t)
    if not m:
        return "", t
    return re.sub(r"\s+", " ", m[1]).strip(), m[2].strip()


def routing_key(eircode: str) -> str:
    """Full Eircode -> its 3-character routing key. Anything else (e.g. a bare Dublin district '15') -> ''."""
    m = _EIRCODE_RE.match(eircode or "")
    return m[1].upper() if m else ""


def org_or_blank(name: str) -> str:
    """Keep company / organisation names; blank anything that reads as a person (Charter: no personal names)."""
    n = re.sub(r"\s+", " ", name or "").strip()
    if not n or _TITLE_RE.search(n) or not _ORG_WORDS.search(n):
        return ""
    return n


def _base_class(code: str) -> str:
    """'5.12 (b)' -> '5.12'."""
    return code.split("(")[0].strip()


def is_pharma(profile: dict) -> bool:
    major = _base_class(split_class(profile.get("major_class_of_activity"))[0])
    ied = _base_class(split_class(profile.get("ied_activity"))[0])
    return major in PHARMA_CLASSES or ied in PHARMA_IED


def _get(path: str, **params):
    return json.loads(fetch(f"{API}/{path}?" + urllib.parse.urlencode(params)))


def fetch_raw(max_pages: int = 20) -> bytes:
    """Every IE/IPPC/IPC licence profile (activity fields included), plus, for the pharmaceutical ones only, the
    site record (NACE code, town, Eircode routing key) and the licence version list."""
    profiles = {}
    for ltype in LICENCE_TYPES:
        rows, total = [], None
        for page in range(1, max_pages + 1):
            j = _get("LicenceProfile/licenceprofilesearchlist", licence_type_filter=ltype, page=page, per_page=PER_PAGE)
            total = j.get("count") if total is None else total
            batch = j.get("list") or []
            rows.extend(batch)
            if not batch or len(rows) >= total:
                break
        if total is None or len(rows) != total:
            raise RuntimeError(f"LEAP returned {len(rows)} of {total} '{ltype}' profiles; refusing a partial dataset")
        profiles[ltype] = {"count": total, "list": rows}

    sites, licences = {}, {}
    for ltype in LICENCE_TYPES:
        for p in profiles[ltype]["list"]:
            if not is_pharma(p):
                continue
            pn, pid = p["profile_number"], p["licence_profile_id"]
            s = _get("Site/byprofileid", licence_profile_id=pid) or {}
            # keep only what parse() uses: never street address lines or the full Eircode
            sites[pn] = {"nacecode": s.get("nacecode"), "city": s.get("city"),
                         "eircode_routing_key": routing_key(s.get("eircode"))}
            lic = _get("Licence/listbyprofileid", licence_profile_id=pid)
            licences[pn] = {"count": lic.get("count"),
                            "list": [{k: v.get(k) for k in ("reg_no", "licence_type", "date_of_licence", "licence_status")}
                                     for v in lic.get("list") or []]}
    return json.dumps({"profiles": profiles, "sites": sites, "licences": licences}).encode("utf-8")


def parse(raw: bytes) -> list:
    data = json.loads(raw)
    sites, licences = data.get("sites", {}), data.get("licences", {})
    out, seen = [], set()
    for ltype, block in data.get("profiles", {}).items():
        rows = block.get("list") or []
        if block.get("count") is not None and block["count"] != len(rows):
            raise RuntimeError(f"LEAP says {block['count']} '{ltype}' profiles but the download holds {len(rows)}")
        for p in rows:
            pn = p.get("profile_number") or ""
            if not is_pharma(p) or pn in seen:
                continue
            seen.add(pn)
            site = sites.get(pn) or {}
            lic = licences.get(pn) or {}
            versions = lic.get("list") or []
            if lic.get("count") is not None and lic["count"] != len(versions):
                raise RuntimeError(f"LEAP says {pn} has {lic['count']} licence versions but the download holds {len(versions)}")
            dates = sorted(iso_date(v.get("date_of_licence") or "") for v in versions if v.get("date_of_licence"))
            regno = p.get("active_licence_regno") or ""
            current = next((v for v in versions if v.get("reg_no") == regno), {})
            major_code, major_desc = split_class(p.get("major_class_of_activity"))
            ied_code, ied_desc = split_class(p.get("ied_activity"))
            name = re.sub(r"\s+-\s+" + re.escape(pn) + r"\s*$", "", p.get("name") or "") if pn else (p.get("name") or "")
            town = (site.get("city") or p.get("town") or "").strip()
            out.append({
                "licence_profile": pn,
                "licence_number": regno,
                "licence_type": p.get("active_licence_type") or "",
                "licence_status": p.get("active_licence_status") or "",
                "licence_substatus": p.get("active_licence_substatus") or "",
                "licensee": org_or_blank(p.get("organisation_name")),
                "site_name": org_or_blank(name),
                "county": (p.get("county") or "").strip(),
                "town": town,
                "eircode_routing_key": site.get("eircode_routing_key") or "",
                "sector": p.get("active_licence_sector") or "",
                "activity_class": major_code,
                "activity_description": major_desc,
                "ied_activity_class": ied_code,
                "ied_activity_description": ied_desc,
                "nace_code": (site.get("nacecode") or "").strip(),
                "first_licence_date": dates[0] if dates else "",
                "current_licence_date": iso_date(current.get("date_of_licence") or p.get("active_licence_startdate") or ""),
                "licence_versions": len(versions),
                "url": PROFILE_URL + urllib.parse.quote(pn) if pn else "",
            })
    out.sort(key=lambda r: r["licence_profile"])
    return out
