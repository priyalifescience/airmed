"""Finland: Fimea basic register of medicinal products (human medicines, one row per product) plus Fimea's list of
medicine shortage notices (one row per package notice), in one table told apart by the `table` column.

Source: Fimea (Finnish Medicines Agency) open data, https://fimea.fi/tietoa_fimeasta/avoin-data, licence CC BY 4.0.
  - Lääkevalmisteiden perusrekisteri, XML, rebuilt every night: https://data.pilvi.fimea.fi/avoin-data/Perusrekisteri2026.xml
    (~225 MB; schema Perusrekisteri_Fimea_2026.xsd). Three lists: Pakkaus (package, ~146,000, incl. withdrawn ones),
    Laakevalmiste (product, ~30,000) and Laakeaine (active-substance set, ~32,000), linked by id references.
    The older Perusrekisteri.xml (2022 schema) is the same register without the package -> substance link.
  - Saatavuushäiriötiedot, semicolon text file: https://data.pilvi.fimea.fi/avoin-data/Saatavuushairiot.txt
    (~700 notices: package number VNR, in force K/E, start, end, notified, modified, company).
fetch_raw() downloads both and packs them into one zip (in memory) so parse() works on a single blob.

Choices:
  - Human medicines only (HUM = 1, ~28,000 products, current and withdrawn), like hpra_medicines; veterinary-only
    products are dropped. Shortage notices are kept when their package belongs to a human product, or when the package
    number is not in the register at all (product fields then empty).
  - One row per product, not per package (146,000 package rows would be ~60 MB). Package detail is summed into
    `packages`, `packages_marketed` (Kaupan = 1) and `packages_in_shortage` (the register's own shortage flag); the
    per-package shortage dates are in the `shortage` rows.
  - Interchangeable medicines: the register carries Fimea's substitution group per product (Substituutioryhma), which
    is the content of the quarterly "vaihtokelpoiset lääkevalmisteet" list, so that list (PDF + a separate database
    file on fimea.fi, behind a browser challenge) is not downloaded. Lääke75+ is not included.
  - Labels are kept as published, in Finnish (dosage form, route, status, procedure, ATC name); active-substance names
    are the register's own (English/Latin INN-style) names. ATC codes are kept for cross-country joins.
  - Size: ~28,700 rows, ~27 MB of JSON. To stay under 30 MB, shortage rows reuse `holder` for the notifying company
    (Yritys), and the notice's modified date and the parallel-distribution flag are not kept.
  - Every row carries `register_date` (Ajopvm), because Fimea's licence asks users to state "the date when Fimea
    released the data".
Holder and company are organisations; the source holds no personal data in the fields kept.
"""

import csv
import io
import xml.etree.ElementTree as ET
import zipfile

from ..http import fetch
from ..util import yes

KEY = "fi_fimea_medicines"
FIELDS = ["table", "register_date", "product_id", "trade_name", "atc_code", "atc_name", "strength", "dosage_form",
          "routes", "active_substances", "ddd", "ddd_unit", "authorisation_type", "authorisation_number",
          "eu_authorisation_number", "holder", "authorisation_status", "procedure", "authorisation_date",
          "authorisation_end_date", "parallel_import", "biological", "biosimilar",
          "narcotic", "additional_monitoring", "substitution_group", "packages", "packages_marketed",
          "packages_in_shortage", "vnr", "package_size", "shortage_in_force", "shortage_start", "shortage_end",
          "shortage_notified"]
REGISTER_URL = "https://data.pilvi.fimea.fi/avoin-data/Perusrekisteri2026.xml"
SHORTAGE_URL = "https://data.pilvi.fimea.fi/avoin-data/Saatavuushairiot.txt"
REGISTER_NAME, SHORTAGE_NAME = "Perusrekisteri2026.xml", "Saatavuushairiot.txt"
MIN_PRODUCTS = 20000    # ~28,000 human products; far fewer means a broken download
MIN_SHORTAGES = 100     # ~700 notices
SHORTAGE_HEADER = ["VNR", "Voimassa", "SaatavuushairioAlkupaiva", "SaatavuushairioLoppupaiva", "Ilmoituspaiva",
                   "Muokkauspaiva", "Yritys"]


def fetch_raw() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(REGISTER_NAME, fetch(REGISTER_URL, timeout=900))
        z.writestr(SHORTAGE_NAME, fetch(SHORTAGE_URL, timeout=120))
    return buf.getvalue()


def _t(el, path: str) -> str:
    x = el.find(path)
    return (x.text or "").strip() if x is not None and x.text else ""


def _attr(el, path: str, name: str = "value") -> str:
    x = el.find(path)
    return (x.get(name) or "").strip() if x is not None else ""


def _empty(table: str, register_date: str) -> dict:
    r = {f: "" for f in FIELDS}
    r.update({"table": table, "register_date": register_date, "routes": [], "active_substances": []})
    return r


def _shortages(text: str) -> list:
    rd = csv.reader(io.StringIO(text, newline=""), delimiter=";", quotechar='"')
    header = next(rd, None)
    if [h.strip() for h in header or []] != SHORTAGE_HEADER:
        raise RuntimeError(f"Fimea shortage file has an unexpected header: {header}")
    out = []
    for row in rd:
        if not any(c.strip() for c in row):
            continue
        if len(row) != len(SHORTAGE_HEADER):
            raise RuntimeError(f"Fimea shortage row has {len(row)} columns: {row}")
        out.append([c.strip() for c in row])
    return out


