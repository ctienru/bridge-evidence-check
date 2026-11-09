"""Quote verification: position, value and assertion checks (contract §6, §7.3; 06 §3).

Every extracted fact becomes exactly one `CheckedEvidence`; nothing is dropped. Two
independent outputs per fact: where the quote is (`position_status`) and whether the
evidence may be used (`exclusion_reasons`). The checks run in a fixed order:

1. Position. Layer 1 verbatim (`text.locate`). Layer 2 conservative normalization (NFKC,
   quote and dash unification, case-fold, whitespace collapse; nothing is removed, so
   decimal points, comparison operators and negation words survive), projected back to
   original offsets through an index map. Otherwise a `difflib.SequenceMatcher` candidate
   (a pointer for a human, never a verification: AGENTS.md), otherwise `not_found`, which
   skips layers 3 and 4 and sets `exclusion_reasons == ["quote_not_found"]`.
2. Layer 3 value-in-quote: the raw value as written (number, unit, concept alias, date,
   identifier, drug name) must be readable from the located span as a whole source token
   (boundaries are read in the document, so a clipped `<35.1` or `heatstroke` does not
   count), and bound to the fact it describes: a number to its unit and label, a stage or
   severity to its diagnosis, a date or dose to its drug and a start / stop date to a
   non-negated start / stop word, a date of birth to its label, an event date to its own
   measurement (the nearest date, with nothing else between), a PAD symptom or cirrhosis
   qualifier to the patient's own actual text in the same clause, a `doc_dates` date to the
   nearest name of the document it describes, a GLP-1 purpose to a cue (a MACE cue cannot
   be overwritten), and each lifestyle value to one unambiguous cue. A percentile, a range
   end, a bound ("below", "<"), a signed number or a goal is not a measured value; a
   hypothetical or resumed start, or a start word that belongs to another drug, is not an
   initiation; a drug with an end date or a stop in its source clause is not ongoing; a
   role-only document reference must fit exactly one document. Identity reads every
   identifier at every located occurrence with its own cues, and a match needs an actual
   (non-hypothetical) patient identifier; a heading line governs the `Label:` entries under
   it across sentence breaks.
3. Layer 4 sentence-level assertion check (`check_assertion`) with the frozen cue table,
   matched on the NFKC form of the sentence.
4. Document-level exclusions: `claim_document` (PA draft) and `wrong_patient` (identity,
   read from each identity fact's own text: the complete identifier under its own label).

Pure functions only: no SQL, no I/O except loading the frozen tables, no document text in
exceptions. Offsets are Python string indices into the text read with `newline=""`.
"""

from __future__ import annotations

import calendar
import difflib
import itertools
import re
import unicodedata
from bisect import bisect_left
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from dataclasses import field as dc_field
from datetime import date
from decimal import Decimal
from functools import cached_property
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from bridge_check.cues import Cues, load_cues
from bridge_check.enums import (
    ATTENDANCE,
    AXES,
    AXIS_DEFAULTS,
    CLAIM_IDS,
    CONCEPTS,
    DOC_ROLES,
    END_KINDS,
    EXTRACTION_FIELDS,
    GLP1_NAMES,
    PROGRAM_TYPES,
    PURPOSES,
)
from bridge_check.input import PrimaryPatient
from bridge_check.rules_schema import load_drugs
from bridge_check.schema import Extraction, Fact
from bridge_check.sentences import sentence_containing, split_sentences
from bridge_check.text import locate, sha8

RULES_DIR = Path(__file__).resolve().parents[2] / "rules"
DEFAULT_TERMS_PATH = RULES_DIR / "verify-terms-v1.yaml"
DEFAULT_DRUGS_PATH = RULES_DIR / "drugs-v2.yaml"

CANDIDATE_RATIO = 0.8
"""Minimum `SequenceMatcher.ratio()` between the normalized quote and the best window for a
`candidate`. A candidate never supports anything; the ratio only decides whether a human
is shown a likely location (06 §3: "history of stroke" vs "no history of stroke" is 0.92,
so similarity says nothing about the fact)."""

NORMALIZATIONS: tuple[str, ...] = ("nfkc", "quotes_dashes", "casefold", "whitespace")
_QUOTES_DASHES: dict[str, str] = {
    **dict.fromkeys("‘’‚‛′", "'"),
    **dict.fromkeys("“”„‟″", '"'),
    **dict.fromkeys("‐‑‒–—―−", "-"),
}

LOCATED: tuple[str, ...] = ("verbatim", "normalized")
_SHARED_FACT_FIELDS = frozenset(Fact.model_fields)
_COLUMN_FIELDS = frozenset({"kind", "concept", "raw_value", "raw_unit"})

# A list-item boundary inside a sentence (A-06): a line break that starts a bullet, a
# number, a table row, or a `Label:` form line ("Patient ID:", "Type 2 diabetes:"). The
# `Label:` line is a verifier extension: form documents carry no sentence punctuation.
_LIST_ITEM = re.compile(r"\r?\n(?=[ \t]*(?:[-*•]\s|\d+[.)]\s|\||[A-Za-z][A-Za-z0-9 /()'-]{0,40}:))")
_TABLE_SPACES = re.compile(r" {3,}")
_LABEL_LINE = re.compile(r"[ \t]*[A-Za-z][A-Za-z0-9 /()'-]{0,40}:")
# A heading line: a label and a colon with nothing after it ("Family history:"). Its cues
# govern the `Label:` entries under it until the sentence ends (a blank line splits sentences).
_HEADING_ONLY = re.compile(r"[ \t]*[A-Za-z][A-Za-z0-9 /()'-]{0,40}:[ \t]*")
_HEADING_AT = re.compile(r"[ \t]*[A-Za-z][A-Za-z0-9 /()'-]{0,40}:[ \t]*(?=\r?\n)")
_BLANK_GAP = re.compile(r"\r?\n[ \t]*\r?\n")
_HEADING_LINE = re.compile(r"(?:^|[\r\n])[ \t]*[A-Za-z][A-Za-z0-9 /()'-]{0,40}:[ \t]*(?=\r?\n|$)")


class VerifyError(Exception):
    """An unexpected error while verifying one fact. Carries no document text."""

    def __init__(self, fact_path: str, error_type: str) -> None:
        super().__init__(f"{fact_path}: {error_type}")
        self.fact_path = fact_path
        self.error_type = error_type


# --- Frozen tables ----------------------------------------------------------------------------


