"""Italy (AIFA): authorised pharmaceutical manufacturing sites ("Officine autorizzate").

AIFA's open data page "Officine autorizzate" (https://www.aifa.gov.it/officine-autorizzate) publishes three CSV lists
under art. 50(8) of Legislative Decree 219/2006, each with company, site address and (for two of them) province:
- officine_autorizzate_medicinali_<date>.csv: sites authorised to manufacture medicines (`site_type` "medicinali");
- officine_autorizzate_gas_medicali_<date>.csv: sites authorised to manufacture medical gases ("gas medicinali");
- OFFICINE_API_<month>_<year>.csv: sites authorised or registered to manufacture or import active substances
  ("sostanze attive"; AIFA's page calls them "materie prime farmacologicamente attive").
The file names change with each update, so the links are read from the page on every run; the list date in the
file name is kept as `list_date`. The files do not say which activities each site is authorised for.

We keep the company, the town, the province code and the region, and drop the street and house number (by choice:
plant addresses are companies' public data, but the town is enough to compare with the Irish pharma map). The town
is the part of the published address after the last " - " (with the postcode removed), or after the house number;
when the address cannot be split safely the town is left empty and only the province and region are kept. The region
comes from the province code (table below; "RSM" is San Marino). Coordinates are not published and not added.
"""

import calendar
import csv
import io
import re

from ..http import fetch
from .it_aifa_reimbursed_medicines import clean, decode, it_date, page_links

KEY = "it_aifa_manufacturing_sites"
FIELDS = ["company", "town", "province", "region", "site_type", "list_date"]
PAGE = "https://www.aifa.gov.it/it/officine-autorizzate"
LISTS = [  # (link pattern, site_type, minimum rows)
    (r"officine_autorizzate_medicinali_[^/]*\.csv$", "medicinali", 150),
    (r"officine_autorizzate_gas_medicali_[^/]*\.csv$", "gas medicinali", 50),
    (r"OFFICINE_API_[^/]*\.csv$", "sostanze attive", 150),
]
MONTHS = {"GENNAIO": 1, "FEBBRAIO": 2, "MARZO": 3, "APRILE": 4, "MAGGIO": 5, "GIUGNO": 6, "LUGLIO": 7,
          "AGOSTO": 8, "SETTEMBRE": 9, "OTTOBRE": 10, "NOVEMBRE": 11, "DICEMBRE": 12}
_REGIONS = {
    "Piemonte": "AL AT BI CN NO TO VB VC", "Valle d'Aosta": "AO", "Lombardia": "BG BS CO CR LC LO MB MI MN PV SO VA",
    "Trentino-Alto Adige": "BZ TN", "Veneto": "BL PD RO TV VE VI VR", "Friuli-Venezia Giulia": "GO PN TS UD",
    "Liguria": "GE IM SP SV", "Emilia-Romagna": "BO FC FO FE MO PC PR RA RE RN",
    "Toscana": "AR FI GR LI LU MS PI PO PT SI", "Umbria": "PG TR", "Marche": "AN AP FM MC PU PS",
    "Lazio": "FR LT RI RM VT", "Abruzzo": "AQ CH PE TE", "Molise": "CB IS", "Campania": "AV BN CE NA SA",
    "Puglia": "BA BR BT FG LE TA", "Basilicata": "MT PZ", "Calabria": "CS CZ KR RC VV",
    "Sicilia": "AG CL CT EN ME PA RG SR TP", "Sardegna": "CA CI MD NU OG OR OT SS SU VS", "San Marino": "RSM",
}
PROVINCE_REGION = {p: reg for reg, ps in _REGIONS.items() for p in ps.split()}


def fetch_raw() -> bytes:
    """The three CSVs, each preceded by a line '#FILE <site_type>|<file name>' (UTF-8)."""
    parts = []
    for pattern, site_type, _ in LISTS:
        urls = page_links(PAGE, pattern)
        if len(urls) != 1:
            raise RuntimeError(f"AIFA officine autorizzate: expected one {site_type} file, found {urls}")
        parts.append(f"#FILE {site_type}|{urls[0].rsplit('/', 1)[-1]}\n" + decode(fetch(urls[0], timeout=120)))
    return "\n".join(parts).encode("utf-8")


def _list_date(name: str) -> str:
    m = re.search(r"(\d{2}[.-]\d{2}[.-]\d{4})", name)
    if m:
        return it_date(m[1])
    m = re.search(r"_([A-Z]+)_(\d{4})", name.upper())
    if m and m[1] in MONTHS:                       # OFFICINE_API_GIUGNO_2025: AIFA dates it the last day ("al 30/06/2025")
        mo, y = MONTHS[m[1]], int(m[2])
        return f"{y}-{mo:02d}-{calendar.monthrange(y, mo)[1]:02d}"
    return ""


def split_location(address: str, prov_col: str = "") -> tuple:
    """Published address -> (town, province code). The street is never returned."""
    a = clean(address).rstrip(" .")
    province = ""
    m = re.search(r"\(\s*([A-Z]{2,3})\s*\)$", a)
    if m:
        province, a = m[1], a[:m.start()].rstrip(" -")
    else:
        province = clean(prov_col).rstrip(".")
    town = ""
    if re.search(r"\s-\s|\s-$|-\s", a):
        town = re.split(r"\s+-\s*|\s*-\s+", a)[-1]
    else:
        m = re.search(r"(?:\d\S*|\bSNC|\))\s+([^\d,()]+)$", a)
        if m:
            town = m[1]
    town = re.sub(r"^\d{5}\s+", "", clean(town))
    town = re.sub(r"^\([^)]*\)\s*", "", town)            # "(LOC.CASTIGLION FIORENTINO) AREZZO" -> "AREZZO"
    if not town or re.search(r"\d", town) or re.match(r"(VIA|VIALE|PIAZZA|STRADA|CORSO|LOC)\b", town, re.I):
        town = ""
    return town, province


def parse(raw: bytes, min_rows: bool = True) -> list:
    text = raw.decode("utf-8")
    chunks = re.split(r"^#FILE ", text, flags=re.M)[1:]
    if len(chunks) != len(LISTS):
        raise RuntimeError(f"AIFA officine: expected {len(LISTS)} files, got {len(chunks)}")
    out = []
    for chunk in chunks:
        head, body = chunk.split("\n", 1)
        site_type, name = head.strip().split("|", 1)
        list_date = _list_date(name)
        rows = [[clean(c) for c in r] for r in csv.reader(io.StringIO(body), delimiter=";")]
        hi = next((i for i, r in enumerate(rows[:5]) if r and r[0].upper() in ("AZIENDA", "DENOMINAZIONE")), None)
        if hi is None:
            raise RuntimeError(f"AIFA officine {name}: header row not found")
        n = 0
        for r in rows[hi + 1:]:
            if len(r) < 2 or not r[0] or not r[1]:
                continue
            town, prov = split_location(r[1], r[2] if len(r) > 2 else "")
            out.append({"company": r[0], "town": town, "province": prov, "region": PROVINCE_REGION.get(prov, ""),
                        "site_type": site_type, "list_date": list_date})
            n += 1
        need = next(m for p, t, m in LISTS if t == site_type)
        if min_rows and n < need:
            raise RuntimeError(f"AIFA officine {name}: only {n} sites (expected at least {need})")
    out.sort(key=lambda r: (r["site_type"], r["company"].lower(), r["province"], r["town"]))
    return out
