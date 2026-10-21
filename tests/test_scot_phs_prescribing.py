"""Offline test for the PHS Scotland prescribing collector. Fixture: five real grouped rows from the datastore SQL
reply for the July 2026 "Data by Prescriber Location" table (items without a BNF code, one appliance group, and the
substances atorvastatin, sertraline and blood glucose testing strips). The table totals are rebuilt in the test from
those rows; the live run checks the real table totals."""

import json
import unittest
from pathlib import Path

from airmed.collectors import scot_phs_prescribing as m
from airmed.privacy import check_fields, clean_record

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "scot_phs_prescribing.json"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


def _month(records, ym="202607"):
    tot = {"n": "999", "i": str(sum(int(r["i"]) for r in records)), "q": str(sum(float(r["q"]) for r in records)),
           "g": str(sum(float(r["g"]) for r in records)), "a": ym, "b": ym}
    return {"resource_id": "x", "totals": tot, "records": records}


class TestScotPhsPrescribing(unittest.TestCase):
    def setUp(self):
        self.recs = json.loads(FIXTURE.read_text(encoding="utf-8"))["records"]
        self.raw = json.dumps({"months": {"2026-07": _month(self.recs)}}).encode()
        self.rows = m.parse(self.raw, min_groups=1)

    def test_shape(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 5)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)

    def test_values(self):
        a = [r for r in self.rows if r["bnf_chemical_substance_code"] == "0212000B0"][0]
        self.assertEqual((a["year"], a["year_month"], a["bnf_chapter"], a["bnf_section"], a["bnf_paragraph"]),
                         (2026, "2026-07", "2", "12", "0"))
        self.assertEqual((a["items"], a["paid_quantity"], a["gross_ingredient_cost_gbp"], a["bnf_presentations"],
                          a["prescriber_locations"]), (367875, 17062204.32, 671601.97, 13, 920))
        app = [r for r in self.rows if r["bnf_chapter"] == "21"][0]          # 11-digit appliance codes
        self.assertEqual((app["bnf_chemical_substance_code"], app["bnf_section"], app["items"]), ("", "2", 12400))
        nocode = [r for r in self.rows if r["bnf_chapter"] == ""][0]
        self.assertEqual((nocode["items"], nocode["bnf_presentations"]), (10387, 1))
        self.assertEqual(self.rows[0], nocode)                                # sorted by substance code first

    def test_deterministic_and_clean(self):
        self.assertEqual(self.rows, m.parse(self.raw, min_groups=1))
        stats = {}
        for r in self.rows:
            clean_record(r, stats)
        self.assertEqual(stats.get("blanked", 0), 0)

    def test_totals_mismatch_refused(self):
        data = json.loads(self.raw)
        data["months"]["2026-07"]["totals"]["i"] = str(int(data["months"]["2026-07"]["totals"]["i"]) + 1)
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(data).encode(), min_groups=1)

    def test_wrong_month_gap_and_short_refused(self):
        with self.assertRaises(RuntimeError):     # table holds another month
            m.parse(json.dumps({"months": {"2026-07": _month(self.recs, "202606")}}).encode(), min_groups=1)
        with self.assertRaises(RuntimeError):     # gap
            m.parse(json.dumps({"months": {"2026-05": _month(self.recs, "202605"),
                                           "2026-07": _month(self.recs)}}).encode(), min_groups=1)
        with self.assertRaises(RuntimeError):     # default MIN_GROUPS: a real month has ~2,000 groups
            m.parse(self.raw)

    def test_resource_names(self):
        self.assertEqual(m._NAME_RE.search("Data by Prescriber Location – July 2026").groups(), ("July", "2026"))
        self.assertTrue(m._NAME_RE.search("Data by Prescriber Location - January 2018 "))
        self.assertTrue(m._NAME_RE.search("Data by Prescribing Location - May 2017"))
        self.assertIsNone(m._NAME_RE.search("Data by Dispenser Location - July 2026"))
        self.assertIsNone(m._NAME_RE.search("Data by Board – July 2026"))

    def test_registry_entry(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(src["status"], "approved")
        self.assertTrue(src["licence_url"].startswith("https://"))
        self.assertEqual(sorted(src["field_docs"]), sorted(m.FIELDS))


if __name__ == "__main__":
    unittest.main()
