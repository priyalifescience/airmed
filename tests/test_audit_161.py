"""Release 1.6.1 fixes from the 9 November 2026 audit: person-named trial sponsors, spam titles in research indexes,
and licence notes given as a single string."""
import unittest

from airmed.collectors import ctgov_ireland
from airmed.output import licence_metadata
from airmed.privacy import PHONE_RE, SPAM_TITLE_RE

rule = ctgov_ireland.sponsor_or_blank


class TestSponsorRule161(unittest.TestCase):
    def test_sponsor_investigators_blanked_whatever_the_class(self):
        # real cases found in v1.6: ClinicalTrials.gov classed these OTHER_GOV or INDUSTRY
        for name, cls in (("Katarina Hedin", "OTHER_GOV"), ("Conor Martin", "OTHER_GOV"), ("Yufang Shi", "OTHER_GOV"),
                          ("Prof. Dr. Thomas Forst", "INDUSTRY"), ("Johnny Ludvigsson", "OTHER_GOV")):
            self.assertEqual(rule(name, cls, "SPONSOR_INVESTIGATOR"), "", name)

    def test_titles_and_degrees_blanked(self):
        for name in ("Prof. Arie Levine", "Dr Vikki Hughes", "Dr. Yaacov Lawrence", "Maja Kovacevic, MD",
                     "Aviel Roy-Shapira, M.D.", "Qinghua Xia,Prof", "Yongjian Wu, MD, PhD", "Mónica Olivares Martín; PhD",
                     "LiNanlin,Ph.D, Chief Physician,Clinical Professor"):
            self.assertEqual(rule(name, "INDUSTRY"), "", name)

    def test_organisations_kept(self):
        for name, cls, rp in (("Boehringer Ingelheim", "INDUSTRY", "SPONSOR"),
                              ("Dr. Reddy's Laboratories Limited", "INDUSTRY", ""),
                              ("Dr. Falk Pharma GmbH", "INDUSTRY", ""),
                              ("M.D. Anderson Cancer Center", "OTHER", ""),
                              ("Dr. Rajendra Prasad Government Medical College", "OTHER", "SPONSOR_INVESTIGATOR"),
                              ("Dr. Horst Schmidt Klinik GmbH", "OTHER", ""),
                              ("University College Dublin", "OTHER", "SPONSOR_INVESTIGATOR"),
                              ("Pandit Bhagwat Dayal Sharma, PGIMS, Rohtak", "OTHER", "")):
            self.assertEqual(rule(name, cls, rp), name, name)

    def test_old_two_argument_call_still_works(self):
        # fda_ndc_directory and medicaid_drug_spending call the rule with two arguments
        self.assertEqual(rule("Pfizer Laboratories Div Pfizer Inc", ""), "Pfizer Laboratories Div Pfizer Inc")
        self.assertEqual(rule("Dr John Smith", ""), "")


class TestSpamTitles161(unittest.TestCase):
    def test_spam_found_in_v16_is_caught(self):
        for t in ("+971-556-394139Abortion Pills in Manama-Dubai & Muharraq-Abu Dhabi",
                  "Abortion pills in kuwait ✚971529704578 ⭕ cyto", "Order now on WhatsApp"):
            self.assertTrue(SPAM_TITLE_RE.search(t), t)

    def test_research_titles_survive(self):
        for t in ("Access to abortion pills via telemedicine in Ireland: a cohort study",
                  "Misoprostol for the treatment of postpartum haemorrhage",
                  "A 12-month randomised trial of 1,000 patients", "Variant rs1234567 and warfarin dose",
                  "COVID-19 vaccine effectiveness, 2021-2023"):
            self.assertFalse(SPAM_TITLE_RE.search(t), t)
            self.assertFalse(PHONE_RE.search(t), t)


class TestLicenceNotesString161(unittest.TestCase):
    def test_single_string_note_is_one_note(self):
        src = {"publisher": "X", "licence": "CC BY 4.0", "licence_url": "https://creativecommons.org/licenses/by/4.0/",
               "attribution": "Source: X, retrieved {retrieved_date}.", "licence_notes": "Check the source for updates."}
        lic = licence_metadata(src, "2026-11-09T00:00:00+00:00")
        self.assertEqual(lic["licence_notes"], ["Check the source for updates."])


if __name__ == "__main__":
    unittest.main()
