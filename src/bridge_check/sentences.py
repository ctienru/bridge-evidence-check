"""Rule-based sentence splitter with a clinical abbreviation list (contract §11).

`split_sentences` returns (start, end) spans into the document string, trimmed of
surrounding whitespace, in order, never empty, together covering every non-whitespace
character. Boundaries are:

- `.`, `?` or `!` followed by whitespace and then an uppercase letter, a digit or a line
  break, unless the word ending at that punctuation is in `ABBREVIATIONS`;
- a blank line;
- a line break followed by a list item (`-`, `*`, a number followed by `.` or `)`) or a
  `|` table row, and the line break that ends a `|` table row.

The splitter has a fixed version string so runs can record which splitter they used.
Changing the rules or the abbreviation list means bumping `SPLITTER_VERSION`.
"""

from __future__ import annotations

import re

SPLITTER_VERSION = "sentences-v1"

# Clinical and general abbreviations after which a period does not end a sentence.
# The whole token ending at the period (minus leading brackets or quotes) must equal an
# entry, case-insensitively; `first.` is not `st.`.
ABBREVIATIONS: tuple[str, ...] = (
    "dr.",
    "mr.",
    "mrs.",
    "ms.",
    "vs.",
    "e.g.",
    "i.e.",
    "approx.",
    "b.i.d.",
    "t.i.d.",
    "q.d.",
    "q.i.d.",
    "p.o.",
    "p.r.n.",
    "s/p.",
    "h/o.",
    "r/o.",
    "wt.",
    "ht.",
    "pt.",
    "hx.",
    "no.",
    "mg.",
    "kg.",
    "lb.",
    "lbs.",
    "cm.",
    "in.",
    "yo.",
    "y.o.",
    "st.",
    "jr.",
    "sr.",
    "etc.",
)

# `.?!` then whitespace then uppercase / digit / line break. The lookahead keeps the
# whitespace out of the match so the boundary is placed right after the punctuation.
_TERMINAL = re.compile(r"[.?!]+(?=[ \t]*(?:\r?\n|[ \t][A-Z0-9]|[ \t]*\r?\n))")
_BLANK_LINE = re.compile(r"\r?\n[ \t]*\r?\n")
_LIST_ITEM = re.compile(r"\r?\n(?=[ \t]*(?:[-*]\s|\d+[.)]\s|\|))")
# A table row also ends at its line break, so the line after a row is its own sentence.
_TABLE_ROW_END = re.compile(r"(?<=\|)[ \t]*\r?\n")
_WORD_BEFORE = re.compile(r"(\S+)$")
# "1." at the start of a line is a list marker, not a sentence end.
_LIST_NUMBER = re.compile(r"(?:^|[\r\n])[ \t]*\d+\.$")


def _is_abbreviation(doc: str, punct_end: int) -> bool:
    """True if the token ending at `punct_end` is a known abbreviation."""
    match = _WORD_BEFORE.search(doc, 0, punct_end)
    if match is None:
        return False
    token = match.group(1).casefold().lstrip("([\"'")
    return token in ABBREVIATIONS


def _is_list_number(doc: str, punct_end: int) -> bool:
    return _LIST_NUMBER.search(doc, max(0, punct_end - 16), punct_end) is not None


def _boundaries(doc: str) -> set[int]:
    cuts: set[int] = set()
    for match in _TERMINAL.finditer(doc):
        if match.group(0) == "." and (
            _is_abbreviation(doc, match.end()) or _is_list_number(doc, match.end())
        ):
            continue
        cuts.add(match.end())
    for match in _BLANK_LINE.finditer(doc):
        cuts.add(match.start())
    for match in _LIST_ITEM.finditer(doc):
        cuts.add(match.start())
    for match in _TABLE_ROW_END.finditer(doc):
        cuts.add(match.start())
    return cuts


def _trim(doc: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and doc[start].isspace():
        start += 1
    while end > start and doc[end - 1].isspace():
        end -= 1
    return (start, end) if start < end else None


def split_sentences(doc: str) -> list[tuple[int, int]]:
    """Sentence spans (start, end) of `doc`; see the module docstring for the rules."""
    cuts = sorted(_boundaries(doc) | {0, len(doc)})
    spans: list[tuple[int, int]] = []
    for start, end in zip(cuts, cuts[1:], strict=False):
        trimmed = _trim(doc, start, end)
        if trimmed is not None:
            spans.append(trimmed)
    return spans


def sentence_containing(spans: list[tuple[int, int]], start: int) -> tuple[int, int]:
    """The span containing offset `start`, or the last span that begins before it."""
    candidate: tuple[int, int] | None = None
    for span in spans:
        if span[0] <= start < span[1]:
            return span
        if span[0] <= start:
            candidate = span
    if candidate is None:
        raise ValueError(f"offset {start} is before the first sentence")
    return candidate
