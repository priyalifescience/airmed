"""Offline test for the Health Canada Notice of Compliance parser (fixture: real API records, trimmed)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import hc_notice_of_compliance as m
from airmed.privacy import check_fields

FIXTURE = Path(__file__).parent / "fixtures" / "hc_notice_of_compliance.json"


class TestHcNoticeOfCompliance(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw)

    def test_shape(self):
        check_fields(m.FIELDS)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)

    def test_admin_and_veterinary_left_out(self):
        self.assertEqual([r["noc_number"] for r in self.rows], [38500, 19914, 17732, 23106, 23097])
        self.assertEqual({r["submission_type"] for r in self.rows}, {"NDS", "SNDS", "ANDS", "SANDS"})

    def test_values(self):
        r = self.rows[0]
        self.assertEqual((r["noc_date"], r["company"], r["submission_type"], r["is_supplement"]),
                         ("2026-10-20", "MYLAN PHARMACEUTICALS ULC", "SANDS", "yes"))
        self.assertIn("RIVASTIGMINE 9.5 MG per DAY", r["ingredients"])
        self.assertEqual(r["reference_company"], "NOVARTIS PHARMACEUTICALS CANADA INC")
        nds = [x for x in self.rows if x["noc_number"] == 23106][0]
        self.assertEqual(nds["brand_names"], ["OSNUVO"])

    def test_unknown_submission_type_refused(self):
        bad = json.loads(self.raw)
        bad["noticeofcompliancemain"][0]["noc_on_submission_type"] = "Something new"
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(bad).encode())


if __name__ == "__main__":
    unittest.main()
