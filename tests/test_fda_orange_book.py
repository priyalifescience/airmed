"""Offline test for the FDA Orange Book patents + exclusivity parser (fixture: real data files trimmed to 4 products)."""

import io
import json
import unittest
import zipfile
from pathlib import Path

from airmed.collectors import fda_orange_book as m
from airmed.privacy import check_fields

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "fda_orange_book.zip"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


def rezip(raw: bytes, edit) -> bytes:
    src = zipfile.ZipFile(io.BytesIO(raw))
    files = {n: src.read(n).decode("ascii") for n in src.namelist()}
    edit(files)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for n, t in files.items():
            z.writestr(n, t)
    return out.getvalue()


class TestFdaOrangeBook(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw, min_records=1)

    def test_registry_entry(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["status"], "approved")
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(set(src["field_docs"]), set(m.FIELDS))
        check_fields(m.FIELDS)

    def test_shape(self):
        self.assertEqual(len(self.rows), 25)       # 13 patent rows + 12 distinct exclusivity rows
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
        kinds = [r["record_type"] for r in self.rows]
        self.assertEqual((kinds.count("patent"), kinds.count("exclusivity")), (13, 12))
        keys = [(r["appl_type"], r["appl_no"], r["product_no"]) for r in self.rows]
        self.assertEqual(keys, sorted(keys))

    def test_patent_values(self):
        ped = [r for r in self.rows if r["appl_no"] == "020610" and r["patent_no"] == "7452872"]
        self.assertEqual([(r["pediatric_extension"], r["patent_expiry"]) for r in ped],
                         [("", "2026-08-24"), ("yes", "2027-02-24")])
        p = ped[0]
        self.assertEqual((p["trade_name"], p["ingredient"], p["patent_use_code"]), ("COLAZAL", "BALSALAZIDE DISODIUM", "U-141"))
        self.assertEqual((p["approval_date"], p["reference_listed_drug"], p["marketing_category"]), ("2000-07-18", "yes", "prescription"))
        self.assertEqual(p["exclusivity_code"], "")
        re_ = next(r for r in self.rows if r["patent_no"] == "RE44733")
        self.assertEqual((re_["drug_substance_claim"], re_["drug_product_claim"], re_["patent_submitted"]), ("yes", "yes", "2016-01-12"))
        self.assertEqual(re_["applicant"], "MERCK SHARP AND DOHME LLC A SUB OF MERCK AND CO INC")

    def test_exclusivity_values(self):
        pc = next(r for r in self.rows if r["appl_type"] == "A")
        self.assertEqual((pc["record_type"], pc["exclusivity_code"], pc["exclusivity_expiry"]), ("exclusivity", "PC", "2026-11-24"))
        self.assertEqual((pc["patent_no"], pc["patent_expiry"]), ("", ""))
        # the source repeats some exclusivity lines verbatim; each is kept once
        ex = [(r["appl_no"], r["exclusivity_code"], r["exclusivity_expiry"]) for r in self.rows if r["record_type"] == "exclusivity"]
        self.assertEqual(len(ex), len(set(ex)))

    def test_bad_header_raises(self):
        bad = rezip(self.raw, lambda f: f.__setitem__("patent.txt", f["patent.txt"].replace("Patent_No", "PatentNumber", 1)))
        with self.assertRaises(RuntimeError):
            m.parse(bad, min_records=1)

    def test_orphan_patent_row_raises(self):
        bad = rezip(self.raw, lambda f: f.__setitem__("patent.txt", f["patent.txt"] + "N~999999~001~1234567~Jan 1, 2030~~~~~\n"))
        with self.assertRaises(RuntimeError):
            m.parse(bad, min_records=1)

    def test_partial_dataset_refused(self):
        with self.assertRaises(RuntimeError):
            m.parse(self.raw)


if __name__ == "__main__":
    unittest.main()
