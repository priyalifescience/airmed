"""US Medicaid State Drug Utilization Data (SDUD), CMS: national totals by NDC product and year.

Source: data.medicaid.gov (DKAN), one dataset per year ("State Drug Utilization Data YYYY"). The raw files hold one
row per state x quarter x utilisation type (fee-for-service / managed care) x 11-digit NDC package; CMS's national
rows (state "XX") alone number about 320,000 a year (2025). Airmid keeps only the national rows and sums them on the
server, per 9-digit NDC product (labeler + product code, all package sizes) per calendar year: about 25,000 rows a
year, which is what keeps the dataset under the size rule. Window: the three latest years with all four quarters
published.

Rows CMS suppresses (fewer than 11 prescriptions in a state/national quarter row) carry no amounts and add nothing;
a product whose every row is suppressed is left out. Amounts are what Medicaid reimbursed pharmacies BEFORE
manufacturer rebates, which CMS does not publish per drug, so they are not net spending.

SDUD product names are cut to 10 characters, so each NDC product is also named from the FDA National Drug Code
Directory (US government work): current listings first, then delisted/excluded products. Products the FDA files do
not know keep only CMS's short name. FDA labeler names are company names; a name that does not read as an
organisation is blanked (Airmid never publishes personal names; see _labeler_or_blank).

Count check: for each year the national totals are also asked for with one un-grouped query, and the parser refuses
the year if the product rows do not add up to them exactly.
"""

import io
import json
import re
import time
import zipfile
from decimal import Decimal

from ..http import fetch
from .ctgov_ireland import sponsor_or_blank

KEY = "medicaid_drug_spending"
FIELDS = ["year", "ndc_product", "labeler_code", "product_code", "cms_product_name", "fda_proprietary_name",
          "fda_nonproprietary_name", "fda_substance_name", "fda_labeler_name", "fda_name_source",
          "number_of_prescriptions", "units_reimbursed", "total_amount_reimbursed_usd", "medicaid_amount_reimbursed_usd"]
SEARCH = "https://data.medicaid.gov/api/1/search?fulltext=State%20Drug%20Utilization%20Data&page-size=100"
QUERY = "https://data.medicaid.gov/api/1/datastore/query/{id}/0"
FDA_FILES = [("current", "https://www.accessdata.fda.gov/cder/ndctext.zip", "product.txt"),
             ("excluded", "https://www.accessdata.fda.gov/cder/ndc_excluded.zip", "Products_excluded.txt")]
YEARS = 3
PAGE = 5000
MIN_PRODUCTS = 5000     # a real year has ~30,000 products with data; fewer means a broken reply
EXTRA_PAUSE = 0.5
NATIONAL = [{"property": "state", "value": "XX", "operator": "="}]
SUMS = {"rx": "number_of_prescriptions", "units": "units_reimbursed", "tot": "total_amount_reimbursed",
        "mcd": "medicaid_amount_reimbursed"}


def _sum(alias, col):
    return {"alias": alias, "expression": {"operator": "sum", "operands": [col]}}


def _query(dataset_id: str, q: dict) -> list:
    time.sleep(EXTRA_PAUSE)
    body = {"count": False, "schema": False, "keys": True, **q}
    j = json.loads(fetch(QUERY.format(id=dataset_id), timeout=240, data=json.dumps(body).encode("utf-8"),
                         headers={"Content-Type": "application/json"}))
    if not isinstance(j.get("results"), list):
        raise RuntimeError(f"SDUD query on {dataset_id} returned no results list")
    return j["results"]


def sdud_years() -> dict:
    """{year: dataset id} for every yearly SDUD dataset, newest first."""
    j = json.loads(fetch(SEARCH, timeout=90))
    res = j.get("results", {})
    out = {}
    for d in (res.values() if isinstance(res, dict) else res):
        m = re.fullmatch(r"State Drug Utilization Data (\d{4})", str(d.get("title", "")).strip())
        if m and d.get("identifier"):
            out[int(m.group(1))] = str(d["identifier"])
    return dict(sorted(out.items(), reverse=True))


def _complete_years(years: dict) -> list:
    picked = []
    for y, ds in years.items():
        quarters = _query(ds, {"properties": ["quarter"], "groupings": ["quarter"], "conditions": NATIONAL, "limit": 10})
        if len(quarters) == 4:
            picked.append(y)
        if len(picked) == YEARS:
            break
    if len(picked) < YEARS:
        raise RuntimeError(f"only {len(picked)} complete SDUD years found")
    return picked


def _products(ds: str) -> list:
    rows = []
    for offset in range(0, 400000, PAGE):
        page = _query(ds, {
            "properties": ["labeler_code", "product_code", *[_sum(a, c) for a, c in SUMS.items()],
                           {"alias": "nm", "expression": {"operator": "max", "operands": ["product_name"]}}],
            "groupings": ["labeler_code", "product_code"], "conditions": NATIONAL,
            "sorts": [{"property": "labeler_code", "order": "asc"}, {"property": "product_code", "order": "asc"}],
            "limit": PAGE, "offset": offset})
        rows.extend(page)
        if len(page) < PAGE:
            return rows
    raise RuntimeError(f"SDUD {ds}: more products than expected; refusing a partial year")


def _decode(b: bytes) -> str:
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:          # a few FDA labeler names are Windows-1252 ("Domp\xe9")
        return b.decode("cp1252", errors="replace")


