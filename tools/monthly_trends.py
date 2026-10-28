"""Airmid Éireann monthly trend report engine.

    python tools/monthly_trends.py --dist <release dir> --month YYYY-MM --out <dir>

--dist   a release directory: catalog.json plus one folder per dataset holding <key>.csv (the published layout).
--month  the edition month. Each indicator is reported for its own latest complete period that ended before the
         edition month (so a 2026-10 edition reports September 2026 at the latest, and earlier months where a source
         publishes later). The reference period is recorded next to every figure.
--out    output directory: report.json, indicators.csv (one row per indicator), series.csv (tidy long series) and
         charts/<indicator>.svg.

Indicator definitions live in tools/trends_indicators.json (see its "conventions" block). The rules applied here:
  * a month is complete for a dated-event source only when it ended before the source was collected, minus the
    indicator's publication lag; when a source's records stop before that month, the month holding its last record
    is treated as partial and excluded;
  * a month is complete for a source with its own period field when it is present (and, where a completeness key is
    set, has at least min_ratio x the highest number of key values seen in the previous 12 periods);
  * changes are month-on-month and year-on-year, given only when both periods are complete; percentage changes are
    withheld when a count behind either period is below the indicator's min_n.

Output is deterministic: the same release, definitions and code give byte-identical files. generated_at is pinned to
--generated-at, else SOURCE_DATE_EPOCH, else the release timestamp in catalog.json.

Standard library plus pandas only. Describes data; it does not explain causes or forecast.
"""
import argparse
import csv
import hashlib
import json
import math
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

ENGINE_VERSION = "1.0.0"
HERE = Path(__file__).resolve().parent
DEFAULT_INDICATORS = HERE / "trends_indicators.json"
SERIES_MONTHS = 24
SERIES_YEARS = 10
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]


# ---------------------------------------------------------------- period arithmetic
def mi(ym):
    """'YYYY-MM' -> month index."""
    return int(ym[:4]) * 12 + int(ym[5:7]) - 1


def ms(i):
    """month index -> 'YYYY-MM'."""
    return f"{i // 12:04d}-{i % 12 + 1:02d}"


def pidx(p, freq):
    return mi(p) if freq == "month" else int(p)


def pstr(i, freq):
    return ms(i) if freq == "month" else f"{i:04d}"


def month_label(ym):
    return f"{MONTHS[int(ym[5:7]) - 1]} {ym[:4]}"


def period_label(p, freq, window):
    if freq == "year":
        return p
    if window > 1:
        return f"{window} months to {month_label(p)}"
    return month_label(p)


# ---------------------------------------------------------------- loading
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Release:
    def __init__(self, dist):
        self.dist = Path(dist)
        self.catalog_path = self.dist / "catalog.json"
        self.catalog = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        self.entries = {d["key"]: d for d in self.catalog.get("datasets", [])}
        self._frames = {}
        self._hashes = {}

    def csv_path(self, key):
        return self.dist / key / f"{key}.csv"

    def frame(self, key):
        if key not in self._frames:
            p = self.csv_path(key)
            if not p.exists():
                raise FileNotFoundError(f"dataset file missing: {p}")
            self._frames[key] = pd.read_csv(p, dtype=str, keep_default_na=False, encoding="utf-8")
        return self._frames[key]

    def csv_sha256(self, key):
        if key not in self._hashes:
            self._hashes[key] = sha256_file(self.csv_path(key))
        return self._hashes[key]

    def retrieved(self, key):
        e = self.entries.get(key)
        if not e or not e.get("retrieved"):
            raise ValueError(f"catalog.json has no retrieved date for {key}")
        return e["retrieved"][:10]


