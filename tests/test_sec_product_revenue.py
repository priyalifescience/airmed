"""Offline tests for the SEC product revenue collector: XBRL instance and label extraction (test instance modelled on
real 10-Q instances), the whole fetch path with sec.gov replaced by local fixtures, de-duplication across filings,
and the company coverage table."""

import json
import unittest
from pathlib import Path

from airmed import http
from airmed.collectors import sec_product_revenue as m
from airmed.privacy import check_fields

ROOT = Path(__file__).resolve().parent.parent
FIX = Path(__file__).parent / "fixtures"
INSTANCE = (FIX / "sec_product_revenue_instance.xml").read_bytes()
LABELS = (FIX / "sec_product_revenue_lab.xml").read_bytes()


def registry_entry(key):
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


def submissions(name, filings):
    keys = ["accessionNumber", "filingDate", "reportDate", "form", "isXBRL", "primaryDocument"]
    return {"name": name, "filings": {"recent": {k: [f[k] for f in filings] for k in keys}, "files": []}}


OLDER = (INSTANCE.replace(b">1049000000<", b">1000000000<")            # value later revised in the newer report
         .replace(b">Q2<", b">Q4<").replace(b">2026<", b">2025<"))
SITE = {
    m.SUBMISSIONS.format(cik="0000000001"): json.dumps(submissions("EXAMPLE PHARMA INC", [
        {"accessionNumber": "0000000001-26-000002", "filingDate": "2026-08-04", "reportDate": "2026-06-28",
         "form": "10-Q", "isXBRL": 1, "primaryDocument": "xx-20260628.htm"},
        {"accessionNumber": "0000000001-26-000001", "filingDate": "2026-02-20", "reportDate": "2025-12-31",
         "form": "10-K", "isXBRL": 1, "primaryDocument": "xx-20251231.htm"},
        {"accessionNumber": "0000000001-26-000003", "filingDate": "2026-08-05", "reportDate": "2026-08-05",
         "form": "8-K", "isXBRL": 0, "primaryDocument": "x.htm"},
    ])).encode(),
    m.SUBMISSIONS.format(cik="0000000002"): json.dumps(submissions("NO TAGS PLC", [
        {"accessionNumber": f"0000000002-26-00000{i}", "filingDate": f"2026-0{i}-01", "reportDate": "",
         "form": "20-F", "isXBRL": 0, "primaryDocument": "a.htm"} for i in (1, 2, 3)])).encode(),
}
for acc, inst in (("000000000126000002", INSTANCE), ("000000000126000001", OLDER)):
    base = f"https://www.sec.gov/Archives/edgar/data/1/{acc}/"
    SITE[base + "index.json"] = json.dumps({"directory": {"item": [
        {"name": "xx_htm.xml"}, {"name": "xx_lab.xml"}, {"name": "xx.htm"}]}}).encode()
    SITE[base + "xx_htm.xml"] = inst
    SITE[base + "xx_lab.xml"] = LABELS


