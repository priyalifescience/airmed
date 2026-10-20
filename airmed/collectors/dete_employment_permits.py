"""DETE (Ireland): employment permits issued, by employer, by economic sector and by county, from the yearly
statistics workbooks of the Department of Enterprise, Tourism and Employment.

Three tables, each row tagged in `table`:
- employer: permits issued to each named employer (monthly columns from 2020, and in 2018-2019; annual only before);
- sector:   permits issued by economic sector (NACE-based sectors from 2020; DETE's older sector list before);
- county:   permits by county of employment (annual; DETE also lists some countries and "No County Entered").
All sectors are kept: filter on `sector` (e.g. "C - Manufacture of Chemicals & Pharmaceuticals") for life sciences.

Years: one workbook per table per year, linked from the statistics page; the current year is year-to-date and is
replaced every month (`latest_month` says how far it goes). The 2009 workbooks, and the 2010 sector and county
workbooks, are old binary .xls files that the standard library cannot read: they are skipped (2010 employer data,
published as .xlsx, is kept). "Total" / "Grand Total" rows are not copied (they are sums of the rows kept).

Layouts differ by year and are read by their header cells:
- "wide" (2020 on): one row per employer/sector/county, one column per month plus a total column (as published);
- "long" (2010-2019): Year / Month / label / New / Renewal / Total / Refused / Withdrawn, with a month row followed
  by that month's rows. Where a long workbook has month blocks, the monthly totals become issued_jan..issued_dec and
  issued_total, new, renewal, refused and withdrawn are summed from the month blocks (totals_basis
  "summed_from_months"); otherwise they are the published annual values (totals_basis "published").

Persons: an employer can be a sole trader, i.e. a natural person. Airmid never lists persons, so an employer name is
kept only when it carries a company or public-body marker (see ORG_MARKERS: Ltd, Limited, DAC, UC, PLC, CLG,
Teoranta, LLP, Partnership, Inc, GmbH, ..., University, Hospital, HSE, Council, ...). Names without one are
withheld: all such rows of a workbook are merged into ONE row with `employer` blank and `employers_withheld` = the
number of rows merged, their counts added up, so the table still adds up to the published totals. The rule is
deliberately strict: a company whose published name lacks a legal form (e.g. "Abbott Ireland") is withheld too.

Month columns: a month the workbook covers but where the row has no figure is 0; a month the workbook does not
cover (later months of the current year; August 2019, absent from DETE's 2019 employer workbook) is blank.
Size: about 57,000 rows / 27 MB JSON for 2010-2026; growth is about 8,000 employer rows a year.
"""

import base64
import io
import json
import re
import xml.etree.ElementTree as ET
import zipfile

from ..http import fetch

KEY = "dete_employment_permits"
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
FIELDS = (["year", "table", "employer", "employers_withheld", "sector", "county", "latest_month", "issued_total"]
          + [f"issued_{m}" for m in MONTHS] + ["new", "renewal", "refused", "withdrawn", "totals_basis", "source_file"])
BASE = "https://enterprise.gov.ie"
PAGE = BASE + "/en/what-we-do/workplace-and-skills/employment-permits/statistics/"
YEAR_PAGE_RE = re.compile(r'href="(/en/[Pp]ublications/[Ee]mployment-[Pp]ermit-[Ss]tatis[a-z]*-(\d{4})\.html)"')
FILE_RE = re.compile(r'href="(/en/publications/publication-files/[^"]+?(\d{4})\.(xlsx|xls))"', re.I)
MIN_YEARS = 15

# ---------- natural persons ----------

