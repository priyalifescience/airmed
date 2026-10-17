"""US NLM DailyMed: index of human prescription drug labels (SPL metadata only, never label text).

DailyMed holds about 159,000 SPL documents of every type (OTC, homeopathic, animal, devices, bulk ingredients...).
This collector keeps the current human prescription drug labels (document type LOINC 34391-3, about 52,000), listed
through the DailyMed web services (/services/v2/spls.json?doctype=34391-3, 100 per page, the service maximum).
RxNorm concepts come from NLM's DailyMed RxNorm mapping file (rxnorm_mappings.zip, one download), joined on set id.

Per label: set id, version, title, published date, labeler (the company name DailyMed prints in square brackets at
the end of the title) and the RxNorm clinical/branded drug concepts the label maps to.

Privacy: a handful of labelers are individuals trading under their own name ('FIRSTNAME I. SURNAME', no
organisation word); for those the labeler is blanked and the bracketed name in the title becomes [labeler withheld].
"""

import datetime
import html
import io
import json
import re
import urllib.parse
import zipfile

from ..collectors.ctgov_ireland import ORG_WORDS
from ..collectors.fda_warning_letters import EXTRA_ORG
from ..http import fetch

KEY = "dailymed_spl_index"
FIELDS = ["setid", "spl_version", "title", "labeler", "published_date", "document_type", "rxcuis", "rxnorm_names", "url"]
DOCTYPE = "34391-3"
DOCUMENT_TYPE = "HUMAN PRESCRIPTION DRUG LABEL"
SPLS = "https://dailymed.nlm.nih.gov/dailymed/services/v2/spls.json?"
RXNORM_ZIP = "https://dailymed-data.nlm.nih.gov/public-release-files/rxnorm_mappings.zip"
LABEL_URL = "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid="
PAGE = 100
# RxNorm term types naming a drug concept (each RXCUI in the file has exactly one of these besides PSN/SY synonyms)
CONCEPT_TTYS = ("SCD", "SBD", "GPCK", "BPCK")
PERSON_NAME = re.compile(r"^[A-Za-z][A-Za-z'’-]+ [A-Za-z]\.? [A-Za-z][A-Za-z'’-]+$")
ENTITY = re.compile(r"&([A-Za-z]+);")


def _page_url(page: int) -> str:
    return SPLS + urllib.parse.urlencode({"doctype": DOCTYPE, "pagesize": str(PAGE), "page": str(page)})


def _rxnorm(setids: set) -> dict:
    """{setid: [[rxcui, name, tty], ...]} from the mapping file, for the given set ids only."""
    out = {}
    with zipfile.ZipFile(io.BytesIO(fetch(RXNORM_ZIP, timeout=180))) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".txt"))
        with z.open(name) as h:
            lines = io.TextIOWrapper(h, encoding="utf-8", errors="replace")
            header = next(lines).rstrip("\n").split("|")
            if header[:5] != ["SETID", "SPL_VERSION", "RXCUI", "RXSTRING", "RXTTY"]:
                raise RuntimeError(f"unexpected rxnorm_mappings header {header}")
            for line in lines:
                p = line.rstrip("\n").split("|")
                if len(p) >= 5 and p[0] in setids and p[4] in CONCEPT_TTYS:
                    out.setdefault(p[0], []).append([p[2], p[3], p[4]])
    return out


def fetch_raw(max_pages: int = 1000) -> bytes:
    """{"total": n, "db_published": d, "spls": [...], "rxnorm": {setid: [[rxcui, name, tty]]}}"""
    spls, total, db_published = [], None, None
    for page in range(1, max_pages + 1):
        j = json.loads(fetch(_page_url(page), timeout=90))
        meta = j.get("metadata", {})
        if total is None:
            total, db_published = meta.get("total_elements"), meta.get("db_published_date")
        elif meta.get("db_published_date") != db_published:
            raise RuntimeError("DailyMed database was republished during the run; run again")
        spls.extend(j.get("data", []))
        if not j.get("data") or page >= int(meta.get("total_pages") or 0):
            break
    unique = {s.get("setid") for s in spls}
    if total is None or len(unique) != total:
        raise RuntimeError(f"DailyMed listed {len(unique)} distinct labels of {total}; refusing a partial dataset")
    rx = _rxnorm(unique)
    return json.dumps({"total": total, "db_published": db_published, "spls": spls, "rxnorm": rx}).encode("utf-8")


def labeler_from_title(title: str) -> str:
    t = (title or "").strip()
    if not t.endswith("]") or "[" not in t:
        return ""
    return t[t.rfind("[") + 1:-1].strip()


def looks_like_person(name: str) -> bool:
    """A few labelers are individuals trading under their own name (e.g. small medical gas suppliers), written
    'FIRSTNAME I. SURNAME'. Company names with a middle initial always carry an organisation word or suffix."""
    return bool(PERSON_NAME.match(name or "")) and not ORG_WORDS.search(name) and not EXTRA_ORG.search(name)


def _clean_title(value: str) -> str:
    # some titles carry HTML entities, sometimes upper-case (&RSQUO;); decode them, never alter anything else
    t = ENTITY.sub(lambda m: "&" + m.group(1).lower() + ";", value or "")
    return " ".join(html.unescape(t).split())


def _date(value: str) -> str:
    try:
        return datetime.datetime.strptime((value or "").strip(), "%b %d, %Y").date().isoformat()
    except ValueError:
        return (value or "").strip()


def parse(raw: bytes) -> list:
    data = json.loads(raw)
    rx = data.get("rxnorm", {})
    out, seen = [], set()
    for s in data.get("spls", []):
        setid = (s.get("setid") or "").strip()
        if not setid or setid in seen:
            continue
        seen.add(setid)
        concepts = sorted({(c[0], c[1]) for c in rx.get(setid, [])}, key=lambda c: (c[1].lower(), c[0]))
        title = _clean_title(s.get("title"))
        labeler = labeler_from_title(title)
        if labeler and looks_like_person(labeler):
            title, labeler = title[:title.rfind("[")].rstrip() + " [labeler withheld]", ""
        out.append({
            "setid": setid,
            "spl_version": str(s.get("spl_version") or ""),
            "title": title,
            "labeler": labeler,
            "published_date": _date(s.get("published_date")),
            "document_type": DOCUMENT_TYPE,
            "rxcuis": [c[0] for c in concepts],
            "rxnorm_names": [c[1] for c in concepts],
            "url": LABEL_URL + setid,
        })
    total = data.get("total")
    if total is not None and len(out) != total:
        raise RuntimeError(f"DailyMed index says {total} labels but holds {len(out)}")
    out.sort(key=lambda r: (r["title"].lower(), r["setid"]))
    return out
