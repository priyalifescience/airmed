"""Offline test for the AIFA spending and consumption files (fixture: 17 real monthly rows of the 2024 file for ATC
A10BJ, GLP-1 analogues, in Piemonte, Lombardia and Lazio, January, February and June)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import it_aifa_medicines_spending as m
from airmed.privacy import check_fields

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "it_aifa_medicines_spending.csv"
HEADER = FIXTURE.read_text(encoding="utf-8").splitlines()[0]


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestItAifaMedicinesSpending(unittest.TestCase):
    def setUp(self):
        self.annual = m.annualise(FIXTURE.read_text(encoding="utf-8"))
        self.rows = m.parse(json.dumps({"2024": self.annual}).encode("utf-8"), min_rows_per_year=0)

    def test_shape(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 2)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)

    def test_months_and_regions_added_up(self):
        a = next(r for r in self.rows if r["reimbursement_class"] == "A")
        self.assertEqual((a["year"], a["atc_code"], a["direct_purchase_packs"], a["direct_purchase_spend_eur"],
                          a["community_packs"], a["community_spend_eur"], a["months_reported"], a["regions_reported"]),
                         (2024, "A10BJ", 436783, 30517366.81, 95439, 19325742.76, 3, 3))
        self.assertEqual(a["atc_description"], "ANALOGHI DEL RECETTORE GLP-1 (GLUCAGON-LIKE PEPTIDE-1)")

    def test_empty_stays_empty_and_scientific_notation(self):
        text = HEADER + "\n" + "\n".join([
            "2024|01|010|PIEMONTE|C|A|X|A10|X|A10B|X|A10BJ|GLP-1|||1.48E2|10,5",
            "2024|02|010|PIEMONTE|C|A|X|A10|X|A10B|X|A10BJ|GLP-1|||2|1.5"])
        r = m.annualise(text)[0]
        self.assertEqual((r["direct_purchase_packs"], r["direct_purchase_spend_eur"], r["community_packs"],
                          r["community_spend_eur"]), ("", "", 150, 12.0))

    def test_wrong_year_and_too_few_rows_refused(self):
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps({"2023": self.annual}).encode("utf-8"), min_rows_per_year=0)
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps({"2024": self.annual}).encode("utf-8"))

    def test_registry_entry_matches(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(src["status"], "approved")
        self.assertEqual(list(src["field_docs"]), m.FIELDS)


if __name__ == "__main__":
    unittest.main()
