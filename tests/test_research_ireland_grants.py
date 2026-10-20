"""Offline test for the Research Ireland grants parser (fixture: real rows of the SFI 2000-2024 and Research Ireland
grant commitment files, as fetch_raw stores them, i.e. with lead applicant and ORCID already removed). The
person-dropping step itself is tested on a CSV whose lead applicant is a placeholder, "Jane Example"."""

import json
import unittest
from pathlib import Path

from airmed.collectors import research_ireland_grants as m
from airmed.privacy import check_fields

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "research_ireland_grants.json"

SOURCE_CSV = (
    "Project ID,Programme Name,Lead Applicant,ORCID ID,Research Body,Funder Name,Funder ROR ID,Project title,"
    "Actual Start Date,Final End Date,Award Amount\n"
    "25/ESS/4045,European Social Survey (ESS),Jane Example,https://orcid.org/0000-0000-0000-0000,"
    "University College Dublin,Research Ireland,https://ror.org/010t7sr36,"
    "SFI ERC Support Programme - Dr. Jane Example (UCD),1/1/2025,12/31/2026,\"€ 645,734.00\"\n")


def registry_entry(key):
    pending = ROOT / "sources" / "pending" / f"{key}.json"
    if pending.exists():
        return json.loads(pending.read_text(encoding="utf-8"))
    return json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))["sources"][key]


class TestResearchIrelandGrants(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.rows = m.parse(self.raw, min_rows={})

    def row(self, gid):
        return next(r for r in self.rows if r["grant_id"] == gid)

    def test_shape(self):
        check_fields(m.FIELDS)
        self.assertEqual(len(self.rows), 7)
        for r in self.rows:
            self.assertEqual(list(r), m.FIELDS)
        self.assertEqual({r["source_file"] for r in self.rows}, {"sfi_2000_2024", "research_ireland"})

    def test_sfi_values(self):
        r = self.row("00/PI.1/B038")
        self.assertEqual((r["research_body"], r["research_body_ror"], r["start_date"], r["end_date"],
                          r["amount_eur"], r["amount_basis"], r["funder_crossref_id"]),
                         ("Trinity College Dublin (TCD)", "https://ror.org/02tyrky19", "2001-10-01", "2007-03-31",
                          5471668.03, "Current Total Commitment", "10.13039/501100001602"))
        self.assertEqual(self.row("12/RC/2275_P2")["sub_programme"], "Phase 2")

    def test_negative_amounts(self):
        self.assertEqual(self.row("13/IA/1977(N)")["amount_eur"], -667861.65)
        self.assertEqual(self.row("16/IA/4528 MI (N)")["amount_eur"], -348960)    # published as (348,960.00)

    def test_research_ireland_values_us_dates_and_euro_sign(self):
        r = self.row("25/ESS/4045")
        self.assertEqual((r["start_date"], r["end_date"], r["amount_eur"], r["amount_basis"], r["funder_ror"]),
                         ("2025-01-01", "2026-12-31", 645734, "Award Amount", "https://ror.org/010t7sr36"))
        self.assertEqual(self.row("25/HERA/4046")["amount_eur"], 137599.9)

    def test_names_in_titles_withheld(self):
        r = self.row("12/ERC/B2499")
        self.assertEqual(r["title_redacted"], "yes")
        self.assertTrue(r["title"].startswith("SFI ERC Support - [name withheld] - "))
        self.assertEqual(self.row("00/PI.1/B038")["title_redacted"], "no")
        self.assertEqual(m.redact_title("Walton Visitor Award for Professor Jane Example"),
                         "Walton Visitor Award for [name withheld]")
        self.assertEqual(m.redact_title("SFI ERC Support - Jane Example (Trinity)", "Jane Example"),
                         "SFI ERC Support - [name withheld] (Trinity)")

    def test_people_never_reach_raw(self):
        text = m._drop_people(SOURCE_CSV)
        self.assertNotIn("Jane Example", text)
        self.assertNotIn("orcid", text.lower())
        raw = json.dumps({"files": {"research_ireland": {"url": "", "licence": "", "csv": text},
                                    "sfi_2000_2024": {"url": "", "licence": "", "csv": ""}}}).encode()
        (r,) = m.parse(raw, min_rows={})
        self.assertEqual((r["title"], r["title_redacted"]), ("SFI ERC Support Programme - [name withheld] (UCD)", "yes"))
        self.assertNotIn("Jane", json.dumps(r))
        self.assertNotIn("orcid", self.raw.decode("utf-8").lower())

    def test_personal_column_refused(self):
        raw = json.dumps({"files": {"research_ireland": {"url": "", "licence": "", "csv": SOURCE_CSV},
                                    "sfi_2000_2024": {"url": "", "licence": "", "csv": ""}}}).encode()
        with self.assertRaises(RuntimeError):
            m.parse(raw, min_rows={})

    def test_too_few_rows_refused(self):
        with self.assertRaises(RuntimeError):
            m.parse(self.raw)

    def test_registry_entry_matches(self):
        src = registry_entry(m.KEY)
        self.assertEqual(src["fields_kept"], m.FIELDS)
        self.assertEqual(src["status"], "approved")
        self.assertEqual(list(src["field_docs"]), m.FIELDS)


if __name__ == "__main__":
    unittest.main()
