"""Small helpers shared by collectors."""

import re


def iso_date(value: str) -> str:
    """Normalise common source date formats to YYYY-MM-DD; unknown formats are returned unchanged."""
    v = (value or "").strip()
    if not v:
        return ""
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", v)                      # 20210322
    if m:
        return f"{m[1]}-{m[2]}-{m[3]}"
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", v)                 # dd/mm/yyyy (EU) – caller decides
    if m:
        return f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}"
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(T.*)?", v)                   # ISO date or datetime
    if m:
        return m[1]
    return v


def us_date(value: str) -> str:
    """mm/dd/yyyy (US) to YYYY-MM-DD."""
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", (value or "").strip())
    return f"{m[3]}-{int(m[1]):02d}-{int(m[2]):02d}" if m else (value or "").strip()


def yes(value) -> str:
    """Normalise yes/no style flags to 'yes' / 'no' / ''."""
    v = str(value or "").strip().lower()
    if v in ("yes", "y", "true", "1"):
        return "yes"
    if v in ("no", "n", "false", "0"):
        return "no"
    return ""


def split_list(value: str, sep: str = ";") -> list:
    return [p.strip() for p in (value or "").split(sep) if p.strip()]
