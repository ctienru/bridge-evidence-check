"""The pipeline never imports the data side (AGENTS.md "Never do").

Every module under `src/bridge_check/` outside `dataside/` is parsed with `ast`; any
import of `bridge_check.dataside` (absolute, or relative `.dataside`) fails the test.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "bridge_check"
FORBIDDEN = "bridge_check.dataside"


def _pipeline_modules() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if "dataside" not in p.relative_to(SRC).parts)


def dataside_imports(source: str) -> list[str]:
    """Import statements in `source` that reach the data-side package."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.extend(a.name for a in node.names if a.name.startswith(FORBIDDEN))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith(FORBIDDEN) or (node.level and module.split(".")[0] == "dataside"):
                found.append(module)
            if module in ("bridge_check", "") and node.level <= 1:
                found.extend(a.name for a in node.names if a.name == "dataside")
    return found


def test_there_are_pipeline_modules_to_check() -> None:
    names = {p.name for p in _pipeline_modules()}
    assert "cli.py" in names and "enums.py" in names


@pytest.mark.parametrize("module", _pipeline_modules(), ids=lambda p: p.relative_to(SRC).as_posix())
def test_pipeline_module_does_not_import_dataside(module: Path) -> None:
    assert dataside_imports(module.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize(
    "source",
    [
        "from bridge_check.dataside import drafting",
        "from bridge_check.dataside.cues import load_cues",
        "import bridge_check.dataside.candidates",
        "from .dataside import cues",
        "from bridge_check import dataside",
    ],
)
def test_detector_catches_every_import_form(source: str) -> None:
    assert dataside_imports(source), source
