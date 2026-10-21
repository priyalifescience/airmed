"""France: reimbursed medicines dispensed by community pharmacies, national totals per year by ATC level 5 and by
presentation (CIP13), latest 5 years (Open Medic, Assurance Maladie).

Source: Caisse nationale de l'Assurance Maladie (CNAM), "Open Medic : base complète sur les dépenses de
médicaments interrégimes" on data.gouv.fr
(https://www.data.gouv.fr/fr/datasets/open-medic-base-complete-sur-les-depenses-de-medicaments-interregimes/), data
from the SNDS, all insurance schemes, medicines dispensed in community pharmacies ("pharmacie de ville"), 2014
onwards. Besides the full yearly base (~100 MB-1 GB, by age, sex, region and prescriber specialty) the CNAM
publishes "bases complémentaires" prefixed NB_ that add the number of people who received the medicine
(consommants) at each ATC level, with the national file per level having no breakdown at all.

Size choice: the national NB files are already national totals (ATC5: ~1,200 rows a year; CIP13: ~12,500 rows a
year), so nothing is summed here: the files NB_<year>_atc5.CSV.gz and NB_<year>_cip13.CSV.gz are kept as
published for the latest 5 years, one row per year x level x code (~70,000 rows, ~10 MB). The ATC5 rows join with
other countries' ATC data; the CIP13 rows join with fr_bdpm_medicines.cip13_code. Some ATC5-level rows carry a
shorter ATC code (e.g. A02AH, B05X) where the CNAM classes medicines only to that level; codes are kept as
published.

Values: nbc = number of people with at least one dispensing in the year (not additive across codes: one person can
receive several medicines), REM = amount reimbursed, BSE = reimbursement base (both in euro; per the CNAM they
exclude the per-pack dispensing fees paid to pharmacists since 1 January 2015), BOITES = boxes dispensed. French
number notation ("5.183,28") is converted to numbers; labels are kept as published (upper case French). The ATC5
and CIP13 totals of a year are checked against each other (boxes must agree within 0.5%).

The CNAM download links (download2.php?Dir_Rep=<year>_ATC5) return a page whose file links carry a session
token, so each page is read first. No personal data: national aggregates only.
"""

import gzip
import json
import re

from ..http import fetch, fetch_json

KEY = "fr_open_medic"
FIELDS = ["year", "level", "code", "label", "consumers", "reimbursed_eur", "reimbursement_base_eur", "boxes"]
DATASET_API = ("https://www.data.gouv.fr/api/1/datasets/"
               "open-medic-base-complete-sur-les-depenses-de-medicaments-interregimes/")
SITE = "https://open-data-assurance-maladie.ameli.fr/medicaments/"
PAGE_URL = SITE + "download2.php?Dir_Rep={year}_{level}"
LEVELS = ["ATC5", "CIP13"]
YEARS_KEPT = 5
MIN_ROWS = {"ATC5": 800, "CIP13": 8000}
HEADER = {"ATC5": ["ATC5", "l_atc5", "nbc", "REM", "BSE", "BOITES"],
          "CIP13": ["CIP13", "l_cip13", "nbc", "REM", "BSE", "BOITES"]}


def years_available() -> list:
    """Years with both an ATC5 and a CIP13 resource on data.gouv.fr, newest first."""
    j = fetch_json(DATASET_API, timeout=90)
    seen = {}
    for r in j.get("resources", []):
        m = re.fullmatch(r"\s*(\d{4})\s+(ATC5|CIP13)\s*", str(r.get("title") or ""))
        if m:
            seen.setdefault(int(m[1]), set()).add(m[2])
    return sorted((y for y, lv in seen.items() if lv == set(LEVELS)), reverse=True)


def national_file(year: int, level: str) -> str:
    """Text of NB_<year>_<level>.CSV.gz (the national file, no breakdown)."""
    page = fetch(PAGE_URL.format(year=year, level=level), timeout=90).decode("latin-1")
    want = f"NB_{year}_{level.lower()}.CSV.gz"
    links = [h.replace("&amp;", "&") for h in re.findall(r'href="\./(download_file\.php\?[^"]+)"', page)
             if h.lower().endswith(want.lower())]
    if len(links) != 1:
        raise RuntimeError(f"Open Medic {year} {level}: {len(links)} links to {want}")
    raw = gzip.decompress(fetch(SITE + links[0], timeout=300))
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252")


def fetch_raw(years_kept: int = YEARS_KEPT) -> bytes:
    years = years_available()[:years_kept]
    if len(years) < years_kept:
        raise RuntimeError(f"Open Medic: only {len(years)} years listed")
    return json.dumps({"years": {str(y): {lv: national_file(y, lv) for lv in LEVELS} for y in years}},
                      ensure_ascii=False).encode("utf-8")


def number(v: str):
    """'5.183,28' -> 5183.28, '11733' -> 11733."""
    v = v.strip()
    if not re.fullmatch(r"-?\d{1,3}(\.\d{3})*(,\d+)?|-?\d+(,\d+)?", v):
        raise RuntimeError(f"Open Medic: unexpected number {v!r}")
    v = v.replace(".", "").replace(",", ".")
    return float(v) if "." in v else int(v)


def rows_of(text: str, level: str) -> list:
    lines = [ln.rstrip("\r") for ln in text.split("\n") if ln.strip()]
    if not lines or [h.strip().lower() for h in lines[0].split(";")] != [h.lower() for h in HEADER[level]]:
        raise RuntimeError(f"Open Medic {level}: unexpected header {lines[:1]}")
    out = []
    for ln in lines[1:]:
        c = ln.split(";")
        if len(c) != 6:
            raise RuntimeError(f"Open Medic {level}: bad line {ln!r}")
        out.append([c[0].strip(), c[1].strip()] + [number(x) for x in c[2:]])
    return out


def parse(raw: bytes, min_rows: dict = None) -> list:
    min_rows = MIN_ROWS if min_rows is None else min_rows
    years = json.loads(raw).get("years", {})
    if not years:
        raise RuntimeError("no Open Medic years in the download")
    keys = sorted(years, key=int)
    if [int(k) for k in keys] != list(range(int(keys[0]), int(keys[-1]) + 1)):
        raise RuntimeError(f"Open Medic years are not contiguous: {keys}")
    out = []
    for y in keys:
        boxes = {}
        for level in LEVELS:
            rows = rows_of(years[y][level], level)
            if len(rows) < min_rows[level]:
                raise RuntimeError(f"Open Medic {y} {level}: only {len(rows)} rows")
            boxes[level] = sum(r[5] for r in rows)
            for code, label, nbc, rem, bse, boites in rows:
                out.append({"year": int(y), "level": level, "code": code, "label": label, "consumers": nbc,
                            "reimbursed_eur": rem, "reimbursement_base_eur": bse, "boxes": boites})
        if abs(boxes["ATC5"] - boxes["CIP13"]) > 0.005 * max(boxes.values()):
            raise RuntimeError(f"Open Medic {y}: ATC5 boxes {boxes['ATC5']} vs CIP13 boxes {boxes['CIP13']}")
    return out
