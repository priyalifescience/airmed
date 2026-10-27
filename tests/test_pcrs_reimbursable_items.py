"""Offline test for the HSE-PCRS reimbursable items parser (fixture: the full list and the eight category lists as
downloaded on 27/10/2026, cut to 5 real items: a reference-priced drug, a High Tech drug with no published price,
an item on two lists, a nutrition product and an item on the full list only)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import pcrs_reimbursable_items as m
from airmed.privacy import check_fields

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "pcrs_reimbursable_items.json"


class TestPcrsReimbursableItems(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw, min_rows=0)

    def row(self, code):
        return next(r for r in self.rows if r["code"] == code)

    def test_shape(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 5)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)

    def test_reference_priced_drug(self):
        r = self.row("11921")
        self.assertEqual((r["item"], r["inn"], r["pack_size"], r["strength"], r["reimbursement_price_eur"],
                          r["reference_price_eur"], r["reference_priced"], r["categories"]),
                         ("Abilify Tabs. 5 mg. 28 (A)", "ARIPIPRAZOLE", "28", "5MG", "66.85", "10.5784", "yes", "Drugs"))

    def test_high_tech_price_is_blank_not_zero(self):
        r = self.row("88522")
        self.assertEqual((r["reimbursement_price_eur"], r["reference_price_eur"], r["inn"]), ("", "", "USTEKINUMAB"))
        self.assertEqual(r["categories"], "Drugs; High Tech Drugs")

    def test_lists(self):
        self.assertEqual(self.row("85170")["categories"], "Dressings; Syringes, Needles and Lancets")
        self.assertEqual(self.row("81020")["categories"], "Clinical Nutritional Products")
        self.assertEqual(self.row("43511")["categories"], "")

    def test_missing_list_fails(self):
        lists = json.loads(self.raw)
        del lists["9"]
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(lists).encode("utf-8"), min_rows=0)

    def test_changed_columns_fail(self):
        lists = json.loads(self.raw)
        lists["0"] = lists["0"].replace("Reimbursement Price", "Price", 1)
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(lists).encode("utf-8"), min_rows=0)

    def test_too_few_rows_fail(self):
        with self.assertRaises(RuntimeError):
            m.parse(self.raw)

    def test_registry(self):
        src = json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][m.KEY]
        self.assertEqual(src["status"], "approved")
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(sorted(src["field_docs"]), sorted(m.FIELDS))
        self.assertIn("does not endorse", src["attribution"])


if __name__ == "__main__":
    unittest.main()
