"""Freshness check (v1.7): warn when a dataset's last good collection is older than its expected cadence.

weekly.sh keeps last week's copy of a source that fails, which is safe but silent: on 2 Nov 2026 nine datasets had
not been refreshed, one of them for three weeks, and nobody was told. Every dataset is collected by the weekly run,
so the expected cadence is 7 days; a dataset is stale when its datapackage.json "created" time is more than
CADENCE_DAYS - MARGIN_DAYS old. The margin makes a source that failed in this Monday's run (its copy is then about
7 days old, give or take how long the run took) show up in the same run, not a week later. Held sources are skipped. A per-source cadence can be set in CADENCE_OVERRIDES
(none needed so far).

The check only prints (one STALE line per dataset, which the weekly log keeps); it never stops a run or a release.
"""

import datetime as dt
import json
from pathlib import Path

CADENCE_DAYS = 7
MARGIN_DAYS = 0.5
CADENCE_OVERRIDES = {}   # key -> days


def stale(out_dir: Path, keys, now: dt.datetime = None) -> list:
    """[(key, last_collected_iso or "", age_days or None, cadence_days)] for each dataset older than its cadence."""
    now = now or dt.datetime.now(dt.timezone.utc)
    found = []
    for key in keys:
        cadence = CADENCE_OVERRIDES.get(key, CADENCE_DAYS)
        dp = Path(out_dir) / key / "datapackage.json"
        try:
            created = json.loads(dp.read_text(encoding="utf-8")).get("created") or ""
            when = dt.datetime.fromisoformat(created)
            if when.tzinfo is None:
                when = when.replace(tzinfo=dt.timezone.utc)
        except (OSError, ValueError):
            found.append((key, "", None, cadence))   # never collected, or unreadable metadata
            continue
        age = (now - when).total_seconds() / 86400
        if age > cadence - MARGIN_DAYS:
            found.append((key, created, round(age, 1), cadence))
    return found


def report(out_dir: Path, keys) -> int:
    """Print one STALE line per stale dataset and return how many there are."""
    rows = stale(out_dir, keys)
    try:   # v1.7: a registry entry may carry "stale_reason" for a known, documented outage
        from .registry import load_registry
        reasons = {k: v.get("stale_reason", "") for k, v in load_registry().items() if isinstance(v, dict)}
    except Exception:
        reasons = {}
    for key, created, age, cadence in rows:
        if reasons.get(key):
            print(f"STALE {key}: last good collection {created[:10] or '?'} (known: {reasons[key][:160]})")
            continue
        if age is None:
            print(f"STALE {key}: no readable collection in {out_dir} (expected every {cadence} days)")
        else:
            print(f"STALE {key}: last good collection {created[:10]}, {age} days ago (expected every {cadence} days)")
    if rows:
        print(f"WARN: {len(rows)} dataset(s) older than their expected cadence")
    else:
        print("fresh all datasets collected within their expected cadence")
    return len(rows)