class VerifyTerms(BaseModel):
    """`rules/verify-terms-v1.yaml` plus the drug and GLP-1 names added to the A-09 list."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    version: str = Field(pattern=r"^verify-terms-v\d+$")
    concept_terms: dict[str, list[str]]
    blocking_terms: list[str]
    treatment_terms: list[str]
    question_openers: list[str]
    kind_labels: dict[str, list[str]]
    other_value_labels: list[str]
    qualifier_fillers: list[str]
    dob_labels: list[str]
    age_labels: list[str]
    age_suffixes: list[str]
    id_labels: dict[str, list[str]]
    pad_symptom_terms: list[str]
    pad_asymptomatic_terms: list[str]
    cirrhosis_terms: list[str]
    noncirrhotic_terms: list[str]
    coordinators: list[str]
    start_verbs: list[str]
    restart_verbs: list[str]
    stop_verbs: list[str]
    percentile_terms: list[str]
    a09_fillers: list[str]
    doc_role_terms: dict[str, list[str]]
    lifestyle_cues: dict[str, dict[str, list[str]]]
    claim_labels: dict[str, list[str]]
    claim_label_blockers: list[str]
    answer_tokens: list[str]
    answer_markers: list[str]
    empty_markers: list[str]
    attachment_terms: list[str]
    attachment_negations: list[str]
    attachment_finite_forms: list[str]
    attachment_subjects: list[str]
    medication_list_status: dict[str, list[str]]
    section_headings: list[str]
    bound_words: list[str]
    range_words: list[str]
    range_openers: list[str]
    bp_non_measurement_words: list[str]
    purpose_cues: dict[str, list[str]]
    treatment_modifier_suffixes: list[str]
    event_object_fillers: list[str]

    def model_post_init(self, context: Any, /) -> None:
        unknown = set(self.concept_terms) - set(CONCEPTS)
        if unknown or "other" in self.concept_terms:
            raise ValueError("concept_terms: unknown concept or terms for `other`")
        if set(self.id_labels) != {"mbi", "local"}:
            raise ValueError("id_labels: exactly `mbi` and `local`")
        if set(self.doc_role_terms) != set(DOC_ROLES):
            raise ValueError("doc_role_terms: one entry per document role")
        if not set(self.purpose_cues) <= set(PURPOSES) - {"unknown"}:
            raise ValueError("purpose_cues: unknown purpose")
        if not set(self.claim_labels) <= set(CLAIM_IDS):
            raise ValueError("claim_labels: unknown claim id")
        for axis, values in self.lifestyle_cues.items():
            allowed = {
                "program_type": PROGRAM_TYPES,
                "attendance": ATTENDANCE,
                "end_kind": END_KINDS,
            }
            if axis not in allowed or not set(values) <= set(allowed[axis]) - {"unknown"}:
                raise ValueError(f"lifestyle_cues: unknown axis or value under {axis!r}")


def load_terms(
    path: Path = DEFAULT_TERMS_PATH, drugs_path: Path = DEFAULT_DRUGS_PATH
) -> VerifyTerms:
    with path.open(encoding="utf-8") as fh:
        data: Any = yaml.safe_load(fh)
    drug_names = [n for d in load_drugs(drugs_path).drugs for n in d.names]
    data["treatment_terms"] = [*data["treatment_terms"], *GLP1_NAMES, *drug_names]
    return VerifyTerms.model_validate(data)


# --- Inputs and outputs -----------------------------------------------------------------------


@dataclass(frozen=True)
class Document:
    doc_id: str
    role: str
    text: str
    sha256: str


Docs = Mapping[str, Document]


@dataclass(frozen=True)
class VerifyContext:
    primary_patient: PrimaryPatient
    cues: Cues
    terms: VerifyTerms

    @classmethod
    def load(cls, primary_patient: PrimaryPatient) -> VerifyContext:
        return cls(primary_patient, load_cues(), load_terms())


@dataclass(frozen=True)
class CheckedEvidence:
    """One verified fact; the columns of the `evidence` table (06 §3.5)."""

    field: str
    fact_path: str
    kind: str | None
    concept: str | None
    doc_id: str
    doc_sha256: str
    start: int | None
    end: int | None
    quote: str
    raw_value: str | None
    raw_unit: str | None
    event_date: str | None
    """The model's event date. Use it only when `event_date_source == "llm"`; compute fills
    the stored column with the inherited document date when it is NULL (contract §5 item 3)."""
    date_precision: str | None
    certainty_llm: str
    subject_llm: str
    temporality_llm: str
    certainty_checked: str | None
    subject_checked: str | None
    temporality_checked: str | None
    relative_llm: str
    position_status: str
    assertion_check: str | None
    exclusion_reasons: tuple[str, ...]
    flags: tuple[str, ...]
    ref: str
    """`doc_id[start:end] sha8` (sha8 of the located span; of the quote when not found)."""
    event_date_source: str | None = None
    """`llm` when a date bound to the fact in its own quote equals `event_date`; `none` when
    the quote carries no such date (compute dates the fact through verified `doc_dates`,
    contract §5 item 3); NULL when not checked (not found, or no `event_date`)."""
    attributes: Mapping[str, Any] = dc_field(default_factory=dict)


@dataclass(frozen=True)
class DocFact:
    """Per-document identity conclusion (`doc_facts`); `doc_date` is filled by compute."""

    doc_id: str
    identity_status: str
    identity_evidence_index: int | None


@dataclass(frozen=True)
class VerifyResult:
    evidence: list[CheckedEvidence]
    doc_facts: list[DocFact]


# --- Normalization with an index map ----------------------------------------------------------


@dataclass(frozen=True)
class Normalized:
    """`text` with, per character, the original span of the cluster it came from."""

    text: str
    starts: tuple[int, ...]
    ends: tuple[int, ...]
    first: tuple[bool, ...]
    last: tuple[bool, ...]
    fired: frozenset[str]

    def to_original(self, start: int, end: int) -> tuple[int, int] | None:
        """Original offsets of `text[start:end]`, or None if it cuts through a cluster."""
        if start >= end or not self.first[start] or not self.last[end - 1]:
            return None
        return self.starts[start], self.ends[end - 1]


def normalize(text: str, steps: frozenset[str] = frozenset(NORMALIZATIONS)) -> Normalized:
    """Conservative normalization (06 §3 layer 2), one cluster at a time.

    A cluster is a base character with the combining marks after it, or a run of
    whitespace. Each cluster is NFKC-normalized, quotes and dashes are unified and it is
    case-folded; a whitespace run becomes one space. Every output character maps back to its
    cluster, so a match is projected to original offsets and never splits an expansion.
    `steps` switches single normalizations off (used to record which ones a match needs).
    """
    out: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    first: list[bool] = []
    last: list[bool] = []
    fired: set[str] = set()
    i, n = 0, len(text)
    while i < n:
        j = i + 1
        if text[i].isspace() and "whitespace" in steps:
            while j < n and text[j].isspace():
                j += 1
            if text[i:j] != " ":
                fired.add("whitespace")
            piece = " "
        else:
            while j < n and unicodedata.combining(text[j]):
                j += 1
            cluster = text[i:j]
            nfkc = unicodedata.normalize("NFKC", cluster) if "nfkc" in steps else cluster
            if nfkc != cluster:
                fired.add("nfkc")
            unified = (
                "".join(_QUOTES_DASHES.get(c, c) for c in nfkc)
                if "quotes_dashes" in steps
                else nfkc
            )
            if unified != nfkc:
                fired.add("quotes_dashes")
            piece = unified.casefold() if "casefold" in steps else unified
            if piece != unified:
                fired.add("casefold")
            if piece.isspace() and "whitespace" in steps:
                piece = " "
        for k, c in enumerate(piece):
            out.append(c)
            starts.append(i)
            ends.append(j)
            first.append(k == 0)
            last.append(k == len(piece) - 1)
        i = j
    return Normalized(
        "".join(out), tuple(starts), tuple(ends), tuple(first), tuple(last), frozenset(fired)
    )


def needed_normalizations(quote: str, original: str) -> list[str]:
    """The smallest set of normalizations under which `quote` equals `original`.

    Subsets are tried by size, then in `NORMALIZATIONS` order, so a ligature that both NFKC
    and case-folding expand is recorded as `nfkc` only.
    """
    q = quote.strip()
    for size in range(len(NORMALIZATIONS) + 1):
        for subset in itertools.combinations(NORMALIZATIONS, size):
            if normalize(q, frozenset(subset)).text == normalize(original, frozenset(subset)).text:
                return list(subset)
    return list(NORMALIZATIONS)


def _find_all(haystack: str, needle: str) -> list[int]:
    found: list[int] = []
    pos = haystack.find(needle)
    while pos != -1:
        found.append(pos)
        pos = haystack.find(needle, pos + 1)
    return found


def locate_normalized(norm_doc: Normalized, quote: str) -> list[tuple[int, int]]:
    """Original spans of every normalized occurrence of `quote` (cluster-aligned only)."""
    nq = normalize(quote.strip()).text
    if not nq:
        return []
    spans: list[tuple[int, int]] = []
    for pos in _find_all(norm_doc.text, nq):
        span = norm_doc.to_original(pos, pos + len(nq))
        if span is not None:
            spans.append(span)
    return spans


def find_candidate(norm_doc: Normalized, quote: str) -> tuple[int, int, float] | None:
    """The best `SequenceMatcher` window for `quote` if its ratio reaches `CANDIDATE_RATIO`."""
    nq = normalize(quote.strip()).text
    nd = norm_doc.text
    if not nq or not nd:
        return None
    block = difflib.SequenceMatcher(None, nq, nd, autojunk=False).find_longest_match(
        0, len(nq), 0, len(nd)
    )
    if block.size == 0:
        return None
    lo = max(0, block.b - block.a)
    hi = min(len(nd), lo + len(nq))
    ratio = difflib.SequenceMatcher(None, nq, nd[lo:hi], autojunk=False).ratio()
    if ratio < CANDIDATE_RATIO:
        return None
    while lo < hi and not norm_doc.first[lo]:
        lo += 1
    while hi > lo and not norm_doc.last[hi - 1]:
        hi -= 1
    span = norm_doc.to_original(lo, hi)
    if span is None:
        return None
    return span[0], span[1], round(ratio, 4)


# --- Term and cue matching --------------------------------------------------------------------

# Matching runs on text with NFKC and quote/dash unification only: full-width letters and
# compatibility forms become plain, while line breaks and case are kept (list-item
# boundaries need the line breaks; acronyms such as MI and PAD need the case). Patterns
# allow any whitespace between words, so a phrase broken across lines still matches.
_SCAN_STEPS = frozenset({"nfkc", "quotes_dashes"})


@dataclass(frozen=True)
class Hit:
    start: int
    end: int
    label: str
    """concept, `axis:value` for a cue, or a fixed tag."""
    text: str
    entry: str = ""
    """The configured table entry that matched (a cue's identity for right-hand lookup)."""


def _term_pattern(term: str, *, case_sensitive: bool | None = None) -> re.Pattern[str]:
    body = re.escape(term).replace(r"\ ", r"\s+")
    if term[0].isalnum():
        body = r"(?<![^\W_])" + body
    if term[-1].isalnum():
        body += r"(?![^\W_])"
    if case_sensitive is None:
        case_sensitive = sum(c.isupper() for c in term) >= 2
    return re.compile(body, 0 if case_sensitive else re.IGNORECASE)


Patterns = Sequence[tuple[re.Pattern[str], str, str]]


def _patterns(
    terms: Iterable[str], label: str, *, case_sensitive: bool | None = None
) -> list[tuple[re.Pattern[str], str, str]]:
    return [(_term_pattern(t, case_sensitive=case_sensitive), label, t) for t in terms]


def _leftmost_longest(hits: Iterable[Hit]) -> list[Hit]:
    chosen: list[Hit] = []
    last_end = -1
    for hit in sorted(hits, key=lambda h: (h.start, -(h.end - h.start))):
        if hit.start >= last_end:
            chosen.append(hit)
            last_end = hit.end
    return chosen


def _scan(text: str, patterns: Patterns) -> list[Hit]:
    return [
        Hit(m.start(), m.end(), label, m.group(0), entry)
        for pattern, label, entry in patterns
        for m in pattern.finditer(text)
    ]


def _words_regex(words: Iterable[str]) -> str:
    alternatives = sorted({re.escape(w).replace(r"\ ", r"\s+") for w in words}, key=len)
    return "|".join(reversed(alternatives))


class _Matchers:
    """Compiled patterns for one (cues, terms) pair."""

    def __init__(self, cues: Cues, terms: VerifyTerms) -> None:
        self.cues = cues
        self.terms = terms
        self.cue_patterns: list[tuple[re.Pattern[str], str, str]] = [
            (_term_pattern(cue, case_sensitive=False), f"{axis}:{value}", cue)
            for axis, values in cues.axes.items()
            for value, words in values.items()
            for cue in words
        ]
        self.right_hand = frozenset(p.casefold() for p in cues.right_hand_patterns)
        self.terminators = [_term_pattern(t, case_sensitive=False) for t in cues.terminators]
        self.concept_patterns = [
            p for concept, words in terms.concept_terms.items() for p in _patterns(words, concept)
        ] + _patterns(terms.blocking_terms, "blocked")
        self.treatment_patterns = _patterns(terms.treatment_terms, "treatment")
        self.openers = frozenset(w.casefold() for w in terms.question_openers)
        self.label_patterns = [
            p
            for kind, words in terms.kind_labels.items()
            for p in _patterns(words, kind, case_sensitive=False)
        ] + _patterns(terms.other_value_labels, "other", case_sensitive=False)
        self.claim_labels = {
            claim_id: frozenset(normalize(x).text.casefold() for x in words)
            for claim_id, words in terms.claim_labels.items()
        }
        # Answers a PA field may offer: yes/no tokens, GLP-1 product names, BMI brackets.
        self.answer_patterns = _patterns(
            [*terms.answer_tokens, *GLP1_NAMES], "answer", case_sensitive=False
        ) + [
            (re.compile(rx), "answer", rx)
            for rx in (r"<\d+", r"\d+-\d+(?:\.\d)?", r"\d+\+", r"≥\d+")
        ]
        self.claim_blocker_patterns = _patterns(
            terms.claim_label_blockers, "blocker", case_sensitive=False
        )
        self.answer_markers = tuple(sorted({_box_norm(m) for m in terms.answer_markers}))
        self.answer_tokens = tuple(t.casefold() for t in terms.answer_tokens)
        self.empty_markers = tuple(sorted({_box_norm(m) for m in terms.empty_markers}))
        self.attachment_negations = tuple(n.casefold() for n in terms.attachment_negations)
        self.attachment_finite = frozenset(f.casefold() for f in terms.attachment_finite_forms)
        self.attachment_subjects = frozenset(x.casefold() for x in terms.attachment_subjects)
        self.attachment_patterns = _patterns(
            terms.attachment_terms, "attachment", case_sensitive=False
        )
        self.list_status_patterns = [
            p
            for status, words in terms.medication_list_status.items()
            for p in _patterns(words, status, case_sensitive=False)
        ]
        self.section_heading_patterns = _patterns(
            terms.section_headings, "heading", case_sensitive=False
        )
        self.dob_patterns = _patterns(terms.dob_labels, "dob", case_sensitive=False)
        self.age_patterns = _patterns(terms.age_labels, "age", case_sensitive=False)
        self.age_suffix_patterns = _patterns(terms.age_suffixes, "age", case_sensitive=False)
        self.symptom_patterns = _patterns(terms.pad_symptom_terms, "symptom", case_sensitive=False)
        self.asymptomatic_patterns = _patterns(
            terms.pad_asymptomatic_terms, "asymptomatic", case_sensitive=False
        )
        self.cirrhosis_patterns = _patterns(
            terms.cirrhosis_terms, "cirrhosis", case_sensitive=False
        )
        self.noncirrhotic_patterns = _patterns(
            terms.noncirrhotic_terms, "noncirrhotic", case_sensitive=False
        )
        self.coordinators = [_term_pattern(c, case_sensitive=False) for c in terms.coordinators]
        fillers = _words_regex(terms.qualifier_fillers)
        self.filler = re.compile(rf"[\s,:()/-]*(?:(?:{fillers})[\s,:()/-]*)*", re.IGNORECASE)
        a09 = _words_regex(terms.a09_fillers)
        self.a09_filler = re.compile(rf"\s*(?:(?:{a09})\s+)*", re.IGNORECASE)
        self.event_patterns = (
            _patterns(terms.start_verbs, "start", case_sensitive=False)
            + _patterns(terms.restart_verbs, "restart", case_sensitive=False)
            + _patterns(terms.stop_verbs, "stop", case_sensitive=False)
        )
        self.percentile_patterns = _patterns(
            terms.percentile_terms, "percentile", case_sensitive=False
        )
        self.role_patterns = {
            role: _patterns(words, role, case_sensitive=False)
            for role, words in terms.doc_role_terms.items()
        }
        self.lifestyle_patterns = {
            axis: [p for value, words in values.items() for p in _patterns(words, value)]
            for axis, values in terms.lifestyle_cues.items()
        }
        bound = _words_regex(terms.bound_words)
        rng = _words_regex(terms.range_words)
        openers = _words_regex(terms.range_openers)
        self.bound_before = re.compile(rf"(?<![^\W_])(?:{bound})\s*$", re.IGNORECASE)
        self.range_after = re.compile(rf"^\s*(?:{rng})\s+[<>]?\s*\d", re.IGNORECASE)
        self.range_before = re.compile(rf"\d\s+(?:{rng})\s*$", re.IGNORECASE)
        self.range_opener_before = re.compile(rf"(?<![^\W_])(?:{openers})\s*$", re.IGNORECASE)
        self.bp_non_measurement = _patterns(
            terms.bp_non_measurement_words, "non_measurement", case_sensitive=False
        )
        self.purpose_patterns = [
            p for value, words in terms.purpose_cues.items() for p in _patterns(words, value)
        ]
        objects = _words_regex(terms.event_object_fillers)
        self.event_object = re.compile(rf"\s*(?:(?:{objects})\s+)*", re.IGNORECASE)
        suffixes = _words_regex(terms.treatment_modifier_suffixes)
        # Used with `.match(text, pos)`, which anchors at `pos` itself.
        self.treatment_modifier = re.compile(rf"-(?:{suffixes})(?![^\W_])", re.IGNORECASE)
        # `<label> [#|no.|number] [:|#] <identifier>`: the whole token after the label is the
        # identifier, read in full; `_id_token` decides whether its format is resolvable.
        self.id_patterns = [
            (
                re.compile(
                    rf"(?<![^\W_])(?:{_words_regex(words)})(?![^\W_])[ \t]*"
                    r"(?:#|no\.|number)?[ \t]*[:#]?[ \t]*(\S+)",
                    re.IGNORECASE,
                ),
                kind,
            )
            for kind, words in terms.id_labels.items()
        ]

    def concepts(self, text: str) -> list[Hit]:
        return _leftmost_longest(_scan(text, self.concept_patterns))

    def terminator_positions(self, sentence: str) -> list[tuple[int, int]]:
        """Terminators (A-06) plus list-item boundaries. A `Label:` line is a boundary unless
        the line before it is a heading (ends with `:` and nothing else, "Family history:"),
        whose cues govern the entries under it."""
        spans = [(m.start(), m.end()) for p in self.terminators for m in p.finditer(sentence)]
        if self.cues.list_item_boundary:
            for m in _LIST_ITEM.finditer(sentence):
                if _LABEL_LINE.match(sentence, m.end()) and _HEADING_LINE.search(
                    sentence, 0, m.start()
                ):
                    continue  # a heading above governs every `Label:` entry under it
                spans.append((m.start(), m.end()))
        return spans

    def cue_hits(self, sentence: str) -> list[Hit]:
        hits = _leftmost_longest(_scan(sentence, self.cue_patterns))
        return [h for h in hits if h.entry != "?" or self._question_cue(sentence, h.start)]

    def _question_cue(self, sentence: str, pos: int) -> bool:
        """A-08: `?` is a cue only when attached to a word, and not when it ends a question."""
        before = sentence[pos - 1] if pos > 0 else " "
        after = sentence[pos + 1] if pos + 1 < len(sentence) else " "
        if not (before.isalnum() or after.isalnum()):
            return False
        if sentence.rstrip().endswith("?") and pos == len(sentence.rstrip()) - 1:
            words = sentence.split()
            if words and words[0].strip("\"'(").casefold() in self.openers:
                return False
        return True


_MATCHERS: dict[tuple[int, int], _Matchers] = {}


def _matchers(cues: Cues, terms: VerifyTerms) -> _Matchers:
    key = (id(cues), id(terms))
    found = _MATCHERS.get(key)
    if found is None or found.cues is not cues or found.terms is not terms:
        found = _Matchers(cues, terms)
        _MATCHERS[key] = found
    return found


# --- Layer 4: sentence-level assertion check --------------------------------------------------


@dataclass(frozen=True)
class AssertionCheck:
    result: str  # matched | mismatch | unrecognized
    checked: Mapping[str, str | None]
    """Per axis: the value the cues give (the default when no cue is in scope), or None when
    the scope cannot be decided (cues for two values of one axis, an ambiguous A-09 case)."""
    per_axis: Mapping[str, str]

    def key(self) -> tuple[str, tuple[str | None, ...]]:
        return self.result, tuple(self.checked[a] for a in AXES)


def check_assertion(
    sentence: str,
    mention_span: tuple[int, int],
    claimed: Mapping[str, str],
    cues: Cues,
    *,
    terms: VerifyTerms,
    concept: str | None = None,
    whole_span: bool = False,
) -> AssertionCheck:
    """Contract §6 outcome table for one mention, offsets relative to `sentence`.

    Cues are matched on the NFKC form of the sentence (offsets mapped), so a full-width or
    line-broken cue still counts. A cue left of the mention applies when no terminator lies
    between them; a cue right of the mention applies only when its table entry is a
    right-hand pattern (A-07, A-08) with no terminator in between. With `whole_span` (no
    mention word could be located) cues inside the span act as left cues.

    A-09: a negation cue whose text up to the mention names a treatment and not the fact's
    own concept negates the treatment only; if a coordinator ("or", "and") follows the
    treatment, the negation may reach the mention too, and certainty is undecidable.
    """
    m = _matchers(cues, terms)
    norm = normalize(sentence, _SCAN_STEPS)
    text = norm.text
    ms = bisect_left(norm.starts, mention_span[0])
    me = bisect_left(norm.starts, mention_span[1])
    terminators = m.terminator_positions(text)

    def blocked(a: int, b: int) -> bool:
        return any(a <= ts and te <= b for ts, te in terminators)

    headings = [(h.start, h.end) for h in _scan(text, m.section_heading_patterns)]
    applying: list[Hit] = []
    undecidable: set[str] = set()
    for hit in m.cue_hits(text):
        if any(hs <= hit.start and hit.end <= he for hs, he in headings):
            continue  # the heading's own words ("HISTORY OF PRESENT ILLNESS") assert nothing
        inside = ms <= hit.start and hit.end <= me
        if inside and whole_span:
            ok = not blocked(hit.end, me)
        elif hit.end <= ms:
            ok = not blocked(hit.end, ms)
        elif hit.start >= me:
            ok = hit.entry.casefold() in m.right_hand and not blocked(me, hit.start)
        else:
            ok = False  # overlaps the mention
        if ok and hit.label == "certainty:negated" and hit.end <= ms:
            # A-09: the treatment must be the object of the negation ("not on insulin"),
            # not a modifier of the denied diagnosis ("no prior treatment-related stroke").
            between = text[hit.end : ms]
            treatments = [
                t
                for t in _scan(between, m.treatment_patterns)
                if m.a09_filler.fullmatch(between, 0, t.start)
                and not m.treatment_modifier.match(between, t.end)
            ]
            own = [h for h in m.concepts(between) if h.label == concept]
            if treatments and not own:
                ok = False
                rest = between[max(t.end for t in treatments) :]
                if any(p.search(rest) for p in m.coordinators) or "," in rest:
                    undecidable.add("certainty")
        if ok:
            applying.append(hit)

    checked: dict[str, str | None] = {}
    per_axis: dict[str, str] = {}
    for axis in AXES:
        values = {h.label.split(":", 1)[1] for h in applying if h.label.startswith(axis + ":")}
        claim, default = claimed[axis], AXIS_DEFAULTS[axis]
        if len(values) > 1 or axis in undecidable:
            checked[axis], per_axis[axis] = None, "unrecognized"
        elif values:
            (value,) = values
            checked[axis] = value
            per_axis[axis] = "matched" if value == claim else "mismatch"
        else:
            checked[axis] = default
            per_axis[axis] = "matched" if claim == default else "unrecognized"
    outcomes = set(per_axis.values())
    result = (
        "mismatch"
        if "mismatch" in outcomes
        else "unrecognized"
        if "unrecognized" in outcomes
        else "matched"
    )
    return AssertionCheck(result, checked, per_axis)


# --- Layer 3: values --------------------------------------------------------------------------

# A number token starts at its comparator when it has one; digits are never read without a
# comparator written right before them, and never from inside a word ("A1c", "T2DM").
_NUMBER = re.compile(
    r"(?:(?<![<>=≤≥])(<=|>=|[<>≤≥])\s*"
    r"|(?<![\w.,<>=≤≥-])(?<![<>=≤≥]\s)(?<!-\s))"
    r"(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?!\d)(?![.,]\d)"
)
_RAW_NUMBER = re.compile(r"\s*(?:(<=|>=|[<>≤≥])\s*)?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?\s*")
_COMPARATORS = {">=": "≥", "<=": "≤"}
# An identifier-like token: letters, digits and inner hyphens, read in full.
_ID_TOKEN = re.compile(r"\S+")
_ID_TRAIL = ".,;:)]}'\""
_ID_SHAPE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")


def _id_token(raw: str) -> tuple[str, bool]:
    """(canonical identifier, resolvable) for a whitespace-delimited token with trailing
    punctuation removed. A token with characters outside letters, digits, `.`, `_`, `-`
    (`P-0001/2`, a non-ASCII letter) cannot be resolved and never matches anything."""
    token = unicodedata.normalize("NFKC", raw).rstrip(_ID_TRAIL)
    return canonical_id(token), _ID_SHAPE.match(token) is not None and any(
        c.isdigit() for c in token
    )


_ORDINAL = re.compile(r"(?:st|nd|rd|th)\b", re.IGNORECASE)
_DASH_NUMBER_AFTER = re.compile(r"[ \t]*-[ \t]*\d")
_DASH_NUMBER_BEFORE = re.compile(r"\d[ \t]*-[ \t]*$")


def _canonical_number(cmp: str | None, digits: str, decimals: str | None) -> str:
    sign = _COMPARATORS.get(cmp or "", cmp or "")
    return sign + digits.replace(",", "") + (f".{decimals}" if decimals is not None else "")


def parse_raw_number(raw: str) -> str | None:
    """Canonical token of a raw value as written (comparator + digits + decimals), or None."""
    m = _RAW_NUMBER.fullmatch(unicodedata.normalize("NFKC", raw))
    return _canonical_number(*m.groups()) if m else None


_MONTHS: dict[str, int] = {
    **{name.casefold(): i for i, name in enumerate(calendar.month_name) if name},
    **{name.casefold(): i for i, name in enumerate(calendar.month_abbr) if name},
    "sept": 9,
}
_MONTH = "|".join(sorted(_MONTHS, key=len, reverse=True))
_DATE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?<![\d-])(\d{4})-(\d{2})-(\d{2})(?![\d-])"), "ymd"),
    (re.compile(r"(?<![\d-])(\d{4})-(\d{2})(?![\d-])"), "ym"),
    (re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})/(\d{4})(?![\d/])"), "mdy"),
    (re.compile(r"(?<![\d-])(\d{1,2})-(\d{1,2})-(\d{4})(?![\d-])"), "mdy"),
    (
        re.compile(rf"(?<![a-z])({_MONTH})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})(?!\d)"),
        "Mdy",
    ),
    (re.compile(rf"(?<!\d)(\d{{1,2}})\s+({_MONTH})\.?,?\s+(\d{{4}})(?!\d)"), "dMy"),
    (re.compile(rf"(?<![a-z])({_MONTH})\.?,?\s+(\d{{4}})(?!\d)"), "My"),
    (re.compile(r"(?<![\d/.,-])((?:19|20)\d{2})(?![\d/-])"), "y"),
)


