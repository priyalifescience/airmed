"""OpenAlex: scholarly works published from 2023 onwards with at least one author affiliation in the EU-27, the
United Kingdom, Norway or Switzerland, in pharmacology, pharmaceutical science, toxicology, drug discovery and
medicinal chemistry. The European companion of openalex_ireland_pharma, with the same topic filter.

Filter: institutions.country_code is any of COUNTRIES (one OR filter, so a work with several European countries
is returned once), plus the two disjoint topic queries of the Irish collector:
  field30     any of the work's OpenAlex topics lies in the field "Pharmacology, Toxicology and Pharmaceutics"
  medchem     topic "Computational Drug Discovery Methods" (T10211) or "Synthesis and biological activity"
              (T10274) and no field-30 topic

Keyless OpenAlex access only allows page-number paging, which stops at 10,000 results per query, so each topic
query is split into publication-date windows (quarters for field30, about 16,000 works a year, so no window is
near the limit; whole years for medchem, about 6,000 a year). The windows do not overlap and the last one is open-ended, so every work falls in
exactly one query and the per-query totals add up to the dataset size. Starting in 2023 keeps the dataset near
86,000 works (CSV about 30 MB, under the 40 MB size rule) and one full run near 450 API requests, inside the
1,000 requests a day OpenAlex gives keyless users.

Works whose title contains a phone number or email address are dropped (spam deposits, not research).

Work-level fields only. Authorships are reduced to their institutions' country codes inside fetch_raw, so author
names, author ids, ORCIDs and raw affiliation strings are never stored.
"""

import json
import urllib.parse

from ..http import fetch
from ..privacy import EMAIL_RE, PHONE_RE
from .openalex_ireland_pharma import API, MAILTO, MAX_RESULTS, MEDCHEM_TOPICS, PER_PAGE, _short

KEY = "openalex_europe_pharma"
FIELDS = ["openalex_id", "doi", "title", "publication_year", "publication_date", "type", "venue", "oa_status",
          "is_oa", "cited_by_count", "countries", "primary_topic", "primary_subfield", "matched_topics",
          "filter_basis", "is_retracted"]

EU27 = ("AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU",
        "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE")
COUNTRIES = EU27 + ("GB", "NO", "CH")
FROM_YEAR = 2023
LAST_YEAR = 2026          # the last window of each query is open-ended, so later-dated works are not lost
TOPIC_FILTERS = {
    "field30": "topics.field.id:30",
    "medchem": "topics.id:" + "|".join(MEDCHEM_TOPICS) + ",topics.field.id:!30",
}
SELECT = ("id,doi,title,publication_year,publication_date,type,primary_location,open_access,cited_by_count,"
          "authorships,primary_topic,topics,is_retracted")


def _windows(quarters: bool) -> list:
    """Disjoint (from, to) publication-date windows from FROM_YEAR; the last has no end date."""
    out = []
    for y in range(FROM_YEAR, LAST_YEAR + 1):
        if quarters:
            out += [(f"{y}-01-01", f"{y}-03-31"), (f"{y}-04-01", f"{y}-06-30"),
                    (f"{y}-07-01", f"{y}-09-30"), (f"{y}-10-01", f"{y}-12-31")]
        else:
            out.append((f"{y}-01-01", f"{y}-12-31"))
    out[-1] = (out[-1][0], "")
    return out


def queries() -> dict:
    base = "institutions.country_code:" + "|".join(COUNTRIES)
    q = {}
    for basis, quarters in (("field30", True), ("medchem", False)):
        for frm, to in _windows(quarters):
            flt = f"{base},from_publication_date:{frm}" + (f",to_publication_date:{to}" if to else "")
            q[f"{basis}:{frm}"] = flt + "," + TOPIC_FILTERS[basis]
    return q


def _url(flt: str, page: int) -> str:
    q = {"filter": flt, "select": SELECT, "per_page": str(PER_PAGE), "page": str(page), "mailto": MAILTO}
    return API + "?" + urllib.parse.urlencode(q, safe=":,|!*")


def _strip(work: dict, basis: str) -> dict:
    """Keep only institution country codes from authorships: no author names, ids or ORCIDs leave here."""
    countries = sorted({i.get("country_code") for a in work.get("authorships") or []
                        for i in a.get("institutions") or [] if i.get("country_code")})
    w = {k: work.get(k) for k in ("id", "doi", "title", "publication_year", "publication_date", "type",
                                  "cited_by_count", "is_retracted")}
    oa = work.get("open_access") or {}
    w["open_access"] = {"oa_status": oa.get("oa_status"), "is_oa": oa.get("is_oa")}
    pt = work.get("primary_topic") or {}
    w["primary_topic"] = {"display_name": pt.get("display_name"),
                          "subfield": {"display_name": (pt.get("subfield") or {}).get("display_name")}}
    # only what parse() reads: the full topic objects are about half of a page's bytes
    w["topics"] = [{"id": t.get("id"), "display_name": t.get("display_name"),
                    "field": {"id": (t.get("field") or {}).get("id")}} for t in work.get("topics") or []]
    w["venue"] = ((work.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
    w["countries"] = countries
    w["filter_basis"] = basis
    return w


def _fetch_query(flt: str, basis: str, max_pages: int = 60):
    got, ids, total = [], set(), None
    for n in range(1, max_pages + 1):
        page = json.loads(fetch(_url(flt, n), timeout=120))
        if total is None:
            total = page["meta"]["count"]
            if total > MAX_RESULTS:
                raise RuntimeError(f"OpenAlex query {flt} has {total} works, above the {MAX_RESULTS} paging limit; "
                                   "split it into smaller date windows")
        for w in page.get("results", []):
            if w.get("id") not in ids:
                ids.add(w.get("id"))
                got.append(_strip(w, basis))
        if not page.get("results") or n * PER_PAGE >= total:
            break
    return got, total


def fetch_raw() -> bytes:
    """Page-number paging per date window; the unique count of each query must equal its stated total
    (one retry per query, since page-number paging over a changing index can shift by a work or two)."""
    qs = queries()
    works, counts = [], {}
    for name, flt in qs.items():
        basis = name.split(":", 1)[0]
        got, total = _fetch_query(flt, basis)
        if len(got) != total:
            got, total = _fetch_query(flt, basis)
            if len(got) != total:
                raise RuntimeError(f"OpenAlex query {name} returned {len(got)} unique of {total} works")
        counts[name] = total
        works.extend(got)
    return json.dumps({"counts": counts, "filters": qs, "works": works}, ensure_ascii=False).encode("utf-8")


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
            continue   # spam deposits (e.g. pill adverts with phone numbers) carrying a European affiliation
        pt = w.get("primary_topic") or {}
        matched = [t.get("display_name") or "" for t in w.get("topics") or []
                   if _short((t.get("field") or {}).get("id")) == "30" or _short(t.get("id")) in MEDCHEM_TOPICS]
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
            "countries": sorted(set(w.get("countries") or [])),
            "primary_topic": pt.get("display_name") or "",
            "primary_subfield": (pt.get("subfield") or {}).get("display_name") or "",
            "matched_topics": matched,
            "filter_basis": w.get("filter_basis") or "",
            "is_retracted": bool(w.get("is_retracted")),
        })
    out.sort(key=lambda r: (r["publication_date"], r["openalex_id"]), reverse=True)
    return out
