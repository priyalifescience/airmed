"""Health Canada Recalls and Safety Alerts (open data, English file): recalls and alerts for health products only,
that is drugs, natural health products, biologics and vaccines, radiopharmaceuticals and medical devices.

The publisher's file mixes in food (CFIA), vehicles (Transport Canada) and consumer products; those are left out.
A record is kept when it comes from Health Canada's medical devices programme, or when one of its ' - '-joined
categories is a health-product category. Veterinary-only and cannabis-only records are left out.
The "What you should do" advice text is not kept.
"""

import json

from ..http import fetch

KEY = "hc_recalls"
FIELDS = ["recall_id", "last_updated", "title", "product", "issue", "category", "organization", "recall_class",
          "archived", "url"]
URL = "https://recalls-rappels.canada.ca/sites/default/files/opendata-donneesouvertes/HCRSAMOpenData.json"
DEVICE_PROGRAMME = "Medical devices"
HEALTH_CATEGORIES = {"Drugs", "Natural health products", "Biologic or vaccine", "Radiopharmaceuticals",
                     "Health products", "Medical devices", "Homeopathic medicine"}
NON_HEALTH_ORGS = {"TC", "CFIA", "Consumer product safety"}
NEEDED = ["NID", "Title", "URL", "Organization", "Product", "Issue", "Category", "Recall class", "Last updated",
          "Archived"]


def fetch_raw() -> bytes:
    return fetch(URL, timeout=300)


def _health(r: dict) -> bool:
    org = (r.get("Organization") or "").strip()
    if org in NON_HEALTH_ORGS:
        return False
    if org == DEVICE_PROGRAMME:
        return True
    parts = {p.strip() for p in (r.get("Category") or "").split(" - ")}
    return bool(parts & HEALTH_CATEGORIES)


def parse(raw: bytes) -> list:
    rows = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("Health Canada recalls file is not a non-empty list")
    missing = [c for c in NEEDED if c not in rows[0]]
    if missing:
        raise RuntimeError(f"Health Canada recalls file is missing fields {missing}")
    out, seen = [], set()
    for r in rows:
        if not _health(r):
            continue
        nid = int(r["NID"])
        if nid in seen:
            raise RuntimeError(f"duplicate recall id {nid}")
        seen.add(nid)
        out.append({"recall_id": nid, "last_updated": r.get("Last updated") or "", "title": (r.get("Title") or "").strip(),
                    "product": (r.get("Product") or "").strip(), "issue": (r.get("Issue") or "").strip(),
                    "category": (r.get("Category") or "").strip(), "organization": (r.get("Organization") or "").strip(),
                    "recall_class": (r.get("Recall class") or "").strip(),
                    "archived": "yes" if str(r.get("Archived")) == "1" else "no", "url": r.get("URL") or ""})
    if len(rows) > 1000 and len(out) < 5000:
        raise RuntimeError(f"only {len(out)} health-product recalls; refusing a partial dataset")
    out.sort(key=lambda x: (x["last_updated"], x["recall_id"]), reverse=True)
    return out
