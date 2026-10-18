"""ECDC ESAC-Net: antimicrobial consumption in EU/EEA countries, by country, year, sector and ATC group.

Source: the "downloadable tables" (Annex, tables D1-D24) of ECDC's Annual Epidemiological Report
"Antimicrobial consumption in the EU/EEA (ESAC-Net)" for 2022. This is the most recent ESAC-Net release ECDC
publishes as a machine-readable file: later years (2023, 2024) are published only as PDF reports and in the
interactive ESAC-Net dashboard, which has no download or API. The tables cover:
- J01 antibacterial subgroups (J01A, J01C, J01D, J01E, J01F, J01M, J01X) in the community, 2013-2022;
- J01 subgroups plus carbapenems (J01DH) and polymyxins (J01XB) in the hospital sector, 2013-2022;
- oral vancomycin + fidaxomicin and metronidazole in hospitals, 2022;
- antimycotics (J02, J02AA01), dermatological antifungals (D01B, D01BA02), antimycobacterials (J04A) and
  antivirals (J05), community and hospital combined, 2018-2022;
- the share of WHO AWaRe "Reserve" antibiotics in hospital antibiotic consumption, 2013-2022.

Values are as published (DDD per 1 000 inhabitants per day, except the Reserve share). ECDC's own trend
symbol and compound annual growth rate are kept per country and table. Country labels keep ECDC's footnote
markers in country_label (e.g. "Finland (a)": data include remote primary care centres and nursing homes).
Totals for all of J01 are not in these tables and are not computed here.
"""

import io
import re
import xml.etree.ElementTree as ET
import zipfile

from ..http import fetch

KEY = "ecdc_antimicrobial_consumption"
FIELDS = ["table", "table_title", "sector", "atc_code", "atc_group", "country", "country_label", "year", "value",
          "unit", "ecdc_trend", "ecdc_cagr"]
REPORT_YEAR = 2022
URL = ("https://www.ecdc.europa.eu/sites/default/files/documents/"
       "antimicrobial-resistance-ESAC-Net-report-downloadable-tables-2022.xlsx")
SECTORS = {"AC": "Community", "HC": "Hospital", "TC": "Community and hospital"}
DDD_UNIT = "DDD per 1 000 inhabitants per day"
RESERVE_UNIT = "share of all hospital antibiotic consumption (0-1)"
MIN_COUNTRIES = 20
_M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def fetch_raw() -> bytes:
    return fetch(URL, timeout=120)


def _read_xlsx(raw: bytes) -> dict:
    """{sheet name: [(row number, {column letter: text})]} using only the standard library."""
    z = zipfile.ZipFile(io.BytesIO(raw))
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        shared = ["".join(t.text or "" for t in si.iter(_M + "t"))
                  for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(_M + "si")]
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    out = {}
    for sh in ET.fromstring(z.read("xl/workbook.xml")).find(_M + "sheets"):
        target = rels[sh.get(_R + "id")].lstrip("/")
        target = target if target.startswith("xl/") else "xl/" + target
        rows = []
        for row in ET.fromstring(z.read(target)).iter(_M + "row"):
            cells = {}
            for c in row.findall(_M + "c"):
                col = re.match(r"[A-Z]+", c.get("r")).group(0)
                t, v = c.get("t"), c.find(_M + "v")
                if t == "s":
                    val = shared[int(v.text)]
                elif t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter(_M + "t"))
                else:
                    val = v.text if v is not None and v.text is not None else ""
                cells[col] = val.strip()
            rows.append((int(row.get("r")), cells))
        out[sh.get("name")] = rows
    return out


def _num(s: str):
    s = (s or "").strip()
    if s in ("", "N/A", "-") or s.startswith("#"):   # "#NUM!" etc. = Excel formula error in ECDC's sheet
        return ""
    return float(f"{float(s):.12g}")      # drop binary noise from Excel (1.2715000000000001 -> 1.2715)


def _country(label: str) -> str:
    s = re.sub(r"\s*\([a-z]\)\s*$", "", label)
    return re.sub(r"[\s*†#]+$", "", s).strip()


def _trend(s: str) -> str:
    s = (s or "").strip()
    return {"↑": "increase", "↓": "decrease", "-": "no significant trend", "N/A": "not assessed"}.get(s, s)


