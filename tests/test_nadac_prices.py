"""Offline test for the CMS NADAC parser (fixture trimmed from a real data.medicaid.gov datastore reply)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import nadac_prices as m
from airmed.privacy import check_fields

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "nadac_prices.json"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestNadacPrices(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw)
        self.by = {r["ndc"]: r for r in self.rows}

    def test_shape(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 7)   # 8 rows in the file, one an exact repeat
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
            self.assertEqual(r["as_of_date"], "2026-10-14")
        names = [r["ndc_description"].lower() for r in self.rows]
        self.assertEqual(names, sorted(names))

    def test_values(self):
        r = self.by["00002418430"]
        self.assertEqual((r["ndc_description"], r["nadac_per_unit"], r["pricing_unit"]), ("EVISTA 60 MG TABLET", "6.34306", "EA"))
        self.assertEqual(r["classification_for_rate_setting"], "B")
        self.assertEqual((r["corresponding_generic_drug_nadac_per_unit"], r["corresponding_generic_drug_effective_date"]),
                         ("0.22348", "2026-09-23"))
        self.assertEqual(self.by["00002773701"]["explanation_code"], "1, 5, 6")
        self.assertEqual(self.by["00002773701"]["corresponding_generic_drug_effective_date"], "")   # null in source
        self.assertEqual(self.by["00002898005"]["classification_for_rate_setting"], "B-BIO")

    def test_count_mismatch_refused(self):
        data = json.loads(self.raw)
        data["count"] += 1
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(data).encode())

    def test_differing_duplicate_kept(self):
        data = json.loads(self.raw)
        twin = dict(data["rows"][1], nadac_per_unit="9.99999")
        data["rows"].append(twin)
        data["count"] += 1
        prices = sorted(r["nadac_per_unit"] for r in m.parse(json.dumps(data).encode()) if r["ndc"] == twin["ndc"])
        self.assertEqual(prices, ["6.34306", "9.99999"])

    def test_registry_entry_matches(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(src["status"], "approved")
        self.assertEqual(set(src["field_docs"]), set(m.FIELDS))


if __name__ == "__main__":
    unittest.main()
