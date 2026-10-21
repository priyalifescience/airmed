"""Offline test for the BDPM HAS SMR/ASMR collector (fixture fr_bdpm.json, see test_fr_bdpm_medicines)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import fr_bdpm_has_opinions as m
from airmed.privacy import check_fields, clean_record

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "fr_bdpm.json"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestFrBdpmHasOpinions(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw, min_rows=1)

    def test_shape_and_values(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 37)       # 20 SMR + 17 ASMR lines
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
        c = [r for r in self.rows if r["cis_code"] == "65007804" and r["has_file_code"] == "CT-19532"]
        self.assertEqual(sorted(r["assessment"] for r in c), ["ASMR", "SMR"])
        asmr = [r for r in c if r["assessment"] == "ASMR"][0]
        self.assertEqual((asmr["opinion_date"], asmr["rating"], asmr["has_opinion_url"], asmr["source_updated"]),
                         ("2022-07-11", "IV", "https://www.has-sante.fr/jcms/p_3367902", "2026-09-29"))
        self.assertEqual(asmr["medicine_name"], "COSENTYX 150 mg, solution injectable en stylo prérempli")

    def test_deterministic_and_clean(self):
        self.assertEqual(self.rows, m.parse(self.raw, min_rows=1))
        stats = {}
        for r in self.rows:
            clean_record(r, stats)
        self.assertEqual(stats.get("blanked", 0), 0)
        with self.assertRaises(RuntimeError):
            m.parse(self.raw)                     # default MIN_ROWS: a real download has ~25,000 rows
        data = json.loads(self.raw)
        data["files"]["CIS_HAS_SMR_bdpm.txt"] = data["files"]["CIS_HAS_SMR_bdpm.txt"].replace("\t20220711\t", "\t2022\t")
        with self.assertRaises(RuntimeError):     # a date the format description does not allow
            m.parse(json.dumps(data).encode(), min_rows=1)

    def test_registry_entry(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(src["status"], "approved")
        self.assertTrue(src["licence_url"].startswith("https://"))
        self.assertEqual(sorted(src["field_docs"]), sorted(m.FIELDS))


if __name__ == "__main__":
    unittest.main()
