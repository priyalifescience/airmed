"""CORDIS: EU-funded research projects (Horizon 2020 and Horizon Europe) in health, medicine, pharma and biotech.

Source: the official CORDIS bulk project files (CSV, zipped), published by the Publications Office of the EU and
listed on data.europa.eu. Project-level data only. Organisation names are kept (organisations are legal entities,
not persons); organisation addresses, VAT numbers, geolocations, web sites and contact forms are never kept, and
the separate ERC principal-investigator file is never downloaded.

Health filter (a project is kept if ANY rule matches; the reasons are listed in `health_filter_basis`):
  programme   one of its legal bases (programme parts) is Horizon 2020 Societal Challenge 1 "Health, demographic
              change and well-being" (H2020-EU.3.1.*, which includes IMI2 = H2020-EU.3.1.7) or Horizon Europe
              Pillar II Cluster 1 "Health" (HORIZON.2.1*, which includes the Innovative Health Initiative = HORIZON.2.1.7)
  joint_undertaking  its topic belongs to a health joint undertaking / partnership call: IMI2, IHI or Global
              Health EDCTP3 (catches any such project filed under another legal basis)
  euroscivoc  CORDIS classified it in the European Science Vocabulary under "medical and health sciences"
              (this branch holds pharmacology and pharmacy, medical biotechnology, clinical medicine, health
              sciences, basic medicine); this brings in health projects funded elsewhere, e.g. ERC, MSCA, EIC
"""

import csv
import io
import json
import re
import zipfile

from ..http import fetch

KEY = "cordis_health"
FIELDS = ["project_id", "acronym", "title", "framework_programme", "legal_basis", "programme_part", "topic",
          "topic_title", "call", "funding_scheme", "start_date", "end_date", "total_cost_eur", "eu_contribution_eur",
          "coordinator_organisation", "coordinator_country", "participant_countries", "participant_organisations",
          "organisation_count", "status", "health_filter_basis", "health_fields", "cordis_url"]

ZIPS = {
    "H2020": "https://cordis.europa.eu/data/cordis-h2020projects-csv.zip",
    "HORIZON": "https://cordis.europa.eu/data/cordis-HORIZONprojects-csv.zip",
}
# Lower bounds on the number of projects in each file (35,389 and 23,954 on 8 Oct 2026). A smaller file means a
# truncated or broken download, and we refuse it rather than publish a partial dataset.
MIN_PROJECTS = {"H2020": 35000, "HORIZON": 20000}

# Only these columns are copied out of the zip files; everything else (addresses, VAT, geolocation, contact form,
# objectives) is dropped at download time.
KEEP = {
    "project.csv": ["id", "acronym", "status", "title", "startDate", "endDate", "totalCost", "ecMaxContribution",
                    "topics", "frameworkProgramme", "masterCall", "subCall", "fundingScheme"],
    "organization.csv": ["projectID", "name", "country", "role", "order"],
    "legalBasis.csv": ["projectID", "legalBasis", "title"],
    "euroSciVoc.csv": ["projectID", "euroSciVocPath", "euroSciVocTitle"],
    "topics.csv": ["projectID", "topic", "title"],
}

HEALTH_LEGAL = ("H2020-EU.3.1", "HORIZON.2.1")
HEALTH_JU = re.compile(r"(^|-)(IMI2|IHI|EDCTP3)(-|$)")
HEALTH_ESV = "medical and health sciences"


def _read_csv(zf: zipfile.ZipFile, name: str) -> list:
    text = zf.read(name).decode("utf-8-sig")
    cols = KEEP[name]
    return [[r.get(c, "") or "" for c in cols] for r in csv.DictReader(io.StringIO(text), delimiter=";")]


