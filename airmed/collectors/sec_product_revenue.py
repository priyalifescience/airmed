"""Revenue by product, as tagged in SEC EDGAR XBRL filings, for large pharma, biotech and medtech companies.

Source: U.S. Securities and Exchange Commission, EDGAR. For each company (fixed list below, by SEC CIK), the
submissions API (data.sec.gov/submissions/CIK##########.json) gives the latest periodic reports (10-K, 10-Q, 20-F,
40-F; amendments are skipped). For each report the filing index (index.json) names the XBRL instance extracted from
the inline XBRL document (*_htm.xml, or the plain instance for older filings) and the company label linkbase
(*_lab.xml). Only revenue facts that carry a product dimension are kept.

Why not the companyfacts API: data.sec.gov/api/xbrl/companyfacts holds only facts WITHOUT dimensions, so product
revenue (a revenue concept with a ProductOrServiceAxis member) is never in it. The instance documents are the only
EDGAR source that keeps the product member.

What counts as product revenue (exactly what is tagged, nothing inferred):
  concept   one of REVENUE_CONCEPTS (us-gaap or ifrs-full revenue elements)
  axis      srt/us-gaap ProductOrServiceAxis, ifrs-full ProductsAndServicesAxis, or a company-extension axis whose
            name contains "Product" (e.g. a company's own ProductAxis)
  member    the member as tagged (company-extension members such as pfe:IbranceMember, or standard members such as
            us-gaap:ProductMember, which is a revenue TYPE, not a medicine). member_label is the company's own
            label for the member from its label linkbase; empty when the filing has no label for it.
Any other dimensions on the same fact (geography, segment, reporting unit, consolidation item) are listed in
other_dimensions; `geography` repeats the geographical-axis member when there is one. A row with no geography is
usually the worldwide figure for the product (segment or reporting-unit axes only say where the company reports
it), but check other_dimensions: a consolidation-item axis, for example, can mark a partial amount.

The same period appears in several reports (a 10-Q repeats the prior-year quarter; a 10-K repeats two earlier
years). One row is kept per company, concept, dimensions, period and unit: the value from the most recently filed
report, whose accession and filing date are given. Q4 is not reported in a 10-Q; it is not derived here.

Companies that do not tag product revenue are not rows here; `coverage(raw)` lists every company and why it has
no rows (no product-dimension revenue in the latest periodic filings, foreign filer without XBRL, and so on).

Privacy: company facts only; no names of individuals are read (signatures, officers and the document text are not
downloaded).
"""

import io
import json
import re
import time
import xml.etree.ElementTree as ET

from .. import http
from ..http import fetch

KEY = "sec_product_revenue"
FIELDS = ["company", "company_slug", "cik", "concept", "axis", "member", "member_label", "geography", "other_dimensions",
          "period_start", "period_end", "period_months", "value", "unit", "decimals", "form", "filing_fiscal_year",
          "filing_fiscal_period", "accession", "filed", "filing_url"]

SEC_UA = "Priya Life Science (Airmid Eireann open data) info@priyalifescience.com"
SEC_PAUSE = 0.25          # 4 requests a second; SEC's limit is 10
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVES = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/"

