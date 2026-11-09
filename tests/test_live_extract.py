"""Real-API extraction on the synthetic smoke case (`uv run pytest -q -m live`).

Opt-in only: the test runs only when `-m live` selects it explicitly (not under a plain
`pytest`, which excludes nothing by marker) and a key exists (`ANTHROPIC_API_KEY` in the
environment, else `.env` in the checkout; read inside the test, never at import, never
printed). The `live` marker is excluded from CI.
This is the one place the request shape meets the real API: the schema travels as the
`input_schema` of the `record_extraction` tool with `tool_choice: auto` (ADR 0002), so
every change to the schema, the tool or the prompt is checked here with one call on the
cheapest case. The measured tokens, latency and cost are printed in the terminal summary
(`conftest.py`). `docs/live-run-01.md` records the same measurement on the frozen cases.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from bridge_check.extract import PROMPT_VERSION, SERVER_INPUT_ALLOWANCE_TOKENS, TOOL_NAME, extract
from bridge_check.input import load_case
from bridge_check.schema import SCHEMA_VERSION
from bridge_check.store import open_store

ROOT = Path(__file__).resolve().parent.parent
SMOKE = ROOT / "fixtures" / "synthetic" / "case-smoke"
KEY = "ANTHROPIC_API_KEY"


def _key_from_dotenv(path: Path = ROOT / ".env") -> str | None:
    """`KEY=value` from `.env`; None when the file or the line is absent."""
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip() == KEY and value.strip():
            return value.strip().strip("'\"")
    return None


pytestmark = pytest.mark.live

LIVE_MARKEXPR = "live"


def live_selected(markexpr: str) -> bool:
    """True only for the documented opt-in, exactly `-m live`. Any other expression,
    including one where `live` appears under a negation or inside a group, is not one."""
    return markexpr.strip() == LIVE_MARKEXPR


def make_client(key: str) -> Any:
    """An SDK client holding `key`; its repr (what pytest prints for a fixture argument in
    a traceback) does not contain the key. A constructor failure (for example a malformed
    proxy variable) is reported by exception class only, without a traceback, so no frame
    holding `key` is ever printed, not even under `--showlocals`."""
    import anthropic

    try:
        return anthropic.Anthropic(api_key=key, max_retries=0)
    except Exception as exc:  # noqa: BLE001 - sanitized on purpose
        pytest.fail(f"could not construct the API client: {type(exc).__name__}", pytrace=False)


@pytest.fixture
def live_client(request: pytest.FixtureRequest) -> Any:
    """A configured client for one explicitly selected live test; skips otherwise. The
    test never sees the key itself, so no traceback frame can print it."""
    if not live_selected(str(request.config.getoption("markexpr") or "")):
        pytest.skip("live tests run only when selected with -m live")
    key = os.environ.get(KEY) or _key_from_dotenv()
    if not key:
        pytest.skip(f"{KEY} not set (environment or .env)")
    return make_client(key)


@pytest.mark.parametrize(
    "expr", ["", "not live", "slow and not live", "not (slow and live)", "live or slow", "(live)"]
)
def test_only_the_exact_live_expression_selects(expr: str) -> None:
    assert not live_selected(expr)


def test_exact_live_expression_selects() -> None:
    assert live_selected("live") and live_selected(" live ")


SYNTHETIC_KEY = "sk-ant-synthetic-" + "k7q2" * 8


def test_client_repr_hides_the_key() -> None:
    client = make_client(SYNTHETIC_KEY)
    assert SYNTHETIC_KEY not in repr(client) and SYNTHETIC_KEY not in str(client)
    assert SYNTHETIC_KEY[:16] not in repr(client)


def test_client_setup_failure_is_reported_without_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import anthropic

    def broken(**kwargs: object) -> object:
        raise ValueError(f"proxy misconfigured for {kwargs.get('api_key')}")

    monkeypatch.setattr(anthropic, "Anthropic", broken)
    with pytest.raises(pytest.fail.Exception) as info:
        make_client(SYNTHETIC_KEY)
    message = str(info.value)
    assert "ValueError" in message and SYNTHETIC_KEY not in message and "k7q2" not in message


def test_live_tool_use_request_accepted_and_parse_succeeds_on_smoke_case(
    tmp_path: Path, live_client: Any, record_property: Callable[[str, object], None]
) -> None:
    store = open_store(tmp_path / "live.db")
    run_id = store.insert_case_run(
        case_id="case-smoke",
        rules_version="bridge-v1",
        code_sha="live",
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
    )
    result = extract(load_case(SMOKE), live_client, store, run_id=run_id)
    attempt = store.attempt(result.source_attempt_id)
    record_property(
        "live",
        f"case-smoke model={attempt['model_returned']} input_tokens={attempt['input_tokens']} "
        f"output_tokens={attempt['output_tokens']} latency_ms={attempt['latency_ms']} "
        f"cost_usd={attempt['cost_usd']}",
    )
    # The API accepted the tool-use request (a rejection raises before any attempt is saved
    # as `response_saved`), the model called the tool, and its input parsed into
    # `Extraction`.
    assert result.source == "api"
    assert attempt["status"] == "parsed"
    saved = json.loads(attempt["response_json"])
    assert saved["stop_reason"] == "tool_use"
    assert [b["name"] for b in saved["content"] if b["type"] == "tool_use"] == [TOOL_NAME]
    assert result.extraction.bp_readings, "expected the synthetic BP reading"
    # The reservation's input bound (ADR 0001) holds for what the server actually billed:
    # the 2 000-token allowance for server-side wrapping is checked on every accepted call.
    request_bytes = len(attempt["request_json"].encode("utf-8"))
    assert attempt["input_tokens"] <= request_bytes + SERVER_INPUT_ALLOWANCE_TOKENS, (
        f"billed input {attempt['input_tokens']} exceeds the reservation bound "
        f"{request_bytes} + {SERVER_INPUT_ALLOWANCE_TOKENS}"
    )
