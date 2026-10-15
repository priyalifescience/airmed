"""OpenAlex: scholarly works from 2015 onwards with at least one author affiliation in Ireland, in pharmacology,
pharmaceutical science, toxicology, drug discovery and medicinal chemistry.

Filter (two disjoint OpenAlex queries, both restricted to institutions.country_code:IE and
from_publication_date:2015-01-01):
  field30     any of the work's OpenAlex topics (up to three per work) lies in the field "Pharmacology, Toxicology
              and Pharmaceutics" (fields/30: subfields Pharmaceutical Science, Pharmacology, Toxicology,
              Drug Discovery, and the general subfield)
  medchem     the work has the topic "Computational Drug Discovery Methods" (T10211) or "Synthesis and biological
              activity" (T10274), the two medicinal-chemistry / drug-discovery topics OpenAlex files outside
              field 30, and has no field-30 topic (so the two queries never overlap)

Works whose title contains a phone number or email address are dropped: in practice these are spam deposits
(e.g. pill adverts) that list an Irish affiliation, not research.

Work-level fields only. Author names, author ids and ORCIDs are dropped inside fetch_raw (only the institutions of
each authorship are kept in the raw file), so they are never stored.
"""

import json
import urllib.parse

from ..http import fetch
from ..privacy import EMAIL_RE, PHONE_RE

KEY = "openalex_ireland_pharma"
FIELDS = ["openalex_id", "doi", "title", "publication_year", "publication_date", "type", "venue", "oa_status",
          "is_oa", "cited_by_count", "irish_institutions", "primary_topic", "primary_subfield", "matched_topics",
          "filter_basis", "is_retracted"]

API = "https://api.openalex.org/works"
MAILTO = "info@priyalifescience.com"
BASE_FILTER = "institutions.country_code:IE,from_publication_date:2015-01-01"
MEDCHEM_TOPICS = ("T10211", "T10274")
QUERIES = {
    "field30": BASE_FILTER + ",topics.field.id:30",
    "medchem": BASE_FILTER + ",topics.id:" + "|".join(MEDCHEM_TOPICS) + ",topics.field.id:!30",
}
SELECT = ("id,doi,title,publication_year,publication_date,type,primary_location,open_access,cited_by_count,"
          "authorships,primary_topic,topics,is_retracted")
PER_PAGE = 200


MAX_RESULTS = 10000   # OpenAlex page-number paging stops at 10,000 results per query


def _url(flt: str, page: int) -> str:
    q = {"filter": flt, "select": SELECT, "per_page": str(PER_PAGE), "page": str(page), "mailto": MAILTO}
    return API + "?" + urllib.parse.urlencode(q, safe=":,|!*")


def _strip(work: dict, basis: str) -> dict:
    """Keep only institutions from authorships: no author names, ids or ORCIDs leave this function."""
    insts = []
    for a in work.get("authorships") or []:
        for i in a.get("institutions") or []:
            insts.append({"display_name": i.get("display_name") or "", "country_code": i.get("country_code") or ""})
    w = {k: work.get(k) for k in ("id", "doi", "title", "publication_year", "publication_date", "type",
                                  "open_access", "cited_by_count", "primary_topic", "topics", "is_retracted")}
    src = ((work.get("primary_location") or {}).get("source") or {})
    w["venue"] = src.get("display_name") or ""
    w["institutions"] = insts
    w["filter_basis"] = basis
    return w


def fetch_raw(max_pages: int = 60) -> bytes:
    """Page-number paging (OpenAlex now needs an API key for cursor paging; we use none). Each page is fetched
    in OpenAlex's default order; duplicates across pages are dropped and the unique count must equal the total."""
    works, counts = [], {}
    for basis, flt in QUERIES.items():
        got, ids, total = [], set(), None
        for n in range(1, max_pages + 1):
            page = json.loads(fetch(_url(flt, n), timeout=120))
            if total is None:
                total = page["meta"]["count"]
                if total > MAX_RESULTS:
                    raise RuntimeError(f"OpenAlex query {basis} has {total} works, above the {MAX_RESULTS} paging limit")
            for w in page.get("results", []):
                if w.get("id") not in ids:
                    ids.add(w.get("id"))
                    got.append(_strip(w, basis))
            if not page.get("results") or n * PER_PAGE >= total:
                break
        if len(got) != total:
            raise RuntimeError(f"OpenAlex query {basis} returned {len(got)} unique of {total} works")
        counts[basis] = total
        works.extend(got)
    return json.dumps({"counts": counts, "filters": QUERIES, "works": works}, ensure_ascii=False).encode("utf-8")


def _short(oa_id: str) -> str:
    return (oa_id or "").rsplit("/", 1)[-1]


def parse(raw: bytes) -> list:
    data = json.loads(raw)
    works = data.get("works", [])
    expected = sum((data.get("counts") or {}).values())
    if expected != len(works):
        raise RuntimeError(f"OpenAlex raw file says {expected} works but holds {len(works)}")
    out, seen = [], set()
    for w in works:
        wid = _short(w.get("id"))
        if not wid or wid in seen:
            continue
        seen.add(wid)
        title = w.get("title") or ""
        if EMAIL_RE.search(title) or PHONE_RE.search(title):
            continue   # spam deposits (e.g. pill adverts with phone numbers) carrying an Irish affiliation
        pt = w.get("primary_topic") or {}
        matched = []
        for t in w.get("topics") or []:
            if _short((t.get("field") or {}).get("id")) == "30" or _short(t.get("id")) in MEDCHEM_TOPICS:
                matched.append(t.get("display_name") or "")
        oa = w.get("open_access") or {}
        out.append({
            "openalex_id": wid,
            "doi": (w.get("doi") or "").replace("https://doi.org/", ""),
            "title": title,
            "publication_year": w.get("publication_year") if w.get("publication_year") is not None else "",
            "publication_date": w.get("publication_date") or "",
            "type": w.get("type") or "",
            "venue": w.get("venue") or "",
            "oa_status": oa.get("oa_status") or "",
            "is_oa": oa.get("is_oa") if oa.get("is_oa") is not None else "",
            "cited_by_count": w.get("cited_by_count") if w.get("cited_by_count") is not None else "",
            "irish_institutions": sorted({i["display_name"] for i in w.get("institutions") or []
                                         if i.get("country_code") == "IE" and i.get("display_name")}),
            "primary_topic": pt.get("display_name") or "",
            "primary_subfield": (pt.get("subfield") or {}).get("display_name") or "",
            "matched_topics": matched,
            "filter_basis": w.get("filter_basis") or "",
            "is_retracted": bool(w.get("is_retracted")),
        })
    out.sort(key=lambda r: (r["publication_date"], r["openalex_id"]), reverse=True)
    return out
