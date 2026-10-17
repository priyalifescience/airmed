"""Write DCAT-AP metadata for a release, so open-data portals (data.gov.ie, data.europa.eu) can harvest it.

    python tools/dcat.py --dist dist/v1

Writes dist/v1/dcat.jsonld (JSON-LD, DCAT-AP 3 vocabulary) and dist/v1/dcat.ttl (Turtle) from catalog.json.
One dcat:Catalog with a dcat:Dataset per dataset and a dcat:Distribution per file (CSV, JSON).
Licences: each dataset points to its source's licence page (dct:license), the source publisher is recorded as
dct:source / prov:wasDerivedFrom, and Priya Life Science is the dct:publisher of the compiled release.
"""

import argparse
import json
from pathlib import Path

BASE = "https://priyalifescience.com/opendata/airmid/v1/"
MEDIA = {"csv": "text/csv", "json": "application/json"}
EU_FMT = {"csv": "http://publications.europa.eu/resource/authority/file-type/CSV",
          "json": "http://publications.europa.eu/resource/authority/file-type/JSON"}
THEME_HEAL = "http://publications.europa.eu/resource/authority/data-theme/HEAL"
THEME_ECON = "http://publications.europa.eu/resource/authority/data-theme/ECON"
THEME_TECH = "http://publications.europa.eu/resource/authority/data-theme/TECH"
ECON_KEYS = ("cso_", "eurostat_", "oecd_", "medicaid", "nhs_prescription", "nadac", "pharma_company", "epa_")
PUBLISHER = {"@id": "https://priyalifescience.com/#organization", "@type": "foaf:Agent",
             "foaf:name": "Priya Life Science", "foaf:homepage": {"@id": "https://priyalifescience.com"}}
CONTEXT = {"dcat": "http://www.w3.org/ns/dcat#", "dct": "http://purl.org/dc/terms/", "foaf": "http://xmlns.com/foaf/0.1/",
           "prov": "http://www.w3.org/ns/prov#", "vcard": "http://www.w3.org/2006/vcard/ns#",
           "xsd": "http://www.w3.org/2001/XMLSchema#", "spdx": "http://spdx.org/rdf/terms#"}


def first_url(text: str, fallback: str) -> str:
    """Some source_endpoint values list several URLs or add a note; DCAT needs one clean URI."""
    for tok in (text or "").replace(";", " ").split():
        if tok.startswith(("https://", "http://")):
            return tok.rstrip(",.")
    return fallback


def lit(v, lang="en"):
    return {"@value": v, "@language": lang}


def build(catalog: dict) -> dict:
    datasets = []
    for d in catalog["datasets"]:
        dsid = BASE + d["key"] + "/"
        themes = [THEME_HEAL] + ([THEME_ECON] if d["key"].startswith(ECON_KEYS) else [])
        dists = []
        for f in d["files"]:
            fmt = f["format"].lower()
            if fmt not in EU_FMT:  # e.g. the datapackage.json descriptor
                fmt = "json" if f["url"].endswith(".json") else "csv"
            dist = {"@id": f["url"] + "#distribution", "@type": "dcat:Distribution",
                    "dct:title": lit(f"{d['title']} ({fmt.upper()})"),
                    "dcat:accessURL": {"@id": dsid}, "dcat:downloadURL": {"@id": f["url"]},
                    "dcat:mediaType": {"@id": "https://www.iana.org/assignments/media-types/" + MEDIA.get(fmt, "application/octet-stream")},
                    "dct:format": {"@id": EU_FMT.get(fmt, EU_FMT["csv"])},
                    "dct:license": {"@id": d["licence_url"]}}
            if f.get("bytes"):
                dist["dcat:byteSize"] = {"@value": str(f["bytes"]), "@type": "xsd:nonNegativeInteger"}
            if f.get("sha256"):
                dist["spdx:checksum"] = {"@type": "spdx:Checksum", "spdx:algorithm": {"@id": "spdx:checksumAlgorithm_sha256"},
                                         "spdx:checksumValue": f["sha256"]}
            dists.append(dist)
        datasets.append({
            "@id": dsid, "@type": "dcat:Dataset",
            "dct:identifier": d["key"],
            "dct:title": lit(d["title"]),
            "dct:description": lit(f"{d['title']}. {d.get('records', 0):,} records, collected {d.get('retrieved', '')[:10]} "
                                   f"from {d['publisher']}. {d.get('attribution', '')} Part of Airmid Éireann, "
                                   "Ireland's open pharma data project."),
            "dct:publisher": {"@id": PUBLISHER["@id"]},
            "dct:source": {"@id": first_url(d.get("source_endpoint"), d["licence_url"])},
            "prov:wasDerivedFrom": {"@id": first_url(d.get("source_endpoint"), d["licence_url"])},
            "dct:rightsHolder": lit(d["publisher"]),
            "dct:license": {"@id": first_url(d["licence_url"], d["licence_url"])},
            "dct:rights": lit(d["licence"]),
            "dct:modified": {"@value": d.get("retrieved", catalog["release"]), "@type": "xsd:dateTime"},
            "dct:accrualPeriodicity": {"@id": "http://publications.europa.eu/resource/authority/frequency/WEEKLY"},
            "dct:language": {"@id": "http://publications.europa.eu/resource/authority/language/ENG"},
            "dcat:theme": [{"@id": t} for t in themes],
            "dcat:keyword": [lit("pharmaceuticals"), lit("medicines"), lit("open data"), lit("Ireland")],
            "dcat:landingPage": {"@id": d.get("browse_url") or catalog.get("homepage", "https://priyalifescience.com/airmed")},
            "dcat:contactPoint": {"@type": "vcard:Organization", "vcard:fn": "Priya Life Science",
                                  "vcard:hasEmail": {"@id": "mailto:info@priyalifescience.com"}},
            "dcat:distribution": dists,
        })
    return {
        "@context": CONTEXT,
        "@graph": [PUBLISHER, {
            "@id": BASE + "dcat.jsonld#catalog", "@type": "dcat:Catalog",
            "dct:title": lit(catalog["name"]),
            "dct:description": lit("Open datasets on medicines, clinical trials, approvals, shortages, safety, trade, spending and "
                                   "research for Ireland and Europe, collected from official publishers with their source licences."),
            "dct:publisher": {"@id": PUBLISHER["@id"]},
            "foaf:homepage": {"@id": catalog.get("homepage", "https://priyalifescience.com/airmed")},
            "dct:modified": {"@value": catalog["release"], "@type": "xsd:dateTime"},
            "dct:language": {"@id": "http://publications.europa.eu/resource/authority/language/ENG"},
            "dct:spatial": {"@id": "http://publications.europa.eu/resource/authority/country/IRL"},
            "dcat:themeTaxonomy": {"@id": "http://publications.europa.eu/resource/authority/data-theme"},
            "dcat:dataset": [{"@id": x["@id"]} for x in datasets],
        }] + datasets,
    }


def esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def to_turtle(doc: dict) -> str:
    """Small JSON-LD (this shape only) to Turtle writer, so portals that want Turtle get it without extra libraries."""
    pre = "".join(f"@prefix {k}: <{v}> .\n" for k, v in doc["@context"].items()) + "\n"
    out, anon = [], [0]

    def val(v):
        if isinstance(v, dict):
            if "@value" in v:
                if "@language" in v:
                    return f'"{esc(v["@value"])}"@{v["@language"]}'
                if "@type" in v:
                    return f'"{esc(v["@value"])}"^^{v["@type"]}'
                return f'"{esc(v["@value"])}"'
            if set(v) == {"@id"}:
                i = v["@id"]
                return i if ":" in i and not i.startswith("http") and not i.startswith("mailto") else f"<{i}>"
            return "[ " + " ; ".join(f"{p} {val(o)}" for p, o in props(v)) + " ]"
        if isinstance(v, list):
            return " , ".join(val(x) for x in v)
        return f'"{esc(str(v))}"'

    def props(node):
        items = []
        if "@type" in node:
            items.append(("a", {"@id": node["@type"]}))
        items += [(k, v) for k, v in node.items() if not k.startswith("@")]
        return items

    graph, seen = [], set()

    def lift(node):  # nested nodes that have their own @id become top-level subjects (as in JSON-LD)
        for k, v in list(node.items()):
            items = v if isinstance(v, list) else [v]
            new_items = []
            for it in items:
                if isinstance(it, dict) and "@id" in it and len(it) > 1:
                    lift(it)
                    if it["@id"] not in seen:
                        seen.add(it["@id"])
                        graph.append(it)
                    new_items.append({"@id": it["@id"]})
                else:
                    new_items.append(it)
            node[k] = new_items if isinstance(v, list) else new_items[0]

    import copy
    for node in copy.deepcopy(doc["@graph"]):
        lift(node)
        if node["@id"] not in seen:
            seen.add(node["@id"])
            graph.append(node)
    for node in graph:
        out.append(f"<{node['@id']}>\n    " + " ;\n    ".join(f"{p} {val(o)}" for p, o in props(node)) + " .\n")
    return pre + "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", default="dist/v1")
    a = ap.parse_args(argv)
    dist = Path(a.dist)
    catalog = json.loads((dist / "catalog.json").read_text(encoding="utf-8"))
    doc = build(catalog)
    (dist / "dcat.jsonld").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    (dist / "dcat.ttl").write_text(to_turtle(doc), encoding="utf-8")
    print(f"dcat: {len(catalog['datasets'])} datasets -> {dist / 'dcat.jsonld'}, {dist / 'dcat.ttl'}")


if __name__ == "__main__":
    main()