def _iso(y: int, m: int | None = None, d: int | None = None) -> str | None:
    try:
        date(y, m or 1, d or 1)
    except ValueError:
        return None
    if m is None:
        return f"{y:04d}"
    return f"{y:04d}-{m:02d}" if d is None else f"{y:04d}-{m:02d}-{d:02d}"


def dates_in(text: str) -> list[tuple[str, int, int]]:
    """(ISO date at the written precision, start, end) for every date in casefolded `text`."""
    found: list[tuple[str, int, int]] = []
    for pattern, shape in _DATE_PATTERNS:
        for m in pattern.finditer(text):
            g = m.groups()
            if shape == "ymd":
                iso = _iso(int(g[0]), int(g[1]), int(g[2]))
            elif shape == "ym":
                iso = _iso(int(g[0]), int(g[1]))
            elif shape == "mdy":
                iso = _iso(int(g[2]), int(g[0]), int(g[1]))
            elif shape == "Mdy":
                iso = _iso(int(g[2]), _MONTHS[g[0]], int(g[1]))
            elif shape == "dMy":
                iso = _iso(int(g[2]), _MONTHS[g[1]], int(g[0]))
            elif shape == "My":
                iso = _iso(int(g[1]), _MONTHS[g[0]])
            else:
                iso = _iso(int(g[0]))
            if iso is not None:
                found.append((iso, m.start(), m.end()))
    return found


