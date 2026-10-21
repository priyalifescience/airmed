"""France: medicines on the public medicines database (BDPM), one row per presentation (box, CIP13) with the fields
of its medicine (specialité, CIS code), plus the ATC code where the ANSM lists the medicine as being of major
therapeutic interest (MITM).

Source: Base de données publique des médicaments (ANSM, HAS and UNCAM), download page
https://base-donnees-publique.medicaments.gouv.fr/telechargement. The BDPM publishes tab-separated TXT files
without a header (described in "Contenu et format des fichiers téléchargeables dans la BDM", v5):
  CIS_bdpm.txt          medicines marketed, or withdrawn less than two years ago (~16,000, one per CIS code)
  CIS_CIP_bdpm.txt      their presentations (~21,000 boxes: CIP7, CIP13, prices, reimbursement rate)
  CIS_MITM.txt          medicines of major therapeutic interest (MITM), the only BDPM file with an ATC code
The specialities file is updated monthly, the presentations file more often (prices); both file dates as shown on
the download page are kept on every row, because the BDPM licence asks for the source and its update date.

Design: the BDPM is a set of linked tables keyed by the CIS code. One dataset with a `table` column and the union
of all columns would be ~100 MB of JSON (mostly empty cells), so the BDPM is split into four datasets that join
on cis_code: fr_bdpm_medicines (this one), fr_bdpm_compositions (active substances), fr_bdpm_has_opinions (HAS
SMR/ASMR ratings) and fr_bdpm_availability (ANSM shortage notices). Medicines without any presentation in the
presentations file keep one row with empty presentation fields; presentations whose CIS is missing from the
specialities file (a handful) keep their row with empty medicine fields.

Values: the BDPM licence forbids altering the data or its meaning. Text is kept exactly as published (only
surrounding spaces are trimmed; a few names start with a space), including the BDPM's ";"-separated lists (routes,
holders, reimbursement rates). Only formats are converted: dates to ISO (YYYY-MM-DD) and euro amounts from the
French notation ("1,234,56" or "24,34") to numbers. The ATC code is only available for MITM medicines; for the
others, join fr_bdpm_compositions (substance names and BDPM substance codes) or fr_open_medic by cip13_code.

Holders (titulaires) are companies. The source holds no personal data.
"""

import json
import re

from ..http import fetch

KEY = "fr_bdpm_medicines"
FIELDS = ["cis_code", "medicine_name", "pharmaceutical_form", "routes", "authorisation_status",
          "authorisation_procedure", "marketing_status", "authorisation_date", "bdm_status",
          "eu_authorisation_number", "holders", "enhanced_monitoring", "atc_code", "mitm", "mitm_publication_date",
          "cip7_code", "cip13_code", "presentation", "presentation_status", "presentation_marketing_status",
          "marketing_declaration_date", "hospital_approval", "reimbursement_rate", "price_eur", "public_price_eur",
          "dispensing_fee_eur", "reimbursement_indications", "specialities_file_updated",
          "presentations_file_updated"]
BASE = "https://base-donnees-publique.medicaments.gouv.fr"
PAGE_URL = BASE + "/telechargement"
FILE_URL = BASE + "/download/file/{}"
FILES = ["CIS_bdpm.txt", "CIS_CIP_bdpm.txt", "CIS_MITM.txt"]
COLUMNS = {"CIS_bdpm.txt": 12, "CIS_CIP_bdpm.txt": 13, "CIS_COMPO_bdpm.txt": 8, "CIS_HAS_SMR_bdpm.txt": 6,
           "CIS_HAS_ASMR_bdpm.txt": 6, "HAS_LiensPageCT_bdpm.txt": 2, "CIS_CIP_Dispo_Spec.txt": 8,
           "CIS_MITM.txt": 7}
MIN_ROWS = 15000       # ~22,000 presentations and medicines without one
_DATE_RE = re.compile(r"Date de mise à jour\s*:\s*(\d{2})/(\d{2})/(\d{4})")


def file_dates(page: str) -> dict:
    """{file name: 'YYYY-MM-DD'} from the "(Date de mise à jour : 29/09/2026, ...)" next to each download link."""
    links = list(re.finditer(r'href="/download/file/([A-Za-z_]+\.txt)"', page))
    out = {}
    for i, m in enumerate(links):
        end = links[i + 1].start() if i + 1 < len(links) else len(page)
        d = _DATE_RE.search(page, m.end(), end)
        if d:
            out[m[1]] = f"{d[3]}-{d[2]}-{d[1]}"
    return out


