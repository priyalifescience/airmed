"""Offline test for the BDPM availability (ANSM shortage notices) collector (fixture fr_bdpm.json, see
test_fr_bdpm_medicines)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import fr_bdpm_availability as m
from airmed.privacy import check_fields, clean_record

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "fr_bdpm.json"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestFrBdpmAvailability(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw, min_rows=1)

    def test_shape_and_values(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 1)
        r = self.rows[0]
        self.assertEqual(list(r), m.FIELDS)
        self.assertEqual((r["cis_code"], r["cip13_code"], r["atc_code"], r["status_code"], r["status"],
                          r["start_date"], r["ansm_updated_date"], r["return_date"], r["source_updated"]),
                         ("60614280", "", "J07AL01", 2, "Tension d'approvisionnement", "2026-09-30", "2026-10-09", "",
                          "2026-10-12"))
        self.assertTrue(r["ansm_url"].startswith("https://ansm.sante.fr/"))

    def test_clean_and_refusals(self):
        stats = {}
        for r in self.rows:
            clean_record(r, stats)
        self.assertEqual(stats.get("blanked", 0), 0)
        with self.assertRaises(RuntimeError):
            m.parse(self.raw)                     # default MIN_ROWS: a real download has ~700 notices
        data = json.loads(self.raw)
        data["files"]["CIS_CIP_Dispo_Spec.txt"] = data["files"]["CIS_CIP_Dispo_Spec.txt"].replace("\t2\t", "\t9\t")
        with self.assertRaises(RuntimeError):     # unknown status code
            m.parse(json.dumps(data).encode(), min_rows=1)

    def test_registry_entry(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(src["status"], "approved")
        self.assertTrue(src["licence_url"].startswith("https://"))
        self.assertEqual(sorted(src["field_docs"]), sorted(m.FIELDS))


if __name__ == "__main__":
    unittest.main()
