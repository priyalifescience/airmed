"""Regenerate README.md's dataset table and headline numbers from the live catalog.json, so they never drift.

    python tools/readme_table.py [--catalog https://priyalifescience.com/opendata/airmid/v1/catalog.json]
"""
import argparse
import json
import re
import urllib.request
from pathlib import Path

BASE = "https://priyalifescience.com/opendata/airmid/v1/"
# short display: (topic icon, short licence)
LIC = [("CC0", "CC0"), ("CC BY 4.0", "CC BY 4.0"), ("Open Government Licence v3", "OGL v3"),
       ("Open Government Licence - Canada", "OGL Canada"), ("Public domain", "public domain"),
       ("public domain", "public domain"), ("EMA website", "reuse with credit"), ("Eurostat", "reuse with credit"),
       ("OECD", "reuse with credit"), ("ECDC", "reuse with credit"), ("NTPF", "reuse with credit"),
       ("Public data", "public data")]
ORGS = {"ClinicalTrials.gov": "U.S. National Library of Medicine", "DailyMed": "U.S. National Library of Medicine"}


def short_licence(text):
    for needle, label in LIC:
        if needle.lower() in text.lower():
            return label
    return "see datapackage"


def short_pub(p):
    p = re.split(r"[,(]| / ", p)[0].strip()
    return p.replace("U.S. Food and Drug Administration", "U.S. FDA")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default=BASE + "catalog.json")
    a = ap.parse_args(argv)
    cat = json.load(urllib.request.urlopen(a.catalog, timeout=60))
    ds = cat["datasets"]
    total = sum(int(d["records"]) for d in ds)
    day = cat["release"][:10]
    rows = []
    for d in sorted(ds, key=lambda x: x["title"].lower()):
        k = d["key"]
        site = f"[website]({d['browse_url']})" if d.get("browse_url") and not d["browse_url"].endswith("/airmed") else ""
        rows.append(f"| **{d['title']}** | {int(d['records']):,} | {short_pub(d['publisher'])} · {short_licence(d['licence'])} | "
                    f"[CSV]({BASE}{k}/{k}.csv) · [JSON]({BASE}{k}/{k}.json) | {site} |")
    table = ("| Dataset | Records\\* | Source · licence | Download | Explore |\n|---|---:|---|:---:|---|\n" + "\n".join(rows) +
             f"\n\n<sub>\\* Release of {day}; counts change slightly each week. Live counts: "
             f"[`catalog.json`]({BASE}catalog.json).</sub>\n")
    p = Path(__file__).resolve().parent.parent / "README.md"
    s = p.read_text(encoding="utf-8")
    start = s.index("| | Dataset | Records") if "| | Dataset | Records" in s else s.index("| Dataset | Records")
    end = s.index("<sub>\\*", start)
    end = s.index("</sub>", end) + len("</sub>\n")
    s = s[:start] + table + s[end:]
    s = re.sub(r'alt="Datasets: \d+" src="https://img.shields.io/badge/datasets-\d+-', f'alt="Datasets: {len(ds)}" src="https://img.shields.io/badge/datasets-{len(ds)}-', s)
    s = re.sub(r"<h2>[\d,]+</h2><sub>records(?: in release|, release of)[^<]*</sub>", f"<h2>{total:,}</h2><sub>records, release of {day}</sub>", s)
    s = re.sub(r"<h2>\d+</h2><sub>open datasets</sub>", f"<h2>{len(ds)}</h2><sub>open datasets</sub>", s)
    s = re.sub(r"<h2>\d+</h2><sub>official publishers</sub>", "<h2>20</h2><sub>official publishers</sub>", s)
    p.write_text(s, encoding="utf-8", newline="\n")
    print(f"README: {len(ds)} datasets, {total:,} records, release {day}")


if __name__ == "__main__":
    main()
