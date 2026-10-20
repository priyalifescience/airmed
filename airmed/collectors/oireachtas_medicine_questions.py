"""Houses of the Oireachtas: parliamentary questions (PQs) to the Minister for Health and the Minister for Enterprise
that mention medicines, drugs, the HPRA, pharmaceuticals, pharmacy, clinical trials, vaccines or medicine
reimbursement, from 1 January 2020 to the latest published date.

Source: Oireachtas Open Data API, https://api.oireachtas.ie/v1/questions (written and oral questions). The API caps a
query at 10,000 results and a page at 1,000, so the window is walked month by month (a month that reports the cap is
split in two until every part is below it), 1,000 questions per page, and each part must return exactly the number
of questions the API says it holds. Only questions addressed to the departments in DEPARTMENTS are kept from the
download; the term filter (TERMS) is applied in parse() to the question text and the debate-section heading, and the
terms that matched are recorded per row.

Charter (no personal names): the API's "by" block (the asking TD) is never downloaded, the answering minister is not
requested (show_answers is off), and the published question text starts "123. Deputy <name> asked the Minister for
Health ..." (Irish: "123. D'fhiafraigh Deputy <name> den Aire ..."). That opening clause, up to and including
"asked the" / "den" / "de", is removed, so question_text starts at "Minister for Health ...". A question whose opening
does not match either form is not published (its text could not be cleaned). The rest of the text is kept as
published in the official record (it can mention people, e.g. "(details supplied)", or name organisations).

Links: "url" is the question's URI in the Oireachtas data model (an identifier; it does not open in a browser),
"record_xml_url" the official Akoma Ntoso XML of the debate section holding the question and its answer (as the API
publishes it), and "web_url" the question's page on oireachtas.ie, built from the date and question number.
The terms are English, so questions asked in Irish only match through an English heading.
"""

import calendar
import datetime
import json
import re
import urllib.parse

from ..http import fetch

KEY = "oireachtas_medicine_questions"
FIELDS = ["date", "year", "question_ref", "question_number", "question_type", "house", "department", "topic",
          "question_text", "matched_terms", "url", "web_url", "record_xml_url"]
API = "https://api.oireachtas.ie/v1/questions"
WEB_URL = "https://www.oireachtas.ie/en/debates/question/{date}/{number}/"
FIRST_DATE = "2020-01-01"
PAGE = 1000
API_CAP = 10000
# the API's short department label ("to.showAs"); "Business" is the Department of Business, Enterprise and Innovation
# (to mid-2020), "Enterprise" its successor (Enterprise, Trade and Employment / Enterprise, Tourism and Employment)
DEPARTMENTS = ("Health", "Enterprise", "Business")
TERMS = {
    "medicine": r"\bmedicines?\b|\bmedicinal\b|\bmedications?\b",
    "drug": r"\bdrugs?\b",
    "HPRA": r"\bHPRA\b|\bHealth Products Regulatory Authority\b",
    "pharmaceutical": r"\bpharmaceuticals?\b|\bpharma\b",
    "pharmacy": r"\bpharmac(?:y|ies|ists?)\b",
    "clinical trial": r"\bclinical trials?\b",
    "vaccine": r"\bvaccin\w*",
    "reimbursement": r"\breimburs\w*|\bNCPE\b|\bpharmacoeconomic\w*",
}
_TERM_RES = {k: re.compile(v, re.I) for k, v in TERMS.items()}
_ASKER_RE = re.compile(r"^\s*\d+\s*\.\s*(?:Deputy\s+.+?\s+asked\s+the\s+|D'fhiafraigh\s+(?:an\s+)?(?:Deputy|Teachta)\s+"
                       r".+?\s+(?:den|de|d')\s+)", re.S)
_REF_RE = re.compile(r"\[(\d+/\d{2})\]\s*$")
KEEP = ("date", "questionNumber", "questionType", "showAs", "uri")


def _get(start: str, end: str, skip: int) -> dict:
    q = {"date_start": start, "date_end": end, "limit": PAGE, "skip": skip}
    return json.loads(fetch(API + "?" + urllib.parse.urlencode(q), timeout=120))


def _slim(q: dict) -> dict:
    ds, house = q.get("debateSection") or {}, q.get("house") or {}
    out = {k: q.get(k) for k in KEEP}
    xml = ((ds.get("formats") or {}).get("xml") or {}).get("uri")
    out.update(department=(q.get("to") or {}).get("showAs"), topic=ds.get("showAs"), section_xml=xml,
               house=house.get("showAs"))
    return out


