"""Check the frozen-split manifest (splits.yaml).

Item 0 version: validates the top-level shape only.
TODO(item 1): per-file sha256 for input, docs, gold and replay; compare against the
base branch's splits.yaml (new variants may be added, frozen ones may not change
without a gold_version bump); MTSamples gold must store quote sha256 + offsets only.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

DEFAULT_MANIFEST = Path(__file__).resolve().parent.parent / "splits.yaml"


def validate(data: Any) -> list[str]:
    """Return a list of problems; an empty list means the manifest is valid."""
    problems: list[str] = []
    if not isinstance(data, dict):
        return ["top level must be a mapping"]
    version = data.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        problems.append("'version' must be an integer")
    variants = data.get("variants")
    if not isinstance(variants, list):
        problems.append("'variants' must be a list")
    return problems


def check(path: Path) -> int:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        print(f"freeze_splits: cannot read {path}: {exc}", file=sys.stderr)
        return 1
    problems = validate(data)
    for problem in problems:
        print(f"freeze_splits: {path}: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"freeze_splits: {path} OK ({len(data['variants'])} variants)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the frozen-split manifest.")
    parser.add_argument("--check", action="store_true", required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args(argv)
    return check(args.manifest)


if __name__ == "__main__":
    raise SystemExit(main())
