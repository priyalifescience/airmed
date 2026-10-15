"""Offline test for the Eurostat C21 pharmaceutical industry parser (fixture: real API replies, trimmed)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import eurostat_pharma_industry as m
from airmed.privacy import check_fields

FIXTURE = Path(__file__).parent / "fixtures" / "eurostat_pharma_industry.json"


class TestEurostatPharmaIndustry(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw)

    def test_shape(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 10)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
        self.assertEqual({r["dataset"] for r in self.rows}, set(m.TABLES))

    def test_uk_dropped(self):
        # UK data is outside Eurostat's commercial-reuse country list; the fixture contains it on purpose
        self.assertIn("UK", json.loads(self.raw)["sts_inpr_a"]["dimension"]["geo"]["category"]["label"])
        self.assertEqual({r["country_code"] for r in self.rows}, {"DE", "IE"})

    def test_values_and_confidential_cells(self):
        by = {(r["dataset"], r["country_code"], r["indicator_code"]): r for r in self.rows}
        emp = by[("sbs_sc_ovw", "IE", "EMP_NR")]
        self.assertEqual((emp["indicator"], emp["unit"], emp["year"], emp["value"]), ("Persons employed", "number", "2023", 28184))
        conf = by[("sbs_na_ind_r2", "IE", "V16110")]
        self.assertEqual(conf["value"], "")           # confidential: no value invented
        self.assertIn("C", conf["flags"])
        idx = by[("sts_inpr_a", "DE", "PRD_CA_I21")]
        self.assertEqual((idx["unit"], idx["value"]), ("Index, 2021=100", 99.0))

    def test_deterministic_order(self):
        self.assertEqual(self.rows, m.parse(self.raw))


if __name__ == "__main__":
    unittest.main()
