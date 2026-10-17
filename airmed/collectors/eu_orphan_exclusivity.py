"""EU orphan market exclusivity, from the European Commission's Union Register open dataset (ods_products.json).

The Union Register publishes one JSON dataset of every medicinal product and orphan designation it holds
(CC BY 4.0). Each authorised human medicine lists the orphan designations linked to it, with the date the orphan
market exclusivity started, any paediatric extension, and the date it ended early, if it did. One row per
(medicine, orphan designation) link.

`exclusivity_expiry` is the Register's end date when one is recorded; otherwise it is worked out exactly as the
Register's own product page does ("will expire on"): start + 10 years, + the paediatric extension if granted,
but only for medicines whose status is Active (a refused, suspended or withdrawn medicine gets no projected date).
`expiry_basis` says which. The Register's rule does not model the rare reduction to 6 years (Article 8(2) of
Regulation (EC) No 141/2000), so a computed date is the Register's display value, not a legal determination.
"""

import calendar
import datetime as dt
import json
import re

from ..http import fetch
from .ctgov_ireland import ORG_WORDS

KEY = "eu_orphan_exclusivity"
FIELDS = ["eu_product_number", "product_name", "active_substance", "product_status", "authorisation_date",
          "marketing_authorisation_holder", "orphan_designation_number", "orphan_indication",
          "orphan_designation_status", "exclusivity_start", "paediatric_extension_months",
          "paediatric_extension_date", "exclusivity_end_date", "exclusivity_expiry", "expiry_basis",
          "product_url", "designation_url"]
URL = "https://ec.europa.eu/health/documents/community-register/ods/ods_products.json"
MIN_RECORDS = 250

# Marketing authorisation holders are companies, but Airmid never risks publishing a person's name: keep a holder
# only if it reads as an organisation (the shared ORG_WORDS, plus company forms and names common in this register),
# and never if it looks like a postal address (the source occasionally has an address in the name field).
EXTRA_ORG = re.compile(r"a/s|\bapS\b|laborato|\beeig\b|\beesv\b|s\.r\.[il]\b|s[àa]rl\b|n\.v\.|mbh\b|gesellschaft|"
                       r"disease|\bfrance\b|\bammtek\b|\btheravia\b|\bsanofi\b|\bnovo nordisk\b|\bservier\b|"
                       r"\bupjohn\b|\bpfizer\b|\bablynx\b", re.I)
ADDRESS = re.compile(r"\d.*,|,.*\d")


def holder_or_blank(name: str) -> str:
    name = " ".join((name or "").split())
    if not name or ADDRESS.search(name):
        return ""
    return name if ORG_WORDS.search(name) or EXTRA_ORG.search(name) else ""


def fetch_raw() -> bytes:
    return fetch(URL, timeout=240)


def _en(items) -> str:
    """English text from the register's [{"LanguageCode", "Text"}] lists."""
    items = items or []
    for it in items:
        if it.get("LanguageCode") == "EN":
            return " ".join((it.get("Text") or "").split())
    return " ".join((items[0].get("Text") or "").split()) if items else ""


def _page(uri: str) -> str:
    return (uri or "").rsplit("/", 1)[-1]


def _https(uri: str) -> str:
    return "https://" + uri[len("http://"):] if (uri or "").startswith("http://") else (uri or "")


def add_months(d: dt.date, months: int) -> dt.date:
    """Calendar month arithmetic, clamped to the month's last day (as moment.js, which the Register uses)."""
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return dt.date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def parse(raw: bytes, min_records: int = MIN_RECORDS) -> list:
    data = json.loads(raw).get("data", [])
    designations = {_page(r.get("URI")): r for r in data if r.get("Type") == "Orphan designation"}
    out, unresolved = [], 0
    for p in data:
        if p.get("Type") != "Human":
            continue
        for link in p.get("AssociatedOrphanDesignations") or []:
            od = designations.get(_page(link.get("URI")))
            if od is None:
                unresolved += 1
                od = {}
            start, ext, end = link.get("LinkDate") or "", link.get("ExtensionLength"), link.get("EndDate") or ""
            ext = str(int(ext)) if ext not in (None, "") else ""
            if end:
                expiry, basis = end, "end date recorded in the Union Register"
            elif start and (p.get("Status") or "") != "Active":
                # no market, no exclusivity clock to show: never project a date for a refused/withdrawn medicine
                expiry, basis = "", f"no end date recorded; medicine status is {p.get('Status') or 'unknown'}"
            elif start:
                d = add_months(dt.date.fromisoformat(start), 120)
                if ext:
                    d = add_months(d, int(ext))
                expiry = d.isoformat()
                basis = ("computed as the Register shows it: start + 10 years"
                         + (f" + {ext} months paediatric extension" if ext else ""))
            else:
                expiry, basis = "", "not available in the Union Register"
            out.append({
                "eu_product_number": p.get("EUNumber") or "",
                "product_name": _en(p.get("Name")),
                "active_substance": _en(p.get("ActiveSubstance")),
                "product_status": p.get("Status") or "",
                "authorisation_date": p.get("AuthorisationDate") or "",
                "marketing_authorisation_holder": holder_or_blank((p.get("MAH") or {}).get("Name", "")),
                "orphan_designation_number": od.get("EUNumber") or "",
                "orphan_indication": _en(od.get("Indication")),
                "orphan_designation_status": od.get("Status") or "",
                "exclusivity_start": start,
                "paediatric_extension_months": ext,
                "paediatric_extension_date": link.get("ExtensionDate") or "",
                "exclusivity_end_date": end,
                "exclusivity_expiry": expiry,
                "expiry_basis": basis,
                "product_url": _https(p.get("URI")),
                "designation_url": _https(link.get("URI")),
            })
    if unresolved > 10:
        raise RuntimeError(f"{unresolved} orphan links point at designations missing from the dataset")
    if len(out) < min_records:
        raise RuntimeError(f"only {len(out)} orphan exclusivity links; refusing a partial dataset")
    out.sort(key=lambda r: (r["eu_product_number"], r["orphan_designation_number"], r["designation_url"]))
    return out
