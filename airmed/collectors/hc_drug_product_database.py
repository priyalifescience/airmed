"""Health Canada Drug Product Database (DPD): every human drug product with a Drug Identification Number (DIN),
from the official monthly data extract (four zips: marketed, approved, dormant and cancelled products).

One row per DPD product (DRUG_CODE), joined from the drug, company, active-ingredient, status, therapeutic-class
(ATC), schedule, route and form tables. Only the classes Human and Radiopharmaceutical are kept; Veterinary and
Disinfectant products are left out. The company is the DIN owner (an organisation); its street address is never
copied. Cancelled products are kept in full (the whole register is ~20 MB as CSV, well under the size rule), so
`status` tells marketed, approved-not-yet-marketed, dormant and cancelled products apart.
"""

import csv
import datetime as dt
import io
import zipfile

from ..http import fetch

KEY = "hc_drug_product_database"
FIELDS = ["din", "drug_code", "brand_name", "descriptor", "company", "class", "ingredients", "number_of_ingredients",
          "atc_codes", "atc_names", "schedules", "status", "status_date", "first_marketed_date", "routes",
          "dosage_forms", "biosimilar", "pediatric", "product_categorization", "ai_group_no", "last_update_date"]
BASE = "https://www.canada.ca/content/dam/hc-sc/documents/services/drug-product-database/"
EXTRACTS = {"allfiles.zip": "", "allfiles_ap.zip": "_ap", "allfiles_dr.zip": "_dr", "allfiles_ia.zip": "_ia"}
KEEP_CLASSES = ("Human", "Radiopharmaceutical")
MIN_RECORDS = 40000

# column counts of the tables used (README "Read file for the Drug Product Database data extract")
WIDTH = {"drug": 14, "comp": 18, "ingred": 15, "status": 7, "ther": 4, "route": 4, "form": 4, "schedule": 3, "biosimilar": 4}
TABLES = tuple(WIDTH)


