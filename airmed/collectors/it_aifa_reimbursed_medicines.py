"""Italy (AIFA): medicines reimbursed by the national health service (SSN), Class A and Class H lists.

AIFA publishes, on its open data page "Liste dei farmaci" (https://www.aifa.gov.it/liste-dei-farmaci), the
"Lista farmaci di classe A e H per consentire a tutti gli Operatori la prescrizione per principio attivo": one CSV
per class, each published twice (sorted by active substance and by brand name; the rows are the same). We read the
"per principio attivo" file of each class. The file names carry the list date (e.g.
Classe_A_per_principio_attivo_31-05-2026.csv), so the current links are read from the page on every run.

- Class A ("fascia A"): medicines dispensed by community pharmacies at the SSN's expense. Columns: active substance,
  equivalence group, pack, public price, marketing authorisation holder (MAH, "Titolare AIC"), AIC pack code,
  equivalence group code, whether the pack is on AIFA's transparency list (generic reference price list), the
  region(s) where it is listed only regionally, and cubic metres for medical oxygen.
- Class H ("fascia H"): hospital medicines. Columns as above plus the ex-factory price and the maximum transfer
  price to hospitals ("prezzo massimo di cessione"); no transparency-list column.

ATC codes are not in the class lists. They are added from AIFA's own medicines register ("Anagrafica dei farmaci",
https://drive.aifa.gov.it/farmaci/confezioni_fornitura.csv, same open data page and licence), matched on the 9-digit
AIC pack code; about 1.5% of packs (mostly medical oxygen and other gases) have no register row and keep an empty
`atc_code`. To keep the raw file small, fetch_raw keeps only the register's AIC -> ATC pairs for packs in the lists.

Values are as published (Italian labels kept). Prices are converted from Italian decimal commas to numbers; prices
of medical oxygen are published per cubic metre ("6,55/m³"), which `price_unit` says. MAH names are companies.
"""

import csv
import html
import io
import json
import re

from ..http import fetch

KEY = "it_aifa_reimbursed_medicines"
FIELDS = ["reimbursement_class", "aic_code", "active_substance", "equivalence_group_code",
          "equivalence_group_description", "product_and_pack", "marketing_authorisation_holder", "atc_code",
          "retail_price_eur", "ex_factory_price_eur", "max_hospital_price_eur", "price_unit", "in_transparency_list",
          "regional_list_only", "oxygen_cubic_metres", "list_date"]
BASE = "https://www.aifa.gov.it"
PAGE = BASE + "/it/liste-dei-farmaci"
REGISTER = "https://drive.aifa.gov.it/farmaci/confezioni_fornitura.csv"
MIN_ROWS = {"A": 5000, "H": 1000}


# ---------- helpers shared by the it_aifa_* collectors ----------

def decode(b: bytes) -> str:
    """AIFA CSVs are UTF-8 or Windows-1252 (euro sign, curly apostrophes)."""
    try:
        return b.decode("utf-8-sig")
    except UnicodeDecodeError:
        return b.decode("cp1252")


def page_links(page_url: str, pattern: str) -> list:
    """Absolute https links on an AIFA page whose href matches `pattern` (in page order, no duplicates)."""
    text = decode(fetch(page_url, timeout=60))
    out = []
    for href in re.findall(r'href="([^"]+)"', text):
        href = html.unescape(href)
        if re.search(pattern, href) and href not in out:
            out.append(href)
    return [BASE + h if h.startswith("/") else h for h in out]


def it_num(s: str):
    """Italian number ('1.234,56', '60,69', '7') -> int/float; '', '-' -> ''."""
    v = (s or "").strip()
    if v in ("", "-"):
        return ""
    v = v.replace(".", "").replace(",", ".") if "," in v else v
    if not re.fullmatch(r"-?\d+(\.\d+)?", v):
        raise ValueError(f"AIFA: not a number: {s!r}")
    f = float(v)
    return int(f) if f.is_integer() else f


def it_date(s: str) -> str:
    """dd/mm/yyyy, dd-mm-yyyy, dd.mm.yyyy or yyyy/mm/dd -> YYYY-MM-DD; '' stays ''."""
    v = (s or "").strip()
    if not v:
        return ""
    m = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", v)
    if m:
        return f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}"
    m = re.fullmatch(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", v)
    if m:
        return f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}"
    raise ValueError(f"AIFA: unexpected date {s!r}")


def clean(s) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


# ---------- fetching ----------

