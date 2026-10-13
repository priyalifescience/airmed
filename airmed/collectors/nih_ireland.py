"""NIH RePORTER: US National Institutes of Health awards to organisations in Ireland, fiscal years 2014 onwards.

Principal investigators' names are never requested.
"""

import datetime as dt
import json

from ..http import fetch

KEY = "nih_ireland"
FIELDS = ["project_number", "fiscal_year", "organisation", "city", "award_usd", "institute", "activity_code",
          "project_title", "project_start", "project_end"]
URL = "https://api.reporter.nih.gov/v2/projects/search"
INCLUDE = ["ProjectNum", "FiscalYear", "Organization", "AwardAmount", "ProjectTitle", "AgencyIcAdmin", "ActivityCode",
           "ProjectStartDate", "ProjectEndDate"]


def fetch_raw(page_size: int = 500, max_pages: int = 20) -> bytes:
    years = list(range(2014, dt.date.today().year + 1))
    results, total = [], None
    for page in range(max_pages):
        body = {"criteria": {"org_countries": ["IRELAND"], "fiscal_years": years}, "include_fields": INCLUDE,
                "offset": page * page_size, "limit": page_size}
        j = json.loads(fetch(URL, timeout=120, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"}))
        if total is None:
            total = j["meta"]["total"]
        results.extend(j.get("results", []))
        if len(results) >= total:
            break
    if len(results) != total:
        raise RuntimeError(f"NIH RePORTER returned {len(results)} of {total} projects")
    return json.dumps({"total": total, "results": results}).encode("utf-8")


def parse(raw: bytes) -> list:
    out = []
    for r in json.loads(raw).get("results", []):
        org = r.get("organization") or {}
        ic = r.get("agency_ic_admin") or {}
        out.append({
            "project_number": r.get("project_num", ""),
            "fiscal_year": r.get("fiscal_year", ""),
            "organisation": org.get("org_name", ""),
            "city": org.get("org_city") or "",
            "award_usd": r.get("award_amount") if r.get("award_amount") is not None else "",
            "institute": ic.get("abbreviation", ""),
            "activity_code": r.get("activity_code", ""),
            "project_title": r.get("project_title", ""),
            "project_start": (r.get("project_start_date") or "")[:10],
            "project_end": (r.get("project_end_date") or "")[:10],
        })
    out.sort(key=lambda r: (r["fiscal_year"], r["project_number"]), reverse=True)
    return out
