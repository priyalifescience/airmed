"""Offline test for the hospital discharge (HIPE summary tables) parser (fixture: the real PxStat JSON-stat cubes,
sliced to the last two years, two age groups, Ireland / Ireland plus non-residents / Co. Cork and a few
diagnoses and procedures)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import cso_hospital_discharges as m
from airmed.privacy import check_fields

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "cso_hospital_discharges.json"
CORK = "2ae19629-1451-13a3-e055-000000000001"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestCsoHospitalDischarges(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw)

    def pick(self, table, year, **codes):
        return [r for r in self.rows if r["table"] == table and r["year"] == year
                and all(r[k] == v for k, v in codes.items())]

    def test_shape(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 474)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
        self.assertEqual(list(dict.fromkeys(r["table"] for r in self.rows)), list(m.TABLES))

    def test_diagnosis_values(self):
        (copd,) = self.pick("DHA77", "2025", sex_code="-", age_group_code="-", diagnosis_code="1006")
        self.assertIn("(J40-J44, J47)", copd["diagnosis"])
        self.assertEqual((copd["value"], copd["unit"]), (18496.0, "Number"))
        (allc,) = self.pick("DHA77", "2025", sex_code="-", age_group_code="-", diagnosis_code="0000")
        self.assertEqual(allc["value"], 1997823.0)

    def test_only_main_statistic_kept(self):
        self.assertEqual({r["statistic_code"] for r in self.rows if r["table"] == "DHA77"}, {"DHA77C01"})
        self.assertEqual({r["statistic_code"] for r in self.rows if r["table"] == "DHA76"},
                         {"DHA76C01", "DHA76C02", "DHA76C03"})

    def test_one_way_breakdowns(self):
        for r in self.rows:
            if r["table"].startswith("DHA"):
                detailed = [c for c in ("sex", "age_group", "area")
                            if r[c + "_code"] and r[c + "_code"] not in m.TOTALS[c]]
                self.assertLessEqual(len(detailed), 1, r)
        # the county row is kept at all ages and both sexes ...
        (cork,) = self.pick("DHA89", "2025", sex_code="-", age_group_code="-", area_code=CORK, diagnosis_code="0200")
        self.assertEqual((cork["area"], cork["value"]), ("Co. Cork", 19420.0))
        # ... but never crossed with an age group
        self.assertEqual(self.pick("DHA74", "2025", age_group_code="570", area_code=CORK), [])
        self.assertTrue(self.pick("DHA74", "2025", age_group_code="570", area_code="IE0"))

    def test_hipe_case_types(self):
        r = self.pick("HIPE03", "2024")
        self.assertEqual({x["case_type"] for x in r}, {"All inpatient and daycases", "Inpatient", "Daycases"})

    def test_value_count_mismatch_refused(self):
        data = json.loads(self.raw)
        data["DHA77"]["value"].append(1.0)
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(data).encode())

    def test_missing_statistic_refused(self):
        data = json.loads(self.raw)
        cat = data["DHA85"]["dimension"]["STATISTIC"]["category"]
        cat["index"] = [c if c != "DHA85C01" else "DHA85C09" for c in cat["index"]]
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(data).encode())

    def test_missing_table_refused(self):
        data = json.loads(self.raw)
        del data["HIPE02"]
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(data).encode())

    def test_registry_entry_matches(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(src["status"], "approved")
        self.assertEqual(list(src["field_docs"]), m.FIELDS)


if __name__ == "__main__":
    unittest.main()
