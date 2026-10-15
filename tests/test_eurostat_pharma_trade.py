"""Offline test for the Eurostat Comext SITC 54 trade parser (fixture: real DS-059331 replies, trimmed)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import eurostat_pharma_trade as m
from airmed.privacy import check_fields

FIXTURE = Path(__file__).parent / "fixtures" / "eurostat_pharma_trade.json"


class TestEurostatPharmaTrade(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw)

    def test_shape(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 8)   # annual: 2 partners x 2 flows; monthly: 2 months x 2 flows
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)

    def test_swiss_reporter_dropped(self):
        # the fixture holds Swiss-declared data; Eurostat bars its commercial reuse, so it must never appear
        self.assertIn("CH", json.loads(self.raw)["annual"][0]["dimension"]["reporter"]["category"]["label"])
        self.assertEqual({r["reporter_code"] for r in self.rows}, {"IE"})

    def test_values(self):
        world = [r for r in self.rows if r["freq"] == "A" and r["partner_code"] == "WORLD" and r["flow"] == "export"]
        self.assertEqual(world[0]["period"], "2024")
        self.assertEqual(world[0]["value_eur"], 99661599301)
        monthly = [r for r in self.rows if r["freq"] == "M"]
        self.assertEqual(sorted({r["period"] for r in monthly}), ["2025-01", "2025-02"])

    def test_deterministic_order(self):
        self.assertEqual(self.rows, m.parse(self.raw))
        keys = [(r["freq"], r["reporter_code"], r["partner_code"], r["flow"], r["period"]) for r in self.rows]
        self.assertEqual(keys, sorted(keys))

    def test_unexpected_structure_refused(self):
        data = json.loads(self.raw)
        data["annual"][0]["id"] = data["annual"][0]["id"][:-1]
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(data).encode())


if __name__ == "__main__":
    unittest.main()
