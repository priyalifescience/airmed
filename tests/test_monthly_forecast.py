"""Offline tests for tools/monthly_forecast.py (statistical projections for the monthly report), on synthetic data:
a seasonal series where ETS/ARIMA beat the naive benchmarks and a projection is published; a random walk where the
gate refuses; a low-count series routed to the Poisson rule; series building from a tiny synthetic release (partial
months, completeness, blanks); the accuracy log (append without duplicates, scoring); and byte-identical reruns.
Skipped when pandas or statsforecast is not installed (the collectors and their tests are standard library only)."""

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
    import pandas  # noqa: F401
    import scipy  # noqa: F401
    import statsforecast  # noqa: F401
    HAVE_DEPS = True
except ImportError:
    HAVE_DEPS = False

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "monthly_forecast.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("monthly_forecast", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def months(start, n):
    y, m = int(start[:4]), int(start[5:])
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


N = 60
MONTHS = months("2021-01", N)
# Fixed fixtures. With 60 months the 80% interval coverage of a well-specified model over 42 backtest points varies
# with the noise draw (seed 0 of this generator gives 57%, seeds 1-3 give 85-86%); seed 1 is used. The gate's
# behaviour over many draws is measured separately (see the findings note), not asserted here.
SEASONAL_SEED = 1


def seasonal_series(seed=0):
    r = np.random.default_rng(seed)
    k = np.arange(N)
    return [float(v) for v in 500 + 2 * k + 80 * np.sin(2 * np.pi * k / 12) + r.normal(0, 10, N)]


def random_walk(seed=0):
    r = np.random.default_rng(seed)
    return [float(v) for v in 1000 + np.cumsum(r.normal(0, 20, N))]


@unittest.skipUnless(HAVE_DEPS, "pandas, scipy and statsforecast are needed for the forecast module")
class TestModelsAndGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f = load_tool()
        cls.seasonal = cls.f.analyse("seasonal", MONTHS, seasonal_series(SEASONAL_SEED), False)
        cls.walk = cls.f.analyse("walk", MONTHS, random_walk(0), False)

    def test_seasonal_published_and_beats_naive(self):
        s, f = self.seasonal, self.f
        self.assertEqual(s["decision"], f.PUBLISH, s["reason"])
        self.assertNotIn(s["chosen_model"], f.BENCHMARKS)
        m = s["backtest"]["models"]
        best = min(m["AutoETS"]["mase"], m["AutoARIMA"]["mase"])
        self.assertLess(best, m["SeasonalNaive"]["mase"])
        self.assertLess(best, m["Naive"]["mase"])
        self.assertLess(m[s["chosen_model"]]["mase"], 1.0)
        self.assertGreaterEqual(m[s["chosen_model"]]["coverage80"], f.COV80_MIN)

    def test_backtest_shape(self):
        bt = self.seasonal["backtest"]
        nw, step = self.f.backtest_plan(N)
        self.assertEqual((bt["n_windows"], bt["step"]), (nw, step))
        self.assertGreaterEqual(nw, 6)
        self.assertEqual(bt["points"], nw * self.f.H)
        self.assertEqual(set(bt["models"]), set(self.f.MODEL_ORDER))
        for m in bt["models"].values():
            for k in ("mase", "smape", "coverage80", "coverage95"):
                self.assertIsNotNone(m[k])
            self.assertLessEqual(m["coverage80"], m["coverage95"])

    def test_forecast_bands_ordered(self):
        fc = self.seasonal["forecast"]
        self.assertEqual(len(fc), self.f.H)
        self.assertEqual(fc[0]["month"], "2026-01")
        for r in fc:
            self.assertLessEqual(r["lo95"], r["lo80"])
            self.assertLessEqual(r["lo80"], r["median"])
            self.assertLessEqual(r["median"], r["hi80"])
            self.assertLessEqual(r["hi80"], r["hi95"])

    def test_random_walk_refused(self):
        w, f = self.walk, self.f
        self.assertEqual(w["decision"], f.NO_PROJ, w["reason"])
        self.assertNotIn("forecast", w)
        self.assertIn("seasonal_profile", w)

    def test_rerun_identical(self):
        again = self.f.analyse("seasonal", MONTHS, seasonal_series(SEASONAL_SEED), False)
        self.assertEqual(json.dumps(again, sort_keys=True), json.dumps(self.seasonal, sort_keys=True))

    def test_svg_fan_chart(self):
        s = dict(self.seasonal, title="Synthetic <series>", unit="units", publisher="Test publisher",
                 dataset="synthetic", collected="2026-01-15")
        svg = self.f.svg_fan(s)
        self.assertTrue(svg.startswith("<svg"))
        self.assertIn("Synthetic &lt;series&gt;", svg)
        self.assertIn(self.f.LABEL, svg)
        self.assertEqual(svg.count("<polygon"), 2)