# Tokens (case-insensitive, dots removed: "Ltd." -> "ltd", "S.A." -> "sa") that mark a company or a public body.
# Deliberately not included: "as" (as in "X trading as Y"), generic business words such as Services or Consulting
# (common in sole traders' trading names), and "Ireland".
ORG_MARKERS = {
    # Irish and UK legal forms
    "ltd", "limited", "dac", "uc", "ulc", "plc", "clg", "teoranta", "teo", "llp", "lp", "partnership", "unlimited",
    "company", "co", "cuideachta", "group", "holdings",
    # other legal forms
    "inc", "incorporated", "corp", "corporation", "llc", "pty", "gmbh", "ag", "kg", "sa", "sas", "sarl", "srl",
    "spa", "bv", "nv", "bvba", "ab", "oy", "oyj", "aps", "asa", "kft", "sro", "lda", "sl", "slu", "pte", "bhd",
    "sdn", "pvt", "zoo",
    # public bodies, institutions, branches of foreign companies
    "university", "ollscoil", "college", "institute", "institiuid", "hospital", "hospitals", "hospice", "hse",
    "council", "department", "authority", "agency", "board", "commission", "school", "scoil", "foundation",
    "association", "society", "trust", "branch", "embassy",
}
ORG_PHRASES = ("health service executive", "a/s", "sp z o", "s.p.a")


def looks_like_organisation(name: str) -> bool:
    """True when the name carries a company or public-body marker; False for names that may be natural persons."""
    low = (name or "").lower()
    if any(p in low for p in ORG_PHRASES):
        return True
    tokens = re.findall(r"\w+", low.replace(".", ""))
    return any(t in ORG_MARKERS for t in tokens)


# ---------- fetching ----------

def _table(filename: str) -> str:
    f = filename.lower()
    if "nationality" in f:
        return ""
    if "compan" in f:
        return "employer"
    if "sector" in f:
        return "sector"
    if "county" in f:
        return "county"
    return ""


def links(stats_html: str, year_pages: dict) -> tuple:
    """({url: (year, table)} for .xlsx workbooks, [skipped .xls urls]) from the year pages' HTML."""
    found, skipped = {}, []
    for html in year_pages.values():
        for path, year, ext in FILE_RE.findall(html):
            table = _table(path.rsplit("/", 1)[-1])
            if not table:
                continue
            url = BASE + path
            if ext.lower() == "xls":
                skipped.append(url)
            else:
                found[url] = (int(year), table)
    return found, sorted(set(skipped))


def fetch_raw() -> bytes:
    """The statistics page, every year page, and every employer/sector/county .xlsx as base64, in one JSON."""
    stats = fetch(PAGE, timeout=60).decode("utf-8", "replace")
    pages = {}
    for path, year in sorted(set(YEAR_PAGE_RE.findall(stats))):
        pages[BASE + path] = fetch(BASE + path, timeout=60).decode("utf-8", "replace")
    if len(pages) < MIN_YEARS:
        raise RuntimeError(f"DETE statistics page: only {len(pages)} year pages found (layout changed?)")
    found, skipped = links(stats, pages)
    files = {url: base64.b64encode(fetch(url, timeout=120)).decode("ascii") for url in sorted(found)}
    return json.dumps({"files": files, "skipped_xls": skipped}).encode("utf-8")


# ---------- workbook reading ----------

_M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _rows(xlsx: bytes) -> list:
    """Rows of the first worksheet that has any cell, as [{column letter: text}]."""
    z = zipfile.ZipFile(io.BytesIO(xlsx))
    strings = []
    if "xl/sharedStrings.xml" in z.namelist():
        strings = ["".join(t.text or "" for t in si.iter(_M + "t"))
                   for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(_M + "si")]
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    target = {r.get("Id"): r.get("Target") for r in rels.iter(_PR + "Relationship")}
    for s in wb.iter(_M + "sheet"):
        t = target[s.get(_R + "id")].lstrip("/")
        rows = []
        for row in ET.fromstring(z.read(t if t.startswith("xl/") else "xl/" + t)).iter(_M + "row"):
            cells = {}
            for c in row.findall(_M + "c"):
                v = c.find(_M + "v")
                if v is not None:
                    val = strings[int(v.text)] if c.get("t") == "s" else (v.text or "")
                else:
                    inline = c.find(_M + "is")
                    val = "".join(x.text or "" for x in inline.iter(_M + "t")) if inline is not None else ""
                val = re.sub(r"\s+", " ", val).strip()
                if val:
                    cells[re.match(r"[A-Z]+", c.get("r"))[0]] = val
            if cells:
                rows.append(cells)
        if rows:
            return rows
    return []


def _is_num(s: str) -> bool:
    return re.fullmatch(r"-?\d+(\.0+)?", s) is not None


