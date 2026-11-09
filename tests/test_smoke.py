from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

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


def test_committed_manifest_is_valid() -> None:
    assert _run_freeze(ROOT / "splits.yaml") == 0


def test_invalid_manifest_is_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "splits.yaml"
    bad.write_text("version: one\nvariants: {}\n", encoding="utf-8")
    assert _run_freeze(bad) == 1
