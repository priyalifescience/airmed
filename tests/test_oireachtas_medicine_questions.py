"""Offline test for the Oireachtas medicine-questions parser. Fixture: real questions (slimmed by fetch_raw, so the
asking member's "by" block is already absent) from the May 2020 and October 2026 windows, trimmed to a few per
window; the window counts are the real ones."""

import json
import unittest
from pathlib import Path

from airmed.collectors import oireachtas_medicine_questions as m
from airmed.privacy import check_fields, clean_record

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "oireachtas_medicine_questions.json"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestOireachtasMedicineQuestions(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw)
        self.by = {r["url"].rsplit("/", 2)[-2] + "/" + r["url"].rsplit("/", 1)[-1]: r for r in self.rows}

    def test_shape_and_filter(self):
        check_fields(m.FIELDS)
        # 8 questions in the fixture: ambulance, DOMINO and an Irish-language staffing question match no term
        self.assertEqual(len(self.rows), 5)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
            self.assertTrue(r["matched_terms"])
            self.assertTrue(r["question_text"].startswith("Minister for "))
            self.assertNotIn("Deputy", r["question_text"][:40])

    def test_values(self):
        r = self.by["2026-10-15/pq_121"]
        self.assertEqual((r["question_ref"], r["question_number"], r["question_type"], r["department"], r["topic"]),
                         ("72484/26", 121, "written", "Health", "Medicinal Products"))
        self.assertEqual(r["question_text"], "Minister for Health to provide an update on when skyclarys will be "
                                             "available for patients with Friedreich’s ataxia. [72484/26]")
        self.assertEqual(r["matched_terms"], ["medicine"])    # from the heading "Medicinal Products"
        self.assertEqual(r["web_url"], "https://www.oireachtas.ie/en/debates/question/2026-10-15/121/")
        self.assertEqual(r["record_xml_url"],
                         "https://data.oireachtas.ie/akn/ie/debateRecord/dail/2026-10-15/writtens/mul@/dbsect_135.xml")
        b = self.by["2020-05-27/pq_470"]
        self.assertEqual((b["department"], b["year"], b["matched_terms"], b["house"]),
                         ("Business", 2020, ["pharmaceutical"], "33rd Dáil"))

    def test_clean_text(self):
        self.assertEqual(m.clean_text("12. Deputy A Example asked the Minister for Health if ... [1/26]"),
                         "Minister for Health if ... [1/26]")
        self.assertEqual(m.clean_text(" 634. D'fhiafraigh Deputy A Example den Aire Sláinte cén fáth"),
                         "Aire Sláinte cén fáth")
        self.assertIsNone(m.clean_text("Question from A Example to the Minister"))
        self.assertEqual(m.matched_terms("supply of HRT products and pharmacies"), ["pharmacy"])
        self.assertEqual(m.matched_terms("the drugs payment scheme"), ["drug"])

    def test_deterministic_and_clean(self):
        self.assertEqual(self.rows, m.parse(self.raw))
        stats = {}
        for r in self.rows:
            clean_record(r, stats)
        self.assertEqual(stats.get("blanked", 0), 0)

    def test_incomplete_window_refused(self):
        data = json.loads(self.raw)
        data["parts"][1]["fetched"] -= 1
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(data).encode())

    def test_unrecognised_opening_refused(self):
        data = json.loads(self.raw)
        for q in data["parts"][1]["questions"]:
            q["showAs"] = q["showAs"].replace("Deputy", "Senator")
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
