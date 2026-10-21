"""Offline test for the BDPM medicines collector. Fixture fr_bdpm.json: the real BDPM lines (October 2026 files) of
five medicines (anastrozole Accord, Adempas and Pneumovax (both MITM), Cosentyx, a Boiron homeopathic medicine with
no presentation), shared by the four fr_bdpm_* tests."""

import json
import unittest
from pathlib import Path

from airmed.collectors import fr_bdpm_medicines as m
from airmed.privacy import check_fields, clean_record

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "fr_bdpm.json"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestFrBdpmMedicines(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw, min_rows=1)

    def test_shape(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 8)      # 7 presentations + 1 medicine without a presentation
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)

    def test_values(self):
        a = [r for r in self.rows if r["cip13_code"] == "3400949497294"][0]
        self.assertEqual((a["cis_code"], a["medicine_name"], a["cip7_code"], a["authorisation_date"],
                          a["reimbursement_rate"], a["price_eur"], a["public_price_eur"], a["dispensing_fee_eur"]),
                         ("60002283", "ANASTROZOLE ACCORD 1 mg, comprimé pelliculé", "4949729", "2010-10-28", "100%",
                          24.34, 25.36, 1.02))
        self.assertEqual((a["atc_code"], a["mitm"], a["presentations_file_updated"]), ("", False, "2026-10-20"))
        big = [r for r in self.rows if r["cip13_code"] == "3400927849800"][0]   # published "1,466,29"
        self.assertEqual((big["price_eur"], big["atc_code"], big["mitm"]), (1466.29, "C02KX05", True))
        none = [r for r in self.rows if r["cis_code"] == "69103878"][0]
        self.assertEqual((none["cip13_code"], none["price_eur"], none["holders"]), ("", None, "BOIRON"))  # " BOIRON"

    def test_formats(self):
        self.assertEqual(m.euro("1,234,56"), 1234.56)
        self.assertEqual(m.euro(""), None)
        self.assertEqual(m.iso_date("20260909"), "2026-09-09")
        self.assertEqual(m.decode("l\x92AMM".encode("latin-1")), "l’AMM")
        with self.assertRaises(RuntimeError):
            m.euro("12.5")
        page = ('<a href="/download/file/CIS_bdpm.txt">x</a> (Date de mise à jour : 29/09/2026, 3101 Ko)'
                '<a href="/download/file/CIS_MITM.txt">y</a>')
        self.assertEqual(m.file_dates(page), {"CIS_bdpm.txt": "2026-09-29"})

    def test_deterministic_and_clean(self):
        self.assertEqual(self.rows, m.parse(self.raw, min_rows=1))
        stats = {}
        for r in self.rows:
            clean_record(r, stats)
        self.assertEqual(stats.get("blanked", 0), 0)

    def test_refusals(self):
        with self.assertRaises(RuntimeError):
            m.parse(self.raw)                     # default MIN_ROWS: a real download has ~22,000 rows
        data = json.loads(self.raw)
        data["files"]["CIS_bdpm.txt"] += "1\t2\n"  # wrong column count
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(data).encode(), min_rows=1)

    def test_registry_entry(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(src["status"], "approved")
        self.assertTrue(src["licence_url"].startswith("https://"))
        self.assertEqual(sorted(src["field_docs"]), sorted(m.FIELDS))


if __name__ == "__main__":
    unittest.main()
