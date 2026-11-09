from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from bridge_check import __version__
from bridge_check.cli import EXIT_FAILED, main

ROOT = Path(__file__).resolve().parent.parent
FREEZE = ROOT / "scripts" / "freeze_splits.py"


def test_version_prints_and_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--version"]) == 0
    assert __version__ in capsys.readouterr().out


def test_stub_subcommand_returns_failed() -> None:
    # `check` is implemented; `eval` is still a stub.
    assert main(["eval"]) == EXIT_FAILED


def _run_freeze(manifest: Path) -> int:
    cmd = [sys.executable, str(FREEZE), "--check", "--manifest", str(manifest)]
    return subprocess.run(cmd, capture_output=True, check=False).returncode


def _listed_mtsamples_docs(manifest: Path) -> list[Path]:
    """MTSamples documents listed in the manifest (never committed; fetched at run time)."""
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    return [
        ROOT / "cases" / variant["variant_id"] / rel
        for variant in data.get("variants") or []
        for rel in variant.get("files", {})
        if rel.startswith("docs/D2-mtsamples-")
    ]


def test_committed_manifest_is_valid() -> None:
    missing = [p for p in _listed_mtsamples_docs(ROOT / "splits.yaml") if not p.is_file()]
    if missing:
        # The full check, MTSamples hashes included, runs in the data-integrity CI job after
        # scripts/fetch_mtsamples.py; without the documents the check stops on them.
        pytest.skip(f"{len(missing)} MTSamples document(s) not fetched (fetch_mtsamples.py)")
    assert _run_freeze(ROOT / "splits.yaml") == 0


def test_invalid_manifest_is_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "splits.yaml"
    bad.write_text("version: one\nvariants: {}\n", encoding="utf-8")
    assert _run_freeze(bad) == 1
