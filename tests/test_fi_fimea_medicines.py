"""Offline test for the Fimea collector. Fixture: a zip in the shape fetch_raw() builds, holding the real
Versiotiedot of the 21 October 2026 register and the real Pakkaus / Laakeaine / Laakevalmiste elements of four
products (Lipitor 10 mg, Fentanyl 50 mikrog/ml, the herbal registration Echinaguard and a veterinary-only product),
plus the header and three real lines of the shortage file (one human package, one veterinary package, one package
number that is not in the register)."""

import io
import json
import unittest
import zipfile
from pathlib import Path

from airmed.collectors import fi_fimea_medicines as m
from airmed.privacy import check_fields, clean_record

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "fi_fimea_medicines.zip"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


def _rezip(xml: bytes = None, txt: bytes = None) -> bytes:
    with zipfile.ZipFile(FIXTURE) as z:
        xml = z.read(m.REGISTER_NAME) if xml is None else xml
        txt = z.read(m.SHORTAGE_NAME) if txt is None else txt
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as o:
        o.writestr(m.REGISTER_NAME, xml)
        o.writestr(m.SHORTAGE_NAME, txt)
    return buf.getvalue()


class TestFiFimeaMedicines(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw, min_products=1, min_shortages=1)

    def test_shape(self):
        check_fields(m.FIELDS)
        self.assertEqual([r["table"] for r in self.rows], ["product"] * 3 + ["shortage"] * 2)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
            self.assertEqual(r["register_date"], "2026-10-21")

    def test_product_values(self):
        lip = [r for r in self.rows if r["product_id"] == "REL9173"][0]
        self.assertEqual((lip["trade_name"], lip["atc_code"], lip["atc_name"], lip["strength"], lip["dosage_form"]),
                         ("Lipitor", "C10AA05", "atorvastatiini", "10 mg", "tabletti, kalvopäällysteinen"))
        self.assertEqual((lip["active_substances"], lip["routes"], lip["ddd"], lip["ddd_unit"]),
                         (["Atorvastatin calcium trihydrate"], ["Suun kautta"], "20", "mg"))
        self.assertEqual((lip["authorisation_number"], lip["holder"], lip["authorisation_status"], lip["procedure"],
                          lip["authorisation_date"], lip["substitution_group"]),
                         ("12612", "Viatris Healthcare Limited", "Myyntilupa myönnetty", "Tunnustaminen", "1997-04-21",
                          "1080"))
        self.assertEqual((lip["packages"], lip["packages_marketed"], lip["packages_in_shortage"]), (20, 2, 0))
        fen = [r for r in self.rows if r["table"] == "product" and r["product_id"] == "REL119"][0]
        self.assertEqual((fen["narcotic"], fen["packages_in_shortage"]), ("Huumausainelääke", 1))
        reg = [r for r in self.rows if r["product_id"] == "REL32401"][0]
        self.assertEqual((reg["authorisation_type"], reg["authorisation_number"], reg["authorisation_status"]),
                         ("rekisteröinti", "R508FI", "Rekisteröinti peruutettu"))

    def test_shortages(self):
        sh = [r for r in self.rows if r["table"] == "shortage"]
        self.assertEqual([r["vnr"] for r in sh], ["571031", "433660"])   # veterinary package 473944 dropped
        fen, unknown = sh
        self.assertEqual((unknown["product_id"], unknown["holder"], unknown["shortage_start"]),
                         ("", "Abcur AB", "2024-01-01"))
        self.assertEqual((fen["product_id"], fen["trade_name"], fen["atc_code"], fen["package_size"],
                          fen["shortage_in_force"], fen["shortage_start"], fen["shortage_end"],
                          fen["shortage_notified"], fen["holder"]),
                         ("REL119", "Fentanyl", "N01AH01", "5 x 2 ml", "yes", "2025-06-03", "2026-12-31",
                          "2025-06-03", "Piramal Critical Care B.V."))

    def test_deterministic_and_clean(self):
        self.assertEqual(self.rows, m.parse(self.raw, min_products=1, min_shortages=1))
        stats = {}
        for r in self.rows:
            clean_record(r, stats)
        self.assertEqual(stats.get("blanked", 0), 0)

    def test_partial_refused(self):
        with self.assertRaises(RuntimeError):
            m.parse(self.raw)                                   # default MIN_PRODUCTS
        with self.assertRaises(RuntimeError):
            m.parse(_rezip(txt=b'"VNR";"Status"\r\n"1";"K"\r\n'), min_products=1, min_shortages=1)
        with self.assertRaises(RuntimeError):
            m.parse(_rezip(xml=b"<Perusrekisteri></Perusrekisteri>"), min_products=0, min_shortages=0)

    def test_registry_entry(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(src["status"], "approved")
        self.assertTrue(src["licence_url"].startswith("https://"))
        self.assertEqual(sorted(src["field_docs"]), sorted(m.FIELDS))


if __name__ == "__main__":
    unittest.main()
