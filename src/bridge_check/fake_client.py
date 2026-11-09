"""A scripted stand-in for `anthropic.Anthropic` used by tests and the offline CLI.

Each call to `messages.create` takes the next item of the script: a path to a raw
`Message` JSON file (returned as an `anthropic.types.Message`) or an exception instance
(raised). The last item repeats once the script is used up. Every call's kwargs and
options are recorded. Fixtures live in `fixtures/synthetic/extract/` and are hand-written;
they are not recorded model responses.

CLI: `BRIDGE_FAKE_CLIENT=1` (or `valid`) uses the valid reply; `bad_json`, `truncated`,
`refusal`, `timeout`, `server_error` and `bad_request` select a failure.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import anthropic
import httpx2
from anthropic.types import Message

from bridge_check.manifest import CHECKOUT_ROOT

FIXTURE_DIR = CHECKOUT_ROOT / "fixtures" / "synthetic" / "extract"
ENV_VAR = "BRIDGE_FAKE_CLIENT"
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


def fixture(name: str) -> Path:
    return FIXTURE_DIR / f"response_{name}.json"


def scenario(name: str) -> Path | BaseException:
    """A named script item for the CLI."""
    if name in ("1", "valid"):
        return fixture("valid")
    if name in ("bad_json", "truncated", "refusal"):
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
    def __init__(self, script: Sequence[Path | BaseException]) -> None:
        if not script:
            raise ValueError("script must not be empty")
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []
        self.options: list[dict[str, Any]] = []
        self.messages = _Messages(self)

    def with_options(self, **options: Any) -> FakeClient:
        self.options.append(options)
        return self

    def _next(self, kwargs: dict[str, Any]) -> Message:
        index = min(len(self.calls), len(self.script) - 1)
        self.calls.append(kwargs)
        item = self.script[index]
        if isinstance(item, BaseException):
            raise item
        data = json.loads(item.read_text(encoding="utf-8"))
        return Message.model_validate(data)
