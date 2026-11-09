"""Real-API extraction on the synthetic smoke case. Skipped without ANTHROPIC_API_KEY.

This is where the API actually compiles the schema (the union limit is enforced server
side); a later live run repeats it on the frozen cases and records tokens, latency and errors.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from bridge_check.extract import extract
from bridge_check.input import load_case
from bridge_check.store import open_store

SMOKE = Path(__file__).resolve().parent.parent / "fixtures" / "synthetic" / "case-smoke"

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set"),
]


def test_live_extraction_on_smoke_case(tmp_path: Path) -> None:
    import anthropic

    store = open_store(tmp_path / "live.db")
    run_id = store.insert_case_run(
        case_id="case-smoke",
        rules_version="bridge-v1",
        code_sha="live",
        prompt_version="extract-v1",
        schema_version="v1",
    )
    client = anthropic.Anthropic(max_retries=0)
    result = extract(load_case(SMOKE), client, store, run_id=run_id)
    assert result.source == "api"
    assert result.extraction.bp_readings, "expected the synthetic BP reading"