# ---------------------------------------------------------------- filters and periods
def apply_filters(df, filters):
    mask = pd.Series(True, index=df.index)
    for f in filters or []:
        col, op, val = f["field"], f["op"], f.get("value")
        s = df[col]
        if op == "eq":
            m = s == str(val)
        elif op == "ne":
            m = s != str(val)
        elif op == "in":
            m = s.isin([str(v) for v in val])
        elif op == "not_in":
            m = ~s.isin([str(v) for v in val])
        elif op == "regex":
            m = s.str.contains(val, regex=True, na=False)
        elif op == "not_regex":
            m = ~s.str.contains(val, regex=True, na=False)
        elif op == "nonempty":
            m = s.str.strip() != ""
        elif op == "empty":
            m = s.str.strip() == ""
        elif op in ("gt", "ge", "lt", "le"):
            x = pd.to_numeric(s, errors="coerce")
            m = {"gt": x > val, "ge": x >= val, "lt": x < val, "le": x <= val}[op].fillna(False)
        else:
            raise ValueError(f"unknown filter op {op}")
        mask &= m
    return df[mask]


_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}")
_ISO_MONTH = re.compile(r"^\d{4}-\d{2}")
_DMY = re.compile(r"^(\d{2})/(\d{2})/(\d{4})")


def normalise_dates(s, fmt):
    """Return a Series of 'YYYY-MM-DD' or 'YYYY-MM' or 'YYYY' strings ('' when unreadable)."""
    if fmt == "iso":
        day = s.str.extract(r"^(\d{4}-\d{2}-\d{2})", expand=False)
        mon = s.str.extract(r"^(\d{4}-\d{2})", expand=False)
        return day.fillna(mon).fillna("")
    if fmt == "dmy":
        parts = s.str.extract(r"^(\d{2})/(\d{2})/(\d{4})")
        out = parts[2] + "-" + parts[1] + "-" + parts[0]
        return out.fillna("")
    if fmt == "year":
        return s.str.extract(r"^(\d{4})$", expand=False).fillna("")
    raise ValueError(f"unknown date_format {fmt}")


def to_period(d, freq):
    """normalised date strings -> period strings for the frequency ('' when not derivable)."""
    if freq == "month":
        return d.where(d.str.len() >= 7, "").str[:7]
    return d.where(d.str.len() >= 4, "").str[:4]


# ---------------------------------------------------------------- aggregation
def aggregate(df, agg):
    """df has column _p. Returns {period: {"num", "den", "n"}}."""
    t = agg["type"]
    out = {}
    if df.empty:
        return out
    if t == "count":
        for p, v in df.groupby("_p").size().items():
            out[p] = {"num": float(v), "den": None, "n": int(v)}
    elif t == "count_distinct":
        key = df[agg["keys"]].astype(str).agg("\x1f".join, axis=1)
        for p, v in key.groupby(df["_p"]).nunique().items():
            out[p] = {"num": float(v), "den": None, "n": int(v)}
    elif t == "sum":
        x = pd.to_numeric(df[agg["field"]], errors="coerce")
        g = pd.DataFrame({"_p": df["_p"], "x": x}).dropna()
        for p, grp in g.groupby("_p"):
            out[p] = {"num": float(math.fsum(grp["x"].tolist())), "den": None, "n": int(len(grp))}
    elif t == "value":
        x = pd.to_numeric(df[agg["field"]], errors="coerce")
        g = pd.DataFrame({"_p": df["_p"], "x": x}).dropna()
        for p, grp in g.groupby("_p"):
            if len(grp) != 1:
                raise ValueError(f"aggregation 'value' expects one row per period, got {len(grp)} for {p}")
            out[p] = {"num": float(grp["x"].iloc[0]), "den": None, "n": None}
    elif t == "share":
        measure = agg.get("measure", "count")
        sub = {"type": measure, "field": agg.get("field"), "keys": agg.get("keys")}
        den = aggregate(df, sub)
        num = aggregate(apply_filters(df, agg["numerator_filter"]), sub)
        for p, d in den.items():
            nn = num.get(p, {"num": 0.0, "n": 0})
            out[p] = {"num": nn["num"], "den": d["num"],
                      "n": (int(nn["n"]) if measure != "sum" else None),
                      "den_n": (int(d["n"]) if measure != "sum" else None)}
    else:
        raise ValueError(f"unknown aggregation {t}")
    return out


