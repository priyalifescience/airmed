"""MHRA (UK) drug and device alerts and Drug Safety Update articles, from the GOV.UK Search API.

Two GOV.UK document types are collected, both published by the MHRA:
  medical_safety_alert  (gov.uk/drug-device-alerts: recalls, defect notifications, device and patient safety alerts)
  drug_safety_update    (gov.uk/drug-safety-update: the MHRA's Drug Safety Update articles)
Only listing metadata is requested (title, short description, dates, alert type, specialties), never the page body.
"""

import json
import re
import urllib.parse

from ..http import fetch
from ..util import iso_date

KEY = "mhra_safety_alerts"
FIELDS = ["url", "document_type", "title", "alert_type", "alert_class", "issued_date", "updated_date",
          "description", "specialties"]
API = "https://www.gov.uk/api/search.json"
DOC_TYPES = ("medical_safety_alert", "drug_safety_update")
API_FIELDS = ("title,link,description,public_timestamp,first_published_at,issued_date,alert_type,"
              "medical_specialism,therapeutic_area,content_store_document_type")
PAGE = 500
_CLASS_RE = re.compile(r"\bClass\s+([1-4])\b", re.I)


def _page_url(doc_type: str, start: int) -> str:
    q = {"filter_content_store_document_type": doc_type, "count": str(PAGE), "start": str(start),
         "order": "public_timestamp", "fields": API_FIELDS}
    return API + "?" + urllib.parse.urlencode(q)


def fetch_raw(max_pages: int = 20) -> bytes:
    """All results of both document types, as {"totals": {type: n}, "results": [...]}."""
    totals, results = {}, []
    for doc_type in DOC_TYPES:
        got = []
        for page in range(max_pages):
            j = json.loads(fetch(_page_url(doc_type, page * PAGE)))
            totals.setdefault(doc_type, j.get("total"))
            batch = j.get("results", [])
            got.extend(batch)
            if not batch or len(got) >= totals[doc_type]:
                break
        if len(got) != totals[doc_type]:
            raise RuntimeError(f"GOV.UK search returned {len(got)} of {totals[doc_type]} {doc_type} documents")
        for r in got:
            r["_doc_type"] = doc_type
        results.extend(got)
    return json.dumps({"totals": totals, "results": results}).encode("utf-8")


def parse(raw: bytes) -> list:
    data = json.loads(raw)
    totals, rows = data.get("totals", {}), data.get("results", [])
    for doc_type, n in totals.items():
        have = sum(1 for r in rows if r.get("_doc_type") == doc_type)
        if n is not None and have != n:
            raise RuntimeError(f"GOV.UK says {n} {doc_type} documents but the download holds {have}")
    out, seen = [], set()
    for r in rows:
        link = r.get("link", "")
        if not link or link in seen:
            continue
        seen.add(link)
        doc_type = r.get("_doc_type") or r.get("content_store_document_type", "")
        title = (r.get("title") or "").strip()
        m = _CLASS_RE.search(title)
        issued = r.get("issued_date") or r.get("first_published_at") or r.get("public_timestamp") or ""
        out.append({
            "url": "https://www.gov.uk" + link if link.startswith("/") else link,
            "document_type": doc_type,
            "title": title,
            "alert_type": list(r.get("alert_type") or []),
            "alert_class": f"Class {m[1]}" if m else "",
            "issued_date": iso_date(issued),
            "updated_date": iso_date(r.get("public_timestamp") or ""),
            "description": (r.get("description") or "").strip(),
            "specialties": sorted(r.get("medical_specialism") or r.get("therapeutic_area") or []),
        })
    out.sort(key=lambda r: r["url"])
    out.sort(key=lambda r: r["issued_date"], reverse=True)   # newest first, ties by URL
    return out
