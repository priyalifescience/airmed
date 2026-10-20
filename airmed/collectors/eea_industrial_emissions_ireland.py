"""EEA Industrial Reporting database (IED + E-PRTR): pollutant releases, pollutant transfers and waste transfers of
Irish chemical and pharmaceutical facilities, by reporting year.

Source: the European Environment Agency's DiscoData SQL service (https://discodata.eea.europa.eu/sql), database
[IED].[latest] (the same database the EEA Industrial Emissions Portal, industry.eea.europa.eu, reads). The latest
published version (v16.0, Feb 2026) holds E-PRTR releases and transfers for 2007-2024. Irish data are reported by the
EPA, and the EPA's licence profile number is the facility localId (P0004.FACILITY -> P0004), so every row joins to
epa_pharma_licences.

Scope: facilities with countryCode IE whose E-PRTR Annex I main activity (in any reporting year) is in section 4,
"Chemical industry":
  4(a) basic organic chemicals, 4(b) basic inorganic chemicals, 4(c) fertilisers, 4(d) plant health products and
  biocides, 4(e) "Installations using a chemical or biological process for the production on an industrial scale of
  basic pharmaceutical products", 4(f) explosives and pyrotechnic products.
All of section 4 is kept (not only 4(e)) because Irish API and intermediates plants are often reported under 4(a)
(organic chemicals); filter on eprtr_activity to get 4(e) only. Facility attributes (name, parent company, town,
NUTS 3, main activity) come from the facility record of the same
reporting year, or from the most recent one when the EEA holds none for that year (names change: P0004 is
"Smithkline Beecham (Cork) Limited" until 2014 and "Thermo Fisher Scientific Cork Limited" from 2015).

One row per published record: record_type is pollutant_release (to air, water or land), pollutant_transfer
(off-site transfer in waste water) or waste_transfer (off-site transfer of hazardous / non-hazardous waste).
E-PRTR only requires reporting above the Annex II thresholds, so a missing pollutant means "below threshold or not
reported", never zero.

Not downloaded: street address lines, postcodes and coordinates of facilities; the name and address of waste
receivers (only the receiver's and receiving site's country codes are kept); remarks and further-details free text.
Pollutant codes are kept as the EEA publishes them (e.g. CO2, NOX, TOC, DCM).
"""

import json
import re
import urllib.parse

from ..http import fetch

KEY = "eea_industrial_emissions_ireland"
FIELDS = ["reporting_year", "record_type", "facility_id", "epa_licence_profile", "facility_name", "parent_company",
          "town", "nuts3", "eprtr_activity", "eprtr_activity_description", "facility_status", "number_of_employees",
          "medium", "pollutant", "waste_classification", "waste_treatment", "transboundary", "receiver_country",
          "receiving_site_country", "quantity", "unit", "accidental_quantity_kg", "method_code",
          "confidentiality_reason", "eea_record_id"]
SQL_URL = "https://discodata.eea.europa.eu/sql"
DB = "[IED].[latest]"
MAX_HITS = 200000
ACTIVITY_4 = {
    "a": "Chemical installations for the production on an industrial scale of basic organic chemicals",
    "b": "Chemical installations for the production on an industrial scale of basic inorganic chemicals",
    "c": "Chemical installations for the production on an industrial scale of phosphorous-, nitrogen- or "
         "potassium-based fertilisers (simple or compound fertilisers)",
    "d": "Chemical installations for the production on an industrial scale of basic plant health products and of "
         "biocides",
    "e": "Installations using a chemical or biological process for the production on an industrial scale of basic "
         "pharmaceutical products",
    "f": "Installations for the production on an industrial scale of explosives and pyrotechnic products",
}
_SCOPE = (f"SELECT localId FROM {DB}.[ProductionFacility] "
          "WHERE countryCode = 'IE' AND EPRTRAnnexIMainActivity LIKE '4%'")
_JOIN = f"JOIN {DB}.[ProductionFacilityReport] p ON p.Id = r.facilityReportId"
_WHERE = f"WHERE p.countryCode = 'IE' AND p.localId IN ({_SCOPE})"
QUERIES = {
    "facilities": ("SELECT localId, namespace, facilityName, parentCompanyName, city, NUTS3, EPRTRAnnexIMainActivity, "
                   f"status, reportingYear FROM {DB}.[ProductionFacility] "
                   f"WHERE countryCode = 'IE' AND localId IN ({_SCOPE})"),
    "reports": (f"SELECT p.Id, p.localId, p.reportingYear, p.numberOfEmployees FROM {DB}.[ProductionFacilityReport] p "
                + _WHERE),
    "releases": ("SELECT r.Id, r.facilityReportId, r.pollutant, r.mediumCode, r.totalPollutantQuantityKg, "
                 "r.accidentalPollutantQuantityKg, r.methodCode, r.confidentialityReason "
                 f"FROM {DB}.[PollutantRelease] r {_JOIN} {_WHERE}"),
    "pollutant_transfers": ("SELECT r.Id, r.facilityReportId, r.pollutant, r.totalPollutantQuantityKg, r.methodCode, "
                            f"r.confidentialityReason FROM {DB}.[OffsitePollutantTransfer] r {_JOIN} {_WHERE}"),
    "waste_transfers": ("SELECT r.Id, r.facilityReportId, r.wasteClassification, r.wasteTreatment, "
                        "r.totalWasteQuantityTNE, r.methodCode, r.transboundaryIndicator, r.receiver_countryCode, "
                        "r.receivingSite_countryCode, r.confidentialityReason "
                        f"FROM {DB}.[OffsiteWasteTransfer] r {_JOIN} {_WHERE}"),
}
COUNT_FROM = {"reports": f"{DB}.[ProductionFacilityReport] p {_WHERE}",
              "releases": f"{DB}.[PollutantRelease] r {_JOIN} {_WHERE}",
              "pollutant_transfers": f"{DB}.[OffsitePollutantTransfer] r {_JOIN} {_WHERE}",
              "waste_transfers": f"{DB}.[OffsiteWasteTransfer] r {_JOIN} {_WHERE}"}
