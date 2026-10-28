"""Offline tests for tools/monthly_trends.py (the monthly trend report engine), on a tiny synthetic release built in
a temporary directory: month selection, partial-month exclusion, month-on-month and year-on-year maths, the small-n
rule, 12-month windows, shares and byte-identical reruns. Skipped when pandas is not installed (the collectors and
their tests are standard library only; the report engine is not)."""

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

try:
    import pandas  # noqa: F401
    HAVE_PANDAS = True
except ImportError:
    HAVE_PANDAS = False

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "tools" / "monthly_trends.py"


def load_engine():
    spec = importlib.util.spec_from_file_location("monthly_trends", ENGINE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def months(start, end):
    y, m = int(start[:4]), int(start[5:])
    out = []
    while f"{y:04d}-{m:02d}" <= end:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


MONTHS = months("2024-09", "2026-09")          # 25 complete months in the fixture
EVENT_COUNT = {ym: 30 + i for i, ym in enumerate(MONTHS)}   # 2024-09 -> 30 ... 2026-09 -> 54


def write_csv(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def build_release(d):
    d = Path(d)
    # events: EVENT_COUNT[m] rows per month, every 10th row has flag "x"; plus 7 rows in October 2026 (partial)
    rows = []
    for ym, n in EVENT_COUNT.items():
        for k in range(n):
            rows.append([f"{ym}-{(k % 28) + 1:02d}", "x" if k % 10 == 0 else "y"])
    rows += [["2026-10-02", "y"]] * 7
    write_csv(d / "ev" / "ev.csv", ["event_date", "flag"], rows)
    # the same events, but collected in mid-September: September is not complete
    write_csv(d / "ev_mid" / "ev_mid.csv", ["event_date", "flag"], [r for r in rows if r[0] <= "2026-09-15"])
    # a source whose records stop on 15 July 2026 although it was collected in October
    write_csv(d / "ev_stale" / "ev_stale.csv", ["event_date", "flag"], [r for r in rows if r[0] <= "2026-07-15"])
    # small counts: 5 per month, 8 in September 2026
    small = []
    for ym in MONTHS:
        small += [[f"{ym}-03"]] * (8 if ym == "2026-09" else 5)
    write_csv(d / "small" / "small.csv", ["event_date"], small)
    # a period dataset: 3 regions per month; August 2026 has only one region so far (partial)
    per = []
    for i, ym in enumerate(months("2024-08", "2026-07")):
        for j, reg in enumerate(["A", "B", "C"]):
            per.append([ym, reg, str(100 + i + j)])
    per.append(["2026-08", "A", "999"])
    write_csv(d / "per" / "per.csv", ["month", "region", "value"], per)
    cat = {"name": "Synthetic release", "generator": "airmed test", "release": "2026-10-06T00:00:00+00:00",
           "api_version": "v1", "datasets": []}
    for key, ret in (("ev", "2026-10-05"), ("ev_mid", "2026-09-20"), ("ev_stale", "2026-10-05"),
                     ("small", "2026-10-05"), ("per", "2026-10-05")):
        cat["datasets"].append({"key": key, "title": f"Test {key}", "publisher": "Test Publisher",
                                "licence": "CC BY 4.0", "licence_url": "https://creativecommons.org/licenses/by/4.0/",
                                "attribution": "Source: Test Publisher", "records": 1,
                                "retrieved": f"{ret}T04:00:00+00:00"})
    (d / "catalog.json").write_text(json.dumps(cat), encoding="utf-8")


def ind(id_, dataset, **kw):
    base = {"id": id_, "section": "Test", "title": f"Test {id_}", "definition": "test", "unit": "events",
            "datasets": [dataset], "kind": "event", "frequency": "month", "date_field": "event_date",
            "date_format": "iso", "filter": [], "aggregation": {"type": "count"}, "window": 1, "lag_months": 0,
            "min_n": 20, "decimals": 0}
    base.update(kw)
    return base


INDICATORS = {
    "version": "test",
    "sections": ["Test"],
    "indicators": [
        ind("ev_count", "ev"),
        ind("ev_mid_count", "ev_mid"),
        ind("ev_stale_count", "ev_stale"),
        ind("ev_lag2", "ev", lag_months=2),
        ind("small_count", "small"),
        ind("ev_12m", "ev", window=12),
        ind("ev_share", "ev", unit="percent", decimals=2,
            aggregation={"type": "share", "measure": "count",
                         "numerator_filter": [{"field": "flag", "op": "eq", "value": "x"}]}),
        ind("per_sum", "per", kind="period", date_field="month", unit="units", min_n=None,
            aggregation={"type": "sum", "field": "value"}, completeness={"key": "region", "min_ratio": 1.0}),
    ],
}


@unittest.skipUnless(HAVE_PANDAS, "pandas not installed")
class TestMonthlyTrends(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_engine()
        cls.tmp = tempfile.TemporaryDirectory()
        t = Path(cls.tmp.name)
        cls.dist = t / "dist"
        build_release(cls.dist)
        cls.ind_path = t / "indicators.json"
        cls.ind_path.write_text(json.dumps(INDICATORS), encoding="utf-8")
        cls.out = t / "out"
        cls.rep = cls.m.run(cls.dist, "2026-10", cls.out, cls.ind_path)
        cls.by = {r["id"]: r for r in cls.rep["indicators"]}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_no_errors(self):
        self.assertEqual(self.rep["errors"], [])
        self.assertEqual(len(self.by), len(INDICATORS["indicators"]))

    def test_month_selection_latest_complete_before_edition(self):
        r = self.by["ev_count"]
        self.assertEqual(r["reference_period"], "2026-09")
        self.assertEqual(r["reference_label"], "September 2026")
        self.assertEqual(r["previous"]["period"], "2026-08")
        self.assertEqual(r["year_ago"]["period"], "2025-09")
        self.assertEqual(r["periods_behind_edition"], 0)
        self.assertNotIn("data_lag", r["flags"])

    def test_partial_month_excluded_when_collected_mid_month(self):
        r = self.by["ev_mid_count"]
        self.assertEqual(r["reference_period"], "2026-08")    # September was still running at collection
        self.assertEqual(r["value"], EVENT_COUNT["2026-08"])
        self.assertIn("data_lag", r["flags"])

    def test_partial_month_excluded_when_source_stops_early(self):
        r = self.by["ev_stale_count"]
        self.assertEqual(r["reference_period"], "2026-06")    # last record 15 July: July is partial
        self.assertIn("partial_period_excluded", r["flags"])
        self.assertIn("source_stale", r["flags"])
        self.assertEqual(r["flag_details"]["partial_period_excluded"], "2026-07")

    def test_publication_lag_steps_back(self):
        self.assertEqual(self.by["ev_lag2"]["reference_period"], "2026-07")

    def test_mom_yoy_maths(self):
        r = self.by["ev_count"]
        cur, prev, yago = EVENT_COUNT["2026-09"], EVENT_COUNT["2026-08"], EVENT_COUNT["2025-09"]
        self.assertEqual(r["value"], cur)
        self.assertEqual(r["previous"]["value"], prev)
        self.assertEqual(r["year_ago"]["value"], yago)
        self.assertEqual(r["change"]["mom_abs"], cur - prev)
        self.assertEqual(r["change"]["yoy_abs"], cur - yago)
        self.assertAlmostEqual(r["change"]["mom_pct"], round(100 * (cur - prev) / prev, 2))
        self.assertAlmostEqual(r["change"]["yoy_pct"], round(100 * (cur - yago) / yago, 2))
        self.assertEqual(r["flags"], [])

    def test_october_rows_ignored(self):
        self.assertEqual(self.by["ev_count"]["value"], EVENT_COUNT["2026-09"])

    def test_small_n_withholds_percentages(self):
        r = self.by["small_count"]
        self.assertEqual(r["value"], 8)
        self.assertEqual(r["change"]["mom_abs"], 3)
        self.assertEqual(r["change"]["yoy_abs"], 3)
        self.assertIsNone(r["change"]["mom_pct"])
        self.assertIsNone(r["change"]["yoy_pct"])
        self.assertIn("small_n", r["flags"])

    def test_twelve_month_window(self):
        r = self.by["ev_12m"]
        ms = MONTHS[-12:]
        self.assertEqual(r["value"], sum(EVENT_COUNT[m] for m in ms))
        self.assertEqual(r["reference_label"], "12 months to September 2026")
        self.assertEqual(r["previous"]["value"], sum(EVENT_COUNT[m] for m in MONTHS[-13:-1]))
        # 2024-09 is the first month in the data and is treated as possibly partial, so the year-ago window is
        # 2024-10..2025-09 and the series cannot reach back past 12 months to 2025-09
        self.assertEqual(r["year_ago"]["value"], sum(EVENT_COUNT[m] for m in MONTHS[1:13]))
        self.assertEqual(r["series"][0]["period"], "2025-09")
        self.assertEqual(r["coverage"]["first_complete"], "2024-10")

    def test_share_in_percentage_points(self):
        r = self.by["ev_share"]
        n = EVENT_COUNT["2026-09"]
        x = len(range(0, n, 10))
        self.assertAlmostEqual(r["value"], round(100 * x / n, 6))
        self.assertEqual(r["change_unit"], "percentage points")
        self.assertEqual(r["n"], x)
        self.assertEqual(r["denominator_n"], n)

    def test_period_dataset_partial_month_excluded(self):
        r = self.by["per_sum"]
        self.assertEqual(r["reference_period"], "2026-07")
        self.assertIn("partial_period_excluded", r["flags"])
        i = len(months("2024-08", "2026-07")) - 1
        self.assertEqual(r["value"], (100 + i) * 3 + 3)       # regions A, B, C: 100+i, 101+i, 102+i
        self.assertEqual(r["change"]["mom_abs"], 3)
        self.assertEqual(r["change"]["yoy_abs"], 36)

    def test_outputs_and_sources(self):
        for f in ("report.json", "indicators.csv", "series.csv", "charts/ev_count.svg"):
            self.assertTrue((self.out / f).exists(), f)
        self.assertTrue((self.out / "charts" / "ev_count.svg").read_text(encoding="utf-8").startswith("<svg"))
        src = self.rep["sources"]["ev"]
        self.assertEqual(src["publisher"], "Test Publisher")
        self.assertEqual(src["licence"], "CC BY 4.0")
        self.assertEqual(src["collected"], "2026-10-05T04:00:00+00:00")
        self.assertEqual(len(src["file_sha256"]), 64)
        self.assertEqual(self.rep["generated_at"], "2026-10-06T00:00:00+00:00")
        self.assertEqual(len(self.by["ev_count"]["series"]), 24)

    def test_deterministic(self):
        out2 = Path(self.tmp.name) / "out2"
        self.m.run(self.dist, "2026-10", out2, self.ind_path)
        files = sorted(p.relative_to(self.out).as_posix() for p in self.out.rglob("*") if p.is_file())
        self.assertTrue(files)
        for f in files:
            self.assertEqual((self.out / f).read_bytes(), (out2 / f).read_bytes(), f)

    def test_real_indicator_file_is_valid(self):
        cfg = json.loads((ROOT / "tools" / "trends_indicators.json").read_text(encoding="utf-8"))
        ids = [s["id"] for s in cfg["indicators"]]
        self.assertEqual(len(ids), len(set(ids)))
        for s in cfg["indicators"]:
            for k in ("id", "section", "title", "definition", "unit", "datasets", "kind", "date_field",
                      "aggregation", "min_n"):
                self.assertIn(k, s, f"{s.get('id')}: {k}")
            self.assertIn(s["section"], cfg["sections"])
            self.assertIn(s["kind"], ("event", "period", "snapshot"))


if __name__ == "__main__":
    unittest.main()
