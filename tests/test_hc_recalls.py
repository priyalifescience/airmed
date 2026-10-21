"""Offline test for the Health Canada recalls parser (fixture: real records from the open-data JSON, trimmed)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import hc_recalls as m
from airmed.privacy import check_fields

FIXTURE = Path(__file__).parent / "fixtures" / "hc_recalls.json"


class TestHcRecalls(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw)

    def test_shape(self):
        check_fields(m.FIELDS)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)

    def test_only_health_products_kept(self):
        # 11 fixture records: food (CFIA and a CPAB food notice), a vehicle, a veterinary-only and a cannabis record go
        self.assertEqual([r["recall_id"] for r in self.rows], [82808, 82412, 82807, 82620, 82454, 58041])
        orgs = {r["organization"] for r in self.rows}
        self.assertFalse(orgs & {"CFIA", "TC", "Consumer product safety", "Controlled substances and cannabis"})

    def test_values(self):
        r = self.rows[0]
        self.assertEqual(r["product"], "Dantrium Intravenous (Dantrolene sodium for injection)")
        self.assertEqual((r["issue"], r["category"], r["recall_class"], r["archived"]),
                         ("Contamination", "Drugs", "Type I", "no"))
        self.assertTrue(r["url"].startswith("https://recalls-rappels.canada.ca/en/alert-recall/"))

    def test_missing_field_refused(self):
        bad = json.loads(self.raw)
        for r in bad:
            r.pop("Recall class")
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(bad).encode())


if __name__ == "__main__":
    unittest.main()
