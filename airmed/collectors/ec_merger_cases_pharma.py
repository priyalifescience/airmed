"""European Commission merger cases (EU Merger Regulation) in the pharmaceutical sector, with their decisions.

Source: the European Commission's competition case search (competition-cases.ec.europa.eu, DG Competition). The
public site is a front end to the Commission's Search API (webgate.ec.europa.eu/es/search-api, dataset
CS_PROD_ODSE_PROD); this collector asks the same API the public site uses, with the same public dataset key the site
serves to every visitor. Labels for codes (decision types, case types, NACE sectors, procedure) come from the
Commission's case reference-data API, using the key published in the site's own public configuration file
(competition-cases.ec.europa.eu/assets/env-json-config.json). No login is used.

Scope: merger cases (instrument M) whose sector list includes NACE C.21 (manufacture of basic pharmaceutical
products and pharmaceutical preparations, all sub-classes), G.46.46 (wholesale of pharmaceutical goods) or G.47.73
(retail sale of pharmaceutical products), in either of the two NACE code sets the Commission uses. The Commission
assigns sectors per case; a pharma deal coded only under another sector (for example chemicals C.20 or medical
devices C.32.5) is not included.

Dates: the API stores dates as Brussels midnight expressed in UTC (e.g. 2020-04-13T22:00Z for 14 April 2020). The
calendar date is taken as the UTC time plus 12 hours, which gives the Brussels date for every such value.

Privacy: case titles name the undertakings concerned. A title that reads as naming a natural person (a title
such as "Mr", "Mrs", "Ms", "Dr") is blanked and `title_withheld` is "yes". Case documents, contact details and
case-team names are never read.
"""

import datetime as dt
import json
import re
import uuid

from ..http import fetch

KEY = "ec_merger_cases_pharma"
FIELDS = ["case_number", "title", "title_withheld", "nace_codes", "nace_labels", "case_type", "regulation",
          "procedure", "notification_date", "initiation_date", "deadline_date", "last_decision_date",
          "decision_count", "decision_dates", "decision_types", "oj_publication_dates", "case_url"]

SEARCH = "https://webgate.ec.europa.eu/es/search-api/rest/search?apiKey=CS_PROD_ODSE_PROD&text=*&pageSize={size}&pageNumber={page}"
CONFIG = "https://competition-cases.ec.europa.eu/assets/env-json-config.json"
REFDATA_PATHS = {
    "decision": "/id/MECaseDecisionTypes/related-hierarchies?type=DECISION_TYPE",
    "case_type": "/id/MergerCaseTypes/related-hierarchies?type=CASE_TYPE",
    "nace": "/id/TblovsNace/related-hierarchies?type=NACE_SECTOR",
    "procedure": "/id/MEproceduretype/related-hierarchies?type=PROCEDURE_TYPE",
}
# The two merger regulations, as the case search site's own filter names them.
REGULATIONS = {"MERegulation2": "Council Regulation (EC) No 139/2004", "MERegulation1": "Council Regulation (EEC) No 4064/89"}
PHARMA_SECTORS = [
    "NaceSectorsC_21", "NaceSectorsC_21_1", "NaceSectorsC_21_1_0", "NaceSectorsC_21_2", "NaceSectorsC_21_2_0",
    "NaceSectorsG_46_4_6", "NaceSectorsG_47_7_3",
    "NaceV2Sector_C_21", "NaceV2Sector_C_21.1", "NaceV2Sector_C_21.10", "NaceV2Sector_C_21.2", "NaceV2Sector_C_21.20",
    "NaceV2Sector_G_46.46", "NaceV2Sector_G_47.73",
]
PAGE = 100
PERSON = re.compile(r"\b(?:mr|mrs|ms|miss|dr|sir|herr|frau|m\.|mme|sig\.?)\b\.?\s+[A-Z]", re.I)


# A stable sort on a unique field: with the default relevance order, pages overlap and some results never appear.
SORT = [{"field": "metadataReference", "order": "ASC"}]


def _multipart(query: dict):
    boundary = "airmid" + uuid.uuid4().hex
    parts = ""
    for name, value in (("query", query), ("sort", SORT)):
        parts += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"blob\"\r\n"
                  f"Content-Type: application/json\r\n\r\n{json.dumps(value)}\r\n")
    body = (parts + f"--{boundary}--\r\n").encode("utf-8")
    return body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}


def _search_all(query: dict) -> list:
    results, page, total = [], 1, None
    while True:
        body, headers = _multipart(query)
        j = json.loads(fetch(SEARCH.format(size=PAGE, page=page), data=body, headers=headers))
        total = j.get("totalResults", 0) if total is None else total
        batch = j.get("results", [])
        results.extend(batch)
        if not batch or len(results) >= total or page > 200:
            break
        page += 1
    by_ref = {r.get("reference"): r for r in results}
    if len(by_ref) != total:
        raise RuntimeError(f"EC case search returned {len(by_ref)} distinct of {total} results; refusing a partial dataset")
    return list(by_ref.values())


