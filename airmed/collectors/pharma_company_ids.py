"""Pharma, biotech and medtech COMPANIES relevant to Ireland: a crosswalk of open identifiers
(Wikidata QID, LEI, Irish CRO company number), for legal entities only (never persons).

Sources (all keyless):
  Wikidata (CC0)  query.wikidata.org/sparql. Sector = instance (or subclass) of pharmaceutical company Q19644607,
                  biotechnology company Q90298876, biopharmaceutical company Q131784011, medical device company
                  Q63383584, contract research organisation Q760102, contract manufacturing organisation Q5165673,
                  or "pharmaceutical industry" Q507443 used as a class; OR industry (P452) = pharmaceutical industry
                  Q507443, biotechnology industry Q12303494, biotechnology Q7108, medical technology Q1519843,
                  pharmaceutical manufacturing Q7180757, medical technology industry Q63383285.
                  Irish link (any of): country (P17) Ireland; headquarters (P159) in Ireland; an item in Ireland has
                  the company as parent (P749), owner (P127) or operator (P137) (an Irish subsidiary or facility);
                  the company is itself an organisation in Ireland whose parent/owner/operator is a sector company;
                  or the company's LEI (P1278) has legal jurisdiction IE in GLEIF.
  GLEIF (CC0)     api.gleif.org lei-records: legal name, jurisdiction, entity and registration status, legal-address
                  CITY and COUNTRY only (street lines are dropped inside fetch_raw), registration authority id and
                  number, direct and ultimate parent LEI. Also: entities with legal jurisdiction IE that GLEIF lists
                  as ultimate children of a Wikidata company's LEI (record_basis "gleif_irish_group_entity").
                  Sole proprietors (GLEIF category SOLE_PROPRIETOR) are dropped: Airmid never lists persons.
  CRO (CC BY 4.0) opendata.cro.ie "Company Records" (daily snapshot, CKAN datastore API). Only company number,
                  name, status, type and registration date are requested: never addresses, Eircodes, directors or
                  secretaries.

CRO matching (cro_match_method), first rule that applies wins; matches are by identifier or exact name only:
  gleif_registered_as   GLEIF says the entity is registered at RA000402 (Companies Registration Office, Ireland)
                        as number N, and N exists in CRO open data
  wikidata_P9679        Wikidata "Companies Registration Office (Ireland) Registration Number" N exists in CRO data
  wikidata_opencorporates_ie  Wikidata OpenCorporates ID is "ie/N" and N exists in CRO data
  exact_name_gleif      GLEIF legal name (jurisdiction IE only) equals exactly ONE CRO company name after
                        normalisation (below)
  exact_name_wikidata_P1448   Wikidata official name (P1448) of an item with country/HQ Ireland (or an
                        organisation in Ireland of a sector company) equals exactly ONE CRO name after normalisation
  exact_name_wikidata_label   same, using the English label, and only when the label ends in an Irish legal form
                        (LIMITED, PUBLIC LIMITED COMPANY, DESIGNATED ACTIVITY COMPANY, UNLIMITED COMPANY, COMPANY
                        LIMITED BY GUARANTEE, or their abbreviations), e.g. "ICON plc"
LEI for a Wikidata item that has none on Wikidata (lei_source gleif_by_cro_number): the GLEIF records registered at
RA000402 under the matched CRO number (already fetched, or asked from GLEIF by registration number with jurisdiction
IE); used only when exactly one such record exists.
Normalisation: upper case; "&" -> "AND"; punctuation removed; whitespace collapsed; a trailing legal-form
abbreviation is expanded (LTD -> LIMITED, PLC -> PUBLIC LIMITED COMPANY, DAC -> DESIGNATED ACTIVITY COMPANY,
UC -> UNLIMITED COMPANY, CLG -> COMPANY LIMITED BY GUARANTEE). No fuzzy or partial matching; a name that matches
two or more CRO companies is left unmatched.
"""

import json
import re
import urllib.parse

from ..http import fetch