_POSSESSIVE = re.compile(r"\s*(?:'s|’s|s')?\s*(?:own\s+)?")
_MBI = re.compile(
    r"^[1-9][AC-HJKMNP-RT-Y][AC-HJKMNP-RT-Y0-9]\d[AC-HJKMNP-RT-Y][AC-HJKMNP-RT-Y0-9]\d"
    r"[AC-HJKMNP-RT-Y]{2}\d{2}$"
)


def canonical_id(value: str) -> str:
    return re.sub(r"[\s-]+", "", unicodedata.normalize("NFKC", value)).upper()


def id_type(value: str, label: str | None = None) -> str:
    """The explicit label's type (`mbi` / `local`) when there is one, else `mbi` for an
    MBI-shaped identifier and `local` otherwise."""
    if label is not None:
        return label
    return "mbi" if _MBI.match(canonical_id(value)) else "local"


# --- Per-document index -----------------------------------------------------------------------


class _DocIndex:
    def __init__(self, doc: Document) -> None:
        self.doc = doc

    @cached_property
    def norm(self) -> Normalized:
        return normalize(self.doc.text)

    @cached_property
    def sentences(self) -> list[tuple[int, int]]:
        return split_sentences(self.doc.text)

    def sentence_at(self, offset: int) -> tuple[int, int]:
        return sentence_containing(self.sentences, offset)

    def scoped_sentence(self, offset: int) -> tuple[str, int, int]:
        """(heading prefix or "", sentence start, sentence end) for the text at `offset`."""
        s_start, s_end = self.sentence_at(offset)
        heading = self.heading_for(offset)
        prefix = self.doc.text[heading[0] : heading[1]] + "\n" if heading else ""
        return prefix, s_start, s_end

    def heading_for(self, offset: int) -> tuple[int, int] | None:
        """The heading line ("Family history:") above the `Label:` entry at `offset`, when
        every sentence between is a `Label:` entry too and no blank line intervenes. The
        heading's cues govern the entry (A-06); the entries between keep their cues local."""
        start, end = self.sentence_at(offset)
        text = self.doc.text
        if not _LABEL_LINE.match(text, start):
            return None
        i = self.sentences.index((start, end))
        while i > 0:
            ps, pe = self.sentences[i - 1]
            if _BLANK_GAP.search(text, pe, start):
                return None
            if _HEADING_ONLY.fullmatch(text, ps, pe):
                return ps, pe
            heading = _HEADING_AT.match(text, ps, pe)
            if heading:
                return ps, heading.end()
            if not _LABEL_LINE.match(text, ps):
                return None
            start = ps
            i -= 1
        return None


def is_table_line(doc: str, start: int, end: int) -> bool:
    """Contract §6: a line touched by the span has `|`, two tabs, or 3+ runs of 3+ spaces."""
    line_start = max(doc.rfind("\n", 0, start), doc.rfind("\r", 0, start)) + 1
    stops = [p for p in (doc.find("\n", end), doc.find("\r", end)) if p != -1]
    line_end = min(stops) if stops else len(doc)
    for line in re.split(r"\r\n|\r|\n", doc[line_start:line_end]):
        if "|" in line or line.count("\t") >= 2 or len(_TABLE_SPACES.findall(line)) >= 3:
            return True
    return False


Span = tuple[int, int]


