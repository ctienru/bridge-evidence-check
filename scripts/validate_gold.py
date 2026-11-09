"""Validate the annotator's files against the contract and guide shapes.

`--blind` → `BlindDraft` (guide B-01–B-03), `--adjudication` → one `AdjudicationLine` per
line (L-01), `--gold` → `Gold` (contract §8). Prints `OK <path>` or one line per error with
the field path and the error type (never a field value); exits 1 on any error. Files
under a holdout variant (`splits.yaml`) are refused unread.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from bridge_check.gold_schema import AdjudicationLine, BlindDraft, Gold, format_errors
from bridge_check.manifest import read_problem

ROOT = Path(__file__).resolve().parent.parent


def _validate(model: type[BaseModel], data: Any, label: str) -> list[str]:
    try:
        model.model_validate(data)
    except ValidationError as exc:
        return [f"{label}: {line}" for line in format_errors(exc)]
    return []


def validate_json_file(path: Path, model: type[BaseModel]) -> list[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{path}: cannot read JSON ({type(exc).__name__})"]
    return _validate(model, data, str(path))


def validate_jsonl_file(path: Path, model: type[BaseModel]) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [f"{path}: cannot read ({type(exc).__name__})"]
    problems: list[str] = []
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            problems.append(f"{path}:{lineno}: invalid JSON")
            continue
        problems.extend(_validate(model, data, f"{path}:{lineno}"))
    if not lines:
        problems.append(f"{path}: empty file")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--blind", type=Path, default=None, help="blind_draft.json")
    parser.add_argument("--adjudication", type=Path, default=None, help="adjudication.jsonl")
    parser.add_argument("--gold", type=Path, default=None, help="expected.json")
    parser.add_argument("--root", type=Path, default=ROOT, help="repo root (splits.yaml)")
    args = parser.parse_args(argv)
    jobs: list[tuple[Path | None, Callable[[Path], list[str]]]] = [
        (args.blind, lambda p: validate_json_file(p, BlindDraft)),
        (args.adjudication, lambda p: validate_jsonl_file(p, AdjudicationLine)),
        (args.gold, lambda p: validate_json_file(p, Gold)),
    ]
    if all(path is None for path, _ in jobs):
        parser.error("give at least one of --blind, --adjudication, --gold")
    failed = False
    for path, validate in jobs:
        if path is None:
            continue
        problem = read_problem(args.root.resolve(), path)
        if problem is not None:
            print(f"validate_gold: {problem}", file=sys.stderr)
            failed = True
            continue
        problems = validate(path)
        if problems:
            failed = True
            for problem in problems:
                print(f"validate_gold: {problem}", file=sys.stderr)
        else:
            print(f"OK {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
