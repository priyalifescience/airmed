"""SEC Form 8-K current reports with Item 1.01 (Entry into a Material Definitive Agreement) or Item 2.01 (Completion
of Acquisition or Disposition of Assets), filed by large pharma, biotech and medtech companies.

Source: U.S. Securities and Exchange Commission, EDGAR submissions API (data.sec.gov/submissions/CIK##########.json),
for the same fixed company list as sec_product_revenue. The API lists every filing with its form type, filing and
report dates, accession number, primary document and, for 8-K filings, the item numbers the filer declared. Only
that filing metadata is used: the documents themselves are not downloaded or read.

Scope and limits (stated, not corrected):
  - Item 1.01 covers any material definitive agreement: licensing and collaboration deals, merger agreements, but
    also credit facilities, bond indentures and supply agreements. The item number alone does not tell them apart.
  - Item 2.01 is filed when an acquisition or disposal of a significant amount of assets is completed.
  - Foreign private issuers (20-F filers such as Novo Nordisk, AstraZeneca, GSK, Sanofi, Novartis) report on Form
    6-K, which has no item numbers; they have no rows here.
  - The submissions API "recent" block holds at least the last year or the last 1,000 filings; older filings are in
    extra files, which are read back to OLDEST_YEAR.

Privacy: filing metadata only; no names of individuals (8-K Item 5.02 officer changes are not in scope).
"""

import json

from .. import http
from ..http import fetch
from .sec_product_revenue import COMPANIES, SEC_PAUSE, SEC_UA, SUBMISSIONS

KEY = "sec_8k_deals"
FIELDS = ["company", "company_slug", "cik", "form", "items", "item_1_01", "item_2_01", "filing_date", "report_date",
          "accession", "primary_document_description", "filing_url", "document_url"]
ITEMS = ("1.01", "2.01")
FORMS = ("8-K", "8-K/A")
OLDEST_YEAR = 2018
EXTRA = "https://data.sec.gov/submissions/{name}"


def _rows(block: dict) -> list:
    return [dict(zip(block.keys(), vals)) for vals in zip(*block.values())] if block else []


def deal_filings(rows: list) -> list:
    """8-K and 8-K/A filings from OLDEST_YEAR on that declare Item 1.01 or 2.01, reduced to the metadata kept."""
    return [
        {k: r.get(k, "") for k in ("form", "items", "filingDate", "reportDate", "accessionNumber",
                                    "primaryDocument", "primaryDocDescription")}
        for r in rows
        if r.get("form") in FORMS and (r.get("filingDate") or "")[:4] >= str(OLDEST_YEAR)
        and any(i.strip() in ITEMS for i in (r.get("items") or "").split(","))
    ]


def fetch_raw(companies: dict = None) -> bytes:
    """{"companies": [{slug, cik, name, filings: [8-K rows with item 1.01/2.01], status}]} (filtered as read)."""
    companies = companies or COMPANIES
    old = http.PAUSE_SECONDS
    http.PAUSE_SECONDS = SEC_PAUSE
    out = []
    try:
        for slug, cik in companies.items():
            entry = {"slug": slug, "cik": cik, "name": "", "filings": [], "status": ""}
            out.append(entry)
            try:
                sub = json.loads(fetch(SUBMISSIONS.format(cik=cik), headers={"User-Agent": SEC_UA}))
            except Exception as e:
                entry["status"] = f"submissions API error: {e}"
                continue
            entry["name"] = sub.get("name", "")
            blocks = [sub.get("filings", {}).get("recent", {})]
            for extra in sub.get("filings", {}).get("files", []):
                if (extra.get("filingTo") or "")[:4] >= str(OLDEST_YEAR):
                    blocks.append(json.loads(fetch(EXTRA.format(name=extra["name"]), headers={"User-Agent": SEC_UA})))
            rows = [r for b in blocks for r in _rows(b)]
            entry["periodic_forms"] = sorted({r.get("form") for r in rows if r.get("form") in ("10-K", "10-Q", "20-F", "40-F")})
            entry["count_8k"] = sum(1 for r in rows if r.get("form") in FORMS)
            entry["filings"] = deal_filings(rows)
            entry["status"] = "ok" if entry["count_8k"] else "no 8-K filings in the data read (foreign private issuers file 6-K instead)"
    finally:
        http.PAUSE_SECONDS = old
    return json.dumps({"companies": out}, ensure_ascii=False).encode("utf-8")


def parse(raw: bytes) -> list:
    data = json.loads(raw)
    seen, out = set(), []
    for c in data["companies"]:
        cik = c["cik"]
        for f in c.get("filings", []):
            acc = f["accessionNumber"]
            if (cik, acc) in seen:
                continue
            seen.add((cik, acc))
            items = [i.strip() for i in (f.get("items") or "").split(",") if i.strip()]
            base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/"
            out.append({
                "company": c.get("name", ""), "company_slug": c["slug"], "cik": cik, "form": f["form"],
                "items": items, "item_1_01": "yes" if "1.01" in items else "no",
                "item_2_01": "yes" if "2.01" in items else "no",
                "filing_date": f.get("filingDate", ""), "report_date": f.get("reportDate", ""), "accession": acc,
                "primary_document_description": f.get("primaryDocDescription", ""),
                "filing_url": base,
                "document_url": base + f["primaryDocument"] if f.get("primaryDocument") else "",
            })
    out.sort(key=lambda r: (r["company_slug"], r["accession"]))
    out.sort(key=lambda r: r["filing_date"], reverse=True)
    return out


def coverage(raw: bytes) -> list:
    data = json.loads(raw)
    return [{"company": c.get("name", ""), "company_slug": c["slug"], "cik": c["cik"],
             "periodic_forms": c.get("periodic_forms", []), "count_8k_read": c.get("count_8k", 0),
             "rows_item_1_01_or_2_01": len(c.get("filings", [])), "status": c.get("status", "")}
            for c in data["companies"]]
