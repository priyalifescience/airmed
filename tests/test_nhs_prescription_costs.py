"""Offline test for the NHS PCA parser. Fixture: real NHSBSA grouped rows for two months, trimmed to a few substances;
each month's "totals" were recomputed over the kept rows (the real totals cover ~2,600 rows)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import nhs_prescription_costs as m
from airmed.privacy import check_fields, clean_record

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "nhs_prescription_costs.json"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestNhsPrescriptionCosts(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw, min_rows=1)

    def test_shape(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 10)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
        self.assertEqual(sorted({r["year_month"] for r in self.rows}), ["2026-06", "2026-07"])

    def test_values(self):
        r = [x for x in self.rows if x["year_month"] == "2026-07" and x["bnf_chemical_substance_code"] == "0601011A0"
             and x["unit_of_measure"] == "vial"]
        self.assertEqual(len(r), 1)
        self.assertEqual((r[0]["items"], r[0]["total_quantity"], r[0]["nic_gbp"]), (53179, 213640, 2998507.67))
        self.assertEqual(r[0]["bnf_chemical_substance"], "Insulin aspart")
        self.assertEqual(r[0]["year"], 2026)

    def test_codes_stay_text(self):
        # all-digit BNF codes keep their leading zero and stay strings
        olz = [x for x in self.rows if x["bnf_chemical_substance"] == "Olanzapine"]
        self.assertTrue(olz)
        self.assertTrue(all(x["bnf_chemical_substance_code"] == "040201060" for x in olz))
        self.assertTrue(all(isinstance(x["bnf_chapter_code"], str) for x in self.rows))
        self.assertIn("2148", {x["bnf_chemical_substance_code"] for x in self.rows})   # appliance code, all digits

    def test_deterministic_and_clean(self):
        self.assertEqual(self.rows, m.parse(self.raw, min_rows=1))
        stats = {}
        for r in self.rows:
            clean_record(r, stats)
        self.assertEqual(stats.get("blanked", 0), 0)

    def test_totals_mismatch_refused(self):
        data = json.loads(self.raw)
        data["months"]["202607"]["totals"]["items"] += 1
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(data).encode(), min_rows=1)

    def test_month_gap_refused(self):
        data = json.loads(self.raw)
        data["months"]["202609"] = data["months"]["202607"]
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(data).encode(), min_rows=1)

    def test_short_month_refused(self):
        with self.assertRaises(RuntimeError):
            m.parse(self.raw)   # default MIN_ROWS: a real month has ~2,600 rows

    def test_registry_entry(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(src["status"], "approved")
        self.assertTrue(src["licence_url"].startswith("https://"))
        self.assertEqual(sorted(src["field_docs"]), sorted(m.FIELDS))


if __name__ == "__main__":
    unittest.main()