_PROFILE_RE = re.compile(r"^(P\d{4})\.FACILITY$")
_ACT_RE = re.compile(r"^4\(([a-f])\)")


def _sql(query: str) -> list:
    url = SQL_URL + "?" + urllib.parse.urlencode({"query": query, "p": 1, "nrOfHits": MAX_HITS})
    j = json.loads(fetch(url, timeout=180))
    if j.get("errors") or "results" not in j:
        raise RuntimeError(f"DiscoData query failed: {j.get('errors')}")
    return j["results"]


def fetch_raw() -> bytes:
    """Five SQL queries (facilities, yearly facility reports, releases, pollutant transfers, waste transfers) plus a
    COUNT(*) for each record table, so parse() can refuse a truncated reply."""
    out = {name: _sql(q) for name, q in QUERIES.items()}
    out["counts"] = {name: int(_sql(f"SELECT count(*) n FROM {frm}")[0]["n"]) for name, frm in COUNT_FROM.items()}
    return json.dumps(out).encode("utf-8")


def _num(v):
    if v is None or v == "":
        return ""
    f = float(v)
    return int(f) if f == int(f) else round(f, 6)


def _text(v) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def parse(raw: bytes) -> list:
    data = json.loads(raw)
    for name, n in data.get("counts", {}).items():
        if len(data.get(name) or []) != n:
            raise RuntimeError(f"DiscoData says {n} {name} but the download holds {len(data.get(name) or [])}")
    if not data.get("facilities") or not data.get("reports"):
        raise RuntimeError("no Irish chemical facilities in the download")

    latest, by_year = {}, {}   # localId -> most recent facility record; (localId, year) -> that year's record
    for f in data["facilities"]:
        lid = f.get("localId") or ""
        by_year[(lid, f.get("reportingYear"))] = f
        if lid not in latest or (f.get("reportingYear") or 0) > (latest[lid].get("reportingYear") or 0):
            latest[lid] = f
    reports = {r["Id"]: r for r in data["reports"]}

    out = []

    def base(rec, record_type):
        rep = reports.get(rec.get("facilityReportId"))
        if rep is None:
            raise RuntimeError(f"record {rec.get('Id')} points at an unknown facility report")
        lid = rep.get("localId") or ""
        fac = by_year.get((lid, rep.get("reportingYear"))) or latest.get(lid, {})
        act = _text(fac.get("EPRTRAnnexIMainActivity"))
        m, p = _ACT_RE.match(act), _PROFILE_RE.match(lid)
        emp = rep.get("numberOfEmployees")
        return {
            "reporting_year": int(rep.get("reportingYear") or 0),
            "record_type": record_type,
            "facility_id": lid,
            "epa_licence_profile": p[1] if p else "",
            "facility_name": _text(fac.get("facilityName")),
            "parent_company": _text(fac.get("parentCompanyName")),
            "town": _text(fac.get("city")),
            "nuts3": _text(fac.get("NUTS3")),
            "eprtr_activity": act,
            "eprtr_activity_description": ACTIVITY_4.get(m[1], "") if m else "",
            "facility_status": _text(fac.get("status")),
            "number_of_employees": int(emp) if emp not in (None, "") else "",
            "medium": "", "pollutant": "", "waste_classification": "", "waste_treatment": "", "transboundary": "",
            "receiver_country": "", "receiving_site_country": "", "quantity": "", "unit": "",
            "accidental_quantity_kg": "",
            "method_code": _text(rec.get("methodCode")),
            "confidentiality_reason": _text(rec.get("confidentialityReason")),
            "eea_record_id": rec.get("Id"),
        }

    for r in data.get("releases") or []:
        row = base(r, "pollutant_release")
        row.update(medium=_text(r.get("mediumCode")), pollutant=_text(r.get("pollutant")),
                   quantity=_num(r.get("totalPollutantQuantityKg")), unit="kg",
                   accidental_quantity_kg=_num(r.get("accidentalPollutantQuantityKg")))
        out.append(row)
    for r in data.get("pollutant_transfers") or []:
        row = base(r, "pollutant_transfer")
        row.update(medium="WASTEWATER", pollutant=_text(r.get("pollutant")),
                   quantity=_num(r.get("totalPollutantQuantityKg")), unit="kg")
        out.append(row)
    for r in data.get("waste_transfers") or []:
        row = base(r, "waste_transfer")
        tb = r.get("transboundaryIndicator")
        row.update(waste_classification=_text(r.get("wasteClassification")),
                   waste_treatment=_text(r.get("wasteTreatment")),
                   transboundary="" if tb is None else ("yes" if tb else "no"),
                   receiver_country=_text(r.get("receiver_countryCode")),
                   receiving_site_country=_text(r.get("receivingSite_countryCode")),
                   quantity=_num(r.get("totalWasteQuantityTNE")), unit="t")
        out.append(row)
    out.sort(key=lambda r: (r["reporting_year"], r["facility_id"], r["record_type"], r["medium"], r["pollutant"],
                            r["waste_classification"], r["waste_treatment"], r["eea_record_id"]))
    return out
