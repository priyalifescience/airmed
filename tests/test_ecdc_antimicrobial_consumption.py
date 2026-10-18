"""Offline test for the ECDC ESAC-Net antimicrobial consumption parser (fixture: five sheets of the real 2022
downloadable tables workbook, trimmed to a few countries and rewritten with inline strings)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import ecdc_antimicrobial_consumption as m
from airmed.privacy import check_fields

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "ecdc_antimicrobial_consumption.xlsx"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestEcdcAntimicrobialConsumption(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw, min_countries=1)

    def find(self, table, label, year):
        return next(r for r in self.rows if (r["table"], r["country_label"], r["year"]) == (table, label, year))

    def test_shape(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 198)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
        self.assertEqual([r["table"] for r in self.rows][0], "D1")
        self.assertEqual(sorted({r["table"] for r in self.rows}, key=lambda t: int(t[1:])),
                         ["D1", "D11", "D17", "D22", "D24"])

    def test_values(self):
        r = self.find("D1", "Ireland", "2022")
        self.assertEqual((r["sector"], r["atc_code"], r["atc_group"], r["value"], r["unit"]),
                         ("Community", "J01A", "tetracyclines", 3.8181, m.DDD_UNIT))
        self.assertEqual((r["ecdc_trend"], r["ecdc_cagr"]), ("no significant trend", 0.0288316371997))
        carb = self.find("D11", "Ireland", "2013")
        self.assertEqual((carb["sector"], carb["atc_code"]), ("Hospital", "J01DH"))
        tb = self.find("D22", "Austria", "2018")
        self.assertEqual((tb["sector"], tb["atc_code"], tb["value"]), ("Community and hospital", "J04A", 0.1251))
        res = self.find("D24", "Ireland", "2022")
        self.assertEqual((res["atc_code"], res["unit"]), ("", m.RESERVE_UNIT))

    def test_cross_section_table(self):
        d17 = [r for r in self.rows if r["table"] == "D17"]
        self.assertEqual({r["atc_code"] for r in d17}, {"A07AA09+A07AA12", "P01AB01"})
        self.assertEqual({r["year"] for r in d17}, {"2022"})

    def test_gaps_and_markers(self):
        cy = self.find("D1", "Cyprus", "2022")
        self.assertEqual((cy["value"], cy["ecdc_trend"], cy["ecdc_cagr"]), ("", "not assessed", ""))
        fi = self.find("D11", "Finland (a)", "2013")
        self.assertEqual(fi["country"], "Finland")
        self.assertEqual(self.find("D1", "Reported EU/EEA**", "2013")["country"], "Reported EU/EEA")

    def test_footnotes_not_read_as_countries(self):
        # in D22 the footnote rows follow the country rows directly, without a blank row
        self.assertFalse(any(r["country"].startswith("All country") for r in self.rows))
        self.assertEqual(len([r for r in self.rows if r["table"] == "D22"]), 4 * 5)

    def test_too_few_countries_refused(self):
        with self.assertRaises(RuntimeError):
            m.parse(self.raw)

    def test_deterministic(self):
        self.assertEqual(self.rows, m.parse(self.raw, min_countries=1))

    def test_registry_entry_matches(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(src["status"], "approved")
        self.assertEqual(list(src["field_docs"]), m.FIELDS)


if __name__ == "__main__":
    unittest.main()
