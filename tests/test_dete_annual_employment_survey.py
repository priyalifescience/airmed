"""Offline test for the DETE Annual Employment Survey parser (fixture: the four real appendix CSVs of the 2025
survey, as fetch_raw bundles them)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import dete_annual_employment_survey as m
from airmed.privacy import check_fields

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "dete_annual_employment_survey.json"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestDeteAnnualEmploymentSurvey(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw)

    def jobs(self, table, category, year, etype=None):
        hits = [r for r in self.rows if (r["table"], r["category"], r["year"]) == (table, category, year)
                and (etype is None or r["employment_type"] == etype)]
        return [r["jobs"] for r in hits]

    def test_shape(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 4320)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
            self.assertIsInstance(r["jobs"], int)

    def test_pharma_and_medtech(self):
        self.assertEqual(self.jobs("A1", "Chemicals", "2025"), [47771])
        self.assertEqual(self.jobs("A1", "Medical Devices", "2025"), [47112])
        self.assertEqual(self.jobs("A7", "Chemicals", "2025"), [43293])     # foreign-owned
        self.assertEqual(self.jobs("A1", "Grand Total", "2016"), [387082])  # "387082" and "387,082" both parse

    def test_latest_copy_of_duplicated_table(self):
        b9 = [r for r in self.rows if r["table"] == "B9"]
        self.assertEqual({r["table_title"][-9:] for r in b9}, {"2016-2025"})
        self.assertEqual(self.jobs("B9", "All Regions", "2025"), [18609])
        self.assertEqual(self.jobs("B9", "All Regions", "2015"), [])

    def test_figures_that_look_like_years(self):
        # B6 has figures such as 1938 and 2093; they must not be read as a header row
        self.assertEqual(self.jobs("B6", "Mid East", "2021"), [2043])
        self.assertEqual(len([r for r in self.rows if r["table"] == "B6"]), 120)

    def test_levels_and_counties(self):
        levels = {(r["category"], r["category_level"]) for r in self.rows if r["table"] == "B1"}
        self.assertIn(("Dublin", "group"), levels)
        self.assertIn(("Dublin", "item"), levels)
        self.assertIn(("BMW Area", "group"), levels)
        self.assertIn(("Grand Total", "total"), levels)
        self.assertEqual(self.jobs("county", "Tipperary", "2025", "Total"), [12487])   # trailing space trimmed
        self.assertEqual(self.jobs("county", "(blank)", "2025"), [])

    def test_missing_file_refused(self):
        data = json.loads(self.raw)
        del data["files"]["irish-firms"]
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(data).encode())

    def test_registry_entry_matches(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["fields_kept"], m.FIELDS)
        # Held until DETE confirms the licence: never collected or released, but the parser stays tested.
        self.assertEqual(src["status"], "pending")
        self.assertTrue(src["reason"].startswith("Held 2026-10-20"))
        self.assertEqual(list(src["field_docs"]), m.FIELDS)


if __name__ == "__main__":
    unittest.main()
