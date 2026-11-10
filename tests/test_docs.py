"""Structural checks for `docs/contracts.md` and `docs/annotation-guide.md`.

The MTSamples window check mirrors `test_public_outputs_contain_no_mtsamples_text` from
the contract (§11): no 40-character window of a locally fetched MTSamples document may
appear in either document. It is skipped when no such file exists locally.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from leakcheck import (
    WINDOW,
    mtsamples_files,
    read_exact,
)
from leakcheck import assert_no_shared_windows as _assert_no_shared_windows

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "docs" / "contracts.md"
GUIDE = ROOT / "docs" / "annotation-guide.md"
LIVE_RUN = ROOT / "docs" / "live-run-01.md"
ADR_LIMITS = ROOT / "docs" / "adr" / "0001-global-limits.md"
ADR_OUTPUT_MODE = ROOT / "docs" / "adr" / "0002-extraction-output-mode.md"
CHECKPOINT_A = ROOT / "docs" / "checkpoint-a.md"
EVAL_DOC = ROOT / "docs" / "eval.md"
RECOVERY = ROOT / "docs" / "recovery.md"
README = ROOT / "README.md"

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


def test_live_run_and_adr_exist_and_name_no_plan_tickets() -> None:
    for doc in (LIVE_RUN, ADR_LIMITS, ADR_OUTPUT_MODE, CHECKPOINT_A, EVAL_DOC, RECOVERY):
        text = _read(doc)
        assert not re.search(r"\bW\d{2}\b", text), f"{doc.name} names a plan ticket"
        assert "/Users/" not in text, f"{doc.name} contains a home-directory path"


def test_readme_has_no_placeholders() -> None:
    assert "{{" not in _read(README), "README.md still contains a {{placeholder}}"


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


@pytest.mark.parametrize(
    "doc",
    [CONTRACT, GUIDE, LIVE_RUN, ADR_LIMITS, ADR_OUTPUT_MODE, CHECKPOINT_A, EVAL_DOC, RECOVERY],
    ids=[
        "contracts",
        "annotation-guide",
        "live-run-01",
        "adr-0001",
        "adr-0002",
        "checkpoint-a",
        "eval",
        "recovery",
    ],
)
def test_documents_contain_no_mtsamples_window(doc: Path) -> None:
    sources = mtsamples_files()
    if not sources:
        pytest.skip("no local MTSamples documents under cases/*/docs/")
    target = _read(doc)
    for source in sources:
        _assert_no_shared_windows(target, doc.name, read_exact(source), source.name)


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
