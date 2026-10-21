"""Offline test for the FDA NDC Directory parser (fixture: seven real products from openFDA's drug/ndc bulk file,
October 2026, slimmed as fetch_raw slims them; the one OTC row's labeler and brand were replaced by example names)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import fda_ndc_directory as m
from airmed.privacy import check_fields, clean_record

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "fda_ndc_directory.json"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestFdaNdcDirectory(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw, min_records=1)
        self.by = {r["product_ndc"]: r for r in self.rows}

    def test_shape_and_scope(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 6)          # the OTC product is out of scope
        self.assertNotIn("HUMAN OTC DRUG", {r["product_type"] for r in self.rows})
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
        keys = [(r["product_ndc"], r["product_id"]) for r in self.rows]
        self.assertEqual(keys, sorted(keys))

    def test_values(self):
        p = self.by["60715-3150"]
        self.assertEqual((p["labeler_name"], p["product_type"], p["finished"], p["generic_name"]),
                         ("Pfizer Ireland Pharmaceuticals Unlimited Company", "BULK INGREDIENT", "no", "Azithromycin"))
        self.assertEqual((p["marketing_start_date"], p["listing_expiration_date"]), ("2011-12-29", "2026-12-31"))
        o = self.by["71335-0146"]
        self.assertEqual((o["dea_schedule"], o["application_number"], o["finished"], o["package_count"]),
                         ("CII", "ANDA202677", "yes", 10))
        self.assertTrue(o["pharm_class"] and isinstance(o["route"], list))
        z = self.by["71894-123"]
        self.assertEqual((z["brand_name"], z["application_number"], z["spl_set_id"]),
                         ("Zolgensma", "BLA125694", "68cd4f06-70e1-40d8-bedb-609ec0afa471"))
        self.assertEqual(self.by["0002-0013"]["active_ingredients"], ["INSULIN HUMAN 100 [iU]/mL"])

    def test_company_rule(self):
        f = m.company_or_blank
        self.assertEqual(f("Takeda Ireland Ltd.", 1), "Takeda Ireland Ltd.")
        self.assertEqual(f("Novartis", 1), "Novartis")                          # one word: never a full personal name
        self.assertEqual(f("Dr. Reddy's Laboratories Inc.", 650), "Dr. Reddy's Laboratories Inc.")
        self.assertEqual(f("Dr. Reddy's Laboratories Inc.", 3), "")              # "Dr." in a small firm: withheld
        self.assertEqual(f("Jane Q. Doe, M.D., Inc.", 3), "")
        self.assertEqual(f("Doe, Jane", 3), "")
        self.assertEqual(f("Example Pharma, LLC", 1), "Example Pharma, LLC")    # "Word, LLC" is not an inverted name
        self.assertEqual(f("Jane Doe", 3), "")
        self.assertEqual(f("Novo Nordisk", 61), "Novo Nordisk")                  # no company word, but many products

    def test_person_like_labeler_withheld_with_brand(self):
        data = json.loads(self.raw)
        data["results"][3]["labeler_name"] = "Jane Doe"
        data["results"][3]["brand_name"] = "Doe Relief"
        r = {x["product_ndc"]: x for x in m.parse(json.dumps(data).encode(), min_records=1)}["71335-0146"]
        self.assertEqual((r["labeler_name"], r["labeler_withheld"], r["brand_name"]), ("", "yes", ""))
        self.assertEqual(r["generic_name"], "Oxycodone and Acetaminophen")

    def test_partial_file_refused(self):
        with self.assertRaises(RuntimeError):
            m.parse(self.raw)
        data = json.loads(self.raw)
        data["total_in_file"] = 99
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(data).encode(), min_records=1)

    def test_no_packages_in_fixture(self):
        text = self.raw.decode("utf-8")
        self.assertNotIn("package_ndc", text)
        self.assertNotIn("packaging", text)

    def test_deterministic_and_clean(self):
        self.assertEqual(self.rows, m.parse(self.raw, min_records=1))
        stats = {}
        for r in self.rows:
            clean_record(r, stats)
        self.assertEqual(stats.get("blanked", 0), 0)

    def test_registry_entry(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(src["status"], "approved")
        self.assertTrue(src["licence_url"].startswith("https://"))
        self.assertEqual(sorted(src["field_docs"]), sorted(m.FIELDS))


if __name__ == "__main__":
    unittest.main()