# ---------------------------------------------------------------- one indicator
def compute_indicator(spec, rel, edition):
    key = spec["datasets"][0]
    freq = spec.get("frequency", "month")
    kind = spec["kind"]
    window = int(spec.get("window", 1))
    lag = int(spec.get("lag_months", 0))
    flags, details = set(), {}

    raw = rel.frame(key)
    dates_all = normalise_dates(raw[spec["date_field"]], spec.get("date_format", "iso"))
    df = apply_filters(raw.assign(_d=dates_all), spec.get("filter"))
    df = df.assign(_p=to_period(df["_d"], freq))
    df = df[df["_p"] != ""]

    if spec.get("dedupe"):
        keys = spec["dedupe"]["keys"]
        df = df.sort_values(keys + ["_d"], kind="mergesort").drop_duplicates(keys, keep="first")

    snapshot_dates = {}
    if kind == "snapshot":
        latest = df.groupby("_p")["_d"].transform("max")
        df = df[df["_d"] == latest]
        snapshot_dates = {p: d for p, d in df.groupby("_p")["_d"].max().items()}

    edition_i = mi(edition) if freq == "month" else int(edition[:4])
    cap = edition_i - 1                                     # the period before the edition period
    agg = aggregate(df, spec["aggregation"])
    complete = {}                                           # period index -> aggregate dict

    if kind == "event":
        retrieved = rel.retrieved(key)
        ret_i = mi(retrieved[:7]) if freq == "month" else int(retrieved[:4])
        if freq == "year" and retrieved[5:10] == "12-31":
            ret_i += 1
        last = min(cap, ret_i - 1) - (lag if freq == "month" else 0)
        if lag:
            details["publication_lag_months"] = lag
        # source stops before the candidate period: its last record's period may be partial
        valid = dates_all[dates_all != ""]
        valid = valid[valid.map(lambda d: d <= retrieved[:len(d)])]   # ignore future-dated records
        if len(valid):
            dmax = valid.max()
            dmax_p = dmax[:7] if freq == "month" else dmax[:4]
            dmax_i = pidx(dmax_p, freq)
            if dmax_i < last:
                ends_period = (len(dmax) == 10 and
                               ((freq == "month" and dmax == _month_end(dmax_p)) or
                                (freq == "year" and dmax[5:] == "12-31")))
                new_last = dmax_i if ends_period else dmax_i - 1
                flags.add("source_stale")
                details["source_last_record"] = dmax
                if not ends_period:
                    flags.add("partial_period_excluded")
                    details["partial_period_excluded"] = dmax_p
                last = new_last
        if spec.get("coverage_start"):
            first = pidx(spec["coverage_start"] if freq == "month" else spec["coverage_start"][:4], freq)
        else:
            first = (min(pidx(p, freq) for p in agg) + 1) if agg else last + 1
        zero = {"num": 0.0, "den": None, "n": 0}
        if spec["aggregation"]["type"] == "share":
            zero = {"num": 0.0, "den": 0.0, "n": 0, "den_n": 0}
        elif spec["aggregation"]["type"] == "sum":
            zero = {"num": 0.0, "den": None, "n": 0}
        for i in range(first, last + 1):
            complete[i] = agg.get(pstr(i, freq), dict(zero))
    else:  # period or snapshot
        present = sorted(pidx(p, freq) for p in agg)
        comp = spec.get("completeness")
        keycount = {}
        if comp:
            kc = df.groupby("_p")[comp["key"]].nunique()
            keycount = {pidx(p, freq): int(v) for p, v in kc.items()}
        excluded = []
        for idx, i in enumerate(present):
            if i > cap:
                continue
            ok = True
            if comp:
                prev = [keycount[j] for j in present[max(0, idx - 12):idx]]
                if prev and keycount.get(i, 0) < comp.get("min_ratio", 1.0) * max(prev):
                    ok = False
            if ok:
                complete[i] = agg[pstr(i, freq)]
            else:
                excluded.append(i)
        last = max(complete) if complete else None
        first = min(complete) if complete else None
        later_excluded = [pstr(i, freq) for i in excluded if last is None or i > last]
        if later_excluded:
            flags.add("partial_period_excluded")
            details["partial_period_excluded"] = later_excluded[-1] if len(later_excluded) == 1 else later_excluded
            if comp:
                details["completeness_rule"] = (f"distinct {comp['key']} >= {comp.get('min_ratio', 1.0)} x "
                                                f"highest of previous 12 periods")
        if last is None:
            raise ValueError(f"{spec['id']}: no complete period")

    def at(i):
        """windowed aggregate at period index i, or None when any period in the window is not complete."""
        if i is None:
            return None
        cells = [complete.get(j) for j in range(i - window + 1, i + 1)]
        if any(c is None for c in cells):
            return None
        num = math.fsum(c["num"] for c in cells)
        den = None if cells[0].get("den") is None else math.fsum(c["den"] for c in cells)
        ns = [c.get("n") for c in cells]
        n = None if any(v is None for v in ns) else int(sum(ns))
        dns = [c.get("den_n") for c in cells]
        den_n = None if any(v is None for v in dns) else int(sum(dns))
        return {"num": num, "den": den, "n": n, "den_n": den_n}

    def value_of(a):
        if a is None:
            return None
        if spec["aggregation"]["type"] == "share":
            return None if not a["den"] else 100.0 * a["num"] / a["den"]
        return a["num"] / float(spec.get("scale", 1))

    # reference = latest complete period whose whole window is complete
    ref = last
    while first is not None and ref > first and at(ref) is None:
        ref -= 1
    if at(ref) is None:
        raise ValueError(f"{spec['id']}: no complete window")
    cur = at(ref)
    prev_i = ref - 1 if freq == "month" else None
    yago_i = ref - 12 if freq == "month" else ref - 1
    prev, yago = at(prev_i), at(yago_i)

    min_n = spec.get("min_n")
    is_share = spec["aggregation"]["type"] == "share"

    def n_basis(a):
        if a is None:
            return None
        if is_share:
            vals = [v for v in (a.get("n"), a.get("den_n")) if v is not None]
            return min(vals) if vals else None
        return a.get("n")

    def change(a, b, label):
        if a is None or b is None:
            return None, None, False
        va, vb = value_of(a), value_of(b)
        if va is None or vb is None:
            return None, None, False
        absd = va - vb
        small = (min_n is not None and n_basis(a) is not None and n_basis(b) is not None and
                 (n_basis(a) < min_n or n_basis(b) < min_n))
        pct = None
        if not small and vb != 0:
            pct = 100.0 * absd / vb
        if small:
            details.setdefault("small_n_comparisons", []).append(label)
        return absd, pct, small

    mom_abs, mom_pct, mom_small = change(cur, prev, "month_on_month")
    yoy_abs, yoy_pct, yoy_small = change(cur, yago, "year_on_year")
    if min_n is not None and n_basis(cur) is not None and n_basis(cur) < min_n:
        flags.add("small_n")
        details["small_n_rule"] = f"n < {min_n}: percentages not given"
    if mom_small or yoy_small:
        flags.add("small_n")
        details["small_n_rule"] = f"n < {min_n}: percentages not given"
    if freq == "month" and prev is None:
        flags.add("comparison_unavailable")
        details.setdefault("comparison_unavailable", []).append("month_on_month")
    if yago is None:
        flags.add("comparison_unavailable")
        details.setdefault("comparison_unavailable", []).append("year_on_year")
    behind = cap - ref
    if behind > 0:
        flags.add("data_lag")
    if spec.get("provisional"):
        flags.add("provisional")

    span = SERIES_MONTHS if freq == "month" else SERIES_YEARS
    series = []
    for i in range(ref - span + 1, ref + 1):
        v = value_of(at(i))
        series.append({"period": pstr(i, freq), "value": _r(v)})
    while series and series[0]["value"] is None:
        series.pop(0)

    ref_p = pstr(ref, freq)
    res = {
        "id": spec["id"],
        "section": spec["section"],
        "title": spec["title"],
        "definition": spec["definition"],
        "unit": spec["unit"],
        "frequency": freq,
        "window": window,
        "datasets": spec["datasets"],
        "date_field": spec["date_field"],
        "filter": spec.get("filter", []),
        "aggregation": spec["aggregation"],
        "min_n": min_n,
        "lag_months": lag,
        "decimals": spec.get("decimals", 0),
        "notes": spec.get("notes", []),
        "reference_period": ref_p,
        "reference_label": period_label(ref_p, freq, window),
        "value": _r(value_of(cur)),
        "n": cur.get("n"),
        "previous": _cmp(prev_i, prev, value_of, freq, window),
        "year_ago": _cmp(yago_i, yago, value_of, freq, window),
        "change": {"mom_abs": _r(mom_abs), "mom_pct": _r(mom_pct, 2), "yoy_abs": _r(yoy_abs),
                   "yoy_pct": _r(yoy_pct, 2)},
        "change_unit": "percentage points" if is_share else spec["unit"],
        "coverage": {"first_complete": pstr(first, freq) if first is not None else None,
                     "last_complete": pstr(last, freq)},
        "periods_behind_edition": behind,
        "flags": sorted(flags),
        "flag_details": details,
        "series": series,
        "chart": f"charts/{spec['id']}.svg",
    }
    if is_share:
        res["numerator"] = _r(cur["num"])
        res["denominator"] = _r(cur["den"])
        res["denominator_n"] = cur.get("den_n")
    if snapshot_dates:
        res["snapshot_date"] = snapshot_dates.get(ref_p)
        for k, i in (("previous", prev_i), ("year_ago", yago_i)):
            if res[k] and i is not None:
                res[k]["snapshot_date"] = snapshot_dates.get(pstr(i, freq))
    return res


