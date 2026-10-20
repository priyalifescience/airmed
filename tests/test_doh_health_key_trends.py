"""Offline test for the Department of Health "Key Trends" parser (fixture: the real PxStat JSON-stat cubes, sliced
to the last two years and at most four categories)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import doh_health_key_trends as m
from airmed.privacy import check_fields

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "doh_health_key_trends.json"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestDohHealthKeyTrends(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw)

    def pick(self, table, stat, period, cat):
        return next(r for r in self.rows if (r["table"], r["statistic_code"], r["period"], r["category_code"])
                    == (table, stat, period, cat))

    def test_shape(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 152)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
        self.assertEqual(list(dict.fromkeys(r["table"] for r in self.rows)), m.TABLES)

    def test_gms_prescriptions(self):
        items = self.pick("KTA38", "KTA38C01", "2024", "IE0")
        self.assertEqual((items["value"], items["unit"], items["category"]), (71.226, "'000", "Ireland"))
        cost = self.pick("KTA38", "KTA38C03", "2024", "IE0")
        self.assertEqual((cost["statistic"], cost["value"]), ("Average cost per item", 15.2343105))

    def test_medical_cards(self):
        r = self.pick("KTA36", "KTA36C02", "2024", "205")
        self.assertEqual((r["breakdown"], r["category"], r["value"], r["unit"]), ("Age Group", "0 - 4 years", 20.4, "%"))

    def test_value_count_mismatch_refused(self):
        data = json.loads(self.raw)
        data["KTA38"]["value"].append(1.0)
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(data).encode())

    def test_missing_table_refused(self):
        data = json.loads(self.raw)
        del data["KTA37"]
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(data).encode())

    def test_registry_entry_matches(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(src["status"], "approved")
        self.assertEqual(list(src["field_docs"]), m.FIELDS)


if __name__ == "__main__":
    unittest.main()
