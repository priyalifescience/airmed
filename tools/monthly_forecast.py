"""Airmid Éireann monthly report: statistical projections module.

    python tools/monthly_forecast.py --dist <release dir> --out <dir> [--log <forecast_log.csv>]
    python tools/monthly_forecast.py --dist <newer release dir> --score <forecast_log.csv> --out <dir>

The first form builds monthly series from the release files, backtests six models per series, applies a publish gate
and writes forecast.json, forecast.csv, charts/<series>.svg and appends published projections to the accuracy log.
The second form scores past projections in a log against the actuals of a newer release (forecast_scores.csv).

Method, fixed in code and recorded in forecast.json:
  * series are built from named dataset files and fields; only complete months are used (a month is complete for a
    dated-event source when it ended before the source was collected, minus a publication or registration lag; for a
    source with its own month field when it is present and, where a completeness key is set, has enough key values);
  * at most the latest 120 complete months are used; at least 36 are required, otherwise "not projected
    (insufficient history)";
  * count series with a mean monthly count below 10 are not projected: the observed rate is reported with an exact
    Poisson 95% interval;
  * models (statsforecast): SeasonalNaive (season 12), Naive, AutoETS, AutoARIMA, AutoTheta and an equal-weight
    combination of ETS, ARIMA and Theta. Combination intervals are the average of the three component intervals;
  * rolling-origin backtest, horizon 6: MASE (scaled by the in-sample seasonal naive MAE of each training window),
    sMAPE and empirical coverage of the 80% and 95% intervals;
  * the model with the lowest mean MASE is chosen. A projection is published only when the chosen model is not one of
    the two naive benchmarks, its MASE is below 1, its MASE is at least 5% below the better benchmark's, and its 80%
    interval covered at least 65% of backtest actuals. Otherwise: "seasonal pattern only; no projection".

Output is deterministic: the same release and code give byte-identical files (no random elements; n_jobs=1; floats
rounded to 6 significant figures). generated_at is pinned to --generated-at, else SOURCE_DATE_EPOCH, else the release
timestamp in catalog.json. Describes past patterns; it makes no causal claims and gives no advice.
"""
import argparse
import csv
import hashlib
import json
import math
import os
import platform
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

FORECAST_VERSION = "1.0.0"
LABEL = "Statistical projection based on past patterns. Not a prediction of events and not advice."
H = 6
LEVELS = (80, 95)
SEASON = 12
MIN_HISTORY = 36
MAX_HISTORY = 120
MIN_TRAIN = 24
MAX_WINDOWS = 12
COUNT_MEAN_MIN = 10.0
MASE_MAX = 1.0
SKILL_MIN = 0.05
COV80_MIN = 0.65
SEED = 20261021
BENCHMARKS = ("SeasonalNaive", "Naive")
COMPONENTS = ("AutoETS", "AutoARIMA", "AutoTheta")
MODEL_ORDER = ("SeasonalNaive", "Naive", "AutoETS", "AutoARIMA", "AutoTheta", "Combination")
CHART_HISTORY = 48

NOT_ENOUGH = "not projected (insufficient history)"
NO_PROJ = "seasonal pattern only; no projection"
POISSON = "low count: observed rate only, no projection"
PUBLISH = "projection published"

# ---------------------------------------------------------------- series definitions
NTPF_REPORTS = [("OPNational01", "Outpatient (first appointment)"),
                ("IPDCNational01", "Inpatient/day case (GI endoscopy excluded)"),
                ("IPDCNational04", "GI endoscopy")]