def fetch_raw() -> bytes:
    """The four official extract zips, stored unchanged inside one zip (only the tables used are kept)."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, suffix in EXTRACTS.items():
            src = zipfile.ZipFile(io.BytesIO(fetch(BASE + name, timeout=300)))
            for t in TABLES:
                member = f"{t}{suffix}.txt"
                if member not in src.namelist():
                    raise RuntimeError(f"{name} has no {member} (holds {src.namelist()})")
                bundle.writestr(f"{name}/{member}", src.read(member))
    return out.getvalue()


def _date(v: str) -> str:
    """'22-MAR-2025' -> '2025-03-22'."""
    v = (v or "").strip()
    if not v:
        return ""
    try:
        return dt.datetime.strptime(v, "%d-%b-%Y").date().isoformat()
    except ValueError:
        return v


def _rows(bundle: zipfile.ZipFile, extract: str, table: str) -> list:
    member = f"{extract}/{table}{EXTRACTS[extract]}.txt"
    try:
        data = bundle.read(member)
    except KeyError:
        raise RuntimeError(f"DPD bundle has no {member}")
    rows = []
    for n, r in enumerate(csv.reader(io.StringIO(data.decode("utf-8-sig"))), start=1):
        if not r:
            continue
        if len(r) != WIDTH[table]:
            raise RuntimeError(f"{member} line {n}: {len(r)} fields, expected {WIDTH[table]}")
        rows.append([c.strip() for c in r])
    return rows


def _num(v: str) -> str:
    """'10.0' -> '10', '0.50' -> '0.5'; other text unchanged."""
    try:
        f = float(v)
    except ValueError:
        return v
    return f"{f:g}" if abs(f) < 1e15 else v


def _ingredient(r: list) -> str:
    # DRUG_CODE, ACTIVE_INGREDIENT_CODE, INGREDIENT, INGREDIENT_SUPPLIED_IND, STRENGTH, STRENGTH_UNIT, STRENGTH_TYPE,
    # DOSAGE_VALUE, BASE, DOSAGE_UNIT, NOTES, ...
    s = " ".join(p for p in (_num(r[4]) if r[4] else "", r[5]) if p)
    per = " ".join(p for p in (_num(r[7]) if r[7] else "", r[9]) if p)
    if s and per:
        s = f"{s} / {per}"
    return f"{r[2]} {s}".strip()


def _add(d: dict, code: str, value: str) -> None:
    if value and value not in d.setdefault(code, []):
        d[code].append(value)


def parse(raw: bytes, min_records: int = MIN_RECORDS) -> list:
    bundle = zipfile.ZipFile(io.BytesIO(raw))
    out = []
    seen = set()
    for extract in EXTRACTS:
        drugs = _rows(bundle, extract, "drug")
        codes = {r[0] for r in drugs}
        if len(codes) != len(drugs):
            raise RuntimeError(f"{extract}: duplicate DRUG_CODE in drug table")

        company = {}
        for r in _rows(bundle, extract, "comp"):
            if r[0] in company:
                raise RuntimeError(f"{extract}: product {r[0]} has more than one company row")
            company[r[0]] = r[3]
        status, first_marketed = {}, {}
        for r in _rows(bundle, extract, "status"):
            if r[1] == "Y":
                if r[0] in status:
                    raise RuntimeError(f"{extract}: product {r[0]} has more than one current status")
                status[r[0]] = (r[2], _date(r[3]))
            if r[2] == "MARKETED":
                d = _date(r[3])
                if d and (r[0] not in first_marketed or d < first_marketed[r[0]]):
                    first_marketed[r[0]] = d
        ingred, atc_c, atc_n, sched, route, form, bios = {}, {}, {}, {}, {}, {}, set()
        for r in _rows(bundle, extract, "ingred"):
            _add(ingred, r[0], _ingredient(r))
        for r in _rows(bundle, extract, "ther"):
            # the table repeats some (code, ATC) lines verbatim; atc_codes[i] is named by atc_names[i]
            if r[1] and r[1] not in atc_c.get(r[0], []):
                atc_c.setdefault(r[0], []).append(r[1])
                atc_n.setdefault(r[0], []).append(r[2])
        for r in _rows(bundle, extract, "schedule"):
            _add(sched, r[0], r[1])
        for r in _rows(bundle, extract, "route"):
            _add(route, r[0], r[2])
        for r in _rows(bundle, extract, "form"):
            _add(form, r[0], r[2])
        for r in _rows(bundle, extract, "biosimilar"):
            if r[1].lower() == "biosimilar":
                bios.add(r[0])

        for r in drugs:
            # DRUG_CODE, PRODUCT_CATEGORIZATION, CLASS, DIN, BRAND_NAME, DESCRIPTOR, PEDIATRIC_FLAG, ACCESSION_NUMBER,
            # NUMBER_OF_AIS, LAST_UPDATE_DATE, AI_GROUP_NO, CLASS_F, BRAND_NAME_F, DESCRIPTOR_F
            code = r[0]
            if code not in status or code not in company:
                raise RuntimeError(f"{extract}: product {code} has no current status or no company row")
            if r[2] not in KEEP_CLASSES:
                continue
            if code in seen:
                raise RuntimeError(f"product {code} appears in more than one extract")
            seen.add(code)
            ings = sorted(ingred.get(code, []))
            out.append({
                "din": r[3], "drug_code": int(code), "brand_name": r[4], "descriptor": r[5], "company": company[code],
                "class": r[2], "ingredients": ings, "number_of_ingredients": int(r[8]) if r[8].isdigit() else len(ings),
                "atc_codes": atc_c.get(code, []), "atc_names": atc_n.get(code, []), "schedules": sorted(sched.get(code, [])),
                "status": status[code][0], "status_date": status[code][1],
                "first_marketed_date": first_marketed.get(code, ""), "routes": sorted(route.get(code, [])),
                "dosage_forms": sorted(form.get(code, [])), "biosimilar": "yes" if code in bios else "",
                "pediatric": "yes" if r[6] == "Y" else "", "product_categorization": r[1], "ai_group_no": r[10],
                "last_update_date": _date(r[9]),
            })
    if len(out) < min_records:
        raise RuntimeError(f"only {len(out)} DPD human products; refusing a partial dataset")
    out.sort(key=lambda x: (x["din"], x["drug_code"]))
    return out
