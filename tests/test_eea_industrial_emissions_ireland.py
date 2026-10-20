"""Offline test for the EEA Industrial Reporting (Ireland, chemical industry) parser. Fixture: real DiscoData rows for
two facilities (P0004 Cork, P0010 Hovione), trimmed to a few records; "counts" recomputed over the kept rows."""

import json
import unittest
from pathlib import Path

from airmed.collectors import eea_industrial_emissions_ireland as m
from airmed.privacy import check_fields, clean_record

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "eea_industrial_emissions_ireland.json"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestEeaIndustrialEmissionsIreland(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw)

    def test_shape(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 13)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
        self.assertEqual({r["record_type"] for r in self.rows},
                         {"pollutant_release", "pollutant_transfer", "waste_transfer"})
        self.assertEqual({r["epa_licence_profile"] for r in self.rows}, {"P0004", "P0010"})

    def test_values(self):
        r = [x for x in self.rows if x["eea_record_id"] == 7751241][0]
        self.assertEqual((r["reporting_year"], r["medium"], r["pollutant"], r["quantity"], r["unit"], r["method_code"]),
                         (2007, "AIR", "DCM", 2330, "kg", "C"))
        # the facility name of the same reporting year, not today's name
        self.assertEqual(r["facility_name"], "Smithkline Beecham (Cork) Limited")
        self.assertEqual((r["eprtr_activity"], r["number_of_employees"], r["nuts3"]), ("4(e)", 550, "IE053"))
        self.assertTrue(r["eprtr_activity_description"].endswith("basic pharmaceutical products"))
        w = [x for x in self.rows if x["eea_record_id"] == 9038199][0]
        self.assertEqual(w["facility_name"], "Thermo Fisher Scientific Cork Limited")
        self.assertEqual((w["waste_classification"], w["waste_treatment"], w["transboundary"], w["receiving_site_country"],
                          w["quantity"], w["unit"], w["number_of_employees"]), ("HW", "D", "yes", "DK", 0.016, "t", 400))
        t = [x for x in self.rows if x["eea_record_id"] == 537739][0]
        self.assertEqual((t["record_type"], t["medium"], t["pollutant"], t["quantity"]),
                         ("pollutant_transfer", "WASTEWATER", "DCM", 18.34))

    def test_deterministic_and_clean(self):
        self.assertEqual(self.rows, m.parse(self.raw))
        stats = {}
        for r in self.rows:
            clean_record(r, stats)
        self.assertEqual(stats.get("blanked", 0), 0)

    def test_truncated_reply_refused(self):
        data = json.loads(self.raw)
        data["waste_transfers"].pop()
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(data).encode())

    def test_orphan_record_refused(self):
        data = json.loads(self.raw)
        data["releases"][0]["facilityReportId"] = -1
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(data).encode())

    def test_registry_entry(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(src["status"], "approved")
        self.assertTrue(src["licence_url"].startswith("https://"))
        self.assertEqual(sorted(src["field_docs"]), sorted(m.FIELDS))


if __name__ == "__main__":
    unittest.main()
