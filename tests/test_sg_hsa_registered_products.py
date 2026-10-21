"""Offline test for the Singapore HSA registered therapeutic products parser (fixture: real data.gov.sg reply, trimmed)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import sg_hsa_registered_products as m
from airmed.privacy import check_fields

FIXTURE = Path(__file__).parent / "fixtures" / "sg_hsa_registered_products.json"


class TestSgHsaRegisteredProducts(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw)

    def test_shape(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 5)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)

    def test_made_in_ireland(self):
        irl = {r["licence_no"] for r in self.rows if r["made_in_ireland"] == "yes"}
        self.assertEqual(irl, {"SIN02823P", "SIN14376P"})
        t = [r for r in self.rows if r["licence_no"] == "SIN14376P"][0]
        self.assertEqual(t["manufacturer_countries"], ["FRANCE", "IRELAND"])
        self.assertEqual(t["manufacturers"], ["Fournier Laboratories Ireland Limited", "Mylan Laboratories SAS"])

    def test_dates_and_lists(self):
        r = [r for r in self.rows if r["licence_no"] == "SIN02823P"][0]
        self.assertEqual(r["approval_date"], "1989-05-22")   # published as 22/5/1989
        multi = [r for r in self.rows if r["licence_no"] == "SIN03440P"][0]
        self.assertEqual(len(multi["active_ingredients"]), len(multi["strengths"]))
        self.assertGreater(len(multi["active_ingredients"]), 1)

    def test_partial_reply_refused(self):
        bad = json.loads(self.raw)
        bad["result"]["total"] += 1
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(bad).encode())


if __name__ == "__main__":
    unittest.main()