class TestSecProductRevenue(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def fake_fetch(url, timeout=60, retries=3, data=None, headers=None):
            self.calls.append((url, (headers or {}).get("User-Agent")))
            return SITE[url]
        self._fetch, m.fetch = m.fetch, fake_fetch
        self.raw = m.fetch_raw({"example": "0000000001", "notags": "0000000002"})
        self.rows = m.parse(self.raw)

    def tearDown(self):
        m.fetch = self._fetch

    def test_extract_instance(self):
        got = m.extract_instance(INSTANCE)
        self.assertEqual((got["fy"], got["fp"]), ("2026", "Q2"))
        facts = {(f["member"], f["start"], tuple(f["other_dimensions"])): f for f in got["facts"]}
        self.assertEqual(len(got["facts"]), 6)     # total, cost, nil and instant facts are not product revenue
        ib = facts[("xx:IbranceMember", "2026-03-30", ("us-gaap:StatementBusinessSegmentsAxis=xx:BiopharmaSegmentMember",))]
        self.assertEqual(ib["concept"], "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax")  # prefix normalised
        self.assertEqual((ib["axis"], ib["value"], ib["unit"], ib["decimals"]), ("srt:ProductOrServiceAxis", 1058000000, "iso4217:USD", "-6"))
        # standard axis wins over the company portfolio axis on the same fact
        sky = [f for f in got["facts"] if f["member"] == "xx:SKYRIZIMember"][0]
        self.assertEqual(sky["axis"], "srt:ProductOrServiceAxis")
        self.assertEqual(sky["other_dimensions"], ["xx:KeyProductPortfolioAxis=xx:ImmunologyMember"])
        # a company product axis alone is accepted
        port = [f for f in got["facts"] if f["axis"] == "xx:KeyProductPortfolioAxis"]
        self.assertEqual([p["member"] for p in port], ["xx:ImmunologyMember"])
        self.assertIn("us-gaap:ProductMember", got["members"])

    def test_labels(self):
        lab = m.extract_labels(LABELS, ["xx:IbranceMember", "us-gaap:ProductMember", "xx:SKYRIZIMember"])
        self.assertEqual(lab, {"xx:IbranceMember": "Ibrance [Member]", "us-gaap:ProductMember": "Product [Member]"})

    def test_fetch_path_is_polite(self):
        self.assertTrue(all(ua == m.SEC_UA and "@" in ua for _, ua in self.calls))
        self.assertFalse(any("8-K" in u or "x.htm" in u for u, _ in self.calls))     # 8-K and documents never read
        self.assertEqual(http.PAUSE_SECONDS, 1.0)                                  # pause restored afterwards
        # the company without XBRL is given up after GIVE_UP_AFTER filings
        notags = [c for c in json.loads(self.raw)["companies"] if c["slug"] == "notags"][0]
        self.assertEqual(len(notags["filings"]), m.GIVE_UP_AFTER)

    def test_rows_dedup_and_shape(self):
        check_fields(m.FIELDS)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
        self.assertEqual(len(self.rows), 6)          # the 10-K repeats all six facts; one row each survives
        py = [r for r in self.rows if r["member"] == "xx:IbranceMember" and r["period_start"] == "2025-03-31"][0]
        self.assertEqual(py["value"], 1049000000)    # value from the newer report wins
        self.assertEqual((py["accession"], py["filed"], py["form"], py["filing_fiscal_period"]),
                         ("0000000001-26-000002", "2026-08-04", "10-Q", "Q2"))
        self.assertEqual(py["period_months"], 3)
        self.assertEqual(py["member_label"], "Ibrance [Member]")
        self.assertEqual(py["company"], "EXAMPLE PHARMA INC")
        us = [r for r in self.rows if r["geography"]][0]
        self.assertEqual((us["geography"], us["period_months"], us["concept"]), ("country:US", 6, "us-gaap:Revenues"))
        self.assertEqual(py["filing_url"], "https://www.sec.gov/Archives/edgar/data/1/000000000126000002/")

    def test_coverage(self):
        cov = {c["company_slug"]: c for c in m.coverage(self.raw)}
        self.assertEqual(cov["example"]["status"], "product revenue tagged")
        self.assertEqual(cov["example"]["product_members"], 4)
        self.assertTrue(cov["notags"]["status"].startswith("no product-dimension revenue"))

    def test_helpers(self):
        self.assertEqual(m._months("2026-01-01", "2026-12-31"), 12)
        self.assertEqual(m._months("2026-03-30", "2026-06-28"), 3)
        self.assertEqual(m._months("2025-07-01", "2026-03-31"), 9)
        self.assertEqual(m.geography(["ifrs-full:GeographicalAreasAxis=country:CN", "ifrs-full:SegmentsAxis=x:Y"]), "country:CN")
        self.assertTrue(m._is_product_axis("ifrs-full:ProductsAndServicesAxis"))
        self.assertFalse(m._is_product_axis("srt:LitigationCaseAxis"))
        self.assertEqual(len(m.COMPANIES), 48)

    def test_registry_entry_matches(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(src["status"], "approved")
        self.assertEqual(set(src["field_docs"]), set(m.FIELDS))


if __name__ == "__main__":
    unittest.main()
