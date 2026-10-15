"""US FDA medical device recalls since 2018 (openFDA), one row per recalled product (recall number).

The base is openFDA's device enforcement report (recall class, status, firm country). The device recall endpoint
adds the FDA-assigned root cause and the three-letter device product code, joined on recall number
(enforcement `recall_number` == recall `product_res_number`).

Firm street addresses, postal codes and the recall endpoint's `additional_info_contact` (phone numbers) are dropped
inside fetch_raw, so they are never kept even in memory beyond the page that brought them.
"""

import datetime
import json

from ..http import fetch
from ..util import iso_date

KEY = "fda_device_recalls"
FIELDS = ["recall_number", "event_id", "classification", "status", "recalling_firm", "firm_country", "product_code",
          "product_description", "reason_for_recall", "root_cause", "voluntary_mandated", "recall_initiation_date",
          "classification_date", "report_date", "termination_date"]
FIRST_YEAR = 2018
PAGE = 1000
ENF_API = "https://api.fda.gov/device/enforcement.json?search=recall_initiation_date:%5B{y}0101+TO+{y}1231%5D&limit={n}&skip={s}"
REC_API = "https://api.fda.gov/device/recall.json?search=event_date_initiated:%5B{y}-01-01+TO+{y}-12-31%5D&limit={n}&skip={s}"
ENF_KEEP = ("recall_number", "event_id", "classification", "status", "recalling_firm", "country", "product_description",
            "reason_for_recall", "voluntary_mandated", "recall_initiation_date", "center_classification_date",
            "report_date", "termination_date")
REC_KEEP = ("product_res_number", "product_code", "root_cause_description")
DESC_MAX = 300
REASON_MAX = 1000


def _year_pages(template: str, year: int, keep: tuple) -> list:
    rows, total = [], None
    for page in range(30):   # openFDA caps skip at 25,000; one year is far below that
        j = json.loads(fetch(template.format(y=year, n=PAGE, s=page * PAGE), timeout=120))
        if total is None:
            total = j["meta"]["results"]["total"]
        batch = j.get("results", [])
        rows.extend({k: r.get(k) for k in keep} for r in batch)
        if not batch or len(rows) >= total:
            break
    if len(rows) != total:
        raise RuntimeError(f"openFDA returned {len(rows)} of {total} device records for {year}")
    return rows


def fetch_raw(last_year: int = None) -> bytes:
    last_year = last_year or datetime.date.today().year
    enforcement, recalls = [], []
    for y in range(FIRST_YEAR, last_year + 1):
        enforcement.extend(_year_pages(ENF_API, y, ENF_KEEP))
        recalls.extend(_year_pages(REC_API, y, REC_KEEP))
    return json.dumps({"enforcement": enforcement, "recalls": recalls}).encode("utf-8")


def _short(text: str, limit: int) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= limit else t[:limit - 1].rstrip() + "…"


def parse(raw: bytes) -> list:
    data = json.loads(raw)
    extra = {}
    for r in data.get("recalls", []):
        num = r.get("product_res_number") or ""
        if num and (num not in extra or not extra[num].get("root_cause_description")):
            extra[num] = r
    out, seen = [], set()
    for r in data.get("enforcement", []):
        num = r.get("recall_number") or ""
        if not num or num in seen:
            continue
        seen.add(num)
        x = extra.get(num, {})
        out.append({
            "recall_number": num,
            "event_id": r.get("event_id") or "",
            "classification": r.get("classification") or "",
            "status": r.get("status") or "",
            "recalling_firm": (r.get("recalling_firm") or "").strip(),
            "firm_country": r.get("country") or "",
            "product_code": x.get("product_code") or "",
            "product_description": _short(r.get("product_description"), DESC_MAX),
            "reason_for_recall": _short(r.get("reason_for_recall"), REASON_MAX),
            "root_cause": x.get("root_cause_description") or "",
            "voluntary_mandated": r.get("voluntary_mandated") or "",
            "recall_initiation_date": iso_date(r.get("recall_initiation_date") or ""),
            "classification_date": iso_date(r.get("center_classification_date") or ""),
            "report_date": iso_date(r.get("report_date") or ""),
            "termination_date": iso_date(r.get("termination_date") or ""),
        })
    out.sort(key=lambda r: r["recall_number"])
    out.sort(key=lambda r: r["recall_initiation_date"], reverse=True)
    return out
