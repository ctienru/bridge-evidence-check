"""Validate the rules tables (`rules/bridge-v1.yaml`, `rules/drugs-v1.yaml`).

Loads both files through the Pydantic models in `bridge_check.rules_schema`, prints a
short summary and exits 1 on any validation error. With `--require-complete` it also
exits 1 while any review marker (`TODO(terri)` / `REVIEW(terri)`) remains in either
file, so CI can refuse rule content that has not been checked by a human.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from bridge_check.rules_schema import (
    ANTIHYPERTENSIVE_CLASSES,
    CONDITION_IDS,
    DrugTable,
    RulesTable,
    load_drugs,
    load_rules,
)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RULES = ROOT / "rules" / "bridge-v1.yaml"
DEFAULT_DRUGS = ROOT / "rules" / "drugs-v1.yaml"
PENDING_MARKER = re.compile(r"\b(TODO|REVIEW)\(terri\)")


def _load[T](path: Path, loader: Callable[[Path], T]) -> T | None:
    try:
        return loader(path)
    except FileNotFoundError:
        print(f"check_rules: {path}: file not found", file=sys.stderr)
    except ValidationError as exc:
        print(f"check_rules: {path}: {exc.error_count()} validation error(s)", file=sys.stderr)
        for err in exc.errors():
            loc = ".".join(str(part) for part in err["loc"]) or "<root>"
            print(f"  {loc}: {err['msg']}", file=sys.stderr)
    return None


def pending_markers(path: Path) -> list[tuple[int, str]]:
    """Return (line number, marker) for every human-pending marker in the file."""
    found: list[tuple[int, str]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        for match in PENDING_MARKER.finditer(line):
            found.append((lineno, match.group(0)))
    return found


def summarize(rules: RulesTable, drugs: DrugTable) -> None:
    covered = {c.id for c in rules.conditions}
    missing = [i for i in CONDITION_IDS if i not in covered and not i.startswith("lifestyle.")]
    print(f"check_rules: rules {rules.version}, accessed {rules.policy_snapshot.accessed}")
    print(f"  sources: {', '.join(s.id for s in rules.policy_snapshot.sources)}")
    print(f"  conditions: {len(rules.conditions)} (missing: {missing or 'none'})")
    print(f"  project policies: {len(rules.project_policies)}")
    antihypertensives = [d for d in drugs.drugs if d.class_ in ANTIHYPERTENSIVE_CLASSES]
    ambiguous = [d for d in drugs.drugs if d.class_ambiguous]
    print(
        f"check_rules: drugs v{drugs.version}: {len(drugs.drugs)} entries, "
        f"{len(antihypertensives)} antihypertensive, {len(ambiguous)} class_ambiguous"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the rules tables.")
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    parser.add_argument("--drugs", type=Path, default=DEFAULT_DRUGS)
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="also fail while any review marker remains",
    )
    args = parser.parse_args(argv)

    rules = _load(args.rules, load_rules)
    drugs = _load(args.drugs, load_drugs)
    if rules is None or drugs is None:
        return 1
    summarize(rules, drugs)

    if args.require_complete:
        pending = [(p, n, m) for p in (args.rules, args.drugs) for n, m in pending_markers(p)]
        if pending:
            print(f"check_rules: {len(pending)} human-pending marker(s) remain:", file=sys.stderr)
            for path, lineno, marker in pending:
                shown = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
                print(f"  {shown}:{lineno}: {marker}", file=sys.stderr)
            return 1
        print("check_rules: no human-pending markers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
