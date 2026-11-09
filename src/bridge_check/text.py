"""Byte-exact document reading, verbatim quote location and hashing (contract §7.1, §8).

Documents are read with `newline=""` so no newline conversion happens; every offset in the
project is an index into the string returned by `read_doc`, `end` exclusive. `locate` is an
exact substring search: no normalization and no fuzzy matching (AGENTS.md). Hashes are
sha256 over the UTF-8 encoding of the quoted span; `sha8` is its first 8 hex characters,
the only form in which text is referred to in public outputs (`doc_id[start:end] sha8`).
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def read_doc(path: Path) -> str:
    """Read a document byte-exactly: UTF-8, no newline translation."""
    with path.open(encoding="utf-8", newline="") as fh:
        return fh.read()


def locate(doc: str, quote: str) -> list[tuple[int, int]]:
    """Every verbatim occurrence of `quote` in `doc` as (start, end), end exclusive.

    Overlapping occurrences are all reported. An empty quote has no occurrences.
    """
    if not quote:
        return []
    spans: list[tuple[int, int]] = []
    pos = doc.find(quote)
    while pos != -1:
        spans.append((pos, pos + len(quote)))
        pos = doc.find(quote, pos + 1)
    return spans


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha8(text: str) -> str:
    """First 8 hex characters of the sha256 of `text`."""
    return sha256_hex(text)[:8]


def quote_sha256(doc: str, start: int, end: int) -> str:
    """sha256 of the span `doc[start:end]`."""
    if not 0 <= start < end <= len(doc):
        raise ValueError(f"span [{start}:{end}] is outside the document (length {len(doc)})")
    return sha256_hex(doc[start:end])
