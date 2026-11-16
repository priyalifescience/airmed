"""v1.7: the optional OpenAlex API key is added to request URLs only when set, and is masked in messages."""
import os
import unittest
from unittest import mock

from airmed import http
from airmed.collectors import openalex_europe_pharma as eu
from airmed.collectors import openalex_ireland_pharma as ie

FAKE = "testkey123"


class OpenAlexKeyTest(unittest.TestCase):
    def test_no_key_no_param(self):
        with mock.patch.dict(os.environ, {"OPENALEX_API_KEY": ""}), \
             mock.patch.object(ie, "KEY_FILE", "~/.no_such_openalex_key_file"):
            self.assertNotIn("api_key", ie._url("institutions.country_code:IE", 1))
            self.assertNotIn("api_key", eu._url("institutions.country_code:IE", 1))

    def test_key_from_env(self):
        with mock.patch.dict(os.environ, {"OPENALEX_API_KEY": FAKE}):
            self.assertIn("api_key=" + FAKE, ie._url("institutions.country_code:IE", 1))
            self.assertIn("api_key=" + FAKE, eu._url("institutions.country_code:IE", 1))
            self.assertIn("mailto=", ie._url("institutions.country_code:IE", 1))

    def test_redact(self):
        u = f"https://api.openalex.org/works?filter=x&api_key={FAKE}&page=2"
        r = http.redact(u)
        self.assertNotIn(FAKE, r)
        self.assertIn("api_key=***", r)
        self.assertIn("page=2", r)
        self.assertEqual(http.redact("https://example.org/a?b=1"), "https://example.org/a?b=1")


if __name__ == "__main__":
    unittest.main()
