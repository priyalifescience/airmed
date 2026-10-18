"""Offline test for the FDA original-approvals parser (fixture: real openFDA drugsfda records, trimmed to 5)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import fda_approvals as m
from airmed.privacy import check_fields

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "fda_approvals.json"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestFdaApprovals(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw)

    def test_parse(self):
        self.assertEqual(len(self.rows), 5)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
            self.assertIn(r["application_type"], ("NDA", "BLA", "ANDA"))
            self.assertRegex(r["approval_date"], r"^\d{4}-\d{2}-\d{2}$")
        keys = [(r["approval_date"], r["application_number"]) for r in self.rows]
        self.assertEqual(keys, sorted(keys, reverse=True))
        check_fields(m.FIELDS)

    def test_all_years_kept(self):
        by = {r["application_number"]: r for r in self.rows}
        self.assertEqual(by["NDA000552"]["approval_date"], "1939-02-09")
        self.assertEqual(by["BLA761261"]["submission_class"], "Type 1 - New Molecular Entity")

    def test_earliest_orig_approval_used(self):
        by = {r["application_number"]: r for r in self.rows}
        self.assertEqual(by["ANDA077904"]["approval_date"], "2006-10-23")

    def test_non_approved_orig_skipped(self):
        d = json.loads(self.raw)
        d["results"][0]["submissions"] = [{"submission_type": "SUPPL", "submission_status": "AP",
                                           "submission_status_date": "20200101"}]
        self.assertEqual(len(m.parse(json.dumps(d).encode())), 4)

    def test_registry_entry(self):
        e = registry_entry(m.KEY)
        self.assertEqual(e["fields_kept"], m.FIELDS)
        self.assertEqual(sorted(e["field_docs"]), sorted(m.FIELDS))
        self.assertNotIn("2021", e["name"])


if __name__ == "__main__":
    unittest.main()