class _Window:
    """A located span read inside the sentences around it.

    Tokens (numbers, dates, terms, identifiers) are found in the whole window, so their
    boundaries come from the source document, then mapped back to document offsets. A token
    counts for the fact only when it lies completely inside the span: a quote that clips
    `<35.1` to `35.1`, or `heatstroke` to `stroke`, does not contain the token.
    """

    def __init__(self, idx: _DocIndex, start: int, end: int, m: _Matchers) -> None:
        self.idx = idx
        self.doc = idx.doc.text
        self.start, self.end, self.m = start, end, m
        first = idx.sentence_at(start)
        last = idx.sentence_at(max(start, end - 1))
        self.ws, self.we = min(first[0], start), max(last[1], end)
        self.scan_norm = normalize(self.doc[self.ws : self.we], _SCAN_STEPS)
        self.full_norm = normalize(self.doc[self.ws : self.we])

    def _back(self, norm: Normalized, s: int, e: int) -> Span | None:
        span = norm.to_original(s, e)
        return None if span is None else (span[0] + self.ws, span[1] + self.ws)

    def inside(self, span: Span) -> bool:
        return self.start <= span[0] and span[1] <= self.end

    def scan(self, patterns: Patterns) -> list[Hit]:
        """Leftmost-longest hits in the window, in document offsets."""
        out = []
        for h in _leftmost_longest(_scan(self.scan_norm.text, patterns)):
            span = self._back(self.scan_norm, h.start, h.end)
            if span is not None:
                out.append(Hit(span[0], span[1], h.label, h.text, h.entry))
        return out

    def scan_inside(self, patterns: Patterns) -> list[Hit]:
        return [h for h in self.scan(patterns) if self.inside((h.start, h.end))]

    def find(self, needle: str) -> list[Span]:
        """Normalized, word-bounded occurrences of `needle` inside the span."""
        nn = normalize(needle.strip()).text
        text = self.full_norm.text
        out: list[Span] = []
        if not nn:
            return out
        for pos in _find_all(text, nn):
            end = pos + len(nn)
            if nn[0].isalnum() and pos > 0 and text[pos - 1].isalnum():
                continue
            if nn[-1].isalnum() and end < len(text) and text[end].isalnum():
                continue
            span = self._back(self.full_norm, pos, end)
            if span is not None and self.inside(span):
                out.append(span)
        return out

    @cached_property
    def numbers(self) -> list[tuple[str, int, int]]:
        out = []
        for m in _NUMBER.finditer(self.full_norm.text):
            span = self._back(self.full_norm, m.start(), m.end())
            if span is not None:
                out.append((_canonical_number(*m.groups()), *span))
        return out

    @cached_property
    def dates(self) -> list[tuple[str, int, int]]:
        out = []
        for iso, s, e in dates_in(self.full_norm.text):
            span = self._back(self.full_norm, s, e)
            if span is not None:
                out.append((iso, *span))
        return out

    def plain_numbers(self) -> list[Span]:
        """Number tokens that are not part of a date."""
        dates = [(s, e) for _, s, e in self.dates]
        return [
            (s, e) for _, s, e in self.numbers if not any(ds <= s and e <= de for ds, de in dates)
        ]

    @cached_property
    def breaks(self) -> list[Span]:
        """Clause boundaries in document offsets: terminators and gaps between sentences."""
        out = []
        for ts, te in self.m.terminator_positions(self.scan_norm.text):
            span = self._back(self.scan_norm, ts, te)
            if span is not None:
                out.append(span)
        sentences = [s for s in self.idx.sentences if s[1] > self.ws and s[0] < self.we]
        out += [(a[1], b[0]) for a, b in zip(sentences, sentences[1:], strict=False)]
        return out

    def same_clause(self, a: Span, b: Span) -> bool:
        lo, hi = (a[1], b[0]) if a[0] <= b[0] else (b[1], a[0])
        if lo > hi:
            return True  # overlapping
        if self.idx.sentence_at(a[0]) != self.idx.sentence_at(b[0]):
            return False
        return not any(lo <= bs and be <= hi for bs, be in self.breaks)

    def between(self, a: Span, b: Span) -> Span:
        return (a[1], b[0]) if a[0] <= b[0] else (b[1], a[0])

    def label_before(self, value: Span, labels: list[Hit]) -> Hit | None:
        """The nearest label before `value` in its clause with no other number in between."""
        prior = [
            h for h in labels if h.end <= value[0] and self.same_clause((h.start, h.end), value)
        ]
        if not prior:
            return None
        label = max(prior, key=lambda h: h.end)
        if any(label.end <= s and e <= value[0] for s, e in self.plain_numbers()):
            return None
        return label

    def adjacent(self, a: Span, b: Span) -> bool:
        """Only qualifier fillers and punctuation stand between `a` and `b`, same clause."""
        if not self.same_clause(a, b):
            return False
        lo, hi = self.between(a, b)
        gap = unicodedata.normalize("NFKC", self.doc[lo:hi]) if lo < hi else ""
        return self.m.filler.fullmatch(gap) is not None

    def drug_bound(self, drug: Span, other: Span) -> bool:
        """`other` (a date, a dose) belongs to the drug at `drug`.

        Its owner is the nearest drug mention before it in the same clause ("started
        metformin on X and Wegovy on Y": X is metformin's), or, with none before it, the
        nearest one after it. Drug mentions joined only by punctuation ("Semaglutide
        (Wegovy)") are one drug.
        """
        if not self.same_clause(drug, other):
            return False
        mentions = [(h.start, h.end) for h in self.scan(self.m.treatment_patterns)] + [drug]
        mentions = [x for x in mentions if self.same_clause(x, other)]
        before = [x for x in mentions if x[1] <= other[0]]
        after = [x for x in mentions if x[0] >= other[1]]
        if before:
            owner = max(before, key=lambda x: x[1])
        elif after:
            owner = min(after, key=lambda x: x[0])
        else:
            return False
        if owner[0] < drug[1] and drug[0] < owner[1]:
            return True
        return self.adjacent(owner, drug) and not any(
            self.between(owner, drug)[0] <= s and e <= self.between(owner, drug)[1]
            for _, s, e in self.numbers
        )

    def assertion_of(self, span: Span, claimed: Mapping[str, str]) -> AssertionCheck:
        """`check_assertion` for `span` in its sentence, with the heading above a `Label:`
        entry prepended (the same scope `_assert_at` uses for the fact's mention)."""
        prefix, s_start, s_end = self.idx.scoped_sentence(span[0])
        return check_assertion(
            prefix + self.doc[s_start:s_end],
            (len(prefix) + span[0] - s_start, len(prefix) + min(span[1], s_end) - s_start),
            claimed,
            self.m.cues,
            terms=self.m.terms,
        )

    def identifiers(self) -> list[tuple[str, str, Span]]:
        """(type, canonical identifier, span) for every labelled identifier whose label or
        value touches the span. The identifier is read in full from the source, so a quote
        that clips `P-0001-A` to `P-0001` still yields `P-0001-A`."""
        out: list[tuple[str, str, Span]] = []
        for pattern, kind in self.m.id_patterns:
            for match in pattern.finditer(self.scan_norm.text):
                raw = match.group(1)
                end = match.end(1) - (len(raw) - len(raw.rstrip(_ID_TRAIL)))
                span = self._back(self.scan_norm, match.start(1), end)
                label = self._back(self.scan_norm, match.start(), match.start(1))
                if span is None or label is None:
                    continue
                ident, resolvable = _id_token(raw)
                if label[0] < self.end and self.start < span[1]:
                    out.append((kind if resolvable else "unresolved", ident, span))
        # A longer label wins at the same identifier ("Medicare ID" over "ID").
        best: dict[Span, tuple[str, str, Span]] = {}
        for item in out:
            best.setdefault(item[2], item)
        return list(best.values())

    def dobs(self) -> list[tuple[str, Span]]:
        """(ISO date, span) for every day-precision date after a DOB label in the window
        whose label or value touches the span, with no other date between label and date."""
        labels = self.scan(self.m.dob_patterns)
        out = []
        for iso, s, e in self.dates:
            if len(iso) != 10:
                continue
            prior = [h for h in labels if h.end <= s and self.same_clause((h.start, h.end), (s, e))]
            if not prior:
                continue
            label = max(prior, key=lambda h: h.end)
            if any(label.end <= ds and de <= s for _, ds, de in self.dates):
                continue
            if label.start < self.end and self.start < e:
                out.append((iso, (s, e)))
        return out

    def subject_certainty(self, span: Span) -> tuple[str | None, str | None]:
        check = self.assertion_of(span, _CLAIM_PRESENT)
        return check.checked["subject"], check.checked["certainty"]

    def axes(self, span: Span) -> tuple[str | None, str | None, str | None]:
        """(subject, certainty, temporality) the cues give for the text at `span`."""
        checked = self.assertion_of(span, _CLAIM_PRESENT).checked
        return checked["subject"], checked["certainty"], checked["temporality"]

    def event_drug_bound(self, event: Span, drugs: list[Span]) -> bool:
        """The event word at `event` describes one of `drugs`: its nearest drug mention in
        the clause (before it, else after it) is one of them ("Metformin was started and
        Wegovy was continued": `started` is metformin's)."""
        mentions = [
            (h.start, h.end)
            for h in self.scan(self.m.treatment_patterns)
            if self.same_clause((h.start, h.end), event)
        ] + [d for d in drugs if self.same_clause(d, event)]
        others = [x for x in mentions if not (x[0] < event[1] and event[0] < x[1])]
        if not others:
            return False
        # The drug right after the verb with only object fillers between is its object
        # ("started taking metformin"); otherwise the nearest mention on either side.
        objects = [
            x
            for x in others
            if x[0] >= event[1]
            and self.m.event_object.fullmatch(
                unicodedata.normalize("NFKC", self.doc[event[1] : x[0]])
            )
        ]
        if objects:
            owner = min(objects, key=lambda x: x[0])
        else:
            owner = min(others, key=lambda x: min(abs(x[0] - event[1]), abs(event[0] - x[1])))
        return any((owner[0] < d[1] and d[0] < owner[1]) or self.adjacent(owner, d) for d in drugs)

    def actual(self, span: Span) -> bool:
        """The text at `span` asserts something the patient actually has or did: present,
        patient, and not hypothetical ("would be started", "may develop")."""
        checked = self.assertion_of(span, _CLAIM_PRESENT).checked
        return (
            checked["certainty"] == "present"
            and checked["subject"] == "patient"
            and checked["temporality"] not in (None, "hypothetical")
        )

    def measurement(self, s: int, e: int, kind: str) -> bool:
        """The number token at [s, e) is an absolute measurement of `kind`: not part of a
        date, not an ordinal or a percentile (unless `kind` is a percentile), not one end
        of a range ("28-36.5")."""
        if any(ds <= s and e <= de for _, ds, de in self.dates):
            return False
        after = self.doc[e : self.we]
        before = self.doc[self.ws : s]
        ordinal = _ORDINAL.match(after) is not None
        percentile = any(
            h.start - e <= 2 and not self.doc[e : h.start].strip(" \t") and h.start >= e
            for h in self.scan(self.m.percentile_patterns)
        ) or (
            ordinal
            and any(
                h.start >= e and h.start - e <= 14 for h in self.scan(self.m.percentile_patterns)
            )
        )
        if kind == "bmi_percentile":
            return percentile
        if ordinal or percentile:
            return False
        norm_after = unicodedata.normalize("NFKC", after)
        norm_before = unicodedata.normalize("NFKC", before)
        for dash in "\u2010\u2011\u2012\u2013\u2014\u2015\u2212":
            norm_after = norm_after.replace(dash, "-")
            norm_before = norm_before.replace(dash, "-")
        if _DASH_NUMBER_AFTER.match(norm_after) or _DASH_NUMBER_BEFORE.search(norm_before):
            return False
        # Bounds and ranges written in words: "below 36.5", "28 to 36.5", "between 28 and 36.5".
        m = self.m
        if m.bound_before.search(norm_before) or m.range_opener_before.search(norm_before):
            return False
        return not (m.range_after.match(norm_after) or m.range_before.search(norm_before))

    def value_bound(self, anchor: Span, other: Span) -> bool:
        """`other` (a date) belongs to the value at `anchor`: same clause, and no other
        number, value label or treatment term stands between them."""
        if not self.same_clause(anchor, other):
            return False
        lo, hi = self.between(anchor, other)
        if any(lo <= s and e <= hi for s, e in self.plain_numbers()):
            return False
        if any(lo <= s and e <= hi for _, s, e in self.dates):
            return False
        hits = self.scan(self.m.label_patterns) + self.scan(self.m.treatment_patterns)
        return not any(lo <= h.start and h.end <= hi for h in hits)

    def event_of(self, date: Span) -> Hit | None:
        """The event word (start / restart / stop) the date at `date` belongs to: the nearest
        one before it in the clause with no other date between, else the nearest after."""
        events = [
            h
            for h in self.scan(self.m.event_patterns)
            if self.same_clause((h.start, h.end), date)
            and not (h.start < date[1] and date[0] < h.end)
        ]
        if not events:
            return None

        def clear(h: Hit, *, coordinators: bool) -> bool:
            """Nothing stands between the event word and the date that would attach the date
            elsewhere: another event word, another date, or (when asked) a coordinator."""
            lo, hi = self.between((h.start, h.end), date)
            if any(lo <= o.start and o.end <= hi for o in events if o is not h):
                return False
            if any(lo <= s and e <= hi for _, s, e in self.dates):
                return False
            gap = self.doc[lo:hi]
            return not (
                coordinators and ("," in gap or any(p.search(gap) for p in self.m.coordinators))
            )

        # An action phrase reads "<verb> [drug] on <date>" or "on <date> <verb> ...": the date
        # belongs to the nearest event word on either side that no coordinator separates from
        # it, a preceding one first ("Stopped metformin on <date> and started ..."), else a
        # following one ("on <date> it was stopped"). "Continued metformin on <date> and
        # started ..." leaves the date with no event word: unrecognized.
        before = [h for h in events if h.end <= date[0] and clear(h, coordinators=True)]
        if before:
            return max(before, key=lambda h: h.end)
        after = [h for h in events if h.start >= date[1] and clear(h, coordinators=True)]
        return min(after, key=lambda h: h.start) if after else None

    def id_tokens(self) -> list[tuple[str, Span]]:
        """(canonical identifier, span) of every resolvable whitespace-delimited token inside
        the span, trailing punctuation removed."""
        out = []
        for match in _ID_TOKEN.finditer(self.scan_norm.text):
            raw = match.group(0)
            ident, resolvable = _id_token(raw)
            end = match.end() - (len(raw) - len(raw.rstrip(_ID_TRAIL)))
            span = self._back(self.scan_norm, match.start(), end)
            if resolvable and span is not None and self.inside(span):
                out.append((ident, span))
        return out


_CLAIM_PRESENT = {"certainty": "present", "subject": "patient", "temporality": "current"}


@dataclass
class _ValueCheck:
    reasons: list[str] = dc_field(default_factory=list)
    anchors: list[Span] = dc_field(default_factory=list)
    flags: list[str] = dc_field(default_factory=list)
    identifiers: list[list[str | None]] = dc_field(default_factory=list)
    """Per labelled identifier: [type, canonical id, subject_checked, certainty_checked]."""
    dobs: list[list[str | None]] = dc_field(default_factory=list)
    """Per labelled date of birth: [ISO date, subject_checked, certainty_checked]."""
    event_date_source: str | None = None
    quote_date: dict[str, str] | None = None
    """The quote's own bound date at the text's precision; None when it names none."""
    list_status: str | None = None
    """For a medication list: `current`, `discontinued` or `unknown` from its heading."""

    def unrecognized(self) -> None:
        if "unrecognized" not in self.flags:
            self.flags.append("unrecognized")

    def need(self, found: Sequence[Span], *, anchor: bool = False) -> None:
        if not found:
            if "value_not_in_quote" not in self.reasons:
                self.reasons.append("value_not_in_quote")
        elif anchor and not self.anchors:
            self.anchors = list(found)


def _bound_numbers(w: _Window, accept: Callable[[str], bool], kind: str, unit: str) -> list[Span]:
    """Number tokens inside the span that `accept` and that belong to this fact: followed by
    `unit` (when given) and, when a value label precedes them, labelled with `kind`."""
    labels = w.scan(w.m.label_patterns)
    units = w.find(unit) if unit.strip() else []
    out = []
    for tok, s, e in w.numbers:
        if not accept(tok) or not w.inside((s, e)) or not w.measurement(s, e, kind):
            continue
        if unit.strip() and not any(
            0 <= u[0] - e <= 3 and not w.doc[e : u[0]].strip(" \t| ") for u in units
        ):
            continue
        label = w.label_before((s, e), labels)
        # A percentile is labelled "BMI" too ("BMI 36th percentile").
        kinds = {kind, "bmi"} if kind == "bmi_percentile" else {kind}
        if label is not None and label.label not in kinds:
            continue
        if label is None and not unit.strip() and kind != "bmi_percentile":
            continue
        out.append((s, e))
    return out


