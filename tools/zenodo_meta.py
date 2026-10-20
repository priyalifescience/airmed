"""Regenerate .zenodo.json (the text Zenodo shows for each GitHub release) from the live catalog.json.

    python tools/zenodo_meta.py [--version 1.2.1]

Run it before tagging a release, so the Zenodo record lists every dataset with its record count, grouped by topic.
"""
import argparse
import html
import json
import urllib.request
from pathlib import Path

BASE = "https://priyalifescience.com/opendata/airmid/v1/"
GROUPS = [
    ("Clinical trials", ["ctgov_ireland", "ctgov_europe"]),
    ("Medicines and approvals", ["hpra_medicines", "ema_medicines", "ema_orphans", "eu_orphan_exclusivity", "ema_prime",
                                 "ema_paediatric_plans", "fda_approvals", "fda_orange_book", "fda_purple_book",
                                 "hc_approvals", "hc_drug_product_database", "dailymed_spl_index"]),
    ("Shortages and safety", ["ema_shortages", "fda_shortages", "ema_referrals", "ema_psusa", "mhra_safety_alerts",
                              "fda_device_recalls", "fda_warning_letters", "faers_counts", "ecdc_antimicrobial_consumption"]),
    ("Industry, trade and spending", ["cso_pharma_exports", "cso_pharma_industry_stats", "eurostat_pharma_trade",
                                      "eurostat_pharma_industry", "oecd_pharma_spending", "nhs_prescription_costs",
                                      "medicaid_drug_spending", "nadac_prices", "pharma_company_ids", "epa_pharma_licences",
                                      "eea_industrial_emissions_ireland", "dete_annual_employment_survey",
                                      "dete_employment_permits"]),
    ("Health services and research", ["ntpf_waiting_lists", "cordis_health", "openalex_ireland_pharma",
                                      "openalex_europe_pharma", "nih_ireland", "research_ireland_grants"]),
    ("Irish health system, public spending and parliament", ["cso_health_accounts", "cso_hospital_discharges",
                                                             "doh_health_key_trends", "ni_bso_gp_prescribing",
                                                             "etenders_health_awards", "oireachtas_medicine_questions"]),
]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--catalog", default=BASE + "catalog.json")
    a = ap.parse_args(argv)
    cat = json.load(urllib.request.urlopen(a.catalog, timeout=60))
    ds = {d["key"]: d for d in cat["datasets"]}
    total = sum(int(d["records"]) for d in ds.values())
    day = cat["release"][:10]
    placed = {k for _, keys in GROUPS for k in keys}
    groups = GROUPS + ([("Other", sorted(k for k in ds if k not in placed))] if set(ds) - placed else [])
    parts = [
        f"<p><strong>Airmid Éireann</strong> is the open-data project of Priya Life Science. It collects public records on "
        f"medicines, clinical trials, approvals, shortages, safety, trade, spending and research for Ireland and Europe "
        f"from official publishers, checks them, and releases them as CSV and JSON with each source's licence, a data "
        f"dictionary, checksums and DCAT-AP metadata.</p>",
        f"<p>This software release contains the collectors and release builder. The data release of {day} holds "
        f"<strong>{len(ds)} datasets and {total:,} records</strong>, refreshed weekly at "
        f'<a href="{BASE}">priyalifescience.com/opendata/airmid/v1</a> '
        f'(index: <a href="{BASE}catalog.json">catalog.json</a>; search: <a href="{BASE}search/">search by meaning</a>).</p>',
    ]
    for title, keys in groups:
        items = [f"<li>{html.escape(ds[k]['title'])}: {int(ds[k]['records']):,} records "
                 f"({html.escape(ds[k]['publisher'].split(',')[0].split(' (')[0])})</li>" for k in keys if k in ds]
        if items:
            parts.append(f"<p><strong>{title}</strong></p><ul>{''.join(items)}</ul>")
    parts.append("<p>No personal names or contact details are published. The data have multiple licences: each dataset keeps "
                 "the licence of its source (listed in catalog.json and each datapackage.json); they are not all CC BY 4.0. "
                 "This software is EUPL-1.2. Not medical advice. Project page: "
                 '<a href="https://priyalifescience.com/airmed">priyalifescience.com/airmed</a>.</p>')
    p = Path(__file__).resolve().parent.parent / ".zenodo.json"
    z = json.loads(p.read_text(encoding="utf-8"))
    z["description"] = "".join(parts)
    z["version"] = a.version
    z.pop("publication_date", None)  # Zenodo uses the GitHub release date
    kw = set(z.get("keywords", []))
    kw |= {"open data", "Europe", "Canada", "patents", "drug spending", "pharmacovigilance", "DCAT-AP"}
    z["keywords"] = sorted(kw, key=str.lower)
    p.write_text(json.dumps(z, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f".zenodo.json: version {a.version}, {len(ds)} datasets, {total:,} records, {len(z['description'])} chars")


if __name__ == "__main__":
    main()