def fetch_raw() -> bytes:
    """Both programme files, reduced to the columns in KEEP: {"H2020": {"project.csv": [[...], ...], ...}, ...}."""
    out = {"columns": KEEP, "programmes": {}}
    for fp, url in ZIPS.items():
        zf = zipfile.ZipFile(io.BytesIO(fetch(url, timeout=600)))
        if zf.testzip() is not None:
            raise RuntimeError(f"CORDIS {fp} zip is corrupt")
        tables = {name: _read_csv(zf, name) for name in KEEP}
        n = len(tables["project.csv"])
        if n < MIN_PROJECTS[fp]:
            raise RuntimeError(f"CORDIS {fp} file holds only {n} projects (expected at least {MIN_PROJECTS[fp]})")
        out["programmes"][fp] = tables
    return json.dumps(out, ensure_ascii=False).encode("utf-8")


def _money(v: str) -> str:
    """CORDIS writes Horizon Europe amounts with a decimal comma ("2073781,25"); normalise to a dot."""
    v = (v or "").strip().replace(",", ".")
    if not v:
        return ""
    try:
        f = float(v)
    except ValueError:
        return ""
    return str(int(f)) if f == int(f) else f"{f:.2f}"


def parse(raw: bytes) -> list:
    data = json.loads(raw)
    cols = data["columns"]
    out = []
    for fp, tables in sorted(data["programmes"].items()):
        rows = {name: [dict(zip(cols[name], r)) for r in tables.get(name, [])] for name in cols}
        legal, esv, topic_title, orgs = {}, {}, {}, {}
        for r in rows["legalBasis.csv"]:
            legal.setdefault(r["projectID"], []).append((r["legalBasis"], r["title"]))
        for r in rows["euroSciVoc.csv"]:
            esv.setdefault(r["projectID"], []).append((r["euroSciVocPath"], r["euroSciVocTitle"]))
        for r in rows["topics.csv"]:
            topic_title.setdefault(r["projectID"], {})[r["topic"]] = r["title"]
        for r in rows["organization.csv"]:
            orgs.setdefault(r["projectID"], []).append(r)

        seen = set()
        for p in rows["project.csv"]:
            pid = p["id"].strip()
            if not pid or pid in seen:
                continue
            seen.add(pid)
            lb = sorted(set(legal.get(pid, [])))
            basis = []
            if any(code.startswith(HEALTH_LEGAL) for code, _ in lb):
                basis.append("programme")
            if HEALTH_JU.search(p["topics"] or ""):
                basis.append("joint_undertaking")
            health_fields = sorted({t for path, t in esv.get(pid, []) if path.startswith(HEALTH_ESV)})
            if health_fields:
                basis.append("euroscivoc")
            if not basis:
                continue

            po = sorted(orgs.get(pid, []), key=lambda o: (int(o["order"]) if o["order"].isdigit() else 10**6, o["name"]))
            coord = next((o for o in po if o["role"] == "coordinator"), {})
            names = []
            for o in po:
                if o["name"] and o["name"] not in names:
                    names.append(o["name"])
            out.append({
                "project_id": pid,
                "acronym": p["acronym"],
                "title": p["title"],
                "framework_programme": p["frameworkProgramme"] or fp,
                "legal_basis": [code for code, _ in lb],
                "programme_part": [t for _, t in lb],
                "topic": p["topics"],
                "topic_title": topic_title.get(pid, {}).get(p["topics"], ""),
                "call": p["masterCall"] or p["subCall"],
                "funding_scheme": p["fundingScheme"],
                "start_date": p["startDate"],
                "end_date": p["endDate"],
                "total_cost_eur": _money(p["totalCost"]),
                "eu_contribution_eur": _money(p["ecMaxContribution"]),
                "coordinator_organisation": coord.get("name", ""),
                "coordinator_country": coord.get("country", ""),
                "participant_countries": sorted({o["country"] for o in po if o["country"]}),
                "participant_organisations": names,
                "organisation_count": len(names),
                "status": p["status"],
                "health_filter_basis": basis,
                "health_fields": health_fields,
                "cordis_url": f"https://cordis.europa.eu/project/id/{pid}",
            })
    out.sort(key=lambda r: (int(r["project_id"]) if r["project_id"].isdigit() else 0, r["project_id"]))
    return out
