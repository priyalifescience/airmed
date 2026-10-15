"""Offline test for the FAERS aggregate counts parser (fixture trimmed from real openFDA count= replies)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import faers_counts as m
from airmed.privacy import check_fields

FIXTURE = Path(__file__).parent / "fixtures" / "faers_counts.json"


class TestFaersCounts(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw)

    def test_shape(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 8)   # 2 years x (1 total + 3 drugs)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
        self.assertEqual([r["row_type"] for r in self.rows[:4]], ["year_total", "drug", "drug", "drug"])

    def test_values(self):
        total = self.rows[0]
        self.assertEqual((total["year"], total["reports"], total["serious_reports"]), (2015, 1187780, 578385))
        self.assertEqual(total["death_reports"], 99691)
        first = self.rows[1]
        self.assertEqual((first["rank"], first["drug_generic_name"], first["reports"]), (1, "ETANERCEPT", 57541))
        self.assertEqual(first["serious_reports"], 16552)
        # a drug missing from the death list is "" (below cut-off), never 0
        self.assertIn("", [r["death_reports"] for r in self.rows if r["row_type"] == "drug"])
        self.assertEqual(self.rows[1]["hospitalisation_reports"], "")

    def test_no_case_level_fields(self):
        for bad in ("safetyreportid", "patient", "reporter", "narrative"):
            self.assertFalse(any(bad in f for f in m.FIELDS))

    def test_broken_totals_raise(self):
        data = json.loads(self.raw)
        data["years"]["2015"]["serious"] = {"1": 10, "2": 10}
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(data).encode())


if __name__ == "__main__":
    unittest.main()
