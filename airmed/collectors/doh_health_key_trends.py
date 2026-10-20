"""Department of Health (Ireland): "Health in Ireland: Key Trends" tables (KTA series), in tidy long format.

The Department publishes the tables behind its annual "Health in Ireland: Key Trends" report through the CSO
PxStat database; data.gov.ie lists each one (e.g. kta38-prescription-items-dispensed-under-the-general-medical-
services-gms-scheme) under CC BY 4.0 with the PxStat API as the download. About 38 tables exist; only those about
medicines, prescribing, health spending, eligibility schemes and the hospital workforce are kept:

- KTA08 insured persons covered by private health insurance, by age group;
- KTA09 whole-time equivalents of consultant and non-consultant hospital doctors;
- KTA13 hospital doctors employed in the public health service (WTE), by consultant specialty / grade;
- KTA14 public health expenditure (Euro million); KTA15 HSE non-capital net expenditure by heading;
  KTA16 capital public health expenditure by programme;
- KTA30 public acute hospital summary statistics;
- KTA36 number and percentage of the population with a medical card, by age group;
- KTA37 Primary Care Reimbursement Service schemes (medical card, GP visit card, Drug Payment Scheme, Long Term
  Illness, dental and ophthalmic schemes);
- KTA38 prescription items dispensed under the General Medical Services (GMS) scheme: items, total cost,
  average cost per item.

Left out (not about medicines, spending or workforce): blood donations, ED trolleys and waiting times, patient
experience, transplants, long-stay care, addiction treatment, hospital bed days and emergency discharges (see
the dataset cso_hospital_discharges), GP visits, child obesity, admissions, infections, deaths, screening,
smoking, fertility, breastfeeding and ambulance response.

One row per table, statistic, year and breakdown category (all kept tables have one breakdown; "Ireland" where
the table is national only). Values as published.
"""

import itertools
import json

from ..http import fetch

KEY = "doh_health_key_trends"
FIELDS = ["table", "table_title", "statistic_code", "statistic", "period", "breakdown", "category_code", "category",
          "unit", "value", "status"]
URL = "https://ws.cso.ie/public/api.restful/PxStat.Data.Cube_API.ReadDataset/{}/JSON-stat/2.0/en"
TABLES = ["KTA08", "KTA09", "KTA13", "KTA14", "KTA15", "KTA16", "KTA30", "KTA36", "KTA37", "KTA38"]
CONFIDENTIAL = -99999999


def fetch_raw() -> bytes:
    """All tables as one JSON object {table code: JSON-stat 2.0 cube}."""
    return json.dumps({t: json.loads(fetch(URL.format(t), timeout=180)) for t in TABLES}).encode("utf-8")


def _codes(dim):
    idx = dim["category"]["index"]
    return list(idx) if isinstance(idx, list) else [k for k, _ in sorted(idx.items(), key=lambda kv: kv[1])]


def _period(code: str) -> str:
    if len(code) == 6 and code.isdigit():           # TLIST(M1): 201501 -> 2015-01
        return f"{code[:4]}-{code[4:]}"
    if len(code) == 5 and code.isdigit():           # TLIST(Q1): 20251 -> 2025-Q1
        return f"{code[:4]}-Q{code[4]}"
    return code


def _cube_rows(table: str, r: dict) -> list:
    ids, size, values = r["id"], r["size"], r["value"]
    n = 1
    for s in size:
        n *= s
    if isinstance(values, dict):  # JSON-stat may send a sparse object
        values = [values.get(str(i)) for i in range(n)]
    if len(values) != n:
        raise RuntimeError(f"CSO {table}: cube has {len(values)} values, expected {n}")
    time_dims = [d for d in ids if d.startswith("TLIST(")]
    other = [d for d in ids if d != "STATISTIC" and d not in time_dims]
    if len(time_dims) != 1 or len(other) != 1 or "STATISTIC" not in ids:
        raise RuntimeError(f"CSO {table}: unexpected dimensions {ids}")
    tdim, bdim = time_dims[0], other[0]
    codes = [_codes(r["dimension"][d]) for d in ids]
    if [len(c) for c in codes] != list(size):
        raise RuntimeError(f"CSO {table}: dimension sizes do not match the category lists")
    labels = {d: r["dimension"][d]["category"].get("label", {}) for d in ids}
    units = r["dimension"]["STATISTIC"]["category"].get("unit", {})
    out = []
    for combo, v in zip(itertools.product(*codes), values):
        c = dict(zip(ids, combo))
        sc, tc, bc = c["STATISTIC"], c[tdim], c[bdim]
        status = ""
        if v == CONFIDENTIAL:
            v, status = None, "confidential"
        out.append({"table": table, "table_title": r.get("label", "").strip(), "statistic_code": sc,
                    "statistic": labels["STATISTIC"].get(sc, sc).strip(), "period": _period(tc),
                    "breakdown": r["dimension"][bdim].get("label", bdim), "category_code": bc,
                    "category": labels[bdim].get(bc, bc).strip(), "unit": units.get(sc, {}).get("label", ""),
                    "value": "" if v is None else v, "status": status})
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
