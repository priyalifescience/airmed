"""Command line: python -m airmed list | run <source|all> [--out DIR] | check"""

import argparse
import sys
from pathlib import Path

from .collectors import ALL
from .output import write_dataset
from .privacy import check_fields, clean_record
from .registry import SourceNotApproved, approved_source, load_registry


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
    """Offline consistency check: every collector has an approved registry entry with matching fields."""
    bad = 0
    for key, mod in ALL.items():
        try:
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
    a = ap.parse_args(argv)
    if a.cmd == "list":
        for key, s in load_registry().items():
            print(f"{s.get('status', '?'):9} {key:16} {s.get('name', '')}")
        return 0
    if a.cmd == "check":
        return check()
    keys = list(ALL) if a.source == "all" else [a.source]
    rc = 0
    for key in keys:
        if key not in ALL:
            print(f"FAIL  {key}: no collector")
            rc = 1
            continue
        try:
            res = run_one(key, Path(a.out))
            print(f"ok    {key}: {res['records']} records -> {res['dir']} ({res['blanked']} values blanked by privacy guard)")
        except Exception as e:
            print(f"FAIL  {key}: {e}")
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
