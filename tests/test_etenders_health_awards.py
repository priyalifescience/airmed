"""Offline test for the eTenders health filter and parser (fixture: 7 real rows of the OGP eTenders open data CSV,
including two non-health rows that must be left out; in one row a real sole-trader supplier name was replaced by a
placeholder, "Jane Example Counselling Psychotherapy", so that no real person is named in the repo)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import etenders_health_awards as m
from airmed.privacy import check_fields

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "etenders_health_awards.csv"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestEtendersHealthAwards(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw, min_source_rows=0)

    def row(self, tid):
        return next(r for r in self.rows if r["tender_id"] == tid)

    def test_shape_and_filter(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 4)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
            self.assertTrue(r["health_filter"])
        ids = {r["tender_id"] for r in self.rows}
        self.assertNotIn("8974552", ids)      # Dublin City Council building works
        self.assertNotIn("9177829", ids)      # prison visitor centres: CPV 85 social work only among additional codes
        self.assertNotIn("8388341", ids)      # student counselling: CPV 853 social work, not 851 health services

    def test_award_values(self):
        r = self.row("8201217")
        self.assertEqual((r["contracting_authority"], r["published_date"], r["main_cpv_code"], r["awarded_value_eur"],
                          r["awarded_suppliers"], r["suppliers_withheld"]),
                         ("St James's Hospital", "2026-05-22", "33696500", 1568293,
                          ["Chromsystems Instruments and Chemicals GmbH"], 0))
        self.assertEqual(r["health_filter"], ["main_cpv_33", "additional_cpv_33_851", "health_authority"])
        self.assertTrue(r["ted_award_url"].startswith("https://ted.europa.eu/"))
        self.assertEqual(self.row("5719182")["health_filter"][:1], ["main_cpv_851"])
        self.assertEqual(self.row("8317704")["health_filter"], ["health_authority"])   # HPRA, IT services CPV

    def test_natural_person_supplier_withheld(self):
        self.assertEqual(m._suppliers("| Jane Example Counselling Psychotherapy | Fannin Limited"), (["Fannin Limited"], 1))
        self.assertNotIn("Jane Example", json.dumps(self.rows))

    def test_html_entities_and_separators(self):
        self.assertEqual(m._suppliers("| Ernst &amp; Young Chartered Accountants Ltd | Vodafone; KPMG Ireland Limited"),
                         (["Ernst & Young Chartered Accountants Ltd", "KPMG Ireland Limited"], 1))
        self.assertEqual(self.row("221162")["suppliers_withheld"], 1)          # "Bluett & O'Donoghue Architects"

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
