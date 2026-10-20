"""Command line: python -m airmed list | run <source|all> [--out DIR] | check"""

import argparse
import sys
from pathlib import Path

from .collectors import ALL
from .output import write_dataset
from .privacy import check_fields, clean_record
from .registry import SourceNotApproved, approved_source, held_sources, load_registry


def run_one(key: str, out_dir: Path) -> dict:
    src = approved_source(key)  # refuses blocked or unknown sources
    mod = ALL[key]
    if list(mod.FIELDS) != list(src["fields_kept"]):
        raise SourceNotApproved(f"{key}: collector fields differ from the registry's fields_kept")
    check_fields(mod.FIELDS)
    stats = {}
    records = [clean_record(r, stats) for r in mod.parse(mod.fetch_raw())]
    return write_dataset(key, src, mod.FIELDS, records, out_dir, stats)


def check() -> int:
    """Offline consistency check: every collector has an approved registry entry with matching fields.

    A collector whose source is on hold (status "pending") is reported as held, not as a failure, as long as its
    registry entry still matches its fields."""
    bad = 0
    held = held_sources()
    for key, mod in ALL.items():
        try:
            if key in held:
                src = load_registry()[key]
                check_fields(mod.FIELDS)
                if list(mod.FIELDS) != list(src.get("fields_kept", [])):
                    raise SourceNotApproved("fields differ from registry")
                print(f"held  {key}: {held[key]}")
                continue
            src = approved_source(key)
            check_fields(mod.FIELDS)
            if list(mod.FIELDS) != list(src["fields_kept"]):
                raise SourceNotApproved("fields differ from registry")
            print(f"ok    {key}")
        except Exception as e:  # report every problem, not just the first
            bad += 1
            print(f"FAIL  {key}: {e}")
    return 1 if bad else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="airmed")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("check")
    r = sub.add_parser("run")
    r.add_argument("source")
    r.add_argument("--out", default="out")
    rel = sub.add_parser("release")
    rel.add_argument("--src", default="out")
    rel.add_argument("--dist", default="dist/v1")
    a = ap.parse_args(argv)
    if a.cmd == "list":
        for key, s in load_registry().items():
            print(f"{s.get('status', '?'):9} {key:16} {s.get('name', '')}")
        return 0
    if a.cmd == "check":
        return check()
    if a.cmd == "release":
        from .release import ReleaseRefused, build
        try:
            res = build(Path(a.src), Path(a.dist))
        except ReleaseRefused as e:
            print(f"REFUSED  {e}")
            return 1
        print(f"ok    release: {res['datasets']} datasets, {res['records']:,} records -> {res['dist']}"
              + (f" (held, not released: {', '.join(res['held'])})" if res.get("held") else ""))
        return 0
    held = held_sources()
    keys = list(ALL) if a.source == "all" else [a.source]
    rc = 0
    for key in keys:
        if a.source == "all" and key in held:  # on hold: skipped, not a failure (naming it alone still refuses)
            print(f"skip  {key}: held ({held[key]})")
            continue
        if key not in ALL:
            print(f"FAIL  {key}: no collector")
            rc = 1
            continue
        try:
            res = run_one(key, Path(a.out))
            print(f"ok    {key}: {res['records']} records -> {res['dir']} ({res['blanked']} values blanked by privacy guard"
                  + (f": {res['by_field']}" if res['by_field'] else "") + ")")
        except Exception as e:
            print(f"FAIL  {key}: {e}")
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
