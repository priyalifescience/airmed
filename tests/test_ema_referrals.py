"""Offline test for the EMA referrals parser (fixture: EMA's JSON report trimmed to 5 human and 2 veterinary
referrals)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import ema_referrals as m
from airmed.privacy import check_fields

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "ema_referrals.json"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestEmaReferrals(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw, min_records=1)
        self.by = {r["reference_number"]: r for r in self.rows}

    def test_registry_entry(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["status"], "approved")
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(set(src["field_docs"]), set(m.FIELDS))
        check_fields(m.FIELDS)

    def test_human_only_and_order(self):
        self.assertEqual(len(self.rows), 5)                 # the 2 veterinary referrals are left out
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
            self.assertTrue(r["url"].startswith("https://www.ema.europa.eu/en/medicines/human/referrals/"))
        keys = [(r["reference_number"], r["url"]) for r in self.rows]
        self.assertEqual(keys, sorted(keys))

    def test_ongoing_referral(self):
        r = self.by["EMA/REF/0000355053"]
        self.assertEqual((r["inn"], r["referral_type"], r["status"], r["procedure_start_date"], r["ec_decision_date"]),
                         ("rifampicin", "Article 31 referrals", "Procedure started", "2026-06-25", ""))

    def test_safety_referral(self):
        r = self.by["EMEA/H/A-31/1539"]
        self.assertEqual(r["safety_referral"], "yes")
        self.assertTrue(r["prac_recommendation"])
        self.assertEqual(r["therapeutic_class"], "genito-urinary system and sex hormones; dermatologicals")

    def test_dash_class_blank(self):
        self.assertNotIn("-", [r["therapeutic_class"] for r in self.rows])

    def test_partial_dataset_refused(self):
        with self.assertRaises(RuntimeError):
            m.parse(self.raw)


if __name__ == "__main__":
    unittest.main()
