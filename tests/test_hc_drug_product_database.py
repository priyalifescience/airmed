"""Offline test for the Health Canada DPD parser (fixture: the real October 2026 extract tables trimmed to 16 products
across the four zips; company address columns blanked)."""

import io
import json
import unittest
import zipfile
from pathlib import Path

from airmed.collectors import hc_drug_product_database as m
from airmed.privacy import check_fields

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "hc_drug_product_database.zip"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


def rebundle(raw: bytes, edit) -> bytes:
    src = zipfile.ZipFile(io.BytesIO(raw))
    files = {n: src.read(n).decode("utf-8") for n in src.namelist()}
    edit(files)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for n, t in files.items():
            z.writestr(n, t)
    return out.getvalue()


class TestHcDrugProductDatabase(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw, min_records=1)
        self.by = {r["drug_code"]: r for r in self.rows}

    def test_registry_entry(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["status"], "approved")
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(set(src["field_docs"]), set(m.FIELDS))
        check_fields(m.FIELDS)

    def test_shape(self):
        self.assertEqual(len(self.rows), 12)              # 16 products, 4 veterinary/disinfectant ones dropped
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
            self.assertIn(r["class"], ("Human", "Radiopharmaceutical"))
        keys = [(r["din"], r["drug_code"]) for r in self.rows]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual({r["status"] for r in self.rows},
                         {"MARKETED", "APPROVED", "DORMANT", "CANCELLED POST MARKET", "CANCELLED PRE MARKET"})

    def test_values(self):
        a = self.by[15]
        self.assertEqual((a["din"], a["brand_name"], a["company"], a["atc_codes"]), ("00015229", "AVENTYL", "AA PHARMA INC", ["N06AA10"]))
        self.assertEqual(a["ingredients"], ["NORTRIPTYLINE (NORTRIPTYLINE HYDROCHLORIDE) 10 MG"])
        self.assertEqual((a["status"], a["status_date"], a["first_marketed_date"]), ("MARKETED", "2022-01-10", "1965-12-31"))
        o = self.by[81048]
        self.assertEqual((o["biosimilar"], o["ingredients"], o["schedules"]), ("yes", ["SOMATROPIN 5 MG / 1.5 ML"], ["PRESCRIPTION", "SCHEDULE D"]))
        self.assertEqual(self.by[2]["status"], "CANCELLED POST MARKET")
        self.assertEqual(self.by[81047]["first_marketed_date"], "")       # cancelled before it was ever marketed
        self.assertEqual(self.by[81314]["class"], "Radiopharmaceutical")
        self.assertEqual(self.by[115]["routes"], ["INTRAMUSCULAR", "INTRAVENOUS", "SUBCUTANEOUS"])
        # the source repeats this ATC line; it is kept once, paired with its name
        t = self.by[100651]
        self.assertEqual((t["atc_codes"], t["atc_names"]), (["N07BC51"], ["BUPRENORPHINE, COMBINATIONS"]))
        self.assertEqual(t["number_of_ingredients"], 2)

    def test_no_address_or_vet(self):
        text = json.dumps(self.rows)
        self.assertNotIn("Veterinary", text)
        self.assertNotIn(85, self.by)                                    # veterinary product in the marketed zip

    def test_bad_width_raises(self):
        bad = rebundle(self.raw, lambda f: f.__setitem__("allfiles.zip/route.txt", f["allfiles.zip/route.txt"] + '"15","56","ORAL"\n'))
        with self.assertRaises(RuntimeError):
            m.parse(bad, min_records=1)

    def test_two_current_statuses_raise(self):
        bad = rebundle(self.raw, lambda f: f.__setitem__(
            "allfiles.zip/status.txt", f["allfiles.zip/status.txt"] + '"15","Y","DORMANT","01-JAN-2026","DORMANT","",""\n'))
        with self.assertRaises(RuntimeError):
            m.parse(bad, min_records=1)

    def test_partial_dataset_refused(self):
        with self.assertRaises(RuntimeError):
            m.parse(self.raw)


if __name__ == "__main__":
    unittest.main()
