"""Offline test for the FEST collector. Fixture: a zip holding a cut-down copy of the real FEST 2.5.1 Rekvirent file
of 8 October 2026: its HentetDato and four real package entries (Zyprexa Velotab 5 mg, Lipitor 80 mg, Ozempic
0.25 mg and Omlyclo 300 mg, which has a reimbursement price ending and a stepped price starting after the extract
date), with the brand, substance, reimbursement and substitution-group entries they point to."""

import io
import json
import unittest
import zipfile
from pathlib import Path

from airmed.collectors import no_fest_medicines as m
from airmed.privacy import check_fields, clean_record

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "no_fest_medicines.zip"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestNoFestMedicines(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw, min_packages=1)
        self.by = {r["varenr"]: r for r in self.rows}

    def test_shape(self):
        check_fields(m.FIELDS)
        self.assertEqual([r["varenr"] for r in self.rows], ["000159", "061561", "110341", "129359"])
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
            self.assertEqual(r["fest_date"], "2026-10-08")

    def test_values(self):
        lip = self.by["061561"]
        self.assertEqual((lip["atc_code"], lip["name_form_strength"], lip["brand_name"], lip["company"],
                          lip["active_substances"], lip["pack_size"], lip["pack_unit"], lip["ddd"], lip["ddd_unit"]),
                         ("C10AA05", "Lipitor tab 80 mg", "Lipitor", "Viatris Healthcare Limited", ["Atorvastatin"],
                          "100", "stk", 0.02, "g"))
        self.assertEqual((lip["aup_nok"], lip["aip_nok"], lip["reimbursement_price_nok"], lip["step_price_nok"],
                          lip["aup_valid_from"]), (832.9, 624.83, 169.7, 169.7, "2026-05-01"))
        self.assertEqual((lip["reimbursed"], lip["reimbursement_groups"], lip["reimbursement_basis"],
                          lip["substitution_group"], lip["substitution_group_name"]),
                         ("yes", ["C10AA05_1"], ["§5-14 §2"], "001621", "ATORVASTATIN TABLETTER 80MG"))
        oz = self.by["110341"]
        self.assertEqual((oz["ean"], oz["reimbursed"], oz["reimbursement_price_nok"], oz["routes"]),
                         (["5712249132736", "5712249108496"], "no", "", ["Subkutan bruk"]))

    def test_price_valid_on_extract_date(self):
        om = self.by["129359"]
        # Refusjonspris 6153.3 runs to 2026-10-15 and Trinnpris starts 2026-10-15; the extract is 2026-10-08
        self.assertEqual((om["reimbursement_price_nok"], om["step_price_nok"], om["black_triangle"],
                          om["reference_product"]), (6153.3, "", "yes", "Xolair"))
        self.assertEqual(m._price_now([("AUP", "1", "2026-01-01", ""), ("AUP", "2", "2026-09-01", ""),
                                       ("AUP", "3", "2026-11-01", "")], "2026-10-08"), {"AUP": ("2026-09-01", "2")})

    def test_deterministic_and_clean(self):
        self.assertEqual(self.rows, m.parse(self.raw, min_packages=1))
        stats = {}
        for r in self.rows:
            clean_record(r, stats)
        self.assertEqual(stats.get("blanked", 0), 0)

    def test_partial_refused(self):
        with self.assertRaises(RuntimeError):
            m.parse(self.raw)                                   # default MIN_PACKAGES
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as o:
            o.writestr("a.xml", b"<FEST/>")
            o.writestr("b.xml", b"<FEST/>")
        with self.assertRaises(RuntimeError):
            m.parse(buf.getvalue(), min_packages=0)

    def test_registry_entry(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(src["status"], "approved")
        self.assertTrue(src["licence_url"].startswith("https://"))
        self.assertEqual(sorted(src["field_docs"]), sorted(m.FIELDS))


if __name__ == "__main__":
    unittest.main()
