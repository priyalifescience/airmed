"""Italy (AIFA): medicines temporarily in shortage ("Lista dei farmaci temporaneamente carenti").

One CSV on AIFA's open data page "Liste dei farmaci", section "Carenze e indisponibilità"
(https://www.aifa.gov.it/liste-dei-farmaci; file /documents/20142/847339/elenco_medicinali_carenti.csv, updated
several times a week). The file starts with a note and a line "Elenco dei farmaci carenti aggiornato al dd/mm/yyyy"
(kept as `list_date`), then one row per pack (AIC code): brand, AIC code, active substance, form and strength, MAH,
start date, expected end date, whether an equivalent medicine is available, reason, AIFA's advice, AIFA note,
reimbursement class and ATC code.

AIFA's note on the file: packs whose MAH has not reported the actual end of the shortage stay on the list, even after
the expected end date. So an expected end date in the past does not mean the shortage has ended.

Values are as published (Italian labels kept); dates converted to ISO. The MAH ("Titolare AIC") is a company.
"""

import csv
import io
import re

from ..http import fetch
from .it_aifa_reimbursed_medicines import clean, decode, it_date

KEY = "it_aifa_shortages"
FIELDS = ["medicine", "aic_code", "active_substance", "form_and_strength", "marketing_authorisation_holder",
          "atc_code", "reimbursement_class", "start_date", "expected_end_date", "equivalent_available", "reason",
          "aifa_advice", "aifa_note", "list_date"]
URL = "https://www.aifa.gov.it/documents/20142/847339/elenco_medicinali_carenti.csv"
MIN_ROWS = 500
FAX_RE = re.compile(r"\s*[–-]\s*Fax\s+[\d ]+$")
COLUMNS = [("Nome medicinale", "medicine"), ("Codice AIC", "aic_code"), ("Principio attivo", "active_substance"),
           ("Forma farmaceutica e dosaggio", "form_and_strength"), ("Titolare AIC", "marketing_authorisation_holder"),
           ("Data inizio", "start_date"), ("Fine presunta", "expected_end_date"), ("Equivalente", "equivalent_available"),
           ("Motivazioni", "reason"), ("Suggerimenti/Indicazioni AIFA", "aifa_advice"), ("Nota AIFA", "aifa_note"),
           ("Classe di rimborsabilit", "reimbursement_class"), ("Codice ATC", "atc_code")]


def fetch_raw() -> bytes:
    return decode(fetch(URL, timeout=120)).encode("utf-8")


def parse(raw: bytes, min_rows: int = MIN_ROWS) -> list:
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8")), delimiter=";"))
    hi = next((i for i, r in enumerate(rows[:10]) if r and clean(r[0]) == "Nome medicinale"), None)
    if hi is None:
        raise RuntimeError("AIFA carenze: header row not found")
    m = next((re.search(r"aggiornato al (\d{1,2}/\d{1,2}/\d{4})", " ".join(r)) for r in rows[:hi]
              if re.search(r"aggiornato al \d", " ".join(r))), None)
    list_date = it_date(m[1]) if m else ""
    h = [clean(c) for c in rows[hi]]
    idx = {}
    for col, field in COLUMNS:
        i = next((j for j, x in enumerate(h) if x.startswith(col)), None)
        if i is None:
            raise RuntimeError(f"AIFA carenze: column {col!r} missing (got {h})")
        idx[field] = i
    out = []
    for r in rows[hi + 1:]:
        if not any(c.strip() for c in r):
            continue
        r = r + [""] * (len(h) - len(r))
        rec = {f: clean(r[i]) for f, i in idx.items()}
        # an office fax number (Ministero della Salute, Ufficio Centrale Stupefacenti) would make the privacy guard
        # blank the whole advice; it is not personal data, but we drop only the number and keep the advice
        rec["aifa_advice"] = FAX_RE.sub("", rec["aifa_advice"])
        for f in ("start_date", "expected_end_date"):
            rec[f] = it_date(rec[f])
        if not re.fullmatch(r"\d{9}", rec["aic_code"]):
            raise RuntimeError(f"AIFA carenze: unexpected AIC code {rec['aic_code']!r}")
        rec["list_date"] = list_date
        out.append({f: rec[f] for f in FIELDS})
    if len(out) < min_rows:
        raise RuntimeError(f"AIFA carenze: only {len(out)} rows (expected at least {min_rows}); broken download?")
    out.sort(key=lambda r: (r["medicine"].lower(), r["aic_code"], r["start_date"]))
    return out
