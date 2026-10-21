"""Offline test for the World Bank WDI health indicators parser (fixture: real API replies, trimmed)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import worldbank_health_indicators as m
from airmed.privacy import check_fields

FIXTURE = Path(__file__).parent / "fixtures" / "worldbank_health_indicators.json"


class TestWorldbankHealthIndicators(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw)

    def test_shape(self):
        check_fields(m.FIELDS)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
        self.assertEqual({r["indicator_code"] for r in self.rows}, set(m.INDICATORS))
        self.assertTrue(all(r["value"] is not None for r in self.rows))

    def test_values(self):
        r = [x for x in self.rows if x["country_code"] == "IRL" and x["indicator_code"] == "SH.XPD.CHEX.GD.ZS"
             and x["year"] == 2022]
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["value"], 6.02078247)
        self.assertEqual((r[0]["is_aggregate"], r[0]["income_level"]), ("no", "High income"))

    def test_income_group_aggregate_matched(self):
        hic = [x for x in self.rows if x["country_code"] == "HIC"]
        self.assertTrue(hic)
        self.assertTrue(all(x["is_aggregate"] == "yes" and x["country"] == "High income" for x in hic))

    def test_other_licence_refused(self):
        bad = json.loads(self.raw)
        for v in bad["meta"]["TX.VAL.TECH.MF.ZS"]["source"][0]["concept"][0]["variable"]:
            for x in v["metatype"]:
                if x["id"] == "License_Type":
                    x["value"] = "Custom"
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(bad).encode())


if __name__ == "__main__":
    unittest.main()
