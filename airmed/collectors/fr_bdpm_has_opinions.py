"""France: HAS Transparency Committee opinions on medicines, actual benefit (SMR) and improvement in actual benefit
(ASMR) ratings since 2002, as published in the public medicines database (BDPM).

Source: Base de données publique des médicaments (ANSM, HAS and UNCAM),
https://base-donnees-publique.medicaments.gouv.fr/telechargement:
  CIS_HAS_SMR_bdpm.txt      SMR opinions: CIS code, HAS file code, reason for the assessment, opinion date,
                            SMR value (e.g. Important, Modéré, Faible, Insuffisant), SMR wording
  CIS_HAS_ASMR_bdpm.txt     ASMR opinions: same columns, ASMR value (I to V, or "Commentaires sans chiffrage...")
  HAS_LiensPageCT_bdpm.txt  link from each HAS file code to the opinion page on has-sante.fr
One row per opinion line, with `assessment` = "SMR" or "ASMR"; the HAS link is joined by the HAS file code. The
same opinion applies to every CIS it lists, so one HAS file code appears on several rows. This is the HTA table of
the split BDPM (see fr_bdpm_medicines): join on cis_code. Comparable with the Irish NCPE assessments.

Values: the SMR/ASMR wording is kept exactly as published (only surrounding spaces trimmed; the BDPM ends many
SMR texts with " ;"); opinion dates are converted to ISO. The update date of the SMR or ASMR file from the
download page is on every row, as the BDPM licence asks.
"""

from . import fr_bdpm_medicines as bdpm

KEY = "fr_bdpm_has_opinions"
FIELDS = ["assessment", "cis_code", "medicine_name", "has_file_code", "evaluation_reason", "opinion_date",
          "rating", "rating_text", "has_opinion_url", "source_updated"]
FILES = ["CIS_bdpm.txt", "CIS_HAS_SMR_bdpm.txt", "CIS_HAS_ASMR_bdpm.txt", "HAS_LiensPageCT_bdpm.txt"]
MIN_ROWS = 15000       # ~15,500 SMR + ~10,100 ASMR lines


def fetch_raw() -> bytes:
    return bdpm.download(FILES)


def parse(raw: bytes, min_rows: int = MIN_ROWS) -> list:
    b = bdpm.load(raw)
    names = {r[0]: r[1] for r in bdpm.table(b, "CIS_bdpm.txt")}
    links = {r[0]: r[1] for r in bdpm.table(b, "HAS_LiensPageCT_bdpm.txt")}
    out = []
    for kind, name in (("SMR", "CIS_HAS_SMR_bdpm.txt"), ("ASMR", "CIS_HAS_ASMR_bdpm.txt")):
        upd = b["updated"][name]
        for r in bdpm.table(b, name):
            out.append({
                "assessment": kind,
                "cis_code": r[0],
                "medicine_name": names.get(r[0], ""),
                "has_file_code": r[1],
                "evaluation_reason": r[2],
                "opinion_date": bdpm.iso_date(r[3]),
                "rating": r[4],
                "rating_text": r[5],
                "has_opinion_url": links.get(r[1], ""),
                "source_updated": upd,
            })
    if len(out) < min_rows:
        raise RuntimeError(f"BDPM HAS opinions: only {len(out)} rows")
    return out
