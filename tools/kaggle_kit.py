"""Write paste-ready Kaggle texts (file descriptions, column descriptions, provenance) and a starter notebook.

    python tools/kaggle_kit.py --out <folder>
"""
import argparse
import json
import urllib.request
from pathlib import Path

BASE = "https://priyalifescience.com/opendata/airmid/v1/"

NOTEBOOK_CELLS = [
    ("markdown", "# Airmid Éireann: getting started\n\nOpen data on medicines, clinical trials, shortages, approvals, safety and spending "
                 "for Ireland and Europe. Live weekly copy: https://priyalifescience.com/opendata/airmid/v1/ · "
                 "Project: https://priyalifescience.com/airmed"),
    ("code", "import glob, json, os\nimport pandas as pd\n\n"
             "ROOT = next(p for p in glob.glob('/kaggle/input/*') if os.path.exists(os.path.join(p, 'catalog.json')))\n"
             "def load(key, **kw):\n    return pd.read_csv(os.path.join(ROOT, key, key + '.csv'), **kw)\n\n"
             "catalog = json.load(open(os.path.join(ROOT, 'catalog.json')))\n"
             "pd.DataFrame(catalog['datasets'])[['key', 'title', 'records']].sort_values('records', ascending=False)"),
    ("markdown", "## Irish trials recruiting now, by phase"),
    ("code", "trials = load('ctgov_ireland')\nrec = trials[trials['overall_status'] == 'RECRUITING']\n"
             "print(len(rec), 'recruiting trials with an Irish site')\nrec['phases'].fillna('not stated').value_counts()"),
    ("markdown", "## Ireland's share of Europe's clinical trials\n`start_date` can be a planned future date, so keep completed years."),
    ("code", "eu = load('ctgov_europe', usecols=['nct_id', 'start_date', 'countries'])\n"
             "eu['year'] = pd.to_numeric(eu['start_date'].astype(str).str[:4], errors='coerce')\n"
             "eu = eu[eu['year'].between(2015, 2025)].copy()\n"
             "eu['ireland'] = eu['countries'].astype(str).str.contains('Ireland')\n"
             "by = eu.groupby('year').agg(trials=('nct_id', 'count'), with_ireland=('ireland', 'sum'))\n"
             "by['share_%'] = (100 * by['with_ireland'] / by['trials']).round(1)\nby"),
    ("markdown", "## Open EU medicine shortages"),
    ("code", "short = load('ema_shortages')\nshort[~short['status'].str.contains('resolved', case=False, na=False)][['medicine', 'inn', 'status']]"),
    ("markdown", "## One medicine across all datasets\nThe cross-reference matches active substances by normalised name, with WHO ATC codes."),
    ("code", "links = pd.read_csv(os.path.join(ROOT, 'links', 'medicine_links.csv'))\nlinks.sort_values('dataset_count', ascending=False).head(15)"),
    ("markdown", "Multiple licences: each dataset keeps the licence of its source (see `catalog.json` and each "
                 "`datapackage.json`); they are not all CC BY 4.0, and some carry conditions listed in `README.md`. "
                 "Please credit the original publisher and \"Airmid Éireann, Priya Life Science\". Not medical advice."),
]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    out = Path(a.out)
    cat = json.load(urllib.request.urlopen(BASE + "catalog.json", timeout=60))
    ds = sorted(cat["datasets"], key=lambda d: d["key"])

    files = ["KAGGLE FILE DESCRIPTIONS: on the Data tab, click each file, then the pencil next to 'About this file', "
             "and paste its line.\n"]
    for d in ds:
        files.append(f"{d['key']}/{d['key']}.csv\n{d['title']}. {int(d['records']):,} records, collected "
                     f"{d['retrieved'][:10]} from {d['publisher']}. Licence: {d['licence']}. {d.get('attribution', '')}\n")
    files.append("catalog.json\nIndex of every dataset: title, publisher, licence, record count, collection date and file links.\n")
    files.append("DATA_DICTIONARY.md\nPlain-English description of every column in every dataset.\n")
    files.append("links/medicine_links.csv\nThe same active substance across datasets, matched by normalised name, with WHO ATC codes "
                 "where known. A starting point for joins, not an official mapping.\n")
    (out / "kaggle_1_file_descriptions.txt").write_text("\n".join(files), encoding="utf-8")

    cols = ["KAGGLE COLUMN DESCRIPTIONS: on the Data tab, open a CSV, click 'Column' view, then the pencil next to each "
            "column name. The score rises with each file done: start with the big files.\n"]
    for d in sorted(ds, key=lambda d: -int(d["records"])):
        cols.append(f"=== {d['key']}.csv ===")
        for f in d.get("fields", []):
            cols.append(f"{f['name']}: {f.get('description', '')}")
        cols.append("")
    (out / "kaggle_2_column_descriptions.txt").write_text("\n".join(cols), encoding="utf-8")

    pubs = sorted({d["publisher"] for d in ds})
    prov = ("KAGGLE PROVENANCE: Metadata tab -> Provenance.\n\n"
            "SOURCES (paste into 'Sources'):\n" + "\n".join(f"- {p}" for p in pubs) +
            f"\n\nFull list with licence links: {BASE}catalog.json\n\n"
            "COLLECTION METHODOLOGY (paste into 'Collection methodology'):\n"
            "Each dataset is collected by an open-source collector (https://github.com/priyalifescience/airmed) directly from "
            "the publisher's official API, bulk file or open-data portal. A source is only collected if it is on an approved "
            "list with its licence recorded. Collectors keep only listed fields, check record counts against the publisher's "
            "own totals where one is given, and refuse partial downloads. Every value passes a privacy filter: personal names "
            "and contact details are never published (e.g. trial sponsors that are individuals are blanked). A release is "
            "refused if a dataset shrinks unexpectedly. The collection runs every Monday; each file records its collection "
            "date. Corrections are logged at https://priyalifescience.com/corrections .\n\n"
            "UPDATE FREQUENCY (Metadata tab): Weekly\n\n"
            "LICENCE (Settings): Other (specified in description)\n")
    (out / "kaggle_3_provenance_and_settings.txt").write_text(prov, encoding="utf-8")

    nb = {"nbformat": 4, "nbformat_minor": 5,
          "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"}},
          "cells": [{"cell_type": t, "metadata": {}, "source": s, **({"outputs": [], "execution_count": None} if t == "code" else {})}
                    for t, s in NOTEBOOK_CELLS]}
    (out / "kaggle_4_airmid_starter_notebook.ipynb").write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote 4 files to", out)


if __name__ == "__main__":
    main()
