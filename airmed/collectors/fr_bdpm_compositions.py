"""France: active substances of every medicine on the public medicines database (BDPM), one row per medicine
(CIS code), pharmaceutical element and substance, as published in CIS_COMPO_bdpm.txt.

Source: Base de données publique des médicaments (ANSM, HAS and UNCAM),
https://base-donnees-publique.medicaments.gouv.fr/telechargement. The composition file gives "the qualitative and
quantitative composition in active substances and therapeutic fractions (as in the Summary of Product
Characteristics)" (format description v5): pharmaceutical element (e.g. "comprimé"), BDPM substance code,
substance name, dosage, dosage reference (e.g. "un comprimé"), component nature (SA = active substance,
ST = therapeutic fraction) and the number linking an active substance to its therapeutic fraction.

This is the substance table of the split BDPM (see fr_bdpm_medicines for the design): join on cis_code. The BDPM
gives no ATC code here; substance names are kept exactly as published (French, upper case, e.g. "ANASTROZOLE"),
with the BDPM's own substance code. Text is kept as published (surrounding spaces trimmed); the medicine name is
copied from the specialities file for convenience. The file's update date from the download page is on every row,
as the BDPM licence asks.
"""

from . import fr_bdpm_medicines as bdpm

KEY = "fr_bdpm_compositions"
FIELDS = ["cis_code", "medicine_name", "pharmaceutical_element", "substance_code", "substance", "dosage",
          "dosage_reference", "component_nature", "substance_fraction_link", "source_updated"]
FILES = ["CIS_bdpm.txt", "CIS_COMPO_bdpm.txt"]
MIN_ROWS = 20000       # ~32,000 rows


def fetch_raw() -> bytes:
    return bdpm.download(FILES)


def parse(raw: bytes, min_rows: int = MIN_ROWS) -> list:
    b = bdpm.load(raw)
    names = {r[0]: r[1] for r in bdpm.table(b, "CIS_bdpm.txt")}
    upd = b["updated"]["CIS_COMPO_bdpm.txt"]
    out = [{
        "cis_code": r[0],
        "medicine_name": names.get(r[0], ""),
        "pharmaceutical_element": r[1],
        "substance_code": r[2],
        "substance": r[3],
        "dosage": r[4],
        "dosage_reference": r[5],
        "component_nature": r[6],
        "substance_fraction_link": r[7],
        "source_updated": upd,
    } for r in bdpm.table(b, "CIS_COMPO_bdpm.txt")]
    if len(out) < min_rows:
        raise RuntimeError(f"BDPM compositions: only {len(out)} rows")
    return out
