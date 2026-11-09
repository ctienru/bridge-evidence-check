"""Extraction: cache key, lookup order, attempt state machine, retry budget (contract §11).

Every test uses `FakeClient` fed from `fixtures/synthetic/extract/`; no network.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from bridge_check.extract import (
    MAX_ATTEMPTS,
    MODEL,
    ExtractionFailed,
    build_request,
    cache_key,
    classify_response,
    extract,
    load_system_prompt,
)
from bridge_check.fake_client import FakeClient, fixture, status_error, timeout_error
from bridge_check.input import LoadedCase, canonical_json, load_case
from bridge_check.store import Store, open_store

ROOT = Path(__file__).resolve().parent.parent
SMOKE = ROOT / "fixtures" / "synthetic" / "case-smoke"
VALID = fixture("valid")
BAD_JSON = fixture("bad_json")
SCHEMA_VIOLATION = fixture("schema_violation")
TRUNCATED = fixture("truncated")
REFUSAL = fixture("refusal")


class Clock:
    """A fake monotonic clock; `sleep` advances it."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def case() -> LoadedCase:
    return load_case(SMOKE)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    s = open_store(tmp_path / "t.db")
    yield s
    s.close()


def _run(store: Store) -> int:
    return store.insert_case_run(
        case_id="case-smoke",
        rules_version="bridge-v1",
        code_sha="test",
        prompt_version="extract-v1",
        schema_version="v1",
    )


def _extract(case: LoadedCase, client: FakeClient, store: Store, clock: Clock | None = None) -> Any:
    clock = clock or Clock()
    return extract(case, client, store, run_id=_run(store), sleep=clock.sleep, clock=clock)


def _statuses(store: Store) -> list[str]:
    rows = store.conn.execute("SELECT status FROM attempts ORDER BY id").fetchall()
    return [str(r[0]) for r in rows]


# --- request and cache key ---------------------------------------------------------------------


def test_request_kwargs_are_exactly_the_contract_set(case: LoadedCase) -> None:
    req = build_request(case, load_system_prompt())
    assert set(req) == {"model", "system", "messages", "output_config", "max_tokens", "thinking"}
    assert req["model"] == MODEL == "claude-sonnet-5-5"
    assert req["thinking"] == {"type": "adaptive"}
    assert req["output_config"]["format"]["type"] == "json_schema"
    assert "temperature" not in req


def test_request_sends_documents_with_doc_id_and_role_only(case: LoadedCase) -> None:
    req = build_request(case, load_system_prompt())
    sent = canonical_json(req)
    blocks = req["messages"][0]["content"]
    assert [b["text"].split('"')[1] for b in blocks] == sorted(case.texts)
    joined = "".join(b["text"] for b in blocks)
    for doc_id, text in case.texts.items():
        assert text in joined, doc_id
    # Identity and timepoints are compared by the program, never sent (contract §7.1).
    # (The date of birth is not checked: the synthetic referral itself states it.)
    for hidden in (case.input.primary_patient.name, case.input.assessment_date.isoformat()):
        assert hidden not in sent
    assert "primary_patient" not in sent and "target_course" not in sent


def test_prompt_never_mentions_hidden_input_fields() -> None:
    prompt = load_system_prompt()
    for name in ("primary_patient", "assessment_date", "target_course"):
        assert name not in prompt


def test_cache_key_is_stable_under_dict_order(case: LoadedCase) -> None:
    req = build_request(case, "prompt")
    reordered = dict(reversed(list(req.items())))
    reordered["output_config"] = {
        "format": dict(reversed(list(req["output_config"]["format"].items())))
    }
    assert cache_key(req) == cache_key(reordered)
    assert cache_key(req) == cache_key(build_request(case, "prompt"))


def test_cache_key_changes_with_prompt(case: LoadedCase) -> None:
    assert cache_key(build_request(case, "prompt a")) != cache_key(build_request(case, "prompt b"))


