"""A scripted stand-in for `anthropic.Anthropic` used by tests and the offline CLI.

Each call to `messages.create` takes the next item of the script: a path to a raw
`Message` JSON file (returned as an `anthropic.types.Message`) or an exception instance
(raised). The last item repeats once the script is used up. Every call's kwargs and
options are recorded. Fixtures live in `fixtures/synthetic/extract/` and are hand-written;
they are not recorded model responses.

CLI: `BRIDGE_FAKE_CLIENT=1` (or `valid`) uses the valid reply; `no_tool_call`, `truncated`,
`refusal`, `timeout`, `server_error` and `bad_request` select a failure.

Fault injection (failure-recovery tests and `docs/recovery.md` only): with the fake client,
`BRIDGE_FAKE_FAULT=<boundary>` stops the run at that boundary as a killed process would
leave it. `before_response_saved` fires in the fake client after the request is recorded;
`after_response_saved` and `in_rules` fire in the store (`Store.fault_hook`). The fault is
an `InjectedFault`, a `BaseException`, so no pipeline handler records it and the run stays
`running` for the next check to recover. Without `BRIDGE_FAKE_CLIENT` the variable is
ignored: no production path ever has a hook.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import anthropic
import httpx2
from anthropic.types import Message

from bridge_check.manifest import CHECKOUT_ROOT

FIXTURE_DIR = CHECKOUT_ROOT / "fixtures" / "synthetic" / "extract"
ENV_VAR = "BRIDGE_FAKE_CLIENT"
FAULT_ENV = "BRIDGE_FAKE_FAULT"
FAULT_POINTS: tuple[str, ...] = ("before_response_saved", "after_response_saved", "in_rules")
_FAKE_URL = "https://fake.invalid/v1/messages"


def _request() -> httpx2.Request:
    return httpx2.Request("POST", _FAKE_URL)


def timeout_error() -> anthropic.APITimeoutError:
    return anthropic.APITimeoutError(request=_request())


def connection_error() -> anthropic.APIConnectionError:
    """A transport failure; the SDK raises the same class for a refused connection and for
    a dropped response, so the caller cannot know whether the request was received."""
    return anthropic.APIConnectionError(message="synthetic connection error", request=_request())


def status_error(code: int, error_type: str | None = None) -> anthropic.APIStatusError:
    """A synthetic HTTP error; `error_type` fills the API's `{"error": {"type": ...}}` body."""
    response = httpx2.Response(code, request=_request())
    cls: type[anthropic.APIStatusError]
    if code == 400:
        cls = anthropic.BadRequestError
    elif code == 429:
        cls = anthropic.RateLimitError
    elif code >= 500:
        cls = anthropic.InternalServerError
    else:
        cls = anthropic.APIStatusError
    body = {"type": "error", "error": {"type": error_type}} if error_type else None
    return cls(f"synthetic {code}", response=response, body=body)


class InjectedFault(BaseException):
    """A simulated kill at a named boundary. A `BaseException`, like `KeyboardInterrupt`,
    so the pipeline's `except Exception` handlers do not record it."""

    def __init__(self, point: str) -> None:
        super().__init__(point)
        self.point = point


def fault_point() -> str | None:
    """The boundary named by `BRIDGE_FAKE_FAULT`, only when the fake client is on."""
    if not os.environ.get(ENV_VAR, "").strip():
        return None
    name = os.environ.get(FAULT_ENV, "").strip()
    if not name:
        return None
    if name not in FAULT_POINTS:
        raise ValueError(f"{FAULT_ENV}: unknown boundary {name!r}")
    return name


def fault_hook() -> Callable[[str], None] | None:
    """A hook for `Store.fault_hook` that raises at the configured boundary, else None."""
    point = fault_point()
    if point is None:
        return None

    def hook(name: str) -> None:
        if name == point:
            raise InjectedFault(name)

    return hook


def fixture(name: str) -> Path:
    return FIXTURE_DIR / f"response_{name}.json"


def scenario(name: str) -> Path | BaseException:
    """A named script item for the CLI."""
    if name in ("1", "valid"):
        return fixture("valid")
    if name in ("no_tool_call", "truncated", "refusal"):
        return fixture(name)
    if name == "timeout":
        return timeout_error()
    if name == "server_error":
        return status_error(500)
    if name == "bad_request":
        return status_error(400)
    raise ValueError(f"{ENV_VAR}: unknown scenario {name!r}")


class _Messages:
    def __init__(self, owner: FakeClient) -> None:
        self._owner = owner

    def create(self, **kwargs: Any) -> Message:
        return self._owner._next(kwargs)


class FakeClient:
    def __init__(self, script: Sequence[Path | BaseException], fault: str | None = None) -> None:
        if not script:
            raise ValueError("script must not be empty")
        self.script = list(script)
        self.fault = fault
        self.calls: list[dict[str, Any]] = []
        self.options: list[dict[str, Any]] = []
        self.messages = _Messages(self)

    def with_options(self, **options: Any) -> FakeClient:
        self.options.append(options)
        return self

    def _next(self, kwargs: dict[str, Any]) -> Message:
        index = min(len(self.calls), len(self.script) - 1)
        self.calls.append(kwargs)
        if self.fault == "before_response_saved":
            raise InjectedFault(self.fault)
        item = self.script[index]
        if isinstance(item, BaseException):
            raise item
        data = json.loads(item.read_text(encoding="utf-8"))
        return Message.model_validate(data)