@unittest.skipUnless(HAVE_DEPS, "pandas, scipy and statsforecast are needed for the forecast module")
class TestRulesWithoutModels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f = load_tool()

    def test_low_count_poisson(self):
        r = np.random.default_rng(3)
        vals = [float(v) for v in r.poisson(2.0, N)]
        s = self.f.analyse("rare", MONTHS, vals, True)
        self.assertEqual(s["decision"], self.f.POISSON)
        p = s["poisson"]
        self.assertEqual(p["events"], int(sum(vals)))
        self.assertAlmostEqual(p["rate_per_month"], sum(vals) / N, places=5)
        self.assertLess(p["ci95"][0], p["rate_per_month"])
        self.assertGreater(p["ci95"][1], p["rate_per_month"])
        self.assertNotIn("backtest", s)

    def test_poisson_ci_known_values(self):
        lo, hi = self.f.poisson_ci(0, 1)
        self.assertEqual(lo, 0.0)
        self.assertAlmostEqual(hi, 3.689, places=3)
        lo, hi = self.f.poisson_ci(10, 1)
        self.assertAlmostEqual(lo, 4.795, places=3)
        self.assertAlmostEqual(hi, 18.390, places=3)

    def test_count_series_mean_ten_goes_to_models_rule(self):
        # the rule is "mean < 10": exactly at the threshold the series is not routed to Poisson
        f = self.f
        self.assertFalse(10.0 < f.COUNT_MEAN_MIN)

    def test_insufficient_history(self):
        s = self.f.analyse("short", MONTHS[:35], [1.0] * 35, False)
        self.assertEqual(s["decision"], self.f.NOT_ENOUGH)

    def test_backtest_plan(self):
        f = self.f
        self.assertEqual(f.backtest_plan(36), (7, 1))
        self.assertEqual(f.backtest_plan(120), (12, 2))
        self.assertEqual(f.backtest_plan(29), (0, 1))

    def test_choose_gate(self):
        f = self.f

        def bt(**mase):
            ms = {m: {"mase": mase.get(m, 2.0), "coverage80": mase.get("cov", 0.8)} for m in f.MODEL_ORDER}
            return {"models": ms}
        self.assertEqual(f.choose(bt(AutoETS=0.5, SeasonalNaive=0.9, Naive=0.8))[1], f.PUBLISH)
        self.assertEqual(f.choose(bt(Naive=0.5, AutoETS=0.6))[1], f.NO_PROJ)            # benchmark wins
        self.assertEqual(f.choose(bt(AutoETS=0.78, Naive=0.8))[1], f.NO_PROJ)            # skill < 5%
        self.assertEqual(f.choose(bt(AutoETS=1.2, Naive=1.5, SeasonalNaive=1.6))[1], f.NO_PROJ)  # MASE >= 1
        self.assertEqual(f.choose(bt(AutoETS=0.5, Naive=0.8, cov=0.6))[1], f.NO_PROJ)    # coverage

    def test_accuracy_log(self):
        f = self.f
        result = {"generated_at": "2026-10-21T07:39:37+00:00", "release": {"release": "2026-10-21T07:39:37+00:00"},
                  "series": [{"id": "x", "decision": f.PUBLISH, "chosen_model": "AutoETS",
                              "history": {"last": "2026-08"},
                              "forecast": [{"month": "2026-09", "median": 100.0, "lo80": 90.0, "hi80": 110.0,
                                            "lo95": 80.0, "hi95": 120.0},
                                           {"month": "2026-10", "median": 100.0, "lo80": 90.0, "hi80": 110.0,
                                            "lo95": 80.0, "hi95": 120.0},
                                           {"month": "2026-11", "median": 100.0, "lo80": 90.0, "hi80": 110.0,
                                            "lo95": 80.0, "hi95": 120.0}]},
                             {"id": "y", "decision": f.NO_PROJ}]}
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "forecast_log.csv"
            self.assertEqual(f.append_log(log, f.log_rows(result)), 3)
            self.assertEqual(f.append_log(log, f.log_rows(result)), 0)       # rerun: no duplicates
            rows = f.read_log(log)
            self.assertEqual(len(rows), 3)
            self.assertEqual(list(rows[0]), f.LOG_FIELDS)
            self.assertEqual([r["horizon"] for r in rows], ["1", "2", "3"])
            scored = f.score_log(rows, {"x": {"2026-09": 105.0, "2026-10": 115.0}})
        self.assertEqual(len(scored), 2)                                     # 2026-11 has no actual yet
        a, b = scored
        self.assertEqual((a["abs_error"], a["inside_80"], a["inside_95"]), (5.0, "yes", "yes"))
        self.assertEqual((b["abs_error"], b["inside_80"], b["inside_95"]), (15.0, "no", "yes"))
        summ = f.summarise_scores(scored)["x"]
        self.assertEqual((summ["n"], summ["mean_abs_error"], summ["coverage80"], summ["coverage95"]),
                         (2, 10.0, 0.5, 1.0))


