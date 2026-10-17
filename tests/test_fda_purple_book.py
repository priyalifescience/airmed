"""Offline test for the FDA Purple Book parser (fixture: real September 2026 monthly CSV trimmed to 6 products)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import fda_purple_book as m
from airmed.privacy import check_fields

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "fda_purple_book.csv"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestFdaPurpleBook(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw, min_records=1)
        self.by = {r["bla_number"]: r for r in self.rows}

    def test_registry_entry(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["status"], "approved")
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(set(src["field_docs"]), set(m.FIELDS))
        check_fields(m.FIELDS)

    def test_shape(self):
        # only the all-products section is used; the 2 rows in the monthly changes section are not double counted
        self.assertEqual(len(self.rows), 6)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
            self.assertEqual(r["data_month"], "2026-09")
        keys = [(r["bla_number"], r["product_number"]) for r in self.rows]
        self.assertEqual(keys, sorted(keys))

    def test_values(self):
        ruc = self.by["125495"]
        self.assertEqual((ruc["proprietary_name"], ruc["license_type"], ruc["center"]), ("Ruconest", "351(a)", "CBER"))
        self.assertEqual((ruc["date_of_first_licensure"], ruc["ref_product_exclusivity_expiry"], ruc["orphan_exclusivity_expiry"]),
                         ("2014-07-16", "2026-07-16", "2021-07-16"))
        ic = self.by["761450"]
        self.assertEqual((ic["license_type"], ic["ref_product_proprietary_name"], ic["interchangeable_approval_date"]),
                         ("351(k) Interchangeable", "Perjeta", "2025-11-13"))
        self.assertEqual(ic["first_interchangeable_exclusivity_expiry"], "Date TBD")   # non-date text kept as written
        self.assertEqual(self.by["761133"]["date_of_first_licensure"], "Not Eligible")
        self.assertEqual(self.by["761133"]["dosage_form"], "Injection")                # stray trailing space trimmed
        self.assertEqual(self.by["125276"]["patent_list_provided"], "yes")
        self.assertEqual(self.by["761378"]["license_type"], "351(k) Biosimilar")

    def test_latest_link(self):
        page = ('<a href="https://www.accessdata.fda.gov/drugsatfda_docs/PurpleBook/2026/purplebook-search-February-data-download.csv">'
                '<a href="https://www.accessdata.fda.gov/drugsatfda_docs/PurpleBook/2026/purplebook-search-september-data-download.csv">'
                '<a href="https://www.accessdata.fda.gov/drugsatfda_docs/PurpleBook/2025/purplebook-search-december-data-download.csv">')
        self.assertTrue(m.latest_csv_url(page).endswith("2026/purplebook-search-september-data-download.csv"))
        with self.assertRaises(RuntimeError):
            m.latest_csv_url("<html></html>")

    def test_duplicate_product_raises(self):
        lines = self.raw.decode("utf-8").splitlines()
        with self.assertRaises(RuntimeError):
            m.parse(("\n".join(lines + [lines[-1]]) + "\n").encode(), min_records=1)

    def test_partial_dataset_refused(self):
        with self.assertRaises(RuntimeError):
            m.parse(self.raw)


if __name__ == "__main__":
    unittest.main()
