"""Offline test for the NI GP prescribing collector. Fixture: the header (Windows-1252, "Gross Cost (£)"), nine real
data rows and the trailing blank rows of the BSO August 2026 file."""

import json
import unittest
from pathlib import Path

from airmed.collectors import ni_bso_gp_prescribing as m
from airmed.privacy import check_fields, clean_record

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "ni_bso_gp_prescribing.csv"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestNiBsoGpPrescribing(unittest.TestCase):
    def setUp(self):
        self.month = m.group_month(FIXTURE.read_bytes(), "2026-08")
        self.raw = json.dumps({"months": {"2026-08": {"url": "x", **self.month}}}).encode()
        self.rows = m.parse(self.raw, min_groups=1)

    def test_shape(self):
        check_fields(m.FIELDS)
        self.assertEqual(self.month["rows"], 9)          # blank trailing rows skipped
        self.assertEqual(len(self.rows), 3)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)

    def test_values(self):
        a = [r for r in self.rows if r["substance"] == "Atorvastatin"]
        self.assertEqual(len(a), 1)   # 20mg + 40mg, generic + Lipitor: one substance x presentation row
        a = a[0]
        self.assertEqual((a["year_month"], a["bnf_chapter"], a["bnf_section"], a["bnf_chemical_substance_code"],
                          a["presentation"]), ("2026-08", "2", "12", "0212000B0", "Tablet"))
        self.assertEqual((a["items"], a["total_quantity"], a["gross_cost_gbp"], a["actual_cost_gbp"], a["products"],
                          a["practices"]), (781, 33124, 974.99, 801.48, 2, 2))
        strips = [r for r in self.rows if r["bnf_chemical_substance_code"] == "0601060D0"][0]
        self.assertEqual((strips["substance"], strips["items"], strips["total_quantity"]), ("", 14, 1700))
        dressing = [r for r in self.rows if r["bnf_chapter"] == "20"][0]   # 11-digit appliance code
        self.assertEqual((dressing["bnf_chemical_substance_code"], dressing["items"], dressing["gross_cost_gbp"]),
                         ("", 3, 10.5))

    def test_deterministic_and_clean(self):
        self.assertEqual(self.rows, m.parse(self.raw, min_groups=1))
        stats = {}
        for r in self.rows:
            clean_record(r, stats)
        self.assertEqual(stats.get("blanked", 0), 0)

    def test_wrong_month_refused(self):
        with self.assertRaises(RuntimeError):
            m.group_month(FIXTURE.read_bytes(), "2026-07")

    def test_totals_mismatch_refused(self):
        data = json.loads(self.raw)
        data["months"]["2026-08"]["totals"]["items"] += 1
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(data).encode(), min_groups=1)

    def test_gap_and_short_month_refused(self):
        data = json.loads(self.raw)
        data["months"]["2026-10"] = data["months"]["2026-08"]
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(data).encode(), min_groups=1)
        with self.assertRaises(RuntimeError):
            m.parse(self.raw)   # default MIN_GROUPS: a real month has ~2,000 groups

    def test_resource_names(self):
        self.assertTrue(m._NAME_RE.search("GP Prescribing Northern Ireland - August 2026"))
        self.assertTrue(m._NAME_RE.search("GP Prescribing, Northern Ireland - December 2018"))
        self.assertEqual(m._NAME_RE.search("GP Prescribing Northern Ireland, April 2026").groups(), ("April", "2026"))

    def test_registry_entry(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(src["status"], "approved")
        self.assertTrue(src["licence_url"].startswith("https://"))
        self.assertEqual(sorted(src["field_docs"]), sorted(m.FIELDS))


if __name__ == "__main__":
    unittest.main()
