"""Offline tests for the SEC 8-K deals collector (fixture trimmed from the real Pfizer submissions API reply, plus
three synthetic rows with accession 9999999999-* for Item 2.01, an 8-K/A and a pre-2018 filing)."""

import json
import unittest
from pathlib import Path

from airmed.collectors import sec_8k_deals as m
from airmed.privacy import check_fields

ROOT = Path(__file__).resolve().parent.parent
FIX = Path(__file__).parent / "fixtures"
SITE = {
    m.SUBMISSIONS.format(cik="0000078003"): (FIX / "sec_8k_deals_submissions.json").read_bytes(),
    m.SUBMISSIONS.format(cik="0000353278"): (FIX / "sec_8k_deals_submissions_20f.json").read_bytes(),
}


class TestSec8kDeals(unittest.TestCase):
    def setUp(self):
        self.urls = []

        def fake_fetch(url, timeout=60, retries=3, data=None, headers=None):
            self.urls.append(url)
            assert "@" in (headers or {}).get("User-Agent", "")
            return SITE[url]
        self._fetch, m.fetch = m.fetch, fake_fetch
        self.raw = m.fetch_raw({"pfizer": "0000078003", "novo": "0000353278"})
        self.rows = m.parse(self.raw)

    def tearDown(self):
        m.fetch = self._fetch

    def test_selection(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 3)     # 1.01, 2.01 and 8-K/A 1.01; not 2.02, 7.01, 10-Q or the 2017 filing
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
        self.assertEqual([r["filing_date"] for r in self.rows], ["2024-01-05", "2023-04-01", "2023-03-13"])
        real = [r for r in self.rows if not r["accession"].startswith("9999")][0]
        self.assertEqual(real["items"], ["1.01", "7.01", "8.01", "9.01"])
        self.assertEqual((real["item_1_01"], real["item_2_01"], real["company"]), ("yes", "no", "PFIZER INC"))
        self.assertTrue(real["document_url"].startswith("https://www.sec.gov/Archives/edgar/data/78003/"))
        acq = self.rows[0]
        self.assertEqual((acq["item_1_01"], acq["item_2_01"], acq["form"]), ("no", "yes", "8-K"))
        self.assertEqual(self.rows[1]["form"], "8-K/A")
        self.assertEqual(len(self.urls), 2)     # only the submissions API; no documents are fetched

    def test_coverage(self):
        cov = {c["company_slug"]: c for c in m.coverage(self.raw)}
        self.assertEqual(cov["pfizer"]["rows_item_1_01_or_2_01"], 3)
        self.assertEqual(cov["novo"]["periodic_forms"], ["20-F"])
        self.assertIn("6-K", cov["novo"]["status"])

    def test_registry_entry_matches(self):
        src = json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][m.KEY]
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(src["status"], "approved")
        self.assertEqual(set(src["field_docs"]), set(m.FIELDS))


if __name__ == "__main__":
    unittest.main()