def _window(start: datetime.date, end: datetime.date, parts: list):
    s, e = start.isoformat(), end.isoformat()
    first = _get(s, e, 0)
    count = int(first["head"]["counts"]["questionCount"])
    if count >= API_CAP and start < end:
        mid = start + (end - start) // 2
        _window(start, mid, parts)
        _window(mid + datetime.timedelta(days=1), end, parts)
        return
    if count >= API_CAP:
        raise RuntimeError(f"Oireachtas API: {s} alone reports the {API_CAP}-question cap")
    got, kept, depts = 0, [], {}
    page = first
    while True:
        res = page.get("results") or []
        got += len(res)
        for r in res:
            q = r.get("question") or {}
            d = (q.get("to") or {}).get("showAs") or ""
            depts[d] = depts.get(d, 0) + 1
            if d in DEPARTMENTS:
                kept.append(_slim(q))
        if not res or got >= count:
            break
        page = _get(s, e, got)
    parts.append({"start": s, "end": e, "count": count, "fetched": got, "departments": depts, "questions": kept})


def fetch_raw(first_date: str = FIRST_DATE, last_date: str = None) -> bytes:
    """Every question from first_date to last_date (default today), month by month; questions to other departments
    are counted but not kept."""
    start = datetime.date.fromisoformat(first_date)
    last = datetime.date.fromisoformat(last_date) if last_date else datetime.date.today()
    parts = []
    while start <= last:
        end = min(datetime.date(start.year, start.month, calendar.monthrange(start.year, start.month)[1]), last)
        _window(start, end, parts)
        start = end + datetime.timedelta(days=1)
    return json.dumps({"first_date": first_date, "last_date": last.isoformat(), "parts": parts}).encode("utf-8")


def clean_text(show_as: str):
    """Remove the 'N. Deputy <name> asked the' opening. Returns None when the opening is not recognised."""
    t = re.sub(r"\s+", " ", show_as or "").strip()
    m = _ASKER_RE.match(t)
    if not m:
        return None
    rest = t[m.end():].strip()
    return rest[:1].upper() + rest[1:]


def matched_terms(*texts) -> list:
    blob = " ".join(t or "" for t in texts)
    return [k for k, rx in _TERM_RES.items() if rx.search(blob)]


def parse(raw: bytes, max_unclean_share: float = 0.01) -> list:
    data = json.loads(raw)
    parts = data.get("parts") or []
    if not parts:
        raise RuntimeError("no Oireachtas question windows in the download")
    for p in parts:
        if p.get("fetched") != p.get("count"):
            raise RuntimeError(f"Oireachtas {p.get('start')}..{p.get('end')}: fetched {p.get('fetched')} of {p.get('count')}")
    out, seen, unclean, considered = [], set(), 0, 0
    for p in parts:
        for q in p.get("questions") or []:
            if q.get("department") not in DEPARTMENTS:
                continue
            text = clean_text(q.get("showAs"))
            terms = matched_terms(text if text is not None else q.get("showAs"), q.get("topic"))
            if not terms:
                continue
            considered += 1
            if text is None:
                unclean += 1
                continue
            uri = q.get("uri") or ""
            if uri in seen:
                continue
            seen.add(uri)
            ref = _REF_RE.search(text)
            date, num = q.get("date") or "", q.get("questionNumber")
            out.append({
                "date": date,
                "year": int(date[:4]) if date[:4].isdigit() else "",
                "question_ref": ref[1] if ref else "",
                "question_number": q.get("questionNumber") if q.get("questionNumber") is not None else "",
                "question_type": q.get("questionType") or "",
                "house": q.get("house") or "",
                "department": q.get("department") or "",
                "topic": re.sub(r"\s+", " ", q.get("topic") or "").strip(),
                "question_text": text,
                "matched_terms": terms,
                "url": uri,
                "web_url": WEB_URL.format(date=date, number=num) if date and num else "",
                "record_xml_url": q.get("section_xml") or "",
            })
    if considered and unclean > max_unclean_share * considered:
        raise RuntimeError(f"{unclean} of {considered} matching questions have an unrecognised opening")
    out.sort(key=lambda r: (r["date"], r["question_type"], r["question_number"] if r["question_number"] != "" else 0,
                            r["url"]))
    return out