# Companies already followed on priyalifescience.com (cache/company_financials.json, "groups"), by SEC CIK.
# slug -> CIK. The SEC registrant name is taken from the submissions API at collection time.
COMPANIES = {
    "abbott": "0000001800", "abbvie": "0001551152", "amgen": "0000318154", "argenx": "0001697862",
    "astrazeneca": "0000901832", "autolus": "0001730463", "baxter": "0000010456", "bicycle": "0001761612",
    "biogen": "0000875045", "biontech": "0001776985", "blco": "0001860742", "bms": "0000014272",
    "bsx": "0000885725", "crl": "0001100682", "danaher": "0000313616", "edwards": "0001099800",
    "genmab": "0001434265", "gilead": "0000882095", "grifols": "0001438569", "gsk": "0001131399",
    "haleon": "0001900304", "icon": "0001060955", "illumina": "0001110803", "indivior": "0001625297",
    "iqvia": "0001478242", "jazz": "0001232524", "jnj": "0000200406", "lilly": "0000059478",
    "livanova": "0001639691", "medtronic": "0001613103", "merck": "0000310158", "mereo": "0001719714",
    "moderna": "0001682852", "novartis": "0001114448", "novo": "0000353278", "pfizer": "0000078003",
    "qiagen": "0001015820", "regeneron": "0000872589", "sanofi": "0001121404", "silence": "0001479615",
    "snn": "0000845982", "stryker": "0000310764", "takeda": "0001395064", "teleflex": "0000096943",
    "thermo": "0000097745", "vertex": "0000875320", "viatris": "0001792044", "zoetis": "0001555280",
}

PERIODIC_FORMS = ("10-K", "10-Q", "20-F", "40-F")
MAX_FILINGS = {"10-Q": 9, "10-K": 9, "20-F": 3, "40-F": 3}   # by the company's latest periodic form
GIVE_UP_AFTER = 2          # stop reading a company's filings when the latest two have no product revenue

REVENUE_CONCEPTS = {
    "us-gaap": {"RevenueFromContractWithCustomerExcludingAssessedTax", "RevenueFromContractWithCustomerIncludingAssessedTax",
                "Revenues", "SalesRevenueNet", "SalesRevenueGoodsNet", "RevenueFromContractWithCustomerProductAndServiceExcludingAssessedTax"},
    "ifrs-full": {"Revenue", "RevenueFromContractsWithCustomers", "RevenueFromSaleOfGoods"},
}
STANDARD_PRODUCT_AXES = {"ProductOrServiceAxis", "ProductsAndServicesAxis"}

NS_PREFIX = [  # namespace URI pattern -> conventional prefix (instance prefixes vary between filings)
    (re.compile(r"^http://fasb\.org/us-gaap/"), "us-gaap"),
    (re.compile(r"^http://fasb\.org/srt/"), "srt"),
    (re.compile(r"^https?://xbrl\.ifrs\.org/taxonomy/[^/]+/ifrs-full$"), "ifrs-full"),
    (re.compile(r"^http://xbrl\.sec\.gov/dei/"), "dei"),
    (re.compile(r"^http://xbrl\.sec\.gov/country/"), "country"),
]
XBRLI = "http://www.xbrl.org/2003/instance"
XBRLDI = "http://xbrl.org/2006/xbrldi"
LINK = "http://www.xbrl.org/2003/linkbase"
XLINK = "http://www.w3.org/1999/xlink"
STANDARD_LABEL = "http://www.xbrl.org/2003/role/label"


def _prefix_for(uri: str, declared: str) -> str:
    for pat, p in NS_PREFIX:
        if pat.search(uri or ""):
            return p
    return declared


def _months(start: str, end: str) -> int:
    """Length of a duration in whole months, rounded (3, 6, 9, 12 for usual reporting periods)."""
    y1, m1, d1 = (int(x) for x in start.split("-"))
    y2, m2, d2 = (int(x) for x in end.split("-"))
    days = (y2 - y1) * 365.25 + (m2 - m1) * 30.44 + (d2 - d1) + 1
    return int(round(days / 30.44))


def _number(text: str):
    t = (text or "").strip()
    if re.fullmatch(r"-?\d+", t):
        return int(t)
    try:
        return float(t)
    except ValueError:
        return None


def _is_product_axis(qname: str) -> bool:
    prefix, _, local = qname.partition(":")
    if prefix in ("srt", "us-gaap", "ifrs-full"):
        return local in STANDARD_PRODUCT_AXES
    return local.endswith("Axis") and "product" in local.lower()   # company-extension product axis


