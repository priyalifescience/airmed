"""eTenders (Ireland): public procurement notices and contract awards in health, medicines and medical
technology, from the Office of Government Procurement's open data file (all eTenders notices since 2013).

The OGP file (one CSV, refreshed regularly, found through the data.gov.ie CKAN API) holds three kinds of rows,
named in `source_type`: "OpenData-Publications" (tender notices, with the award where one was published),
"OpenData-Contracts" (contracts recorded on eTenders, including direct-invite / mini-competition awards; one row per
awarded supplier, so the same tender id can repeat with the same awarded value: do not add values across rows of
one tender) and "OpenData-DPSTenders" (dynamic purchasing system tenders).

Health filter (a row is kept when any applies; the reasons are listed in `health_filter`):
- main_cpv_33 / main_cpv_851: the main CPV code is in division 33 (medical equipment, pharmaceuticals and personal
  care products) or group 851 (health services);
- additional_cpv_33_851: one of the additional CPV codes is in division 33 or in group 851 (health services);
  the rest of division 85 (social work, education counselling, prison visitor centres) is not used;
- health_authority: the contracting authority or the client authority is the HSE, a hospital, Children's Health
  Ireland or the HPRA (see AUTHORITY_RE).
Everything else (roads, IT for other departments, ...) is left out.

Persons: suppliers can be sole traders. A supplier name is published only when it carries a company or
public-body marker (the same rule as dete_employment_permits.looks_like_organisation); other names are left out of
`awarded_suppliers` and counted in `suppliers_withheld`. The rule is strict: well-known firms published without a
legal form (e.g. "KPMG", "Arup", "Vodafone") are withheld too. Supplier lists are split on "|" and ";" after HTML
entities are decoded. Values are otherwise as published (dates converted to ISO, euro amounts and counts to numbers).
"""

import csv
import html
import io
import json
import re

from ..http import fetch
from ..util import iso_date
from .dete_employment_permits import looks_like_organisation

KEY = "etenders_health_awards"
FIELDS = ["tender_id", "parent_agreement_id", "contracting_authority", "client_contracting_authority",
          "agreement_owner", "title", "published_date", "directive", "competition_type", "main_cpv_code",
          "main_cpv_description", "additional_cpv_codes", "spend_category", "contract_type", "threshold_level",
          "procedure", "submission_deadline", "evaluation_type", "estimated_value_eur", "duration_months",
          "cancelled_date", "award_published_date", "awarded_value_eur", "bids_received", "sme_bids_received",
          "awarded_suppliers", "suppliers_withheld", "awarded_smes", "ted_notice_url", "ted_award_url", "platform",
          "source_type", "health_filter"]
CKAN = "https://data.gov.ie/api/3/action/package_show?id=contract-notices-published-on-etenders"
AUTHORITY_RE = re.compile(r"\b(HSE|Health Service Executive|Hospitals?|Children'?s Health Ireland|HPRA|"
                          r"Health Products Regulatory Authority)\b", re.I)
MIN_SOURCE_ROWS = 50000
# source column -> our field, and how to read it
COLUMNS = [
    ("Tender ID", "tender_id", "text"), ("Parent Agreement ID", "parent_agreement_id", "text"),
    ("Contracting Authority", "contracting_authority", "text"),
    ("Name of Client Contracting Authority", "client_contracting_authority", "text"),
    ("Agreement Owner", "agreement_owner", "text"), ("Tender/Contract Name", "title", "text"),
    ("Notice Published Date / Contract Created Date", "published_date", "date"), ("Directive", "directive", "text"),
    ("Competition Type", "competition_type", "text"), ("Main Cpv Code", "main_cpv_code", "text"),
    ("Main Cpv Code Description", "main_cpv_description", "text"),
    ("Additional CPV Codes on CFT", "additional_cpv_codes", "list"), ("Spend Category", "spend_category", "text"),
    ("Contract Type", "contract_type", "text"), ("Threshold Level", "threshold_level", "text"),
    ("Procedure", "procedure", "text"), ("Tender Submission Deadline", "submission_deadline", "date"),
    ("Evaluation Type", "evaluation_type", "text"),
    ("Sum of Notice Estimated Value (€)", "estimated_value_eur", "num"),
    ("Sum of Contract Duration (Months)", "duration_months", "num"), ("Cancelled Date", "cancelled_date", "date"),
    ("Award Published", "award_published_date", "date"), ("Sum of Awarded Value (€)", "awarded_value_eur", "num"),
    ("Sum of No of Bids Received", "bids_received", "num"),
    ("Sum of No of SMEs Bids Received", "sme_bids_received", "num"),
    ("Sum of No of Awarded SMEs", "awarded_smes", "num"), ("TED Notice Link", "ted_notice_url", "text"),
    ("TED CAN Link", "ted_award_url", "text"), ("Platform", "platform", "text"), ("Source", "source_type", "text"),
]


