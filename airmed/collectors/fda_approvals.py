"""US FDA original approvals (Drugs@FDA via openFDA): every application whose ORIGINAL submission was approved,
for all years Drugs@FDA holds. One row per application. NDA, BLA and ANDA (generic) applications are all
included, with the application type in its own column.

The openFDA search API cannot page past skip=25,000 and more than 25,000 applications have an approved original
submission, so the collector reads openFDA's official bulk file for the drugsfda endpoint (one zipped JSON,
about 9 MB) instead, checks that it holds the number of records its own metadata and the download index state,
and keeps the applications with an approved ORIG submission.
"""

import io
import json
import zipfile

from ..http import fetch
from ..util import iso_date

KEY = "fda_approvals"
FIELDS = ["application_number", "application_type", "sponsor_name", "brand_names", "active_ingredients",
          "dosage_forms", "routes", "approval_date", "review_priority", "submission_class"]
DOWNLOAD_INDEX = "https://api.fda.gov/download.json"
BULK_PREFIX = "https://download.open.fda.gov/drug/drugsfda/"


def _is_orig_ap(s: dict) -> bool:
    return s.get("submission_type") == "ORIG" and s.get("submission_status") == "AP"


def _slim(r: dict) -> dict:
    """Keep only what parse() reads; the bulk file carries much more (every supplement, document links...)."""
    return {
        "application_number": r.get("application_number", ""),
        "sponsor_name": r.get("sponsor_name", ""),
        "products": [{"brand_name": p.get("brand_name", ""), "dosage_form": p.get("dosage_form", ""),
                      "route": p.get("route", ""),
                      "active_ingredients": [{"name": a.get("name", "")} for a in p.get("active_ingredients", [])]}
                     for p in r.get("products", [])],
        "submissions": [{k: s.get(k, "") for k in ("submission_type", "submission_status", "submission_status_date",
                                                   "review_priority", "submission_class_code_description")}
                        for s in r.get("submissions", []) if _is_orig_ap(s)],
    }


def fetch_raw() -> bytes:
    index = json.loads(fetch(DOWNLOAD_INDEX, timeout=120))["results"]["drug"]["drugsfda"]
    parts = index["partitions"]
    if len(parts) != 1 or not parts[0]["file"].startswith(BULK_PREFIX):
        raise RuntimeError(f"unexpected openFDA drugsfda download layout: {[p.get('file') for p in parts]}")
    z = zipfile.ZipFile(io.BytesIO(fetch(parts[0]["file"], timeout=300)))
    names = [n for n in z.namelist() if n.endswith(".json")]
    if len(names) != 1:
        raise RuntimeError(f"expected one JSON file in the drugsfda zip, found {names}")
    data = json.loads(z.read(names[0]))
    results = data.get("results", [])
    total = data["meta"]["results"]["total"]
    if len(results) != total or total != int(index["total_records"]):
        raise RuntimeError(f"drugsfda bulk file holds {len(results)} records; its metadata says {total}, "
                           f"the download index says {index['total_records']}")
    kept = [_slim(r) for r in results if any(_is_orig_ap(s) for s in r.get("submissions", []))]
    return json.dumps({"total_in_file": total, "last_updated": data["meta"].get("last_updated", ""),
                       "results": kept}).encode("utf-8")


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
        orig = [s for s in r.get("submissions", []) if _is_orig_ap(s)]
        if not orig:
            continue
        # earliest dated ORIG approval (an undated one only if none is dated)
        o = min(orig, key=lambda s: s.get("submission_status_date") or "99999999")
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
