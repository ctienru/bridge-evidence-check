"""Guard `reports/baseline-dev.json` in CI (contract §11).

    uv run python scripts/check_baseline_title.py --base <git-ref> --title "<PR title>"

Exit 1 when the base has the baseline and this checkout deleted it, or when the file
differs from the base and the PR title lacks `[update baseline]`. Exit 0 otherwise,
including when the base has no baseline (bootstrap). The title is read, never printed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bridge_check.baseline import UPDATE_MARKER, baseline_change_problem

ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", required=True, help="git ref of the PR base (or the zero sha)")
    ap.add_argument("--title", default="", help="the PR title")
    ap.add_argument("--root", type=Path, default=ROOT)
    args = ap.parse_args(argv)
    problem = baseline_change_problem(args.base, args.title, args.root)
    if problem is not None:
        print(f"check_baseline_title: {problem}", file=sys.stderr)
        return 1
    marker = "with" if UPDATE_MARKER in args.title else "without"
    print(f"check_baseline_title: ok ({marker} the update marker)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