KEY = "pharma_company_ids"
FIELDS = ["record_basis", "wikidata_qid", "label", "irish_link", "sector_basis", "via_wikidata_qid", "hq_country",
          "website", "parent_qids", "parent_labels", "inception_year", "stock_listings", "opencorporates_id",
          "lei", "lei_source", "gleif_legal_name", "gleif_jurisdiction", "gleif_entity_status", "gleif_registration_status",
          "gleif_legal_city", "gleif_legal_country", "gleif_registered_at", "gleif_registered_as",
          "gleif_direct_parent_lei", "gleif_ultimate_parent_lei", "wikidata_cro_number", "cro_company_number",
          "cro_company_name", "cro_company_status", "cro_company_type", "cro_registration_date", "cro_match_method"]

SPARQL = "https://query.wikidata.org/sparql"
GLEIF = "https://api.gleif.org/api/v1/lei-records"
CRO = "https://opendata.cro.ie/api/3/action/datastore_search"
CRO_RESOURCE = "3fef41bc-b8f4-4b10-8434-ce51c29b1bba"
CRO_FIELDS = "company_num,company_name,company_status,company_type,company_reg_date"   # never address/eircode
CRO_RA = "RA000402"   # GLEIF registration-authority code of the Companies Registration Office, Ireland

CLASSES = ("Q19644607", "Q90298876", "Q131784011", "Q63383584", "Q760102", "Q5165673", "Q507443")
INDUSTRIES = ("Q507443", "Q12303494", "Q7108", "Q1519843", "Q7180757", "Q63383285")

def _sector(var: str, basis: str) -> str:
    """SPARQL pattern: `var` is a sector company; `basis` is bound to the matching class or industry."""
    return ("{ VALUES %(b)s { %(cls)s } %(v)s wdt:P31/wdt:P279* %(b)s } "
            "UNION { VALUES %(b)s { %(ind)s } %(v)s wdt:P452 %(b)s } "
            "FILTER NOT EXISTS { %(v)s wdt:P31 wd:Q5 }") % {
        "v": var, "b": basis, "cls": " ".join("wd:" + q for q in CLASSES), "ind": " ".join("wd:" + q for q in INDUSTRIES)}


# Three candidate queries (kept separate so each stays well inside the query service's 60 s limit).
# Each returns ?c = company, ?why = Irish link, ?b = sector class/industry (or, for organisations in Ireland,
# the sector company that is their parent, owner or operator).
Q_CANDIDATES = [
    """SELECT DISTINCT ?c ?why ?b WHERE { %s
   { ?c wdt:P17 wd:Q27 BIND("country_ireland" AS ?why) }
   UNION { ?c wdt:P159/wdt:P17 wd:Q27 BIND("hq_in_ireland" AS ?why) }
   UNION { ?f wdt:P749|wdt:P127|wdt:P137 ?c. ?f wdt:P17 wd:Q27. BIND("irish_subsidiary_or_facility" AS ?why) } }"""
    % _sector("?c", "?b"),
    """SELECT DISTINCT ?c ?why ?b WHERE { %s ?c wdt:P1278 [] BIND("lei_candidate" AS ?why) }""" % _sector("?c", "?b"),
    """SELECT DISTINCT ?c ?why ?b WHERE { ?c wdt:P749|wdt:P127|wdt:P137 ?b. ?c wdt:P17 wd:Q27. %s
   ?c wdt:P31/wdt:P279* wd:Q43229. FILTER NOT EXISTS { ?c wdt:P31 wd:Q5 }
   BIND("organisation_in_ireland_of_sector_company" AS ?why) }""" % _sector("?b", "?k"),
]

