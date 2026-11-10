"""MTSamples leak checks shared by the tests (contract §11).

A public file leaks if it shares any 40-character window with a locally fetched MTSamples
document. Failure messages name files and counts only, never the matched text. With no
fetched MTSamples document (`scripts/fetch_mtsamples.py` not run) the checks skip.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WINDOW = 40


def mtsamples_files(root: Path = ROOT) -> list[Path]:
    return sorted((root / "cases").glob("*/docs/D2-mtsamples-*.txt"))


def read_exact(path: Path) -> str:
    with path.open(encoding="utf-8", newline="") as fh:
        return fh.read()


def windows(text: str) -> set[str]:
    return {text[i : i + WINDOW] for i in range(0, max(len(text) - WINDOW + 1, 0))}


def shared_window_count(target: str, source: str) -> int:
    return sum(1 for w in windows(source) if w in target)


def assert_no_shared_windows(target: str, target_name: str, source: str, source_name: str) -> None:
    """Fail with a message that carries counts and names only, never the matched text."""
    hits = shared_window_count(target, source)
    if hits:
        pytest.fail(
            f"{target_name} shares {hits} {WINDOW}-char window(s) with {source_name}",
            pytrace=False,
        )
