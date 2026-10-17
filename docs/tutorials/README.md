# Using Airmid Éireann data

Every dataset is a plain CSV (and JSON) file at a stable address, so you can open it in a spreadsheet, a notebook or
any programming language. No sign-up, no key. These recipes were run against the live release before publishing;
all of them are in one script, [`recipes.py`](recipes.py) (`pip install pandas`, then `python recipes.py`).

Base address: `https://priyalifescience.com/opendata/airmid/v1/`. The list of datasets, with record counts,
licences and file links, is [`catalog.json`](https://priyalifescience.com/opendata/airmid/v1/catalog.json). What each
column means is in the [data dictionary](https://priyalifescience.com/opendata/airmid/v1/DATA_DICTIONARY.md).

## In a spreadsheet (no code)

**Excel:** Data → Get Data → From Web → paste a CSV address, for example
`https://priyalifescience.com/opendata/airmid/v1/ema_shortages/ema_shortages.csv` → Load. Refresh later with
Data → Refresh All to get the weekly update.

**Google Sheets:** in a cell, type
`=IMPORTDATA("https://priyalifescience.com/opendata/airmid/v1/ema_shortages/ema_shortages.csv")`.
Google Sheets limits how big an imported file can be, so use it for the smaller datasets (shortages, approvals,
alerts); open the big ones (European trials, Eurostat trade) in Excel or Python.

## In Python (pandas)

```python
import pandas as pd
BASE = "https://priyalifescience.com/opendata/airmid/v1/"

# Irish trials that are recruiting now, by phase
trials = pd.read_csv(BASE + "ctgov_ireland/ctgov_ireland.csv")
recruiting = trials[trials["overall_status"] == "RECRUITING"]
print(len(recruiting))
print(recruiting["phases"].fillna("not stated").value_counts())
```

### How big a share of Europe's trials does Ireland host?

```python
eu = pd.read_csv(BASE + "ctgov_europe/ctgov_europe.csv", usecols=["nct_id", "start_date", "countries"])
eu["year"] = pd.to_numeric(eu["start_date"].astype(str).str[:4], errors="coerce")
eu = eu[eu["year"].between(2015, 2025)].copy()   # start_date can be a PLANNED future date
eu["ireland"] = eu["countries"].astype(str).str.contains("Ireland")
by_year = eu.groupby("year").agg(trials=("nct_id", "count"), with_ireland=("ireland", "sum"))
by_year["share_%"] = (100 * by_year["with_ireland"] / by_year["trials"]).round(1)
print(by_year)
```

In the release of 15 October 2026 this gives between 1.2% and 2.0% a year for 2015 to 2025 (for example 155 of
10,444 trials that started in 2023). Note that ClinicalTrials.gov stores planned start dates, so filter to the years
you mean.

### Open EU medicine shortages

```python
short = pd.read_csv(BASE + "ema_shortages/ema_shortages.csv")
open_ = short[~short["status"].str.contains("resolved", case=False, na=False)]
print(open_[["medicine", "inn", "status"]])
```

### Irish pharma exports by month

```python
exp = pd.read_csv(BASE + "cso_pharma_exports/cso_pharma_exports.csv")
print(exp.groupby("month")["exports_eur_thousand"].sum().tail(12))
```

Values are in thousands of euro, as published by the CSO. Single months can move sharply: September 2025 shows
EUR 14.4 billion of exports to the USA alone, against about EUR 2.4 billion in the months either side. That is the
CSO's published figure, not a processing error; check the CSO's own releases before drawing conclusions.

### One medicine across all datasets

```python
links = pd.read_csv(BASE + "links/medicine_links.csv")
print(links[links["substance"] == "methotrexate"])
```

The cross-reference matches active substances by normalised name. It is a starting point for joining datasets, not
an official mapping; check the records themselves.

## Without installing anything (Python standard library)

```python
import csv, io, urllib.request
url = "https://priyalifescience.com/opendata/airmid/v1/ema_shortages/ema_shortages.csv"
rows = list(csv.DictReader(io.StringIO(urllib.request.urlopen(url).read().decode("utf-8"))))
print(len(rows), rows[0]["medicine"])
```

## Good practice

- **Credit the source.** Each dataset keeps its publisher's licence (see `catalog.json` or each `datapackage.json`).
  Credit the publisher and "Airmid Éireann, Priya Life Science", and cite DOI 10.5281/zenodo.23336432.
- **Record the release date.** The data refreshes every Monday; `catalog.json` shows when each dataset was collected.
- **Report errors** through the [issue forms](https://github.com/priyalifescience/airmed/issues/new/choose).
- **FAERS counts are reports, not proof** that a medicine caused an event. Read the field notes before using them.
