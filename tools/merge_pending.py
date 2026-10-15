"""Merge sources/pending/*.json into sources/registry.json and register the collector modules (one-off integrator)."""
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parent.parent
reg_path = root / "sources" / "registry.json"
reg = json.loads(reg_path.read_text(encoding="utf-8"))
added = []
for p in sorted((root / "sources" / "pending").glob("*.json")):
    entry = json.loads(p.read_text(encoding="utf-8"))
    key = p.stem
    entry.pop("key", None)
    reg["sources"][key] = entry
    added.append(key)

reg["sources"]["eu_ctis"] = {
    "name": "EU Clinical Trials Information System (CTIS) public portal",
    "publisher": "European Medicines Agency",
    "endpoint": "https://euclinicaltrials.eu/",
    "status": "blocked",
    "reason": "No published reuse terms for CTIS data; the EMA legal notice excludes content supplied by third parties "
              "(sponsors, Member States). Ask EMA in writing before any reuse.",
}
ct = reg["sources"]["ctgov_ireland"]["field_docs"]
ct["lead_sponsor"] = ("Lead sponsor organisation. Blank when ClinicalTrials.gov does not class it as industry, "
                      "government or network AND the name does not read as an organisation (investigator-led studies "
                      "often name a person; Airmid never publishes personal names).")
if "ctgov_europe" in reg["sources"]:
    reg["sources"]["ctgov_europe"]["field_docs"]["lead_sponsor"] = ct["lead_sponsor"]
reg_path.write_text(json.dumps(reg, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

init = root / "airmed" / "collectors" / "__init__.py"
mods = sorted(p.stem for p in (root / "airmed" / "collectors").glob("*.py") if p.stem != "__init__")
order = ["ctgov_ireland", "hpra_medicines", "ema_shortages", "ema_medicines", "ema_orphans", "fda_shortages",
         "fda_approvals", "hc_approvals", "cso_pharma_exports", "nih_ireland"]
order += [m for m in mods if m not in order]
init.write_text('"""Collectors. Each module exposes KEY, FIELDS, parse(raw: bytes) -> list[dict] and fetch_raw() -> bytes."""\n\n'
                "from . import (" + ", ".join(sorted(mods)) + ")\n\n"
                "ALL = {m.KEY: m for m in (" + ", ".join(order) + ")}\n", encoding="utf-8")
print("merged:", added)
print("collectors:", order)