SERIES = [
    {"id": "ie_pharma_exports_total", "title": "Ireland's exports of medicinal and pharmaceutical products, all destinations",
     "definition": "Sum of exports_eur_thousand over every destination row of CSO table TSM10 (SITC 54) in the month, "
                   "including 'Other countries' and 'EU country not specified'; a month counts only when every "
                   "other destination has a value.",
     "unit": "EUR million", "scale": 1000, "dataset": "cso_pharma_exports", "kind": "period", "date_field": "month",
     "date_format": "iso", "filter": [], "agg": {"type": "sum", "field": "exports_eur_thousand"},
     "completeness": {"key": "country_code", "min_ratio": 1.0}, "is_count": False,
     "blank_as_zero": {"field": "country_code", "values": ["ZZEU99"]},
     "notes": ["'EU country not specified' (ZZEU99) is blank for 2015-01 to 2020-12 and for 2025-09; it is counted "
               "as zero there. Where it has a value it averages about EUR 2 million a month, under 0.1% of the total.",
               "CSO publishes goods exports about six weeks after the month; recent months are provisional and are "
               "revised."]},
    {"id": "nhs_england_items", "title": "Prescription items dispensed in the community, England",
     "definition": "Sum of items over all BNF chemical substances in NHSBSA Prescription Cost Analysis for the month.",
     "unit": "million items", "scale": 1e6, "dataset": "nhs_prescription_costs", "kind": "period",
     "date_field": "year_month", "date_format": "iso", "filter": [], "agg": {"type": "sum", "field": "items"},
     "completeness": {"key": "bnf_chemical_substance_code", "min_ratio": 0.9}, "is_count": False},
    {"id": "nhs_england_nic", "title": "Net ingredient cost of prescriptions dispensed in the community, England",
     "definition": "Sum of nic_gbp over all BNF chemical substances for the month (list price before discounts).",
     "unit": "GBP million", "scale": 1e6, "dataset": "nhs_prescription_costs", "kind": "period",
     "date_field": "year_month", "date_format": "iso", "filter": [], "agg": {"type": "sum", "field": "nic_gbp"},
     "completeness": {"key": "bnf_chemical_substance_code", "min_ratio": 0.9}, "is_count": False},
    {"id": "ni_gp_items", "title": "GP prescription items dispensed, Northern Ireland",
     "definition": "Sum of items over all rows of the BSO GP prescribing data for the month.",
     "unit": "million items", "scale": 1e6, "dataset": "ni_bso_gp_prescribing", "kind": "period",
     "date_field": "year_month", "date_format": "iso", "filter": [], "agg": {"type": "sum", "field": "items"},
     "completeness": {"key": "bnf_chemical_substance_code", "min_ratio": 0.9}, "is_count": False},
    {"id": "ni_gp_actual_cost", "title": "Actual cost of GP prescribing, Northern Ireland",
     "definition": "Sum of actual_cost_gbp over all rows of the BSO GP prescribing data for the month.",
     "unit": "GBP million", "scale": 1e6, "dataset": "ni_bso_gp_prescribing", "kind": "period",
     "date_field": "year_month", "date_format": "iso", "filter": [], "agg": {"type": "sum", "field": "actual_cost_gbp"},
     "completeness": {"key": "bnf_chemical_substance_code", "min_ratio": 0.9}, "is_count": False},
] + [
    {"id": f"ntpf_{code.lower()}_total", "title": f"People on the NTPF waiting list: {label}, Ireland",
     "definition": f"Sum of total over all hospitals in NTPF report {code}, latest snapshot in the month.",
     "unit": "people", "scale": 1, "dataset": "ntpf_waiting_lists", "kind": "snapshot", "date_field": "snapshot_date",
     "date_format": "iso", "filter": [{"field": "report", "op": "eq", "value": code}],
     "agg": {"type": "sum", "field": "total"}, "is_count": False}
    for code, label in NTPF_REPORTS
] + [
    {"id": "ctgov_ireland_starts", "title": "Studies with a site in Ireland starting in the month (ClinicalTrials.gov)",
     "definition": "ClinicalTrials.gov studies with at least one site in Ireland whose start date falls in the month. "
                   "Withdrawn studies excluded.",
     "unit": "studies", "scale": 1, "dataset": "ctgov_ireland", "kind": "event", "date_field": "start_date",
     "date_format": "iso", "filter": [{"field": "overall_status", "op": "ne", "value": "WITHDRAWN"}],
     "agg": {"type": "count"}, "lag_months": 6, "is_count": True,
     "notes": ["Studies are often registered, or add a site, after they start, so recent months rise in later "
               "snapshots. A six-month lag is applied (the descriptive report uses three) so the model is not fitted "
               "to the most understated months; the latest months used are still provisional."]},
    {"id": "ctgov_europe_starts", "title": "Studies with a site in Europe starting in the month (ClinicalTrials.gov)",
     "definition": "ClinicalTrials.gov studies with at least one site in the EU-27, UK, Norway, Iceland, Switzerland or "
                   "Liechtenstein whose start date falls in the month. Withdrawn studies excluded.",
     "unit": "studies", "scale": 1, "dataset": "ctgov_europe", "kind": "event", "date_field": "start_date",
     "date_format": "iso", "filter": [{"field": "overall_status", "op": "ne", "value": "WITHDRAWN"}],
     "agg": {"type": "count"}, "lag_months": 6, "coverage_start": "2015-01", "is_count": True,
     "notes": ["Same registration lag as the Ireland series; the dataset covers studies starting 2015 or later."]},
    {"id": "ema_shortages_first_published", "title": "Medicine shortages first published by EMA in the month",
     "definition": "Entries in EMA's medicine shortages list whose first publication date falls in the month.",
     "unit": "shortage entries", "scale": 1, "dataset": "ema_shortages", "kind": "event",
     "date_field": "first_published", "date_format": "dmy", "filter": [], "agg": {"type": "count"},
     "lag_months": 0, "is_count": True,
     "notes": ["EMA lists shortages affecting more than one member state or that it coordinates; national shortages "
               "in Ireland are not included."]},
    {"id": "fda_original_approvals_all", "title": "US FDA original approvals, all application types",
     "definition": "Drugs@FDA applications (NDA, BLA and ANDA) whose original approval date falls in the month.",
     "unit": "applications", "scale": 1, "dataset": "fda_approvals", "kind": "event", "date_field": "approval_date",
     "date_format": "iso", "filter": [], "agg": {"type": "count"}, "lag_months": 0, "is_count": True},
    {"id": "fda_original_nda_bla", "title": "US FDA original approvals of new drug and biologic applications (NDA and BLA)",
     "definition": "Drugs@FDA applications of type NDA or BLA whose original approval date falls in the month.",
     "unit": "applications", "scale": 1, "dataset": "fda_approvals", "kind": "event", "date_field": "approval_date",
     "date_format": "iso", "filter": [{"field": "application_type", "op": "in", "value": ["NDA", "BLA"]}],
     "agg": {"type": "count"}, "lag_months": 0, "is_count": True},
    {"id": "oireachtas_medicine_questions", "title": "Parliamentary questions on medicines, drugs, pharmaceuticals and the HPRA",
     "definition": "Oireachtas parliamentary questions to the Departments of Health and Enterprise matching the "
                   "medicines topic terms, by date in the official record.",
     "unit": "questions", "scale": 1, "dataset": "oireachtas_medicine_questions", "kind": "event", "date_field": "date",
     "date_format": "iso", "filter": [], "agg": {"type": "count"}, "lag_months": 0, "coverage_start": "2020-01",
     "is_count": True,
     "notes": ["The Dáil does not sit in August and sits less in December; months with no sittings count as zero. "
               "The record has gaps around dissolutions and elections, which are real zeros, not missing data."]},
]