# property queries, run on the final QID set (VALUES inserted at %s)
Q_PROPS = {
    "label": "SELECT ?c ?v WHERE { VALUES ?c { %s } ?c rdfs:label ?v FILTER(lang(?v)='en') }",
    "lei": "SELECT ?c ?v WHERE { VALUES ?c { %s } ?c wdt:P1278 ?v }",
    "hq_country": "SELECT ?c ?v WHERE { VALUES ?c { %s } ?c wdt:P159/wdt:P17 ?k. ?k rdfs:label ?v FILTER(lang(?v)='en') }",
    "country": "SELECT ?c ?v WHERE { VALUES ?c { %s } ?c wdt:P17 ?k. ?k rdfs:label ?v FILTER(lang(?v)='en') }",
    "website": "SELECT ?c ?v WHERE { VALUES ?c { %s } ?c wdt:P856 ?v }",
    "parent": "SELECT ?c ?v ?l WHERE { VALUES ?c { %s } ?c wdt:P749 ?v. OPTIONAL { ?v rdfs:label ?l FILTER(lang(?l)='en') } }",
    "inception": "SELECT ?c ?v WHERE { VALUES ?c { %s } ?c wdt:P571 ?v }",
    "opencorporates": "SELECT ?c ?v WHERE { VALUES ?c { %s } ?c wdt:P1320 ?v }",
    "cro": "SELECT ?c ?v WHERE { VALUES ?c { %s } ?c wdt:P9679 ?v }",
    "legal_name": "SELECT ?c ?v WHERE { VALUES ?c { %s } ?c wdt:P1448 ?v }",
    "listing": ("SELECT ?c ?v ?l WHERE { VALUES ?c { %s } ?c p:P414 ?st. ?st ps:P414 ?x; wikibase:rank ?r. "
                "FILTER(?r != wikibase:DeprecatedRank) FILTER NOT EXISTS { ?st pq:P582 [] } "
                "?x rdfs:label ?l FILTER(lang(?l)='en') OPTIONAL { ?st pq:P249 ?v } }"),
    "sector_label": "SELECT ?c ?v WHERE { VALUES ?c { %s } ?c rdfs:label ?v FILTER(lang(?v)='en') }",
}

GLEIF_PAGE = 100
LEGAL_FORMS = {"LTD": "LIMITED", "PLC": "PUBLIC LIMITED COMPANY", "DAC": "DESIGNATED ACTIVITY COMPANY",
               "UC": "UNLIMITED COMPANY", "CLG": "COMPANY LIMITED BY GUARANTEE"}


# ---------- fetching ----------

def _sparql(query: str) -> list:
    body = urllib.parse.urlencode({"query": query}).encode("utf-8")
    data = json.loads(fetch(SPARQL, timeout=120, data=body, headers={
        "Accept": "application/sparql-results+json", "Content-Type": "application/x-www-form-urlencoded"}))
    out = []
    for b in data["results"]["bindings"]:
        out.append({k: v["value"].replace("http://www.wikidata.org/entity/", "") for k, v in b.items()})
    return out


def _gleif_json(url: str) -> dict:
    return json.loads(fetch(url, headers={"Accept": "application/vnd.api+json"}))


def _slim_gleif(rec: dict) -> dict:
    """Keep only what Airmid uses. Street lines, postcodes and HQ addresses never leave this function."""
    a = rec.get("attributes") or {}
    e, reg = a.get("entity") or {}, a.get("registration") or {}
    la = e.get("legalAddress") or {}
    links = {k: sorted((rec.get("relationships") or {}).get(k, {}).get("links", {}))
             for k in ("direct-parent", "ultimate-parent")}
    return {"lei": rec.get("id") or a.get("lei") or "", "legal_name": (e.get("legalName") or {}).get("name") or "",
            "jurisdiction": e.get("jurisdiction") or "", "category": e.get("category") or "",
            "entity_status": e.get("status") or "", "registration_status": reg.get("status") or "",
            "city": la.get("city") or "", "country": la.get("country") or "",
            "registered_at": (e.get("registeredAt") or {}).get("id") or "", "registered_as": e.get("registeredAs") or "",
            "has_direct_parent": "lei-record" in links["direct-parent"],
            "has_ultimate_parent": "lei-record" in links["ultimate-parent"]}


def _gleif_paged(url: str, params: dict) -> list:
    """All pages of a GLEIF list endpoint; the number of records must equal GLEIF's stated total."""
    recs, page, total = [], 1, None
    while True:
        q = dict(params, **{"page[size]": str(GLEIF_PAGE), "page[number]": str(page)})
        d = _gleif_json(url + "?" + urllib.parse.urlencode(q))
        pg = d.get("meta", {}).get("pagination", {})
        total = pg.get("total", 0) if total is None else total
        recs.extend(_slim_gleif(r) for r in d.get("data", []))
        if page >= (pg.get("lastPage") or 1):
            break
        page += 1
    if len(recs) != total:
        raise RuntimeError(f"GLEIF {url} returned {len(recs)} of {total} records")
    return recs


