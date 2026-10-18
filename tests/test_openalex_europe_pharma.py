"""Offline test for the OpenAlex Europe pharma collector, on a trimmed real fixture (5 works)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import openalex_europe_pharma as oa
from airmed.privacy import check_fields

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "openalex_europe_pharma.json"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestOpenAlexEuropePharma(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = oa.parse(self.raw)

    def test_parse(self):
        self.assertEqual(len(self.rows), 5)
        for r in self.rows:
            self.assertEqual(list(r), oa.FIELDS)
            self.assertTrue(r["openalex_id"].startswith("W"))
            self.assertFalse(r["doi"].startswith("http"))
            self.assertTrue(set(r["countries"]) & set(oa.COUNTRIES), r["openalex_id"])
            self.assertIn(r["filter_basis"], ("field30", "medchem"))
            self.assertTrue(r["matched_topics"])
            self.assertGreaterEqual(int(r["publication_year"]), oa.FROM_YEAR)
        dates = [(r["publication_date"], r["openalex_id"]) for r in self.rows]
        self.assertEqual(dates, sorted(dates, reverse=True))
        check_fields(oa.FIELDS)

    def test_no_author_or_institution_names_in_raw(self):
        text = self.raw.decode("utf-8")
        for bad in ('"author"', "orcid", "authorships", "raw_author_name", "raw_affiliation", "display_name\": \"University"):
            self.assertNotIn(bad, text)

    def test_count_mismatch_refuses(self):
        d = json.loads(self.raw)
        first = next(iter(d["counts"]))
        d["counts"][first] += 1
        with self.assertRaises(RuntimeError):
            oa.parse(json.dumps(d).encode())

    def test_spam_titles_dropped(self):
        d = json.loads(self.raw)
        d["works"][0]["title"] = "Abortion pills for sale call +971-582181939"
        self.assertEqual(len(oa.parse(json.dumps(d).encode())), 4)

    def test_windows_disjoint_and_under_paging_limit_design(self):
        q = oa.queries()
        self.assertEqual(len(q), 16 + 4)
        self.assertEqual(sum(1 for f in q.values() if "to_publication_date" not in f), 2)   # open-ended last windows
        for f in q.values():
            self.assertIn("institutions.country_code:" + "|".join(oa.COUNTRIES), f)
        self.assertEqual(len(oa.COUNTRIES), 30)

    def test_registry_entry(self):
        e = registry_entry(oa.KEY)
        self.assertEqual(e["fields_kept"], oa.FIELDS)
        self.assertEqual(sorted(e["field_docs"]), sorted(oa.FIELDS))
        self.assertEqual(e["status"], "approved")


if __name__ == "__main__":
    unittest.main()
