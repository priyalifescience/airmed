"""ClinicalTrials.gov API v2: every study with at least one site in mainland China (all statuses, full history).

ClinicalTrials.gov names Hong Kong and Taiwan as separate countries; they are not selected here, but a selected
study that also has sites there lists them in `countries`. China's own registries (ChiCTR, and the CDE drug trial
platform) are not used: both reserve all rights. See _ctgov_country.
"""

from . import _ctgov_country as base

KEY = "ctgov_china"
COUNTRIES = ("China",)
FIELDS = base.FIELDS


def fetch_raw() -> bytes:
    return base.fetch_raw(COUNTRIES)


def parse(raw: bytes) -> list:
    return base.parse(raw, COUNTRIES)