def _cro(params: dict) -> list:
    q = dict(params, resource_id=CRO_RESOURCE, fields=CRO_FIELDS)
    d = json.loads(fetch(CRO + "?" + urllib.parse.urlencode(q)))
    if not d.get("success"):
        raise RuntimeError("CRO datastore query failed")
    return d["result"]["records"]


def _values(qids) -> str:
    return " ".join("wd:" + q for q in sorted(qids))


def _cro_num_from_gleif(rec: dict) -> str:
    """CRO company number from a GLEIF record registered at the Irish CRO, else ''."""
    n = (rec.get("registered_as") or "").strip()
    return str(int(n)) if rec.get("registered_at") == CRO_RA and n.isdigit() else ""


def _cro_num_from_wd(value: str, oc: bool = False) -> str:
    """CRO number from Wikidata P9679 ('490938') or an OpenCorporates ID ('ie/490938'), else ''."""
    v = (value or "").strip().lower()
    if oc:
        m = re.fullmatch(r"ie/(\d+)", v)
        return str(int(m.group(1))) if m else ""
    return str(int(v)) if v.isdigit() else ""


IRISH_LINKS = {"country_ireland", "hq_in_ireland", "organisation_in_ireland_of_sector_company"}
NAME_FORMS = tuple(" " + f for f in LEGAL_FORMS.values())


def _wd_names(cands: list, props: dict) -> dict:
    """Names usable for exact CRO matching, only for items with country/HQ in Ireland: the Wikidata official name
    (P1448), and the English label when it ends in an Irish legal form (e.g. 'ICON plc')."""
    irish = {c["c"] for c in cands if c["why"] in IRISH_LINKS}
    out = {}
    for r in props.get("legal_name", []):
        if r["c"] in irish:
            out.setdefault(r["c"], set()).add(("P1448", r["v"]))
    for r in props.get("label", []):
        if r["c"] in irish and norm_name(r["v"]).endswith(NAME_FORMS):
            out.setdefault(r["c"], set()).add(("label", r["v"]))
    return {q: sorted(v) for q, v in out.items()}


