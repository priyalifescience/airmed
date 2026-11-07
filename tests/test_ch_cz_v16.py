"""Offline tests for the Swiss Specialities List and the two Czech SUKL collectors (no network). Fixtures are real records
cut down from the files downloaded on 6 November 2026 (tools/_make_v16_fixtures.py)."""

import io
import json
import unittest
import zipfile
from pathlib import Path

from airmed.collectors import ch_specialities_list as ch, cz_sukl_medicines as med, cz_sukl_supply_notices as notices
from airmed.privacy import check_fields

FIXTURES = Path(__file__).parent / "fixtures"


class TestSwissList(unittest.TestCase):
    def setUp(self):
        self.raw = (FIXTURES / "ch_specialities_list.json").read_bytes()
        self.rows = ch.parse(self.raw, min_rows=0)

    def test_shape(self):
        check_fields(ch.FIELDS)
        self.assertGreater(len(self.rows), 0)
        for r in self.rows:
            self.assertEqual(list(r), ch.FIELDS)

    def test_one_row_per_pack(self):
        data = json.loads(self.raw)
        packs = sum(len(mp["packagedMedicinalProducts"]) for i in data["items"] for mp in i["medicinalProducts"])
        self.assertEqual(len(self.rows), packs)

    def test_values_as_published(self):
        r = next(x for x in self.rows if x["gtin"] == "7680536620137")
        self.assertEqual((r["trademark"], r["dosage_form_strength"], r["pack_size"], r["ex_factory_price_chf"], r["retail_price_chf"]),
                         ("3TC", "Filmtabl 150 mg", "60 Stk", "162.73", "191.9"))
        self.assertEqual((r["substances"], r["it_code"], r["limitation"]), ("Lamivudinum", "08.03.", "no"))

    def test_short_download_fails(self):
        with self.assertRaises(RuntimeError):
            ch.parse(self.raw)


class TestCzechMedicines(unittest.TestCase):
    def setUp(self):
        self.raw = (FIXTURES / "cz_sukl_medicines.zip").read_bytes()
        self.rows = med.parse(self.raw, min_rows=0)

    def test_shape(self):
        check_fields(med.FIELDS)
        self.assertGreater(len(self.rows), 0)
        for r in self.rows:
            self.assertEqual(list(r), med.FIELDS)

    def test_lookups_joined(self):
        r = next(x for x in self.rows if x["sukl_code"] == "0000362")
        self.assertEqual((r["name"], r["strength"], r["atc"]), ("ADRENALIN LÉČIVA", "1MG/ML", "C01CA24"))
        self.assertTrue(r["form"])
        self.assertTrue(r["marketing_authorisation_holder"])
        self.assertTrue(r["substances"])
        self.assertEqual((r["supplied_last_6_months"], r["unlimited_validity"]), ("yes", "yes"))

    def test_no_who_ddd(self):
        self.assertFalse([f for f in med.FIELDS if "ddd" in f.lower()])

    def test_short_download_fails(self):
        with self.assertRaises(RuntimeError):
            med.parse(self.raw)


class TestCzechNotices(unittest.TestCase):
    def setUp(self):
        self.raw = (FIXTURES / "cz_sukl_supply_notices.zip").read_bytes()
        self.rows = notices.parse(self.raw, min_rows=0)

    def test_shape(self):
        check_fields(notices.FIELDS)
        for r in self.rows:
            self.assertEqual(list(r), notices.FIELDS)

    def test_translated_type_and_dates(self):
        r = next(x for x in self.rows if x["sukl_code"] == "0000072" and x["notice_type"] == "interruption")
        self.assertEqual((r["effective_from"], r["notified_on"], r["latest"]), ("2013-09-18", "2013-09-17", "no"))
        self.assertEqual(next(x for x in self.rows if x["sukl_code"] == "0000072" and x["notice_type"] == "end")["latest"], "yes")

    def test_unknown_type_fails(self):
        with zipfile.ZipFile(io.BytesIO(self.raw)) as z:
            text = z.read("mr_hlaseni.csv").decode("cp1250")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("mr_hlaseni.csv", text.replace("preruseni", "jine").encode("cp1250"))
        with self.assertRaises(RuntimeError):
            notices.parse(buf.getvalue(), min_rows=0)


if __name__ == "__main__":
    unittest.main()