# ---------------------------------------------------------------- period helpers
def mi(ym):
    return int(ym[:4]) * 12 + int(ym[5:7]) - 1


def ms(i):
    return f"{i // 12:04d}-{i % 12 + 1:02d}"


def month_label(ym):
    names = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
             "November", "December"]
    return f"{names[int(ym[5:7]) - 1]} {ym[:4]}"


def r6(v):
    """Round to 6 significant figures (stable text output)."""
    if v is None:
        return None
    v = float(v)
    if not math.isfinite(v):
        return None
    if v == 0:
        return 0.0
    return float(f"{v:.6g}")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- release access
class Release:
    def __init__(self, dist):
        self.dist = Path(dist)
        self.catalog = json.loads((self.dist / "catalog.json").read_text(encoding="utf-8"))
        self.entries = {d["key"]: d for d in self.catalog.get("datasets", [])}
        self._frames = {}

    def csv_path(self, key):
        return self.dist / key / f"{key}.csv"

    def frame(self, key):
        if key not in self._frames:
            self._frames[key] = pd.read_csv(self.csv_path(key), dtype=str, keep_default_na=False, encoding="utf-8")
        return self._frames[key]

    def retrieved(self, key):
        e = self.entries.get(key) or {}
        if not e.get("retrieved"):
            raise ValueError(f"catalog.json has no retrieved date for {key}")
        return e["retrieved"][:10]

    def publisher(self, key):
        return (self.entries.get(key) or {}).get("publisher", "")


def apply_filters(df, filters):
    mask = pd.Series(True, index=df.index)
    for f in filters or []:
        s, op, val = df[f["field"]], f["op"], f.get("value")
        if op == "eq":
            m = s == str(val)
        elif op == "ne":
            m = s != str(val)
        elif op == "in":
            m = s.isin([str(v) for v in val])
        elif op == "regex":
            m = s.str.contains(val, regex=True, na=False)
        else:
            raise ValueError(f"unknown filter op {op}")
        mask &= m
    return df[mask]


def normalise_dates(s, fmt):
    if fmt == "iso":
        day = s.str.extract(r"^(\d{4}-\d{2}-\d{2})", expand=False)
        mon = s.str.extract(r"^(\d{4}-\d{2})", expand=False)
        return day.fillna(mon).fillna("")
    if fmt == "dmy":
        p = s.str.extract(r"^(\d{2})/(\d{2})/(\d{4})")
        return (p[2] + "-" + p[1] + "-" + p[0]).fillna("")
    raise ValueError(f"unknown date_format {fmt}")