def _month_end(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return date.fromordinal(nxt.toordinal() - 1).isoformat()


def _r(v, nd=6):
    if v is None:
        return None
    v = round(float(v), nd)
    if v == 0:
        v = 0.0
    return int(v) if v.is_integer() and abs(v) < 1e15 else v


def _cmp(i, a, value_of, freq, window):
    if i is None:
        return None
    p = pstr(i, freq)
    return {"period": p, "label": period_label(p, freq, window), "value": _r(value_of(a)),
            "n": None if a is None else a.get("n")}


# ---------------------------------------------------------------- formatting and charts
def fmt_num(v, decimals):
    if v is None:
        return "n/a"
    return f"{v:,.{decimals}f}"


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def svg_chart(ind, publisher, zero_base=True):
    W, H = 640, 300
    x0, x1, y0, y1 = 64, 616, 56, 236
    pts = [(s["period"], s["value"]) for s in ind["series"]]
    vals = [v for _, v in pts if v is not None]
    dec = ind.get("decimals", 0)
    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
             f'role="img" aria-label="{esc(ind["title"])}">',
             f'<rect x="0" y="0" width="{W}" height="{H}" fill="#ffffff"/>',
             f'<text x="16" y="24" font-family="sans-serif" font-size="14" font-weight="bold" fill="#1a1a1a">'
             f'{esc(ind["title"][:88])}</text>',
             f'<text x="16" y="42" font-family="sans-serif" font-size="11" fill="#555555">'
             f'{esc(ind["unit"])}. Reference period: {esc(ind["reference_label"])}.</text>']
    if not vals:
        lines.append("</svg>")
        return "\n".join(lines) + "\n"
    lo, hi = min(vals), max(vals)
    if zero_base and lo >= 0:
        lo = 0.0
    if hi == lo:
        hi, lo = hi + 1, (lo - 1 if lo != 0 else 0.0)
    pad = (hi - lo) * 0.05
    lo2, hi2 = (lo if lo == 0 else lo - pad), hi + pad
    n = len(pts)

    def X(k):
        return x0 + (x1 - x0) * (k / (n - 1) if n > 1 else 0.5)

    def Y(v):
        return y1 - (y1 - y0) * (v - lo2) / (hi2 - lo2)

    for t in range(3):
        v = lo2 + (hi2 - lo2) * t / 2
        y = Y(v)
        lines.append(f'<line x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}" stroke="#e3e3e3" stroke-width="1"/>')
        lines.append(f'<text x="{x0 - 6}" y="{y + 4:.1f}" text-anchor="end" font-family="sans-serif" '
                     f'font-size="10" fill="#555555">{esc(fmt_num(v, dec))}</text>')
    segs, cur = [], []
    for k, (_, v) in enumerate(pts):
        if v is None:
            if cur:
                segs.append(cur)
            cur = []
        else:
            cur.append(f"{X(k):.1f},{Y(v):.1f}")
    if cur:
        segs.append(cur)
    for sg in segs:
        if len(sg) == 1:
            x, y = sg[0].split(",")
            lines.append(f'<circle cx="{x}" cy="{y}" r="2.5" fill="#1f5f8b"/>')
        else:
            lines.append(f'<polyline points="{" ".join(sg)}" fill="none" stroke="#1f5f8b" stroke-width="2"/>')
    kx, kv = n - 1, pts[-1][1]
    if kv is not None:
        lines.append(f'<circle cx="{X(kx):.1f}" cy="{Y(kv):.1f}" r="4" fill="#c0392b"/>')
    ticks = sorted({0, n // 2, n - 1})
    for k in ticks:
        lines.append(f'<text x="{X(k):.1f}" y="{y1 + 16}" text-anchor="middle" font-family="sans-serif" '
                     f'font-size="10" fill="#555555">{esc(pts[k][0])}</text>')
    lines.append(f'<text x="16" y="{H - 14}" font-family="sans-serif" font-size="10" fill="#555555">'
                 f'Source: {esc(publisher[:100])}. Airmid Éireann, indicator {esc(ind["id"])}.</text>')
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- run
def resolve_generated_at(arg, rel):
    if arg:
        return arg
    sde = os.environ.get("SOURCE_DATE_EPOCH")
    if sde:
        return datetime.fromtimestamp(int(sde), tz=timezone.utc).isoformat()
    return rel.catalog.get("release")


def run(dist, edition, out, indicators_path=DEFAULT_INDICATORS, generated_at=None, only=None):
    if not re.fullmatch(r"\d{4}-\d{2}", edition):
        raise ValueError("--month must be YYYY-MM")
    rel = Release(dist)
    indicators_path = Path(indicators_path)
    cfg = json.loads(indicators_path.read_text(encoding="utf-8"))
    out = Path(out)
    (out / "charts").mkdir(parents=True, exist_ok=True)

    results, errors = [], []
    for spec in cfg["indicators"]:
        if only and spec["id"] not in only:
            continue
        try:
            results.append(compute_indicator(spec, rel, edition))
        except (KeyError, ValueError, FileNotFoundError) as e:
            errors.append({"id": spec["id"], "error": f"{type(e).__name__}: {e}"})

    used = sorted({k for r in results for k in r["datasets"]})
    sources = {}
    for k in used:
        e = rel.entries.get(k, {})
        sources[k] = {"title": e.get("title"), "publisher": e.get("publisher"), "licence": e.get("licence"),
                      "licence_url": e.get("licence_url"), "attribution": e.get("attribution"),
                      "collected": e.get("retrieved"), "records": e.get("records"),
                      "file": f"{k}/{k}.csv", "file_sha256": rel.csv_sha256(k)}
    for r in results:
        r["publishers"] = [sources[k]["publisher"] for k in r["datasets"]]
        r["collected"] = [sources[k]["collected"] for k in r["datasets"]]

    report = {
        "report": "Airmid Éireann monthly trend report",
        "edition": edition,
        "generated_at": resolve_generated_at(generated_at, rel),
        "engine": {"name": "airmed tools/monthly_trends.py", "version": ENGINE_VERSION,
                   "script_sha256": sha256_file(Path(__file__).resolve()),
                   "indicators_file": indicators_path.name, "indicators_version": cfg.get("version"),
                   "indicators_sha256": sha256_file(indicators_path),
                   "pandas_version": pd.__version__},
        "data_release": {"name": rel.catalog.get("name"), "generator": rel.catalog.get("generator"),
                         "release": rel.catalog.get("release"), "api_version": rel.catalog.get("api_version"),
                         "catalog_sha256": sha256_file(rel.catalog_path)},
        "rules": {
            "reference_period": "each indicator uses its own latest complete period ending before the edition month",
            "completeness": cfg.get("conventions", {}),
            "changes": "month-on-month and year-on-year, only when both periods are complete; percentage changes "
                       "withheld below min_n; shares change in percentage points",
            "description_only": "figures describe the data; no causes, predictions or medical advice",
        },
        "sections": cfg.get("sections", []),
        "indicators": results,
        "errors": errors,
        "sources": sources,
    }
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8",
                                     newline="\n")

    cols = ["id", "section", "title", "unit", "frequency", "window", "reference_period", "reference_label", "value",
            "n", "previous_period", "previous_value", "year_ago_period", "year_ago_value", "mom_abs", "mom_pct",
            "yoy_abs", "yoy_pct", "change_unit", "flags", "datasets", "publishers", "collected"]
    with open(out / "indicators.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(cols)
        for r in results:
            p, y, c = r["previous"] or {}, r["year_ago"] or {}, r["change"]
            w.writerow([r["id"], r["section"], r["title"], r["unit"], r["frequency"], r["window"],
                        r["reference_period"], r["reference_label"], _c(r["value"]), _c(r["n"]),
                        p.get("period", ""), _c(p.get("value")), y.get("period", ""), _c(y.get("value")),
                        _c(c["mom_abs"]), _c(c["mom_pct"]), _c(c["yoy_abs"]), _c(c["yoy_pct"]), r["change_unit"],
                        ";".join(r["flags"]), ";".join(r["datasets"]), "; ".join(r["publishers"]),
                        ";".join(r["collected"])])
    with open(out / "series.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["id", "period", "value", "unit"])
        for r in results:
            for s in r["series"]:
                w.writerow([r["id"], s["period"], _c(s["value"]), r["unit"]])
    kinds = {s["id"]: s["kind"] for s in cfg["indicators"]}
    for r in results:
        svg = svg_chart(r, "; ".join(r["publishers"]), zero_base=kinds[r["id"]] == "event")
        (out / r["chart"]).write_text(svg, encoding="utf-8", newline="\n")
    return report


def _c(v):
    return "" if v is None else v


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dist", required=True, help="release directory (catalog.json + <key>/<key>.csv)")
    ap.add_argument("--month", required=True, help="edition month, YYYY-MM")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--indicators", default=str(DEFAULT_INDICATORS), help="indicator definitions JSON")
    ap.add_argument("--generated-at", default=None, help="timestamp to record (default: pinned, see docstring)")
    a = ap.parse_args(argv)
    rep = run(a.dist, a.month, a.out, a.indicators, a.generated_at)
    for r in rep["indicators"]:
        print(f"{r['id']:<40} {r['reference_label']:<32} {r['value']!s:>14}  {','.join(r['flags'])}")
    for e in rep["errors"]:
        print(f"ERROR {e['id']}: {e['error']}", file=sys.stderr)
    return 1 if rep["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
