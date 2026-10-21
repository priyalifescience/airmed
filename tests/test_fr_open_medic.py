"""Offline test for the Open Medic collector. Fixture: the header and the semaglutide (A10BJ06) lines of the CNAM
national files NB_2024/NB_2025_atc5.CSV and NB_2024/NB_2025_cip13.CSV (Ozempic presentations), as downloaded in
October 2026."""

import json
import unittest
from pathlib import Path

from airmed.collectors import fr_open_medic as m
from airmed.privacy import check_fields, clean_record

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "fr_open_medic.json"
SMALL = {"ATC5": 1, "CIP13": 1}


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestFrOpenMedic(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw, min_rows=SMALL)

    def test_shape(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 8)       # per year: 1 ATC5 + 3 CIP13
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)

    def test_values(self):
        a = [r for r in self.rows if r["year"] == 2025 and r["level"] == "ATC5"][0]
        self.assertEqual((a["code"], a["label"], a["consumers"], a["reimbursed_eur"], a["reimbursement_base_eur"],
                          a["boxes"]), ("A10BJ06", "SEMAGLUTIDE", 534332, 348097704.55, 363593842.61, 4677641))
        c = [r for r in self.rows if r["year"] == 2024 and r["code"] == "3400930151105"][0]
        self.assertEqual((c["level"], c["label"], c["boxes"], c["reimbursed_eur"]),
                         ("CIP13", "OZEMPIC 1 MG, SOLUTION INJECTABLE EN 1", 2786732, 207335957.02))
        self.assertEqual(m.number("5.183,28"), 5183.28)
        self.assertEqual(m.number("11733"), 11733)

    def test_deterministic_and_clean(self):
        self.assertEqual(self.rows, m.parse(self.raw, min_rows=SMALL))
        stats = {}
        for r in self.rows:
            clean_record(r, stats)
        self.assertEqual(stats.get("blanked", 0), 0)

    def test_refusals(self):
        with self.assertRaises(RuntimeError):
            m.parse(self.raw)                       # default MIN_ROWS: a real year has ~1,150 / ~12,600 rows
        data = json.loads(self.raw)
        data["years"]["2025"]["CIP13"] = data["years"]["2025"]["CIP13"].replace(";3256556", ";1")
        with self.assertRaises(RuntimeError):       # ATC5 and CIP13 boxes disagree
            m.parse(json.dumps(data).encode(), min_rows=SMALL)
        data = json.loads(self.raw)
        data["years"]["2027"] = data["years"]["2025"]
        with self.assertRaises(RuntimeError):       # gap in the years
            m.parse(json.dumps(data).encode(), min_rows=SMALL)
        data = json.loads(self.raw)
        data["years"]["2025"]["ATC5"] = data["years"]["2025"]["ATC5"].replace("BOITES", "BOX")
        with self.assertRaises(RuntimeError):       # unexpected header
            m.parse(json.dumps(data).encode(), min_rows=SMALL)

    def test_registry_entry(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(src["status"], "approved")
        self.assertTrue(src["licence_url"].startswith("https://"))
        self.assertEqual(sorted(src["field_docs"]), sorted(m.FIELDS))


if __name__ == "__main__":
    unittest.main()
