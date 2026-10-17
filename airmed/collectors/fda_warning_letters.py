"""US FDA warning letters about human drugs, biologics and medical devices (FDA warning letters listing, 2021 onwards).

Source: the JSON that feeds the datatable on FDA's official warning letters page (the page FDA links as its warning
letter search; it lists letters posted from 2021 on, older letters are in FDA's archive). Only the listing columns are
kept; the letters themselves are not downloaded.

Scope: letters about human medical products. A letter is kept when its issuing office is a drug, biologics or device
office (CDER, OPDP, pharmaceutical quality operations, CBER, CDRH), or its subject names a human drug, biologic or
device topic. Tobacco, food, dietary supplement and veterinary (animal drug) letters are left out.

Privacy: many letters go to individuals (clinical investigators, IRB chairs, sole traders). The company name is kept
only when it reads as an organisation and shows no sign of a person (credentials such as M.D. or Ph.D., "Dr.", an
investigator/IRB subject), or is a single word; otherwise the name, the letter URL and the FDA case number (both of which contain or lead
to the name) are blanked and `company_withheld` is "yes". Over-blanking a small firm is the accepted cost of never
naming a person.
"""

import html
import json
import re
import urllib.parse

from ..collectors.ctgov_ireland import ORG_WORDS
from ..http import fetch
from ..util import us_date

KEY = "fda_warning_letters"
FIELDS = ["company", "company_withheld", "issuing_office", "subject", "product_area", "letter_issue_date", "posted_date",
          "response_letter_date", "closeout_date", "fda_case_number", "url"]
SITE = "https://www.fda.gov"
AJAX = SITE + "/datatables/views/ajax?"
VIEW = {"view_name": "warning_letter_solr_index", "view_display_id": "warning_letter_solr_block", "view_path": "/node/360089",
        "view_base_path": "inspections-compliance-enforcement-and-criminal-investigations/compliance-actions-and-activities/"
                          "warning-letters/datatables-data"}
PAGE = 200

# Organisation signs beyond the shared ctgov list: company suffixes and trading words seen in FDA letters.
EXTRA_ORG = re.compile(
    r"\b(lp|llp|pllc|pbc|co|corp|incorporated|partnership|s\.?r\.?o|sdn\.? bhd|d\.o\.o|anonim|sirketi|sanayi|"
    r"de c\.?v|n\.v|lda|unipessoal|gmbh|kg|pvt|private|labs?|store|shop|market|marketplace|supply|suppliers?|"
    r"distributors?|imports?|brands?|products|industries|industrias|manufactura|manufacturing|chemicals?|chem|"
    r"cosmetics?|cosmetique|kozmetik|kozmetika|nutrition|nutritionals|nutraceuticals|naturals|wellness|aesthetics|"
    r"apothecary|meds|rx|peptides?|supplements|botanicals|herbals?|l\.l\.c|drugs|pharm|infusions?|scientific|"
    r"orthop(?:a)?edics|beauty|derma|aerosol|kratom|hemp|cbd|usa|power|fillers?|vitamins|partners|experts|studio|"
    r"mall|tech|therapy)\b|\.(com|org|net|biz|us|in|shop|gold)\b|www\.", re.I)
# Signs of a person: academic or clinical credentials, honorifics.
PERSON = re.compile(r"\b(?:m\.?d|d\.?o|ph\.?d|d\.?d\.?s|pharm\.?d|r\.?ph|d\.?v\.?m|m\.?s|r\.?n|n\.?p|fccp|facp|mph)\.?(?![\w.])|"
                    r"\b(?:dr|mr|mrs|ms|miss)\b\.?\s", re.I)
PERSON_SUBJECT = re.compile(r"investigator|institutional review board|\birb\b|bioresearch monitoring|\bbimo\b|"
                            r"bioavailability-bioequivalence|failure to obtain investigational new drug", re.I)

DRUG_OFFICE = re.compile(r"drug evaluation|\bcder\b|pharmaceutical quality|prescription drug promotion|\bopdp\b|"
                         r"\bdrug\b", re.I)
