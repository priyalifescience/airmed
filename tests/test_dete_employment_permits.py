"""Offline test for the DETE employment permits parser (fixture: rows trimmed from the real DETE workbooks of
2011, 2012, 2019, 2022 and 2026, rewritten as small .xlsx files; the one natural-person employer is a placeholder
name, "Jane Example", carrying the counts of a real sole-trader row, so that no real person is named in the repo)."""

import base64
import io
import json
import unittest
import zipfile
from pathlib import Path

from airmed.collectors import dete_employment_permits as m
from airmed.privacy import check_fields

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "dete_employment_permits.json"


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestDeteEmploymentPermits(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw)

    def row(self, **kw):
        return next(r for r in self.rows if all(r[k] == v for k, v in kw.items()))

    def test_shape(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 11)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
        labels = {r["sector"] or r["county"] or r["employer"] for r in self.rows}
        self.assertFalse(labels & {"Total", "Grand Total"})

    def test_wide_employer_workbook_2026(self):
        r = self.row(year=2026, employer="Eli Lilly Kinsale Limited")
        self.assertEqual((r["table"], r["latest_month"], r["issued_total"], r["issued_jan"], r["issued_sep"],
                          r["issued_oct"], r["totals_basis"], r["employers_withheld"]),
                         ("employer", 9, 76, 9, 13, "", "published", 0))
        icon = self.row(year=2026, employer="ICON Clinical Research Limited")
        self.assertEqual((icon["issued_jan"], icon["issued_total"]), (0, 9))     # blank cell in a covered month = 0

    def test_natural_person_withheld(self):
        names = {r["employer"] for r in self.rows}
        self.assertNotIn("Jane Example", names)
        self.assertNotIn("Abbott Ireland", names)                 # strict rule: no legal form, withheld too
        merged = self.row(year=2026, table="employer", employer="")
        self.assertEqual((merged["employers_withheld"], merged["issued_total"]), (2, 36))
        self.assertFalse(m.looks_like_organisation("Jane Example"))
        self.assertFalse(m.looks_like_organisation("John Smith trading as Smith Plumbing"))
        for name in ("Pfizer Ireland Limited", "ICON plc", "Mount Affinity Productions DAC", "Éire Composites Teoranta",
                     "Chromsystems Instruments and Chemicals GmbH", "Beaumont Hospital", "Health Service Executive",
                     "University of Galway", "Zurich Insurance PLC", "Ltd."):
            self.assertTrue(m.looks_like_organisation(name), name)

    def test_long_monthly_2019_month_in_year_column_and_missing_august(self):
        r = self.row(year=2019, employer="Zenith Technologies Limited")
        self.assertEqual((r["latest_month"], r["issued_jan"], r["issued_aug"], r["issued_nov"], r["issued_dec"],
                          r["issued_total"], r["totals_basis"]), (12, 6, "", 11, 4, 54, "summed_from_months"))

    def test_long_sector_without_label_header_2012(self):
        r = self.row(year=2012, sector="Medical & Nursing")
        self.assertEqual((r["issued_jan"], r["issued_feb"], r["issued_mar"], r["issued_total"], r["new"],
                          r["renewal"], r["refused"], r["withdrawn"]), (79, 75, "", 154, 120, 34, 23, 2))

    def test_wide_sector_with_issued_under_months_2022(self):
        r = self.row(year=2022, sector="C - Manufacture of Chemicals & Pharmaceuticals")
        self.assertEqual((r["issued_total"], r["issued_jan"], r["issued_dec"], r["latest_month"]), (682, 30, 52, 12))

    def test_county_tables(self):
        self.assertEqual((self.row(year=2026, county="Dublin")["issued_total"],
                          self.row(year=2026, county="Dublin")["refused"]), (13243, 1366))
        cork = self.row(year=2011, county="Cork")
        self.assertEqual((cork["issued_total"], cork["new"], cork["renewal"], cork["refused"], cork["withdrawn"],
                          cork["latest_month"]), (417, 261, 156, 64, 12, ""))

    def test_link_discovery(self):
        page = ('<a href="/en/publications/publication-files/employment-permits-issued-to-companies-2026.xlsx">a</a>'
                '<a href="/en/publications/publication-files/employment-permits-by-nationality-2026.xlsx">b</a>'
                '<a href="/en/publications/publication-files/permits-issued-by-sector-2009.xls">c</a>')
        found, skipped = m.links("", {"p": page})
        self.assertEqual(found, {"https://enterprise.gov.ie/en/publications/publication-files/"
                                 "employment-permits-issued-to-companies-2026.xlsx": (2026, "employer")})
        self.assertEqual(skipped, ["https://enterprise.gov.ie/en/publications/publication-files/"
                                   "permits-issued-by-sector-2009.xls"])

    def test_bad_number_refused(self):
        data = json.loads(self.raw)
        url = next(u for u in data["files"] if "county-2026" in u)
        src = zipfile.ZipFile(io.BytesIO(base64.b64decode(data["files"][url])))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for n in src.namelist():
                z.writestr(n, src.read(n).replace(b"<v>3047</v>", b"<v>n/a</v>"))
        xlsx = buf.getvalue()
        data["files"] = {url: base64.b64encode(xlsx).decode()}
        with self.assertRaises(ValueError):
            m.parse(json.dumps(data).encode())

    def test_registry_entry_matches(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["fields_kept"], m.FIELDS)
        # Held until DETE confirms the licence: never collected or released, but the parser stays tested.
        self.assertEqual(src["status"], "pending")
        self.assertTrue(src["reason"].startswith("Held 2026-10-20"))
        self.assertEqual(list(src["field_docs"]), m.FIELDS)


if __name__ == "__main__":
    unittest.main()
