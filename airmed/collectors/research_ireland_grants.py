"""Research Ireland (Taighde Éireann): research grant commitments, from the funder's open data on data.gov.ie.

Two files are combined, each row tagged in `source_file`:
- "sfi_2000_2024": the Science Foundation Ireland grant commitments file, awards 2000 to 31 July 2024 (final;
  SFI and the Irish Research Council merged into Research Ireland on 1 August 2024);
- "research_ireland": the Research Ireland grant commitments file (awards from August 2024; the current file runs
  to January 2026 and is replaced about once a year).
Both are found through the data.gov.ie CKAN API (package_show), so a new yearly file is picked up automatically.

Kept as published: grant id, programme (and SFI sub-programme / supplement), research body (an organisation) and
its ROR id, funder and funder id, project title, start and end dates, and the amount in euro. The two files
measure money differently: SFI gives the "Current Total Commitment", Research Ireland the "Award Amount"
(`amount_basis` says which). Research Ireland dates are published as month/day/year and are converted to ISO.

Persons: the files also name each grant's lead applicant and their ORCID iD. Airmid never publishes personal names
or personal identifiers, so both columns are dropped when the file is read (in fetch_raw, so they never reach the
raw file either). Some titles also name a person ("SFI ERC Support - <name> (Trinity)", "Walton Visitor Award for
Professor <name>"): the lead applicant's name, and any honorific + name, are replaced in the title by
"[name withheld]" (see redact_title) and `title_redacted` is "yes". Every other title is exactly as published.
"""

import csv
import io
import json
import re
import urllib.parse

from ..http import fetch
from ..util import us_date

KEY = "research_ireland_grants"
FIELDS = ["source_file", "grant_id", "programme", "sub_programme", "supplement", "research_body",
          "research_body_ror", "funder", "funder_ror", "funder_crossref_id", "title", "title_redacted",
          "start_date", "end_date", "amount_eur", "amount_basis"]
CKAN = "https://data.gov.ie/api/3/action/package_show?id="
PACKAGES = {"sfi_2000_2024": "science-foundation-ireland-grants-commitments",
            "research_ireland": "research-ireland-grant-commitments"}
NEVER = ("Lead Applicant", "ORCID", "ORCID ID")      # personal: never copied out of fetch_raw's text
MIN_ROWS = {"sfi_2000_2024": 7000, "research_ireland": 1000}


def _decode(b: bytes) -> str:
    """The files are not UTF-8 (Windows-1252: the euro sign is byte 0x80); accept either."""
    try:
        return b.decode("utf-8-sig")
    except UnicodeDecodeError:
        return b.decode("cp1252")


HONORIFIC = r"(?:Dr|Prof|Professor|Mr|Mrs|Ms|Mx)\b\.?"
NAME_WORD = r"[A-ZÀ-ÞĀ-Ž][\w'’-]*"
HONORIFIC_NAME_RE = re.compile(rf"\b{HONORIFIC}\s+(?:{NAME_WORD}\s+)?{NAME_WORD}")
WITHHELD = "[name withheld]"
TITLE_COLS = ("Proposal Title", "Project title")
REDACTED_COL = "Airmid Title Redacted"


def redact_title(title: str, lead: str = "") -> str:
    """Remove personal names from a grant title. Some titles name the researcher ("SFI ERC Support - Jane Doe
    (Trinity)", "Walton Visitor Award for Professor X"): the lead applicant's surname, with an honorific and up to
    two capitalised words before it, is replaced by "[name withheld]"; so is any honorific followed by one or two
    capitalised words (a visitor or other named person)."""
    t = title or ""
    words = re.findall(r"[\w'’-]+", lead or "")
    if words and len(words[-1]) >= 3:
        t = re.sub(rf"(?:\b{HONORIFIC}\s+)?(?:\b{NAME_WORD}\s+){{0,2}}\b{re.escape(words[-1])}\b", WITHHELD, t)
    return HONORIFIC_NAME_RE.sub(WITHHELD, t)


