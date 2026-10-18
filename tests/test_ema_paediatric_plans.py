"""Offline test for the EMA paediatric investigation plan decisions parser (fixture: EMA's JSON report trimmed to 8
decisions; e-mail addresses and phone numbers in the enquiries field replaced by placeholders)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import ema_paediatric_plans as m
from airmed.privacy import check_fields, clean_record

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "ema_paediatric_plans.json"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestEmaPaediatricPlans(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw, min_records=1)
        self.by = {r["decision_number"]: r for r in self.rows}

    def test_registry_entry(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["status"], "approved")
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(set(src["field_docs"]), set(m.FIELDS))
        check_fields(m.FIELDS)

    def test_shape_and_order(self):
        self.assertEqual(len(self.rows), 8)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
            self.assertTrue(r["url"].startswith("https://www.ema.europa.eu/"))
        keys = [(r["decision_number"], r["pip_number"], r["decision_date"], r["url"]) for r in self.rows]
        self.assertEqual(keys, sorted(keys))

    def test_decision(self):
        r = self.by["P/0169/2024"]
        self.assertEqual((r["pip_number"], r["invented_name"], r["active_substance"]),
                         ("EMEA-002727-PIP03-23", "Opdualag", "nivolumab;relatlimab"))
        self.assertEqual((r["decision_type_code"], r["decision_date"]), ("P", "2024-05-06"))
        self.assertEqual(r["organisation"], "Bristol-Myers Squibb EEIG")

    def test_compliance(self):
        r = self.by["P/0497/2022"]
        self.assertEqual(r["compliance_outcome"], "Positive")
        self.assertRegex(r["compliance_opinion_date"], r"^\d{4}-\d{2}-\d{2}$")

    def test_no_contact_details_survive(self):
        stats = {}
        for r in self.rows:
            clean_record(r, stats)
            for v in r.values():
                self.assertNotIn("@", v)
        self.assertEqual(stats.get("blanked", 0), 0)

    def test_organisation_or_blank(self):
        f = m.organisation_or_blank
        self.assertEqual(f("AbbVie LtdE-mail: a@b.com Tel. +44 000000"), "AbbVie Ltd")
        self.assertEqual(f("Dr. Falk Pharma GmbH; Email: a@b.de; Tel.: +49 000000"), "Dr. Falk Pharma GmbH")
        self.assertEqual(f("Ultragenyx UK Limited c/o Regus; Tel. +1 (000) 0000000"), "Ultragenyx UK Limited")
        self.assertEqual(f("Merck Sharp & Dohme B.V.pip.x@msd.com+33 000000"), "")   # end of name unknown
        self.assertEqual(f("E-mail: someone@example.org Tel. +1 000000"), "")
        self.assertEqual(f("Argenx  E-mail: a@b.com"), "")                              # no company marker
        self.assertEqual(f("Jane Example; jane@example.org"), "")
        self.assertEqual(f(""), "")

    def test_partial_dataset_refused(self):
        with self.assertRaises(RuntimeError):
            m.parse(self.raw)


if __name__ == "__main__":
    unittest.main()