def fetch_raw() -> bytes:
    # 1. Wikidata candidates and their properties
    cands = [row for q in Q_CANDIDATES for row in _sparql(q)]
    qids = sorted({c["c"] for c in cands}, key=lambda q: int(q[1:]))
    props = {}
    for name, tmpl in Q_PROPS.items():
        ids = sorted({c["b"] for c in cands}) if name == "sector_label" else qids
        rows = []
        for i in range(0, len(ids), 400):
            rows.extend(_sparql(tmpl % _values(ids[i:i + 400])))
        props[name] = rows

    # 2. GLEIF records for every LEI on those items (batched), then Irish-jurisdiction group entities of each LEI
    leis = sorted({r["v"].strip().upper() for r in props["lei"] if r["v"].strip()})
    gleif = {}
    for i in range(0, len(leis), GLEIF_PAGE):
        for r in _gleif_paged(GLEIF, {"filter[lei]": ",".join(leis[i:i + GLEIF_PAGE])}):
            gleif[r["lei"]] = r
    # group entities only for companies with a real Irish link (not bare LEI candidates outside Ireland)
    linked = {c["c"] for c in cands if c["why"] != "lei_candidate"}
    group_of = {}
    for r in props["lei"]:
        lei = r["v"].strip().upper()
        if lei in gleif and (r["c"] in linked or gleif[lei]["jurisdiction"] == "IE"):
            group_of.setdefault(lei, set()).add(r["c"])
    children = {}
    for lei in sorted(group_of):
        kids = _gleif_paged(f"{GLEIF}/{lei}/ultimate-children", {})
        children[lei] = [k for k in kids if k["jurisdiction"] == "IE"]

    keep = dict(gleif)
    for kids in children.values():
        for k in kids:
            keep.setdefault(k["lei"], k)

    # 3. CRO: verify identifier matches (batched by number) ...
    nums = set()
    for rec in keep.values():
        if _cro_num_from_gleif(rec):
            nums.add(int(_cro_num_from_gleif(rec)))
    for r in props["cro"] + props["opencorporates"]:
        n = _cro_num_from_wd(r["v"], oc=r in props["opencorporates"])
        if n:
            nums.add(int(n))
    cro_by_num = {}
    nums = sorted(nums)
    for i in range(0, len(nums), 200):
        for rec in _cro({"filters": json.dumps({"company_num": nums[i:i + 200]}), "limit": "1000"}):
            cro_by_num[str(rec["company_num"])] = rec
    # ... and search exact-name candidates, only where no identifier match exists
    names = set()
    for rec in keep.values():
        n = _cro_num_from_gleif(rec)
        if rec["jurisdiction"] == "IE" and rec["legal_name"] and not (n and n in cro_by_num):
            names.add(rec["legal_name"])
    wd_ids = {}
    for r in props["cro"] + props["opencorporates"]:
        n = _cro_num_from_wd(r["v"], oc=r in props["opencorporates"])
        if n and n in cro_by_num:
            wd_ids.setdefault(r["c"], n)
    for r in props["lei"]:
        n = _cro_num_from_gleif(keep.get(r["v"].strip().upper()) or {})
        if n and n in cro_by_num:
            wd_ids.setdefault(r["c"], n)
    wd_names = _wd_names(cands, props)
    for qid, lst in wd_names.items():
        if qid not in wd_ids:
            names.update(name for _, name in lst)
    cro_by_name = {}
    for name in sorted(names):
        cro_by_name[name] = _cro({"q": name, "limit": "100"})

    # 4. GLEIF records registered at the CRO under a matched number that we do not hold yet (LEI by CRO number)
    have = {_cro_num_from_gleif(r) for r in keep.values()} - {""}
    found = set(cro_by_num)
    for name in names:
        rec = _exact_one(name, cro_by_name)
        if rec:
            found.add(str(rec["company_num"]))
    gleif_by_cro = {}
    for n in sorted(found - have, key=int):
        recs = _gleif_paged(GLEIF, {"filter[entity.registeredAs]": n, "filter[entity.jurisdiction]": "IE"})
        recs = [r for r in recs if _cro_num_from_gleif(r) == n]
        gleif_by_cro[n] = recs
        for r in recs:
            keep.setdefault(r["lei"], r)

    # 5. direct and ultimate parent LEI for every GLEIF record we keep
    parents = {}
    for lei in sorted(keep):
        rec, par = keep[lei], {}
        for rel, flag in (("direct-parent", "has_direct_parent"), ("ultimate-parent", "has_ultimate_parent")):
            if rec.get(flag):
                d = _gleif_json(f"{GLEIF}/{lei}/{rel}")
                par[rel] = (d.get("data") or {}).get("id", "")
        if par:
            parents[lei] = par

    raw = {"wikidata": {"candidates": cands, "props": props},
           "gleif": {"records": gleif, "children": children, "by_cro_number": gleif_by_cro, "parents": parents},
           "cro": {"by_number": cro_by_num, "name_search": cro_by_name},
           "counts": {"wikidata_items": len(qids), "leis": len(leis), "gleif_records": len(gleif)}}
    return json.dumps(raw, ensure_ascii=False, sort_keys=True).encode("utf-8")


# ---------- parsing ----------

def norm_name(name: str) -> str:
    s = (name or "").upper().replace("&", " AND ")
    s = re.sub(r"[^\w\s]", " ", s)
    toks = s.split()
    if toks and toks[-1] in LEGAL_FORMS:
        toks[-1] = LEGAL_FORMS[toks[-1]]
    return " ".join(toks)


def _cro_cols(rec: dict, method: str) -> dict:
    if not rec:
        return {"cro_company_number": "", "cro_company_name": "", "cro_company_status": "", "cro_company_type": "",
                "cro_registration_date": "", "cro_match_method": ""}
    return {"cro_company_number": str(rec.get("company_num", "")),
            "cro_company_name": " ".join((rec.get("company_name") or "").split()),
            "cro_company_status": (rec.get("company_status") or "").strip(),
            "cro_company_type": (rec.get("company_type") or "").strip(),
            "cro_registration_date": (rec.get("company_reg_date") or "")[:10],
            "cro_match_method": method}


