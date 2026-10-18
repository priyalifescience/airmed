"""Offline test for the CSO pharmaceutical industry statistics parser (fixture: the real PxStat JSON-stat
cubes, sliced to a few periods and categories)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import cso_pharma_industry_stats as m
from airmed.privacy import check_fields

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "cso_pharma_industry_stats.json"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestCsoPharmaIndustryStats(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw)

    def pick(self, table, stat, period, cat):
        return next(r for r in self.rows if (r["table"], r["statistic_code"], r["period"], r["category_code"])
                    == (table, stat, period, cat))

    def test_shape(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 146)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
        self.assertEqual(list(dict.fromkeys(r["table"] for r in self.rows)), list(m.TABLES))

    def test_production_index_filter(self):
        mim = [r for r in self.rows if r["table"] == "MIM05"]
        # food (10) is dropped; NACE 21 is unpublished (null) in the source, so it is left out; W0780 stays
        self.assertEqual({r["category_code"] for r in mim}, {"W0780"})
        r = self.pick("MIM05", "MIM05C01", "2026-07", "W0780")
        self.assertEqual((r["value"], r["unit"]), (122.2, "Base Year 2021=100"))
        self.assertEqual(self.pick("MIM05", "MIM05C02", "2026-07", "W0780")["value"], "")   # gap stays a gap

    def test_earnings_and_quarters(self):
        r = self.pick("EHQ58", "EHQ58C01", "2026-Q1", "C21")
        self.assertEqual((r["value"], r["unit"]), (2051.95, "Euro"))
        self.assertEqual({r["category_code"] for r in self.rows if r["table"] == "EHQ15"}, {"21"})

    def test_confidential_marker(self):
        r = self.pick("AIA30", "AIA30C12", "2021", "21")
        self.assertEqual((r["value"], r["status"]), ("", "confidential"))
        ok = self.pick("AIA30", "AIA30C04", "2021", "21")
        self.assertEqual((ok["value"], ok["status"]), (24079.0, ""))

    def test_pmma(self):
        r = self.pick("PMMA01", "PMMA01C01", "2025", "-")
        self.assertEqual(r["unit"], "Number")
        self.assertIsInstance(r["value"], float)

    def test_value_count_mismatch_refused(self):
        data = json.loads(self.raw)
        data["MIA05"]["value"].append(1.0)
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(data).encode())

    def test_missing_table_refused(self):
        data = json.loads(self.raw)
        del data["EHQ15"]
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(data).encode())

    def test_registry_entry_matches(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(src["status"], "approved")
        self.assertEqual(list(src["field_docs"]), m.FIELDS)


if __name__ == "__main__":
    unittest.main()
