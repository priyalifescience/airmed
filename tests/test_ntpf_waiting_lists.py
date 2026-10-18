"""Offline test for the NTPF waiting list parser (fixture: rows trimmed from the real 2025 and 2026 NTPF Open
Data CSV files; hospital names are organisations)."""

import json
import unittest
from pathlib import Path
from unittest import mock

from airmed.collectors import ntpf_waiting_lists as m
from airmed.privacy import check_fields

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "ntpf_waiting_lists.json"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestNtpfWaitingLists(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw)

    def test_shape(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 7)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
        keys = [tuple(r[f] for f in m.FIELDS[:7]) for r in self.rows]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(len(keys), len(set(keys)))

    def test_values_and_thousands_separators(self):
        r = next(x for x in self.rows if x["hospital"] == "Beaumont Hospital" and x["case_type"] == "Day Case")
        self.assertEqual((r["snapshot_date"], r["list_type"], r["report"], r["adult_child"]),
                         ("2025-12-18", "Inpatient/Day Case", "IPDCNational03", "Adult"))
        self.assertEqual((r["waiting_0_6_months"], r["waiting_18_plus_months"], r["total"]), (4569, 485, 7752))

    def test_repeated_rows_summed(self):
        # the January 2026 outpatient-by-specialty file lists Breast Surgery twice (994 + 4,511 people)
        r = next(x for x in self.rows if x["snapshot_date"] == "2026-01-29" and x["specialty"] == "Breast Surgery")
        self.assertEqual((r["list_type"], r["total"], r["waiting_0_6_months"]), ("Outpatient", 5505, 5381))

    def test_window(self):
        with mock.patch.object(m, "WINDOW_MONTHS", 2):
            rows = m.parse(self.raw)
        self.assertEqual(sorted({r["snapshot_date"] for r in rows}), ["2026-01-29", "2026-02-26"])

    def test_link_discovery(self):
        page = ('<a href="https://www.ntpf.ie/app/uploads/2025/01/OpenData_OPNational01_2024-1.csv">x</a>'
                '<a href="https://www.ntpf.ie/app/uploads/2026/10/OpenData_IPDCNational04_2026.csv">y</a>'
                '<a href="https://www.ntpf.ie/app/uploads/2024/10/OP-Waiting-List-by-Group-Hospital-2020.csv">z</a>')
        self.assertEqual(m._links(page), {
            ("OPNational01", 2024): "https://www.ntpf.ie/app/uploads/2025/01/OpenData_OPNational01_2024-1.csv",
            ("IPDCNational04", 2026): "https://www.ntpf.ie/app/uploads/2026/10/OpenData_IPDCNational04_2026.csv"})

    def test_bad_number_refused(self):
        data = json.loads(self.raw)
        url = next(iter(data["files"]))
        first_row = data["files"][url].splitlines()[1]
        data["files"][url] = data["files"][url].replace(first_row, first_row.rsplit(",", 1)[0] + ",n/a", 1)
        with self.assertRaises(ValueError):
            m.parse(json.dumps(data).encode())

    def test_registry_entry_matches(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(src["status"], "approved")
        self.assertEqual(list(src["field_docs"]), m.FIELDS)


if __name__ == "__main__":
    unittest.main()