def extract_instance(xml_bytes: bytes) -> dict:
    """Product-dimension revenue facts from one XBRL instance, with QNames normalised to conventional prefixes.

    Returns {"fy": ..., "fp": ..., "facts": [{concept, axis, member, other_dimensions, start, end, value, unit,
    decimals}], "members": [qnames needing a label]}."""

    prefixes = {}            # uri -> normalised prefix
    declared = {}            # declared prefix -> uri (last wins; instances declare each prefix once)
    for _event, (p, uri) in ET.iterparse(io.BytesIO(xml_bytes), events=("start-ns",)):
        declared[p] = uri
        prefixes[uri] = _prefix_for(uri, p)

    def norm_qname(q: str) -> str:
        p, _, local = (q or "").strip().partition(":")
        uri = declared.get(p)
        return f"{prefixes.get(uri, p)}:{local}" if local else q

    def clark_to_q(tag: str) -> str:
        if tag.startswith("{"):
            uri, local = tag[1:].split("}", 1)
            return f"{prefixes.get(uri, uri)}:{local}"
        return tag

    tree_root = ET.fromstring(xml_bytes)
    contexts = {}
    for ctx in tree_root.iter(f"{{{XBRLI}}}context"):
        period = ctx.find(f"{{{XBRLI}}}period")
        start = period.findtext(f"{{{XBRLI}}}startDate") if period is not None else None
        end = period.findtext(f"{{{XBRLI}}}endDate") if period is not None else None
        if not (start and end):
            continue   # revenue is a duration; instants are never revenue
        dims = []
        for em in ctx.iter(f"{{{XBRLDI}}}explicitMember"):
            dims.append((norm_qname(em.get("dimension")), norm_qname(em.text)))
        if any(True for _ in ctx.iter(f"{{{XBRLDI}}}typedMember")):
            dims.append(("typed", "typed"))
        contexts[ctx.get("id")] = (start.strip(), end.strip(), dims)
    units = {}
    for u in tree_root.iter(f"{{{XBRLI}}}unit"):
        measures = [norm_qname(m.text) for m in u.iter(f"{{{XBRLI}}}measure")]
        units[u.get("id")] = "/".join(measures)
    fy = fp = ""
    facts, members = [], set()
    for el in tree_root:
        q = clark_to_q(el.tag)
        if q == "dei:DocumentFiscalYearFocus":
            fy = (el.text or "").strip()
        elif q == "dei:DocumentFiscalPeriodFocus":
            fp = (el.text or "").strip()
        prefix, _, local = q.partition(":")
        if local not in REVENUE_CONCEPTS.get(prefix, ()):
            continue
        ctx = contexts.get(el.get("contextRef"))
        if not ctx:
            continue
        start, end, dims = ctx
        # The standard product axis wins; a company "product" axis (e.g. a portfolio grouping) on the same fact is
        # then just another dimension. Without a standard axis, exactly one company product axis is accepted.
        prod = [(a, m) for a, m in dims if a.partition(":")[0] in ("srt", "us-gaap", "ifrs-full") and _is_product_axis(a)]
        if not prod:
            prod = [(a, m) for a, m in dims if _is_product_axis(a)]
        if len(prod) != 1 or el.get("{http://www.w3.org/2001/XMLSchema-instance}nil") == "true":
            continue           # no product member (or two product axes of the same kind: ambiguous, skipped)
        value = _number(el.text)
        if value is None:
            continue
        axis, member = prod[0]
        other = sorted(f"{a}={m}" for a, m in dims if (a, m) != prod[0])
        facts.append({"concept": q, "axis": axis, "member": member, "other_dimensions": other, "start": start,
                      "end": end, "value": value, "unit": units.get(el.get("unitRef"), el.get("unitRef") or ""),
                      "decimals": el.get("decimals") or ""})
        members.add(member)
    return {"fy": fy, "fp": fp, "facts": facts, "members": sorted(members)}