def test_cache_key_changes_with_role(case: LoadedCase) -> None:
    docs = [
        d.model_copy(update={"role": "clinical"}) if d.doc_id == "D1-referral" else d
        for d in case.input.documents
    ]
    other = LoadedCase(
        case.case_dir,
        case.input.model_copy(update={"documents": docs}),
        case.texts,
        case.doc_sha256,
    )
    assert cache_key(build_request(case, "p")) != cache_key(build_request(other, "p"))


def test_cache_key_changes_with_document_text(case: LoadedCase) -> None:
    texts = {**case.texts, "D2-clinical": case.texts["D2-clinical"] + " "}
    other = LoadedCase(case.case_dir, case.input, texts, case.doc_sha256)
    assert cache_key(build_request(case, "p")) != cache_key(build_request(other, "p"))


def test_timeout_and_retries_are_options_not_request_kwargs(case: LoadedCase, store: Store) -> None:
    client = FakeClient([VALID])
    _extract(case, client, store)
    assert "timeout" not in client.calls[0] and "max_retries" not in client.calls[0]
    assert client.options[0]["max_retries"] == 0
    assert client.options[0]["timeout"] > 0
    stored = store.conn.execute("SELECT request_json, cache_key FROM attempts").fetchone()
    assert cache_key(json.loads(stored[0])) == stored[1]


# --- lookup order --------------------------------------------------------------------------------


def test_valid_reply_goes_started_saved_parsed(case: LoadedCase, store: Store) -> None:
    result = _extract(case, FakeClient([VALID]), store)
    assert result.source == "api"
    assert _statuses(store) == ["parsed"]
    row = store.attempt(result.source_attempt_id)
    assert row["response_json"] is not None and row["model_returned"] == "claude-sonnet-5-5"
    assert row["cost_usd"] == pytest.approx(5200 * 2e-6 + 1400 * 10e-6)
    assert store.count("extractions") == 1
    assert store.count("dead_letters") == 0


def test_second_run_is_a_cache_hit_without_api_call(case: LoadedCase, store: Store) -> None:
    first = _extract(case, FakeClient([VALID]), store)
    client = FakeClient([VALID])
    second = _extract(case, client, store)
    assert second.source == "cache"
    assert second.extraction_id == first.extraction_id
    assert client.calls == []
    assert store.count("attempts") == 1


def test_saved_response_is_replayed_without_api_call(case: LoadedCase, store: Store) -> None:
    # Scenario (a): the raw response reached disk, the process died before parsing.
    first = _extract(case, FakeClient([VALID]), store)
    store.conn.execute("DELETE FROM extractions")
    store.conn.execute(
        "UPDATE attempts SET status = 'response_saved' WHERE id = ?", (first.source_attempt_id,)
    )
    client = FakeClient([VALID])
    replayed = _extract(case, client, store)
    assert replayed.source == "replay"
    assert replayed.source_attempt_id == first.source_attempt_id
    assert client.calls == []
    assert store.count("attempts") == 1
    assert _statuses(store) == ["parsed"]
    assert store.count("extractions") == 1


def test_terminal_parse_failed_is_not_replayed(case: LoadedCase, store: Store) -> None:
    with pytest.raises(ExtractionFailed):
        _extract(case, FakeClient([BAD_JSON]), store)
    client = FakeClient([VALID])
    result = _extract(case, client, store)
    assert result.source == "api"
    assert len(client.calls) == 1


def test_failed_replay_falls_through_to_the_api(case: LoadedCase, store: Store) -> None:
    run_id = _run(store)
    key = cache_key(build_request(case, load_system_prompt()))
    aid = store.insert_attempt(case_run_id=run_id, cache_key=key, attempt_no=1, request_json="{}")
    store.save_response(
        aid,
        response_json=BAD_JSON.read_text(encoding="utf-8"),
        model_returned="m",
        latency_ms=1,
        input_tokens=1,
        output_tokens=1,
        cost_usd=0.0,
    )
    client = FakeClient([VALID])
    result = _extract(case, client, store)
    assert result.source == "api"
    assert len(client.calls) == 1
    assert store.attempt(aid)["status"] == "parse_failed"


