"""EMA: medicines granted PRIME (PRIority MEdicines) eligibility, current and previous, from EMA's published list.

EMA publishes this list only as an Excel workbook (two tabs: "PRIME products (current)" and "PRIME products
(previous)"). It is read here with the standard library (zipfile + XML); no spreadsheet package is needed.
EMA does not name the applicant company in this list (only "SME" or "Other"), so no organisation field exists.
"""

import datetime as dt
import io
import re
import xml.etree.ElementTree as ET
import zipfile

from ..http import fetch

KEY = "ema_prime"
FIELDS = ["name", "substance_type", "therapeutic_area", "therapeutic_indication", "supporting_data",
          "applicant_type", "prime_granted_date", "early_entry", "prime_list", "status", "list_date"]
URL = "https://www.ema.europa.eu/en/documents/other/list-medicines-currently-prime-scheme_en.xlsx"
MIN_RECORDS = 120

_M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"
SHEETS = {"PRIME products (current)": "current", "PRIME products (previous)": "previous"}
# header text in the workbook -> our field
COLUMNS = {
    "name": "name", "substance type": "substance_type", "therapeutic area": "therapeutic_area",
    "therapeutic indication": "therapeutic_indication", "type of data supporting request": "supporting_data",
    "type of applicant": "applicant_type", "date of granting prime eligibility": "prime_granted_date",
    "status": "status",
}
REQUIRED = {"name", "substance_type", "therapeutic_area", "therapeutic_indication", "applicant_type",
            "prime_granted_date"}


def fetch_raw() -> bytes:
    return fetch(URL, timeout=120)


def _clean(s) -> str:
    """Collapse spaces; separate lines inside a cell (e.g. a status history) with "; "."""
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in str(s or "").replace("\r", "\n").split("\n")]
    out = ""
    for ln in (x for x in lines if x):
        if not out:
            out = ln
        elif out.endswith((",", "-")) or ln.startswith("("):
            out += " " + ln                         # a line wrapped mid-phrase
        else:
            out += "; " + ln
    return out


def excel_date(value: str) -> str:
    """Excel serial day number (1900 date system) or a dd/mm/yyyy string -> YYYY-MM-DD; '' when not a date."""
    v = _clean(value)
    if re.fullmatch(r"\d+(\.0+)?", v):
        n = int(float(v))
        if 20000 < n < 80000:                       # 1954..2119: anything else is not a grant date
            return (dt.date(1899, 12, 30) + dt.timedelta(days=n)).isoformat()
        return ""
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", v)
    return f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}" if m else ""


def _col(ref: str) -> str:
    return re.match(r"[A-Z]+", ref)[0]


def _sheets(z: zipfile.ZipFile) -> dict:
    """Sheet name -> worksheet path inside the zip."""
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    target = {r.get("Id"): r.get("Target") for r in rels.iter(_PR + "Relationship")}
    out = {}
    for s in wb.iter(_M + "sheet"):
        t = target[s.get(_R + "id")].lstrip("/")
        out[s.get("name")] = t if t.startswith("xl/") else "xl/" + t
    return out


def parse(raw: bytes, min_records: int = MIN_RECORDS) -> list:
    z = zipfile.ZipFile(io.BytesIO(raw))
    strings = []
    if "xl/sharedStrings.xml" in z.namelist():
        strings = ["".join(t.text or "" for t in si.iter(_M + "t"))
                   for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(_M + "si")]
    styles = ET.fromstring(z.read("xl/styles.xml"))
    fonts = styles.find(_M + "fonts").findall(_M + "font")
    italic = {i for i, xf in enumerate(styles.find(_M + "cellXfs").findall(_M + "xf"))
              if fonts[int(xf.get("fontId", 0))].find(_M + "i") is not None}
    paths = _sheets(z)
    missing = [s for s in SHEETS if s not in paths]
    if missing:
        raise RuntimeError(f"EMA PRIME workbook is missing tab(s) {missing}; layout changed")

    out = []
    for sheet, which in SHEETS.items():
        root = ET.fromstring(z.read(paths[sheet]))
        header, list_date, count = None, "", 0
        for row in root.iter(_M + "row"):
            cells, styled = {}, {}
            for c in row.findall(_M + "c"):
                v = c.find(_M + "v")
                if v is not None:
                    val = strings[int(v.text)] if c.get("t") == "s" else v.text
                else:
                    inline = c.find(_M + "is")
                    val = "".join(t.text or "" for t in inline.iter(_M + "t")) if inline is not None else ""
                if _clean(val):
                    cells[_col(c.get("r"))] = _clean(val)
                    styled[_col(c.get("r"))] = int(c.get("s", 0))
            if not cells:
                continue
            if header is None:
                first = cells.get("A", "")
                if not list_date and len(cells) == 1 and excel_date(first):
                    list_date = excel_date(first)              # the list's "as of" date, above the table
                if first.rstrip("*").strip().lower() == "name":
                    header = {col: COLUMNS[k] for col, h in cells.items()
                              if (k := h.rstrip("*").strip().lower()) in COLUMNS}
                    lost = REQUIRED - set(header.values())
                    if lost:
                        raise RuntimeError(f"EMA PRIME tab {sheet!r}: column(s) {sorted(lost)} not found")
                continue
            rec = {header[col]: val for col, val in cells.items() if col in header}
            date_col = next(col for col, f in header.items() if f == "prime_granted_date")
            granted = excel_date(cells.get(date_col, ""))
            if not rec.get("name") or not granted:
                continue                                       # footnotes and blank rows below the table
            name_col = next(col for col, f in header.items() if f == "name")
            count += 1
            out.append({
                "name": rec["name"],
                "substance_type": rec.get("substance_type", ""),
                "therapeutic_area": rec.get("therapeutic_area", ""),
                "therapeutic_indication": rec.get("therapeutic_indication", ""),
                "supporting_data": rec.get("supporting_data", ""),
                "applicant_type": rec.get("applicant_type", ""),
                "prime_granted_date": granted,
                "early_entry": "yes" if styled.get(name_col) in italic else "no",
                "prime_list": which,
                "status": rec.get("status", "") if which == "previous" else "Currently in PRIME scheme",
                "list_date": list_date,
            })
        if header is None:
            raise RuntimeError(f"EMA PRIME tab {sheet!r}: header row not found; layout changed")
        if count == 0:
            raise RuntimeError(f"EMA PRIME tab {sheet!r} holds no medicines")
    if len(out) < min_records:
        raise RuntimeError(f"only {len(out)} PRIME medicines; refusing a partial dataset")
    out.sort(key=lambda r: (r["prime_list"], r["name"].lower(), r["prime_granted_date"], r["therapeutic_indication"]))
    return out
