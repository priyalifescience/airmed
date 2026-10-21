"""Italy (AIFA): medicines spending and consumption national totals by class and ATC, per year (2016 onwards).

AIFA's open data page "Spesa e consumo relativi al flusso della farmaceutica convenzionata e degli acquisti diretti"
(https://www.aifa.gov.it/spesa-e-consumo-relativi-al-flusso-della-farmaceutica-convenzionata-e-degli-acquisti-diretti)
publishes one file per year (CSV, or a zip holding one CSV; pipe-separated) with, per month, region, reimbursement
class and ATC code (5 characters, the 4th ATC level; a few rows carry a 4-character code):
- numero_confezioni_traccia / spesa_flusso_tracciabilita: packs and spend in the medicines traceability flow
  (direct purchases by public health facilities, "acquisti diretti");
- numero_confezioni_convenzionata / spesa_convenzionata: packs and spend dispensed by community pharmacies under the
  SSN agreement ("farmaceutica convenzionata"), from the collaborating pharmacies.
AIFA describes the figures as "Dati elaborati da AIFA" used in its spending monitoring (OsMed report, monthly
monitoring reports). The page's link to the "Manuale operativo" (field descriptions) currently points to an unrelated
document, so the field docs here describe the columns from their names and the page text.

Size: the monthly regional files hold about 1.7 million rows (2016-2025); even annual totals per region would be
about 175,000 rows and 54 MB of JSON, above our 30 MB limit. So we publish national annual totals: the 12 months and
the 21 regions / autonomous provinces of each year are added up per class and ATC code (this is our only change; no
value is estimated). `months_reported` and `regions_reported` say how many months and regions had a row.
Empty cells are not zero: a pack/spend value that is empty in every source row stays empty. Class labels are as
published (e.g. both "C-bis" and "C-BIS" occur); ATC descriptions are AIFA's Italian ones (the first one met in the
year), and only the ATC code at the published level is kept (levels 1-3 can be derived from the code).
"""

import csv
import io
import json
import re
import zipfile

from ..http import fetch
from .it_aifa_reimbursed_medicines import clean, decode, page_links

KEY = "it_aifa_medicines_spending"
FIELDS = ["year", "reimbursement_class", "atc_code", "atc_description",
          "direct_purchase_packs", "direct_purchase_spend_eur", "community_packs", "community_spend_eur",
          "months_reported", "regions_reported"]
PAGE = "https://www.aifa.gov.it/it/spesa-e-consumo-relativi-al-flusso-della-farmaceutica-convenzionata-e-degli-acquisti-diretti"
FIRST_YEAR = 2016
REQUIRED = ["anno", "mese", "codreg", "regione", "classe", "atc4", "descrizione_atc4", "numero_confezioni_traccia",
            "spesa_flusso_tracciabilita", "numero_confezioni_convenzionata", "spesa_convenzionata"]
VALUES = [("numero_confezioni_traccia", "direct_purchase_packs"), ("spesa_flusso_tracciabilita", "direct_purchase_spend_eur"),
          ("numero_confezioni_convenzionata", "community_packs"), ("spesa_convenzionata", "community_spend_eur")]
MIN_ROWS_PER_YEAR = 500


def _num(s: str):
    v = (s or "").strip()
    if not v:
        return None
    if "," in v and "." not in v:
        v = v.replace(",", ".")
    if not re.fullmatch(r"-?\d+(\.\d+)?([eE][+-]?\d+)?", v):          # some years write 1.48E6
        raise ValueError(f"AIFA spesa e consumo: not a number: {s!r}")
    return float(v)


def annualise(text: str) -> list:
    """One year's monthly file -> national annual rows (sum of the months and regions per class and ATC code)."""
    reader = csv.DictReader(io.StringIO(text), delimiter="|")
    reader.fieldnames = [clean(c).lower() for c in reader.fieldnames or []]
    missing = [c for c in REQUIRED if c not in reader.fieldnames]
    if missing:
        raise RuntimeError(f"AIFA spesa e consumo: column(s) {missing} missing (got {reader.fieldnames})")
    agg = {}
    for r in reader:
        key = (clean(r["anno"]), clean(r["classe"]), clean(r["atc4"]))
        if not key[0] or not key[2]:
            continue
        a = agg.get(key)
        if a is None:
            a = agg[key] = {"desc": clean(r["descrizione_atc4"]), "months": set(), "regions": set(), **{f: None for _, f in VALUES}}
        a["months"].add(clean(r["mese"]))
        a["regions"].add(clean(r["codreg"]))
        for col, f in VALUES:
            v = _num(r[col])
            if v is not None:
                a[f] = v if a[f] is None else a[f] + v
    out = []
    for (year, cls, atc), a in agg.items():
        rec = {"year": int(year), "reimbursement_class": cls, "atc_code": atc, "atc_description": a["desc"],
               "months_reported": len(a["months"]), "regions_reported": len(a["regions"])}
        for _, f in VALUES:
            v = a[f]
            rec[f] = "" if v is None else (int(v) if f.endswith("packs") else round(v, 2))
        out.append({f: rec[f] for f in FIELDS})
    return out


def _year(url: str):
    m = re.search(r"dati_?(\d{4})_", url)
    return int(m[1]) if m else None


def fetch_raw() -> bytes:
    """{year: [annual rows]} as JSON. Each monthly file is annualised as soon as it is read, to keep memory low."""
    urls = [u for u in page_links(PAGE, r"/847578/dati_?\d{4}_") if _year(u) and _year(u) >= FIRST_YEAR]
    years = sorted({_year(u) for u in urls})
    if len(urls) != len(years) or not years or years != list(range(FIRST_YEAR, years[-1] + 1)):
        raise RuntimeError(f"AIFA spesa e consumo: unexpected file list {urls}")
    out = {}
    for u in urls:
        body = fetch(u, timeout=600)
        if body[:2] == b"PK":
            z = zipfile.ZipFile(io.BytesIO(body))
            names = [n for n in z.namelist() if n.lower().endswith(".csv")]
            if len(names) != 1:
                raise RuntimeError(f"AIFA spesa e consumo {u}: expected one CSV in the zip, found {names}")
            body = z.read(names[0])
        out[str(_year(u))] = annualise(decode(body))
    return json.dumps(out, ensure_ascii=False).encode("utf-8")


def parse(raw: bytes, min_rows_per_year: int = MIN_ROWS_PER_YEAR) -> list:
    data = json.loads(raw)
    out = []
    for year, rows in data.items():
        if len(rows) < min_rows_per_year:
            raise RuntimeError(f"AIFA spesa e consumo {year}: only {len(rows)} rows (expected at least {min_rows_per_year})")
        bad = {r["year"] for r in rows} - {int(year)}
        if bad:
            raise RuntimeError(f"AIFA spesa e consumo: file for {year} holds rows for {sorted(bad)}")
        out.extend({f: r[f] for f in FIELDS} for r in rows)
    out.sort(key=lambda r: (r["year"], r["reimbursement_class"], r["atc_code"]))
    return out
