"""Offline test for the EU orphan market exclusivity parser (fixture: Union Register open dataset trimmed to 5
medicines, their 11 orphan designations and 2 unrelated records; designation sponsors and addresses removed)."""

import datetime as dt
import json
import unittest
from pathlib import Path

from airmed.collectors import eu_orphan_exclusivity as m
from airmed.privacy import check_fields

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "eu_orphan_exclusivity.json"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestEuOrphanExclusivity(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw, min_records=1)
        self.by = {(r["eu_product_number"], r["orphan_designation_number"]): r for r in self.rows}

    def test_registry_entry(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["status"], "approved")
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(set(src["field_docs"]), set(m.FIELDS))
        check_fields(m.FIELDS)

    def test_shape(self):
        self.assertEqual(len(self.rows), 11)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
            self.assertTrue(r["product_url"].startswith("https://") and r["designation_url"].startswith("https://"))
        keys = [(r["eu_product_number"], r["orphan_designation_number"]) for r in self.rows]
        self.assertEqual(keys, sorted(keys))

    def test_recorded_end_date(self):
        r = self.by[("EU/1/12/794", "EU/3/08/595")]
        self.assertEqual((r["product_name"], r["marketing_authorisation_holder"]), ("ADCETRIS", "Takeda Pharma A/S"))
        self.assertEqual((r["exclusivity_start"], r["paediatric_extension_months"], r["exclusivity_end_date"]),
                         ("2012-10-30", "24", "2024-06-20"))
        self.assertEqual(r["exclusivity_expiry"], "2024-06-20")
        self.assertEqual(r["expiry_basis"], "end date recorded in the Union Register")

    def test_computed_expiry(self):
        r = self.by[("EU/1/07/393", "EU/3/14/1304")]       # Soliris, myasthenia gravis: 10 years + 24 months
        self.assertEqual((r["exclusivity_start"], r["exclusivity_end_date"], r["exclusivity_expiry"]),
                         ("2017-08-17", "", "2029-08-17"))
        self.assertIn("24 months paediatric extension", r["expiry_basis"])
        r = self.by[("EU/1/07/393", "EU/3/13/1185")]
        self.assertEqual(r["exclusivity_expiry"], "2029-08-28")

    def test_no_projection_for_inactive_or_missing(self):
        r = self.by[("EU/1/22/1668", "EU/3/16/1622")]       # Roctavian, withdrawn, no end date
        self.assertEqual(r["exclusivity_expiry"], "")
        self.assertIn("Withdrawn", r["expiry_basis"])
        r = self.by[("EU/1/21/1605", "EU/3/14/1372")]       # no start date, but an end date
        self.assertEqual((r["exclusivity_start"], r["exclusivity_expiry"]), ("", "2022-01-19"))

    def test_holder_never_an_address_or_person(self):
        # the source has an address in this medicine's holder name field: it must be blanked
        self.assertEqual(self.by[("EU/1/21/1569", "EU/3/17/1936")]["marketing_authorisation_holder"], "")
        self.assertEqual(m.holder_or_blank("Dr Jane Example"), "")
        self.assertEqual(m.holder_or_blank("Novo Nordisk A/S"), "Novo Nordisk A/S")

    def test_add_months_clamps(self):
        self.assertEqual(m.add_months(dt.date(2016, 2, 29), 120), dt.date(2026, 2, 28))
        self.assertEqual(m.add_months(dt.date(2020, 10, 31), 4), dt.date(2021, 2, 28))

    def test_partial_dataset_refused(self):
        with self.assertRaises(RuntimeError):
            m.parse(self.raw)


if __name__ == "__main__":
    unittest.main()
