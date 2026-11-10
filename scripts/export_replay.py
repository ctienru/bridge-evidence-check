"""Write the public replay of one completed run (contract §11).

    uv run python scripts/export_replay.py --db <path> --case cases/case-07 [--run-id N] \
        [--out-dir replays]

The file is `<out-dir>/<variant_id>/<input_hash>-<prompt_version>-<schema_version>.json`,
written through `bridge_check.export.export_public_run()` (allow-list; MTSamples quotes as
offset + hash). The run is `--run-id`, else the newest completed run of the case. The
output is deterministic; the script prints the file name and quote counts only. Holdout
variants are refused.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bridge_check.export import ExportError, dump_replay, export_public_run, replay_path
from bridge_check.input import case_id_of, load_case, resolve_case_dir
from bridge_check.manifest import read_problem, write_problem
from bridge_check.store import open_store

ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--case", required=True, help="case directory or variant id")
    ap.add_argument("--run-id", type=int)
    ap.add_argument("--out-dir", type=Path, default=ROOT / "replays")
    args = ap.parse_args(argv)

    case_dir = resolve_case_dir(args.case)
    problem = read_problem(ROOT, case_dir)
    if problem is not None:
        print(f"export_replay: {problem}", file=sys.stderr)
        return 2
    if not args.db.is_file():
        print("export_replay: database not found", file=sys.stderr)
        return 1
    case = load_case(case_dir)
    store = open_store(args.db)
    try:
        run_id = args.run_id or store.latest_completed_run(case_id_of(args.case))
        if run_id is None:
            print("export_replay: no completed run for this case", file=sys.stderr)
            return 1
        run = store.case_run(run_id)
        if run["input_hash"] != case.input_hash:
            print("export_replay: the run's input hash differs from the case", file=sys.stderr)
            return 1
        payload = export_public_run(store, run_id, case.texts)
    except ExportError as exc:
        print(f"export_replay: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()
    out = replay_path(
        args.out_dir,
        payload["variant_id"],
        payload["input_hash"],
        payload["prompt_version"],
        payload["schema_version"],
    )
    problem = write_problem(ROOT, out)
    if problem is not None:
        print(f"export_replay: {problem}", file=sys.stderr)
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(dump_replay(payload), encoding="utf-8")
    print(
        f"export_replay: {out.parent.name}/{out.name} run {run_id}: "
        f"{payload['quote_count']} quotes, {payload['lossy_quote_count']} lossy"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
