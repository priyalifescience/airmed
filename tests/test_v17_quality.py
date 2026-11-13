"""v1.7 quality fixes (13 November 2026): retries, openFDA index tolerance, renamed source labels, SUKL duplicates,
the "Fabio" sponsor leak and the freshness check."""
import datetime as dt
import io
import json
import tempfile
import unittest
import urllib.error
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from airmed import freshness, http
from airmed.collectors import ctgov_ireland, cz_sukl_supply_notices, hc_approvals, hc_notice_of_compliance
from airmed.util import check_bulk_counts


class TestBulkCounts(unittest.TestCase):
    def test_file_must_match_its_own_metadata(self):
        with self.assertRaises(RuntimeError):
            check_bulk_counts("drug/ndc", 999, 1000, 1000)

    def test_small_index_lag_is_a_warning(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            check_bulk_counts("drug/ndc", 79029, 79029, 79072)   # 43 apart, as on 2 Nov 2026
        self.assertIn("WARN", buf.getvalue())

    def test_large_index_gap_refuses(self):
        with self.assertRaises(RuntimeError):
            check_bulk_counts("drugsfda", 25000, 25000, 26000)


class TestSponsor17(unittest.TestCase):
    def test_org_word_inside_a_first_name_does_not_save_a_person(self):
        self.assertEqual(ctgov_ireland.sponsor_or_blank("Prof. Fabio Facchinetti", "OTHER"), "")
        self.assertEqual(ctgov_ireland.sponsor_or_blank("Fabio Rossi", "OTHER", "SPONSOR_INVESTIGATOR"), "")

    def test_titled_organisations_still_kept(self):
        for name in ("Dr. Rajendra Prasad Government Medical College", "Dr. Reddy's Laboratories Limited"):
            self.assertEqual(ctgov_ireland.sponsor_or_blank(name, "OTHER", "SPONSOR_INVESTIGATOR"), name)


class TestHealthCanadaLabels(unittest.TestCase):
    def _main(self, t):
        return {"noc_number": 1, "noc_date": "2026-10-01", "noc_manufacturer_name": "X INC", "noc_on_submission_type": t,
                "noc_is_admin": "N", "noc_product_type": "Prescription Pharmaceutical", "noc_is_suppliment": "N"}

    def test_both_spellings_map(self):
        for t, want in (("New Drug Submission (NDS)", "NDS"), ("New Drug Submission", "NDS"),
                        ("Supplement to a New", "SNDS"), ("Abbreviated New Drug", "ANDS"),
                        ("Supplement to an Abb", "SANDS")):
            self.assertEqual(hc_notice_of_compliance.TYPES[t], want)

    def test_hc_approvals_reads_new_label(self):
        rows = [dict(self._main("New Drug Submission"), noc_number=n) for n in range(1, 302)]
        raw = json.dumps({"noticeofcompliancemain": rows, "drugproduct": [], "medicinalingredient": []}).encode()
        self.assertEqual(len(hc_approvals.parse(raw)), 301)


class TestSuklDuplicates(unittest.TestCase):
    def test_exact_duplicates_dropped_and_counted(self):
        cols = cz_sukl_supply_notices.COLUMNS
        row = ["NE", "0001125", "MORPHIN", "10MG", "B", "N02AA01", "preruseni", "9.5.2018", "9.5.2018", "", "", "", ""]
        other = row[:]
        other[11] = "Výrobní důvody"     # same product, type and dates, different reason: a different notice
        lines = [";".join(cols), ";".join(row), ";".join(row), ";".join(other)]
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("mr_hlaseni.csv", "\n".join(lines).encode("cp1250"))
        out = io.StringIO()
        with redirect_stdout(out):
            recs = cz_sukl_supply_notices.parse(buf.getvalue(), min_rows=1)
        self.assertEqual(len(recs), 2)
        self.assertIn("1 exact duplicate", out.getvalue())


class TestFreshness(unittest.TestCase):
    def test_stale_and_fresh(self):
        now = dt.datetime(2026, 11, 13, tzinfo=dt.timezone.utc)
        with tempfile.TemporaryDirectory() as d:
            for key, created in (("a", "2026-11-09T05:00:00+00:00"), ("b", "2026-10-21T09:49:24+00:00")):
                (Path(d) / key).mkdir()
                (Path(d) / key / "datapackage.json").write_text(json.dumps({"created": created}))
            got = freshness.stale(Path(d), ["a", "b", "c"], now=now)
        self.assertEqual([g[0] for g in got], ["b", "c"])


class TestRetries(unittest.TestCase):
    def test_dropped_connection_is_retried(self):
        import http.client as hc
        calls = []

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, n):
                return b"{}"

        def opener(req, timeout):
            calls.append(1)
            if len(calls) == 1:
                raise hc.RemoteDisconnected("Remote end closed connection without response")
            return Resp()

        with mock.patch.object(http._opener, "open", side_effect=opener), mock.patch.object(http.time, "sleep"):
            self.assertEqual(http.fetch("https://example.org/x", backoff=0), b"{}")
        self.assertEqual(len(calls), 2)

    def test_truncated_json_is_fetched_again(self):
        replies = [b'{"a": "cut', b'{"a": 1}']
        with mock.patch.object(http, "fetch", side_effect=lambda *a, **k: replies.pop(0)), \
                mock.patch.object(http.time, "sleep"):
            self.assertEqual(http.fetch_json_retry("https://example.org/x"), {"a": 1})

    def test_404_not_retried(self):
        err = urllib.error.HTTPError("https://example.org/x", 404, "nf", {}, None)
        with mock.patch.object(http._opener, "open", side_effect=err) as m, mock.patch.object(http.time, "sleep"):
            with self.assertRaises(urllib.error.HTTPError):
                http.fetch("https://example.org/x")
        self.assertEqual(m.call_count, 1)


if __name__ == "__main__":
    unittest.main()
