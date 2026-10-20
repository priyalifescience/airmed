"""Offline test for the CSO System of Health Accounts parser (fixture: the real PxStat JSON-stat cubes SHA01-SHA15,
sliced to the last two years and a few categories)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import cso_health_accounts as m
from airmed.privacy import check_fields

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "cso_health_accounts.json"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestCsoHealthAccounts(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw)

    def pick(self, table, year, **codes):
        return [r for r in self.rows if r["table"] == table and r["year"] == year
                and all(r[k] == v for k, v in codes.items())]

    def test_shape(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 246)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
            self.assertNotEqual(r["value"], None)
        self.assertEqual(list(dict.fromkeys(r["table"] for r in self.rows)), m.TABLES)

    def test_function_by_financing(self):
        (total,) = self.pick("SHA12", "2024", function_code="-", financing_scheme_code="-")
        self.assertEqual((total["value"], total["unit"]), (36302.0, "Euro Million"))
        (goods,) = self.pick("SHA12", "2024", function_code="11", financing_scheme_code="01")
        self.assertIn("(HC.5)", goods["function"])
        self.assertIn("(HF.1)", goods["financing_scheme"])
        self.assertEqual(goods["value"], 3058.0)
        self.assertEqual((goods["provider_code"], goods["revenue_code"], goods["item_code"]), ("", "", ""))

    def test_other_breakdowns(self):
        (rev,) = self.pick("SHA09", "2024", revenue_code="18", financing_scheme_code="-")
        self.assertEqual(rev["value"], 36302.0)
        (line,) = self.pick("SHA08", "2024", item_code="16")
        self.assertEqual(line["value"], 28218.0)
        (gdp,) = self.pick("SHA07", "2024", statistic_code="SHA07C06")
        self.assertEqual((gdp["unit"], gdp["statistic"]), ("%", "Current Expenditure GPD"))   # CSO's spelling

    def test_value_count_mismatch_refused(self):
        data = json.loads(self.raw)
        data["SHA10"]["value"].append(1.0)
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(data).encode())

    def test_unknown_breakdown_refused(self):
        data = json.loads(self.raw)
        cube = data["SHA12"]
        cube["id"] = [d if d != "C03313V03997" else "C09999V09999" for d in cube["id"]]
        cube["dimension"]["C09999V09999"] = cube["dimension"].pop("C03313V03997")
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(data).encode())

    def test_missing_table_refused(self):
        data = json.loads(self.raw)
        del data["SHA15"]
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(data).encode())

    def test_registry_entry_matches(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(src["status"], "approved")
        self.assertEqual(list(src["field_docs"]), m.FIELDS)


if __name__ == "__main__":
    unittest.main()
