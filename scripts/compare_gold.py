"""Compare one completed `bridge check` run against its gold (contract §8).

    uv run python scripts/compare_gold.py --db <path> --case cases/case-07 --out <json> \
        [--md <markdown>] [--run-id N] [--gold <expected.json>] [--gold-questions <json>]

Per gold fact: matched / matched but excluded / wrong value / missed, plus false positives
and the `expected_absent` checks. Per condition and claim: live vs gold status and flags,
and for each mismatch the first upstream error (`bridge_check.compare.ERROR_CLASSES`).
The run is `--run-id`, else the newest completed run of the case. Output is deterministic
(sorted keys, no timestamps) and carries enums, counts, key names and evidence references
(`doc_id[start:end] sha8`) only. Gold is read, never written; `--gold-questions` lists rows
whose gold looks wrong (for the next guide revision). Holdout variants are refused.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from bridge_check.compare import (
    GoldQuestions,
    compare_stored_run,
    render_markdown,
    upsert_markdown_section,
)
from bridge_check.compute import DrugIndex
from bridge_check.gold_schema import Gold, format_errors
from bridge_check.input import case_id_of, resolve_case_dir
from bridge_check.manifest import read_problem, write_problem
from bridge_check.rules_schema import load_drugs, load_rules
from bridge_check.store import open_store

ROOT = Path(__file__).resolve().parent.parent
RULES = ROOT / "rules" / "bridge-v1.yaml"
DRUGS = ROOT / "rules" / "drugs-v2.yaml"


def dump(report: Any) -> str:
    return json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def load_gold(path: Path) -> tuple[Gold, str]:
    raw = path.read_bytes()
    return Gold.model_validate_json(raw), hashlib.sha256(raw).hexdigest()


def load_questions(path: Path | None) -> frozenset[tuple[str, str]]:
    if path is None:
        return frozenset()
    return GoldQuestions.model_validate_json(path.read_bytes()).keys()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--case", required=True, help="case directory or variant id")
    ap.add_argument("--run-id", type=int)
    ap.add_argument("--gold", type=Path, help="default <case>/expected.json")
    ap.add_argument("--gold-questions", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--md", type=Path, help="markdown file; the case's section is replaced")
    args = ap.parse_args(argv)

    case_dir = resolve_case_dir(args.case)
    gold_path = args.gold or case_dir / "expected.json"
    for path in (case_dir, gold_path):
        problem = read_problem(ROOT, path)
        if problem is not None:
            print(f"compare_gold: {problem}", file=sys.stderr)
            return 2
    for path in [args.out, *([args.md] if args.md else [])]:
        problem = write_problem(ROOT, path)
        if problem is not None:
            print(f"compare_gold: {problem}", file=sys.stderr)
            return 2
    try:
        gold, gold_sha = load_gold(gold_path)
        questions = load_questions(args.gold_questions)
    except ValidationError as exc:
        for line in format_errors(exc):
            print(f"compare_gold: {line}", file=sys.stderr)
        return 1
    if not args.db.is_file():
        print("compare_gold: database not found", file=sys.stderr)
        return 1
    store = open_store(args.db)
    try:
        run_id = args.run_id or store.latest_completed_run(case_id_of(args.case))
        if run_id is None:
            print("compare_gold: no completed run for this case", file=sys.stderr)
            return 1
        report = compare_stored_run(
            store,
            run_id,
            gold=gold,
            gold_sha256=gold_sha,
            rules=load_rules(RULES),
            drugs=DrugIndex(load_drugs(DRUGS)),
            questions=questions,
        )
    finally:
        store.close()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(dump(report), encoding="utf-8")
    if args.md:
        args.md.parent.mkdir(parents=True, exist_ok=True)
        upsert_markdown_section(args.md, report["variant_id"], render_markdown(report))
    t = report["totals"]
    print(
        f"compare_gold: {report['variant_id']} run {run_id}: conditions "
        f"{t['conditions_correct']}/{t['conditions_total']}, claims "
        f"{t['claims_correct']}/{t['claims_total']}, facts {t['matched']}/{t['gold_facts']} "
        f"matched, false support {t['false_support']}, missed exclusion {t['missed_exclusion']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