def _exact_one(name: str, search: dict):
    """The single CRO record whose normalised name equals the normalised `name`, else None (0 or 2+ hits)."""
    target = norm_name(name)
    hits = {str(r["company_num"]): r for r in search.get(name, []) if norm_name(r.get("company_name")) == target}
    return next(iter(hits.values())) if len(hits) == 1 else None


def _match_cro(g: dict, wd_cro: list, wd_oc: list, wd_names: list, cro: dict):
    """(CRO record, method) by the first rule that applies (see module docstring), else (None, '')."""
    by_num, search = cro["by_number"], cro["name_search"]
    n = _cro_num_from_gleif(g or {})
    if n in by_num:
        return by_num[n], "gleif_registered_as"
    for v in wd_cro:
        n = _cro_num_from_wd(v)
        if n in by_num:
            return by_num[n], "wikidata_P9679"
    for v in wd_oc:
        n = _cro_num_from_wd(v, oc=True)
        if n in by_num:
            return by_num[n], "wikidata_opencorporates_ie"
    if g and g.get("jurisdiction") == "IE" and g.get("legal_name"):
        rec = _exact_one(g["legal_name"], search)
        if rec:
            return rec, "exact_name_gleif"
    for kind, name in wd_names:
        rec = _exact_one(name, search)
        if rec:
            return rec, "exact_name_wikidata_" + kind
    return None, ""


def _gleif_cols(g: dict, parents: dict) -> dict:
    g = g or {}
    p = parents.get(g.get("lei", ""), {})
    return {"gleif_legal_name": g.get("legal_name", ""), "gleif_jurisdiction": g.get("jurisdiction", ""),
            "gleif_entity_status": g.get("entity_status", ""), "gleif_registration_status": g.get("registration_status", ""),
            "gleif_legal_city": g.get("city", ""), "gleif_legal_country": g.get("country", ""),
            "gleif_registered_at": g.get("registered_at", ""), "gleif_registered_as": g.get("registered_as", ""),
            "gleif_direct_parent_lei": p.get("direct-parent", ""), "gleif_ultimate_parent_lei": p.get("ultimate-parent", "")}


def _qnum(q: str) -> int:
    return int(q[1:]) if q and q[1:].isdigit() else 0


def _usable(g):
    """The GLEIF record, unless it is a sole proprietor (a person): Airmid never lists persons."""
    return g if g and g.get("category") != "SOLE_PROPRIETOR" else None


