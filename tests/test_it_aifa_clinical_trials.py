"""Offline test for the AIFA (OsSC) clinical trial files (fixture: real rows of the 20250103 extracts: one ongoing
trial with 4 participating centres, two concluded trials (one ended early) and one withdrawn trial; the source rows
include the sponsor's contact e-mail, which must never be published)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import it_aifa_clinical_trials as m
from airmed.privacy import check_fields

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "it_aifa_clinical_trials.json"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestItAifaClinicalTrials(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw, min_trials={})

    def row(self, eudract):
        return next(r for r in self.rows if r["eudract_number"] == eudract)

    def test_shape_one_record_per_trial(self):
        check_fields(m.FIELDS)
        self.assertEqual([r["eudract_number"] for r in self.rows],
                         ["2007-002604-17", "2018-003608-38", "2021-000677-89", "2022-002316-23"])
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
            self.assertEqual(r["data_date"], "2025-01-03")

    def test_no_contact_emails(self):
        self.assertIn(b"@", self.raw)
        self.assertNotIn("@", json.dumps(self.rows))

    def test_ongoing_trial_centres(self):
        r = self.row("2022-002316-23")
        self.assertEqual((r["aifa_file"], r["phase"], r["aifa_decision"], r["aifa_decision_date"],
                          r["ethics_decision_date"], r["sponsor"], r["applicant"], r["participating_centres_count"]),
                         ("On-going", "Fase 3", "POSITIVE", "2023-01-12", "2023-01-16", "NOVARTIS PHARMA AG",
                          "NOVARTIS FARMA S.P.A.", 4))
        self.assertIn("AZIENDA OSPEDALIERO-UNIVERSITARIA DI MODENA [Emilia-Romagna]", r["participating_centres"])
        self.assertEqual(r["participating_regions"], ["Emilia-Romagna", "Lazio", "Lombardia"])
        self.assertEqual(r["condition"], "")                      # "-" in the source means not given

    def test_concluded_and_withdrawn(self):
        r = self.row("2018-003608-38")
        self.assertEqual((r["aifa_file"], r["concluded"], r["end_date_early"], r["early_end_efficacy"],
                          r["early_end_other_reasons"]), ("Concluse", "SI", "2022-07-07", "NO", "SI"))
        self.assertEqual(self.row("2007-002604-17")["end_date_regular"], "2019-12-19")
        r = self.row("2021-000677-89")
        self.assertEqual((r["aifa_file"], r["withdrawal_date"], r["participating_centres"]),
                         ("non approvate/ritirate", "2022-11-25", []))

    def test_too_few_trials_refused(self):
        with self.assertRaises(RuntimeError):
            m.parse(self.raw)

    def test_registry_entry_matches(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(src["status"], "approved")
        self.assertEqual(list(src["field_docs"]), m.FIELDS)


if __name__ == "__main__":
    unittest.main()
