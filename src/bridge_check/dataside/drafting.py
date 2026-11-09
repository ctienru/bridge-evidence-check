"""Route 1: authored documents drafted from a spec (planning 05 §5.2, guide P-04).

A `DraftSpec` lists the documents to write and the facts each must contain. The model
returns `documents: {doc_id: text}` and `quote_map: {fact_id: quote}`. Four deterministic
checks then run per fact, as pure functions over the returned text:

1. `quote_unique` — the quote occurs verbatim exactly once in the named document
   (reported as `quote_not_found` or `quote_ambiguous` when it fails);
2. `value_in_quote` — the spec value (and unit, when given) is a substring of the quote;
3. `cue_in_sentence` — the sentence holding the quote has a cue for every non-default
   axis value (`cues.cue_in_sentence`);
4. `must_use_present` — every requested dirty wording appears in the document.

Nothing here prints document text or quotes; results carry `fact_id` and check names only.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bridge_check.cues import Cues, cue_in_sentence
from bridge_check.enums import (
    AXIS_DEFAULTS,
    EXTRACTION_FIELDS,
    SAFE_ID_PATTERN,
    Certainty,
    DocRole,
    Subject,
    Temporality,
)
from bridge_check.sentences import sentence_containing, split_sentences
from bridge_check.text import locate

# JSON mode requires the word JSON in the messages; never rely on the private prompt for it.
JSON_INSTRUCTION = (
    "Respond with a single JSON object in exactly the output_format given; "
    "output JSON only, no prose."
)
CHECKS: tuple[str, ...] = ("quote_unique", "value_in_quote", "cue_in_sentence", "must_use_present")


class _Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class SpecDocument(_Strict):
    doc_id: str = Field(pattern=SAFE_ID_PATTERN)
    role: DocRole
    instructions: str


class SpecFact(_Strict):
    fact_id: str = Field(min_length=1)
    doc_id: str = Field(min_length=1)
    field: str
    kind: str | None = None
    concept: str | None = None
    value: str = Field(min_length=1)
    unit: str | None = None
    certainty: Certainty
    subject: Subject
    temporality: Temporality
    event_date: str | None = None
    must_use: list[str] = Field(default_factory=list)
    note: str | None = None

    @field_validator("event_date", mode="before")
    @classmethod
    def _date_to_str(cls, value: Any) -> Any:
        """YAML parses a bare `2025-03-15` into a date; the spec stores ISO strings."""
        return value.isoformat() if isinstance(value, date) else value

    @model_validator(mode="after")
    def _known_field(self) -> SpecFact:
        if self.field not in EXTRACTION_FIELDS:
            raise ValueError(f"fact {self.fact_id!r}: unknown extraction field")
        return self


class DraftSpec(_Strict):
    case_id: str = Field(min_length=1)
    documents: list[SpecDocument] = Field(min_length=1)
    facts: list[SpecFact]

    @model_validator(mode="after")
    def _consistent(self) -> DraftSpec:
        doc_ids = {d.doc_id for d in self.documents}
        if len(doc_ids) != len(self.documents):
            raise ValueError("duplicate doc_id in documents")
        fact_ids = [f.fact_id for f in self.facts]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("duplicate fact_id in facts")
        for fact in self.facts:
            if fact.doc_id not in doc_ids:
                raise ValueError(f"fact {fact.fact_id!r}: doc_id not in documents")
        return self


class DraftResponse(_Strict):
    documents: dict[str, str]
    quote_map: dict[str, str]


# Strict structured output cannot express dynamic keys, so the model returns arrays of
# pairs; `parse_response` turns them into the dicts used everywhere else.
RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["documents", "quote_map"],
    "properties": {
        "documents": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["doc_id", "text"],
                "properties": {"doc_id": {"type": "string"}, "text": {"type": "string"}},
            },
        },
        "quote_map": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["fact_id", "quote"],
                "properties": {"fact_id": {"type": "string"}, "quote": {"type": "string"}},
            },
        },
    },
}


def _pairs_to_dict(value: Any, key: str, val: str) -> Any:
    """`[{key: k, val: v}, ...]` → `{k: v}`; a dict passes through; duplicates are an error."""
    if not isinstance(value, list):
        return value
    out: dict[str, Any] = {}
    for item in value:
        if not isinstance(item, dict) or key not in item or val not in item:
            return value  # let the model validation report the shape
        if item[key] in out:
            raise ValueError(f"duplicate {key} in response")
        out[item[key]] = item[val]
    return out


@dataclass(frozen=True)
class CheckResult:
    fact_id: str
    check: str
    passed: bool


def load_spec(path: Path) -> DraftSpec:
    """Load a spec; a YAML error is re-raised as `ValueError` naming only the error type."""
    try:
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise ValueError(f"spec: invalid YAML ({type(exc).__name__})") from None
    return DraftSpec.model_validate(data)


def _axis_values(fact: SpecFact) -> dict[str, str]:
    return {
        "certainty": fact.certainty,
        "subject": fact.subject,
        "temporality": fact.temporality,
    }


def _first_non_space(doc: str, start: int, end: int) -> int:
    i = start
    while i < end and doc[i].isspace():
        i += 1
    return i


def _last_non_space(doc: str, start: int, end: int) -> int:
    i = end - 1
    while i > start and doc[i].isspace():
        i -= 1
    return i


def check_fact(fact: SpecFact, response: DraftResponse, cues: Cues) -> list[CheckResult]:
    """The four checks for one fact; the first check decides the others' input."""
    doc = response.documents.get(fact.doc_id)
    quote = response.quote_map.get(fact.fact_id)
    if doc is None or quote is None:
        return [CheckResult(fact.fact_id, "quote_not_found", False)]
    hits = locate(doc, quote)
    if not hits:
        return [CheckResult(fact.fact_id, "quote_not_found", False)]
    if len(hits) > 1:
        return [CheckResult(fact.fact_id, "quote_ambiguous", False)]
    results = [CheckResult(fact.fact_id, "quote_unique", True)]

    value_ok = fact.value in quote and (fact.unit is None or fact.unit in quote)
    results.append(CheckResult(fact.fact_id, "value_in_quote", value_ok))

    start, end = hits[0]
    spans = split_sentences(doc)
    s_start, s_end = sentence_containing(spans, _first_non_space(doc, start, end))
    sentence = doc[s_start:s_end]
    # the quote's non-whitespace content must lie inside one sentence: a cue found in a
    # neighbouring sentence would otherwise be borrowed (review of PR #9)
    within = (
        s_start <= _first_non_space(doc, start, end) and _last_non_space(doc, start, end) < s_end
    )
    cue_ok = within and all(
        cue_in_sentence(sentence, axis, value, cues)
        for axis, value in _axis_values(fact).items()
        if value != AXIS_DEFAULTS[axis]
    )
    results.append(CheckResult(fact.fact_id, "cue_in_sentence", cue_ok))

    must_ok = all(term in doc for term in fact.must_use)
    results.append(CheckResult(fact.fact_id, "must_use_present", must_ok))
    return results