def check_values(fact_field: str, fact: Fact, w: _Window, docs: Docs | None = None) -> _ValueCheck:
    """Layer 3: the raw value as written must be readable from the located span, as a whole
    token, and bound to the fact it describes (06 §3)."""
    vc = _ValueCheck()
    m = w.m
    d: dict[str, Any] = fact.model_dump()

    def dates_equal(iso: str) -> list[Span]:
        return [(s, e) for found, s, e in w.dates if found == iso and w.inside((s, e))]

    def event_dates(name: str, drugs: list[Span], wanted: str) -> None:
        """A drug date bound, through its nearest event word, to an actual `wanted` event of
        this drug. No event word at all → `unrecognized`; another event (a restart for a
        start), a negated or hypothetical one, or one that governs another drug → not in
        the quote."""
        if not d.get(name):
            return
        # The date belongs to its nearest event word, and the event word to its nearest drug:
        # "continued Wegovy and on <date> started metformin" is metformin's start.
        bound = dates_equal(d[name])
        events = [(x, w.event_of(x)) for x in bound]
        if bound and all(ev is None for _, ev in events):
            vc.unrecognized()
            return
        good = [
            x
            for x, ev in events
            if ev is not None
            and ev.label == wanted
            and w.actual((ev.start, ev.end))
            and w.event_drug_bound((ev.start, ev.end), drugs)
        ]
        if wanted == "start" and any(
            h.label == "restart" and any(w.same_clause((h.start, h.end), a) for a in drugs)
            for h in w.scan(m.event_patterns)
        ):
            good = []  # a documented resumption is not an initiation (contract §5)
        vc.need(good)

    if fact_field in ("anthropometrics", "labs"):
        canonical = parse_raw_number(d["raw_value"])
        if canonical is None:
            vc.reasons.append("unparseable_value")
        else:
            found = _bound_numbers(w, lambda t: t == canonical, d["kind"], d["raw_unit"])
            vc.need(found, anchor=True)
    elif fact_field == "bp_readings":
        # No comparator before the reading: `BP <145/98` is not a reading of 145/98.
        pattern = re.compile(
            rf"(?<![\d<>=\u2264\u2265])(?<![<>=\u2264\u2265]\s)(?<!\d\.)"
            rf"{d['sbp']}\s*(?:/|over)\s*{d['dbp']}(?!\d)(?!\.\d)"
        )
        found = []
        non_measurement = w.scan(m.bp_non_measurement)
        for match in pattern.finditer(w.full_norm.text):
            span = w._back(w.full_norm, match.start(), match.end())
            if span is None or not w.inside(span):
                continue
            # "BP goal 145/98": the nearest such word before the pair, with no number between.
            if any(
                h.end <= span[0]
                and w.same_clause((h.start, h.end), span)
                and not any(h.end <= s and e <= span[0] for s, e in w.plain_numbers())
                for h in non_measurement
            ):
                continue
            found.append(span)
        vc.need(found, anchor=True)
    elif fact_field == "diagnoses":
        mentions: list[Span] = []
        if d["concept"] != "other":
            mentions = [
                (h.start, h.end)
                for h in w.scan_inside(m.concept_patterns)
                if h.label == d["concept"]
            ]
            vc.need(mentions, anchor=True)

        def qualifier(found: list[Span]) -> None:
            vc.need([q for q in found if any(w.adjacent(q, x) for x in mentions)])

        if d["ckd_stage"]:
            qualifier(w.find(d["ckd_stage"]))
        if d["fibrosis_stage"]:
            qualifier(w.find(d["fibrosis_stage"]))
        if d["osa_severity"] != "unspecified":
            qualifier(w.find(d["osa_severity"]))
        if d["ahi"] is not None:
            value = Decimal(str(d["ahi"]))
            vc.need(_bound_numbers(w, lambda t: t[0].isdigit() and Decimal(t) == value, "ahi", ""))
        if d["symptomatic"] != "unknown" and d["concept"] == "pad":
            vc.need(_qualified(w, mentions, d["symptomatic"] == "yes", "symptom"))
        if d["cirrhosis"] is not None:
            vc.need(_qualified(w, mentions, bool(d["cirrhosis"]), "cirrhosis"))
    elif fact_field == "medications":
        drugs = w.find(d["name"])
        vc.need(drugs, anchor=True)
        if d["dose"].strip():
            vc.need([x for x in w.find(d["dose"]) if any(w.drug_bound(a, x) for a in drugs)])
        event_dates("start", drugs, "start")
        event_dates("end", drugs, "stop")
        if d["end_kind"] == "ongoing":
            # An end date, or an actual stop event of this drug in its source clause (also
            # outside a clipped quote), contradicts "ongoing".
            stopped = [
                h
                for h in w.scan(m.event_patterns)
                if h.label == "stop"
                and w.actual((h.start, h.end))
                and w.event_drug_bound((h.start, h.end), drugs)
            ]
            if d.get("end") or stopped:
                vc.need([])
    elif fact_field in ("glp1_start", "prior_glp1"):
        drugs = w.find(d["drug"])
        vc.need(drugs, anchor=True)
        if fact_field == "glp1_start":
            event_dates("date", drugs, "start")
            # Purpose (contract §3.4 MACE downgrade): a cue in the drug's clause is required;
            # a `mace` cue with any other claimed purpose excludes the fact.
            # Read from the drug's whole source clause: a quote clipped before "to reduce
            # major adverse cardiovascular events" must not hide the cue.
            cues = [
                h
                for h in w.scan(m.purpose_patterns)
                if any(w.same_clause((h.start, h.end), a) for a in drugs)
            ]
            if any(h.label == "mace" for h in cues) and d["purpose"] != "mace":
                vc.need([])
            elif d["purpose"] != "unknown" and not any(h.label == d["purpose"] for h in cues):
                vc.unrecognized()
        elif d.get("date"):
            vc.need([x for x in dates_equal(d["date"]) if any(w.drug_bound(a, x) for a in drugs)])
    elif fact_field == "patient_identity":
        labelled = w.identifiers()
        for kind, ident, span in labelled:
            vc.identifiers.append([kind, ident, *w.axes(span)])
        if d["patient_id"].strip():
            wanted = canonical_id(d["patient_id"])
            whole = [span for ident, span in w.id_tokens() if ident == wanted]
            vc.need(whole, anchor=True)
            for span in whole:
                if span not in {x for _, _, x in labelled}:
                    vc.identifiers.append([id_type(d["patient_id"]), wanted, *w.axes(span)])
        dobs = w.dobs()
        for iso, span in dobs:
            vc.dobs.append([iso, *w.axes(span)])
        if d["dob"]:
            vc.need([span for iso, span in dobs if iso == d["dob"] and w.inside(span)])
        if d["stated_age"] is not None:
            age = str(d["stated_age"])
            before = w.scan(m.age_patterns)
            after = w.scan(m.age_suffix_patterns)
            found = []
            for tok, s, e in w.numbers:
                if tok != age or not w.inside((s, e)):
                    continue
                age_label = w.label_before((s, e), before)
                suffix = any(
                    0 <= h.start - e <= 1 and not w.doc[e : h.start].strip(" -") for h in after
                )
                if (age_label is not None and age_label.label == "age") or suffix:
                    found.append((s, e))
            vc.need(found, anchor=True)
    elif fact_field == "doc_dates":
        # The quote must name the target document (contract §5 item 3), by doc_id or by a word
        # for its role, and the date must be the one bound to that name: nearest, with no
        # other date or document name between. Another document's doc_id dates that document;
        # no name at all → unrecognized.
        target = d["target_doc_id"]
        others = {canonical_id(x) for x in (docs or {}) if x != target}
        tokens = w.id_tokens()
        role = docs[target].role if docs and target in docs else None
        # Every document name in the window, labelled `target` or `other`.
        names: list[tuple[Span, str]] = [
            (span, "target" if ident == canonical_id(target) else "other")
            for ident, span in tokens
            if ident == canonical_id(target) or ident in others
        ]
        for r, patterns in m.role_patterns.items():
            names += [
                ((h.start, h.end), "target" if r == role else "other") for h in w.scan(patterns)
            ]
        names = [
            ((h.start, h.end), h.label)
            for h in _leftmost_longest(Hit(a, b, lab, "") for (a, b), lab in names)
        ]

        def possessed(n: Span) -> bool:
            """A target name right after another document's name ("the referral's case
            summary") describes that document, not the target."""
            src_text = w.idx.doc.text
            for o, lab in names:
                if lab == "other" and o[1] <= n[0] and _POSSESSIVE.fullmatch(src_text, o[1], n[0]):
                    return True
            return False

        possessed_target = any(lab == "target" and possessed(n) for n, lab in names)
        names = [(n, "other" if lab == "target" and possessed(n) else lab) for n, lab in names]

        named_by_id = any(ident == canonical_id(target) for ident, _ in tokens)
        same_role = sum(1 for x in (docs or {}).values() if role is not None and x.role == role)
        if any(ident in others for ident, _ in tokens) or possessed_target:
            vc.need([])  # names (or possesses) another document: that document's date
        elif not any(lab == "target" and w.inside(span) for span, lab in names):
            vc.need(dates_equal(d["date"]), anchor=True)
            vc.unrecognized()
        elif (
            not named_by_id
            and target != fact.doc_id
            and not any(lab == "target" for _n, lab in _attached_only(w, names, m))
        ):
            # "the case summary dated X" in a referral may describe the referral itself; only
            # an attached document of that role is the target (contract §5 item 3).
            vc.need(dates_equal(d["date"]), anchor=True)
            vc.unrecognized()
        elif not named_by_id and same_role > 1:
            # "the consult" with two clinical documents: the reference is not unique.
            vc.need(dates_equal(d["date"]), anchor=True)
            vc.unrecognized()
        else:
            if not named_by_id and target != fact.doc_id:
                # Only the mention that carries the affirmed attachment can own the date;
                # another mention of the same role in the quote dates nothing.
                names = _attached_only(w, names, m)

            def owner(x: Span) -> str | None:
                """Label of the nearest document name to the date in its clause with no other
                date between them ("letter dated X encloses the D2 note dated Y": Y is D2's)."""
                best: tuple[int, str] | None = None
                for n, lab in names:
                    if not w.same_clause(n, x):
                        continue
                    lo, hi = w.between(n, x)
                    if any(lo <= s and e <= hi for _, s, e in w.dates):
                        continue
                    distance = hi - lo
                    if best is None or distance < best[0]:
                        best = (distance, lab)
                return None if best is None else best[1]

            vc.need([x for x in dates_equal(d["date"]) if owner(x) == "target"], anchor=True)
    elif fact_field == "medication_lists":
        if d["section_title"].strip():
            vc.need(w.find(d["section_title"]), anchor=True)
        heading = d["section_title"].strip()
        if not heading:
            first_line = w.idx.doc.text[w.start : w.end].split("\n", 1)[0]
            heading = first_line.split(":", 1)[0] if ":" in first_line else ""
        statuses = {h.label for h in _scan(normalize(heading).text, m.list_status_patterns)}
        if "discontinued" in statuses:
            vc.list_status = "discontinued"
        elif "current" in statuses:
            vc.list_status = "current"
        else:
            vc.list_status = "unknown"
    elif fact_field == "pa_form_claims":
        # A field of the draft is `<label>: <options>` on one line. The value counts only on
        # the PA draft, only when the whole label of its field is a label of the claimed box
        # (guide K-01, K-02) and the field asks the qualifying question (no blocker word), and,
        # when the field offers several answers, only when the claimed one is the single
        # marked one; an unmarked or doubly marked field is kept as `unrecognized` (review).
        values = w.find(d["claimed_value"])
        role = docs[fact.doc_id].role if docs and fact.doc_id in docs else None
        text = w.idx.doc.text

        def field_of(pos: int) -> tuple[int, int, int] | None:
            """(label start, colon, field end) of the `<label>: <options>` field at `pos`."""
            ls = text.rfind("\n", 0, pos) + 1
            le = text.find("\n", pos)
            le = len(text) if le < 0 else le
            colon = text.rfind(":", ls, pos)
            if colon < 0:
                return None
            label_start = text.rfind(":", ls, colon)
            label_start = ls if label_start < 0 else _next_label_start(text, label_start + 1, colon)
            nxt = text.find(":", pos, le)
            field_end = le if nxt < 0 else _next_label_start(text, pos, nxt)
            return label_start, colon, field_end

        own_fields: list[tuple[int, int, int]] = []
        blocked = False
        for v in values:
            fld = field_of(v[0])
            if fld is None:
                continue
            label = normalize(text[fld[0] : fld[1]].strip()).text.casefold()
            if label not in m.claim_labels.get(d["claim_id"], ()):
                continue  # another box, or no box at all: not this claim's value
            if any(p.search(label) for p, _, _ in m.claim_blocker_patterns):
                blocked = True  # the qualifying words, but about a relative or another stage
            else:
                own_fields.append(fld)
        if role != "pa_draft" or (blocked and not own_fields):
            vc.unrecognized()
            vc.need(values, anchor=True)
        elif not own_fields:
            vc.need([])  # the value sits in no field of this claim
        else:
            fld = own_fields[0]
            options = text[fld[1] + 1 : fld[2]]
            offered = sum(1 for p, _, _ in m.answer_patterns for _m in p.finditer(options))
            boxes_text = _box_norm(options)
            marks = sum(boxes_text.count(mk) for mk in m.answer_markers)
            empties = sum(boxes_text.count(mk) for mk in m.empty_markers)
            bound = [v for v in values if field_of(v[0]) == fld]

            def marked(v: Span) -> bool:
                lead = _box_norm(text[max(fld[1] + 1, v[0] - 8) : v[0]]).rstrip()
                return any(lead.endswith(mk) for mk in m.answer_markers)

            choice = offered > 1 or marks > 0 or empties > 0
            if choice and (marks != 1 or not any(marked(v) for v in bound)):
                vc.unrecognized()  # the field offers choices and the selection is not clear
            vc.need(bound, anchor=True)
    elif fact_field == "lifestyle":
        # Each value needs a cue in the quote (contract §3.5); without one it is unrecognized,
        # like a non-default assertion without a cue. `description` is a summary: not checked.
        for axis in ("program_type", "attendance", "end_kind"):
            value = d[axis]
            labels = {h.label for h in w.scan_inside(m.lifestyle_patterns[axis])}
            if value == "unknown":
                if labels:
                    vc.unrecognized()  # the text states it ("completed"); the extraction did not
                continue
            # No cue for the value, or cues for two values ("referred to a dietitian"):
            # the text does not settle it.
            if value not in labels or len(labels) > 1:
                vc.unrecognized()
        for name in ("start", "end"):
            if d.get(name):
                vc.need(dates_equal(d[name]))

    # What the quote itself says about the date, whatever the model wrote (or omitted).
    vc.quote_date = quote_date_attribute(quote_dates(w, vc))
    if fact.event_date:
        vc.event_date_source = _event_date(fact.event_date, quote_dates(w, vc), vc)
    return vc


