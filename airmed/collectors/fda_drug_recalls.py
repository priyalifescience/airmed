"""US FDA drug recalls (openFDA drug enforcement reports), all years openFDA holds (2004 on), one row per recalled
product (recall number).

The collector reads openFDA's official bulk file for the drug/enforcement endpoint (one zipped JSON, about 4 MB) and
checks that it holds the number of records its own metadata and the download index state. Firm street addresses,
postal codes, city, state, lot/code information, distribution pattern and product quantities are dropped inside
fetch_raw. A record without a recall number (not yet classified; one in the October 2026 file) is skipped. Phone numbers
and e-mail addresses printed in the product description or recall reason are replaced by "[phone removed]" /
"[e-mail removed]"; descriptions are cut to 300 characters and reasons to 1,000, as in fda_device_recalls.

Privacy: recalling firms are mostly companies and pharmacies, but a few are individuals (sole traders, online sellers).
The firm name is kept only when fda_ndc_directory.company_or_blank reads it as an organisation; otherwise it is blanked,
`firm_withheld` is "yes", and the product description or recall reason is blanked when it repeats a word of the
withheld name. The `openfda` block (product NDCs, brand and generic names) is filled by openFDA for about one recall
in six; it links a recall to the fda_ndc_directory dataset.
"""

import json

from ..privacy import EMAIL_RE, PHONE_RE
from ..util import iso_date
from .fda_ndc_directory import bulk_results, company_or_blank, mentions, name_group, name_words

KEY = "fda_drug_recalls"
FIELDS = ["recall_number", "event_id", "classification", "status", "recalling_firm", "firm_withheld", "firm_country",
          "product_description", "reason_for_recall", "voluntary_mandated", "initial_firm_notification",
          "product_ndc", "brand_name", "generic_name", "recall_initiation_date", "classification_date", "report_date",
          "termination_date"]
KEEP = ("recall_number", "event_id", "classification", "status", "recalling_firm", "country", "product_description",
        "reason_for_recall", "voluntary_mandated", "initial_firm_notification", "recall_initiation_date",
        "center_classification_date", "report_date", "termination_date")
OPENFDA_KEEP = ("product_ndc", "brand_name", "generic_name")
DESC_MAX = 300
REASON_MAX = 1000
MIN_RECORDS = 10000     # the file holds ~18,000 recalls; far fewer means a broken file
PHONE_MARK = "[phone removed]"
EMAIL_MARK = "[e-mail removed]"


def _slim(r: dict) -> dict:
    o = r.get("openfda") or {}
    return {**{k: r.get(k) for k in KEEP}, "openfda": {k: o.get(k) or [] for k in OPENFDA_KEEP}}


def fetch_raw() -> bytes:
    results, meta = bulk_results("enforcement")
    return json.dumps({"total_in_file": len(results), "last_updated": meta.get("last_updated", ""),
                       "results": [_slim(r) for r in results]}).encode("utf-8")


def _short(text: str, limit: int) -> str:
    """Whitespace-normalised, firm phone numbers and e-mail addresses replaced by a marker, cut to `limit`.

    About 1 product description in 17 prints the firm's customer-service number; without the marker the privacy guard
    would blank the whole description."""
    t = " ".join((text or "").split())
    t = PHONE_RE.sub(PHONE_MARK, EMAIL_RE.sub(EMAIL_MARK, t))
    return t if len(t) <= limit else t[:limit - 1].rstrip() + "…"


def _uniq(items) -> list:
    out = []
    for i in items or []:
        if i and i not in out:
            out.append(i)
    return out


def parse(raw: bytes, min_records: int = MIN_RECORDS) -> list:
    data = json.loads(raw)
    rows = data.get("results", [])
    if data.get("total_in_file") is not None and data["total_in_file"] != len(rows):
        raise RuntimeError(f"recall raw file says {data['total_in_file']} records but holds {len(rows)}")
    if len(rows) < min_records:
        raise RuntimeError(f"only {len(rows)} drug recalls; refusing a partial file")
    groups = {}
    for r in rows:
        g = name_group(r.get("recalling_firm"))
        groups[g] = groups.get(g, 0) + 1
    out, seen = [], set()
    for r in rows:
        num = r.get("recall_number") or ""
        if not num or num in seen:
            continue
        seen.add(num)
        raw_firm = " ".join((r.get("recalling_firm") or "").split())
        firm = company_or_blank(raw_firm, groups.get(name_group(raw_firm), 0))
        hidden = name_words(raw_firm) if raw_firm and not firm else set()
        desc = _short(r.get("product_description"), DESC_MAX)
        reason = _short(r.get("reason_for_recall"), REASON_MAX)
        o = r.get("openfda") or {}
        out.append({
            "recall_number": num,
            "event_id": r.get("event_id") or "",
            "classification": r.get("classification") or "",
            "status": r.get("status") or "",
            "recalling_firm": firm,
            "firm_withheld": "yes" if raw_firm and not firm else "no",
            "firm_country": r.get("country") or "",
            "product_description": "" if mentions(desc, hidden) else desc,
            "reason_for_recall": "" if mentions(reason, hidden) else reason,
            "voluntary_mandated": r.get("voluntary_mandated") or "",
            "initial_firm_notification": r.get("initial_firm_notification") or "",
            "product_ndc": _uniq(o.get("product_ndc")),
            "brand_name": _uniq(o.get("brand_name")) if firm or not raw_firm else [],
            "generic_name": _uniq(o.get("generic_name")),
            "recall_initiation_date": iso_date(r.get("recall_initiation_date") or ""),
            "classification_date": iso_date(r.get("center_classification_date") or ""),
            "report_date": iso_date(r.get("report_date") or ""),
            "termination_date": iso_date(r.get("termination_date") or ""),
        })
    out.sort(key=lambda r: r["recall_number"])
    out.sort(key=lambda r: r["recall_initiation_date"], reverse=True)
    return out
