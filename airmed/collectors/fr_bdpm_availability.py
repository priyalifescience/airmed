"""France: ANSM medicine availability notices (stock-outs, supply tensions, withdrawals, returns to supply), as
published in the public medicines database (BDPM).

Source: Base de données publique des médicaments (ANSM, HAS and UNCAM),
https://base-donnees-publique.medicaments.gouv.fr/telechargement, file CIS_CIP_Dispo_Spec.txt: "the medicines for
which the ANSM has published information on its website under 'Disponibilité des produits de santé'" (format
description v5). Columns: CIS code, CIP13 code (empty when all marketed presentations are concerned), status code
(1 Rupture de stock, 2 Tension d'approvisionnement, 3 Arrêt de commercialisation, 4 Remise à disposition), status
label, start date (for notices before 06/10/2023 this is the update date, not the start), date updated on the ANSM
site, date of return to supply, and the link to the ANSM page. One row per published line (~700: the current
notices, not a history). The medicine name and, for MITM medicines, the ATC code are joined from the BDPM
specialities and MITM files (see fr_bdpm_medicines for the split design).

Values are as published; dates are converted to ISO. The file's update date from the download page is on every
row, as the BDPM licence asks. Comparable with the HPRA shortages list.
"""

from . import fr_bdpm_medicines as bdpm

KEY = "fr_bdpm_availability"
FIELDS = ["cis_code", "cip13_code", "medicine_name", "atc_code", "status_code", "status", "start_date",
          "ansm_updated_date", "return_date", "ansm_url", "source_updated"]
FILES = ["CIS_bdpm.txt", "CIS_MITM.txt", "CIS_CIP_Dispo_Spec.txt"]
MIN_ROWS = 200         # ~700 notices


def fetch_raw() -> bytes:
    return bdpm.download(FILES)


def parse(raw: bytes, min_rows: int = MIN_ROWS) -> list:
    b = bdpm.load(raw)
    names = {r[0]: r[1] for r in bdpm.table(b, "CIS_bdpm.txt")}
    atc = {r[0]: r[1] for r in bdpm.table(b, "CIS_MITM.txt")}
    upd = b["updated"]["CIS_CIP_Dispo_Spec.txt"]
    out = []
    for r in bdpm.table(b, "CIS_CIP_Dispo_Spec.txt"):
        if r[2] not in ("1", "2", "3", "4"):
            raise RuntimeError(f"BDPM availability: unknown status code {r[2]!r}")
        out.append({
            "cis_code": r[0],
            "cip13_code": r[1],
            "medicine_name": names.get(r[0], ""),
            "atc_code": atc.get(r[0], ""),
            "status_code": int(r[2]),
            "status": r[3],
            "start_date": bdpm.iso_date(r[4]),
            "ansm_updated_date": bdpm.iso_date(r[5]),
            "return_date": bdpm.iso_date(r[6]),
            "ansm_url": r[7],
            "source_updated": upd,
        })
    if len(out) < min_rows:
        raise RuntimeError(f"BDPM availability: only {len(out)} rows")
    return out
