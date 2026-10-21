"""Netherlands: outpatient medicine use and cost under the Health Insurance Act (Zvw) per ATC code and year, from
2012 (pharmacy) and 2017 (hospital add-on medicines): users, dispensings, DDD and reimbursement (GIPdatabank).

Source: Zorginstituut Nederland, Zorgcijfersdatabank / GIPdatabank, page "Open Data GIP"
(https://www.zorgcijfersdatabank.nl/algemeen/open-data-gip). The institute publishes, per release, a multi-year
CSV ("meerjaren", 5 years, '#'-separated) for
  Farmacie  medicines dispensed by community pharmacies and dispensing GPs (vergoeding = the basic Zvw
            reimbursement), with users, dispensings and DDD (WHO defined daily doses);
  Add-on    expensive hospital medicines billed as add-ons (vergoeding including VAT), with users only.
"The files are aggregated so that privacy is guaranteed and data can never be traced to individual persons or
health insurers" (Zorginstituut). Field definitions: /algemeen/farmacie-meerjarentabel-per-atc-code and
/algemeen/add-on-meerjarentabel-per-atc-code.

Years: every year from 2012 is taken from the newest multi-year file that contains it (e.g. 2025-2021 from
"meerjaren 2021-2025", 2020 from "2020-2024", ... 2012 from "2012-2016"), so the latest revision of each year is
kept and nothing is summed. The ATC code in each file is "ATC-code laatst bekende stand" (the ATC version of the
file's last year), so the ATC version can differ between years; atc_version_year and source_file say which file a
row comes from. Values are as published: "." (not available, e.g. no DDD for a product) becomes empty, decimal
commas in the older files become decimal points; the ratio columns are the institute's own. "users" can be
fractional in a few rows as published. The add-on file of June 2026 marks its last two years "2024*" and "2025*";
the open-data page does not explain the asterisk (most likely provisional figures), so it is kept as year_asterisk.
"""

import html
import json
import re

from ..http import fetch

KEY = "nl_gip_medicine_use"
FIELDS = ["year", "year_asterisk", "category", "atc_code", "atc_name", "reimbursement_eur", "users", "dispensings", "ddd",
          "reimbursement_per_user", "reimbursement_per_dispensing", "dispensings_per_user", "ddd_per_dispensing",
          "reimbursement_per_ddd", "ddd_per_user", "atc_version_year", "source_file"]
SITE = "https://www.zorgcijfersdatabank.nl"
PAGE_URL = SITE + "/algemeen/open-data-gip"
FIRST_YEAR = {"farmacie": 2012, "addon": 2017}
MIN_ROWS = {"farmacie": 700, "addon": 50}      # per year: ~1,000 and ~150 ATC codes
_TITLE_RE = re.compile(r"GIP\s+(Farmacie|Addon)\s+Zvw\s+meerjaren\s+(\d{4})-(\d{4})_(\d{8})", re.I)
# source column -> our field (both spellings seen in the files)
COLS = {"jaar": "year", "atclaatst": "atc_code", "atclaatst_naam_tekst": "atc_name", "atclaatst_naam": "atc_name",
        "vergoeding": "reimbursement_eur", "gebruikers": "users", "uitgiftes": "dispensings", "ddd": "ddd",
        "vergoeding_per_gebruiker": "reimbursement_per_user", "vergoeding_per_uitgifte": "reimbursement_per_dispensing",
        "uitgifte_per_gebruiker": "dispensings_per_user", "uitgiftes_per_gebruiker": "dispensings_per_user",
        "ddd_per_uitgifte": "ddd_per_dispensing", "vergoeding_per_ddd": "reimbursement_per_ddd",
        "ddd_per_gebruiker": "ddd_per_user"}
NUMERIC = FIELDS[5:15]
_YEAR_RE = re.compile(r"(\d{4})(\*?)")


