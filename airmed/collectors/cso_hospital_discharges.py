"""Department of Health / HSE (Ireland): hospital discharge summary statistics (HIPE), from CSO PxStat.

Source: the Hospital In-Patient Enquiry (HIPE) aggregate tables that the Department of Health (DHA tables,
"Health Statistics" series, 2017 on) and the HSE Healthcare Pricing Office (HIPE tables, 10 years) publish
through the CSO PxStat database and data.gov.ie. These are published summary tables only: counts, rates, bed days
and lengths of stay by sex, age group, area of residence, principal diagnosis (ISHMT shortlist, with ICD-10
ranges in the labels) and principal procedure. Patient-level HIPE data is not open and is never used.

One row per table, statistic, year and combination of breakdown categories; each breakdown has its own code and
label columns (empty when the table has no such breakdown). Codes and labels are CSO's.

Window (the complete DHA74-DHA127 family is about 5.3 million published cells, far too large to republish):
- tables kept: HIPE01-HIPE06 (national totals by admission type, sex/age, inpatient/daycase, length of stay, bed
  days); DHA74 and DHA76 (all discharges, bed days and length of stay by age, sex and area); DHA77, DHA81, DHA83,
  DHA85 (detailed principal diagnosis: discharges and rate, bed days, average length of stay, age-standardised
  rate); DHA89 and DHA91 (high-level principal diagnosis, i.e. ISHMT chapters, by county: discharges, bed days);
  DHA98, DHA102, DHA104, DHA106 (principal procedure, the same four measures); DHA110 (selected principal
  procedures by county);
- left out: the "inpatient and daycase" duplicates of these tables, the "with a procedure recorded" and
  "all-listed procedures" series, the age-standardised morbidity ratio tables, and the area tables for detailed
  diagnoses/procedures (their national figures equal the "All ages" rows of the age-group tables kept here);
- within the DHA tables kept, breakdowns are one-way: a row is kept when at most one of sex, age group and area
  is broken down (the others at their total: "Both sexes", "All ages", "Ireland" or "Ireland plus
  non-residents"); diagnosis and procedure detail is always kept. Cells CSO publishes as empty are left out;
- statistics: in the diagnosis and procedure tables only the main measure is kept (discharges, bed days,
  average length of stay, standardised discharge rate); the crude rate per 1,000, the median length of stay
  and the confidence limits of the standardised rate are left out (see TABLES).
"""

import itertools
import json

from ..http import fetch

KEY = "cso_hospital_discharges"
FIELDS = ["table", "table_title", "statistic_code", "statistic", "unit", "year", "sex_code", "sex",
          "age_group_code", "age_group", "area_code", "area", "diagnosis_code", "diagnosis",
          "procedure_code", "procedure", "case_type_code", "case_type", "value", "status"]
URL = "https://ws.cso.ie/public/api.restful/PxStat.Data.Cube_API.ReadDataset/{}/JSON-stat/2.0/en"
# table -> statistics kept (code suffixes), or None for all
TABLES = {
    "HIPE01": None, "HIPE02": None, "HIPE03": None, "HIPE04": None, "HIPE05": None, "HIPE06": None,
    "DHA74": None, "DHA76": None,
    "DHA77": ["C01"],   # discharges (crude rate per 1,000 left out; DHA85 has the age-standardised rate)
    "DHA81": None,      # inpatient bed days
    "DHA83": ["C01"],   # average length of stay (median left out)
    "DHA85": ["C01"],   # standardised discharge rate per 100,000 (confidence limits left out)
    "DHA89": ["C01"], "DHA91": None,
    "DHA98": ["C01"], "DHA102": None, "DHA104": ["C01"], "DHA106": ["C01"],
    "DHA110": ["C01"],
}
CONFIDENTIAL = -99999999
# CSO dimension id -> column prefix
DIMS = {
    "C02199V02655": "sex",
    "C02076V02508": "age_group",      # DHA age groups
    "C02076V03371": "age_group",      # HIPE02 five-year age groups
    "C04369V05150": "area",           # county of residence
    "C02855V03433": "diagnosis",      # ISHMT principal diagnosis (detailed or high level)
    "C02857V03435": "procedure",      # principal procedure (all or selected)
    "C04621V05406": "case_type",      # HIPE01 admission type
    "C04054V04616": "case_type",      # HIPE03/05/06 inpatient / daycase
    "C04634V05419": "case_type",      # HIPE04 discharge type
}
COLUMNS = ["sex", "age_group", "area", "diagnosis", "procedure", "case_type"]
TOTALS = {"sex": {"-"}, "age_group": {"-"}, "area": {"IE0", "99"}}   # Both sexes, All ages, Ireland (+ non-residents)