def _walk(nodes, out):
    for n in nodes or []:
        if isinstance(n, dict):
            rep = n.get("representations") or {}
            out[n.get("bid") or n.get("code")] = {"code": n.get("code"), "description": n.get("description"),
                                                   "pub": rep.get("PUB_DESC") or rep.get("WEB_MSGE_DS") or ""}
            _walk(n.get("related"), out)
    return out


def fetch_raw() -> bytes:
    cases = _search_all({"bool": {"must": [{"terms": {"caseInstrument": ["M"]}},
                                           {"terms": {"metadataType": ["METADATA_CASE"]}},
                                           {"terms": {"caseSectors": PHARMA_SECTORS}}]}})
    numbers = sorted({n for c in cases for n in c.get("metadata", {}).get("caseNumber", [])})
    decisions = []
    for i in range(0, len(numbers), 50):
        decisions += _search_all({"bool": {"must": [{"terms": {"caseNumber": numbers[i:i + 50]}},
                                                    {"terms": {"metadataType": ["METADATA_DECISION"]}}]}})
    refdata = {}
    try:
        cfg = json.loads(fetch(CONFIG))["modules"]["odse"]["refData"]
        for name, path in REFDATA_PATHS.items():
            refdata[name] = _walk(json.loads(fetch(cfg["url"] + path, headers={"apikey": cfg["apikey"], "application": "ODSE"})), {})
    except Exception as e:  # labels are a convenience; the codes are kept either way
        refdata["error"] = str(e)
    keep = lambda r: {"reference": r.get("reference"), "metadata": r.get("metadata", {})}  # drop text snippets
    return json.dumps({"cases": [keep(c) for c in cases], "decisions": [keep(d) for d in decisions], "refdata": refdata},
                      ensure_ascii=False).encode("utf-8")


def brussels_date(value: str) -> str:
    v = (value or "").strip()
    if not v:
        return ""
    m = re.match(r"(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})", v)
    if not m:
        return v[:10]
    t = dt.datetime.fromisoformat(f"{m[1]}T{m[2]}:{m[3]}") + dt.timedelta(hours=12)
    return t.date().isoformat()


def _first(md: dict, key: str) -> str:
    v = md.get(key) or []
    return v[0] if v else ""


def _label(ref: dict, code: str, prefer_pub=True) -> str:
    x = (ref or {}).get(code)
    if not x:
        return ""
    return (x["pub"] if prefer_pub and x["pub"] else x["description"]) or ""


def _oj_dates(md: dict) -> list:
    return sorted({brussels_date(d) for d in md.get("caseOfficialJournalPublicationsPublishedDates", []) if d})


def parse(raw: bytes) -> list:
    data = json.loads(raw)
    ref = data.get("refdata", {})
    by_case = {}
    for d in data.get("decisions", []):
        md = d["metadata"]
        for n in md.get("caseNumber", []) or [d["reference"].split("-DEC")[0]]:
            by_case.setdefault(n, []).append(md)
    out = []
    for c in data["cases"]:
        md = c["metadata"]
        number = _first(md, "caseNumber")
        title = re.sub(r"</?b>", "", _first(md, "caseTitle")).strip()
        withheld = bool(PERSON.search(title))
        nace = sorted(set(md.get("caseSectors", [])))
        decs = sorted(by_case.get(number, []), key=lambda x: (_first(x, "decisionAdoptionDate"), _first(x, "decisionNumber")))
        dtypes = [_first(x, "decisionTypes") for x in decs]
        out.append({
            "case_number": number,
            "title": "" if withheld else title,
            "title_withheld": "yes" if withheld else "no",
            "nace_codes": [(ref.get("nace", {}).get(n) or {}).get("code") or n for n in nace],
            "nace_labels": [_label(ref.get("nace"), n, prefer_pub=False) for n in nace],
            "case_type": _label(ref.get("case_type"), _first(md, "caseType"), prefer_pub=False) or _first(md, "caseType"),
            "regulation": REGULATIONS.get(_first(md, "caseRegulation"), _first(md, "caseRegulation")),
            "procedure": _label(ref.get("procedure"), _first(md, "caseSimplified")) or _first(md, "caseSimplified"),
            "notification_date": brussels_date(_first(md, "caseNotificationDate")),
            "initiation_date": brussels_date(_first(md, "caseInitiationDate")),
            "deadline_date": brussels_date(_first(md, "caseDeadlineDate")),
            "last_decision_date": brussels_date(_first(md, "caseLastDecisionDate")),
            "decision_count": len(decs),
            "decision_dates": [brussels_date(_first(x, "decisionAdoptionDate")) for x in decs],
            "decision_types": [_label(ref.get("decision"), t) or t for t in dtypes],
            "oj_publication_dates": _oj_dates(md),
            "case_url": f"https://competition-cases.ec.europa.eu/cases/{number}" if number else "",
        })
    out.sort(key=lambda r: (r["notification_date"] or r["initiation_date"] or r["last_decision_date"], r["case_number"]),
             reverse=True)
    return out
