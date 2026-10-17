"""Link the same medicine (active substance) across Airmid datasets.

    python tools/link_medicines.py --dist dist/v1 [--llm gpt-oss:20b --llm-limit 300]

Writes dist/v1/links/:
  medicine_links.csv / .json   one row per substance: normalised name, datasets it appears in, record counts,
                               and up to 5 record keys per dataset (dataset:record_index)
  llm_suggestions.json         (only with --llm) names the deterministic matcher could not place, with the local
                               model's suggested substance. SUGGESTIONS ONLY: never merged into medicine_links.

Matching is deterministic: lower-case, strip salt/ester/hydrate words and dosage noise, split combinations on
" and ", "/", "+", ",", ";". A substance is kept when it appears in at least two datasets.
"""

import argparse
import csv
import json
import re
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

# which field(s) hold active substance names in each dataset
SUBSTANCE_FIELDS = {
    "ema_medicines": ["inn", "active_substance"],
    "ema_orphans": ["active_substance"],
    "ema_shortages": ["inn"],
    "fda_shortages": ["generic_name"],
    "fda_approvals": ["active_ingredients"],
    "hc_approvals": ["ingredients"],
    "faers_counts": ["drug_generic_name"],
    "hpra_medicines": ["active_substances"],
}
ATC_FIELDS = {"ema_medicines": "atc_code", "hpra_medicines": "atc_codes"}
ATC_RE = re.compile(r"^[A-Z][0-9]{2}[A-Z]{2}[0-9]{2}$")  # full 7-character ATC substance codes only
SALTS = (r"hydrochloride|dihydrochloride|hydrobromide|sodium|disodium|potassium|calcium|magnesium|sulfate|sulphate|"
         r"phosphate|acetate|maleate|mesylate|mesilate|besylate|besilate|tartrate|bitartrate|citrate|fumarate|"
         r"succinate|tosylate|lactate|gluconate|chloride|bromide|nitrate|monohydrate|dihydrate|trihydrate|hydrate|"
         r"anhydrous|hemihydrate|pegol|alfa|beta|human|recombinant|base|free")
NOISE = re.compile(r"\(.*?\)|\[.*?\]|\b\d+(\.\d+)?\s*(mg|mcg|µg|g|ml|iu|%|units?)\b", re.I)
SALT_RE = re.compile(rf"\b({SALTS})\b", re.I)
SPLIT = re.compile(r"\s+and\s+|/|\+|;|,")


def norm(name: str) -> str:
    s = NOISE.sub(" ", name.lower())
    s = SALT_RE.sub(" ", s)
    s = re.sub(r"[^a-z0-9\- ]", " ", s)
    return re.sub(r"\s+", " ", s).strip(" -")


def substances(value) -> list:
    vals = value if isinstance(value, list) else [value]
    out = []
    for v in vals:
        for part in SPLIT.split(str(v or "")):
            n = norm(part)
            if len(n) >= 4 and not n.isdigit():
                out.append(n)
    return out


def ask_llm(host, model, names):
    prompt = ("For each product or ingredient name below, give the international non-proprietary name (INN) of its "
              "active substance in lower case, or 'unknown' if you are not sure. Do not guess. Reply as JSON object "
              "name -> inn.\n" + "\n".join(names))
    body = {"model": model, "prompt": prompt, "stream": False, "format": "json", "think": "low",
            "options": {"temperature": 0, "num_predict": 1500}}
    req = urllib.request.Request(host + "/api/generate", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        try:
            return json.loads(json.load(r).get("response", "{}"))
        except json.JSONDecodeError:
            return {}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", default="dist/v1")
    ap.add_argument("--llm", help="optional local Ollama model for suggestions on unplaced names")
    ap.add_argument("--llm-limit", type=int, default=300)
    ap.add_argument("--ollama", default="http://127.0.0.1:11434")
    a = ap.parse_args(argv)
    dist = Path(a.dist)
    catalog = json.loads((dist / "catalog.json").read_text(encoding="utf-8"))
    hits = defaultdict(lambda: defaultdict(list))  # substance -> dataset -> [record index]
    seen_raw = defaultdict(set)                     # dataset -> raw names that produced nothing in >=2 datasets
    atc = defaultdict(Counter)                      # substance -> ATC code -> times seen
    for ds in catalog["datasets"]:
        key = ds["key"]
        fields = SUBSTANCE_FIELDS.get(key)
        if not fields:
            continue
        recs = json.loads((dist / key / f"{key}.json").read_text(encoding="utf-8"))["records"]
        for i, r in enumerate(recs):
            if key == "faers_counts" and r.get("row_type") != "drug":
                continue
            found = set()
            for f in fields:
                if f in r:
                    found.update(substances(r[f]))
            for s in found:
                hits[s][key].append(i)
            # ATC codes from single-substance EMA/HPRA records only (a combination product's code is not the code of
            # each of its substances)
            if len(found) == 1 and key in ATC_FIELDS:
                v = r.get(ATC_FIELDS[key])
                for code in (v if isinstance(v, list) else str(v or "").replace(",", ";").split(";")):
                    code = str(code).strip().upper()
                    if ATC_RE.match(code):
                        atc[next(iter(found))][code] += 1

    rows = []
    for s, by in hits.items():
        if len(by) < 2:
            for key in by:
                seen_raw[key].add(s)
            continue
        rows.append({"substance": s, "atc_codes": [c for c, _ in atc[s].most_common(3)],
                     "datasets": sorted(by), "dataset_count": len(by),
                     "records": {k: len(v) for k, v in sorted(by.items())},
                     "examples": {k: [f"{k}:{i}" for i in v[:5]] for k, v in sorted(by.items())}})
    rows.sort(key=lambda r: (-r["dataset_count"], r["substance"]))
    out = dist / "links"
    out.mkdir(exist_ok=True)
    (out / "medicine_links.json").write_text(json.dumps({
        "about": "Same active substance across Airmid datasets, matched by normalised name (deterministic; no AI). "
                 "atc_codes: WHO ATC codes seen on single-substance EMA/HPRA records for that substance. "
                 "Record keys are dataset:index into that dataset's JSON records array in this release.",
        "count": len(rows), "records": rows}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    with open(out / "medicine_links.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["substance", "atc_codes", "dataset_count", "datasets", "records_per_dataset"])
        for r in rows:
            w.writerow([r["substance"], ";".join(r["atc_codes"]), r["dataset_count"], ";".join(r["datasets"]),
                        ";".join(f"{k}={v}" for k, v in r["records"].items())])
    print(f"linked {len(rows)} substances across >=2 datasets; "
          f"{sum(1 for r in rows if r['dataset_count'] >= 4)} in 4 or more")

    if a.llm:
        lonely = sorted({s for k in ("fda_shortages", "faers_counts", "ema_shortages") for s in seen_raw.get(k, ())})
        lonely = lonely[:a.llm_limit]
        sugg = {}
        for i in range(0, len(lonely), 40):
            sugg.update(ask_llm(a.ollama, a.llm, lonely[i:i + 40]))
        known = set(hits)
        result = [{"name": n, "suggested_inn": str(v).lower(), "suggested_exists_in_airmid": str(v).lower() in known}
                  for n, v in sugg.items() if str(v).lower() not in ("unknown", "", n)]
        (out / "llm_suggestions.json").write_text(json.dumps({
            "about": f"Suggestions from a local model ({a.llm}). NOT verified, NOT used in medicine_links. "
                     "A human must check each one against an official source before use.",
            "count": len(result), "suggestions": result}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"llm suggestions: {len(result)} (of {len(lonely)} unplaced names), not merged")


if __name__ == "__main__":
    main()