def _drop_people(text: str) -> str:
    """The CSV with the lead applicant and ORCID columns removed (so they never reach the raw file either), and
    the lead applicant's name taken out of the title (see redact_title)."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return ""
    head = [h.strip() for h in rows[0]]
    keep = [i for i, h in enumerate(head) if h not in NEVER]
    lead = head.index("Lead Applicant") if "Lead Applicant" in head else None
    title = next((head.index(c) for c in TITLE_COLS if c in head), None)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow([rows[0][i] for i in keep] + [REDACTED_COL])
    for r in rows[1:]:
        r = r + [""] * (len(head) - len(r))
        flag = ""
        if title is not None:
            new = redact_title(r[title], r[lead] if lead is not None else "")
            flag = "yes" if new != r[title] else "no"
            r[title] = new
        w.writerow([r[i] for i in keep] + [flag])
    return buf.getvalue()


def fetch_raw() -> bytes:
    files = {}
    for tag, pkg in PACKAGES.items():
        meta = json.loads(fetch(CKAN + urllib.parse.quote(pkg), timeout=60))["result"]
        csvs = [r["url"] for r in meta["resources"] if (r.get("format") or "").strip(". ").lower() == "csv"]
        if len(csvs) != 1:
            raise RuntimeError(f"data.gov.ie {pkg}: expected one CSV resource, found {csvs}")
        files[tag] = {"url": csvs[0], "licence": meta.get("license_id", ""),
                      "csv": _drop_people(_decode(fetch(csvs[0], timeout=120)))}
    return json.dumps({"files": files}, ensure_ascii=False).encode("utf-8")


def _amount(s: str):
    """'€ 645,734.00', '5471668.03' or '(348,960.00)' (negative) -> number; '' when blank."""
    v = re.sub(r"[€\s,]", "", s or "")
    if not v:
        return ""
    if re.fullmatch(r"\(.*\)", v):                     # accounting style: (348,960.00) is a negative amount
        v = "-" + v[1:-1]
    if not re.fullmatch(r"-?\d+(\.\d+)?", v):
        raise ValueError(f"Research Ireland: not an amount: {s!r}")
    f = float(v)
    return int(f) if f.is_integer() else f


def _get(r: dict, *names) -> str:
    for n in names:
        for k, v in r.items():
            if (k or "").strip().lower() == n.lower():
                return (v or "").strip()
    return ""


def parse(raw: bytes, min_rows: dict = None) -> list:
    min_rows = MIN_ROWS if min_rows is None else min_rows
    files = json.loads(raw)["files"]
    out = []
    for tag in PACKAGES:
        f = files[tag]
        reader = csv.DictReader(io.StringIO(f["csv"]))
        cols = [c.strip() for c in reader.fieldnames or []]
        for c in cols:
            if c in NEVER:
                raise RuntimeError(f"{tag}: personal column {c!r} reached parse")
        n = 0
        for r in reader:
            gid = _get(r, "Proposal ID", "Project ID")
            if not gid:
                continue
            n += 1
            if tag == "sfi_2000_2024":
                start, end = _get(r, "Start Date"), _get(r, "End Date")
                amount, basis = _get(r, "Current Total Commitment"), "Current Total Commitment"
            else:
                start, end = us_date(_get(r, "Actual Start Date")), us_date(_get(r, "Final End Date"))
                amount, basis = _get(r, "Award Amount"), "Award Amount"
            for d in (start, end):
                if d and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
                    raise ValueError(f"{tag} {gid}: unexpected date {d!r}")
            funder_id = _get(r, "Crossref Funder Registry ID")
            published = re.sub(r"\s+", " ", _get(r, *TITLE_COLS))
            title = redact_title(published)                    # backstop: honorific + name (raw is pre-redacted)
            out.append({
                "source_file": tag,
                "grant_id": gid,
                "programme": _get(r, "Programme Name"),
                "sub_programme": _get(r, "Sub-Programme"),
                "supplement": _get(r, "Supplement"),
                "research_body": _get(r, "Research Body"),
                "research_body_ror": _get(r, "Research Body ROR ID"),
                "funder": _get(r, "Funder Name"),
                "funder_ror": _get(r, "Funder ROR ID"),
                "funder_crossref_id": funder_id,
                "title": title,
                "title_redacted": "yes" if title != published or _get(r, REDACTED_COL) == "yes" else "no",
                "start_date": start,
                "end_date": end,
                "amount_eur": _amount(amount),
                "amount_basis": basis,
            })
        if n < min_rows.get(tag, 0):
            raise RuntimeError(f"{tag}: only {n} grants (expected at least {min_rows[tag]}); broken download?")
    out.sort(key=lambda r: (r["source_file"] != "sfi_2000_2024", r["start_date"], r["grant_id"]))
    return out
