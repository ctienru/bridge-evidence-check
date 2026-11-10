"""Write `reports/baseline-dev.json` from stored runs (contract §11).

    uv run python scripts/build_baseline.py --db <path> [--out reports/baseline-dev.json] \
        [--run <variant_id>=<run_id> ...]

Thin wrapper over `bridge_check.baseline.build`: every dev variant of `splits.yaml`, in
manifest order, the newest completed run (or the `--run` given) compared against its gold.
`bridge eval --write-baseline` produces the same file from the same code path.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bridge_check.baseline import build, dump
from bridge_check.export import ExportError, write_public_file
from bridge_check.manifest import write_problem
from bridge_check.store import DatabaseHasLinks, open_store, sidecar_paths

ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=ROOT / "reports" / "baseline-dev.json")
    ap.add_argument("--run", action="append", default=[], help="<variant_id>=<run_id>")
    args = ap.parse_args(argv)
    if not args.db.is_file():
        print("build_baseline: database not found", file=sys.stderr)
        return 1
    # the database and the sidecars SQLite writes by name are outputs too
    for path in (args.out, args.db, *sidecar_paths(args.db)):
        problem = write_problem(ROOT, path)
        if problem is not None:
            print(f"build_baseline: {problem}", file=sys.stderr)
            return 2
    runs = {k: int(v) for k, _, v in (r.partition("=") for r in args.run)}
    try:
        store = open_store(args.db)
    except DatabaseHasLinks as exc:
        print(f"build_baseline: {exc}", file=sys.stderr)
        return 2
    try:
        data = build(store, runs, ROOT)
    except ValueError as exc:
        print(f"build_baseline: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()
    try:
        write_public_file(args.out, dump(data))  # link checks and atomic replacement
    except ExportError as exc:
        print(f"build_baseline: {exc}", file=sys.stderr)
        return 2
    t = data["totals"]
    print(
        f"build_baseline: {t['cases']} cases, conditions {t['conditions_correct']}/"
        f"{t['conditions_total']}, claims {t['claims_correct']}/{t['claims_total']}, "
        f"false support {t['false_support_count']}, missed exclusion "
        f"{t['missed_exclusion_count']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
