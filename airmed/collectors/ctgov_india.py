"""ClinicalTrials.gov API v2: every study with at least one site in India (all statuses, full history).

India's own registry (CTRI, ICMR) is not used: it publishes no terms for bulk re-use, so it would need
written permission first. These are the India-sited studies that sponsors also registered on ClinicalTrials.gov. See _ctgov_country.
"""

from . import _ctgov_country as base

KEY = "ctgov_india"
COUNTRIES = ("India",)
FIELDS = base.FIELDS


def fetch_raw() -> bytes:
    return base.fetch_raw(COUNTRIES)


def parse(raw: bytes) -> list:
    return base.parse(raw, COUNTRIES)