def run_checks(spec: DraftSpec, response: DraftResponse, cues: Cues) -> list[CheckResult]:
    results: list[CheckResult] = []
    for fact in spec.facts:
        results.extend(check_fact(fact, response, cues))
    missing_docs = [d.doc_id for d in spec.documents if d.doc_id not in response.documents]
    for doc_id in missing_docs:
        results.append(CheckResult(f"<document {doc_id}>", "document_missing", False))
    return results


def failed_fact_ids(results: list[CheckResult]) -> list[str]:
    seen: dict[str, None] = {}
    for r in results:
        if not r.passed and not r.fact_id.startswith("<"):
            seen.setdefault(r.fact_id, None)
    return list(seen)


def format_table(results: list[CheckResult]) -> str:
    """`fact_id  check  pass|fail` lines; never any text from the documents."""
    width = max((len(r.fact_id) for r in results), default=7)
    cwidth = max((len(r.check) for r in results), default=5)
    lines = [f"{'fact_id':<{width}}  {'check':<{cwidth}}  result"]
    for r in results:
        lines.append(f"{r.fact_id:<{width}}  {r.check:<{cwidth}}  {'pass' if r.passed else 'FAIL'}")
    return "\n".join(lines)


def build_messages(
    spec: DraftSpec, prompt_text: str, failed_ids: list[str] | None = None
) -> list[dict[str, str]]:
    """System prompt from the private prompt file; user message = the spec as JSON."""
    user = {
        "case_id": spec.case_id,
        "documents": [d.model_dump() for d in spec.documents],
        "facts": [f.model_dump(exclude_none=True) for f in spec.facts],
        "output_format": {
            "documents": [{"doc_id": "<doc_id>", "text": "<full document text>"}],
            "quote_map": [{"fact_id": "<fact_id>", "quote": "<verbatim quote>"}],
        },
    }
    if failed_ids:
        user["revise"] = {
            "failed_fact_ids": failed_ids,
            "instruction": "These facts failed the deterministic checks; rewrite so that each "
            "quote appears verbatim exactly once, contains the value, and its sentence "
            "carries the required cue. Return the complete documents again.",
        }
    return [
        {"role": "system", "content": prompt_text + "\n\n" + JSON_INSTRUCTION},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False, indent=2)},
    ]


def parse_response(raw: Any, spec: DraftSpec | None = None) -> DraftResponse:
    """Validate the model JSON; with `spec`, the document and fact id sets must match it.

    The sets are compared exactly so the model can neither add a document (which could
    name a path outside `--out-docs`) nor drop one. Error messages carry no text.
    """
    if isinstance(raw, dict):
        raw = {
            **raw,
            "documents": _pairs_to_dict(raw.get("documents"), "doc_id", "text"),
            "quote_map": _pairs_to_dict(raw.get("quote_map"), "fact_id", "quote"),
        }
    response = DraftResponse.model_validate(raw)
    if spec is not None:
        want_docs = {d.doc_id for d in spec.documents}
        if set(response.documents) != want_docs:
            raise ValueError("response documents do not match the spec doc_ids")
        want_facts = {f.fact_id for f in spec.facts}
        if set(response.quote_map) != want_facts:
            raise ValueError("response quote_map does not match the spec fact_ids")
    return response


def write_documents(response: DraftResponse, out_dir: Path) -> list[Path]:
    """Write `<doc_id>.txt` per document, byte-exact. Every path is checked before any
    write: the id must be a safe id and the file must stay inside `out_dir`."""
    root = out_dir.resolve()
    targets: list[tuple[Path, str]] = []
    for doc_id, text in response.documents.items():
        path = (root / f"{doc_id}.txt").resolve()
        if not re.match(SAFE_ID_PATTERN, doc_id) or path.parent != root:
            raise ValueError("document id is not a safe file name")
        targets.append((path, text))
    root.mkdir(parents=True, exist_ok=True)
    for path, text in targets:
        with path.open("w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    return [p for p, _ in targets]


def build_record(
    model: str, response: DraftResponse, results: list[CheckResult], today: date | None = None
) -> dict[str, Any]:
    """The drafting record (goes to the private repo): who drafted, when, the quote map
    and the per-fact check outcomes."""
    return {
        "drafted_by": model,
        "drafted_at": (today or date.today()).isoformat(),
        "quote_map": dict(response.quote_map),
        "checks": [{"fact_id": r.fact_id, "check": r.check, "passed": r.passed} for r in results],
    }
