"""FDA Purple Book: licensed biological products (originator, biosimilar and interchangeable) with exclusivity dates.

Source: the latest monthly "Purple Book data download" CSV linked from purplebooksearch.fda.gov/downloads.
Each monthly file has two sections: the month's changes, then every product in the database. Only the full
product section is used. Product-level fields only: the monthly change flag and the supplement numbers are dropped.
"""

import csv
import datetime as dt
import io
import re

from ..http import fetch

KEY = "fda_purple_book"
FIELDS = ["bla_number", "product_number", "proprietary_name", "proper_name", "applicant", "license_type",
          "strength", "dosage_form", "route", "product_presentation", "marketing_status", "licensure_status",
          "approval_date", "interchangeable_approval_date", "ref_product_proper_name", "ref_product_proprietary_name",
          "license_number", "center", "date_of_first_licensure", "exclusivity_expiry",
          "first_interchangeable_exclusivity_expiry", "ref_product_exclusivity_expiry", "orphan_exclusivity_expiry",
          "patent_list_provided", "data_month"]
DOWNLOADS = "https://purplebooksearch.fda.gov/downloads"
LINK_RE = re.compile(r"https://www\.accessdata\.fda\.gov/drugsatfda_docs/PurpleBook/(\d{4})/"
                     r"purplebook-search-([A-Za-z]+)-data-download\.csv", re.I)
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]
MIN_RECORDS = 2000

# source column -> our field
COLUMNS = {
    "BLA Number": "bla_number", "Product Number": "product_number", "Proprietary Name": "proprietary_name",
    "Proper Name": "proper_name", "Applicant": "applicant", "License Type": "license_type", "Strength": "strength",
    "Dosage Form": "dosage_form", "Route of Administration": "route", "Product Presentation": "product_presentation",
    "Marketing Status": "marketing_status", "Licensure": "licensure_status", "Approval Date": "approval_date",
    "Inter. Approval Date": "interchangeable_approval_date", "Ref. Product Proper Name": "ref_product_proper_name",
    "Ref. Product Proprietary Name": "ref_product_proprietary_name", "License Number": "license_number",
    "Center": "center", "Date of First Licensure": "date_of_first_licensure",
    "Exclusivity Expiration Date": "exclusivity_expiry",
    "First Interchangeable Exclusivity Exp. Date": "first_interchangeable_exclusivity_expiry",
    "Ref. Product Exclusivity Exp. Date": "ref_product_exclusivity_expiry",
    "Orphan Exclusivity Exp. Date": "orphan_exclusivity_expiry", "Patent List Provided": "patent_list_provided",
}
DATE_FIELDS = {"approval_date", "interchangeable_approval_date", "date_of_first_licensure", "exclusivity_expiry",
               "first_interchangeable_exclusivity_expiry", "ref_product_exclusivity_expiry",
               "orphan_exclusivity_expiry"}


def latest_csv_url(page: str) -> str:
    """The newest monthly CSV linked from the downloads page (by year, then month)."""
    best = None
    for m in LINK_RE.finditer(page):
        month = m.group(2).lower()
        if month in MONTHS:
            rank = (int(m.group(1)), MONTHS.index(month))
            if best is None or rank > best[0]:
                best = (rank, m.group(0))
    if best is None:
        raise RuntimeError("no Purple Book CSV link found on the downloads page")
    return best[1]


def fetch_raw() -> bytes:
    page = fetch(DOWNLOADS).decode("utf-8", errors="replace")
    return fetch(latest_csv_url(page), timeout=180)


def _date(v: str) -> str:
    """'January 16, 2013' -> '2013-01-16'; other text (e.g. 'Not Eligible') is kept as written."""
    v = (v or "").strip()
    try:
        return dt.datetime.strptime(v, "%B %d, %Y").date().isoformat()
    except ValueError:
        return v


def _data_month(title: str) -> str:
    m = re.search(r"-\s*([A-Za-z]+)\s+(\d{4})\s*$", title or "")
    if m and m.group(1).lower() in MONTHS:
        return f"{m.group(2)}-{MONTHS.index(m.group(1).lower()) + 1:02d}"
    return ""


def parse(raw: bytes, min_records: int = MIN_RECORDS) -> list:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    month = _data_month(rows[0][0] if rows and rows[0] else "")
    headers = [i for i, r in enumerate(rows) if r and r[0].strip() == "N/R/U"]
    if len(headers) < 2:
        raise RuntimeError("Purple Book file does not have the expected changes + all-products sections")
    header = [h.strip() for h in rows[headers[-1]]]
    missing = [c for c in COLUMNS if c not in header]
    if missing:
        raise RuntimeError(f"Purple Book file is missing columns {missing}")
    idx = {c: header.index(c) for c in COLUMNS}
    out, seen = [], set()
    for n, r in enumerate(rows[headers[-1] + 1:], start=headers[-1] + 2):
        if not any(c.strip() for c in r):
            continue
        if len(r) != len(header):
            raise RuntimeError(f"Purple Book line {n}: {len(r)} fields, expected {len(header)}")
        rec = {}
        for col, field in COLUMNS.items():
            v = " ".join(r[idx[col]].split())          # trims stray spaces such as "Injection "
            rec[field] = _date(v) if field in DATE_FIELDS else v
        rec["patent_list_provided"] = "yes" if rec["patent_list_provided"].upper() == "YES" else ""
        rec["data_month"] = month
        k = (rec["bla_number"], rec["product_number"])
        if k in seen:
            raise RuntimeError(f"Purple Book lists product {k} twice")
        seen.add(k)
        out.append({f: rec[f] for f in FIELDS})
    if len(out) < min_records:
        raise RuntimeError(f"only {len(out)} Purple Book products; refusing a partial dataset")
    out.sort(key=lambda r: (r["bla_number"], r["product_number"]))
    return out
