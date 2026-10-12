"""Offline tests: no network. Run with: python -m unittest discover -s tests"""

import json
import tempfile
import unittest
from pathlib import Path

from airmed.collectors import ALL, ctgov_ireland, ema_shortages, hpra_medicines
from airmed.output import write_dataset
from airmed.privacy import ForbiddenField, check_fields, clean_record
from airmed.registry import SourceNotApproved, approved_source, load_registry


class TestRegistry(unittest.TestCase):
    def test_every_collector_is_approved_with_matching_fields(self):
        for key, mod in ALL.items():
            src = approved_source(key)
            self.assertEqual(list(mod.FIELDS), src["fields_kept"], key)

    def test_blocked_sources_refuse(self):
        for key in ("nice_ta", "bfarm_shortages", "jrct", "umin_ctr", "eudragmdp", "yahoo_finance"):
            with self.assertRaises(SourceNotApproved):
                approved_source(key)

    def test_unknown_source_refuses(self):
        with self.assertRaises(SourceNotApproved):
            approved_source("does_not_exist")

    def test_registry_has_no_secrets_fields(self):
        text = json.dumps(load_registry()).lower()
        for word in ("api_key", "apikey", "password", "token=", "secret"):
            self.assertNotIn(word, text)


class TestPrivacy(unittest.TestCase):
    def test_forbidden_field_names(self):
        for name in ("contact_email", "investigator", "phone", "overall_official", "qppv_name"):
            with self.assertRaises(ForbiddenField):
                check_fields([name])

    def test_collector_fields_are_clean(self):
        for mod in ALL.values():
            check_fields(mod.FIELDS)

    def test_emails_and_phones_are_blanked(self):
        stats = {}
        r = clean_record({"title": "Call +353 1 234 5678", "lead_sponsor": "x@example.ie", "phases": ["PHASE2"],
                          "licence_number": "PA0736/003/003", "start_date": "2026-04-23"}, stats)
        self.assertEqual(r["title"], "")
        self.assertEqual(r["lead_sponsor"], "")
        self.assertEqual(r["phases"], ["PHASE2"])
        self.assertEqual(r["licence_number"], "PA0736/003/003")  # licence numbers are not phone numbers
        self.assertEqual(r["start_date"], "2026-04-23")           # dates are not phone numbers
        self.assertEqual(stats["blanked"], 2)


class TestParsers(unittest.TestCase):
    def test_ctgov(self):
        raw = json.dumps({"totalCount": 1, "studies": [{"protocolSection": {
            "identificationModule": {"nctId": "NCT00000001", "briefTitle": "A study"},
            "statusModule": {"overallStatus": "RECRUITING", "startDateStruct": {"date": "2026-01-02"},
                             "lastUpdatePostDateStruct": {"date": "2026-02-03"}},
            "sponsorCollaboratorsModule": {"leadSponsor": {"name": "University College Dublin"}},
            "conditionsModule": {"conditions": ["Asthma"]}, "designModule": {"phases": ["PHASE3"]}}}]}).encode()
        r = ctgov_ireland.parse(raw)[0]
        self.assertEqual(r["nct_id"], "NCT00000001")
        self.assertEqual(r["lead_sponsor"], "University College Dublin")
        self.assertEqual(sorted(r), sorted(ctgov_ireland.FIELDS))

    def test_ema(self):
        raw = json.dumps({"meta": {"total_records": 1}, "data": [{"category": "Human", "medicine_affected": "X",
            "supply_shortage_status": "Shortage ongoing", "therapeutic_area_mesh": "A;B", "shortage_url": "https://www.ema.europa.eu/x"}]}).encode()
        r = ema_shortages.parse(raw)[0]
        self.assertEqual(r["therapeutic_area"], ["A", "B"])
        self.assertEqual(sorted(r), sorted(ema_shortages.FIELDS))

    def test_ema_count_mismatch_refuses(self):
        raw = json.dumps({"meta": {"total_records": 5}, "data": []}).encode()
        with self.assertRaises(RuntimeError):
            ema_shortages.parse(raw)

    def test_hpra(self):
        raw = b"""<Products xmlns="https://assets.hpra.ie/products//xml/Human"><Product>
          <LicenceNumber>PA0001/001/001</LicenceNumber><ProductName>Test</ProductName><PAHolder>Acme Ltd</PAHolder>
          <AuthorisedDate>08/04/1987</AuthorisedDate><ATCs><ATC>V07AB</ATC></ATCs>
          <ActiveSubstances><ActiveSubstance>Sodium chloride</ActiveSubstance></ActiveSubstances>
          <RoutesOfAdministration><RoutesOfAdministration>Oral use</RoutesOfAdministration></RoutesOfAdministration>
          <DispensingLegalStatus><Status>Prescription</Status></DispensingLegalStatus></Product></Products>"""
        r = hpra_medicines.parse(raw, min_products=1)[0]
        self.assertEqual(r["authorised_date"], "1987-04-08")
        self.assertEqual(r["atc_codes"], ["V07AB"])
        self.assertEqual(r["routes"], ["Oral use"])
        self.assertEqual(sorted(r), sorted(hpra_medicines.FIELDS))

    def test_hpra_partial_download_refuses(self):
        with self.assertRaises(RuntimeError):
            hpra_medicines.parse(b'<Products xmlns="https://assets.hpra.ie/products//xml/Human"></Products>')


class TestOutput(unittest.TestCase):
    def test_writes_csv_json_and_datapackage(self):
        src = approved_source("ema_shortages")
        recs = [{k: "" for k in ema_shortages.FIELDS}]
        with tempfile.TemporaryDirectory() as d:
            res = write_dataset("ema_shortages", src, ema_shortages.FIELDS, recs, Path(d), {})
            pkg = json.loads((Path(res["dir"]) / "datapackage.json").read_text(encoding="utf-8"))
            self.assertEqual(pkg["licenses"][0]["path"], src["licence_url"])
            self.assertEqual(len(pkg["resources"]), 2)
            self.assertTrue((Path(res["dir"]) / "ema_shortages.csv").exists())


if __name__ == "__main__":
    unittest.main()
