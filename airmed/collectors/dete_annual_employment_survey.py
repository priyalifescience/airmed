"""DETE (Ireland): Annual Employment Survey (AES), employment in agency-assisted firms, in tidy long format.

The Department of Enterprise, Tourism and Employment surveys every client company of IDA Ireland, Enterprise
Ireland and Udaras na Gaeltachta each year and publishes the appendix tables as CSV files on the survey's
publication page (annual-employment-survey-YYYY.html): employment by sector and by region for all, Irish-owned
and foreign-owned firms (tables A1-A9, B1-B9), and by county for all firms. "Chemicals" (which includes
pharmaceuticals) and "Medical Devices" are sectors of their own, so this is the official headcount series for
Ireland's agency-assisted pharma and medtech industry. Only these aggregate tables are used; no firm is named.

fetch_raw finds the newest publication page (this year back to three years ago) and downloads its four appendix
CSVs (all firms, all firms by county, Irish-owned, foreign-owned).

One row per table, category (sector, region or county) and year, with the number of jobs as published.
Choices:
- the "% Change" columns are left out (they can be computed from the jobs figures);
- some CSVs still contain an older copy of a table (e.g. "B7 ... 2015-2024" next to "B7 ... 2016-2025"); only the
  copy covering the latest years is kept;
- category_level tells totals and groups apart from items: the sector groups "Manufacturing and Other
  Industry", "Primary Production" and "Services" and the region groups "BMW Area", "South & East" and the first
  "Dublin" row (the Dublin region; the second "Dublin" row is the Dublin sub-region, with the same figures);
- rows with no figures at all (the county pivot's "(blank)" row) are left out.
"""

import csv
import datetime
import io
import json
import re

from ..http import fetch

KEY = "dete_annual_employment_survey"
FIELDS = ["table", "table_title", "ownership", "employment_type", "breakdown", "category", "category_level",
          "year", "jobs"]
BASE = "https://enterprise.gov.ie"
PAGE = BASE + "/en/publications/annual-employment-survey-{}.html"
FILES = {"all-firms": "All companies", "all-firms-by-county": "All companies", "irish-firms": "Irish-owned",
         "foreign-firms": "Foreign-owned"}
LINK_RE = re.compile(r'href="(/en/publications/publication-files/aes-\d{4}-\d{4}-appendix-tables-'
                     r'(all-firms-by-county|all-firms|irish-firms|foreign-firms)\.csv)"', re.I)
TITLE_RE = re.compile(r"^([AB]\d{1,2})\s*[-–]?\s*(.+)$")
COUNTY_RE = re.compile(r"^Sum of (.+)$")
COUNTY_TYPES = {"total jobs": "Total", "pft": "Permanent, full-time", "oth": "Part-time, temporary and short-term contract"}
GROUPS = {"manufacturing and other industry", "primary production", "services", "bmw area", "south & east"}
TOTALS = {"grand total", "all regions"}


def fetch_raw() -> bytes:
    """The newest publication page's four appendix CSVs, as JSON {"page": url, "files": {name: csv text}}."""
    year = datetime.date.today().year
    for y in range(year, year - 4, -1):
        url = PAGE.format(y)
        try:
            html = fetch(url, timeout=60, retries=1).decode("utf-8", "replace")
        except Exception:
            continue
        links = {name: path for path, name in LINK_RE.findall(html)}
        if set(links) == set(FILES):
            files = {}
            for name, path in links.items():
                body = fetch(BASE + path, timeout=120)
                try:
                    files[name] = body.decode("utf-8-sig")
                except UnicodeDecodeError:
                    files[name] = body.decode("cp1252")
            return json.dumps({"page": url, "files": files}).encode("utf-8")
    raise RuntimeError("DETE: no Annual Employment Survey page with the four appendix CSVs found")


