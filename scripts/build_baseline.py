"""Write `reports/baseline-dev.json` from stored runs (contract §11).

    uv run python scripts/build_baseline.py --db <path> [--out reports/baseline-dev.json] \
        [--run <variant_id>=<run_id> ...]

Every dev variant of `splits.yaml`, in manifest order: the newest completed run (or the
`--run` given), compared against its gold (`bridge_check.compare`), with the hash of its
replay under `replays/` and the gold hash from the manifest. The gold file must still have
the manifest hash. A variant without a completed run fails the build. Output is
deterministic and carries statuses, flags, hashes and counts only (`baseline_schema`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from bridge_check.baseline_schema import BASELINE_VERSION, Baseline
from bridge_check.compare import compare_stored_run
from bridge_check.compute import DrugIndex
from bridge_check.export import replay_path
from bridge_check.gold_schema import Gold
from bridge_check.manifest import MANIFEST_NAME, write_problem
from bridge_check.rules_schema import load_drugs, load_rules
from bridge_check.store import open_store

ROOT = Path(__file__).resolve().parent.parent
RULES = ROOT / "rules" / "bridge-v1.yaml"
DRUGS = ROOT / "rules" / "drugs-v2.yaml"
REPLAYS = ROOT / "replays"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(data: Any) -> str:
    return json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def dev_variants(manifest: Path) -> list[dict[str, Any]]:
    data: Any = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    return [v for v in data["variants"] if v.get("split") == "dev"]


def _rows(report_rows: dict[str, Any]) -> dict[str, Any]:
    return {
        cid: {k: r[k] for k in ("status", "flags", "gold_status", "gold_flags", "correct")}
        for cid, r in report_rows.items()
    }


def build(db: Path, runs: dict[str, int], root: Path = ROOT) -> dict[str, Any]:
    manifest = root / MANIFEST_NAME
    rules = load_rules(RULES)
    drugs = DrugIndex(load_drugs(DRUGS))
    store = open_store(db)
    cases: dict[str, Any] = {}
    generated: dict[str, str] = {}
    try:
        for entry in dev_variants(manifest):
            vid = str(entry["variant_id"])
            gold_path = root / "cases" / vid / "expected.json"
            gold_sha = sha256_file(gold_path)
            if gold_sha != entry["files"]["expected.json"]:
                raise SystemExit(f"build_baseline: {vid}: expected.json differs from the manifest")
            run_id = runs.get(vid) or store.latest_completed_run(vid)
            if run_id is None:
                raise SystemExit(f"build_baseline: {vid}: no completed run")
            report = compare_stored_run(
                store,
                run_id,
                gold=Gold.model_validate_json(gold_path.read_bytes()),
                gold_sha256=gold_sha,
                rules=rules,
                drugs=drugs,
            )
            run = report["run"]
            replay = replay_path(
                root / "replays",
                vid,
                run["input_hash"],
                run["prompt_version"],
                run["schema_version"],
            )
            ext = store.extraction_for_run(run_id)
            attempt = store.attempt(int(ext["attempt_id"])) if ext and ext["attempt_id"] else {}
            this = {
                "code_sha": run["code_sha"],
                "prompt_version": run["prompt_version"],
                "schema_version": run["schema_version"],
                "rules_version": run["rules_version"],
                "model_returned": str(attempt.get("model_returned") or ""),
            }
            if generated and this != generated:
                raise SystemExit(f"build_baseline: {vid}: runs differ in versions or model")
            generated = this
            t = report["totals"]
            cases[vid] = {
                "input_hash": run["input_hash"],
                "gold_sha256": gold_sha,
                "replay": (
                    {"path": replay.relative_to(root).as_posix(), "sha256": sha256_file(replay)}
                    if replay.is_file()
                    else None
                ),
                "conditions": _rows(report["conditions"]),
                "claims": _rows(report["claims"]),
                "case_flags": report["case_flags"],
                "conditions_correct": t["conditions_correct"],
                "claims_correct": t["claims_correct"],
                "false_support_count": t["false_support"],
                "claims_false_support_count": t["claims_false_support"],
                "missed_exclusion_count": t["missed_exclusion"],
            }
    finally:
        store.close()
    c = cases.values()
    data = {
        "baseline_version": BASELINE_VERSION,
        "split": "dev",
        "manifest_sha256": sha256_file(manifest),
        "generated_from": generated,
        "cases": cases,
        "totals": {
            "cases": len(cases),
            "conditions_correct": sum(x["conditions_correct"] for x in c),
            "conditions_total": sum(len(x["conditions"]) for x in c),
            "claims_correct": sum(x["claims_correct"] for x in c),
            "claims_total": sum(len(x["claims"]) for x in c),
            "false_support_count": sum(x["false_support_count"] for x in c),
            "claims_false_support_count": sum(x["claims_false_support_count"] for x in c),
            "missed_exclusion_count": sum(x["missed_exclusion_count"] for x in c),
        },
    }
    Baseline.model_validate(data)
    return data


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=ROOT / "reports" / "baseline-dev.json")
    ap.add_argument("--run", action="append", default=[], help="<variant_id>=<run_id>")
    args = ap.parse_args(argv)
    if not args.db.is_file():
        print("build_baseline: database not found", file=sys.stderr)
        return 1
    problem = write_problem(ROOT, args.out)
    if problem is not None:
        print(f"build_baseline: {problem}", file=sys.stderr)
        return 2
    runs = {k: int(v) for k, _, v in (r.partition("=") for r in args.run)}
    data = build(args.db, runs)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(dump(data), encoding="utf-8")
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
