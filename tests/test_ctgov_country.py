"""Offline tests for the ctgov_india and ctgov_china collectors (no network). Fixtures: 3 real studies each, trimmed to
the requested fields: one national study, one multinational, one with a lead sponsor classed OTHER."""

import json
import unittest
from pathlib import Path

from airmed.collectors import ctgov_china, ctgov_india, ctgov_ireland
from airmed.privacy import check_fields

FIXTURES = Path(__file__).parent / "fixtures"
REGISTRY = Path(__file__).parent.parent / "sources" / "registry.json"


class _Base:
    module = None
    country = ""
    national = ""
    multinational = ""

    def setUp(self):
        self.raw = (FIXTURES / f"{self.module.KEY}.json").read_bytes()

    def test_parse(self):
        rows = self.module.parse(self.raw)
        self.assertEqual(len(rows), 3)
        self.assertEqual([r["nct_id"] for r in rows], sorted(r["nct_id"] for r in rows))  # deterministic order
        for r in rows:
            self.assertEqual(list(r), list(ctgov_ireland.FIELDS) + ["countries"])
            self.assertIn(self.country, r["countries"])
            self.assertEqual(r["countries"], sorted(r["countries"]))
        by_id = {r["nct_id"]: r for r in rows}
        self.assertEqual(by_id[self.national]["countries"], [self.country])
        self.assertGreater(len(by_id[self.multinational]["countries"]), 2)  # all site countries kept

    def test_fields_clean(self):
        check_fields(self.module.FIELDS)

    def test_count_mismatch_refuses(self):
        data = json.loads(self.raw)
        data["totalCount"] = 99
        with self.assertRaises(RuntimeError):
            self.module.parse(json.dumps(data).encode())

    def test_study_without_site_in_country_refuses(self):
        data = json.loads(self.raw)
        data["studies"][0]["protocolSection"]["contactsLocationsModule"]["locations"] = [{"country": "Japan"}]
        with self.assertRaises(RuntimeError):
            self.module.parse(json.dumps(data).encode())

    def test_personal_sponsor_blanked(self):
        data = json.loads(self.raw)
        data["studies"][0]["protocolSection"]["sponsorCollaboratorsModule"]["leadSponsor"] = {"name": "Wei Zhang", "class": "OTHER"}
        nct = data["studies"][0]["protocolSection"]["identificationModule"]["nctId"]
        rows = {r["nct_id"]: r for r in self.module.parse(json.dumps(data).encode())}
        self.assertEqual(rows[nct]["lead_sponsor"], "")

    def test_registry_entry_matches(self):
        entry = json.loads(REGISTRY.read_text(encoding="utf-8"))["sources"][self.module.KEY]
        self.assertEqual(entry["status"], "approved")
        self.assertEqual(entry["fields_kept"], self.module.FIELDS)
        self.assertEqual(set(entry["field_docs"]), set(self.module.FIELDS))


class TestSponsorRuleIndia(unittest.TestCase):
    def test_indian_organisations_kept(self):
        for name in ("Jamia Millia Islamia", "PATH", "Sangath", "Aurolab", "Drugs for Neglected Diseases",
                     "Micronutrient Initiative", "Columbia Asia", "Pandit Bhagwat Dayal Sharma, PGIMS, Rohtak"):
            self.assertEqual(ctgov_ireland.sponsor_or_blank(name, "OTHER"), name)

    def test_people_still_blanked(self):
        for name in ("Shruti Shukla", "Dr Meru S", "Prashant Nasa", "Uprety Shraddha", "Ning Wang, MD., PhD.", "Pathak Ravi"):
            self.assertEqual(ctgov_ireland.sponsor_or_blank(name, "OTHER"), "")


class TestCtgovIndia(_Base, unittest.TestCase):
    module = ctgov_india
    country = "India"
    national = "NCT06199843"
    multinational = "NCT06976216"


class TestCtgovChina(_Base, unittest.TestCase):
    module = ctgov_china
    country = "China"
    national = "NCT06211439"
    multinational = "NCT07673887"


if __name__ == "__main__":
    unittest.main()