def _num(s: str):
    s = s.strip().replace(",", "").replace(" ", "")
    if not s:
        return None
    if not re.fullmatch(r"-?\d+(\.\d+)?", s):
        raise RuntimeError(f"DETE: unexpected figure {s!r}")
    f = float(s)
    return int(f) if f.is_integer() else f


def _employment_type(title: str) -> str:
    low = title.lower()
    if "permanent" in low:
        return "Permanent, full-time"
    if "part-time" in low:
        return "Part-time, temporary and short-term contract"
    return "Total"


def _tables(name: str, text: str) -> list:
    """Split one CSV into its stacked tables: [{code, title, type, breakdown, years: {col: year}, rows: [...]}]."""
    tables, cur = [], None
    for cells in csv.reader(io.StringIO(text)):
        cells = [c.strip() for c in cells]
        if not any(cells):
            continue
        first, rest = cells[0], cells[1:]
        m = TITLE_RE.match(first)
        if m and not any(rest):
            title = m.group(2).strip()
            low = title.lower()
            breakdown = "Sector" if "by sector" in low else "Region" if "by region" in low else ""
            if not breakdown:
                raise RuntimeError(f"DETE {name}: table {m.group(1)} has no 'by sector' / 'by region' in {title!r}")
            cur = {"code": m.group(1), "title": title, "type": _employment_type(title), "breakdown": breakdown,
                   "years": None, "rows": []}
            tables.append(cur)
            continue
        m = COUNTY_RE.match(first)
        if m and name == "all-firms-by-county":
            kind = m.group(1).strip()
            if kind.lower() not in COUNTY_TYPES:
                raise RuntimeError(f"DETE {name}: unknown county pivot {first!r}")
            etype = COUNTY_TYPES[kind.lower()]
            cur = {"code": "county", "title": f"All Companies - {etype} Employment by County ('Sum of {kind}')",
                   "type": etype, "breakdown": "County", "years": None, "rows": []}
            tables.append(cur)
            continue
        if cur is None:
            continue
        if cur["years"] is None:
            # the header row: consecutive years (some figures look like years too, so only before the data)
            years = {i: c for i, c in enumerate(cells) if i > 0 and re.fullmatch(r"20\d\d", c)}
            ys = [int(y) for y in years.values()]
            if len(ys) >= 3 and ys == list(range(ys[0], ys[0] + len(ys))):
                cur["years"] = years
            continue   # the header, or section labels between pivots ("Permanent Full-Time", "Part-Time Jobs")
        cur["rows"].append(cells)
    return tables


def parse(raw: bytes) -> list:
    data = json.loads(raw)
    files = data["files"]
    missing = [f for f in FILES if f not in files]
    if missing:
        raise RuntimeError(f"DETE: appendix files missing: {missing}")
    out = []
    for name, ownership in FILES.items():
        tables = [t for t in _tables(name, files[name]) if t["years"]]
        # keep, for each table code (and employment type, for the county pivots), the copy with the latest years
        best = {}
        for t in tables:
            k = (t["code"], t["type"])
            if k not in best or max(t["years"].values()) > max(best[k]["years"].values()):
                best[k] = t
        if not best:
            raise RuntimeError(f"DETE {name}: no tables found")
        for t in tables:
            if best[(t["code"], t["type"])] is not t:
                continue
            seen = set()
            for cells in t["rows"]:
                cat = cells[0]
                figures = {y: _num(cells[i]) if i < len(cells) else None for i, y in t["years"].items()}
                if not cat or all(v is None for v in figures.values()):
                    continue
                low = cat.lower()
                if low in TOTALS:
                    level = "total"
                elif low in GROUPS or (t["breakdown"] == "Region" and low == "dublin" and low not in seen):
                    level = "group"
                else:
                    level = "item"
                seen.add(low)
                for y, v in figures.items():
                    if v is None:
                        continue
                    out.append({"table": t["code"], "table_title": t["title"], "ownership": ownership,
                                "employment_type": t["type"], "breakdown": t["breakdown"], "category": cat,
                                "category_level": level, "year": y, "jobs": v})
    return out