def _fda_names(want: set) -> dict:
    """{'LLLLLPPPP': [proprietary, nonproprietary, substance, labeler, source]} for the wanted product keys."""
    found = {}
    for source, url, member in FDA_FILES:
        with zipfile.ZipFile(io.BytesIO(fetch(url, timeout=300))) as z, z.open(member) as fh:
            head = _decode(fh.readline()).rstrip("\r\n").split("\t")
            ix = {h.strip(): i for i, h in enumerate(head)}
            need = ("PRODUCTNDC", "PROPRIETARYNAME", "NONPROPRIETARYNAME", "SUBSTANCENAME", "LABELERNAME")
            if any(n not in ix for n in need):
                raise RuntimeError(f"FDA {member}: unexpected columns")
            for line in fh:
                r = _decode(line).rstrip("\r\n").split("\t")
                p = r[ix["PRODUCTNDC"]].split("-") if len(r) > ix["PRODUCTNDC"] else []
                if len(p) != 2:
                    continue
                k = p[0].zfill(5) + p[1].zfill(4)
                if k not in want:
                    continue
                rec = [r[ix[n]].strip() if len(r) > ix[n] else "" for n in need[1:]] + [source]
                # a current listing wins; a delisted record only fills a gap or a missing substance
                if k not in found or (not found[k][2] and rec[2]):
                    found[k] = rec
    return found


def fetch_raw() -> bytes:
    """About 8 SDUD queries per year plus two FDA zip files (~42 MB, filtered to the products seen)."""
    years = sdud_years()
    out = {}
    for y in sorted(_complete_years(years)):
        ds = years[y]
        totals = _query(ds, {"properties": [_sum(a, c) for a, c in SUMS.items()], "conditions": NATIONAL, "limit": 1})
        out[str(y)] = {"dataset_id": ds, "totals": totals[0] if totals else {}, "products": _products(ds)}
    want = {r["labeler_code"].zfill(5) + r["product_code"].zfill(4) for yr in out.values() for r in yr["products"]}
    return json.dumps({"years": out, "fda": _fda_names(want)}).encode("utf-8")


# FDA labelers are registered firms, but Airmid still never risks printing a person's name. A labeler name is kept when
# ctgov_ireland.sponsor_or_blank reads it as an organisation, when it carries a company word that list lacks
# ("Incorporated", "LP", "USA", "Packaging" ...), when it is a single word (not a full personal name), or when the FDA
# files list it on at least LABELER_MIN_PRODUCTS of the products seen (Novo Nordisk, McKesson ...). Anything else is
# blanked: in the 2023-2025 run that blanked 9 of 1,625 names, all of them companies (accepted cost).
LABELER_WORDS = re.compile(r"incorporat|\bl\.?\s?l\.?\s?c\b|\bl\.?p\.?\b|\bcorp|&|\busa?\b|\bu\.s\.|generic|specialt|"
                           r"packag|\brx|pharm|phama|phara|marketing|drug|\bdba\b|products|disease|dermatolog|labor|"
                           r"\bassn\b|\bassoc", re.I)
LABELER_MIN_PRODUCTS = 5


def _labeler_or_blank(name: str, products_listed: int) -> str:
    name = (name or "").strip()
    if not name:
        return ""
    if (sponsor_or_blank(name, "") or LABELER_WORDS.search(name) or len(name.split()) == 1
            or products_listed >= LABELER_MIN_PRODUCTS):
        return name
    return ""


def _dec(v) -> Decimal:
    return Decimal(str(v)) if v not in (None, "") else Decimal(0)


def _num(d: Decimal, places: int):
    q = d.quantize(Decimal(1).scaleb(-places))
    return int(q) if q == q.to_integral_value() else float(q)


def parse(raw: bytes, min_products: int = MIN_PRODUCTS) -> list:
    data = json.loads(raw)
    fda = data.get("fda", {})
    per_labeler = {}
    for v in fda.values():
        per_labeler[v[3]] = per_labeler.get(v[3], 0) + 1
    years = data.get("years", {})
    if not years:
        raise RuntimeError("no SDUD years in the download")
    out = []
    for year, yr in sorted(years.items()):
        prods, tot = yr.get("products", []), yr.get("totals", {})
        sums = {a: sum((_dec(p.get(a)) for p in prods), Decimal(0)) for a in SUMS}
        for a in SUMS:
            if sums[a] != _dec(tot.get(a)):
                raise RuntimeError(f"SDUD {year}: product rows {a}={sums[a]} do not match national total {tot.get(a)}")
        kept = 0
        for p in prods:
            if all(p.get(a) is None for a in SUMS):
                continue            # every national row for this product was suppressed (< 11 prescriptions)
            lab, prod = str(p["labeler_code"]).zfill(5), str(p["product_code"]).zfill(4)
            names = fda.get(lab + prod) or ["", "", "", "", ""]
            out.append({
                "year": int(year),
                "ndc_product": f"{lab}-{prod}",
                "labeler_code": lab,
                "product_code": prod,
                "cms_product_name": str(p.get("nm") or "").strip(),
                "fda_proprietary_name": names[0],
                "fda_nonproprietary_name": names[1],
                "fda_substance_name": names[2],
                "fda_labeler_name": _labeler_or_blank(names[3], per_labeler.get(names[3], 0)),
                "fda_name_source": names[4],
                "number_of_prescriptions": _num(_dec(p.get("rx")), 0),
                "units_reimbursed": _num(_dec(p.get("units")), 3),
                "total_amount_reimbursed_usd": _num(_dec(p.get("tot")), 2),
                "medicaid_amount_reimbursed_usd": _num(_dec(p.get("mcd")), 2),
            })
            kept += 1
        if kept < min_products:
            raise RuntimeError(f"SDUD {year}: only {kept} products with data")
    out.sort(key=lambda r: (r["year"], r["ndc_product"]))
    return out
