"""FDA Orange Book: patents and exclusivities for approved drug products, from the official data files zip.

One tidy table, one row per protection: every patent row (patent.txt) and every exclusivity row (exclusivity.txt),
each joined to its product (products.txt) on application type + application number + product number, so a row
carries the ingredient, trade name, applicant company, form, strength and approval date it protects.
`record_type` says which kind of row it is; patent-only columns are blank on exclusivity rows and vice versa.
Products with no listed patent or exclusivity are not included. Patents are listed for NDAs only; generic (ANDA)
products appear only through exclusivity rows such as PC (180-day patent challenge exclusivity).
"""

import datetime as dt
import io
import zipfile

from ..http import fetch
from ..util import yes

KEY = "fda_orange_book"
FIELDS = ["record_type", "appl_type", "appl_no", "product_no", "ingredient", "trade_name", "applicant",
          "dosage_form", "route", "strength", "approval_date", "reference_listed_drug", "marketing_category",
          "patent_no", "pediatric_extension", "patent_expiry", "drug_substance_claim", "drug_product_claim",
          "patent_use_code", "delist_requested", "patent_submitted", "exclusivity_code", "exclusivity_expiry"]
URL = "https://www.fda.gov/media/76860/download"
MIN_RECORDS = 15000

PRODUCT_HEADER = ["Ingredient", "DF;Route", "Trade_Name", "Applicant", "Strength", "Appl_Type", "Appl_No",
                  "Product_No", "TE_Code", "Approval_Date", "RLD", "RS", "Type", "Applicant_Full_Name"]
PATENT_HEADER = ["Appl_Type", "Appl_No", "Product_No", "Patent_No", "Patent_Expire_Date_Text", "Drug_Substance_Flag",
                 "Drug_Product_Flag", "Patent_Use_Code", "Delist_Flag", "Submission_Date"]
EXCLUSIVITY_HEADER = ["Appl_Type", "Appl_No", "Product_No", "Exclusivity_Code", "Exclusivity_Date"]
MARKETING = {"RX": "prescription", "OTC": "over the counter", "DISCN": "discontinued"}


def fetch_raw() -> bytes:
    return fetch(URL, timeout=180)


def _date(v: str) -> str:
    """'Aug 24, 2026' -> '2026-08-24'; anything else (e.g. 'Approved Prior to Jan 1, 1982') is kept as written."""
    v = (v or "").strip()
    try:
        return dt.datetime.strptime(v, "%b %d, %Y").date().isoformat()
    except ValueError:
        return v


def _flag(v: str) -> str:
    return "yes" if (v or "").strip().upper() == "Y" else ""


def _table(zf: zipfile.ZipFile, name: str, header: list) -> list:
    names = {n.lower(): n for n in zf.namelist()}
    if name not in names:
        raise RuntimeError(f"Orange Book zip has no {name} (holds {zf.namelist()})")
    data = zf.read(names[name])
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    lines = [l for l in text.splitlines() if l.strip()]
    got = lines[0].split("~") if lines else []
    if got != header:
        raise RuntimeError(f"{name}: unexpected header {got}")
    rows = []
    for n, line in enumerate(lines[1:], start=2):
        cells = line.split("~")
        if len(cells) != len(header):
            raise RuntimeError(f"{name} line {n}: {len(cells)} fields, expected {len(header)}")
        rows.append(dict(zip(header, (c.strip() for c in cells))))
    return rows


def parse(raw: bytes, min_records: int = MIN_RECORDS) -> list:
    zf = zipfile.ZipFile(io.BytesIO(raw))
    products = {}
    for p in _table(zf, "products.txt", PRODUCT_HEADER):
        k = (p["Appl_Type"], p["Appl_No"], p["Product_No"])
        if k in products:
            raise RuntimeError(f"products.txt: duplicate product {k}")
        products[k] = p
    patents = _table(zf, "patent.txt", PATENT_HEADER)
    exclusivities = []
    seen = set()
    for e in _table(zf, "exclusivity.txt", EXCLUSIVITY_HEADER):   # the file repeats some rows verbatim; keep one
        k = tuple(e.values())
        if k not in seen:
            seen.add(k)
            exclusivities.append(e)

    def base(kind: str, r: dict) -> dict:
        k = (r["Appl_Type"], r["Appl_No"], r["Product_No"])
        p = products.get(k)
        if p is None:
            raise RuntimeError(f"{kind} row for {k} has no product in products.txt")
        form, _, route = p["DF;Route"].partition(";")
        row = dict.fromkeys(FIELDS, "")
        row.update({
            "record_type": kind, "appl_type": k[0], "appl_no": k[1], "product_no": k[2],
            "ingredient": p["Ingredient"], "trade_name": p["Trade_Name"], "applicant": p["Applicant_Full_Name"],
            "dosage_form": form.strip(), "route": route.strip(), "strength": p["Strength"],
            "approval_date": _date(p["Approval_Date"]), "reference_listed_drug": yes(p["RLD"]),
            "marketing_category": MARKETING.get(p["Type"], p["Type"]),
        })
        return row

    out = []
    for r in patents:
        row = base("patent", r)
        num = r["Patent_No"]
        row.update({
            "patent_no": num.replace("*PED", ""),
            "pediatric_extension": "yes" if num.endswith("*PED") else "",
            "patent_expiry": _date(r["Patent_Expire_Date_Text"]),
            "drug_substance_claim": _flag(r["Drug_Substance_Flag"]),
            "drug_product_claim": _flag(r["Drug_Product_Flag"]),
            "patent_use_code": r["Patent_Use_Code"],
            "delist_requested": _flag(r["Delist_Flag"]),
            "patent_submitted": _date(r["Submission_Date"]),
        })
        out.append(row)
    for r in exclusivities:
        row = base("exclusivity", r)
        row.update({"exclusivity_code": r["Exclusivity_Code"], "exclusivity_expiry": _date(r["Exclusivity_Date"])})
        out.append(row)
    if len(out) != len(patents) + len(exclusivities):
        raise RuntimeError("row count does not match the source files")
    if len(out) < min_records:
        raise RuntimeError(f"only {len(out)} Orange Book patent/exclusivity rows; refusing a partial dataset")
    out.sort(key=lambda r: (r["appl_type"], r["appl_no"], r["product_no"], r["record_type"], r["patent_no"],
                            r["pediatric_extension"], r["patent_use_code"], r["exclusivity_code"],
                            r["exclusivity_expiry"]))
    return out