def _int(s: str) -> int:
    if not _is_num(s):
        raise ValueError(f"DETE: not a whole number: {s!r}")
    return int(float(s))


def _month(h: str):
    """0-11 for a month header ('Jan', 'January', 'Permits Issued Jan'), else None."""
    h = re.sub(r"^permits issued\s+", "", h.lower()).strip()
    for i, m in enumerate(MONTHS):
        if h in (m, "sept" if m == "sep" else m) or h == m + {"jan": "uary", "feb": "ruary", "mar": "ch", "apr": "il", "may": "", "jun": "e",
                                   "jul": "y", "aug": "ust", "sep": "tember", "oct": "ober", "nov": "ember",
                                   "dec": "ember"}[m]:
            return i
    return None


LABEL_HEADERS = {"employer name", "sector", "economic sector", "county", "county/country"}
MEASURES = {"new", "renewal", "refused", "withdrawn", "issued"}


def _layout(header_rows: list) -> dict:
    """Column roles from the header cells above the data."""
    roles = {}
    for row in header_rows:
        for col, text in row.items():
            h = re.sub(r"^permits issued\s+", "", text.lower()).strip()
            m = _month(text)
            if m is not None:
                roles[col] = ("mcol", m)                    # a month header wins over 'Issued' under it
            elif roles.get(col, ("",))[0] == "mcol":
                continue
            elif h in ("total", "grand total"):
                roles[col] = ("total",)
            elif h in MEASURES:
                roles[col] = ("measure", h)
            elif h in LABEL_HEADERS:
                roles[col] = ("label",)
            elif h in ("year", "month"):
                roles[col] = (h,)
    cols = {r[0]: c for c, r in roles.items() if r[0] in ("label", "year", "month", "total")}
    if "label" not in cols:
        if "month" in cols:                                    # long layout, label column has no header
            cols["label"] = chr(ord(cols["month"]) + 1)
        else:
            cols["label"] = "A"
    return {"roles": roles, "label": cols["label"], "year": cols.get("year"), "month": cols.get("month"),
            "long": "year" in cols or "month" in cols or not any(r[0] == "mcol" for r in roles.values())}



def _blank(year: int, table: str, source_file: str) -> dict:
    return {"year": year, "table": table, "employer": "", "employers_withheld": "", "sector": "", "county": "",
            "latest_month": "", "issued_total": "", **{f"issued_{m}": "" for m in MONTHS},
            "new": "", "renewal": "", "refused": "", "withdrawn": "", "totals_basis": "", "source_file": source_file}


def _finish(rec: dict, label: str, months: dict, covered: set, latest) -> dict:
    """Put the label in its field (withholding person-like employer names) and fill the month columns:
    a month the workbook covers but the row has no figure for is 0; a month the workbook does not cover is ''."""
    table = rec["table"]
    if table == "employer":
        if looks_like_organisation(label):
            rec["employer"], rec["employers_withheld"] = label, 0
        else:
            rec["employer"], rec["employers_withheld"] = "", 1
    else:
        rec[table] = label
    if latest is not None:
        rec["latest_month"] = latest + 1
        for i, m in enumerate(MONTHS):
            rec[f"issued_{m}"] = months.get(i, 0) if i in covered else ""
    return rec


def _add(a, b):
    if a == "":
        return b
    return a if b == "" else a + b


def _merge_withheld(rows: list) -> list:
    """All employer rows whose name was withheld become one row per workbook, counts added up."""
    keep, merged = [], None
    for r in rows:
        if r["table"] != "employer" or r["employers_withheld"] == 0:
            keep.append(r)
            continue
        if merged is None:
            merged = dict(r)
            continue
        for k in ["employers_withheld", "issued_total", "new", "renewal", "refused", "withdrawn"] + [
                f"issued_{m}" for m in MONTHS]:
            merged[k] = _add(merged[k], r[k])
    return keep + ([merged] if merged else [])