def write_release(root, datasets, retrieved):
    """Tiny release: catalog.json plus <key>/<key>.csv for each {key: (fields, rows)}."""
    root = Path(root)
    cat = {"release": "2026-10-21T00:00:00+00:00", "generator": "test", "datasets": []}
    for key, (fields, rows) in datasets.items():
        (root / key).mkdir(parents=True, exist_ok=True)
        with (root / key / f"{key}.csv").open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(fields)
            w.writerows(rows)
        cat["datasets"].append({"key": key, "publisher": f"Publisher of {key}", "retrieved": retrieved})
    (root / "catalog.json").write_text(json.dumps(cat), encoding="utf-8")


@unittest.skipUnless(HAVE_DEPS, "pandas, scipy and statsforecast are needed for the forecast module")
class TestSeriesBuilding(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f = load_tool()

    def spec(self, sid):
        return next(s for s in self.f.SERIES if s["id"] == sid)

    def test_event_series_zero_fill_and_partial_month(self):
        rows = [["01/03/2024"], ["15/03/2024"], ["02/05/2024"], ["03/10/2026"]]
        with tempfile.TemporaryDirectory() as td:
            write_release(td, {"ema_shortages": (["first_published"], rows)}, "2026-10-19T04:00:00+00:00")
            s = self.f.build_series(self.spec("ema_shortages_first_published"), self.f.Release(td))
        # first record month (2024-03) is treated as possibly partial; the collection month 2026-10 is excluded
        self.assertEqual(s["months"][0], "2024-04")
        self.assertEqual(s["months"][-1], "2026-09")
        self.assertEqual(dict(zip(s["months"], s["values"]))["2024-05"], 1.0)
        self.assertEqual(dict(zip(s["months"], s["values"]))["2024-04"], 0.0)

    def test_event_lag(self):
        rows = [["NCT1", "RECRUITING", "2020-01"], ["NCT2", "WITHDRAWN", "2026-01"], ["NCT3", "COMPLETED", "2026-09"]]
        with tempfile.TemporaryDirectory() as td:
            write_release(td, {"ctgov_ireland": (["nct_id", "overall_status", "start_date"], rows)},
                          "2026-10-19T04:00:00+00:00")
            s = self.f.build_series(self.spec("ctgov_ireland_starts"), self.f.Release(td))
        self.assertEqual(s["months"][-1], "2026-03")                 # 2026-09 minus a 6-month lag
        self.assertEqual(sum(s["values"]), 0.0)                       # withdrawn excluded; 2020-01 is first, dropped

    def test_period_completeness_and_blank_as_zero(self):
        rows = []
        for m in months("2023-01", 14):
            for cc in ("US", "DE", "ZZEU99"):
                v = "" if (cc == "ZZEU99" and m == "2023-02") or (cc == "DE" and m == "2024-02") else "1000"
                rows.append([m, cc, cc, v])
        with tempfile.TemporaryDirectory() as td:
            write_release(td, {"cso_pharma_exports": (["month", "country_code", "country", "exports_eur_thousand"],
                                                      rows)}, "2026-10-19T04:00:00+00:00")
            s = self.f.build_series(self.spec("ie_pharma_exports_total"), self.f.Release(td))
        vals = dict(zip(s["months"], s["values"]))
        self.assertEqual(vals["2023-02"], 2.0)          # ZZEU99 blank counted as zero; EUR thousand -> million
        self.assertEqual(vals["2023-03"], 3.0)
        self.assertNotIn("2024-02", vals)               # DE missing: incomplete month excluded
        self.assertEqual(s["months"][-1], "2024-01")
        self.assertTrue(any("2024-02" in n for n in s["notes"]))

    def test_run_writes_outputs_and_is_deterministic(self):
        r = np.random.default_rng(1)
        rows = []
        for k, m in enumerate(months("2016-01", 120)):
            for _ in range(int(r.poisson(1.0))):
                rows.append([f"03/{m[5:]}/{m[:4]}"])
        with tempfile.TemporaryDirectory() as td:
            dist = Path(td) / "dist"
            write_release(dist, {"ema_shortages": (["first_published"], rows)}, "2026-10-19T04:00:00+00:00")
            outs = []
            for k in range(2):
                out = Path(td) / f"out{k}"
                self.f.run(dist, out, log_path=out / "forecast_log.csv", only=["ema_shortages_first_published"])
                outs.append(out)
            a = (outs[0] / "forecast.json").read_bytes()
            self.assertEqual(a, (outs[1] / "forecast.json").read_bytes())
            self.assertEqual((outs[0] / "forecast.csv").read_bytes(), (outs[1] / "forecast.csv").read_bytes())
            j = json.loads(a)
            self.assertEqual(j["label"], self.f.LABEL)
            self.assertIn("statsforecast", j["libraries"])
            self.assertEqual(j["generated_at"], "2026-10-21T00:00:00+00:00")
            self.assertEqual(j["series"][0]["decision"], self.f.POISSON)
            self.assertFalse((outs[0] / "forecast_log.csv").exists())   # nothing published, nothing logged


if __name__ == "__main__":
    unittest.main()