def fetch_raw() -> bytes:
    """{"lists": {"A": {"name", "text"}, "H": {...}}, "atc": {aic: atc}} as JSON."""
    lists = {}
    for cls in ("A", "H"):
        urls = page_links(PAGE, rf"Classe_{cls}_per_principio_attivo[^/]*\.csv$")
        if len(urls) != 1:
            raise RuntimeError(f"AIFA liste dei farmaci: expected one Class {cls} file, found {urls}")
        lists[cls] = {"name": urls[0].rsplit("/", 1)[-1], "text": decode(fetch(urls[0], timeout=120))}
    wanted = set()
    for cls, v in lists.items():
        rows = _rows(v["text"])
        i = _col([clean(x) for x in rows[0]], "Codice AIC" if cls == "H" else "AIC")
        wanted |= {r[i].strip() for r in rows[1:] if len(r) > i}
    atc = {}
    for r in csv.DictReader(io.StringIO(decode(fetch(REGISTER, timeout=600))), delimiter=";"):
        aic = (r.get("CODICE_AIC") or "").strip()
        if aic in wanted and (r.get("CODICE_ATC") or "").strip():
            atc[aic] = r["CODICE_ATC"].strip()
    if len(atc) < 0.9 * len(wanted):
        raise RuntimeError(f"AIFA register: ATC found for only {len(atc)} of {len(wanted)} packs")
    return json.dumps({"lists": lists, "atc": atc}, ensure_ascii=False).encode("utf-8")


# ---------- parsing ----------

def _rows(text: str) -> list:
    return [r for r in csv.reader(io.StringIO(text), delimiter=";") if any(c.strip() for c in r)]


def _col(header: list, prefix: str, required: bool = True):
    for i, h in enumerate(header):
        if clean(h).lower().startswith(prefix.lower()):
            return i
    if required:
        raise RuntimeError(f"AIFA class list: column starting {prefix!r} missing (got {header})")
    return None


def _price(s: str) -> tuple:
    v = clean(s)
    if v.endswith("/m³"):
        return it_num(v[:-3]), "per m³"
    return it_num(v), "per pack"


def parse_list(cls: str, name: str, text: str, atc: dict) -> list:
    rows = _rows(text)
    h = [clean(c) for c in rows[0]]
    c = {k: _col(h, p, req) for k, p, req in [
        ("sub", "Principio attivo", True), ("grp", "Descrizione gruppo", True), ("pack", "Denominazione", True),
        ("pub", "Prezzo al pubblico", True), ("exf", "Prezzo Ex-factory", cls == "H"),
        ("max", "Prezzo massimo di cessione", cls == "H"), ("mah", "Titolare AIC", True),
        ("aic", "Codice AIC" if cls == "H" else "AIC", True), ("code", "Codice Gruppo", True),
        ("tl", "X=in lista di trasparenza", cls == "A"), ("reg", "Solo in lista di Regione", cls == "A"),
        ("o2", "Metri cubi ossigeno", True)]}
    m = re.search(r"(\d{2}-\d{2}-\d{4})", name)
    list_date = it_date(m[1]) if m else ""
    out = []
    for r in rows[1:]:
        r = r + [""] * (len(h) - len(r))
        g = lambda k: clean(r[c[k]]) if c[k] is not None else ""
        aic = g("aic")
        if not re.fullmatch(r"\d{9}", aic):
            raise RuntimeError(f"AIFA Class {cls}: unexpected AIC code {aic!r}")
        pub, unit = _price(g("pub"))
        exf, unit2 = _price(g("exf"))
        mx, _ = _price(g("max"))
        out.append({
            "reimbursement_class": cls, "aic_code": aic, "active_substance": g("sub"),
            "equivalence_group_code": g("code"), "equivalence_group_description": g("grp"),
            "product_and_pack": g("pack"), "marketing_authorisation_holder": g("mah"), "atc_code": atc.get(aic, ""),
            "retail_price_eur": pub, "ex_factory_price_eur": exf, "max_hospital_price_eur": mx,
            "price_unit": unit if pub != "" else (unit2 if exf != "" else ""),
            "in_transparency_list": ("yes" if g("tl").upper() == "X" else "no") if cls == "A" else "",
            "regional_list_only": [x.strip() for x in g("reg").split(",") if x.strip()],
            "oxygen_cubic_metres": it_num(g("o2")), "list_date": list_date,
        })
    return out


def parse(raw: bytes, min_rows: dict = None) -> list:
    data = json.loads(raw)
    min_rows = MIN_ROWS if min_rows is None else min_rows
    out = []
    for cls in ("A", "H"):
        f = data["lists"][cls]
        rows = parse_list(cls, f["name"], f["text"], data.get("atc", {}))
        if len(rows) < min_rows.get(cls, 0):
            raise RuntimeError(f"AIFA Class {cls}: only {len(rows)} rows (expected at least {min_rows[cls]})")
        out.extend(rows)
    out.sort(key=lambda r: (r["reimbursement_class"], r["active_substance"].lower(), r["aic_code"]))
    return out