def _month_end_day(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    nxt = datetime(y + (m == 12), 1 if m == 12 else m + 1, 1)
    return (nxt - pd.Timedelta(days=1)).strftime("%Y-%m-%d")


def build_series(spec, rel):
    """Complete monthly series for one definition. Returns dict(months, values, notes, excluded)."""
    raw = rel.frame(spec["dataset"])
    d_all = normalise_dates(raw[spec["date_field"]], spec.get("date_format", "iso"))
    df = apply_filters(raw.assign(_d=d_all), spec.get("filter"))
    df = df[df["_d"].str.len() >= 7].assign(_p=lambda x: x["_d"].str[:7])
    retrieved = rel.retrieved(spec["dataset"])
    cap = mi(retrieved[:7]) - 1                      # last month that ended before collection
    notes, excluded = [], []
    agg = spec["agg"]
    if agg["type"] == "sum":
        df = df.assign(_x=pd.to_numeric(df[agg["field"]], errors="coerce"))
        bz = spec.get("blank_as_zero")
        if bz:
            hit = df["_x"].isna() & df[bz["field"]].isin(bz["values"])
            df.loc[hit, "_x"] = 0.0

    if spec["kind"] == "event":
        last = cap - int(spec.get("lag_months", 0))
        valid = df["_d"][df["_d"].map(lambda d: d <= retrieved[:len(d)])]
        if len(valid):
            dmax = valid.max()
            if mi(dmax[:7]) < last:                   # the source stops early: its last month may be partial
                ends = len(dmax) == 10 and dmax == _month_end_day(dmax[:7])
                last = mi(dmax[:7]) if ends else mi(dmax[:7]) - 1
                if not ends:
                    excluded.append(dmax[:7])
        counts = df.groupby("_p").size()
        if spec.get("coverage_start"):
            first = mi(spec["coverage_start"])
        else:                                         # first month of records may be partial
            first = (min(mi(p) for p in counts.index) + 1) if len(counts) else last + 1
        months = [ms(i) for i in range(first, last + 1)]
        values = [float(counts.get(m, 0)) for m in months]
        if int(spec.get("lag_months", 0)):
            notes.append(f"Lag of {spec['lag_months']} months applied after the collection date {retrieved}.")
    else:
        if spec["kind"] == "snapshot":
            latest = df.groupby("_p")["_d"].transform("max")
            df = df[df["_d"] == latest]
        if agg["type"] == "sum":
            ok = df[df["_x"].notna()]
            totals = ok.groupby("_p")["_x"].apply(lambda x: math.fsum(x.tolist()))
        else:
            ok = df
            totals = df.groupby("_p").size().astype(float)
        present = sorted(mi(p) for p in totals.index if mi(p) <= cap)
        comp = spec.get("completeness")
        keyc = ok.groupby("_p")[comp["key"]].nunique() if comp else None
        good = []
        for k, i in enumerate(present):
            p = ms(i)
            if comp:
                prev = [int(keyc[ms(j)]) for j in present[max(0, k - 12):k]]
                ref = max(prev) if prev else int(keyc[p])
                if comp.get("min_ratio", 1.0) >= 1.0:   # strict: every key seen anywhere must be present
                    ref = int(keyc.max())
                if int(keyc[p]) < comp.get("min_ratio", 1.0) * ref:
                    excluded.append(p)
                    continue
            good.append(i)
        # keep the longest contiguous run ending at the last complete month
        run = []
        for i in reversed(good):
            if run and i != run[-1] - 1:
                notes.append(f"Gap before {ms(run[-1])}: earlier months not used.")
                break
            run.append(i)
        run.reverse()
        months = [ms(i) for i in run]
        values = [float(totals[m]) for m in months]
    scale = float(spec.get("scale", 1))
    values = [v / scale for v in values]
    if len(months) > MAX_HISTORY:
        months, values = months[-MAX_HISTORY:], values[-MAX_HISTORY:]
    later = [p for p in excluded if not months or p > months[-1]]
    if later:
        notes.append("Partial or incomplete month(s) excluded: " + ", ".join(sorted(set(later))) + ".")
    return {"months": months, "values": values, "notes": notes, "retrieved": retrieved}


# ---------------------------------------------------------------- statistics
def poisson_ci(k, exposure=1.0, conf=0.95):
    """Exact (Garwood) interval for a Poisson rate: k events over `exposure` months."""
    from scipy.stats import chi2
    a = 1 - conf
    lo = 0.0 if k == 0 else chi2.ppf(a / 2, 2 * k) / 2
    hi = chi2.ppf(1 - a / 2, 2 * k + 2) / 2
    return lo / exposure, hi / exposure


def backtest_plan(n, h=H):
    """(n_windows, step) for a rolling-origin backtest leaving at least MIN_TRAIN months in the first window."""
    room = n - h - MIN_TRAIN
    if room < 0:
        return 0, 1
    if room >= (MAX_WINDOWS - 1) * 2:
        return MAX_WINDOWS, 2
    return min(MAX_WINDOWS, room + 1), 1


def _models():
    from statsforecast.models import AutoARIMA, AutoETS, AutoTheta, Naive, SeasonalNaive
    return [SeasonalNaive(season_length=SEASON), Naive(), AutoETS(season_length=SEASON),
            AutoARIMA(season_length=SEASON), AutoTheta(season_length=SEASON)]


def _frame(months, values):
    return pd.DataFrame({"unique_id": "s", "ds": pd.to_datetime([m + "-01" for m in months]),
                         "y": np.asarray(values, dtype=float)})


def _add_combination(df):
    df = df.copy()
    df["Combination"] = df[[m for m in COMPONENTS]].mean(axis=1)
    for lv in LEVELS:
        for side in ("lo", "hi"):
            df[f"Combination-{side}-{lv}"] = df[[f"{m}-{side}-{lv}" for m in COMPONENTS]].mean(axis=1)
    return df


def _sf():
    from statsforecast import StatsForecast
    return StatsForecast(models=_models(), freq="MS", n_jobs=1)


def seasonal_naive_scale(y):
    y = np.asarray(y, dtype=float)
    if len(y) <= SEASON:
        return float("nan")
    return float(np.mean(np.abs(y[SEASON:] - y[:-SEASON])))


def backtest(months, values, h=H):
    nw, step = backtest_plan(len(values), h)
    np.random.seed(SEED)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cv = _sf().cross_validation(h=h, df=_frame(months, values), n_windows=nw, step_size=step,
                                    level=list(LEVELS), refit=True)
    cv = _add_combination(cv.reset_index() if "unique_id" not in cv.columns else cv)
    y_all = np.asarray(values, dtype=float)
    ds_index = {pd.Timestamp(m + "-01"): k for k, m in enumerate(months)}
    scales = {}
    for c in sorted(cv["cutoff"].unique()):
        k = ds_index[pd.Timestamp(c)]
        scales[pd.Timestamp(c)] = seasonal_naive_scale(y_all[:k + 1])
    out = {}
    for m in MODEL_ORDER:
        mase_w = []
        for c, g in cv.groupby("cutoff", sort=True):
            sc = scales[pd.Timestamp(c)]
            if sc and math.isfinite(sc) and sc > 0:
                mase_w.append(float(np.mean(np.abs(g["y"] - g[m]))) / sc)
        y, f = cv["y"].to_numpy(float), cv[m].to_numpy(float)
        den = np.abs(y) + np.abs(f)
        sm = np.where(den == 0, 0.0, 200.0 * np.abs(y - f) / np.where(den == 0, 1, den))
        res = {"mase": r6(np.mean(mase_w)) if mase_w else None, "smape": r6(np.mean(sm)),
               "mae": r6(np.mean(np.abs(y - f)))}
        for lv in LEVELS:
            lo = np.maximum(cv[f"{m}-lo-{lv}"].to_numpy(float), 0.0)
            hi = cv[f"{m}-hi-{lv}"].to_numpy(float)
            res[f"coverage{lv}"] = r6(np.mean((y >= lo) & (y <= hi)))
        out[m] = res
    cutoffs = [pd.Timestamp(c).strftime("%Y-%m") for c in sorted(cv["cutoff"].unique())]
    return {"n_windows": nw, "step": step, "horizon": h, "cutoffs": cutoffs, "points": int(len(cv)),
            "models": out}


def fit_forecast(months, values, model, h=H):
    np.random.seed(SEED)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fc = _sf().forecast(h=h, df=_frame(months, values), level=list(LEVELS))
    fc = _add_combination(fc.reset_index() if "unique_id" not in fc.columns else fc)
    rows = []
    for _, r in fc.sort_values("ds").iterrows():
        row = {"month": pd.Timestamp(r["ds"]).strftime("%Y-%m"), "median": r6(max(r[model], 0.0))}
        for lv in LEVELS:
            row[f"lo{lv}"] = r6(max(r[f"{model}-lo-{lv}"], 0.0))
            row[f"hi{lv}"] = r6(max(r[f"{model}-hi-{lv}"], 0.0))
        rows.append(row)
    return rows


def choose(bt):
    """Lowest mean MASE (ties: fixed model order) and the publish decision."""
    ms_ = {m: bt["models"][m]["mase"] for m in MODEL_ORDER if bt["models"][m]["mase"] is not None}
    if not ms_:
        return None, NO_PROJ, "MASE could not be computed (constant training data)."
    chosen = min(MODEL_ORDER, key=lambda m: (ms_.get(m, float("inf")), MODEL_ORDER.index(m)))
    best_bench = min(ms_.get(b, float("inf")) for b in BENCHMARKS)
    mase = ms_[chosen]
    cov80 = bt["models"][chosen]["coverage80"]
    skill = 1 - mase / best_bench if best_bench and math.isfinite(best_bench) else None
    if chosen in BENCHMARKS:
        return chosen, NO_PROJ, f"Benchmark {chosen} had the lowest backtest MASE ({mase:.3f}); no model beat it."
    if mase >= MASE_MAX:
        return chosen, NO_PROJ, f"Chosen model MASE {mase:.3f} is not below {MASE_MAX:g}."
    if skill is None or skill < SKILL_MIN:
        return chosen, NO_PROJ, (f"Chosen model MASE {mase:.3f} is less than {SKILL_MIN:.0%} better than the best "
                                 f"naive benchmark ({best_bench:.3f}).")
    if cov80 < COV80_MIN:
        return chosen, NO_PROJ, f"80% interval covered {cov80:.0%} of backtest actuals (minimum {COV80_MIN:.0%})."
    return chosen, PUBLISH, (f"MASE {mase:.3f} < {MASE_MAX:g}; {skill:.0%} better than the best naive benchmark; "
                             f"80% interval coverage {cov80:.0%} >= {COV80_MIN:.0%}.")


def seasonal_profile(months, values, years=3):
    """Observed mean by calendar month over the last `years` complete years of the series (descriptive)."""
    if len(values) < 12 * years:
        years = len(values) // 12
    if years < 1:
        return None
    m, v = months[-12 * years:], values[-12 * years:]
    by = {}
    for a, b in zip(m, v):
        by.setdefault(a[5:7], []).append(b)
    return {"years": years, "from": m[0], "to": m[-1],
            "mean_by_calendar_month": {k: r6(sum(x) / len(x)) for k, x in sorted(by.items())}}


def analyse(sid, months, values, is_count, h=H):
    """Full pipeline for one series held in memory. Returns the per-series result (without metadata)."""
    res = {"id": sid, "history": {"first": months[0] if months else None, "last": months[-1] if months else None,
                                  "n_months": len(months), "months": list(months),
                                  "values": [r6(v) for v in values]}}
    if len(months) < MIN_HISTORY:
        res.update(decision=NOT_ENOUGH, reason=f"{len(months)} complete months; at least {MIN_HISTORY} required.")
        return res
    mean = sum(values) / len(values)
    if is_count and mean < COUNT_MEAN_MIN:
        total = int(round(sum(values)))
        lo, hi = poisson_ci(total, len(values))
        last12 = int(round(sum(values[-12:])))
        lo12, hi12 = poisson_ci(last12, 12)
        res.update(decision=POISSON,
                   reason=f"Mean monthly count {mean:.2f} is below {COUNT_MEAN_MIN:g}.",
                   poisson={"months": len(values), "events": total, "rate_per_month": r6(total / len(values)),
                            "ci95": [r6(lo), r6(hi)],
                            "last_12_months": {"from": months[-12], "to": months[-1], "events": last12,
                                               "rate_per_month": r6(last12 / 12), "ci95": [r6(lo12), r6(hi12)]},
                            "method": "exact (Garwood) Poisson interval, chi-square quantiles"},
                   zero_months=int(sum(1 for v in values if v == 0)))
        return res
    bt = backtest(months, values, h)
    chosen, decision, reason = choose(bt)
    best_bench = min(bt["models"][b]["mase"] for b in BENCHMARKS)
    res.update(backtest=bt, chosen_model=chosen, decision=decision, reason=reason,
               mase_best_benchmark=best_bench,
               skill_vs_best_benchmark=r6(1 - bt["models"][chosen]["mase"] / best_bench) if chosen else None)
    if is_count:
        res["zero_months"] = int(sum(1 for v in values if v == 0))
    if decision == PUBLISH:
        res["forecast"] = fit_forecast(months, values, chosen, h)
    else:
        res["seasonal_profile"] = seasonal_profile(months, values)
    return res


# ---------------------------------------------------------------- SVG fan chart
def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _nice_max(v):
    if v <= 0:
        return 1.0
    e = 10 ** math.floor(math.log10(v))
    for k in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if k * e >= v:
            return k * e
    return 10 * e


def _fmt(v):
    if v == 0:
        return "0"
    if abs(v) >= 100:
        return f"{v:,.0f}"
    if abs(v) >= 10:
        return f"{v:,.1f}"
    return f"{v:,.2f}"


def svg_fan(series):
    W, Ht, L, R, T, B = 760, 380, 70, 20, 56, 78
    hm = series["history"]["months"][-CHART_HISTORY:]
    hv = series["history"]["values"][-CHART_HISTORY:]
    fc = series["forecast"]
    allm = hm + [f["month"] for f in fc]
    top = _nice_max(max(hv + [f["hi95"] for f in fc]) * 1.05)
    pw, ph = W - L - R, Ht - T - B

    def X(k):
        return L + pw * k / max(1, len(allm) - 1)

    def Y(v):
        return T + ph * (1 - v / top)

    n0 = len(hm) - 1
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {Ht}" width="{W}" height="{Ht}" '
           f'role="img" aria-labelledby="t d" font-family="sans-serif" font-size="12">',
           f'<title id="t">{_esc(series["title"])}</title>',
           f'<desc id="d">{_esc(LABEL)} Monthly history to {_esc(month_label(hm[-1]))} and a six-month projection '
           f'({_esc(series["chosen_model"])}) with 80% and 95% bands.</desc>',
           f'<rect width="{W}" height="{Ht}" fill="#ffffff"/>',
           f'<text x="{L}" y="22" font-size="15" font-weight="bold" fill="#1a1a1a">{_esc(series["title"])}</text>',
           f'<text x="{L}" y="40" fill="#444">Unit: {_esc(series["unit"])}, monthly. Projection: '
           f'{_esc(series["chosen_model"])}, from {_esc(month_label(fc[0]["month"]))}.</text>']
    for k in range(5):
        v = top * k / 4
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="#e3e3e3"/>')
        out.append(f'<text x="{L - 6}" y="{Y(v) + 4:.1f}" text-anchor="end" fill="#555">{_esc(_fmt(v))}</text>')
    for k, m in enumerate(allm):
        if m[5:7] == "01" or k == len(allm) - 1:
            out.append(f'<line x1="{X(k):.1f}" x2="{X(k):.1f}" y1="{T + ph}" y2="{T + ph + 4}" stroke="#777"/>')
            lab = m[:4] if m[5:7] == "01" else m
            out.append(f'<text x="{X(k):.1f}" y="{T + ph + 17}" text-anchor="middle" fill="#555">{_esc(lab)}</text>')
    xs = [n0] + [n0 + 1 + k for k in range(len(fc))]
    last_v = hv[-1]
    for lv, op in ((95, 0.18), (80, 0.36)):
        upper = [(X(xs[0]), Y(last_v))] + [(X(x), Y(f[f"hi{lv}"])) for x, f in zip(xs[1:], fc)]
        lower = [(X(x), Y(f[f"lo{lv}"])) for x, f in zip(xs[1:], fc)][::-1] + [(X(xs[0]), Y(last_v))]
        pts = " ".join(f"{a:.1f},{b:.1f}" for a, b in upper + lower)
        out.append(f'<polygon points="{pts}" fill="#c0601a" fill-opacity="{op}" stroke="none"/>')
    hp = " ".join(f"{X(k):.1f},{Y(v):.1f}" for k, v in enumerate(hv))
    out.append(f'<polyline points="{hp}" fill="none" stroke="#1f3b57" stroke-width="2"/>')
    mp = " ".join(f"{X(x):.1f},{Y(v):.1f}" for x, v in zip(xs, [last_v] + [f["median"] for f in fc]))
    out.append(f'<polyline points="{mp}" fill="none" stroke="#8a3f0c" stroke-width="2" stroke-dasharray="5 4"/>')
    out.append(f'<line x1="{X(n0):.1f}" x2="{X(n0):.1f}" y1="{T}" y2="{T + ph}" stroke="#999" stroke-dasharray="2 3"/>')
    ly = Ht - 38
    out += [f'<line x1="{L}" x2="{L + 22}" y1="{ly}" y2="{ly}" stroke="#1f3b57" stroke-width="2"/>',
            f'<text x="{L + 28}" y="{ly + 4}" fill="#333">Observed</text>',
            f'<line x1="{L + 100}" x2="{L + 122}" y1="{ly}" y2="{ly}" stroke="#8a3f0c" stroke-width="2" '
            f'stroke-dasharray="5 4"/>',
            f'<text x="{L + 128}" y="{ly + 4}" fill="#333">Projection (median)</text>',
            f'<rect x="{L + 262}" y="{ly - 6}" width="22" height="12" fill="#c0601a" fill-opacity="0.54"/>',
            f'<text x="{L + 290}" y="{ly + 4}" fill="#333">80% band</text>',
            f'<rect x="{L + 362}" y="{ly - 6}" width="22" height="12" fill="#c0601a" fill-opacity="0.18"/>',
            f'<text x="{L + 390}" y="{ly + 4}" fill="#333">95% band</text>',
            f'<text x="{L}" y="{Ht - 18}" fill="#333">{_esc(LABEL)}</text>',
            f'<text x="{L}" y="{Ht - 4}" fill="#666" font-size="10">Source: {_esc(series["publisher"])} via Airmid '
            f'Éireann ({_esc(series["dataset"])}, collected {_esc(series["collected"])}).</text>',
            "</svg>"]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- accuracy log
