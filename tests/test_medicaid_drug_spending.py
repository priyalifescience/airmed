"""Offline test for the Medicaid SDUD parser. Fixture: real national product sums for two years and their FDA NDC
Directory names, trimmed to a few products; each year's "totals" were recomputed over the kept products."""

import json
import unittest
from pathlib import Path

from airmed.collectors import medicaid_drug_spending as m
from airmed.privacy import check_fields, clean_record

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "medicaid_drug_spending.json"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestMedicaidDrugSpending(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw, min_products=1)

    def test_shape(self):
        check_fields(m.FIELDS)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
        self.assertEqual(sorted({r["year"] for r in self.rows}), [2024, 2025])
        keys = [(r["year"], r["ndc_product"]) for r in self.rows]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(len(keys), len(set(keys)))

    def test_suppressed_products_dropped(self):
        data = json.loads(self.raw)
        n_in = sum(len(y["products"]) for y in data["years"].values())
        n_suppressed = sum(1 for y in data["years"].values() for p in y["products"] if p["rx"] is None and p["mcd"] is None)
        self.assertGreater(n_suppressed, 0)
        self.assertEqual(len(self.rows), n_in - n_suppressed)

    def test_fda_names_joined(self):
        bik = [r for r in self.rows if r["ndc_product"] == "61958-2501" and r["year"] == 2025]
        self.assertEqual(len(bik), 1)
        b = bik[0]
        self.assertEqual(b["fda_proprietary_name"], "Biktarvy")
        self.assertEqual(b["fda_substance_name"], "BICTEGRAVIR SODIUM; EMTRICITABINE; TENOFOVIR ALAFENAMIDE FUMARATE")
        self.assertEqual(b["fda_labeler_name"], "Gilead Sciences, Inc.")
        self.assertEqual(b["fda_name_source"], "current")
        self.assertEqual(b["cms_product_name"], "Biktarvy B")
        self.assertEqual(b["medicaid_amount_reimbursed_usd"], 3479548838.29)
        self.assertGreaterEqual(b["total_amount_reimbursed_usd"], b["medicaid_amount_reimbursed_usd"])
        cym = [r for r in self.rows if r["ndc_product"] == "00002-3235"]
        self.assertTrue(cym and all(r["fda_name_source"] == "excluded" for r in cym))

    def test_unknown_product_keeps_cms_name_only(self):
        unk = [r for r in self.rows if not r["fda_name_source"]]
        self.assertTrue(unk)
        self.assertTrue(all(r["fda_proprietary_name"] == "" and r["cms_product_name"] for r in unk))

    def test_codes_stay_text(self):
        self.assertTrue(all(isinstance(r["labeler_code"], str) and len(r["labeler_code"]) == 5 for r in self.rows))
        self.assertTrue(all(len(r["product_code"]) == 4 for r in self.rows))

    def test_deterministic_and_clean(self):
        self.assertEqual(self.rows, m.parse(self.raw, min_products=1))
        stats = {}
        for r in self.rows:
            clean_record(r, stats)
        self.assertEqual(stats.get("blanked", 0), 0)

    def test_totals_mismatch_refused(self):
        data = json.loads(self.raw)
        y = sorted(data["years"])[0]
        data["years"][y]["totals"]["mcd"] = "1.00"
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(data).encode(), min_products=1)

    def test_too_few_products_refused(self):
        with self.assertRaises(RuntimeError):
            m.parse(self.raw)   # default MIN_PRODUCTS: a real year has ~30,000 products

    def test_person_like_labeler_blanked(self):
        data = json.loads(self.raw)
        data["fda"]["619582501"][3] = "Jane Doe"
        rows = m.parse(json.dumps(data).encode(), min_products=1)
        self.assertTrue(all(r["fda_labeler_name"] != "Jane Doe" for r in rows))

    def test_registry_entry(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(src["status"], "approved")
        self.assertTrue(src["licence_url"].startswith("https://"))
        self.assertEqual(sorted(src["field_docs"]), sorted(m.FIELDS))


if __name__ == "__main__":
    unittest.main()