# --- state machine and budget


def test_bad_json_ends_the_run_without_retry(case: LoadedCase, store: Store) -> None:
    # Contract §11 / AGENTS.md: at most one parse-class attempt per case run.
    client = FakeClient([BAD_JSON, VALID])
    with pytest.raises(ExtractionFailed) as info:
        _extract(case, client, store)
    assert info.value.stage == "parse"
    assert info.value.error_type == "JSONDecodeError"
    assert len(client.calls) == 1
    assert _statuses(store) == ["parse_failed"]
    letters = store.conn.execute("SELECT stage, error_type FROM dead_letters").fetchall()
    assert [tuple(r) for r in letters] == [("parse", "JSONDecodeError")]
    assert store.count("extractions") == 0


def test_schema_violation_records_field_path(case: LoadedCase, store: Store) -> None:
    with pytest.raises(ExtractionFailed):
        _extract(case, FakeClient([SCHEMA_VIOLATION, VALID]), store)
    assert _statuses(store) == ["parse_failed"]
    letter = store.conn.execute("SELECT fact_path, message FROM dead_letters").fetchone()
    assert letter[0] == "bp_readings.0.sbp"
    assert "int_type" in letter[1] or "int_parsing" in letter[1]


@pytest.mark.parametrize(("reply", "status"), [(TRUNCATED, "truncated"), (REFUSAL, "refused")])
def test_truncated_and_refused_are_parse_class(
    case: LoadedCase, store: Store, reply: Path, status: str
) -> None:
    client = FakeClient([reply, VALID])
    with pytest.raises(ExtractionFailed) as info:
        _extract(case, client, store)
    assert info.value.stage == "parse"
    assert _statuses(store) == [status]
    assert len(client.calls) == 1


def test_timeout_is_unknown_outcome_with_null_cost(case: LoadedCase, store: Store) -> None:
    result = _extract(case, FakeClient([timeout_error(), VALID]), store)
    assert result.source == "api"
    rows = store.conn.execute("SELECT status, cost_usd, error_type FROM attempts").fetchall()
    assert tuple(rows[0]) == ("unknown_outcome", None, "APITimeoutError")
    assert rows[1][0] == "parsed"


def test_attempt_budget_is_four(case: LoadedCase, store: Store) -> None:
    clock = Clock()
    client = FakeClient([timeout_error()])
    with pytest.raises(ExtractionFailed) as info:
        _extract(case, client, store, clock)
    assert info.value.stage == "extract"
    assert len(client.calls) == MAX_ATTEMPTS == 4
    assert _statuses(store) == ["unknown_outcome"] * 4
    assert clock.sleeps == [1.0, 2.0, 4.0]  # no wait after the last attempt


def test_server_errors_are_retried(case: LoadedCase, store: Store) -> None:
    result = _extract(case, FakeClient([status_error(500), status_error(429), VALID]), store)
    assert result.source == "api"
    assert _statuses(store) == ["api_error", "api_error", "parsed"]


def test_bad_request_is_not_retried(case: LoadedCase, store: Store) -> None:
    client = FakeClient([status_error(400), VALID])
    with pytest.raises(ExtractionFailed) as info:
        _extract(case, client, store)
    assert info.value.stage == "extract"
    assert info.value.error_type == "BadRequestError"
    assert len(client.calls) == 1
    letter = store.conn.execute("SELECT stage, error_type, message FROM dead_letters").fetchone()
    assert tuple(letter) == ("extract", "BadRequestError", "BadRequestError status=400")


def test_parse_class_limit_inside_attempt_budget(case: LoadedCase, store: Store) -> None:
    client = FakeClient([status_error(500), BAD_JSON, VALID])
    with pytest.raises(ExtractionFailed) as info:
        _extract(case, client, store)
    assert info.value.stage == "parse"
    assert len(client.calls) == 2
    assert _statuses(store) == ["api_error", "parse_failed"]