def extract_labels(lab_bytes: bytes, wanted) -> dict:
    """{member local name: standard label} from a company label linkbase, for the wanted member QNames."""
    if not lab_bytes:
        return {}
    wanted_local = {q.partition(":")[2]: q for q in wanted}
    root = ET.fromstring(lab_bytes)
    out = {}
    for lnk in root.iter(f"{{{LINK}}}labelLink"):
        locs, labels, arcs = {}, {}, []
        for el in lnk:
            typ = el.get(f"{{{XLINK}}}type")
            lab = el.get(f"{{{XLINK}}}label")
            if typ == "locator":
                frag = el.get(f"{{{XLINK}}}href", "").partition("#")[2]
                locs[lab] = frag.split("_", 1)[1] if "_" in frag else frag
            elif typ == "resource" and el.get(f"{{{XLINK}}}role") == STANDARD_LABEL:
                labels[lab] = " ".join((el.text or "").split())
            elif typ == "arc":
                arcs.append((el.get(f"{{{XLINK}}}from"), el.get(f"{{{XLINK}}}to")))
        for frm, to in arcs:
            local = locs.get(frm)
            if local in wanted_local and to in labels:
                out[wanted_local[local]] = labels[to]
    return out


def _sec_json(url: str):
    return json.loads(fetch(url, headers={"User-Agent": SEC_UA}))


def _sec_bytes(url: str) -> bytes:
    return fetch(url, timeout=120, headers={"User-Agent": SEC_UA})


def periodic_filings(sub: dict) -> list:
    """Latest periodic reports (no amendments), newest first, from a submissions API document."""
    r = sub.get("filings", {}).get("recent", {})
    rows = [dict(zip(r.keys(), vals)) for vals in zip(*r.values())] if r else []
    rows = [x for x in rows if x.get("form") in PERIODIC_FORMS]
    rows.sort(key=lambda x: (x.get("filingDate", ""), x.get("accessionNumber", "")), reverse=True)
    if not rows:
        return []
    return rows[:MAX_FILINGS.get(rows[0]["form"], 9)]


def _filing_files(cik: str, acc: str):
    base = ARCHIVES.format(cik_int=int(cik), acc_nodash=acc.replace("-", ""))
    items = _sec_json(base + "index.json").get("directory", {}).get("item", [])
    names = [i.get("name", "") for i in items]
    inst = [n for n in names if n.endswith("_htm.xml")]
    if not inst:   # pre-inline filings: a plain instance named like abc-20201231.xml
        inst = [n for n in names if re.fullmatch(r"[a-z0-9-]+-\d{8}\.xml", n)]
    lab = [n for n in names if n.endswith("_lab.xml")]
    return base, (inst[0] if inst else ""), (lab[0] if lab else "")


