"""Minimal OpenAI wrapper shared by the two data-side scripts.

The data-side model (`gpt-6.1-sol`, planning 05 §5.2) drafts authored documents and
proposes candidates; its output never enters the pipeline. `openai` lives in the optional
`data` dependency group and is imported lazily, so tests, CI and the pipeline never need
it. SDK retries are disabled (`max_retries=0`, AGENTS.md). The key is read from
`OPENAI_API_KEY` or, failing that, from a `.env` file with `KEY=value` lines.

API choice. The project contract and planning documents specify Chat Completions, and
the SDK's `chat.completions.create` is what the recorded request kwargs describe; the
Responses API is not used so the data side and the extractor (Anthropic Messages) stay
one-call-one-record alike. The default model is a reasoning model and rejects sampling
parameters: sending `temperature=0` returned, observed live on 2026-11-08,
`BadRequestError: Error code: 400 - Unsupported value: 'temperature' does not support 0
with this model. Only the default (1) value is supported.` so no `temperature` is sent
(the original requirement said temperature 0).

Output format. Every call uses structured output: `response_format` of type
`json_schema` with `strict: true` and a schema built by the caller (`drafting.py`,
`candidates.py`), not plain "return JSON" prompting. `chat_json` returns the raw content
string so the caller archives it (private repo) before parsing or validating anything.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ENV_VAR = "OPENAI_API_KEY"
DEFAULT_MODEL = "gpt-6.1-sol"
EXIT_NO_KEY = 2


@dataclass(frozen=True)
class RawReply:
    """What the SDK returned, before any parsing.

    `response` is the complete SDK object as a plain dict (or its string form); it is
    archived first, so a reply with no choices or an odd shape is still recorded.
    """

    model: str
    finish_reason: str | None
    refusal: str | None
    content: str
    response: Any

    def as_record(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "finish_reason": self.finish_reason,
            "refusal": self.refusal,
            "content": self.content,
            "response": self.response,
        }

    def problem(self) -> str | None:
        """Why the reply cannot be parsed (`no_choices`, `refused`, `content_filter`,
        `truncated`, `empty`), or None."""
        if self.finish_reason in ("no_choices", "malformed"):
            return self.finish_reason
        if self.refusal:
            return "refused"
        if self.finish_reason == "content_filter":
            return "content_filter"
        if self.finish_reason == "length":
            return "truncated"
        if not self.content.strip():
            return "empty"
        return None


def read_api_key(dotenv: Path = Path(".env")) -> str | None:
    """`OPENAI_API_KEY` from the environment, else from `dotenv`; None when absent."""
    value = os.environ.get(ENV_VAR, "").strip()
    if value:
        return value
    if not dotenv.is_file():
        return None
    for line in dotenv.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, raw = line.partition("=")
        if key.strip() == ENV_VAR:
            value = raw.strip().strip("'\"")
            return value or None
    return None


def make_client(api_key: str) -> Any:
    """An OpenAI client with SDK retries disabled. Imported here so `openai` stays optional."""
    from openai import OpenAI

    return OpenAI(api_key=api_key, max_retries=0)


def json_schema_format(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    """`response_format` for strict structured output."""
    return {
        "type": "json_schema",
        "json_schema": {"name": name, "strict": True, "schema": schema},
    }


def chat_json(
    client: Any, model: str, messages: list[dict[str, str]], response_format: dict[str, Any]
) -> RawReply:
    """One chat completion with structured output. No `temperature` (module docstring)."""
    completion = client.chat.completions.create(
        model=model,
        messages=messages,
        response_format=response_format,
    )
    dump = getattr(completion, "model_dump", None)
    response: Any = dump(mode="json") if callable(dump) else repr(completion)
    model = str(getattr(completion, "model", ""))
    try:
        choices = list(getattr(completion, "choices", None) or [])
        if not choices:
            return RawReply(model, "no_choices", None, "", response)
        choice = choices[0]
        message = choice.message
        return RawReply(
            model=model,
            finish_reason=getattr(choice, "finish_reason", None),
            refusal=getattr(message, "refusal", None),
            content=message.content or "",
            response=response,
        )
    except Exception:  # noqa: BLE001 - odd shapes are archived, then reported as malformed
        return RawReply(model, "malformed", None, "", response)
