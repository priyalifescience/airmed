"""Offline test for the OECD pharmaceutical spending parser (fixture: real SDMX CSV reply, trimmed)."""

import unittest
from pathlib import Path

from airmed.collectors import oecd_pharma_spending as m
from airmed.privacy import check_fields

FIXTURE = Path(__file__).parent / "fixtures" / "oecd_pharma_spending.csv"


class TestOecdPharmaSpending(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw)

    def test_shape(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 48)   # 2 countries x 2 financing x 6 unit/price combos x 2 years
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)

    def test_values(self):
        r = [x for x in self.rows if x["country_code"] == "IRL" and x["financing_code"] == "_T"
             and x["unit_code"] == "PT_EXP_HLTH" and x["year"] == "2022"]
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["value"], 10.908)
        self.assertEqual(r[0]["function"], "Pharmaceuticals and other medical non-durable goods")
        xdc = [x for x in self.rows if x["unit_code"] == "XDC"]
        self.assertTrue(all(x["unit_multiplier"] == "Millions" for x in xdc))

    def test_deterministic_order(self):
        self.assertEqual(self.rows, m.parse(self.raw))

    def test_missing_column_refused(self):
        bad = self.raw.decode("utf-8").replace("OBS_VALUE", "OBS_VAL", 1).encode()
        with self.assertRaises(RuntimeError):
            m.parse(bad)


if __name__ == "__main__":
    unittest.main()
