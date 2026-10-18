"""Offline test for the EMA PRIME list parser (fixture: EMA's PRIME workbook trimmed to 4 current and 10 previous
medicines plus the header and footnote rows; document properties and external links removed)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import ema_prime as m
from airmed.privacy import check_fields

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "ema_prime.xlsx"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestEmaPrime(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw, min_records=1)
        self.by = {(r["name"], r["therapeutic_indication"]): r for r in self.rows}

    def test_registry_entry(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["status"], "approved")
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(set(src["field_docs"]), set(m.FIELDS))
        check_fields(m.FIELDS)

    def test_shape_and_order(self):
        self.assertEqual(len(self.rows), 14)
        self.assertEqual(sum(r["prime_list"] == "current" for r in self.rows), 4)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
            self.assertRegex(r["prime_granted_date"], r"^\d{4}-\d{2}-\d{2}$")
            self.assertEqual(r["list_date"], "2026-09-23")
        keys = [(r["prime_list"], r["name"].lower(), r["prime_granted_date"], r["therapeutic_indication"])
                for r in self.rows]
        self.assertEqual(keys, sorted(keys))

    def test_current_record(self):
        r = self.by[("4D-150", "Treatment of neovascular (wet) age-related macular degeneration (wet AMD)")]
        self.assertEqual((r["substance_type"], r["therapeutic_area"], r["applicant_type"], r["prime_granted_date"]),
                         ("Advanced Therapy Medicinal Product", "Ophthalmology", "SME", "2023-10-12"))
        self.assertEqual((r["prime_list"], r["status"], r["early_entry"]),
                         ("current", "Currently in PRIME scheme", "no"))

    def test_early_entry_from_italics(self):
        r = self.by[("CTI-1601", "Treatment of Friedreich's Ataxia")]
        self.assertEqual(r["early_entry"], "yes")

    def test_previous_status_lines(self):
        r = self.by[("Tisagenlecleucel (Kymriah)", "Treatment of paediatric patients with relapsed or refractory "
                     "B cell acute lymphoblastic leukaemia")]
        self.assertEqual((r["prime_list"], r["status"]), ("previous", "Authorised, see EPAR"))
        r = self.by[("Valoctocogene roxaparvovec (Roctavian)", "Treatment of haemophilia A")]
        self.assertEqual(r["status"], "Marketing authorisation application withdrawn; Resubmission - Authorised, see EPAR")

    def test_footnotes_not_records(self):
        self.assertFalse(any(r["name"].startswith(("*", "SME", "Product(s)")) for r in self.rows))

    def test_excel_date(self):
        self.assertEqual(m.excel_date("45211"), "2023-10-12")
        self.assertEqual(m.excel_date("12/10/2023"), "2023-10-12")
        self.assertEqual(m.excel_date("7"), "")

    def test_partial_dataset_refused(self):
        with self.assertRaises(RuntimeError):
            m.parse(self.raw)


if __name__ == "__main__":
    unittest.main()
