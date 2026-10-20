"""Offline tests: no network. Run with: python -m unittest discover -s tests"""

import json
import tempfile
import unittest
from pathlib import Path

from airmed.collectors import ALL, ctgov_ireland, ema_shortages, hpra_medicines
from airmed.output import write_dataset
from airmed.privacy import ForbiddenField, check_fields, clean_record
from airmed.registry import SourceNotApproved, approved_source, held_sources, load_registry

HELD = {"dete_annual_employment_survey", "dete_employment_permits"}


class TestRegistry(unittest.TestCase):
    def test_every_collector_is_approved_with_matching_fields(self):
        for key, mod in ALL.items():
            if key in HELD:
                continue
            src = approved_source(key)
            self.assertEqual(list(mod.FIELDS), src["fields_kept"], key)

    def test_held_sources_are_pending_and_refused(self):
        held = held_sources()
        self.assertEqual(set(held), HELD)
        for key in HELD:
            self.assertTrue(held[key].startswith("Held 2026-10-20"), key)
            self.assertEqual(list(ALL[key].FIELDS), load_registry()[key]["fields_kept"], key)
            with self.assertRaises(SourceNotApproved):
                approved_source(key)

    def test_run_all_skips_held_sources_without_failing(self):
        from unittest import mock
        from airmed import cli
        ran = []
        fake = lambda key, out: ran.append(key) or {"dir": "x", "records": 1, "blanked": 0, "by_field": {}}
        with mock.patch.object(cli, "run_one", fake):
            self.assertEqual(cli.main(["run", "all", "--out", "unused"]), 0)
        self.assertEqual(set(ran), set(ALL) - HELD)
        self.assertEqual(cli.check(), 0)

    def test_licence_metadata_per_dataset(self):
        reg = load_registry()
        self.assertIn("ODbL", reg["nih_ireland"]["licence"])
        self.assertEqual(reg["nih_ireland"]["licence_url"], "https://opendatacommons.org/licenses/odbl/1.0/")
        for key in ("ctgov_ireland", "ctgov_europe"):
            self.assertIn("{retrieved_date}", reg[key]["attribution"])
            self.assertNotIn("Public data", reg[key]["licence"])
        for key in ("eurostat_pharma_industry", "eurostat_pharma_trade"):
            self.assertIn("Eurostat has no responsibility", reg[key]["attribution"])
        self.assertNotIn("equivalent in effect", reg["oecd_pharma_spending"]["licence"])
        for key, s in reg.items():
            if key.startswith("ema_") and s.get("status") == "approved":
                self.assertEqual(s["licence_url"], "https://www.ema.europa.eu/en/about-us/about-website/legal-notice", key)

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


class TestPrivacyPrecision(unittest.TestCase):
    """The guard must catch real phone numbers but never eat identifiers that look like long digit runs."""
    def test_phones_caught(self):
        from airmed.privacy import PHONE_RE
        for v in ["+353 1 234 5678", "+1-866-850-2876", "866-850-2876", "(866) 850-2876", "Call 01 234 5678", "087 123 4567"]:
            self.assertTrue(PHONE_RE.search(v), v)

    def test_identifiers_kept(self):
        stats = {}
        keep = {"package_ndc": "0641-6024-10", "presentation": "Fentanyl Citrate, Injection, 50 ug/1 mL (NDC 0641-6024-10)",
                "url": "https://www.ema.europa.eu/en/medicines/human/orphan-designations/ema-od-0000149115",
                "licence_number": "PA0736/003/003", "noc_number": "2026-01-15", "eu_designation_number": "EU/3/24/2954",
                "application_number": "ANDA202725", "start_date": "2026-04-23"}
        self.assertEqual(clean_record(keep, stats), keep)
        self.assertEqual(stats.get("blanked", 0), 0)


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


