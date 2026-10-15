"""Build the Airmid semantic search index from a release (run after `python -m airmed release`).

    python tools/search_index.py --dist dist/v1 [--ollama http://127.0.0.1:11434] [--model all-minilm]

Writes dist/v1/search/:
  manifest.json   model id, dims, dataset list, record counts, build time
  items.json      [[dataset_index, label, url_or_empty], ...]  (one row per indexed record, same order as vectors)
  signs.bin       1 bit per dimension per record (sign of the normalised embedding), 48 bytes per record
  related/<key>.json  for each record of <key>: up to 3 nearest records from OTHER datasets [[ds, item, score]]

Vectors come from a local Ollama embedding model (all-minilm = sentence-transformers/all-MiniLM-L6-v2). The browser
runs the same model (transformers.js, Xenova/all-MiniLM-L6-v2) on the visitor's query and scores q . sign(doc), so no
server ever sees the query. Statistical datasets (pure numbers) are not indexed. numpy is needed for `related/`;
without it only the search files are written.
"""

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

MODEL_BROWSER = "Xenova/all-MiniLM-L6-v2"

# label = what a person would search for; extra = short context fields; url = how to open the record.
DATASETS = {
    "ctgov_ireland": dict(label="title", extra=["conditions", "lead_sponsor", "phases", "overall_status"],
                          url=lambda r: f"https://clinicaltrials.gov/study/{r['nct_id']}"),
    "ctgov_europe": dict(label="title", extra=["conditions", "lead_sponsor", "phases", "countries"],
                         url=lambda r: f"https://clinicaltrials.gov/study/{r['nct_id']}"),
    "hpra_medicines": dict(label="product_name", extra=["holder", "dosage_form", "atc_codes", "product_type"]),
    "ema_medicines": dict(label="medicine_name", extra=["inn", "active_substance", "therapeutic_area", "holder"], url="url"),
    "ema_orphans": dict(label=["medicine_name", "active_substance"], extra=["active_substance", "intended_use"], url="url"),
    "ema_shortages": dict(label="medicine", extra=["inn", "therapeutic_area", "forms", "status"], url="url"),
    "fda_shortages": dict(label="generic_name", extra=["therapeutic_category", "dosage_form", "status", "shortage_reason"]),
    "fda_approvals": dict(label="brand_names", extra=["active_ingredients", "sponsor_name", "dosage_forms"]),
    "hc_approvals": dict(label="brand_names", extra=["ingredients", "therapeutic_class", "company"]),
    "nih_ireland": dict(label="project_title", extra=["organisation", "institute"]),
}
GENERIC_LABELS = ["title", "name", "medicine_name", "medicine", "product_name", "project_title", "acronym"]
SKIP_NUMERIC = True  # datasets whose records have no text label are statistics: not indexed


def text_of(v):
    if isinstance(v, list):
        return ", ".join(str(x) for x in v if x not in (None, ""))
    return "" if v is None else str(v)


def describe(key, rec):
    cfg = DATASETS.get(key)
    if cfg is None:  # new dataset without a config: pick the first texty label field, include other short strings
        lab = next((f for f in GENERIC_LABELS if text_of(rec.get(f))), None)
        if lab is None:
            return None
        extra = [k for k, v in rec.items() if k != lab and isinstance(v, (str, list)) and 0 < len(text_of(v)) < 120
                 and not text_of(v).startswith("http")][:5]
        cfg = dict(label=lab, extra=extra, url="url")
    labs = cfg["label"] if isinstance(cfg["label"], list) else [cfg["label"]]
    label = next((text_of(rec.get(f)).strip() for f in labs if text_of(rec.get(f)).strip()), "")
    if not label:
        return None
    ctx = " | ".join(t for t in (text_of(rec.get(f)) for f in cfg["extra"]) if t)
    u = cfg.get("url")
    url = u(rec) if callable(u) else text_of(rec.get(u)) if u else ""
    if url and not url.startswith("https://"):
        url = ""
    return label[:200], (label + (" | " + ctx if ctx else ""))[:500], url


def embed(texts, host, model, batch=128):
    out = []
    for i in range(0, len(texts), batch):
        body = json.dumps({"model": model, "input": texts[i:i + batch]}).encode()
        req = urllib.request.Request(host + "/api/embed", data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=600) as r:
            out.extend(json.load(r)["embeddings"])
        if (i // batch) % 20 == 0:
            print(f"  embedded {min(i + batch, len(texts))}/{len(texts)}", flush=True)
    return out


def pack_signs(vec):
    b = bytearray(len(vec) // 8)
    for j, x in enumerate(vec):
        if x > 0:
            b[j >> 3] |= 1 << (7 - (j & 7))
    return bytes(b)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", default="dist/v1")
    ap.add_argument("--ollama", default="http://127.0.0.1:11434")
    ap.add_argument("--model", default="all-minilm")
    a = ap.parse_args(argv)
    dist = Path(a.dist)
    catalog = json.loads((dist / "catalog.json").read_text(encoding="utf-8"))
    out = dist / "search"
    (out / "related").mkdir(parents=True, exist_ok=True)

    keys, items, texts, per_ds = [], [], [], {}
    for ds in catalog["datasets"]:
        key = ds["key"]
        data = json.loads((dist / key / f"{key}.json").read_text(encoding="utf-8"))
        recs = data["records"]
        rows = [(i, describe(key, r)) for i, r in enumerate(recs)]
        rows = [(i, d) for i, d in rows if d]
        if not rows and SKIP_NUMERIC:
            print(f"skip  {key} (no text labels: statistics)")
            continue
        di = len(keys)
        keys.append(key)
        per_ds[key] = []
        for i, (label, text, url) in rows:
            per_ds[key].append(len(items))
            items.append([di, label, url])
            texts.append(text)
        print(f"index {key}: {len(rows)} of {len(recs)} records")

    t0 = time.time()
    vecs = embed(texts, a.ollama, a.model)
    dims = len(vecs[0])
    if dims % 8:
        sys.exit("embedding size must be a multiple of 8")
    (out / "signs.bin").write_bytes(b"".join(pack_signs(v) for v in vecs))
    (out / "items.json").write_text(json.dumps(items, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    related_written = False
    try:
        import numpy as np
        M = np.asarray(vecs, dtype=np.float32)
        M /= np.linalg.norm(M, axis=1, keepdims=True) + 1e-9
        ds_of = np.asarray([it[0] for it in items])
        for key, idxs in per_ds.items():
            rel = []
            for start in range(0, len(idxs), 2048):
                block = np.asarray(idxs[start:start + 2048])
                S = M[block] @ M.T
                S[:, ds_of == keys.index(key)] = -1  # only link to OTHER datasets
                top = np.argpartition(-S, 3, axis=1)[:, :3]
                for r, cand in enumerate(top):
                    cand = cand[np.argsort(-S[r, cand])]
                    rel.append([[int(ds_of[c]), int(c), round(float(S[r, c]), 3)] for c in cand if S[r, c] >= 0.6])
            (out / "related" / f"{key}.json").write_text(json.dumps(rel, separators=(",", ":")), encoding="utf-8")
        related_written = True
    except ImportError:
        print("numpy not available: related/ not written")

    manifest = {"model_server": a.model, "model_browser": MODEL_BROWSER, "dims": dims, "bytes_per_record": dims // 8,
                "scoring": "dot(query_normalised, sign(doc)); higher is better", "datasets": keys,
                "records": len(items), "related": related_written,
                "built": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "embed_seconds": round(time.time() - t0)}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(json.dumps(manifest))


if __name__ == "__main__":
    main()