def fetch_raw(companies: dict = None) -> bytes:
    """Compact JSON of product revenue facts per company and filing (instances are reduced as they are read)."""
    companies = companies or COMPANIES
    old_pause = http.PAUSE_SECONDS
    http.PAUSE_SECONDS = SEC_PAUSE
    out = []
    try:
        for slug, cik in companies.items():
            entry = {"slug": slug, "cik": cik, "name": "", "status": "", "filings": []}
            out.append(entry)
            try:
                sub = _sec_json(SUBMISSIONS.format(cik=cik))
            except Exception as e:  # one company failing must not stop the others; recorded in coverage
                entry["status"] = f"submissions API error: {e}"
                continue
            entry["name"] = sub.get("name", "")
            filings = periodic_filings(sub)
            if not filings:
                entry["status"] = "no 10-K/10-Q/20-F/40-F in recent filings"
                continue
            entry["latest_form"] = filings[0]["form"]
            empty_streak = 0
            for f in filings:
                acc = f["accessionNumber"]
                rec = {"accession": acc, "form": f["form"], "filed": f.get("filingDate", ""),
                       "report_date": f.get("reportDate", ""), "xbrl": bool(f.get("isXBRL"))}
                entry["filings"].append(rec)
                if not f.get("isXBRL"):
                    rec["status"] = "no XBRL"
                    empty_streak += 1
                else:
                    try:
                        base, inst, lab = _filing_files(cik, acc)
                        rec["filing_url"] = base
                        if not inst:
                            rec["status"] = "no XBRL instance file in filing index"
                            empty_streak += 1
                        else:
                            got = extract_instance(_sec_bytes(base + inst))
                            rec.update(fy=got["fy"], fp=got["fp"], facts=got["facts"])
                            rec["labels"] = extract_labels(_sec_bytes(base + lab), got["members"]) if (lab and got["members"]) else {}
                            rec["status"] = "ok"
                            empty_streak = 0 if got["facts"] else empty_streak + 1
                    except Exception as e:
                        rec["status"] = f"error: {e}"
                        empty_streak += 1
                if empty_streak >= GIVE_UP_AFTER and not any(x.get("facts") for x in entry["filings"]):
                    break
            has = any(x.get("facts") for x in entry["filings"])
            entry["status"] = "product revenue tagged" if has else (
                f"no product-dimension revenue in the latest {len(entry['filings'])} periodic filing(s)")
    finally:
        http.PAUSE_SECONDS = old_pause
    return json.dumps({"retrieved_unix": int(time.time()), "companies": out}, ensure_ascii=False).encode("utf-8")


def geography(other_dimensions) -> str:
    """Member of the geographical axis (srt:StatementGeographicalAxis or ifrs-full:GeographicalAreasAxis) among a fact's other dimensions, else ''."""
    for d in other_dimensions:
        axis, _, member = d.partition("=")
        if axis in ("srt:StatementGeographicalAxis", "us-gaap:StatementGeographicalAxis", "ifrs-full:GeographicalAreasAxis"):
            return member
    return ""


def parse(raw: bytes) -> list:
    data = json.loads(raw)
    best = {}
    for c in data["companies"]:
        for f in c.get("filings", []):
            labels = f.get("labels", {})
            for x in f.get("facts", []):
                key = (c["cik"], x["concept"], x["axis"], x["member"], tuple(x["other_dimensions"]), x["start"],
                       x["end"], x["unit"])
                row = {
                    "company": c.get("name", ""), "company_slug": c["slug"], "cik": c["cik"],
                    "concept": x["concept"], "axis": x["axis"], "member": x["member"],
                    "member_label": labels.get(x["member"], ""), "geography": geography(x["other_dimensions"]),
                    "other_dimensions": list(x["other_dimensions"]),
                    "period_start": x["start"], "period_end": x["end"], "period_months": _months(x["start"], x["end"]),
                    "value": x["value"], "unit": x["unit"], "decimals": x["decimals"], "form": f["form"],
                    "filing_fiscal_year": f.get("fy", ""), "filing_fiscal_period": f.get("fp", ""),
                    "accession": f["accession"], "filed": f["filed"], "filing_url": f.get("filing_url", ""),
                }
                old = best.get(key)
                if old is None or (row["filed"], row["accession"]) > (old["filed"], old["accession"]):
                    best[key] = row
    rows = list(best.values())
    rows.sort(key=lambda r: (r["company_slug"], r["member"], r["concept"], r["other_dimensions"], r["period_end"],
                             r["period_months"]))
    return rows


def coverage(raw: bytes) -> list:
    """One row per company: whether it tags product revenue, and what was read."""
    data = json.loads(raw)
    out = []
    for c in data["companies"]:
        fs = c.get("filings", [])
        members = {x["member"] for f in fs for x in f.get("facts", [])}
        out.append({"company": c.get("name", ""), "company_slug": c["slug"], "cik": c["cik"],
                    "latest_periodic_form": c.get("latest_form", ""), "filings_read": len(fs),
                    "filings_with_product_revenue": sum(1 for f in fs if f.get("facts")),
                    "product_members": len(members), "status": c.get("status", "")})
    return out