BIO_OFFICE = re.compile(r"biologics|\bcber\b|biological products", re.I)
DEVICE_OFFICE = re.compile(r"devices|\bcdrh\b|medical device", re.I)
EXCLUDE_OFFICE = re.compile(r"veterinary|tobacco", re.I)
DRUG_SUBJECT = re.compile(r"drug|pharmac|\bapi\b|compounding|\bpet\b|outsourcing|\botc\b|nonprescription|botox|dscsa", re.I)
BIO_SUBJECT = re.compile(r"biologic|hct/p|human cells|blood|vaccine|tissue|\bbla\b", re.I)
DEVICE_SUBJECT = re.compile(r"device|510\(k\)|\bpma\b|premarket approval|\bqsr\b|quality system|\bide\b|mammograph|"
                            r"radiation", re.I)
EXCLUDE_SUBJECT = re.compile(r"animal|veterinar", re.I)

DATE_TEXT = re.compile(r">\s*(\d{1,2}/\d{1,2}/\d{4})\s*<")
HREF = re.compile(r'href="([^"]+)"')
CASE_NO = re.compile(r"-(\d{5,7})-\d{8}(?:-\d+)?$")


def _page_url(start: int) -> str:
    return AJAX + urllib.parse.urlencode({**VIEW, "start": str(start), "length": str(PAGE), "draw": "1"})


def fetch_raw(max_pages: int = 100) -> bytes:
    """All listing rows, combined into one JSON document {"recordsTotal": n, "data": [[...], ...]}."""
    rows, total = [], None
    for page in range(max_pages):
        j = json.loads(fetch(_page_url(page * PAGE)))
        if total is None:
            total = j.get("recordsTotal")
        batch = j.get("data", [])
        rows.extend(batch)
        if not batch or len(rows) >= (total or 0):
            break
    if total is None or len(rows) != total:
        raise RuntimeError(f"FDA warning letters listing returned {len(rows)} of {total} rows; refusing a partial dataset")
    return json.dumps({"recordsTotal": total, "data": rows}).encode("utf-8")


def _text(cell: str) -> str:
    t = re.sub(r"<[^>]+>", " ", cell or "")
    return " ".join(html.unescape(t).split())


def _date(cell: str) -> str:
    m = DATE_TEXT.search(cell or "")
    return us_date(m.group(1)) if m else ""


def product_area(office: str, subject: str) -> list:
    """Human medical product areas of a letter; empty list = out of scope (tobacco, food, veterinary, other)."""
    if EXCLUDE_OFFICE.search(office) or EXCLUDE_SUBJECT.search(subject):
        return []
    areas = []
    if BIO_OFFICE.search(office) or BIO_SUBJECT.search(subject):
        areas.append("biologics")
    if DEVICE_OFFICE.search(office) or DEVICE_SUBJECT.search(subject):
        areas.append("devices")
    if DRUG_OFFICE.search(office) or DRUG_SUBJECT.search(subject):
        areas.append("drugs")
    return areas


def company_or_blank(name: str, subject: str) -> str:
    name = (name or "").strip()
    if not name or PERSON_SUBJECT.search(subject) or PERSON.search(name):
        return ""
    if ORG_WORDS.search(name) or EXTRA_ORG.search(name):
        return name
    if len(name.split()) == 1:   # a single word (Sanofi, Celmade) is a trading name, never a person's full name
        return name
    return ""


def parse(raw: bytes) -> list:
    data = json.loads(raw)
    rows = data.get("data", [])
    expected = data.get("recordsTotal")
    if expected is not None and expected != len(rows):
        raise RuntimeError(f"FDA listing says {expected} rows but holds {len(rows)}")
    out = []
    for r in rows:
        r = list(r) + [""] * (8 - len(r))
        office, subject = _text(r[3]), _text(r[4])
        areas = product_area(office, subject)
        if not areas:
            continue
        name = _text(r[2])
        company = company_or_blank(name, subject)
        href = HREF.search(r[2] or "")
        path = href.group(1) if href else ""
        case = CASE_NO.search(path)
        out.append({
            "company": company,
            "company_withheld": "no" if company else "yes",
            "issuing_office": office,
            "subject": subject,
            "product_area": areas,
            "letter_issue_date": _date(r[1]),
            "posted_date": _date(r[0]),
            "response_letter_date": _date(r[5]),
            "closeout_date": _date(r[6]),
            "fda_case_number": case.group(1) if (company and case) else "",
            "url": (SITE + path if path.startswith("/") else path) if company else "",
        })
    out.sort(key=lambda x: (x["company"].lower(), x["issuing_office"], x["subject"], x["url"], x["closeout_date"]))
    out.sort(key=lambda x: (x["letter_issue_date"], x["posted_date"]), reverse=True)
    return out
