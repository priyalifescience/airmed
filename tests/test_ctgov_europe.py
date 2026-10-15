"""Offline test for the ctgov_europe collector (no network). Fixture: 3 real studies, trimmed to the requested fields."""

import json
import unittest
from pathlib import Path

from airmed.collectors import ctgov_europe
from airmed.privacy import check_fields

FIXTURE = Path(__file__).parent / "fixtures" / "ctgov_europe.json"


class TestCtgovEurope(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()

    def test_parse(self):
        rows = ctgov_europe.parse(self.raw)
        self.assertEqual(len(rows), 3)
        self.assertEqual([r["nct_id"] for r in rows], sorted(r["nct_id"] for r in rows))  # deterministic order
        for r in rows:
            self.assertEqual(list(r), ctgov_ireland_fields_plus_countries())
            self.assertTrue(r["countries"])
            self.assertTrue(set(r["countries"]) <= set(ctgov_europe.EUROPE))
        by_id = {r["nct_id"]: r for r in rows}
        self.assertEqual(by_id["NCT06816862"]["countries"], ["Ireland"])
        self.assertNotIn("United States", by_id["NCT03231878"]["countries"])  # non-European sites dropped

    def test_fields_clean(self):
        check_fields(ctgov_europe.FIELDS)

    def test_count_mismatch_refuses(self):
        data = json.loads(self.raw)
        data["totalCount"] = 99
        with self.assertRaises(RuntimeError):
            ctgov_europe.parse(json.dumps(data).encode())

    def test_study_without_european_site_refuses(self):
        data = json.loads(self.raw)
        data["studies"][0]["protocolSection"]["contactsLocationsModule"]["locations"] = [{"country": "Japan"}]
        with self.assertRaises(RuntimeError):
            ctgov_europe.parse(json.dumps(data).encode())

    def test_registry_entry_matches(self):
        entry = json.loads((Path(__file__).parent.parent / "sources" / "pending" / "ctgov_europe.json").read_text(encoding="utf-8"))
        self.assertEqual(entry["fields_kept"], ctgov_europe.FIELDS)
        self.assertEqual(set(entry["field_docs"]), set(ctgov_europe.FIELDS))


def ctgov_ireland_fields_plus_countries():
    from airmed.collectors import ctgov_ireland
    return list(ctgov_ireland.FIELDS) + ["countries"]


if __name__ == "__main__":
    unittest.main()