def _qualified(w: _Window, mentions: list[Span], yes: bool, what: str) -> list[Span]:
    """Evidence for a yes/no qualifier in the sentence of a diagnosis mention: an affirmed
    term for yes; a contrary term ("asymptomatic", "non-cirrhotic") or a negated term for no."""
    m = w.m
    positive, contrary = (
        (m.symptom_patterns, m.asymptomatic_patterns)
        if what == "symptom"
        else (m.cirrhosis_patterns, m.noncirrhotic_patterns)
    )

    def near(h: Hit) -> bool:
        """Same clause as a diagnosis mention and about the patient."""
        same = any(w.same_clause((h.start, h.end), x) for x in mentions)
        return same and w.subject_certainty((h.start, h.end))[0] == "patient"

    terms = [h for h in w.scan_inside(positive) if near(h)]
    against = [h for h in w.scan_inside(contrary) if near(h)]
    if yes:
        if against:
            return []
        # The symptom must be actual, not hypothetical ("may develop claudication").
        return [(h.start, h.end) for h in terms if w.actual((h.start, h.end))]
    return [(h.start, h.end) for h in against] + [
        (h.start, h.end) for h in terms if w.subject_certainty((h.start, h.end))[1] == "negated"
    ]


_PRECISION_BY_LENGTH = {4: "year", 7: "month", 10: "day"}


def quote_dates(w: _Window, vc: _ValueCheck) -> list[str]:
    """ISO dates inside the quote that belong to the fact: bound to its mention (nearest, with
    no other number, date, value label or drug between), or any date in the quote when the
    fact has no located mention. Independent of the model's `event_date`."""
    inside = [(iso, (s, e)) for iso, s, e in w.dates if w.inside((s, e))]
    if vc.anchors:
        inside = [(iso, x) for iso, x in inside if any(w.value_bound(a, x) for a in vc.anchors)]
    return [iso for iso, _ in inside]


def quote_date_attribute(dates: list[str]) -> dict[str, str] | None:
    """`{"date", "precision"}` for the quote's own date (contract §5): the first bound date, at
    the precision the text gives; None when the quote names no date."""
    if not dates:
        return None
    return {"date": dates[0], "precision": _PRECISION_BY_LENGTH[len(dates[0])]}


def _event_date(event_date: str, dates: list[str], vc: _ValueCheck) -> str:
    """`llm` when a date in the quote that belongs to the fact equals `event_date`; `none`
    when the quote holds no such date. A bound date that differs is `value_not_in_quote`."""
    if not dates:
        return "none"
    if event_date in dates:
        return "llm"
    if "value_not_in_quote" not in vc.reasons:
        vc.reasons.append("value_not_in_quote")
    return "none"


# --- One fact ---------------------------------------------------------------------------------


def _claimed(fact: Fact) -> dict[str, str]:
    return {"certainty": fact.certainty, "subject": fact.subject, "temporality": fact.temporality}


_EMPTY_BOX = re.compile(r"([\[(])\s*([\])])")
_MARKED_BOX = re.compile(r"([\[(])\s*([xX✓✔])\s*([\])])")


def _box_norm(text: str) -> str:
    """Checkbox syntax in a comparable form: NFKC (full-width brackets), case-folded, one
    space inside an empty box and none inside a marked one."""
    out = unicodedata.normalize("NFKC", text).casefold()
    out = _EMPTY_BOX.sub(r"\1 \2", out)
    return _MARKED_BOX.sub(r"\1\2\3", out)


# Between an attachment cue and the document it governs: "I enclose the hospital summary",
# "the enclosed bariatric surgery consultation note", "a copy of the consult note": at most
# three descriptive words, no coordinator, comma or clause break.
_CUE_THEN_NAME = re.compile(
    r"^\W*(?:(?!(?:and|or|plus|nor)\b)[\w'’.-]+[ \t]+){0,3}$", re.IGNORECASE
)
# Between a document name and a trailing cue ("the consult note dated X is attached"): only a
# copula, the name's own date phrase and date tokens may stand there.
_COPULA_WORDS = frozenset(
    {"is", "are", "was", "were", "has", "have", "been", "now", "also", "dated", "of", "from", "on"}
)


def _name_then_cue(gap: str) -> bool:
    for tok in gap.split():
        word = tok.strip(".,;:()").casefold()
        if word in _COPULA_WORDS or any(ch.isdigit() for ch in word) or word in _MONTHS:
            continue
        return False
    return True


def _attached_only(
    w: _Window, names: list[tuple[Span, str]], m: _Matchers
) -> list[tuple[Span, str]]:
    """`names` with every target mention that no cue affirms as attached relabelled
    `unattached`: it neither dates the target nor counts as naming another document."""
    cues = w.scan(m.attachment_patterns)
    text = w.idx.doc.text
    merged: list[tuple[Span, str]] = []
    for n, lab in sorted(names):
        # adjacent target words ("consultation" + "note") are one mention of the document
        if merged and lab == "target" and merged[-1][1] == "target":
            prev = merged[-1][0]
            if not text[prev[1] : n[0]].strip():
                merged[-1] = ((prev[0], n[1]), lab)
                continue
        merged.append((n, lab))
    out: list[tuple[Span, str]] = []
    for n, lab in merged:
        if lab == "target" and not any(_attached(w, a, n, names, m) for a in cues):
            out.append((n, "unattached"))
        else:
            out.append((n, lab))
    return out


def _attached(w: _Window, a: Hit, n: Span, names: list[tuple[Span, str]], m: _Matchers) -> bool:
    """`a` ("enclosed", "attached") affirms that the document named at `n` is attached: an
    affirmative construction with no other document name in between, and none of the words
    that deny, request or promise an attachment in the four words before the cue."""
    span_a = (a.start, a.end)
    if not w.same_clause(span_a, n):
        return False
    text = w.idx.doc.text
    lo, hi = w.between(span_a, n)
    if any(lo <= o[0] and o[1] <= hi for o, _lab in names if o != n):
        return False
    gap = text[lo:hi]
    affirmed = _CUE_THEN_NAME.match(gap) if a.start < n[0] else _name_then_cue(gap)
    if not affirmed:
        return False
    sentence_start = w.idx.sentence_at(a.start)[0]
    lead = text[max(sentence_start, a.start - 60) : a.start].casefold().split()[-4:]
    if any(tok.strip(".,;:()") in m.attachment_negations for tok in lead):
        return False
    if a.text.casefold() in m.attachment_finite:
        # a finite verb affirms only with an explicit subject right before it ("I enclose",
        # "this letter encloses"); an imperative, bare or after an adverb or a clause ("Then
        # attach", "After review, attach"), is a request, not an attachment
        raw = lead[-1] if lead else ""
        if raw.endswith((",", ";", ":")):
            return False
        return raw.strip(".()") in m.attachment_subjects
    return True


def _next_label_start(text: str, lo: int, colon: int) -> int:
    """Start of the label that ends at `colon`: after the options of the previous field, which
    end at the last run of two or more spaces (or a tab) before the label."""
    gap = max(text.rfind("  ", lo, colon), text.rfind("\t", lo, colon))
    return lo if gap < 0 else gap + 1


def _claim_assertion(fact: Fact) -> AssertionCheck:
    """`matched` when the model gave the default axes for a PA-form box, else `mismatch`."""
    claimed = _claimed(fact)
    result = "matched" if claimed == dict(AXIS_DEFAULTS) else "mismatch"
    return AssertionCheck(
        result,
        dict(AXIS_DEFAULTS),
        {axis: "matched" if claimed[axis] == AXIS_DEFAULTS[axis] else "mismatch" for axis in AXES},
    )


def _unrecognized() -> AssertionCheck:
    return AssertionCheck("unrecognized", dict.fromkeys(AXES), dict.fromkeys(AXES, "unrecognized"))


