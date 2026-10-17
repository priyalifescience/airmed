"""Offline test for the FDA warning letters parser (fixture trimmed from the real FDA listing JSON; the one clinical
investigator row has its name replaced by a placeholder)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import fda_warning_letters as m
from airmed.privacy import check_fields

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "fda_warning_letters.json"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestFdaWarningLetters(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw)
        self.by = {r["company"]: r for r in self.rows}

    def test_shape_and_scope(self):
        check_fields(m.FIELDS)
        # 10 listing rows: tobacco, human food and veterinary letters are out of scope
        self.assertEqual(len(self.rows), 7)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
            self.assertTrue(r["product_area"])
        for gone in ("Smart Vending Services, LLC", "Dreyer’s Grand Ice Cream, Inc.", "Lewis Sausage Company Inc."):
            self.assertNotIn(gone, self.by)
        dates = [r["letter_issue_date"] for r in self.rows]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_values(self):
        r = self.by["Eurofins SF Analytical Laboratories, Inc."]
        self.assertEqual((r["letter_issue_date"], r["posted_date"]), ("2026-10-06", "2026-10-13"))
        self.assertEqual(r["product_area"], ["drugs"])
        self.assertEqual(r["fda_case_number"], "736056")
        self.assertTrue(r["url"].startswith("https://www.fda.gov/inspections-compliance-enforcement-and-criminal-investigations/warning-letters/"))
        self.assertEqual(self.by["Thrive Health and Wellness, LLC dba Thrive Health Solutions"]["closeout_date"], "2026-08-06")
        self.assertEqual(self.by["Synaptent, LLC"]["response_letter_date"], "2022-02-01")
        self.assertEqual(self.by["Synaptent, LLC"]["product_area"], ["drugs"])        # kept on its subject
        self.assertEqual(self.by["Koven Technologies, Inc."]["product_area"], ["devices"])
        self.assertIn("biologics", self.by["Blue Horizon International, LLC"]["product_area"])
        self.assertIn("Sanofi", self.by)                                               # single-word trading name

    def test_person_names_withheld(self):
        withheld = [r for r in self.rows if r["company_withheld"] == "yes"]
        self.assertEqual(len(withheld), 1)
        w = withheld[0]
        self.assertEqual((w["company"], w["url"], w["fda_case_number"]), ("", "", ""))
        self.assertEqual(w["subject"], "Clinical Investigator")
        self.assertNotIn("Placeholder", json.dumps(self.rows))

    def test_company_rules(self):
        self.assertEqual(m.company_or_blank("Makra Kozmetika D.O.O.", "CGMP"), "Makra Kozmetika D.O.O.")
        self.assertEqual(m.company_or_blank("Medline Industries, LP", "CGMP"), "Medline Industries, LP")
        for person in ("A. Placeholder, M.D.", "Sam Example, Ph.D.", "Dr. Example's Lab", "Jo Example Placeholder",
                       "B. Example, MD/Example Eye Associates"):
            self.assertEqual(m.company_or_blank(person, "CGMP"), "", person)
        self.assertEqual(m.company_or_blank("Example Research Institute", "Clinical Investigator (Sponsor)"), "")

    def test_registry_entry_matches(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(src["status"], "approved")
        self.assertEqual(set(src["field_docs"]), set(m.FIELDS))


if __name__ == "__main__":
    unittest.main()
