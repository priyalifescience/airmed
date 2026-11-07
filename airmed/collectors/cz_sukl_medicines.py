"""Czech Republic (SUKL): the national medicines database DLP, one row per product variant with a SUKL code.

Source: the DLP open-data file (a monthly zip of CSV tables, Windows-1250, semicolons) from
https://opendata.sukl.gov.cz/katalog-otevrenych-dat/databaze-lecivych-pripravku-dlp. The file name changes with each
release, so the link is read from that page.

The main table is joined to SUKL's own lookup tables for the marketing authorisation holder, form, route and active
substances. The WHO defined daily dose columns are not kept: DDDs are WHO material, and
SUKL's open-data terms do not cover third-party intellectual property. The holder is a company in this table.

Terms: https://opendata.sukl.gov.cz/podminky-uziti-otevrenych-dat allows commercial use and redistribution if SUKL is
named as the source, the terms are linked, no endorsement is implied and the meaning of the data is not changed.
SUKL also confirmed by email on 5 November 2026 that the data can be used on those conditions.
"""

import csv
import io
import re
import zipfile

from ..http import fetch

KEY = "cz_sukl_medicines"
FIELDS = ["sukl_code", "name", "strength", "form", "pack", "route",
          "marketing_authorisation_holder", "holder_country", "registration_status_code",
          "registration_number", "procedure", "atc", "substances", "dispensing_code", "supplied_last_6_months",
          "product_type", "valid_until", "unlimited_validity"]
PAGE = "https://opendata.sukl.gov.cz/katalog-otevrenych-dat/databaze-lecivych-pripravku-dlp"
LINK_RE = re.compile(r'https://opendata\.sukl\.gov\.cz/soubory/SOD\d{8}/DLP\d{8}\.zip')
MIN_ROWS = 50000


def fetch_raw() -> bytes:
    links = LINK_RE.findall(fetch(PAGE, timeout=60).decode("utf-8", "replace"))
    if not links:
        raise RuntimeError("SUKL DLP: no zip link on the catalogue page")
    return fetch(sorted(links)[-1], timeout=300)


def _table(z: zipfile.ZipFile, name: str) -> list:
    return list(csv.DictReader(io.StringIO(z.read(name).decode("cp1250")), delimiter=";"))


def _date(v: str) -> str:
    v = (v or "").strip()
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", v)
    return f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}" if m else v


def parse(raw: bytes, min_rows: int = MIN_ROWS) -> list:
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        rows = _table(z, "dlp_lecivepripravky.csv")
        orgs = {(o["ZKR_ORG"], o["ZEM"]): o["NAZEV"].strip() for o in _table(z, "dlp_organizace.csv")}
        forms = {f["FORMA"]: f["NAZEV_EN"].strip() for f in _table(z, "dlp_formy.csv")}
        routes = {r["CESTA"]: r["NAZEV_EN"].strip() for r in _table(z, "dlp_cesty.csv")}
        substances = {s["KOD_LATKY"]: (s["NAZEV_EN"] or s["NAZEV_INN"] or s["NAZEV"]).strip() for s in _table(z, "dlp_latky.csv")}
    if rows and not {"KOD_SUKL", "NAZEV", "DRZ", "ZEMDRZ", "REG", "ATC_WHO", "LL"} <= set(rows[0]):
        raise RuntimeError(f"SUKL DLP: unexpected columns {list(rows[0])}")
    out = []
    for r in rows:
        out.append({
            "sukl_code": r["KOD_SUKL"].strip(),
            "name": r["NAZEV"].strip(),
            "strength": r["SILA"].strip(),
            "form": forms.get(r["FORMA"], "") or r["FORMA"].strip(),
            "pack": r["BALENI"].strip(),
            "route": routes.get(r["CESTA"], "") or r["CESTA"].strip(),
            "marketing_authorisation_holder": orgs.get((r["DRZ"], r["ZEMDRZ"]), ""),
            "holder_country": r["ZEMDRZ"].strip(),
            "registration_status_code": r["REG"].strip(),
            "registration_number": r["RC"].strip(),
            "procedure": r["REG_PROC"].strip(),
            "atc": r["ATC_WHO"].strip(),
            "substances": "; ".join(s for s in (substances.get(c.strip(), "") for c in r["LL"].split(",")) if s),
            "dispensing_code": r["VYDEJ"].strip(),
            "supplied_last_6_months": {"1": "yes", "0": "no"}.get(r["DODAVKY"].strip(), ""),
            "product_type": r["TYP_LP"].strip(),
            "valid_until": _date(r["V_PLATDO"]),
            "unlimited_validity": "yes" if r["NEOMEZ"].strip() else "no",
        })
    if len(out) < min_rows:
        raise RuntimeError(f"SUKL DLP: only {len(out)} products (expected at least {min_rows}); broken download?")
    out.sort(key=lambda x: x["sukl_code"])
    return out
