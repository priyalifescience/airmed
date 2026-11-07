"""Czech Republic (SUKL): notices of a medicine's supply starting, being interrupted, ending or resuming.

Marketing authorisation holders must report these to SUKL. Source: mr.zip, a CSV (Windows-1250, semicolons) refreshed by
SUKL, from https://opendata.sukl.gov.cz/katalog-otevrenych-dat/hlaseni-o-uvedeni-preruseni-ukonceni-obnoveni-dodavek-leciveho-pripravku-na-trh

One row per notice, the full history. `latest` marks the most recent valid notice for a product, so filtering on
latest = yes and notice_type = interruption gives the medicines interrupted now. The free-text reason and replacement
notes stay in Czech as published; only the notice type and dates are normalised.

Terms: https://opendata.sukl.gov.cz/podminky-uziti-otevrenych-dat allows commercial use and redistribution if SUKL is
named as the source, the terms are linked, no endorsement is implied and the meaning of the data is not changed.
SUKL also confirmed by email on 5 November 2026 that the data can be used on those conditions.
"""

import csv
import io
import re
import zipfile

from ..http import fetch

KEY = "cz_sukl_supply_notices"
FIELDS = ["sukl_code", "name", "pack_detail", "registration_status_code", "atc", "notice_type", "effective_from",
          "notified_on", "latest", "replacement_sukl_code", "replacement_note", "reason", "expected_resumption"]
URL = "https://opendata.sukl.gov.cz/soubory/MR/mr.zip"
COLUMNS = ["POSLEDNI_PLATNE_HLASENI", "KOD_SUKL", "NAZEV", "DOPLNEK", "REG", "ATC", "TYP_OZNAMENI", "PLATNOST_OD",
           "DATUM_HLASENI", "NAHRAZUJICI_LP", "NAHRAZUJICI_LP_POZNAMKA", "DUVOD_PRERUSENI_UKONCENI", "TERMIN_OBNOVENI"]
TYPES = {"zahajeni": "start", "preruseni": "interruption", "ukonceni": "end", "obnoveni": "resumption"}
MIN_ROWS = 60000


def fetch_raw() -> bytes:
    return fetch(URL, timeout=180)


def _date(v: str) -> str:
    v = (v or "").strip()
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", v)
    return f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}" if m else v


def parse(raw: bytes, min_rows: int = MIN_ROWS) -> list:
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        rows = list(csv.DictReader(io.StringIO(z.read("mr_hlaseni.csv").decode("cp1250")), delimiter=";"))
    if rows and list(rows[0]) != COLUMNS:
        raise RuntimeError(f"SUKL notices: unexpected columns {list(rows[0])}")
    out = []
    for r in rows:
        kind = r["TYP_OZNAMENI"].strip()
        if kind not in TYPES:
            raise RuntimeError(f"SUKL notices: unknown notice type {kind!r}")
        out.append({
            "sukl_code": r["KOD_SUKL"].strip(),
            "name": r["NAZEV"].strip(),
            "pack_detail": r["DOPLNEK"].strip(),
            "registration_status_code": r["REG"].strip(),
            "atc": r["ATC"].strip(),
            "notice_type": TYPES[kind],
            "effective_from": _date(r["PLATNOST_OD"]),
            "notified_on": _date(r["DATUM_HLASENI"]),
            "latest": "yes" if r["POSLEDNI_PLATNE_HLASENI"].strip() == "ANO" else "no",
            "replacement_sukl_code": r["NAHRAZUJICI_LP"].strip(),
            "replacement_note": r["NAHRAZUJICI_LP_POZNAMKA"].strip(),
            "reason": r["DUVOD_PRERUSENI_UKONCENI"].strip(),
            "expected_resumption": _date(r["TERMIN_OBNOVENI"]),
        })
    if len(out) < min_rows:
        raise RuntimeError(f"SUKL notices: only {len(out)} notices (expected at least {min_rows}); broken download?")
    out.sort(key=lambda x: (x["sukl_code"], x["effective_from"], x["notified_on"], x["notice_type"]))
    return out
