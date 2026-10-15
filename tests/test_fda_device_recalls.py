"""Offline test for the FDA device recalls parser (fixture trimmed from real openFDA enforcement + recall replies)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import fda_device_recalls as m
from airmed.privacy import check_fields

FIXTURE = Path(__file__).parent / "fixtures" / "fda_device_recalls.json"


class TestFdaDeviceRecalls(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw)
        self.by = {r["recall_number"]: r for r in self.rows}

    def test_shape(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 3)   # the record with no recall number (not yet classified) is dropped
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
        dates = [r["recall_initiation_date"] for r in self.rows]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_join_and_values(self):
        r = self.by["Z-2372-2023"]
        self.assertEqual((r["classification"], r["firm_country"], r["event_id"]), ("Class I", "United States", "92660"))
        self.assertEqual((r["product_code"], r["root_cause"]), ("NIE", "Process control"))
        self.assertEqual(r["recall_initiation_date"], "2023-06-28")
        self.assertEqual(r["termination_date"], "")
        self.assertEqual(self.by["Z-1618-2023"]["firm_country"], "Germany")
        self.assertEqual(self.by["Z-1618-2023"]["termination_date"], "2024-06-06")
        self.assertLessEqual(len(r["product_description"]), m.DESC_MAX)

    def test_unmatched_recall_keeps_row_with_blank_root_cause(self):
        data = json.loads(self.raw)
        data["recalls"] = [x for x in data["recalls"] if x["product_res_number"] != "Z-0189-2019"]
        r = {x["recall_number"]: x for x in m.parse(json.dumps(data).encode())}["Z-0189-2019"]
        self.assertEqual((r["root_cause"], r["product_code"]), ("", ""))
        self.assertEqual(r["classification"], "Class II")

    def test_no_address_or_contact_in_fixture(self):
        text = self.raw.decode("utf-8")
        for bad in ("address_1", "postal_code", "additional_info_contact"):
            self.assertNotIn(bad, text)


if __name__ == "__main__":
    unittest.main()
