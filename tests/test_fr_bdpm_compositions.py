"""Offline test for the BDPM compositions collector (fixture fr_bdpm.json, see test_fr_bdpm_medicines)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import fr_bdpm_compositions as m
from airmed.privacy import check_fields, clean_record

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "fr_bdpm.json"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestFrBdpmCompositions(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw, min_rows=1)

    def test_shape_and_values(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 32)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
        a = [r for r in self.rows if r["cis_code"] == "60002283"]
        self.assertEqual(len(a), 1)
        self.assertEqual((a[0]["substance_code"], a[0]["substance"], a[0]["dosage"], a[0]["dosage_reference"],
                          a[0]["component_nature"], a[0]["medicine_name"], a[0]["source_updated"]),
                         ("42215", "ANASTROZOLE", "1,00 mg", "un comprimé", "SA",
                          "ANASTROZOLE ACCORD 1 mg, comprimé pelliculé", "2026-09-29"))

    def test_deterministic_and_clean(self):
        self.assertEqual(self.rows, m.parse(self.raw, min_rows=1))
        stats = {}
        for r in self.rows:
            clean_record(r, stats)
        self.assertEqual(stats.get("blanked", 0), 0)
        with self.assertRaises(RuntimeError):
            m.parse(self.raw)                     # default MIN_ROWS: a real download has ~32,000 rows

    def test_registry_entry(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(src["status"], "approved")
        self.assertTrue(src["licence_url"].startswith("https://"))
        self.assertEqual(sorted(src["field_docs"]), sorted(m.FIELDS))


if __name__ == "__main__":
    unittest.main()