LOG_FIELDS = ["series", "made_on", "data_release", "last_actual_month", "target_month", "horizon", "model",
              "median", "lo80", "hi80", "lo95", "hi95"]
SCORE_FIELDS = LOG_FIELDS + ["actual", "abs_error", "inside_80", "inside_95"]


def log_rows(result):
    rows = []
    for s in result["series"]:
        if s.get("decision") != PUBLISH:
            continue
        for k, f in enumerate(s["forecast"], 1):
            rows.append({"series": s["id"], "made_on": result["generated_at"][:10],
                         "data_release": result["release"]["release"], "last_actual_month": s["history"]["last"],
                         "target_month": f["month"], "horizon": k, "model": s["chosen_model"],
                         "median": f["median"], "lo80": f["lo80"], "hi80": f["hi80"], "lo95": f["lo95"],
                         "hi95": f["hi95"]})
    return rows


def read_log(path):
    p = Path(path)
    if not p.exists():
        return []
    with p.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def append_log(path, rows):
    """Append rows to the log; a row already present for the same series, data release, target and model is skipped,
    so rerunning on the same release does not duplicate entries. Returns the number of rows added."""
    p = Path(path)
    have = {(r["series"], r["data_release"], r["target_month"], r["model"]) for r in read_log(p)}
    new = [r for r in rows if (r["series"], str(r["data_release"]), r["target_month"], r["model"]) not in have]
    if not new:
        return 0
    write_header = not p.exists()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=LOG_FIELDS, lineterminator="\n")
        if write_header:
            w.writeheader()
        for r in new:
            w.writerow({k: r[k] for k in LOG_FIELDS})
    return len(new)


