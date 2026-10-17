"""Airmid Éireann recipes: every example in docs/tutorials/README.md, runnable as one script (pip install pandas).

    python docs/tutorials/recipes.py
"""
import pandas as pd

BASE = "https://priyalifescience.com/opendata/airmid/v1/"

# 1. What is in the release?
catalog = pd.read_json(BASE + "catalog.json", typ="series")
datasets = pd.DataFrame(catalog["datasets"])[["key", "title", "records", "publisher"]]
print(datasets.sort_values("records", ascending=False).head(10).to_string(index=False))

# 2. Irish trials that are recruiting now, by phase
trials = pd.read_csv(BASE + "ctgov_ireland/ctgov_ireland.csv")
recruiting = trials[trials["overall_status"] == "RECRUITING"]
print("\nRecruiting trials with an Irish site:", len(recruiting))
print(recruiting["phases"].fillna("not stated").value_counts().head(6).to_string())

# 3. How many European trials started each year include Ireland?
eu = pd.read_csv(BASE + "ctgov_europe/ctgov_europe.csv", usecols=["nct_id", "start_date", "countries"])
eu["year"] = pd.to_numeric(eu["start_date"].astype(str).str[:4], errors="coerce")
eu = eu[eu["year"].between(2015, 2025)].copy()  # start_date can be a PLANNED future date: keep completed years
eu["ireland"] = eu["countries"].astype(str).str.contains("Ireland")
by_year = eu.groupby("year").agg(trials=("nct_id", "count"), with_ireland=("ireland", "sum"))
by_year["share_%"] = (100 * by_year["with_ireland"] / by_year["trials"]).round(1)
print("\nEuropean trials by start year, and the share with an Irish site:")
print(by_year.to_string())

# 4. EU medicine shortages that are not resolved
short = pd.read_csv(BASE + "ema_shortages/ema_shortages.csv")
open_ = short[~short["status"].str.contains("resolved", case=False, na=False)]
print("\nOpen EU shortages:", len(open_))
print(open_[["medicine", "inn", "status"]].head(8).to_string(index=False))

# 5. Ireland's pharma exports (EUR), last 12 months in the CSO data
exp = pd.read_csv(BASE + "cso_pharma_exports/cso_pharma_exports.csv")
total = exp.groupby("month")["exports_eur_thousand"].sum().sort_index().tail(12)
print("\nIrish pharma exports, EUR thousand, all destinations:")
print(total.to_string())

# 6. Which medicines appear in the most datasets?
links = pd.read_csv(BASE + "links/medicine_links.csv")
print("\nSubstances in 6 or more datasets:")
print(links[links["dataset_count"] >= 6][["substance", "dataset_count", "datasets"]].to_string(index=False))
