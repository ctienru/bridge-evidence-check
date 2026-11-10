"""Public replay files (contract §11): `export_public_run()` and its inverse.

A replay is the extraction of one recorded API response, exported through an allow-list so
it can be committed and re-run offline. What leaves the store:

- a header: variant, input hash, prompt and schema versions, the requested and returned
  model, the first 8 hex digits of the cache key, the source attempt's status, timestamps,
  tokens, latency, cost and stop reason, and the sha256 of every input document;
- the extraction, fact by fact, with every `quote` replaced by its position:
  `{start, end, sha256, replay_fidelity}`, plus `text` for documents that are not
  MTSamples (their text is public anyway). MTSamples text never appears: a verbatim quote
  is restored from its offsets (`exact`); a normalized, candidate or unlocated quote is
  `lossy` (normalized keeps its offsets; the others restore to the
  `UNLOCATABLE_PREFIX + sha8` placeholder, which verify reports as not found).
  On MTSamples documents the free-text fields of `HASHED_TEXT_KEYS` are replaced by their
  sha256 and restore to "" (or null).

Nothing else of the raw response or of the request is read: no system prompt, no messages,
no thinking block, no tool-use id.

`export_public_report()` is the gate for the evaluation report (`bridge eval`): a
structural allow-list rather than a field list. Every key and every string value must be
an id, an enum value, a version, a relative path, a date, a hash or an evidence reference
`doc_id[start:end] sha8`; a string with any other shape (free text has spaces or
punctuation these patterns refuse) raises `ExportError`, so no quote, name or note can
leave through it.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from bridge_check.enums import EXTRACTION_FIELDS, MTSAMPLES_DOC_ID_PREFIX
from bridge_check.schema import Extraction
from bridge_check.store import Store
from bridge_check.text import sha256_hex

REPLAY_VERSION = 1
UNLOCATABLE_PREFIX = "\x00UNLOCATABLE:"
HASHED_TEXT_KEYS: dict[str, tuple[str, ...]] = {
    "patient_identity": ("name", "patient_id", "dob"),
    "medications": ("indication",),
    "medication_lists": ("section_title",),
    "lifestyle": ("limitation", "description"),
}
"""Free-text fields hashed on MTSamples documents, per extraction field."""
NULL_WHEN_HASHED: frozenset[str] = frozenset({"dob"})
RESPONSE_KEYS: tuple[str, ...] = ("model", "role", "type", "stop_reason", "stop_sequence")
USAGE_KEYS: tuple[str, ...] = ("input_tokens", "output_tokens")
LOCATED = frozenset({"verbatim", "normalized"})

PUBLIC_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,119}$")
"""An id, enum value, version, ISO date, relative path or hash: no spaces, no brackets."""
PUBLIC_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\[\d+:\d+\] [0-9a-f]{8}$")
"""An evidence reference `doc_id[start:end] sha8` (contract §11)."""


class ExportError(Exception):
    """A run that cannot be exported (no extraction, or a position that does not hold)."""


def public_string(value: str) -> bool:
    return PUBLIC_TOKEN.match(value) is not None or PUBLIC_REF.match(value) is not None


def export_public_report(payload: Any, _path: str = "report") -> Any:
    """`payload` with sorted keys, after checking that every key and string value has a
    public shape (module docstring). Numbers, booleans and None pass; anything else raises
    `ExportError` naming the key path, never the value."""
    if isinstance(payload, Mapping):
        out: dict[str, Any] = {}
        for key in sorted(payload):
            if not isinstance(key, str) or not PUBLIC_TOKEN.match(key):
                raise ExportError(f"{_path}: a key is not a public token")
            out[key] = export_public_report(payload[key], f"{_path}.{key}")
        return out
    if isinstance(payload, list | tuple):
        return [export_public_report(v, f"{_path}[{i}]") for i, v in enumerate(payload)]
    if isinstance(payload, str):
        if not public_string(payload):
            raise ExportError(f"{_path}: a string value is not a public token or reference")
        return payload
    if payload is None or isinstance(payload, bool | int | float):
        return payload
    raise ExportError(f"{_path}: unsupported value type {type(payload).__name__}")


def link_problem(path: Path) -> str | None:
    """Why an existing file may be neither read nor replaced in place: it is a symbolic
    link, or it has more than one hard link (the bytes belong to another name too)."""
    if path.is_symlink():
        return "is a symbolic link; refused"
    try:
        links = os.lstat(path).st_nlink
    except FileNotFoundError:
        return None
    if links > 1:
        return f"has {links} hard links; refused"
    return None


def write_public_file(target: Path, text: str) -> None:
    """Write `text` to `target` by atomic replacement: a sibling temporary file is renamed
    over the destination (`os.replace`), so the directory entry changes and no inode is
    truncated in place. A destination that is a symbolic link or has more than one hard
    link is refused first: writing through it would reach bytes that belong to another
    name (a holdout gold, for instance). Every public output goes through here."""
    linked = link_problem(target)
    if linked is not None:
        raise ExportError(f"{target.name}: {linked}")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp")
    if tmp.exists() or tmp.is_symlink():
        raise ExportError(f"{tmp.name}: temporary file already exists; refused")
    tmp.write_text(text, encoding="utf-8")
    try:
        os.replace(tmp, target)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def is_mtsamples(doc_id: str) -> bool:
    return doc_id.startswith(MTSAMPLES_DOC_ID_PREFIX)


def replay_path(
    root: Path, variant_id: str, input_hash: str, prompt_version: str, schema_version: str
) -> Path:
    return root / variant_id / f"{input_hash}-{prompt_version}-{schema_version}.json"


def _external_quote(
    quote: str, position: Mapping[str, Any] | None, text: str | None, mtsamples: bool
) -> dict[str, Any]:
    status = position["position_status"] if position else "not_found"
    start = position["offset_start"] if position and status in LOCATED else None
    end = position["offset_end"] if position and status in LOCATED else None
    out: dict[str, Any] = {"start": start, "end": end, "sha256": sha256_hex(quote)}
    if not mtsamples:
        out["text"] = quote
        out["replay_fidelity"] = "exact"
        return out
    exact = (
        status == "verbatim"
        and text is not None
        and start is not None
        and end is not None
        and text[start:end] == quote
    )
    if status == "verbatim" and not exact:
        raise ExportError("a verbatim position does not reproduce its quote")
    out["replay_fidelity"] = "exact" if exact else "lossy"
    return out


def export_public_run(store: Store, run_id: int, texts: Mapping[str, str]) -> dict[str, Any]:
    """The public replay of the extraction `run_id` used. `texts` are the case documents
    (needed only to check that verbatim offsets reproduce the quote)."""
    run = store.case_run(run_id)
    ext = store.extraction_for_run(run_id)
    if ext is None or ext["attempt_id"] is None:
        raise ExportError("run has no extraction from a recorded attempt")
    attempt = store.attempt(int(ext["attempt_id"]))
    response = json.loads(attempt["response_json"])
    parsed: dict[str, list[dict[str, Any]]] = json.loads(ext["parsed_json"])
    positions = {str(r["fact_path"]): r for r in store.facts_for_run(run_id)}

    extraction: dict[str, list[dict[str, Any]]] = {}
    lossy = 0
    quotes = 0
    for fld in EXTRACTION_FIELDS:
        rows = []
        for i, fact in enumerate(parsed.get(fld, [])):
            doc_id = str(fact["doc_id"])
            mts = is_mtsamples(doc_id)
            out = dict(fact)
            out["quote"] = _external_quote(
                str(fact["quote"]), positions.get(f"{fld}[{i}]"), texts.get(doc_id), mts
            )
            quotes += 1
            lossy += out["quote"]["replay_fidelity"] == "lossy"
            if mts:
                for key in HASHED_TEXT_KEYS.get(fld, ()):
                    value = out.get(key)
                    if isinstance(value, str) and value:
                        out[key] = {"sha256": sha256_hex(value)}
            rows.append(out)
        extraction[fld] = rows

    usage = response.get("usage") or {}
    return {
        "replay_version": REPLAY_VERSION,
        "variant_id": run["case_id"],
        "input_hash": run["input_hash"],
        "prompt_version": ext["prompt_version"],
        "schema_version": ext["schema_version"],
        "cache_key_sha8": str(ext["cache_key"])[:8],
        "model_returned": attempt["model_returned"],
        "attempt": {
            "attempt_no": attempt["attempt_no"],
            "status": attempt["status"],
            "created_at": attempt["created_at"],
            "latency_ms": attempt["latency_ms"],
            "input_tokens": attempt["input_tokens"],
            "output_tokens": attempt["output_tokens"],
            "cost_usd": attempt["cost_usd"],
        },
        "response": {
            **{k: response.get(k) for k in RESPONSE_KEYS},
            "usage": {k: usage.get(k) for k in USAGE_KEYS},
        },
        "doc_sha256": {d: sha256_hex(t) for d, t in sorted(texts.items())},
        "mtsamples_doc_ids": sorted(d for d in texts if is_mtsamples(d)),
        "quote_count": quotes,
        "lossy_quote_count": lossy,
        "extraction": extraction,
    }


def dump_replay(payload: Mapping[str, Any]) -> str:
    """Canonical text of a replay file: sorted keys, ASCII only, one trailing newline."""
    return json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True) + "\n"


def _restore_quote(q: Mapping[str, Any], text: str | None) -> str:
    if "text" in q:
        return str(q["text"])
    start, end = q.get("start"), q.get("end")
    if (
        q.get("replay_fidelity") == "exact"
        and text is not None
        and isinstance(start, int)
        and isinstance(end, int)
        and sha256_hex(text[start:end]) == q["sha256"]
    ):
        return text[start:end]
    return UNLOCATABLE_PREFIX + str(q["sha256"])[:8]


def restore_extraction(replay: Mapping[str, Any], texts: Mapping[str, str]) -> Extraction:
    """The extraction a replay records, quotes restored from the documents where the
    fidelity allows (the input of an offline evaluation)."""
    data: dict[str, list[dict[str, Any]]] = {}
    for fld, rows in replay["extraction"].items():
        out = []
        for fact in rows:
            f = dict(fact)
            f["quote"] = _restore_quote(fact["quote"], texts.get(str(fact["doc_id"])))
            for key in HASHED_TEXT_KEYS.get(fld, ()):
                if isinstance(f.get(key), dict):
                    f[key] = None if key in NULL_WHEN_HASHED else ""
            out.append(f)
        data[fld] = out
    return Extraction.model_validate(data)
