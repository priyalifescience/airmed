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
# Phone numbers in the formats people actually write them. Deliberately NOT "any long run of digits": product
# codes such as NDC 0641-6024-10, licence numbers and EMA ids are data, and must survive (see tests).
PHONE_RE = re.compile(
    r"(?<![\w/.-])(?:"                                            # not inside an id: 10.5155/x.8.3.195-202.1576
    r"\+\d{1,3}[\s.-]?\(?\d{1,4}\)?(?:[\s.-]?\d{2,4}){2,4}"       # +353 1 234 5678, +1-866-850-2876
    r"|\(\d{3}\)\s?\d{3}[\s.-]\d{4}"                            # (866) 850-2876
    r"|\d{3}[\s.-]\d{3}[\s.-]\d{4}"                               # 866-850-2876, 866.850.2876
    r"|0[1-9]\d{0,3}\s\d{3,4}\s?\d{3,4}"                           # 01 234 5678, 087 123 4567 (not "10 000 000 000" in doses)
    r")(?![\w/-])")
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")


class ForbiddenField(Exception):
    pass


def check_fields(fields) -> None:
    for name in fields:
        low = name.lower()
        for word in FORBIDDEN_FIELD_WORDS:
            if word in low:
                raise ForbiddenField(f"field {name!r} looks like personal or contact data ({word!r})")


def _scrub(value, stats: dict, field: str = ""):
    if isinstance(value, str):
        # URLs and DOIs are identifiers, not contact details (a DOI suffix can look like 195-202.1576)
        is_url = value.startswith(("http://", "https://")) or DOI_RE.match(value) is not None
        if EMAIL_RE.search(value) or (not is_url and PHONE_RE.search(value)):
            stats["blanked"] = stats.get("blanked", 0) + 1
            by = stats.setdefault("by_field", {})
            by[field] = by.get(field, 0) + 1
            return ""
        return value
    if isinstance(value, list):
        return [_scrub(v, stats, field) for v in value]
    return value


def clean_record(record: dict, stats: dict) -> dict:
    check_fields(record.keys())
    return {k: _scrub(v, stats, k) for k, v in record.items()}
