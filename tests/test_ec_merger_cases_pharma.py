"""Offline tests for the EC pharmaceutical merger cases parser (fixture trimmed from the real competition case
search reply of 21 October 2026: five cases, their decisions and the reference-data labels they use)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import ec_merger_cases_pharma as m
from airmed.privacy import check_fields

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "ec_merger_cases_pharma.json"


class TestEcMergerCasesPharma(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw)
        self.by = {r["case_number"]: r for r in self.rows}

    def test_shape(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 5)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
            self.assertTrue(r["case_url"].startswith("https://competition-cases.ec.europa.eu/cases/M."))

    def test_values(self):
        r = self.by["M.11383"]
        self.assertEqual(r["title"], "COOPER / VIATRIS (EUROPEAN OTC BUSINESS)")
        self.assertEqual(r["nace_codes"], ["C.21.20"])
        self.assertEqual(r["notification_date"], "2024-05-03")        # 2024-05-02T22:00Z is 3 May in Brussels
        self.assertEqual(r["decision_dates"], ["2024-06-26", "2024-12-09", "2025-01-10"])
        self.assertEqual(r["decision_types"][0], "Art. 6(1)(b) with conditions & obligations")
        self.assertEqual(r["decision_count"], 3)
        self.assertEqual((r["regulation"], r["procedure"], r["case_type"]),
                         ("Council Regulation (EC) No 139/2004", "Normal", "Merger"))
        open_case = self.by["M.12585"]
        self.assertEqual((open_case["decision_count"], open_case["last_decision_date"]), (0, ""))
        self.assertEqual(open_case["procedure"], "Simplified")
        self.assertEqual(self.by["M.10483.AP"]["case_type"], "Additional Procedure")
        dates = [r["notification_date"] or r["initiation_date"] for r in self.rows]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_person_like_titles_withheld(self):
        w = self.by["M.5393"]          # "... LABORATORIOS DEL DR. ESTEVE ...": over-blanked on purpose
        self.assertEqual((w["title"], w["title_withheld"]), ("", "yes"))
        self.assertTrue(m.PERSON.search("Mr John Example / Example Pharma"))
        self.assertFalse(m.PERSON.search("SANOFI / BOEHRINGER INGELHEIM CONSUMER HEALTHCARE BUSINESS"))

    def test_dates_and_request(self):
        self.assertEqual(m.brussels_date("2020-04-13T22:00:00.000+0000"), "2020-04-14")
        self.assertEqual(m.brussels_date("2024-01-04T23:00:00.000+0000"), "2024-01-05")
        self.assertEqual(m.brussels_date(""), "")
        body, headers = m._multipart({"bool": {}})
        self.assertIn(b'name="query"', body)
        self.assertIn(b'name="sort"', body)
        self.assertIn(b"metadataReference", body)
        self.assertTrue(headers["Content-Type"].startswith("multipart/form-data; boundary="))

    def test_labels_missing_falls_back_to_codes(self):
        data = json.loads(self.raw)
        data["refdata"] = {"error": "unreachable"}
        rows = {r["case_number"]: r for r in m.parse(json.dumps(data).encode())}
        self.assertEqual(rows["M.11383"]["nace_codes"], ["NaceSectorsC_21_2_0"])
        self.assertTrue(rows["M.11383"]["decision_types"][0].startswith("DecisionType"))

    def test_registry_entry_matches(self):
        src = json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][m.KEY]
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(src["status"], "approved")
        self.assertEqual(set(src["field_docs"]), set(m.FIELDS))
        ccpc = json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"]["ccpc_merger_notifications"]
        self.assertEqual(ccpc["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
