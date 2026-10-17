"""Offline test for the pharma company identifier crosswalk, on a trimmed real fixture (6 Wikidata items, 4 GLEIF
records, 6 Irish group entities, the CRO rows they touch)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import pharma_company_ids as pc
from airmed.privacy import check_fields, clean_record

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "pharma_company_ids.json"


def registry_entry():
    pending = ROOT / "sources" / "pending" / "pharma_company_ids.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"]["pharma_company_ids"]


class TestPharmaCompanyIds(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = pc.parse(self.raw)
        self.by_qid = {r["wikidata_qid"]: r for r in self.rows if r["wikidata_qid"]}

    def test_shape_and_order(self):
        self.assertEqual(len(self.rows), 10)
        for r in self.rows:
            self.assertEqual(list(r), pc.FIELDS)
        keys = [(r["record_basis"] != "wikidata", pc._qnum(r["wikidata_qid"]), r["lei"]) for r in self.rows]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(pc.parse(self.raw), self.rows)   # deterministic

    def test_identifier_matches(self):
        perrigo = self.by_qid["Q2916497"]
        self.assertEqual((perrigo["cro_company_number"], perrigo["cro_match_method"]), ("529592", "gleif_registered_as"))
        self.assertEqual(perrigo["gleif_jurisdiction"], "IE")
        self.assertIn("lei_jurisdiction_ie", perrigo["irish_link"])
        stryker_ie = self.by_qid["Q29123215"]
        self.assertEqual((stryker_ie["cro_company_number"], stryker_ie["cro_match_method"]), ("272391", "wikidata_P9679"))
        self.assertEqual(stryker_ie["lei_source"], "gleif_by_cro_number")
        self.assertEqual(stryker_ie["lei"], "5493005YQVR5TQ41KN58")

    def test_exact_name_match_and_lei_by_cro_number(self):
        jazz = self.by_qid["Q16255113"]
        self.assertEqual(jazz["cro_company_number"], "399192")
        self.assertTrue(jazz["cro_match_method"].startswith("exact_name_wikidata_"))
        self.assertEqual((jazz["lei"], jazz["lei_source"]), ("635400GAUMJCLEZRRV50", "gleif_by_cro_number"))

    def test_group_entities_not_duplicated(self):
        leis = [r["lei"] for r in self.rows if r["lei"]]
        self.assertEqual(len(leis), len(set(leis)))
        groups = [r for r in self.rows if r["record_basis"] == "gleif_irish_group_entity"]
        self.assertTrue(groups)
        for g in groups:
            self.assertEqual(g["gleif_jurisdiction"], "IE")
            self.assertTrue(g["via_wikidata_qid"])

    def test_non_irish_lei_candidate_excluded(self):
        self.assertNotIn("Q4914627", self.by_qid)

    def test_ambiguous_name_is_not_matched(self):
        d = json.loads(self.raw)
        hits = d["cro"]["name_search"]["Jazz Pharmaceuticals Public Limited Company"]
        twin = dict(next(h for h in hits if h["company_num"] == 399192), company_num=999999999)
        hits.append(twin)
        jazz = next(r for r in pc.parse(json.dumps(d).encode()) if r["wikidata_qid"] == "Q16255113")
        self.assertEqual((jazz["cro_company_number"], jazz["lei"]), ("", ""))

    def test_sole_proprietor_dropped(self):
        d = json.loads(self.raw)
        for lst in d["gleif"]["children"].values():
            for k in lst:
                k["category"] = "SOLE_PROPRIETOR"
        rows = pc.parse(json.dumps(d).encode())
        self.assertFalse([r for r in rows if r["record_basis"] == "gleif_irish_group_entity"])

    def test_count_mismatch_refuses(self):
        d = json.loads(self.raw)
        d["counts"]["gleif_records"] += 1
        with self.assertRaises(RuntimeError):
            pc.parse(json.dumps(d).encode())

    def test_norm_name(self):
        self.assertEqual(pc.norm_name("ICON plc"), "ICON PUBLIC LIMITED COMPANY")
        self.assertEqual(pc.norm_name("Jazz  Pharmaceuticals, Ltd."), "JAZZ PHARMACEUTICALS LIMITED")
        self.assertEqual(pc.norm_name("Johnson & Johnson (Ireland) DAC"),
                         "JOHNSON AND JOHNSON IRELAND DESIGNATED ACTIVITY COMPANY")
        self.assertNotEqual(pc.norm_name("Medtronic"), pc.norm_name("Medtronic Limited"))

    def test_no_address_or_person_data(self):
        text = self.raw.decode("utf-8").lower()
        for bad in ("addresslines", "postalcode", "eircode", "company_address", "director", "secretary"):
            self.assertNotIn(bad, text)
        check_fields(pc.FIELDS)
        stats = {}
        for r in self.rows:
            clean_record(r, stats)
        self.assertEqual(stats.get("blanked", 0), 0)

    def test_registry_entry(self):
        src = registry_entry()
        self.assertEqual(src["fields_kept"], pc.FIELDS)
        self.assertEqual(sorted(src["field_docs"]), sorted(pc.FIELDS))
        self.assertEqual(src["status"], "approved")
        for k in ("endpoint", "licence", "licence_url", "attribution"):
            self.assertTrue(src[k], k)


if __name__ == "__main__":
    unittest.main()
