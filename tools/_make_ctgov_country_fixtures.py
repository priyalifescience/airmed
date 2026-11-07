"""One-off helper (not shipped in releases' code path): build small offline fixtures for ctgov_india / ctgov_china
from real ClinicalTrials.gov records: one national study, one multinational study, one whose lead sponsor ClinicalTrials.gov
classes OTHER (exercises the sponsor rule).   python tools/_make_ctgov_country_fixtures.py
"""
import json
import urllib.parse
import urllib.request

from airmed.collectors import _ctgov_country as base


def get(flt):
    q = {"filter.advanced": flt, "fields": base.API_FIELDS, "pageSize": "50"}
    req = urllib.request.Request(base.API + "?" + urllib.parse.urlencode(q), headers={"User-Agent": "airmid-fixture"})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())["studies"]


for key, country in (("ctgov_india", "India"), ("ctgov_china", "China")):
    studies = get(base.filter_for((country,)) + " AND AREA[StartDate]RANGE[2024-01-01,MAX]")
    def ncountries(s):
        return len({l.get("country") for l in s["protocolSection"].get("contactsLocationsModule", {}).get("locations", [])})
    national = next(s for s in studies if ncountries(s) == 1)
    multi = next(s for s in studies if ncountries(s) > 2)
    other = next(s for s in studies if s["protocolSection"].get("sponsorCollaboratorsModule", {}).get("leadSponsor", {}).get("class") == "OTHER" and s not in (national, multi))
    picked = [national, multi, other]
    for s in picked:  # keep only the country of each site (the API already returns nothing else for locations)
        m = s["protocolSection"].get("contactsLocationsModule", {})
        m["locations"] = [{"country": l.get("country")} for l in m.get("locations", [])]
    out = {"totalCount": len(picked), "studies": picked}
    with open(f"tests/fixtures/{key}.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(key, [s["protocolSection"]["identificationModule"]["nctId"] for s in picked])
