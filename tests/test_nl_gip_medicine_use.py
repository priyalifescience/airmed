"""Offline test for the Zorginstituut GIP collector. Fixture: headers and real lines of three Open Data GIP files
(Farmacie meerjaren 2012-2016 with decimal commas, Farmacie meerjaren 2021-2025, Addon meerjaren 2021-2025 with
the "2024*" year marker) and a reduced year plan."""

import json
import unittest
from pathlib import Path

from airmed.collectors import nl_gip_medicine_use as m
from airmed.privacy import check_fields, clean_record

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "nl_gip_medicine_use.json"
SMALL = {"farmacie": 1, "addon": 1}


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestNlGipMedicineUse(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw, min_rows=SMALL)

    def test_shape(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 6)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)

    def test_values(self):
        s = [r for r in self.rows if r["atc_code"] == "A10BJ06"][0]
        self.assertEqual((s["year"], s["category"], s["atc_name"], s["reimbursement_eur"], s["users"],
                          s["dispensings"], s["ddd"], s["reimbursement_per_ddd"], s["atc_version_year"]),
                         (2025, "farmacie", "Semaglutide", 147009900, 157040, 837560, 50053500, 2.94, 2025))
        old = [r for r in self.rows if r["year"] == 2012 and r["atc_code"] == "A01AA01"][0]   # decimal commas
        self.assertEqual((old["atc_name"], old["reimbursement_per_user"], old["ddd_per_dispensing"],
                          old["source_file"]), ("Natriumfluoride", 10.34, 1372.0,
                                                "GIP Farmacie Zvw meerjaren 2012-2016_25012018"))
        nf = [r for r in self.rows if r["year"] == 2025 and r["atc_code"] == "A01AA01"][0]
        self.assertEqual((nf["ddd"], nf["ddd_per_user"]), (None, None))                          # "." in the source
        addon = [r for r in self.rows if r["category"] == "addon"][0]
        self.assertEqual((addon["year"], addon["year_asterisk"], addon["atc_code"], addon["users"],
                          addon["dispensings"]), (2024, True, "L04AB02", 18721, None))

    def test_plan_newest_file_wins(self):
        files = [("farmacie", 2021, 2025, "A", "u1"), ("farmacie", 2020, 2024, "B", "u2"),
                 ("addon", 2017, 2021, "C", "u3"), ("farmacie", 2008, 2012, "D", "u4")]
        p = m.plan(files)
        self.assertEqual(p[("farmacie", 2021)][0], "A")
        self.assertEqual(p[("farmacie", 2020)][0], "B")
        self.assertEqual(p[("farmacie", 2012)][0], "D")
        self.assertNotIn(("farmacie", 2011), p)        # before FIRST_YEAR
        self.assertEqual(p[("addon", 2017)][2], 2021)

    def test_deterministic_and_clean(self):
        self.assertEqual(self.rows, m.parse(self.raw, min_rows=SMALL))
        stats = {}
        for r in self.rows:
            clean_record(r, stats)
        self.assertEqual(stats.get("blanked", 0), 0)

    def test_refusals(self):
        with self.assertRaises(RuntimeError):
            m.parse(self.raw)                          # default MIN_ROWS: a real year has ~1,000 ATC codes
        with self.assertRaises(RuntimeError):
            m.value("1.234,5")
        data = json.loads(self.raw)
        t = "GIP Farmacie Zvw meerjaren 2021-2025_11052026"
        data["files"][t] = data["files"][t].replace("#DDD_per_gebruiker", "#nieuwe_kolom")
        with self.assertRaises(RuntimeError):          # unknown column
            m.parse(json.dumps(data).encode(), min_rows=SMALL)

    def test_registry_entry(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(src["status"], "approved")
        self.assertTrue(src["licence_url"].startswith("https://"))
        self.assertEqual(sorted(src["field_docs"]), sorted(m.FIELDS))


if __name__ == "__main__":
    unittest.main()