def parse_workbook(xlsx: bytes, year: int, table: str, source_file: str) -> list:
    rows = _rows(xlsx)
    header, data = [], []
    for r in rows:
        if not data and all(not _is_num(v) or re.fullmatch(r"(19|20)\d\d", v) for v in r.values()):
            header.append(r)
        else:
            data.append(r)
    lay = _layout(header)
    roles, lab = lay["roles"], lay["label"]
    if not any(r[0] in ("total", "mcol", "measure") for r in roles.values()):
        raise RuntimeError(f"DETE {source_file}: no count columns found in the header {header[:3]}")
    out = []
    if not lay["long"]:                                        # wide: one row per label, month columns
        month_cols = {c: r[1] for c, r in roles.items() if r[0] == "mcol"}
        covered, latest = set(month_cols.values()), max(month_cols.values())
        for r in data:
            label = r.get(lab, "")
            if not label or label.lower() in ("total", "grand total"):
                continue
            rec = _blank(year, table, source_file)
            months = {}
            for col, val in r.items():
                role = roles.get(col)
                if not role or col == lab:
                    continue
                if role[0] == "mcol":
                    months[role[1]] = _int(val)
                elif role[0] == "total" or role == ("measure", "issued"):
                    rec["issued_total"] = _int(val)
                elif role[0] == "measure":
                    rec[role[1]] = _int(val)
            if rec["issued_total"] == "" and months:
                raise RuntimeError(f"DETE {source_file}: row {label!r} has no total column")
            rec["totals_basis"] = "published"
            out.append(_finish(rec, label, months, covered, latest))
        return _merge_withheld(out)

    # long: Year / Month / label / New / Renewal / Total / Refused / Withdrawn
    month, agg, order, covered = None, {}, [], set()
    for r in data:
        mark = [r.get(c, "") for c in (lay["year"], lay["month"]) if c and r.get(c)]
        if mark:
            m = _month(mark[-1])
            if m is not None:                                  # a month's total row (2019 has Nov/Dec under Year)
                month = m
                covered.add(m)
            elif not re.fullmatch(r"(19|20)\d\d", mark[0]):
                raise RuntimeError(f"DETE {source_file}: unexpected year/month cell {mark!r}")
            continue                                           # the year's or the month's total row
        label = r.get(lab, "")
        if not label or label.lower() in ("total", "grand total"):
            continue
        vals = {}
        for col, val in r.items():
            role = roles.get(col)
            if role and role[0] == "total":
                vals["issued"] = _int(val)
            elif role and role[0] == "measure":
                vals["issued" if role[1] == "issued" else role[1]] = _int(val)
        if month is None:                                      # annual table: one row per source row
            rec = _blank(year, table, source_file)
            rec["issued_total"] = vals.get("issued", "")
            for k in ("new", "renewal", "refused", "withdrawn"):
                rec[k] = vals.get(k, "")
            rec["totals_basis"] = "published"
            out.append(_finish(rec, label, {}, set(), None))
            continue
        if label not in agg:
            agg[label] = {"months": {}, "sums": {}}
            order.append(label)
        a = agg[label]
        a["months"][month] = a["months"].get(month, 0) + vals.get("issued", 0)
        for k in ("new", "renewal", "refused", "withdrawn"):
            if k in vals:
                a["sums"][k] = a["sums"].get(k, 0) + vals[k]
    if agg:
        latest = max(covered)
        for label in order:
            a = agg[label]
            rec = _blank(year, table, source_file)
            rec["issued_total"] = sum(a["months"].values())
            for k in ("new", "renewal", "refused", "withdrawn"):
                rec[k] = a["sums"].get(k, "")
            rec["totals_basis"] = "summed_from_months"
            out.append(_finish(rec, label, a["months"], covered, latest))
    return _merge_withheld(out)


def parse(raw: bytes) -> list:
    data = json.loads(raw)
    out = []
    for url, b64 in data["files"].items():
        name = url.rsplit("/", 1)[-1]
        year = int(re.search(r"(\d{4})\.xlsx$", name, re.I).group(1))
        table = _table(name)
        if not table:
            continue
        out.extend(parse_workbook(base64.b64decode(b64), year, table, name))
    tables = {"employer": 0, "sector": 1, "county": 2}
    out.sort(key=lambda r: (r["year"], tables[r["table"]], r["sector"], r["county"],
                            r["employer"] == "", r["employer"].lower()))
    return out