def test_failed_replay_then_failed_api_attempt_stops(case: LoadedCase, store: Store) -> None:
    run_id = _run(store)
    key = cache_key(build_request(case, load_system_prompt()))
    aid = store.insert_attempt(case_run_id=run_id, cache_key=key, attempt_no=1, request_json="{}")
    store.save_response(
        aid,
        response_json=BAD_JSON.read_text(encoding="utf-8"),
        model_returned="m",
        latency_ms=1,
        input_tokens=1,
        output_tokens=1,
        cost_usd=0.0,
    )
    client = FakeClient([BAD_JSON, VALID])
    with pytest.raises(ExtractionFailed) as info:
        _extract(case, client, store)
    assert info.value.stage == "parse"
    assert len(client.calls) == 1


def test_response_after_the_wall_clock_is_kept_for_replay(case: LoadedCase, store: Store) -> None:
    clock = Clock()

    class LateClient(FakeClient):
        def _next(self, kwargs: dict[str, Any]) -> Any:
            clock.now += 301.0
            return super()._next(kwargs)

    with pytest.raises(ExtractionFailed) as info:
        _extract(case, LateClient([VALID]), store, clock)
    assert info.value.error_type == "WallClockExceeded"
    assert _statuses(store) == ["response_saved"]
    assert store.count("extractions") == 0
    client = FakeClient([VALID])
    replayed = _extract(case, client, store)
    assert replayed.source == "replay"
    assert client.calls == []


def test_parse_finishing_after_the_wall_clock_is_not_marked_parsed(
    case: LoadedCase, store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The reply arrives at 299 s; classification ends at 301 s.
    import bridge_check.extract as extract_module

    clock = Clock()
    real_classify = extract_module.classify_response

    def slow_classify(resp: dict[str, Any]) -> Any:
        clock.now += 2.0
        return real_classify(resp)

    class AlmostLateClient(FakeClient):
        def _next(self, kwargs: dict[str, Any]) -> Any:
            clock.now += 299.0
            return super()._next(kwargs)

    monkeypatch.setattr(extract_module, "classify_response", slow_classify)
    with pytest.raises(ExtractionFailed) as info:
        _extract(case, AlmostLateClient([VALID]), store, clock)
    assert info.value.error_type == "WallClockExceeded"
    assert _statuses(store) == ["response_saved"]
    assert store.count("extractions") == 0
    monkeypatch.setattr(extract_module, "classify_response", real_classify)
    client = FakeClient([VALID])
    assert _extract(case, client, store).source == "replay"
    assert client.calls == []


def test_wall_clock_budget(case: LoadedCase, store: Store) -> None:
    clock = Clock()

    class SlowClient(FakeClient):
        def _next(self, kwargs: dict[str, Any]) -> Any:
            clock.now += 200.0
            return super()._next(kwargs)

    client = SlowClient([timeout_error()])
    with pytest.raises(ExtractionFailed) as info:
        _extract(case, client, store, clock)
    assert info.value.error_type == "WallClockExceeded"
    assert len(client.calls) == 2
    assert all(o["timeout"] <= 60 for o in client.options)


def test_interrupt_marks_unknown_outcome_and_reraises(case: LoadedCase, store: Store) -> None:
    with pytest.raises(KeyboardInterrupt):
        _extract(case, FakeClient([KeyboardInterrupt()]), store)
    assert _statuses(store) == ["unknown_outcome"]
    assert store.attempt(1)["cost_usd"] is None


# --- classification never echoes text


def test_classification_messages_carry_no_reply_text() -> None:
    secret = "SENTINEL-classify-91c2"
    resp = {
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": '{"' + secret + '": 1}'}],
    }
    out = classify_response(resp)
    assert out.status == "parse_failed"
    assert secret not in (out.message or "") and secret not in (out.fact_path or "")
    assert out.fact_path == "?"
