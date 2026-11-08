"""Structural checks for `docs/contracts.md` and `docs/annotation-guide.md`.

The MTSamples window check mirrors `test_public_outputs_contain_no_mtsamples_text` from
the contract (§11): no 40-character window of a locally fetched MTSamples document may
appear in either document. It is skipped when no such file exists locally.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "docs" / "contracts.md"
GUIDE = ROOT / "docs" / "annotation-guide.md"
WINDOW = 40

_G_HEADING = re.compile(r"^### (G-\d+)\b", re.MULTILINE)
_SOURCE_LINE = re.compile(r"^-?\s*\*{0,2}Source:", re.MULTILINE)
_REVIEWED_LINE = re.compile(r"^-?\s*\*{0,2}Reviewed:\s*(yes|no)\b", re.MULTILINE)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _g_clauses(text: str) -> dict[str, str]:
    """Map each `### G-xx` heading to the body up to the next heading."""
    heads = list(_G_HEADING.finditer(text))
    clauses: dict[str, str] = {}
    for i, match in enumerate(heads):
        start = match.end()
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = text[start:end]
        next_heading = re.search(r"^#{1,3} ", body, re.MULTILINE)
        if next_heading is not None:
            body = body[: next_heading.start()]
        clauses[match.group(1)] = body
    return clauses


def test_both_documents_exist() -> None:
    assert CONTRACT.is_file()
    assert GUIDE.is_file()


def test_guide_has_status_header() -> None:
    lines = _read(GUIDE).splitlines()
    assert any(line.startswith("Status:") for line in lines[:5])


def test_every_g_clause_has_source_and_reviewed() -> None:
    clauses = _g_clauses(_read(GUIDE))
    assert len(clauses) >= 7
    for clause_id, body in clauses.items():
        assert _SOURCE_LINE.search(body), f"{clause_id} lacks a Source: line"
        assert _REVIEWED_LINE.search(body), f"{clause_id} lacks a Reviewed: line"


def test_g_clause_ids_are_sequential() -> None:
    ids = [int(c.split("-")[1]) for c in _g_clauses(_read(GUIDE))]
    assert ids == list(range(1, len(ids) + 1))


def _mtsamples_files() -> list[Path]:
    return sorted((ROOT / "cases").glob("*/docs/D2-mtsamples-*.txt"))


def _windows(text: str) -> set[str]:
    return {text[i : i + WINDOW] for i in range(0, max(len(text) - WINDOW + 1, 0))}


def _shared_window_count(target: str, source: str) -> int:
    return sum(1 for w in _windows(source) if w in target)


def _assert_no_shared_windows(target: str, target_name: str, source: str, source_name: str) -> None:
    """Fail with a message that carries counts and names only, never the matched text."""
    hits = _shared_window_count(target, source)
    if hits:
        pytest.fail(
            f"{target_name} shares {hits} {WINDOW}-char window(s) with {source_name}",
            pytrace=False,
        )


@pytest.mark.parametrize("doc", [CONTRACT, GUIDE], ids=["contracts", "annotation-guide"])
def test_documents_contain_no_mtsamples_window(doc: Path) -> None:
    sources = _mtsamples_files()
    if not sources:
        pytest.skip("no local MTSamples documents under cases/*/docs/")
    target = _read(doc)
    for source in sources:
        with source.open(encoding="utf-8", newline="") as fh:
            text = fh.read()
        _assert_no_shared_windows(target, doc.name, text, source.name)


def test_window_failure_message_does_not_leak_source_text() -> None:
    secret = "synthetic-marker-" + "q7x2" * 12  # 60 chars, longer than one window
    source = "lead-in text " + secret + " trailing text"
    target = "a document that quotes the marker: " + secret
    with pytest.raises(pytest.fail.Exception) as excinfo:
        _assert_no_shared_windows(target, "target.md", source, "source.txt")
    message = str(excinfo.value)
    assert "target.md" in message and "source.txt" in message
    for i in range(0, len(secret) - WINDOW + 1):
        assert secret[i : i + WINDOW] not in message
    assert "q7x2q7x2" not in message


def test_window_check_passes_on_unrelated_text() -> None:
    _assert_no_shared_windows("x" * 100, "t", "y" * 100, "s")
