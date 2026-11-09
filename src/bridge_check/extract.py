"""Extraction call, attempt state machine and extraction cache (contract §7.2, §11).

Lookup order for every check:

1. `extractions` by cache key → `cache` (no API call);
2. the latest attempt with `status='response_saved'` for that key → parse the saved
   response again → `replay` (no API call, no new attempt row);
3. otherwise call the API → `api`.

Every attempt moves through `started` (committed before the request is sent) →
`response_saved` (the complete raw response is committed) → `parsed` | `parse_failed` |
`refused` | `truncated`; or `api_error`; or `unknown_outcome` (timeout or interrupt
before the response reached disk; cost NULL). `parsed` and the `extractions` row are one
transaction. No SQL write transaction is open while the request is in flight.

Retry budget per case run (contract §11, AGENTS.md): at most 4 API attempts (including
the first), of which at most 1 may end parse-class (`parse_failed`, `refused`,
`truncated`), and 5 minutes of wall clock. A parse-class outcome therefore ends the run
(`failed_stage=parse`); only API errors are retried. Planning 06 §2.5 allowed one retry
after a parse-class outcome; the contract wins. A failed replay is not an attempt of this
run and does not use that allowance. The wall clock is checked before each send, bounds
each request's timeout, and is checked again after the reply is classified and before
anything is marked parsed: a reply that arrives or finishes parsing after the budget is
kept (`response_saved`) and replayed by the next check.
The SDK's own retries are off (`max_retries=0`); this loop is the only retry layer
(AGENTS.md).

The raw response is saved and then validated with `Extraction.model_validate_json`;
`messages.parse()` is never used (AGENTS.md). Nothing here logs or stores document text
outside `attempts.request_json` / `response_json`: dead letters and log lines carry
exception class names, validation error types and field paths only.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anthropic
from pydantic import BaseModel, ValidationError

from bridge_check.input import LoadedCase, canonical_json, sha256_canonical
from bridge_check.logs import log_event, silence_sdk_logs
from bridge_check.manifest import CHECKOUT_ROOT
from bridge_check.schema import SCHEMA_VERSION, Extraction, extraction_json_schema
from bridge_check.store import Store
from bridge_check.text import read_doc

MODEL = "claude-sonnet-5-5"
PROMPT_VERSION = "extract-v1"
PROMPT_PATH = CHECKOUT_ROOT / "prompts" / f"{PROMPT_VERSION}.md"
MAX_TOKENS = 16000
THINKING: dict[str, str] = {"type": "adaptive"}

REQUEST_TIMEOUT_S = 60.0
"""Per-request timeout (06 §2.5). Not part of the cache key."""
MAX_ATTEMPTS = 4
MAX_PARSE_CLASS_ATTEMPTS = 1
WALL_CLOCK_S = 300.0
BACKOFF_BASE_S = 1.0

# USD per token, claude-sonnet-5-5 (06 §2.3, 2026-11-08).
PRICE_INPUT = 2.00 / 1_000_000
PRICE_OUTPUT = 10.00 / 1_000_000

_RETRYABLE_STATUS = frozenset({408, 409, 429})
_SAFE_TOKEN = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


def _model_fields(models: tuple[type[BaseModel], ...]) -> frozenset[str]:
    names: set[str] = set()
    for m in models:
        names.update(m.model_fields)
        for field in m.model_fields.values():
            args = getattr(field.annotation, "__args__", ())
            names.update(
                _model_fields(
                    tuple(a for a in args if isinstance(a, type) and issubclass(a, BaseModel))
                )
            )
    return frozenset(names)


_KNOWN_FIELDS = _model_fields((Extraction,))


class ExtractionFailed(Exception):
    """The retry budget is spent or the error cannot be retried.

    `stage` is `extract` (API side) or `parse` (the reply was unusable).
    """

    def __init__(self, stage: str, error_type: str, message: str) -> None:
        super().__init__(f"{stage}: {error_type}: {message}")
        self.stage = stage
        self.error_type = error_type
        self.message = message


@dataclass(frozen=True)
class ExtractResult:
    extraction_id: int
    source: str  # cache | replay | api
    cache_key: str
    source_attempt_id: int
    extraction: Extraction


@dataclass(frozen=True)
class Outcome:
    """What one saved response turned out to be."""

    status: str  # parsed | parse_failed | refused | truncated
    extraction: Extraction | None = None
    error_type: str | None = None
    fact_path: str | None = None
    message: str | None = None


# --- Request ---------------------------------------------------------------------------------


def load_system_prompt(path: Path = PROMPT_PATH) -> str:
    return read_doc(path)


def render_document(doc_id: str, role: str, text: str) -> str:
    """One document as sent to the model: its `doc_id` and `role`, then the full text."""
    return f'<document doc_id="{doc_id}" role="{role}">\n{text}\n</document>'


def build_request(case: LoadedCase, system: str) -> dict[str, Any]:
    """Exactly the kwargs passed to `messages.create` (and hashed into the cache key).

    Only documents with their `doc_id` and `role` are sent; `primary_patient`,
    `assessment_date` and `target_course` never are (contract §7.1).
    """
    refs = sorted(case.input.documents, key=lambda d: d.doc_id)
    content = [
        {"type": "text", "text": render_document(r.doc_id, r.role, case.texts[r.doc_id])}
        for r in refs
    ]
    return {
        "model": MODEL,
        "system": system,
        "messages": [{"role": "user", "content": content}],
        "output_config": {"format": {"type": "json_schema", "schema": extraction_json_schema()}},
        "max_tokens": MAX_TOKENS,
        "thinking": dict(THINKING),
    }


def cache_key(request_kwargs: dict[str, Any]) -> str:
    """`sha256(canonical_json(request_kwargs))`. Timeout, retry settings and metadata are
    never in `request_kwargs` (contract §11)."""
    return sha256_canonical(request_kwargs)


# --- Response classification ----------------------------------------------------------------


def _safe_path(loc: tuple[int | str, ...]) -> str | None:
    """A validation error location with only indices and schema field names."""
    parts = [str(p) if isinstance(p, int) or p in _KNOWN_FIELDS else "?" for p in loc]
    return ".".join(parts) or None


def classify_response(resp: dict[str, Any]) -> Outcome:
    """Classify a saved raw response (a plain dict, as stored in `response_json`)."""
    stop = resp.get("stop_reason")
    if stop == "refusal":
        details = resp.get("stop_details") or {}
        category = details.get("category") if isinstance(details, dict) else None
        cat = category if isinstance(category, str) and _SAFE_TOKEN.match(category) else None
        return Outcome(
            "refused", error_type="Refusal", message=f"stop_reason=refusal category={cat}"
        )
    if stop in ("max_tokens", "model_context_window_exceeded"):
        return Outcome("truncated", error_type="Truncated", message=f"stop_reason={stop}")
    blocks = resp.get("content") or []
    texts = [
        str(b.get("text", "")) for b in blocks if isinstance(b, dict) and b.get("type") == "text"
    ]
    if not texts:
        return Outcome("parse_failed", error_type="NoTextBlock", message="reply has no text block")
    try:
        extraction = Extraction.model_validate_json("".join(texts))
    except ValidationError as exc:
        errors = exc.errors(include_url=False, include_context=False, include_input=False)
        types = sorted({str(e["type"]) for e in errors})
        error_type = "JSONDecodeError" if "json_invalid" in types else "ValidationError"
        return Outcome(
            "parse_failed",
            error_type=error_type,
            fact_path=_safe_path(tuple(errors[0]["loc"])) if errors else None,
            message=f"{len(errors)} validation error(s): {', '.join(types)}",
        )
    return Outcome("parsed", extraction=extraction)


def _cost(input_tokens: int | None, output_tokens: int | None) -> float | None:
    if input_tokens is None or output_tokens is None:
        return None
    return round(input_tokens * PRICE_INPUT + output_tokens * PRICE_OUTPUT, 6)


def _dump(message: Any) -> dict[str, Any]:
    dump = getattr(message, "model_dump", None)
    if callable(dump):
        result: dict[str, Any] = dump(mode="json")
        return result
    if isinstance(message, dict):
        return message
    raise TypeError("client returned an object that is not a Message")


# --- The loop --------------------------------------------------------------------------------


class _Run:
    """State for one call of `extract`."""

    def __init__(
        self,
        case: LoadedCase,
        client: Any,
        store: Store,
        run_id: int,
        sleep: Callable[[float], None],
        clock: Callable[[], float],
    ) -> None:
        self.case = case
        self.client = client
        self.store = store
        self.run_id = run_id
        self.sleep = sleep
        self.clock = clock
        self.t0 = clock()
        self.parse_class_failures = 0
        self.api_errors = 0

    def ms_since(self, t: float) -> int:
        return int((self.clock() - t) * 1000)

    def log(self, event: str, level: int = logging.INFO, **fields: Any) -> None:
        log_event(event, level=level, run_id=self.run_id, case_id=self.case.case_id, **fields)

    def finish(
        self, attempt_id: int, attempt_no: int | None, key: str, outcome: Outcome
    ) -> int | None:
        """Record the outcome of a saved response; the extraction id when parsed."""
        if outcome.status == "parsed":
            assert outcome.extraction is not None
            extraction_id = self.store.mark_parsed(
                attempt_id,
                cache_key=key,
                parsed_json=outcome.extraction.model_dump_json(),
                schema_version=SCHEMA_VERSION,
                prompt_version=PROMPT_VERSION,
            )
            self.log("attempt_parsed", attempt_no=attempt_no, stage="parse")
            return extraction_id
        self.store.set_attempt_status(
            attempt_id, outcome.status, error_type=outcome.error_type, error=outcome.message
        )
        self.store.insert_dead_letter(
            case_run_id=self.run_id,
            attempt_id=attempt_id,
            stage="parse",
            error_type=outcome.error_type or "ParseError",
            fact_path=outcome.fact_path,
            message=outcome.message or outcome.status,
        )
        if attempt_no is not None:  # a replay is not an attempt of this run
            self.parse_class_failures += 1
        self.log(
            f"attempt_{outcome.status}",
            level=logging.WARNING,
            attempt_no=attempt_no,
            stage="parse",
            error_type=outcome.error_type,
        )
        return None

    def api_failure(
        self, attempt_id: int, attempt_no: int, status: str, exc: BaseException, t_req: float
    ) -> None:
        error_type = type(exc).__name__
        code = getattr(exc, "status_code", None)
        message = f"{error_type} status={code}" if code is not None else error_type
        self.store.set_attempt_status(
            attempt_id,
            status,
            error_type=error_type,
            error=message,
            latency_ms=self.ms_since(t_req),
        )
        self.store.insert_dead_letter(
            case_run_id=self.run_id,
            attempt_id=attempt_id,
            stage="extract",
            error_type=error_type,
            message=message,
        )
        self.log(
            f"attempt_{status}",
            level=logging.WARNING,
            attempt_no=attempt_no,
            stage="extract",
            duration_ms=self.ms_since(t_req),
            error_type=error_type,
        )

    def remaining(self) -> float:
        return WALL_CLOCK_S - (self.clock() - self.t0)


def extract(
    inp: LoadedCase,
    client: Any,
    store: Store,
    *,
    run_id: int,
    system_prompt: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> ExtractResult:
    """Return the extraction for `inp`: from the cache, by replay, or from the API."""
    silence_sdk_logs()
    run = _Run(inp, client, store, run_id, sleep, clock)
    request = build_request(
        inp, system_prompt if system_prompt is not None else load_system_prompt()
    )
    key = cache_key(request)

    hit = store.find_extraction(key)
    if hit is not None:
        run.log("extract_cache_hit", stage="extract")
        return ExtractResult(
            int(hit["id"]),
            "cache",
            key,
            int(hit["attempt_id"]),
            Extraction.model_validate_json(hit["parsed_json"]),
        )

    saved = store.latest_response_saved(key)
    if saved is not None:
        run.log("extract_replay", stage="parse")
        outcome = classify_response(json.loads(saved.response_json))
        extraction_id = run.finish(saved.id, None, key, outcome)
        if extraction_id is not None:
            assert outcome.extraction is not None
            return ExtractResult(extraction_id, "replay", key, saved.id, outcome.extraction)

    return _call_api(run, request, key)


def _call_api(run: _Run, request: dict[str, Any], key: str) -> ExtractResult:
    store = run.store
    request_json = canonical_json(request)
    attempt_no = 0
    last = ("extract", "NoAttempt")
    while True:
        if run.parse_class_failures >= MAX_PARSE_CLASS_ATTEMPTS:
            raise ExtractionFailed("parse", last[1], "parse-class attempt budget spent")
        if attempt_no >= MAX_ATTEMPTS:
            raise ExtractionFailed(last[0], last[1], f"attempt budget spent ({MAX_ATTEMPTS})")
        if run.remaining() <= 0:
            raise ExtractionFailed(
                last[0], "WallClockExceeded", f"{WALL_CLOCK_S:.0f}s budget spent"
            )
        attempt_no += 1
        attempt_id = store.insert_attempt(
            case_run_id=run.run_id, cache_key=key, attempt_no=attempt_no, request_json=request_json
        )
        run.log("attempt_started", attempt_no=attempt_no, stage="extract")
        t_req = run.clock()
        timeout = max(0.001, min(REQUEST_TIMEOUT_S, run.remaining()))
        try:
            message = run.client.with_options(timeout=timeout, max_retries=0).messages.create(
                **request
            )
        except KeyboardInterrupt as exc:
            run.api_failure(attempt_id, attempt_no, "unknown_outcome", exc, t_req)
            raise
        except anthropic.APITimeoutError as exc:
            run.api_failure(attempt_id, attempt_no, "unknown_outcome", exc, t_req)
            last = ("extract", type(exc).__name__)
            _backoff(run, attempt_no)
            continue
        except anthropic.APIConnectionError as exc:
            run.api_failure(attempt_id, attempt_no, "api_error", exc, t_req)
            last = ("extract", type(exc).__name__)
            _backoff(run, attempt_no)
            continue
        except anthropic.APIStatusError as exc:
            run.api_failure(attempt_id, attempt_no, "api_error", exc, t_req)
            last = ("extract", type(exc).__name__)
            if exc.status_code in _RETRYABLE_STATUS or exc.status_code >= 500:
                _backoff(run, attempt_no)
                continue
            raise ExtractionFailed(
                "extract", last[1], f"status={exc.status_code}, not retried"
            ) from None
        except Exception as exc:  # noqa: BLE001 - recorded, then the run fails
            run.api_failure(attempt_id, attempt_no, "api_error", exc, t_req)
            raise ExtractionFailed(
                "extract", type(exc).__name__, "unexpected client error"
            ) from None

        latency = run.ms_since(t_req)
        resp = _dump(message)
        usage = resp.get("usage") or {}
        in_tok = usage.get("input_tokens")
        out_tok = usage.get("output_tokens")
        store.save_response(
            attempt_id,
            response_json=json.dumps(resp, ensure_ascii=False, sort_keys=True),
            model_returned=resp.get("model"),
            latency_ms=latency,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=_cost(in_tok, out_tok),
        )
        run.log(
            "attempt_response_saved", attempt_no=attempt_no, stage="extract", duration_ms=latency
        )
        outcome = classify_response(resp)
        if run.remaining() < 0:
            # Over budget (late reply or slow parse): nothing is marked parsed; the attempt
            # stays `response_saved` and the next check replays it.
            store.insert_dead_letter(
                case_run_id=run.run_id,
                attempt_id=attempt_id,
                stage="extract",
                error_type="WallClockExceeded",
                message="time budget spent before the reply was processed; kept for replay",
            )
            run.log(
                "extract_over_budget",
                attempt_no=attempt_no,
                stage="extract",
                error_type="WallClockExceeded",
            )
            raise ExtractionFailed(
                "extract", "WallClockExceeded", "time budget spent before the reply was processed"
            )
        extraction_id = run.finish(attempt_id, attempt_no, key, outcome)
        if extraction_id is not None:
            assert outcome.extraction is not None
            return ExtractResult(extraction_id, "api", key, attempt_id, outcome.extraction)
        last = ("parse", outcome.error_type or "ParseError")


def _backoff(run: _Run, attempt_no: int) -> None:
    """Exponential backoff between retryable API errors, bounded by the wall clock.
    No wait after the last allowed attempt."""
    run.api_errors += 1
    if attempt_no >= MAX_ATTEMPTS:
        return
    delay = min(BACKOFF_BASE_S * 2 ** (run.api_errors - 1), max(run.remaining(), 0.0))
    if delay > 0:
        run.sleep(delay)
