"""Offline test for the MHRA safety alerts parser (fixture trimmed from a real GOV.UK Search API reply)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import mhra_safety_alerts as m
from airmed.privacy import check_fields

FIXTURE = Path(__file__).parent / "fixtures" / "mhra_safety_alerts.json"


class TestMhraSafetyAlerts(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw)

    def test_fields_and_count(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 5)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
            self.assertTrue(r["url"].startswith("https://www.gov.uk/"))
            self.assertRegex(r["issued_date"], r"^\d{4}-\d{2}-\d{2}$")

    def test_values(self):
        recall = next(r for r in self.rows if "Class 2 Medicines Recall" in r["title"])
        self.assertEqual(recall["document_type"], "medical_safety_alert")
        self.assertEqual(recall["alert_class"], "Class 2")
        self.assertEqual(recall["alert_type"], ["medicines-recall-notification"])
        self.assertTrue(recall["specialties"])
        dsu = [r for r in self.rows if r["document_type"] == "drug_safety_update"]
        self.assertEqual(len(dsu), 2)
        self.assertEqual(dsu[-1]["issued_date"], "2009-10-03")   # datetime normalised to a date
        self.assertEqual(dsu[0]["alert_type"], [])

    def test_sorted_newest_first(self):
        dates = [r["issued_date"] for r in self.rows]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_count_mismatch_raises(self):
        data = json.loads(self.raw)
        data["totals"]["drug_safety_update"] = 3
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(data).encode())


if __name__ == "__main__":
    unittest.main()
