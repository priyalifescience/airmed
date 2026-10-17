"""Offline test for the EPA LEAP pharmaceutical licences parser (fixture trimmed from a real LEAP API download)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import epa_pharma_licences as m
from airmed.privacy import check_fields

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "epa_pharma_licences.json"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestEpaPharmaLicences(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw)
        self.by = {r["licence_profile"]: r for r in self.rows}

    def test_shape_and_filter(self):
        check_fields(m.FIELDS)
        # 7 profiles in the fixture; wood panels (8.7) and organic chemicals (5.12) are out of scope
        self.assertEqual(list(self.by), ["P0004", "P0008", "P0018", "P1102", "P1122"])
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
            self.assertIn(r["activity_class"], ("5.16", "5.6"))
            self.assertTrue(r["url"].startswith("https://leap.epa.ie/licence-profile/P"))

    def test_values(self):
        r = self.by["P0004"]
        self.assertEqual((r["licence_number"], r["licence_type"], r["licence_status"]),
                         ("P0004-06", "Industrial Emissions Licence", "Licensed"))
        self.assertEqual(r["licensee"], "Thermo Fisher Scientific Cork Limited")
        self.assertEqual((r["activity_class"], r["ied_activity_class"]), ("5.16", "4.5"))
        self.assertEqual(r["activity_description"], "The production of pharmaceutical products including intermediates.")
        self.assertEqual((r["first_licence_date"], r["current_licence_date"], r["licence_versions"]),
                         ("1994-12-06", "2020-11-19", 6))
        self.assertEqual((r["county"], r["nace_code"]), ("Cork", "2120"))
        w = self.by["P1122"]
        self.assertEqual((w["town"], w["eircode_routing_key"]), ("Dundalk", "A91"))
        leo = self.by["P0008"]   # pre-2013 IPC class wording, no IED activity, abandoned licence without a date
        self.assertEqual((leo["activity_class"], leo["ied_activity_class"], leo["current_licence_date"]), ("5.6", "", ""))
        self.assertEqual(self.by["P1102"]["first_licence_date"], "")   # withdrawn application, never granted

    def test_helpers(self):
        self.assertEqual(m.split_class("5.12 (b). The production of organic chemicals"), ("5.12 (b)", "The production of organic chemicals"))
        self.assertEqual(m.split_class("n/a"), ("", ""))
        self.assertEqual(m.routing_key("D15 YE36"), "D15")
        self.assertEqual(m.routing_key("d22 XR57"), "D22")
        self.assertEqual(m.routing_key("15"), "")          # bare Dublin district, not an Eircode
        self.assertEqual(m.org_or_blank("Mr A Example"), "")
        self.assertEqual(m.org_or_blank("Mr A Example & Mr B Example"), "")
        self.assertEqual(m.org_or_blank("Cara Partners"), "Cara Partners")

    def test_count_mismatch_raises(self):
        data = json.loads(self.raw)
        data["profiles"]["Industrial Emissions Licence"]["count"] = 99
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(data).encode())
        data = json.loads(self.raw)
        data["licences"]["P0004"]["count"] = 7
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(data).encode())

    def test_registry_entry_matches(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(set(src["field_docs"]), set(m.FIELDS))
        self.assertEqual(src["status"], "approved")


if __name__ == "__main__":
    unittest.main()
