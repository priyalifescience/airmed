"""Offline test for the AIFA Class A / Class H reimbursement lists (fixture: 6 real Class A rows and 4 real Class H
rows of the 31-05-2026 lists, with the AIC -> ATC pairs of AIFA's medicines register for those packs)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import it_aifa_reimbursed_medicines as m
from airmed.privacy import check_fields

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "it_aifa_reimbursed_medicines.json"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestItAifaReimbursedMedicines(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw, min_rows={})

    def row(self, aic):
        return next(r for r in self.rows if r["aic_code"] == aic)

    def test_shape(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 10)
        self.assertEqual(sum(r["reimbursement_class"] == "H" for r in self.rows), 4)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
            self.assertEqual(r["list_date"], "2026-05-31")

    def test_class_a_values(self):
        r = self.row("050465018")
        self.assertEqual((r["active_substance"], r["product_and_pack"], r["marketing_authorisation_holder"],
                          r["atc_code"], r["retail_price_eur"], r["price_unit"], r["in_transparency_list"]),
                         ("Abaloparatide", "ELADYNOS*1 penna 1,5 ml 2 mg/ml", "THERAMEX IRELAND LIMITED", "H05AA04",
                          330.55, "per pack", "no"))
        self.assertEqual(self.row("039716182")["in_transparency_list"], "yes")
        self.assertEqual(self.row("035367554")["regional_list_only"], ["Lazio", "Campania", "Sicilia"])
        self.assertEqual(self.row("038907236")["oxygen_cubic_metres"], 1.16)

    def test_class_h_prices(self):
        r = self.row("034499018")
        self.assertEqual((r["retail_price_eur"], r["ex_factory_price_eur"], r["max_hospital_price_eur"], r["atc_code"],
                          r["in_transparency_list"]), (336.95, 204.16, "", "J05AF06", ""))
        r = self.row("038901524")                                  # medical oxygen, priced per cubic metre
        self.assertEqual((r["retail_price_eur"], r["ex_factory_price_eur"], r["price_unit"], r["oxygen_cubic_metres"]),
                         (6.55, 4.2, "per m³", 855.54))
        r = self.row("034330047")                                  # only a maximum hospital price is published
        self.assertEqual((r["retail_price_eur"], r["max_hospital_price_eur"], r["price_unit"]), ("", 330, ""))

    def test_italian_numbers_and_dates(self):
        self.assertEqual((m.it_num("1.234,56"), m.it_num("7"), m.it_num("-"), m.it_num(" ")), (1234.56, 7, "", ""))
        self.assertEqual((m.it_date("31-05-2026"), m.it_date("2022/02/01"), m.it_date("1/2/2026")),
                         ("2026-05-31", "2022-02-01", "2026-02-01"))
        with self.assertRaises(ValueError):
            m.it_num("6,55/m3")

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