class TestRelease(unittest.TestCase):
    """The release builder must refuse anything unsafe or broken. Offline: small hand-made datasets."""

    def _collect(self, root, override=None, sources=None):
        from airmed.collectors import ALL
        for key, mod in ALL.items():
            recs = (override or {}).get(key, [{f: "x" for f in mod.FIELDS} for _ in range(10)])
            # held sources are written too (as an older copy left in out/ would be): the release must skip them
            src = (sources or {}).get(key) or (load_registry()[key] if key in HELD else approved_source(key))
            write_dataset(key, src, mod.FIELDS, recs, Path(root), {})

    def test_full_release_builds_catalog(self):
        from airmed.release import build
        with tempfile.TemporaryDirectory() as d:
            self._collect(Path(d) / "out")
            res = build(Path(d) / "out", Path(d) / "dist" / "v1")
            cat = json.loads((Path(d) / "dist" / "v1" / "catalog.json").read_text(encoding="utf-8"))
            self.assertEqual(res["datasets"], len(cat["datasets"]))
            for ds in cat["datasets"]:
                self.assertTrue(ds["licence_url"].startswith("https://"))
                self.assertTrue(all(f["description"] for f in ds["fields"]), ds["key"])
                self.assertTrue(ds["browse_url"].startswith("https://priyalifescience.com/"), ds["key"])
            self.assertEqual({ds["key"] for ds in cat["datasets"]}, set(ALL) - HELD)
            self.assertEqual(set(res["held"]), HELD)
            for key in HELD:
                self.assertFalse((Path(d) / "dist" / "v1" / key).exists())
            self.assertIn("multiple licences", cat["licence"])
            ct = next(ds for ds in cat["datasets"] if ds["key"] == "ctgov_ireland")
            self.assertNotIn("{retrieved_date}", ct["attribution"])
            self.assertRegex(ct["attribution"], r"retrieved on \d{4}-\d{2}-\d{2}\.")
            readme = (Path(d) / "dist" / "v1" / "README.md").read_text(encoding="utf-8")
            for text in ("Eurostat has no responsibility", "Houses of the Oireachtas is not liable", "ODbL",
                         "Reproduce the information accurately", "Clearly display the date the data were processed",
                         "back-calculate"):
                self.assertIn(text, readme)
            self.assertIn("Licence note:", (Path(d) / "dist" / "v1" / "DATA_DICTIONARY.md").read_text(encoding="utf-8"))

    def test_release_restamps_licence_from_registry(self):
        """A dataset collected under an older licence text is released with the registry's current licence."""
        import hashlib
        from airmed.release import build
        stale = dict(approved_source("nih_ireland"), licence="Public domain (U.S. government work)",
                     licence_url="https://reporter.nih.gov/faqs", attribution="old")
        with tempfile.TemporaryDirectory() as d:
            self._collect(Path(d) / "out", sources={"nih_ireland": stale})
            build(Path(d) / "out", Path(d) / "dist" / "v1")
            folder = Path(d) / "dist" / "v1" / "nih_ireland"
            pkg = json.loads((folder / "datapackage.json").read_text(encoding="utf-8"))
            self.assertIn("ODbL", pkg["licenses"][0]["title"])
            self.assertEqual(pkg["licenses"][0]["path"], "https://opendatacommons.org/licenses/odbl/1.0/")
            self.assertIn("ODbL", pkg["description"])
            payload = json.loads((folder / "nih_ireland.json").read_text(encoding="utf-8"))
            self.assertIn("ODbL", payload["licence"])
            self.assertEqual(len(payload["records"]), 10)
            res = next(r for r in pkg["resources"] if r["format"] == "json")
            self.assertEqual(res["hash"], "sha256:" + hashlib.sha256((folder / "nih_ireland.json").read_bytes()).hexdigest())

    def test_missing_dataset_refused(self):
        from airmed.release import ReleaseRefused, build
        with tempfile.TemporaryDirectory() as d:
            self._collect(Path(d) / "out")
            import shutil
            shutil.rmtree(Path(d) / "out" / "nih_ireland")
            with self.assertRaises(ReleaseRefused):
                build(Path(d) / "out", Path(d) / "dist" / "v1")

    def test_big_shrink_refused(self):
        from airmed.release import ReleaseRefused, build
        with tempfile.TemporaryDirectory() as d:
            self._collect(Path(d) / "out")
            build(Path(d) / "out", Path(d) / "dist" / "v1")
            from airmed.collectors import ema_shortages
            self._collect(Path(d) / "out2", {"ema_shortages": [{f: "x" for f in ema_shortages.FIELDS}]})
            with self.assertRaises(ReleaseRefused):
                build(Path(d) / "out2", Path(d) / "dist" / "v1")

    def test_contact_details_refused_at_release(self):
        from airmed.release import ReleaseRefused, build
        from airmed.collectors import nih_ireland
        with tempfile.TemporaryDirectory() as d:
            bad = [{f: "x" for f in nih_ireland.FIELDS} for _ in range(10)]
            bad[0]["project_title"] = "write to pi@example.ie"
            self._collect(Path(d) / "out", {"nih_ireland": bad})
            with self.assertRaises(ReleaseRefused):
                build(Path(d) / "out", Path(d) / "dist" / "v1")


class TestHttpSafety(unittest.TestCase):
    def test_plain_http_refused(self):
        from airmed.http import fetch
        with self.assertRaises(ValueError):
            fetch("http://example.com/")

    def test_redirect_downgrade_refused(self):
        import urllib.error, urllib.request
        from airmed.http import _HttpsOnlyRedirects
        h = _HttpsOnlyRedirects()
        req = urllib.request.Request("https://example.com/a")
        with self.assertRaises(urllib.error.HTTPError):
            h.redirect_request(req, None, 302, "Found", {}, "http://example.com/b")
        self.assertIsNotNone(h.redirect_request(req, None, 302, "Found", {}, "https://example.com/b"))