def _decode(b: bytes) -> str:
    try:
        return b.decode("utf-8-sig")
    except UnicodeDecodeError:
        return b.decode("cp1252")                    # the OGP file is Windows-1252 (euro sign = 0x80)


def fetch_raw() -> bytes:
    meta = json.loads(fetch(CKAN, timeout=60))["result"]
    csvs = [r["url"] for r in meta["resources"] if (r.get("format") or "").strip(". ").lower() == "csv"]
    if len(csvs) != 1:
        raise RuntimeError(f"data.gov.ie eTenders dataset: expected one CSV resource, found {csvs}")
    return _decode(fetch(csvs[0], timeout=300)).encode("utf-8")


def _num(s: str):
    v = (s or "").strip().replace(",", "")
    if not v:
        return ""
    if not re.fullmatch(r"-?\d+(\.\d+)?", v):
        raise ValueError(f"eTenders: not a number: {s!r}")
    f = float(v)
    return int(f) if f.is_integer() else f


def _date(s: str) -> str:
    d = iso_date(s)
    if d and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
        raise ValueError(f"eTenders: unexpected date {s!r}")
    return d


def _suppliers(s: str) -> tuple:
    """'| A | B' or 'A; B' (HTML entities such as &amp;amp; decoded first) -> ([organisation names], number withheld as possible persons)."""
    names = [n.strip() for n in re.split(r"[|;]", html.unescape(s or "")) if n.strip()]
    keep = [n for n in names if looks_like_organisation(n)]
    return keep, len(names) - len(keep)


def _health(rec: dict) -> list:
    why = []
    main = rec["main_cpv_code"]
    if main.startswith("33"):
        why.append("main_cpv_33")
    if main.startswith("851"):
        why.append("main_cpv_851")
    if any(c.startswith(("33", "851")) for c in rec["additional_cpv_codes"]):
        why.append("additional_cpv_33_851")
    if AUTHORITY_RE.search(rec["contracting_authority"]) or AUTHORITY_RE.search(rec["client_contracting_authority"]):
        why.append("health_authority")
    return why


def parse(raw: bytes, min_source_rows: int = MIN_SOURCE_ROWS) -> list:
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8")))
    cols = reader.fieldnames or []
    missing = [c for c, _, _ in COLUMNS + [("Awarded Suppliers", "", "")] if c not in cols]
    if missing:
        raise RuntimeError(f"eTenders CSV: column(s) {missing} missing (got {cols})")
    out, n = [], 0
    for r in reader:
        n += 1
        rec = {}
        for col, field, kind in COLUMNS:
            v = re.sub(r"\s+", " ", r.get(col) or "").strip()
            if kind == "date":
                rec[field] = _date(v)
            elif kind == "num":
                rec[field] = _num(v)
            elif kind == "list":
                rec[field] = [c.strip() for c in v.split(";") if c.strip()]
            else:
                rec[field] = v
        why = _health(rec)
        if not why:
            continue
        rec["awarded_suppliers"], rec["suppliers_withheld"] = _suppliers(r.get("Awarded Suppliers"))
        rec["health_filter"] = why
        out.append({f: rec[f] for f in FIELDS})
    if n < min_source_rows:
        raise RuntimeError(f"eTenders CSV: only {n} rows (expected at least {min_source_rows}); broken download?")
    out.sort(key=lambda r: (r["published_date"], r["tender_id"], r["title"], r["awarded_suppliers"]))
    return out