def files_listed(page: str) -> list:
    """[(category, first year, last year, title, url)] for every multi-year file on the Open Data GIP page."""
    out = []
    for m in re.finditer(r'<a[^>]+href="(/services/file/get\?[^"]+)"[^>]*>\s*<h4[^>]*>(.*?)</h4>', page, re.S):
        title = html.unescape(re.sub(r"<[^>]+>", "", m[2])).strip()
        t = _TITLE_RE.fullmatch(title)
        if t:
            out.append((t[1].lower(), int(t[2]), int(t[3]), title, SITE + html.unescape(m[1])))
    return out


def plan(files: list) -> dict:
    """{(category, year): (title, url, last year of the file)}: each year from the newest file that holds it."""
    out = {}
    for cat, y0, y1, title, url in sorted(files, key=lambda f: (f[2], f[3]), reverse=True):
        for y in range(max(y0, FIRST_YEAR[cat]), y1 + 1):
            out.setdefault((cat, y), (title, url, y1))
    return out


def fetch_raw() -> bytes:
    p = plan(files_listed(fetch(PAGE_URL, timeout=90).decode("utf-8")))
    if not p:
        raise RuntimeError("Open Data GIP page lists no multi-year files")
    texts = {}
    for title, url, _ in set(p.values()):
        texts[title] = fetch(url, timeout=180).decode("utf-8-sig")
    return json.dumps({"plan": [[c, y, t, v] for (c, y), (t, _, v) in sorted(p.items())], "files": texts},
                      ensure_ascii=False).encode("utf-8")


def value(v: str):
    v = v.strip()
    if v in (".", ""):
        return None
    if "," in v and "." in v:
        raise RuntimeError(f"GIP: ambiguous number {v!r}")
    v = v.replace(",", ".")
    if not re.fullmatch(r"-?\d+(\.\d+)?", v):
        raise RuntimeError(f"GIP: unexpected number {v!r}")
    return float(v) if "." in v else int(v)


def _year(v: str) -> tuple:
    m = _YEAR_RE.fullmatch(v)
    if not m:
        raise RuntimeError(f"GIP: unexpected year {v!r}")
    return m[1], m[2]


def read_file(text: str) -> list:
    lines = [ln.rstrip("\r") for ln in text.split("\n") if ln.strip()]
    hdr = [h.strip().lower() for h in lines[0].split("#")]
    unknown = [h for h in hdr if h not in COLS]
    if unknown or "jaar" not in hdr or "atclaatst" not in hdr:
        raise RuntimeError(f"GIP: unexpected columns {hdr}")
    out = []
    for ln in lines[1:]:
        c = [x.strip() for x in ln.split("#")]
        if len(c) != len(hdr):
            raise RuntimeError(f"GIP: bad line {ln!r}")
        out.append({COLS[h]: v for h, v in zip(hdr, c)})
    return out


def parse(raw: bytes, min_rows: dict = None) -> list:
    min_rows = MIN_ROWS if min_rows is None else min_rows
    data = json.loads(raw)
    parsed = {t: read_file(x) for t, x in data["files"].items()}
    out = []
    for cat, year, title, version in data["plan"]:
        rows = [r for r in parsed[title] if int(_year(r["year"])[0]) == year]
        if len(rows) < min_rows[cat]:
            raise RuntimeError(f"GIP {cat} {year}: only {len(rows)} rows in {title}")
        codes = [r["atc_code"] for r in rows]
        if len(set(codes)) != len(codes):
            raise RuntimeError(f"GIP {cat} {year}: duplicate ATC codes in {title}")
        for r in sorted(rows, key=lambda r: r["atc_code"]):
            rec = {"year": year, "year_asterisk": _year(r["year"])[1] == "*", "category": cat, "atc_code": r["atc_code"], "atc_name": r.get("atc_name", "")}
            for f in NUMERIC:
                rec[f] = value(r[f]) if f in r else None
            rec["atc_version_year"] = version
            rec["source_file"] = title
            out.append(rec)
    if not out:
        raise RuntimeError("no GIP rows")
    return out
