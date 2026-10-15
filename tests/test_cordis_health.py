"""Offline test for the CORDIS health collector, on a trimmed real fixture (5 projects, 3 of them health)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import cordis_health
from airmed.privacy import check_fields

FIXTURE = Path(__file__).parent / "fixtures" / "cordis_health.json"


class TestCordisHealth(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = cordis_health.parse(self.raw)
        self.by_id = {r["project_id"]: r for r in self.rows}

    def test_health_filter(self):
        # 825179 (energy, LC-SC3) and 101069359 (Cluster 5 climate) must be filtered out
        self.assertEqual(sorted(self.by_id), ["101046041", "115842", "633888"])
        self.assertEqual(self.by_id["115842"]["health_filter_basis"], ["programme", "joint_undertaking", "euroscivoc"])
        self.assertEqual(self.by_id["633888"]["health_filter_basis"], ["euroscivoc"])  # ERC, kept via EuroSciVoc
        self.assertEqual(self.by_id["101046041"]["health_filter_basis"], ["programme", "euroscivoc"])

    def test_fields_and_values(self):
        for r in self.rows:
            self.assertEqual(sorted(r), sorted(cordis_health.FIELDS))
            self.assertTrue(r["coordinator_organisation"])
            self.assertEqual(r["cordis_url"], "https://cordis.europa.eu/project/id/" + r["project_id"])
        he = self.by_id["101046041"]
        self.assertEqual(he["total_cost_eur"], "10048971.68")  # decimal comma normalised
        self.assertEqual(he["coordinator_country"], "CH")
        self.assertEqual(he["participant_countries"], sorted(set(he["participant_countries"])))
        self.assertEqual(he["organisation_count"], len(he["participant_organisations"]))

    def test_deterministic_order(self):
        ids = [int(r["project_id"]) for r in self.rows]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(self.rows, cordis_health.parse(self.raw))

    def test_no_address_columns_in_raw(self):
        cols = json.loads(self.raw)["columns"]["organization.csv"]
        for bad in ("street", "postCode", "geolocation", "contactForm", "vatNumber", "organizationURL"):
            self.assertNotIn(bad, cols)
        check_fields(cordis_health.FIELDS)


if __name__ == "__main__":
    unittest.main()
