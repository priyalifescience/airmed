"""NTPF (Ireland): national public hospital waiting lists, monthly snapshots, from the NTPF Open Data page.

Six NTPF Open Data reports are kept, each row tagged with its report code:
- OPNational01: outpatient waiting list by hospital (adult / child);
- OPNational02: outpatient waiting list by specialty (adult / child);
- IPDCNational01: inpatient / day case waiting list by hospital (adult / child), GI endoscopy excluded;
- IPDCNational02: inpatient / day case waiting list by specialty (adult / child), GI endoscopy excluded;
- IPDCNational03: inpatient / day case waiting list by hospital, case type and adult / child;
- IPDCNational04: GI endoscopy waiting list by hospital (adult / child).

The reports are different cuts of the same lists, so do not add them together. Counts are numbers of people
waiting, by time band (0-6, 6-12, 12-18, 18+ months). Hospital names are organisations. NTPF applies statistical
disclosure control (specialty/hospital cells with fewer than 20 people are grouped under "Small Volume").

Only the latest WINDOW_MONTHS monthly snapshots are kept (size rule; the NTPF page has data back to 2014).
Where a published file repeats the same report/date/group/hospital/specialty row (seen in a few monthly
outpatient-by-specialty extracts, whose duplicate rows add up to the national total), the rows are summed.
"""

import csv
import io
import json
import re

from ..http import fetch

KEY = "ntpf_waiting_lists"
FIELDS = ["snapshot_date", "list_type", "report", "adult_child", "hospital", "specialty", "case_type",
          "waiting_0_6_months", "waiting_6_12_months", "waiting_12_18_months", "waiting_18_plus_months", "total"]
PAGE = "https://www.ntpf.ie/waiting-list-data/open-data/"
REPORTS = {
    "OPNational01": "Outpatient",
    "OPNational02": "Outpatient",
    "IPDCNational01": "Inpatient/Day Case",
    "IPDCNational02": "Inpatient/Day Case",
    "IPDCNational03": "Inpatient/Day Case",
    "IPDCNational04": "GI Endoscopy",
}
WINDOW_MONTHS = 24
LINK_RE = re.compile(r'href="(https://www\.ntpf\.ie/app/uploads/\d{4}/\d{2}/OpenData_(%s)_(\d{4})(?:-\d+)?\.csv)"'
                     % "|".join(REPORTS))
BANDS = [("0-6 Months", "waiting_0_6_months"), ("6-12 Months", "waiting_6_12_months"),
         ("12-18 Months", "waiting_12_18_months"), ("18 Months +", "waiting_18_plus_months"), ("Total", "total")]


def _links(page_html: str) -> dict:
    """{(report, year): url}; if a file was re-uploaded, the latest upload path wins."""
    found = {}
    for url, report, year in LINK_RE.findall(page_html):
        key = (report, int(year))
        if key not in found or url > found[key]:
            found[key] = url
    return found


def fetch_raw() -> bytes:
    """The open-data page plus the yearly CSVs needed for the window, as JSON {"files": {url: text}}."""
    links = _links(fetch(PAGE, timeout=60).decode("utf-8", "replace"))
    if not links:
        raise RuntimeError("NTPF open-data page: no OpenData CSV links found (page layout changed?)")
    latest = max(y for _, y in links)
    years = range(latest - WINDOW_MONTHS // 12, latest + 1)   # e.g. 2024..2026: always covers 24 months
    missing = [(r, y) for r in REPORTS for y in years if (r, y) not in links]
    if missing:
        raise RuntimeError(f"NTPF open-data page: missing files {missing}")
    files = {}
    for (report, year), url in sorted(links.items()):
        if year in years:
            files[url] = fetch(url, timeout=120).decode("utf-8-sig")
    return json.dumps({"files": files}).encode("utf-8")


def _int(s: str) -> int:
    s = s.strip().replace(",", "")
    if not re.fullmatch(r"-?\d+", s):
        raise ValueError(f"NTPF: not a whole number: {s!r}")
    return int(s)


def _date(s: str) -> str:
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", s.strip())
    if not m:
        raise ValueError(f"NTPF: unexpected date {s!r}")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"


def parse(raw: bytes) -> list:
    files = json.loads(raw)["files"]
    agg = {}
    for url, text in files.items():
        report = re.search(r"OpenData_([A-Za-z]+\d\d)_", url).group(1)
        reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
        cols = reader.fieldnames or []
        for band, _ in BANDS:
            if band not in cols:
                raise RuntimeError(f"NTPF {url}: column {band!r} missing (got {cols})")
        for r in reader:
            if not (r.get("ArchiveDate") or "").strip():
                continue                                   # trailing blank line
            hospital = (r.get("HospitalName") or r.get("Hospital_Name") or "").strip()
            key = (_date(r["ArchiveDate"]), REPORTS[report], report, (r.get("Adult_Child") or "").strip(), hospital,
                   (r.get("Speciality") or "").strip(), (r.get("Case_Type") or "").strip())
            counts = [_int(r[band]) for band, _ in BANDS]
            if key in agg:
                agg[key] = [a + b for a, b in zip(agg[key], counts)]
            else:
                agg[key] = counts
    months = sorted({k[0][:7] for k in agg}, reverse=True)[:WINDOW_MONTHS]
    keep = set(months)
    out = []
    for key in sorted(agg):
        if key[0][:7] not in keep:
            continue
        row = dict(zip(FIELDS[:7], key))
        row.update({f: v for (_, f), v in zip(BANDS, agg[key])})
        out.append(row)
    return out