def _trend_table(name: str, rows: list, min_countries: int) -> list:
    m = re.fullmatch(r"(D\d+)_([A-Za-z0-9]+)_(AC|HC|TC)", name)
    if not m:
        raise RuntimeError(f"ECDC: unexpected sheet name {name!r}")
    table, code, sector = m.group(1), m.group(2), SECTORS[m.group(3)]
    title = re.sub(r"\s+", " ", rows[0][1].get("A", "")).strip()   # \s also folds the no-break spaces ECDC uses
    header = rows[1][1]
    if not header.get("A", "").startswith("Country"):
        raise RuntimeError(f"ECDC {name}: header row not found")
    years = {col: v for col, v in header.items() if re.fullmatch(r"\d{4}", v)}
    trend_col = next((c for c, v in header.items() if v == "Trend"), None)
    cagr_col = next((c for c, v in header.items() if v.startswith(("Compound annual", "CAGR"))), None)
    if code == "Reserve":
        atc_code, atc_group, unit = "", "WHO AWaRe 'Reserve' antibiotics", RESERVE_UNIT
    else:
        tm = re.search(r"(?:consumption|consumption \(community and hospital sectors\)) of (.+?) "
                       r"\(ATC (?:group|code) ([A-Z0-9]+)\)", title)
        if not tm or tm.group(2) != code:
            raise RuntimeError(f"ECDC {name}: cannot read ATC group from title {title!r}")
        atc_code, atc_group, unit = code, tm.group(1), DDD_UNIT
        if DDD_UNIT not in title:
            raise RuntimeError(f"ECDC {name}: unit changed in title {title!r}")
    value_cols = list(years) + [c for c in (trend_col, cagr_col) if c]
    out, countries = [], 0
    for _, cells in rows[2:]:
        label = cells.get("A", "")
        if not label or not any(cells.get(c) for c in value_cols):
            break                                  # end of the country block (footnotes follow)
        countries += 1
        for col, year in sorted(years.items(), key=lambda kv: kv[1]):
            out.append({"table": table, "table_title": title, "sector": sector, "atc_code": atc_code,
                        "atc_group": atc_group, "country": _country(label), "country_label": label, "year": year,
                        "value": _num(cells.get(col)), "unit": unit,
                        "ecdc_trend": _trend(cells.get(trend_col, "")) if trend_col else "",
                        "ecdc_cagr": _num(cells.get(cagr_col, "")) if cagr_col else ""})
    if countries < min_countries:
        raise RuntimeError(f"ECDC {name}: only {countries} country rows")
    return out


def _cross_section(name: str, rows: list, min_countries: int) -> list:
    """D17: one year, one column per substance group."""
    table = name.split("_")[0]
    title = re.sub(r"\s+", " ", rows[0][1].get("A", "")).strip()
    header = rows[1][1]
    ym = re.search(r"countries, (\d{4}),", title)
    if not ym or DDD_UNIT not in title or "hospital sector" not in title:
        raise RuntimeError(f"ECDC {name}: unexpected title {title!r}")
    cols = {c: v for c, v in header.items() if c != "A" and v}
    out, countries = [], 0
    for _, cells in rows[2:]:
        label = cells.get("A", "")
        if not label or not any(cells.get(c) for c in cols):
            break
        countries += 1
        for col, head in sorted(cols.items()):
            codes = re.findall(r"\(([A-Z]\d{2}[A-Z]{2}\d{2})\)", head)
            out.append({"table": table, "table_title": title, "sector": "Hospital", "atc_code": "+".join(codes),
                        "atc_group": re.sub(r"\s*\*", "", head), "country": _country(label), "country_label": label,
                        "year": ym.group(1), "value": _num(cells.get(col)), "unit": DDD_UNIT, "ecdc_trend": "",
                        "ecdc_cagr": ""})
    if countries < min_countries:
        raise RuntimeError(f"ECDC {name}: only {countries} country rows")
    return out


def parse(raw: bytes, min_countries: int = MIN_COUNTRIES) -> list:
    sheets = _read_xlsx(raw)
    out = []
    for name in sorted(sheets, key=lambda n: int(re.match(r"D(\d+)", n).group(1)) if re.match(r"D\d+_", n) else 999):
        if not re.match(r"D\d+_", name):
            continue
        rows = sheets[name]
        if name.startswith("D17_"):
            out.extend(_cross_section(name, rows, min_countries))
        else:
            out.extend(_trend_table(name, rows, min_countries))
    if not out:
        raise RuntimeError("ECDC: no tables found in workbook")
    return out
