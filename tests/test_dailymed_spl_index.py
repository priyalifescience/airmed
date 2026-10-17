"""Offline test for the DailyMed SPL index parser (fixture trimmed from real DailyMed web service pages and the
rxnorm_mappings file; the individual labeler row uses a placeholder name and set id)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import dailymed_spl_index as m
from airmed.privacy import check_fields

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "dailymed_spl_index.json"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestDailymedSplIndex(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw)
        self.by = {r["setid"]: r for r in self.rows}

    def test_shape(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 5)   # 6 listing entries, one set id repeated across pages
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
            self.assertEqual(r["document_type"], "HUMAN PRESCRIPTION DRUG LABEL")
            self.assertTrue(r["url"].endswith(r["setid"]))
        titles = [r["title"].lower() for r in self.rows]
        self.assertEqual(titles, sorted(titles))

    def test_values(self):
        r = self.by["f9648990-0627-4c66-aae1-d3eef398b5b4"]
        self.assertEqual((r["labeler"], r["spl_version"], r["published_date"]), ("CARILION MATERIALS MANAGEMENT", "3", "2016-08-08"))
        self.assertEqual(r["rxcuis"], ["349490", "352308"])
        self.assertEqual(r["rxnorm_names"], ["aripiprazole 15 MG Oral Tablet", "aripiprazole 15 MG Oral Tablet [Abilify]"])
        self.assertEqual(self.by["018fc687-1fba-202e-e063-6294a90a5c9a"]["rxcuis"], [])          # not in the mapping file
        self.assertEqual(self.by["54ea1ec3-876b-4d3a-a92b-1a6d70951de0"]["labeler"], "DR. REDDY’S LABORATORIES INC.")  # &RSQUO;
        lido = self.by["dc476ebd-fd57-41c3-a649-7185a784a39f"]
        self.assertEqual(len(lido["rxcuis"]), len(lido["rxnorm_names"]))

    def test_individual_labeler_withheld(self):
        r = self.by["00000000-0000-4000-8000-000000000001"]
        self.assertEqual((r["labeler"], r["title"]), ("", "OXYGEN GAS [labeler withheld]"))
        self.assertNotIn("EXAMPLE", json.dumps(self.rows))
        self.assertFalse(m.looks_like_person("E. FOUGERA & CO."))
        self.assertFalse(m.looks_like_person("NOVO NORDISK"))

    def test_count_mismatch_refused(self):
        data = json.loads(self.raw)
        data["total"] += 1
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(data).encode())

    def test_registry_entry_matches(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(src["status"], "approved")
        self.assertEqual(set(src["field_docs"]), set(m.FIELDS))


if __name__ == "__main__":
    unittest.main()