def download(names: list) -> bytes:
    """The named BDPM files (decoded text) and their update dates, as one JSON document."""
    dates = file_dates(fetch(PAGE_URL, timeout=90).decode("utf-8", "replace"))
    missing = [n for n in names if n not in dates]
    if missing:
        raise RuntimeError(f"BDPM download page lists no update date for {missing}")
    files = {n: decode(fetch(FILE_URL.format(n), timeout=300)) for n in names}
    return json.dumps({"updated": {n: dates[n] for n in names}, "files": files}, ensure_ascii=False).encode("utf-8")


def decode(raw: bytes) -> str:
    """The BDPM files are mixed: some UTF-8, most Windows-1252 (curly apostrophes are byte 0x92)."""
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("latin-1")


def table(bundle: dict, name: str) -> list:
    """Rows of one file as lists of trimmed strings; every row must have the documented number of columns."""
    out = []
    for n, line in enumerate(bundle["files"][name].split("\n"), 1):
        line = line.rstrip("\r")
        if not line.strip():
            continue
        cells = line.split("\t")
        if len(cells) != COLUMNS[name]:
            raise RuntimeError(f"BDPM {name} line {n}: {len(cells)} columns, expected {COLUMNS[name]}")
        out.append([c.strip() for c in cells])
    return out


def iso_date(v: str) -> str:
    """'12/03/1998' or '20260909' -> '1998-03-12'; empty stays empty."""
    if not v:
        return ""
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", v)
    if m:
        return f"{m[3]}-{m[2]}-{m[1]}"
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", v)
    if m:
        return f"{m[1]}-{m[2]}-{m[3]}"
    raise RuntimeError(f"BDPM: unexpected date {v!r}")


def euro(v: str):
    """BDPM amounts: '24,34', '1,234,56' (the last comma is the decimal mark) -> float; empty -> None."""
    if not v:
        return None
    m = re.fullmatch(r"(\d{1,3}(?:,\d{3})*|\d+),(\d{2})", v)
    if not m:
        raise RuntimeError(f"BDPM: unexpected euro amount {v!r}")
    return float(m[1].replace(",", "") + "." + m[2])


def load(raw: bytes) -> dict:
    bundle = json.loads(raw)
    if not bundle.get("files"):
        raise RuntimeError("no BDPM files in the download")
    return bundle


def fetch_raw() -> bytes:
    return download(FILES)


def parse(raw: bytes, min_rows: int = MIN_ROWS) -> list:
    b = load(raw)
    upd = b["updated"]
    cis = {r[0]: r for r in table(b, "CIS_bdpm.txt")}
    mitm = {r[0]: r for r in table(b, "CIS_MITM.txt")}
    pres = {}
    for r in table(b, "CIS_CIP_bdpm.txt"):
        pres.setdefault(r[0], []).append(r)
    out = []

    def row(code, p):
        c = cis.get(code) or [""] * 12
        m = mitm.get(code)
        out.append({
            "cis_code": code,
            "medicine_name": c[1],
            "pharmaceutical_form": c[2],
            "routes": c[3],
            "authorisation_status": c[4],
            "authorisation_procedure": c[5],
            "marketing_status": c[6],
            "authorisation_date": iso_date(c[7]),
            "bdm_status": c[8],
            "eu_authorisation_number": c[9],
            "holders": c[10],
            "enhanced_monitoring": c[11],
            "atc_code": m[1] if m else "",
            "mitm": m is not None,
            "mitm_publication_date": iso_date(m[5]) if m else "",
            "cip7_code": p[1] if p else "",
            "cip13_code": p[6] if p else "",
            "presentation": p[2] if p else "",
            "presentation_status": p[3] if p else "",
            "presentation_marketing_status": p[4] if p else "",
            "marketing_declaration_date": iso_date(p[5]) if p else "",
            "hospital_approval": p[7] if p else "",
            "reimbursement_rate": p[8] if p else "",
            "price_eur": euro(p[9]) if p else None,
            "public_price_eur": euro(p[10]) if p else None,
            "dispensing_fee_eur": euro(p[11]) if p else None,
            "reimbursement_indications": p[12] if p else "",
            "specialities_file_updated": upd["CIS_bdpm.txt"],
            "presentations_file_updated": upd["CIS_CIP_bdpm.txt"],
        })

    for code in sorted(set(cis) | set(pres)):
        for p in sorted(pres.get(code, [None]), key=lambda p: p[6] if p else ""):
            row(code, p)
    if len(out) < min_rows:
        raise RuntimeError(f"BDPM medicines: only {len(out)} rows")
    return out
