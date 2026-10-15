"""Offline test for the OpenAlex Ireland pharma collector, on a trimmed real fixture (5 works)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import openalex_ireland_pharma as oa
from airmed.privacy import check_fields

FIXTURE = Path(__file__).parent / "fixtures" / "openalex_ireland_pharma.json"


class TestOpenAlexIrelandPharma(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = oa.parse(self.raw)

    def test_parse(self):
        self.assertEqual(len(self.rows), 5)
        for r in self.rows:
            self.assertEqual(sorted(r), sorted(oa.FIELDS))
            self.assertTrue(r["openalex_id"].startswith("W"))
            self.assertFalse(r["doi"].startswith("http"))
            self.assertTrue(r["irish_institutions"], r["openalex_id"])
            self.assertIn(r["filter_basis"], ("field30", "medchem"))
            self.assertTrue(r["matched_topics"])
        dates = [(r["publication_date"], r["openalex_id"]) for r in self.rows]
        self.assertEqual(dates, sorted(dates, reverse=True))
        check_fields(oa.FIELDS)

    def test_no_author_data_in_raw(self):
        text = self.raw.decode("utf-8")
        for bad in ('"author"', "orcid", "authorships", "raw_author_name"):
            self.assertNotIn(bad, text)

    def test_count_mismatch_refuses(self):
        d = json.loads(self.raw)
        d["counts"]["field30"] += 1
        with self.assertRaises(RuntimeError):
            oa.parse(json.dumps(d).encode())

    def test_spam_titles_dropped(self):
        d = json.loads(self.raw)
        d["works"][0]["title"] = "Abortion pills for sale call +971-582181939"
        self.assertEqual(len(oa.parse(json.dumps(d).encode())), 4)


if __name__ == "__main__":
    unittest.main()
