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


INDEX_GAP_TOLERANCE = 0.005   # 0.5%


def check_bulk_counts(label: str, in_file: int, meta_total: int, index_total: int,
                      tolerance: float = INDEX_GAP_TOLERANCE) -> None:
    """openFDA bulk files (v1.7): the file must hold exactly the number of records its own metadata states (else it
    is truncated: refuse). The download index (download.json) is refreshed separately and often lags the file by a
    few records (4 and 43 on 2 Nov 2026), so a gap of under 0.5% to the index is only a warning; a larger gap still
    refuses."""
    if in_file != meta_total:
        raise RuntimeError(f"{label} bulk file holds {in_file} records; its own metadata says {meta_total}")
    if index_total != meta_total:
        gap = abs(index_total - meta_total) / max(meta_total, 1)
        if gap >= tolerance:
            raise RuntimeError(f"{label} bulk file holds {in_file} records; the download index says {index_total} "
                               f"({gap:.2%} apart, over the {tolerance:.1%} tolerance)")
        print(f"WARN  {label}: download index says {index_total}, the file and its metadata {meta_total} "
              f"({gap:.3%} apart, within {tolerance:.1%}): accepted")
