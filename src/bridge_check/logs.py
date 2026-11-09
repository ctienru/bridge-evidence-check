"""Structured logs: one JSON object per line on stderr (contract §11).

Every line has exactly the keys in `LOG_KEYS`. `log_event` accepts only those keys, so no
document text, quote, offset or patient name can be attached to a log line: there is no
free-text field to put it in. Error details are logged as exception class names only.

The Anthropic SDK can log whole requests, including document text, when `ANTHROPIC_LOG`
is `debug` or `info`. `silence_sdk_logs()` caps the SDK and HTTP-client loggers at
WARNING; it runs whenever logging is configured and again before every extraction, so
that setting can never put document text on stderr. The `bridge_check` logger does not
propagate to the root logger (the SDK may install a plain-text root handler).
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any, TextIO

LOGGER_NAME = "bridge_check"
LOG_KEYS: tuple[str, ...] = (
    "ts",
    "level",
    "run_id",
    "case_id",
    "attempt_no",
    "stage",
    "event",
    "duration_ms",
    "error_type",
)
_FIELD_KEYS = frozenset(LOG_KEYS) - {"ts", "level", "event"}
_EXTRA = "bridge_fields"

logger = logging.getLogger(LOGGER_NAME)

SDK_LOGGER_PREFIXES: tuple[str, ...] = ("anthropic", "httpx", "httpcore")


def silence_sdk_logs() -> None:
    """Cap SDK and HTTP-client loggers at WARNING (they can log request bodies)."""
    names = [
        name
        for name in logging.root.manager.loggerDict
        if name.split(".")[0].startswith(SDK_LOGGER_PREFIXES)
    ]
    for name in {*names, "anthropic", "httpx2", "httpx"}:
        logging.getLogger(name).setLevel(logging.WARNING)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fields: dict[str, Any] = getattr(record, _EXTRA, {})
        line: dict[str, Any] = {k: None for k in LOG_KEYS}
        line.update(fields)
        line["ts"] = datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds")
        line["level"] = record.levelname
        line["event"] = record.getMessage()
        return json.dumps(line, ensure_ascii=False, separators=(",", ":"))


class _BridgeHandler(logging.StreamHandler[TextIO]):
    pass


def configure_logging(level: int = logging.INFO, stream: TextIO | None = None) -> None:
    """Send `bridge_check` logs to `stream` (default: the current stderr) as JSON lines.

    Idempotent: a previous handler installed here is replaced, not duplicated.
    """
    for h in list(logger.handlers):
        if isinstance(h, _BridgeHandler):
            logger.removeHandler(h)
    handler = _BridgeHandler(stream if stream is not None else sys.stderr)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    silence_sdk_logs()


def log_event(event: str, *, level: int = logging.INFO, **fields: Any) -> None:
    """Log `event` (a fixed snake_case name) with structured fields from `LOG_KEYS` only."""
    unknown = set(fields) - _FIELD_KEYS
    if unknown:
        raise TypeError(f"log fields not allowed: {sorted(unknown)}")
    for key, value in fields.items():
        if value is not None and not isinstance(value, int | float | str):
            raise TypeError(f"log field {key} must be a scalar")
    logger.log(level, event, extra={_EXTRA: fields})