def _assert_at(
    idx: _DocIndex,
    start: int,
    end: int,
    vc: _ValueCheck,
    fact: Fact,
    concept: str | None,
    ctx: VerifyContext,
) -> tuple[AssertionCheck, list[dict[str, Any]]]:
    """Layer 4 for the span [start, end): each mention checked in its own sentence."""
    text = idx.doc.text
    mentions = [(s, e, False) for s, e in vc.anchors] or [(start, end, True)]
    checks: list[AssertionCheck] = []
    detail: list[dict[str, Any]] = []
    for ms, me, whole in mentions:
        s_start, s_end = idx.sentence_at(ms)
        if whole and me > s_end:
            # A whole-span mention crossing a sentence end: the scope cannot be decided.
            checks.append(_unrecognized())
            detail.append({"start": ms, "end": me, "result": "unrecognized"})
            continue
        # A heading above a `Label:` entry is prepended to the entry's sentence, without the
        # entries between, so its cues reach the mention and theirs do not.
        prefix, _, _ = idx.scoped_sentence(ms)
        check = check_assertion(
            prefix + text[s_start:s_end],
            (len(prefix) + ms - s_start, len(prefix) + min(me, s_end) - s_start),
            _claimed(fact),
            ctx.cues,
            terms=ctx.terms,
            concept=concept,
            whole_span=whole,
        )
        checks.append(check)
        detail.append({"start": ms, "end": me, "result": check.result})
    if len({c.key() for c in checks}) == 1:
        return checks[0], detail
    # Mentions disagree: which one the model meant cannot be decided.
    return _unrecognized(), detail


def _type_specific(fact: Fact) -> dict[str, Any]:
    return {
        k: v
        for k, v in fact.model_dump(mode="json").items()
        if k not in _SHARED_FACT_FIELDS and k not in _COLUMN_FIELDS
    }


def _unique(items: list[list[str | None]]) -> list[list[str | None]]:
    seen: set[tuple[str | None, ...]] = set()
    out = []
    for item in items:
        if tuple(item) not in seen:
            seen.add(tuple(item))
            out.append(item)
    return out


UNRESOLVED_DOC = "unresolved-doc"
"""Placeholder for a `doc_id` that names no input document. The model's value could be
copied chart text, so it never appears in `ref` (public outputs)."""


def verify_fact(
    fact_field: str,
    fact_path: str,
    fact: Fact,
    docs: Docs,
    ctx: VerifyContext,
    indexes: dict[str, _DocIndex],
) -> CheckedEvidence:
    """Position → layer 3 → layer 4 → flags for one fact (document-level steps come later)."""
    d = fact.model_dump()
    concept = d.get("concept")
    attributes: dict[str, Any] = _type_specific(fact)
    doc = docs.get(fact.doc_id)
    base: dict[str, Any] = {
        "field": fact_field,
        "fact_path": fact_path,
        "kind": d.get("kind"),
        "concept": concept,
        "doc_id": fact.doc_id,
        "doc_sha256": doc.sha256 if doc is not None else "",
        "quote": fact.quote,
        "raw_value": d.get("raw_value"),
        "raw_unit": d.get("raw_unit"),
        "event_date": fact.event_date or None,
        "date_precision": None if fact.date_precision == "none" else fact.date_precision,
        "certainty_llm": fact.certainty,
        "subject_llm": fact.subject,
        "temporality_llm": fact.temporality,
        "relative_llm": fact.relative_to_glp1_initiation,
    }

    def not_found() -> CheckedEvidence:
        public_doc = fact.doc_id if doc is not None else UNRESOLVED_DOC
        if doc is None:
            attributes["doc_unresolved"] = True
        return CheckedEvidence(
            **base,
            start=None,
            end=None,
            certainty_checked=None,
            subject_checked=None,
            temporality_checked=None,
            position_status="not_found",
            assertion_check=None,
            exclusion_reasons=("quote_not_found",),
            flags=(),
            ref=f"{public_doc}[-:-] {sha8(fact.quote)}",
            attributes=attributes,
        )

    if doc is None:
        return not_found()
    idx = indexes.setdefault(doc.doc_id, _DocIndex(doc))
    text = doc.text

    # Every occurrence counts for the repeated-quote rule and for identity screening:
    # verbatim hits first, then normalization-equivalent ones ("MRN:" also finds "mrn:").
    status = "verbatim"
    verbatim = locate(text, fact.quote)
    spans = verbatim + [x for x in locate_normalized(idx.norm, fact.quote) if x not in verbatim]
    if not verbatim:
        status = "normalized"
    if spans:
        if status == "normalized":
            attributes["normalizations"] = needed_normalizations(fact.quote, text[slice(*spans[0])])
    else:
        cand = find_candidate(idx.norm, fact.quote)
        if cand is None:
            return not_found()
        spans = [(cand[0], cand[1])]
        status = "candidate"
        attributes["candidate_ratio"] = cand[2]

    matchers = _matchers(ctx.cues, ctx.terms)
    results = []
    for s, e in spans:
        vc = check_values(fact_field, fact, _Window(idx, s, e, matchers), docs)
        if fact_field == "pa_form_claims":
            # A box on the PA draft is a claim, not an assertion about the patient (guide
            # K-01): its three axes are the defaults and the cue words of the form ("No",
            # "previous") are the box's wording, not negations or history.
            check, detail = _claim_assertion(fact), [{"start": s, "end": e, "result": None}]
        else:
            check, detail = _assert_at(idx, s, e, vc, fact, concept, ctx)
        results.append((s, e, vc, check, detail))

    flags: list[str] = []
    if len(spans) > 1:
        attributes["occurrences"] = [[s, e] for s, e, *_ in results]
        if len({r[3].key() for r in results}) == 1:
            flags.append("ambiguous_match")
        else:
            status = "candidate"
    start, end, vc, check, detail = results[0]
    attributes["mentions"] = detail
    attributes["per_axis"] = dict(check.per_axis)
    if vc.quote_date is not None:
        attributes["quote_date"] = vc.quote_date
    if vc.list_status is not None:
        attributes["list_status"] = vc.list_status
    if fact_field == "patient_identity":
        # Every located occurrence is screened, not only the first (contract §3.5).
        attributes["identifiers"] = _unique([i for r in results for i in r[2].identifiers])
        attributes["dobs_in_text"] = _unique([x for r in results for x in r[2].dobs])

    reasons = list(vc.reasons)
    if check.result == "mismatch":
        reasons.append("assertion_mismatch")
    if check.result == "unrecognized" or "unrecognized" in vc.flags:
        flags.append("unrecognized")
    if is_table_line(text, start, end):
        flags.append("table_source")
    return CheckedEvidence(
        **base,
        start=start,
        end=end,
        certainty_checked=check.checked["certainty"],
        subject_checked=check.checked["subject"],
        temporality_checked=check.checked["temporality"],
        position_status=status,
        assertion_check=check.result,
        exclusion_reasons=tuple(reasons),
        flags=tuple(flags),
        ref=f"{fact.doc_id}[{start}:{end}] {sha8(text[start:end])}",
        event_date_source=vc.event_date_source,
        attributes=attributes,
    )


# --- Document level: claim document and identity ----------------------------------------------


def _identity(
    doc_id: str, evidence: Sequence[CheckedEvidence], ctx: VerifyContext
) -> tuple[str, int | None]:
    """(identity_status, index of the deciding evidence) for one document (contract §3.5).

    Identifiers and dates of birth are read in full from the document text around each
    located identity fact, each with its own subject and certainty from the cues: a failed
    check of another field does not hide them, and a relative's identifier does not shield
    the patient's. Only identifiers of the primary patient's type are compared. Both a
    match and a mismatch need an identifier the cues assert as the patient's actual one
    (patient, present, not hypothetical); a match also needs the fact itself to be
    affirmative (`matched`, present, patient) at a verbatim or normalized position.
    """
    primary = ctx.primary_patient
    primary_id = canonical_id(primary.patient_id)
    primary_type = id_type(primary.patient_id)
    # Identifiers are read from the source text at every located occurrence, so a row whose
    # repeated quote became `candidate` still screens for a mismatch; a match needs a
    # verbatim or normalized position.
    grounded = [
        i
        for i, ev in enumerate(evidence)
        if ev.field == "patient_identity"
        and ev.doc_id == doc_id
        and (ev.position_status in LOCATED or "occurrences" in ev.attributes)
        and "candidate_ratio" not in ev.attributes  # a fuzzy hit grounds nothing
    ]

    def not_actual(subject: str | None, certainty: str | None, temporality: str | None) -> bool:
        """An identifier not asserted as the patient's actual one (family, other, negated,
        uncertain, hypothetical) neither matches nor contradicts (contract §3.5)."""
        return (subject, certainty) != ("patient", "present") or temporality in (
            None,
            "hypothetical",
        )

    def affirmative(
        ev: CheckedEvidence, subject: str | None, certainty: str | None, temporality: str | None
    ) -> bool:
        return (
            ev.position_status in LOCATED
            and ev.assertion_check == "matched"
            and ev.certainty_llm == "present"
            and ev.subject_llm == "patient"
            and (subject, certainty) == ("patient", "present")
            and temporality not in (None, "hypothetical")
        )

    match: int | None = None
    compared = False
    unresolved = False
    for i in grounded:
        ev = evidence[i]
        for kind, ident, subject, certainty, temporality in ev.attributes.get("identifiers", []):
            if not_actual(subject, certainty, temporality):
                continue
            if kind == "unresolved":
                unresolved = True  # a labelled identifier of unknown shape: no match on this doc
                continue
            if kind != primary_type:
                continue
            compared = True
            if ident != primary_id:
                return "mismatch", i
            if match is None and affirmative(ev, subject, certainty, temporality):
                match = i
    if match is not None and not unresolved:
        return "match", match
    if compared or unresolved:
        return "missing", None
    for i in grounded:
        ev = evidence[i]
        for dob, subject, certainty, temporality in ev.attributes.get("dobs_in_text", []):
            if not_actual(subject, certainty, temporality):
                continue
            if dob != primary.dob.isoformat():
                return "mismatch", i
            if match is None and affirmative(ev, subject, certainty, temporality):
                match = i
    if match is not None:
        return "match", match
    return "missing", None


def verify_case(ext: Extraction, docs: Docs, ctx: VerifyContext) -> VerifyResult:
    """Every fact of `ext` as exactly one `CheckedEvidence`, plus one `DocFact` per document."""
    indexes: dict[str, _DocIndex] = {}
    evidence: list[CheckedEvidence] = []
    for fact_field in EXTRACTION_FIELDS:
        for i, fact in enumerate(getattr(ext, fact_field)):
            path = f"{fact_field}[{i}]"
            try:
                evidence.append(verify_fact(fact_field, path, fact, docs, ctx, indexes))
            except Exception as exc:  # noqa: BLE001 - re-raised without text
                raise VerifyError(path, type(exc).__name__) from None

    doc_facts: list[DocFact] = []
    wrong: set[str] = set()
    missing: set[str] = set()
    for doc_id in docs:
        status, index = _identity(doc_id, evidence, ctx)
        doc_facts.append(DocFact(doc_id, status, index))
        if status == "mismatch":
            wrong.add(doc_id)
        elif status == "missing":
            missing.add(doc_id)

    out: list[CheckedEvidence] = []
    for ev in evidence:
        if ev.position_status == "not_found":
            out.append(ev)
            continue
        reasons = list(ev.exclusion_reasons)
        flags = list(ev.flags)
        doc = docs.get(ev.doc_id)
        if doc is not None and doc.role == "pa_draft" and ev.field != "pa_form_claims":
            reasons.append("claim_document")
        if ev.doc_id in wrong:
            reasons.append("wrong_patient")
        if ev.doc_id in missing and ev.field == "patient_identity":
            flags.append("id_missing")
        out.append(replace(ev, exclusion_reasons=tuple(reasons), flags=tuple(flags)))
    return VerifyResult(out, doc_facts)


def verify(ext: Extraction, docs: Docs, ctx: VerifyContext) -> list[CheckedEvidence]:
    """Contract §7.3 signature: the evidence of `verify_case`."""
    return verify_case(ext, docs, ctx).evidence