def parse(raw: bytes, min_products: int = MIN_PRODUCTS, min_shortages: int = MIN_SHORTAGES) -> list:
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        shortage_rows = _shortages(z.read(SHORTAGE_NAME).decode("utf-8-sig"))
        packages, substances, products, register_date = [], {}, {}, ""
        with z.open(REGISTER_NAME) as f:
            for _, el in ET.iterparse(f):   # the stdlib parser does not fetch external entities
                tag = el.tag
                if tag == "Ajopvm":
                    register_date = (el.text or "").strip()
                elif tag == "Pakkaus":
                    packages.append((el.get("Laakevalmiste-ref") or "", _t(el, "VNR-numero"),
                                     _t(el, "Pakkauskokoteksti"), _t(el, "Kaupanolo/Kaupan") == "1",
                                     _t(el, "SaatavuushairioTiedot/Saatavuushairio") == "1",
                                     [x.get("Laakeaine-ref") or "" for x in el.findall("Pakkaus_Laakeaine")]))
                    el.clear()
                elif tag == "Laakeaine":
                    substances[el.get("id") or ""] = [_attr(v, "Aine") for v in el.findall("VaikuttavaAine")
                                                      if _attr(v, "Aine")]
                    el.clear()
                elif tag == "Laakevalmiste":
                    if _t(el, "HUM") == "1":
                        products[el.get("id") or ""] = _product(el)
                    el.clear()
    if not register_date:
        raise RuntimeError("Fimea register has no run date (Versiotiedot/Ajopvm)")
    if len(products) < min_products:
        raise RuntimeError(f"Fimea register holds only {len(products)} human products; refusing a partial dataset")
    by_vnr = {}
    for ref, vnr, size, marketed, short, subst_refs in packages:
        p = products.get(ref)
        if vnr:
            by_vnr.setdefault(vnr, (ref, size))
        if p is None:
            continue
        p["packages"] += 1
        p["packages_marketed"] += marketed
        p["packages_in_shortage"] += short
        for s in subst_refs:
            for name in substances.get(s, []):
                if name not in p["active_substances"]:
                    p["active_substances"].append(name)
    out = []
    for pid, p in products.items():
        p["product_id"], p["register_date"] = pid, register_date
        out.append(p)
    n_short = 0
    for vnr, in_force, start, end, notified, modified, company in shortage_rows:
        ref, size = by_vnr.get(vnr, ("", ""))
        if ref and ref not in products:
            continue                                   # a veterinary-only product
        r = _empty("shortage", register_date)
        p = products.get(ref)
        if p:
            for k in ("product_id", "trade_name", "atc_code", "atc_name", "strength", "dosage_form"):
                r[k] = p[k]
        r.update({"vnr": vnr, "package_size": size, "shortage_in_force": {"K": "yes", "E": "no"}.get(in_force, in_force),
                  "shortage_start": start, "shortage_end": end, "shortage_notified": notified,
                  "holder": company})
        out.append(r)
        n_short += 1
    if n_short < min_shortages:
        raise RuntimeError(f"Fimea shortage list holds only {n_short} human-medicine notices")
    out.sort(key=lambda r: (r["table"], _idnum(r["product_id"]), r["vnr"], r["shortage_start"]))
    return out


def _idnum(pid: str):
    digits = pid[3:] if pid.startswith("REL") else ""
    return (0, int(digits), "") if digits.isdigit() else (1, 0, pid)


def _product(el) -> dict:
    ma = el.find("Myyntilupa")
    reg = el.find("Rekisterointi")
    auth = ma if ma is not None else reg
    r = _empty("product", "")
    r.update({
        "trade_name": _t(el, "Kauppanimi"),
        "atc_code": _attr(el, "ATC-koodi", "id"),
        "atc_name": _attr(el, "ATC-koodi"),
        "strength": _t(el, "Vahvuus"),
        "dosage_form": _attr(el, "Laakemuoto"),
        "routes": [x.get("value", "").strip() for x in el.findall("Antoreitti") if x.get("value", "").strip()],
        "ddd": _t(el, "DDD"),
        "ddd_unit": _t(el, "DDDyksikko"),
        "biological": yes(_t(el, "Biologinen")),
        "biosimilar": yes(_t(el, "Biosimilaari")),
        "narcotic": _attr(el, "Huume"),
        "additional_monitoring": yes(_t(el, "Lisaseurannassa")),
        "substitution_group": _attr(el, "Substituutioryhma", "id"),
        "packages": 0, "packages_marketed": 0, "packages_in_shortage": 0,
    })
    if auth is not None:
        r.update({
            "authorisation_type": "myyntilupa" if ma is not None else "rekisteröinti",
            "authorisation_number": _t(auth, "Lupanumero") or _t(auth, "Rekisterointinumero"),
            "eu_authorisation_number": _t(auth, "EU-lupanumero"),
            "holder": _t(auth, "Haltija"),
            "authorisation_status": _attr(auth, "Tila"),
            "procedure": _attr(auth, "Prosessi"),
            "authorisation_date": _t(auth, "Myontamispaiva"),
            "authorisation_end_date": _t(auth, "Paattymispaiva"),
            "parallel_import": yes(_t(auth, "RinnakkaisTuonti")),
        })
    return r