def fetch_raw() -> bytes:
    """All tables as one JSON object {table code: JSON-stat 2.0 cube}."""
    return json.dumps({t: json.loads(fetch(URL.format(t), timeout=180)) for t in TABLES}).encode("utf-8")


def _codes(dim):
    idx = dim["category"]["index"]
    return list(idx) if isinstance(idx, list) else [k for k, _ in sorted(idx.items(), key=lambda kv: kv[1])]


def _cells(table: str, r: dict):
    """Yield ({dimension id: category code}, value) for every cell of a JSON-stat 2.0 cube (row-major order)."""
    ids, size, values = r["id"], r["size"], r["value"]
    n = 1
    for s in size:
        n *= s
    if isinstance(values, dict):  # JSON-stat may send a sparse object
        values = [values.get(str(i)) for i in range(n)]
    if len(values) != n:
        raise RuntimeError(f"CSO {table}: cube has {len(values)} values, expected {n}")
    codes = [_codes(r["dimension"][d]) for d in ids]
    if [len(c) for c in codes] != list(size):
        raise RuntimeError(f"CSO {table}: dimension sizes do not match the category lists")
    for combo, v in zip(itertools.product(*codes), values):
        yield dict(zip(ids, combo)), v


def _cube_rows(table: str, r: dict) -> list:
    ids = r["id"]
    if [d for d in ids if d.startswith("TLIST(")] != ["TLIST(A1)"] or "STATISTIC" not in ids:
        raise RuntimeError(f"CSO {table}: unexpected dimensions {ids}")
    unknown = [d for d in ids if d not in DIMS and d not in ("STATISTIC", "TLIST(A1)")]
    if unknown:
        raise RuntimeError(f"CSO {table}: unknown breakdowns {unknown}")
    labels = {d: r["dimension"][d]["category"].get("label", {}) for d in ids}
    units = r["dimension"]["STATISTIC"]["category"].get("unit", {})
    title = r.get("label", "").strip()
    one_way = table.startswith("DHA")
    stats = set(_codes(r["dimension"]["STATISTIC"]))
    keep = stats if TABLES[table] is None else {table + s for s in TABLES[table]}
    if keep - stats:
        raise RuntimeError(f"CSO {table}: statistics {sorted(keep - stats)} not found")
    out = []
    for c, v in _cells(table, r):
        if v is None or c["STATISTIC"] not in keep:
            continue
        row = {col + s: "" for col in COLUMNS for s in ("_code", "")}
        for d, col in DIMS.items():
            if d in c:
                row[col + "_code"], row[col] = c[d], labels[d].get(c[d], c[d]).strip()
        if one_way and sum(1 for col in TOTALS if row[col + "_code"] and row[col + "_code"] not in TOTALS[col]) > 1:
            continue
        status = ""
        if v == CONFIDENTIAL:
            v, status = "", "confidential"
        sc = c["STATISTIC"]
        row.update({"table": table, "table_title": title, "statistic_code": sc,
                    "statistic": labels["STATISTIC"].get(sc, sc).strip(), "unit": units.get(sc, {}).get("label", ""),
                    "year": c["TLIST(A1)"], "value": v, "status": status})
        out.append({k: row[k] for k in FIELDS})
    return out


def parse(raw: bytes) -> list:
    cubes = json.loads(raw)
    missing = [t for t in TABLES if t not in cubes]
    if missing:
        raise RuntimeError(f"CSO tables missing from reply: {missing}")
    out = []
    for t in TABLES:
        out.extend(_cube_rows(t, cubes[t]))
    return out
