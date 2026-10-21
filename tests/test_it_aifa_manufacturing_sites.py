"""Offline test for the AIFA authorised manufacturing sites parser (fixture: real rows of the three lists:
medicines 30/06/2026, medical gases 30/06/2026, active substances June 2025, chosen for awkward addresses)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import it_aifa_manufacturing_sites as m
from airmed.privacy import check_fields

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "it_aifa_manufacturing_sites.txt"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestItAifaManufacturingSites(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw, min_rows=False)

    def test_shape(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 17)
        self.assertEqual({r["site_type"] for r in self.rows}, {"medicinali", "gas medicinali", "sostanze attive"})
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
        self.assertEqual({r["list_date"] for r in self.rows if r["site_type"] == "sostanze attive"}, {"2025-06-30"})
        self.assertEqual({r["list_date"] for r in self.rows if r["site_type"] == "medicinali"}, {"2026-06-30"})

    def test_no_street_published(self):
        text = json.dumps([[r["town"], r["province"], r["region"]] for r in self.rows])
        for street in ("VIA ", "VIALE", "CAMPO DI PILE", "MONTANARI", "GHISALLO", "20151", "112"):
            self.assertNotIn(street, text)

    def test_towns_and_regions(self):
        got = {(r["company"], r["site_type"]): (r["town"], r["province"], r["region"]) for r in self.rows}
        self.assertEqual(got[("ADIENNE S.R.L.", "medicinali")], ("CAPONAGO", "MB", "Lombardia"))
        self.assertEqual(got[("CORDEN PHARMA SOCIETA' PER AZIONI", "medicinali")], ("CAPONAGO", "MB", "Lombardia"))
        self.assertEqual(got[("AIR LIQUIDE ITALIA PRODUZIONE S.R.L.", "gas medicinali")], ("PADOVA", "PD", "Veneto"))
        self.assertEqual(got[("SICO SOCIETA' ITALIANA CARBURO OSSIGENO S.P.A.", "gas medicinali")],
                         ("BARI", "BA", "Puglia"))
        self.assertEqual(got[("C.F.M. CO. FARMACEUTICA MILANESE S.P.A.", "sostanze attive")],
                         ("MILANO", "MI", "Lombardia"))
        self.assertEqual(got[("PHARMA PARTNERS S.R.L.", "medicinali")], ("PRATO", "PO", "Toscana"))
        self.assertEqual(got[("VALPHARMA S.P.A.", "medicinali")], ("", "RSM", "San Marino"))
        self.assertEqual(got[("CRIOSERVICE S.R.L.", "gas medicinali")], ("", "LE", "Puglia"))   # cannot split safely

    def test_split_location(self):
        self.assertEqual(m.split_location("INTERPORTO DI NOLA, LOTTO C A1 NOLA (NA)"), ("NOLA", "NA"))
        self.assertEqual(m.split_location("VIA DI MELETO, 2 INT. 6/8 - 50027 GREVE IN CHIANTI (FI)"),
                         ("GREVE IN CHIANTI", "FI"))
        self.assertEqual(m.split_location("VIA ROMA, 1 - (LOC.CASTIGLION FIORENTINO) AREZZO (AR)"), ("AREZZO", "AR"))

    def test_too_few_rows_refused(self):
        with self.assertRaises(RuntimeError):
            m.parse(self.raw)

    def test_registry_entry_matches(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(src["status"], "approved")
        self.assertEqual(list(src["field_docs"]), m.FIELDS)


if __name__ == "__main__":
    unittest.main()
