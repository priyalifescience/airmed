"""Offline test for the FDA drug recalls parser (fixture: five real records from openFDA's drug enforcement bulk file,
October 2026, slimmed as fetch_raw slims them)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import fda_drug_recalls as m
from airmed.privacy import check_fields, clean_record

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "fda_drug_recalls.json"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestFdaDrugRecalls(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw, min_records=1)
        self.by = {r["recall_number"]: r for r in self.rows}

    def _with(self, change):
        data = json.loads(self.raw)
        change(data["results"])
        return {r["recall_number"]: r for r in m.parse(json.dumps(data).encode(), min_records=1)}

    def test_shape(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 4)   # the record with no recall number (not yet classified) is dropped
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
        dates = [r["recall_initiation_date"] for r in self.rows]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_values(self):
        ie = self.by["D-0448-2026"]
        self.assertEqual((ie["recalling_firm"], ie["firm_country"], ie["classification"]),
                         ("GE Healthcare Ireland Limited", "Ireland", "Class II"))
        old = self.by["D-0373-2019"]
        self.assertEqual((old["classification"], old["status"], old["termination_date"]), ("Class I", "Terminated", "2021-11-03"))
        self.assertEqual(old["product_ndc"], ["47335-931", "47335-932"])
        new = self.by["D-0033-2027"]
        self.assertEqual((new["recall_initiation_date"], new["classification_date"], new["termination_date"]),
                         ("2026-09-25", "2026-10-08", ""))
        self.assertEqual((new["product_ndc"], new["firm_withheld"]), (["51672-1394"], "no"))
        self.assertTrue(all(len(r["product_description"]) <= m.DESC_MAX for r in self.rows))

    def test_phone_numbers_replaced_not_blanked(self):
        def add_phone(rows):
            rows[0]["product_description"] = "Tretinoin Cream, Dist. by Example Inc., call 866-555-0100 or help@example.com"
        r = self._with(add_phone)["D-0033-2027"]
        self.assertIn("[phone removed]", r["product_description"])
        self.assertIn("[e-mail removed]", r["product_description"])
        stats = {}
        clean_record(r, stats)
        self.assertEqual(stats.get("blanked", 0), 0)

    def test_person_like_firm_withheld_with_text(self):
        def person(rows):
            rows[0]["recalling_firm"] = "Jane Q. Doe"
            rows[0]["product_description"] = "Skin cream distributed by Jane Doe"
        r = self._with(person)["D-0033-2027"]
        self.assertEqual((r["recalling_firm"], r["firm_withheld"], r["product_description"], r["brand_name"]),
                         ("", "yes", "", []))
        self.assertTrue(r["reason_for_recall"])          # the reason does not repeat the name, so it stays

    def test_partial_file_refused(self):
        with self.assertRaises(RuntimeError):
            m.parse(self.raw)                             # default MIN_RECORDS: the real file holds ~18,000 recalls
        data = json.loads(self.raw)
        data["total_in_file"] = 99
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(data).encode(), min_records=1)

    def test_no_address_or_lot_in_fixture(self):
        text = self.raw.decode("utf-8")
        for bad in ("address_1", "postal_code", "code_info", "distribution_pattern", '"city"'):
            self.assertNotIn(bad, text)

    def test_deterministic_and_clean(self):
        self.assertEqual(self.rows, m.parse(self.raw, min_records=1))
        stats = {}
        for r in self.rows:
            clean_record(r, stats)
        self.assertEqual(stats.get("blanked", 0), 0)

    def test_registry_entry(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(src["status"], "approved")
        self.assertTrue(src["licence_url"].startswith("https://"))
        self.assertEqual(sorted(src["field_docs"]), sorted(m.FIELDS))


if __name__ == "__main__":
    unittest.main()
