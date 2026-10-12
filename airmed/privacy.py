"""Privacy guard. Every record passes through `clean_record` before it is written.

1. Fields whose names suggest people or contacts are refused outright (a collector must never select them).
2. Values that contain an email address or a phone number are blanked, and the run counts them,
   so a source that starts publishing contact details is noticed rather than copied.
"""

import re

FORBIDDEN_FIELD_WORDS = (
    "contact", "email", "e_mail", "phone", "telephone", "fax", "investigator", "official",
    "officer", "person", "firstname", "lastname", "first_name", "last_name", "surname", "qppv", "address",
)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# International or Irish-looking phone numbers: + or 0 followed by 8+ digits, spaces/dashes/brackets allowed
PHONE_RE = re.compile(r"(?<![\w/])(?:\+|00|0)\d[\d\s().-]{7,}\d(?![\w/])")


class ForbiddenField(Exception):
    pass


def check_fields(fields) -> None:
    for name in fields:
        low = name.lower()
        for word in FORBIDDEN_FIELD_WORDS:
            if word in low:
                raise ForbiddenField(f"field {name!r} looks like personal or contact data ({word!r})")


def _scrub(value, stats: dict):
    if isinstance(value, str):
        if EMAIL_RE.search(value) or PHONE_RE.search(value):
            stats["blanked"] = stats.get("blanked", 0) + 1
            return ""
        return value
    if isinstance(value, list):
        return [_scrub(v, stats) for v in value]
    return value


def clean_record(record: dict, stats: dict) -> dict:
    check_fields(record.keys())
    return {k: _scrub(v, stats) for k, v in record.items()}