def parse(raw: bytes) -> list:
    data = json.loads(raw)
    wd, gl, cro = data["wikidata"], data["gleif"], data["cro"]
    props, records, parents = wd["props"], gl["records"], gl.get("parents", {})
    # every GLEIF record we hold, indexed by the CRO number it is registered under (RA000402 only)
    by_cro = {}
    pool = list(records.values()) + [k for lst in gl.get("children", {}).values() for k in lst]
    pool += [r for lst in gl.get("by_cro_number", {}).values() for r in lst]
    for r in pool:
        n = _cro_num_from_gleif(r)
        if n and _usable(r):
            by_cro.setdefault(n, {})[r["lei"]] = r
    counts = data.get("counts", {})
    if counts.get("gleif_records") is not None and counts["gleif_records"] != len(records):
        raise RuntimeError(f"raw file says {counts['gleif_records']} GLEIF records but holds {len(records)}")

    P = {n: {} for n in Q_PROPS}
    for name in Q_PROPS:
        for r in props.get(name, []):
            P[name].setdefault(r["c"], []).append(r)
    sector_label = {r["c"]: r["v"] for r in props.get("sector_label", [])}
    label = {r["c"]: r["v"] for r in props.get("label", [])}
    names_for = _wd_names(wd["candidates"], props)

    why, basis = {}, {}
    for c in wd["candidates"]:
        why.setdefault(c["c"], set()).add(c["why"])
        b = sector_label.get(c["b"], c["b"])
        basis.setdefault(c["c"], set()).add(
            ("subsidiary of " + b) if c["why"] == "organisation_in_ireland_of_sector_company" else b)

    out, seen_leis = [], set()
    for qid in sorted(why, key=_qnum):
        leis = sorted({r["v"].strip().upper() for r in P["lei"].get(qid, []) if r["v"].strip()}) or [""]
        links = set(why[qid])
        if any(records.get(lei, {}).get("jurisdiction") == "IE" for lei in leis):
            links.add("lei_jurisdiction_ie")
        links.discard("lei_candidate")
        if not links:
            continue   # a sector company with an LEI but no Irish link
        incept = sorted(r["v"][:4] for r in P["inception"].get(qid, []) if re.match(r"\d{4}-", r["v"]))
        listings = sorted({f"{r['l']}:{r.get('v', '')}".rstrip(":") for r in P["listing"].get(qid, [])})
        parents_wd = sorted({(r["v"], r.get("l", "")) for r in P["parent"].get(qid, [])}, key=lambda t: _qnum(t[0]))
        wd_cro = sorted({r["v"].strip() for r in P["cro"].get(qid, [])})
        wd_oc = sorted({r["v"].strip() for r in P["opencorporates"].get(qid, [])})
        for lei in leis:
            g = _usable(records.get(lei)) if lei else None
            rec, method = _match_cro(g, wd_cro, wd_oc, names_for.get(qid, []), cro)
            lei_source = "wikidata_P1278" if lei else ""
            if not lei and rec:
                found = list(by_cro.get(str(rec["company_num"]), {}).values())
                if len(found) == 1:   # exactly one LEI registered at the CRO under this number
                    g, lei, lei_source = found[0], found[0]["lei"], "gleif_by_cro_number"
            row = {"record_basis": "wikidata", "wikidata_qid": qid, "label": label.get(qid, ""),
                   "irish_link": sorted(links), "sector_basis": sorted(basis[qid]), "via_wikidata_qid": "",
                   "hq_country": sorted({r["v"] for r in P["hq_country"].get(qid, [])}),
                   "website": sorted({r["v"] for r in P["website"].get(qid, [])}),
                   "parent_qids": [p[0] for p in parents_wd], "parent_labels": [p[1] for p in parents_wd],
                   "inception_year": incept[0] if incept else "", "stock_listings": listings,
                   "opencorporates_id": wd_oc, "lei": lei, "lei_source": lei_source}
            row.update(_gleif_cols(g, parents))
            row["wikidata_cro_number"] = "; ".join(wd_cro)
            row.update(_cro_cols(rec, method))
            out.append(row)
            if lei:
                seen_leis.add(lei)

    # Irish-jurisdiction group entities found through GLEIF relationships of a Wikidata company's LEI
    lei_owner = {}
    for r in props.get("lei", []):
        lei_owner.setdefault(r["v"].strip().upper(), set()).add(r["c"])
    kids = {}
    for parent_lei, lst in gl.get("children", {}).items():
        for k in lst:
            kids.setdefault(k["lei"], (k, set()))[1].update(q for q in lei_owner.get(parent_lei, ()) if q in why)
    for lei in sorted(kids):
        k, via = kids[lei]
        if lei in seen_leis or k.get("jurisdiction") != "IE" or not _usable(k) or not via:
            continue
        rec, method = _match_cro(k, [], [], [], cro)
        row = {"record_basis": "gleif_irish_group_entity", "wikidata_qid": "", "label": "",
               "irish_link": ["lei_jurisdiction_ie"],
               "sector_basis": sorted({f"group of {label.get(q, q)}" for q in via}),
               "via_wikidata_qid": "; ".join(sorted(via, key=_qnum)), "hq_country": [], "website": [],
               "parent_qids": [], "parent_labels": [], "inception_year": "", "stock_listings": [],
               "opencorporates_id": [], "lei": lei, "lei_source": "gleif_ultimate_child"}
        row.update(_gleif_cols(k, parents))
        row["wikidata_cro_number"] = ""
        row.update(_cro_cols(rec, method))
        out.append(row)

    out.sort(key=lambda r: (r["record_basis"] != "wikidata", _qnum(r["wikidata_qid"]), r["lei"]))
    return out