def score_log(log, actuals):
    """Score past projections. `log`: rows (dicts) as in forecast_log.csv; `actuals`: {series: {YYYY-MM: value}}.
    Returns one row per projection whose target month now has an actual: absolute error and whether the actual fell
    inside the 80% and 95% bands (bounds inclusive)."""
    out = []
    for r in log:
        a = actuals.get(r["series"], {}).get(r["target_month"])
        if a is None:
            continue
        med, lo80, hi80 = float(r["median"]), float(r["lo80"]), float(r["hi80"])
        lo95, hi95 = float(r["lo95"]), float(r["hi95"])
        row = {k: r[k] for k in LOG_FIELDS}
        row.update(actual=r6(a), abs_error=r6(abs(a - med)),
                   inside_80="yes" if lo80 <= a <= hi80 else "no",
                   inside_95="yes" if lo95 <= a <= hi95 else "no")
        out.append(row)
    return out


def summarise_scores(scored):
    by = {}
    for r in scored:
        by.setdefault(r["series"], []).append(r)
    return {s: {"n": len(v), "mean_abs_error": r6(sum(float(x["abs_error"]) for x in v) / len(v)),
                "coverage80": r6(sum(x["inside_80"] == "yes" for x in v) / len(v)),
                "coverage95": r6(sum(x["inside_95"] == "yes" for x in v) / len(v))} for s, v in sorted(by.items())}


