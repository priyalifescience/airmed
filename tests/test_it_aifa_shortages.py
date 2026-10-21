"""Offline test for the AIFA shortage list parser (fixture: the two header lines and 5 real rows of the
20/10/2026 list, including a row whose advice ends with an office fax number)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import it_aifa_shortages as m
from airmed.privacy import check_fields, clean_record

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "it_aifa_shortages.csv"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestItAifaShortages(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw, min_rows=0)

    def row(self, aic):
        return next(r for r in self.rows if r["aic_code"] == aic)

    def test_shape(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 5)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
            self.assertEqual(r["list_date"], "2026-10-20")

    def test_values(self):
        r = self.row("045348036")
        self.assertEqual((r["medicine"], r["active_substance"], r["marketing_authorisation_holder"], r["atc_code"],
                          r["start_date"], r["expected_end_date"], r["equivalent_available"], r["reason"],
                          r["reimbursement_class"]),
                         ("ABACAVIR E LAMIVUDINA SUN", "ABACAVIR + LAMIVUDINE", "SUN PHARMA FRANCE", "J05AR02",
                          "2025-07-28", "", "Sì", "Problemi produttivi", "A CARICO DEL SSN AMBITO OSPED."))
        self.assertEqual(self.row("050312038")["expected_end_date"], "2026-12-31")
        self.assertIn("canale ospedaliero: 10/08/2026", self.row("037839115")["aifa_note"])   # multi-line note joined

    def test_office_fax_dropped_advice_kept(self):
        r = self.row("025215017")
        self.assertTrue(r["aifa_advice"].endswith("Ufficio Centrale Stupefacenti"), r["aifa_advice"])
        stats = {}
        clean_record(r, stats)
        self.assertEqual(stats, {})

    def test_too_few_rows_refused(self):
        with self.assertRaises(RuntimeError):
            m.parse(self.raw)

    def test_registry_entry_matches(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(src["status"], "approved")
        self.assertEqual(list(src["field_docs"]), m.FIELDS)


if __name__ == "__main__":
    unittest.main()
