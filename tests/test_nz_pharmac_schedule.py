"""Offline test for the PHARMAC Pharmaceutical Schedule parser (fixture: the real October 2026 XML, pruned)."""

import unittest
from pathlib import Path

from airmed.collectors import nz_pharmac_schedule as m
from airmed.privacy import check_fields

FIXTURE = Path(__file__).parent / "fixtures" / "nz_pharmac_schedule.xml"


class TestNzPharmacSchedule(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw)

    def test_shape(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 11)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
            self.assertEqual(r["edition"], "October 2026")

    def test_values(self):
        g = [r for r in self.rows if r["pack_id"] == "P494275"][0]
        self.assertEqual((g["chemical"], g["brand"], g["quantity"], g["subsidy"], g["price"]),
                         ("Alginic acid", "Gaviscon Infant", 30, 8.06, 8.06))
        self.assertEqual(g["therapeutic_group_code"], "A010102")

    def test_restrictions_inherited(self):
        b = [r for r in self.rows if r["pack_id"] == "P2661454"][0]
        self.assertEqual((b["special_authority_forms"], b["rules"], b["restricted"]),
                         (["SA2535"], ["Special:Subsidy"], "yes"))
        d = [r for r in self.rows if r["section"].startswith("D ")]
        self.assertEqual(d[0]["special_authority_forms"], ["SA1930"])
        self.assertEqual(sum(r["restricted"] == "no" for r in self.rows), 9)

    def test_wrong_document_refused(self):
        with self.assertRaises(RuntimeError):
            m.parse(b"<Other/>")


if __name__ == "__main__":
    unittest.main()