# ---------------------------------------------------------------- run
def library_versions():
    import scipy
    import statsforecast
    return {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__,
            "scipy": scipy.__version__, "statsforecast": statsforecast.__version__}


def resolve_generated_at(arg, rel):
    if arg:
        return arg
    if os.environ.get("SOURCE_DATE_EPOCH"):
        return datetime.fromtimestamp(int(os.environ["SOURCE_DATE_EPOCH"]), tz=timezone.utc).isoformat()
    return rel.catalog.get("release") or "unknown"


def run(dist, out, log_path=None, generated_at=None, only=None):
    rel = Release(dist)
    out = Path(out)
    (out / "charts").mkdir(parents=True, exist_ok=True)
    result = {"label": LABEL, "generated_at": resolve_generated_at(generated_at, rel),
              "forecast_version": FORECAST_VERSION, "code_sha256": sha256_file(__file__),
              "libraries": library_versions(),
              "release": {"generator": rel.catalog.get("generator"), "release": rel.catalog.get("release")},
              "settings": {"horizon": H, "levels": list(LEVELS), "season_length": SEASON, "min_history": MIN_HISTORY,
                           "max_history": MAX_HISTORY, "min_train": MIN_TRAIN, "max_windows": MAX_WINDOWS,
                           "count_mean_min": COUNT_MEAN_MIN, "mase_max": MASE_MAX, "skill_min": SKILL_MIN,
                           "coverage80_min": COV80_MIN, "seed": SEED, "models": list(MODEL_ORDER),
                           "benchmarks": list(BENCHMARKS),
                           "combination": "equal-weight mean of AutoETS, AutoARIMA and AutoTheta; its intervals are "
                                          "the average of the three component intervals",
                           "mase_scale": "in-sample seasonal naive (lag 12) MAE of each backtest training window",
                           "lower_bounds": "intervals and medians are floored at zero (all series are non-negative)"},
              "series": []}
    for spec in SERIES:
        if only and spec["id"] not in only:
            continue
        s = build_series(spec, rel)
        res = analyse(spec["id"], s["months"], s["values"], spec["is_count"])
        meta = {"title": spec["title"], "definition": spec["definition"], "unit": spec["unit"],
                "dataset": spec["dataset"], "field": spec["agg"].get("field") or spec["date_field"],
                "publisher": rel.publisher(spec["dataset"]), "collected": s["retrieved"],
                "notes": list(spec.get("notes", [])) + s["notes"]}
        result["series"].append({**{"id": res.pop("id")}, **meta, **res})
    (out / "forecast.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    with (out / "forecast.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["series", "row_type", "month", "value", "lo80", "hi80", "lo95", "hi95", "model", "decision",
                    "unit", "dataset", "data_release"])
        for s in result["series"]:
            for m, v in zip(s["history"]["months"], s["history"]["values"]):
                w.writerow([s["id"], "observed", m, v, "", "", "", "", "", s["decision"], s["unit"], s["dataset"],
                            result["release"]["release"]])
            for f in s.get("forecast", []):
                w.writerow([s["id"], "projection", f["month"], f["median"], f["lo80"], f["hi80"], f["lo95"],
                            f["hi95"], s["chosen_model"], s["decision"], s["unit"], s["dataset"],
                            result["release"]["release"]])
    for s in result["series"]:
        if s["decision"] == PUBLISH:
            (out / "charts" / f"{s['id']}.svg").write_text(svg_fan(s), encoding="utf-8")
    added = append_log(log_path, log_rows(result)) if log_path else 0
    return result, added


def actuals_from_release(dist, series_ids=None):
    rel = Release(dist)
    out = {}
    for spec in SERIES:
        if series_ids and spec["id"] not in series_ids:
            continue
        s = build_series(spec, rel)
        out[spec["id"]] = dict(zip(s["months"], s["values"]))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dist", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--log", help="forecast_log.csv to append published projections to")
    ap.add_argument("--score", help="score this forecast_log.csv against --dist (a newer release)")
    ap.add_argument("--generated-at")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args(argv)
    if a.score:
        log = read_log(a.score)
        scored = score_log(log, actuals_from_release(a.dist, sorted({r["series"] for r in log})))
        Path(a.out).mkdir(parents=True, exist_ok=True)
        with (Path(a.out) / "forecast_scores.csv").open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=SCORE_FIELDS, lineterminator="\n")
            w.writeheader()
            w.writerows(scored)
        print(json.dumps(summarise_scores(scored), indent=1))
        return 0
    result, added = run(a.dist, a.out, a.log, a.generated_at, a.only)
    for s in result["series"]:
        print(f"{s['id']:<34} n={s['history']['n_months']:<4} {s['decision']:<42} {s.get('chosen_model') or ''}")
    if a.log:
        print(f"log: {added} rows added to {a.log}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
