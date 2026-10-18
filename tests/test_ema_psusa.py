"""Offline test for the EMA PSUSA outcomes parser (fixture: EMA's JSON report trimmed to 6 procedures)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import ema_psusa as m
from airmed.privacy import check_fields

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "ema_psusa.json"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestEmaPsusa(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw, min_records=1)
        self.by = {r["procedure_number"]: r for r in self.rows}

    def test_registry_entry(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["status"], "approved")
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(set(src["field_docs"]), set(m.FIELDS))
        check_fields(m.FIELDS)

    def test_shape_and_order(self):
        self.assertEqual(len(self.rows), 6)                 # blank category rows are kept (PSUSAs are human-only)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
            self.assertTrue(r["url"].startswith("https://www.ema.europa.eu/"))
        keys = [(r["procedure_number"], r["url"]) for r in self.rows]
        self.assertEqual(keys, sorted(keys))

    def test_record(self):
        r = self.by["PSUSA/00001694/202603"]
        self.assertEqual((r["active_substances_in_scope"], r["regulatory_outcome"], r["first_published"]),
                         ("hydroxyethyl starch, hydroxyethyl starch combinations", "Maintenance", "2026-10-15"))
        self.assertEqual(self.by["EMEA/H/N/PSR/J/0031"]["regulatory_outcome"], "Suspension")

    def test_count_mismatch_refused(self):
        doc = json.loads(self.raw)
        doc["meta"]["total_records"] += 1
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(doc).encode(), min_records=1)

    def test_partial_dataset_refused(self):
        with self.assertRaises(RuntimeError):
            m.parse(self.raw)


if __name__ == "__main__":
    unittest.main()
