"""US FDA original approvals (Drugs@FDA via openFDA): every application whose ORIGINAL submission was approved
on or after FROM_DATE. One row per application. NDA, BLA and ANDA (generic) applications are all included,
with the application type in its own column.
"""

import json

from ..http import fetch
from ..util import iso_date

KEY = "fda_approvals"
FIELDS = ["application_number", "application_type", "sponsor_name", "brand_names", "active_ingredients",
          "dosage_forms", "routes", "approval_date", "review_priority", "submission_class"]
FROM_DATE = "20210101"
API = ("https://api.fda.gov/drug/drugsfda.json?search=submissions.submission_type:ORIG+AND+submissions.submission_status:AP"
       "+AND+submissions.submission_status_date:[{frm}+TO+20991231]&limit=1000&skip={skip}")


def fetch_raw(max_pages: int = 25) -> bytes:
    results, total = [], None
    for page in range(max_pages):
        j = json.loads(fetch(API.format(frm=FROM_DATE, skip=page * 1000), timeout=180))
        if total is None:
            total = j["meta"]["results"]["total"]
        results.extend(j.get("results", []))
        if len(results) >= total:
            break
    if len(results) != total:
        raise RuntimeError(f"openFDA returned {len(results)} of {total} applications")
    return json.dumps({"total": total, "results": results}).encode("utf-8")


def _uniq(items):
    seen, out = set(), []
    for i in items:
        if i and i not in seen:
            seen.add(i)
            out.append(i)
    return out


def parse(raw: bytes) -> list:
    out = []
    for r in json.loads(raw).get("results", []):
        # The search matches an application if ANY submission fits, so check the ORIG one ourselves.
        orig = [s for s in r.get("submissions", []) if s.get("submission_type") == "ORIG" and s.get("submission_status") == "AP"]
        if not orig:
            continue
        o = min(orig, key=lambda s: s.get("submission_status_date", "99999999"))
        if o.get("submission_status_date", "") < FROM_DATE:
            continue
        num = r.get("application_number", "")
        prods = r.get("products", [])
        out.append({
            "application_number": num,
            "application_type": "".join(ch for ch in num if ch.isalpha()),
            "sponsor_name": r.get("sponsor_name", ""),
            "brand_names": _uniq(p.get("brand_name", "") for p in prods),
            "active_ingredients": _uniq(a.get("name", "") for p in prods for a in p.get("active_ingredients", [])),
            "dosage_forms": _uniq(p.get("dosage_form", "") for p in prods),
            "routes": _uniq(p.get("route", "") for p in prods),
            "approval_date": iso_date(o.get("submission_status_date", "")),
            "review_priority": o.get("review_priority", ""),
            "submission_class": o.get("submission_class_code_description", ""),
        })
    out.sort(key=lambda r: (r["approval_date"], r["application_number"]), reverse=True)
    return out
