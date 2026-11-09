"""Pydantic models for the three gold-side files written by the annotator.

- `BlindDraft` — `cases/<variant_id>/blind_draft.json` (guide B-01–B-03, contract §8).
- `AdjudicationLine` — one line of `cases/<variant_id>/adjudication.jsonl` (guide L-01).
- `Gold` — `cases/<variant_id>/expected.json` (contract §8).

All models are strict and forbid unknown keys. Text is never stored: `candidate` and
`final` entries may only hold the L-01 allow-list keys, and a fact of an MTSamples document
carries `quote_sha256` instead of `quote` (P-07). `format_errors` renders validation errors
without echoing the offending values, so a validator may print them.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from bridge_check.enums import (
    ALLOWED_ENTRY_KEYS,
    BMI_BRACKET_PATTERN,
    CKD_STAGE_PATTERN,
    CLAIM_IDS,
    CLAIM_PREFIX,
    CLAIMED_VALUE_TOKENS,
    CONDITION_IDS,
    DATE_VALUE_KEYS,
    ENUM_VALUE_KEYS,
    EXCLUSION_IDS,
    EXTRACTION_FIELDS,
    FIBROSIS_STAGE_PATTERN,
    FLAGS,
    FORBIDDEN_ENTRY_KEYS,
    GLP1_CANONICALS,
    GLP1_NAMES,
    GOLD_REVIEW,
    GUIDELINE_CLAUSE_PATTERN,
    MTSAMPLES_DOC_ID_PREFIX,
    NUMERIC_VALUE_KEYS,
    POSITION_KEYS,
    SAFE_ID_PATTERN,
    SCAN_HIT_KEYS,
    AdjudicationItem,
    Certainty,
    Decision,
    GoldOrigin,
    IdentityMatch,
    Presence,
    RelativeToInitiation,
    Status,
    Subject,
    Temporality,
)

_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EVENT_DATE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")
_SHA8 = re.compile(r"^[0-9a-f]{8}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class _Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


def _check_iso_day(value: str) -> str:
    if not _ISO_DAY.match(value):
        raise ValueError("must be an ISO date YYYY-MM-DD")
    date.fromisoformat(value)
    return value


def _check_event_date(value: str | None) -> str | None:
    """`YYYY`, `YYYY-MM` or `YYYY-MM-DD`; the precision follows from the shape."""
    if value is None:
        return None
    if not _EVENT_DATE.match(value):
        raise ValueError("must be YYYY, YYYY-MM or YYYY-MM-DD")
    parts = value.split("-")
    padded = [*parts, "01", "01"][:3]
    date.fromisoformat("-".join(padded))
    return value


def _check_condition_id(value: str) -> str:
    if value.startswith(CLAIM_PREFIX):
        raise ValueError("claim.* is not a condition id here (claims live in gold claims[])")
    if value not in CONDITION_IDS:
        raise ValueError("unknown condition id")
    return value


def _check_clause(value: str | None) -> str | None:
    if value is not None and not re.match(GUIDELINE_CLAUSE_PATTERN, value):
        raise ValueError("guideline_clause must look like G-01 (letter P/S/A/T/C/K/G/W/B/L/U/R)")
    return value


_DRUGS_PATH = Path(__file__).resolve().parent.parent.parent / "rules" / "drugs-v1.yaml"
_SAFE_ID = re.compile(SAFE_ID_PATTERN)
_drug_canonicals: frozenset[str] | None = None


def drug_canonicals(path: Path = _DRUGS_PATH) -> frozenset[str]:
    """`drug_canonical` values of the drug table (loaded once)."""
    global _drug_canonicals
    if _drug_canonicals is None:
        data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        _drug_canonicals = frozenset(str(d["drug_canonical"]) for d in data["drugs"])
    return _drug_canonicals


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def value_problem(key: str, value: Any) -> str | None:
    """Why `value` is not acceptable for allow-list key `key`, or None.

    Every value key has a controlled shape (contract §6, §7.2, §8): an enum, a number, a
    date, a bool, a short pattern or a known drug. Free text can therefore never travel
    under a value key.
    """
    if value is None:
        return None
    if key in ENUM_VALUE_KEYS:
        return None if isinstance(value, str) and value in ENUM_VALUE_KEYS[key] else "not in enum"
    if key in NUMERIC_VALUE_KEYS:
        return None if _is_number(value) else "not a number"
    if key in DATE_VALUE_KEYS:
        if not isinstance(value, str):
            return "not a date string"
        try:
            _check_event_date(value)
        except ValueError:
            return "not YYYY[-MM[-DD]]"
        return None
    if key in ("start", "end"):
        return None if isinstance(value, int) and not isinstance(value, bool) else "not an int"
    if key == "sha8":
        return None if isinstance(value, str) and _SHA8.match(value) else "not sha8"
    if key in ("doc_id", "target_doc_id"):
        return None if isinstance(value, str) and _SAFE_ID.match(value) else "not a doc id"
    if key == "cirrhosis":
        return None if isinstance(value, bool) else "not a bool"
    if key == "fibrosis_stage":
        return (
            None
            if isinstance(value, str) and re.match(FIBROSIS_STAGE_PATTERN, value)
            else "bad stage"
        )
    if key == "ckd_stage":
        return (
            None if isinstance(value, str) and re.match(CKD_STAGE_PATTERN, value) else "bad stage"
        )
    if key == "claim_id":
        return None if isinstance(value, str) and value in CLAIM_IDS else "not a known claim id"
    if key == "claimed_value":
        return claimed_value_problem(None, value)
    if key == "drug_canonical":
        ok = isinstance(value, str) and (value in drug_canonicals() or value in GLP1_CANONICALS)
        return None if ok else "not a canonical drug name"
    return "unknown key"


def claimed_value_problem(claim_id: Any, value: Any) -> str | None:
    """A claimed value must be the form option of its claim (K-02, K-04): a bracket for
    `claim.bmi_bracket`, a GLP-1 name for `claim.drug`, a bool or box token for every other
    (yes/no) claim. Numbers are never accepted: no PA-form box is a free number, and an
    identifier could hide in one."""
    if value is None:
        return None
    if claim_id == "claim.bmi_bracket":
        ok = isinstance(value, str) and re.match(BMI_BRACKET_PATTERN, value) is not None
        return None if ok else "not a BMI bracket"
    if claim_id == "claim.drug":
        ok = isinstance(value, str) and value.casefold() in {n.casefold() for n in GLP1_NAMES}
        return None if ok else "not a GLP-1 drug name"
    if isinstance(value, bool) or (isinstance(value, str) and value in CLAIMED_VALUE_TOKENS):
        return None
    return "not a yes/no form option"


def check_entry_values(entry: dict[str, Any]) -> dict[str, Any]:
    """Every allow-listed value must have its controlled shape (see `value_problem`)."""
    bad = {k: value_problem(k, v) for k, v in entry.items()}
    if "claimed_value" in entry:
        bad["claimed_value"] = claimed_value_problem(entry.get("claim_id"), entry["claimed_value"])
    bad = {k: why for k, why in bad.items() if why is not None}
    if bad:
        raise ValueError(
            "invalid value(s): " + ", ".join(f"{k} ({why})" for k, why in sorted(bad.items()))
        )
    return entry


def check_entry_keys(entry: dict[str, Any]) -> dict[str, Any]:
    """Enforce the L-01 allow-list on a `candidate` / `final` object."""
    forbidden = sorted(k for k in entry if k in FORBIDDEN_ENTRY_KEYS)
    if forbidden:
        raise ValueError(
            f"forbidden key(s) {forbidden} (never written: {', '.join(FORBIDDEN_ENTRY_KEYS)})"
        )
    unknown = sum(1 for k in entry if k not in ALLOWED_ENTRY_KEYS)
    if unknown:  # never name an unknown key: it could itself be text
        raise ValueError(f"{unknown} key(s) not in the L-01 allow-list")
    for key in ("start", "end"):
        if key in entry and (isinstance(entry[key], bool) or not isinstance(entry[key], int)):
            raise ValueError(f"{key} must be an integer offset")
    if "start" in entry and "end" in entry and not entry["start"] < entry["end"]:
        raise ValueError("start must be less than end")
    if "sha8" in entry and not (isinstance(entry["sha8"], str) and _SHA8.match(entry["sha8"])):
        raise ValueError("sha8 must be 8 lowercase hex characters")
    return check_entry_values(entry)


# --- blind_draft.json (B-01–B-03) ------------------------------------------------------


def _check_exclusion_status(condition_id: str, status: str) -> None:
    if condition_id in EXCLUSION_IDS and status == "supported":
        raise ValueError("an exclusion sub-result is never supported (contract §3.3)")


class BlindCondition(_Strict):
    id: str
    status: Status

    _id = field_validator("id")(_check_condition_id)

    @model_validator(mode="after")
    def _exclusion(self) -> BlindCondition:
        _check_exclusion_status(self.id, self.status)
        return self


class InventoryRow(_Strict):
    field: str = Field(min_length=1)
    kind: str | None = None
    concept: str | None = None
    presence: Presence
    location: str | None = None


class BlindDraft(_Strict):
    variant_id: str = Field(min_length=1)
    drafted_at: str
    conditions: list[BlindCondition]
    inventory: list[InventoryRow]
    notes: list[str] = Field(default_factory=list)

    _date = field_validator("drafted_at")(_check_iso_day)


# --- adjudication.jsonl (L-01) ------------------------------------------------------------


class ScanHit(_Strict):
    doc_id: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    sha8: str = Field(pattern=_SHA8.pattern)
    term: str = Field(min_length=1)

    @model_validator(mode="after")
    def _ordered(self) -> ScanHit:
        if not self.start < self.end:
            raise ValueError("start must be less than end")
        return self


assert tuple(ScanHit.model_fields) == SCAN_HIT_KEYS


class AdjudicationLine(_Strict):
    variant_id: str = Field(min_length=1)
    item: AdjudicationItem
    field: str | None = None
    kind: str | None = None
    concept: str | None = None
    condition_id: str | None = None
    candidate: dict[str, Any] | None
    scan_hit: ScanHit | None
    inventory: Presence | None
    decision: Decision
    final: dict[str, Any] | None
    identity_match: IdentityMatch | None = None
    guideline_clause: str | None
    guideline_version: int = Field(ge=0)
    drafted_by: str | None
    decided_at: str
    note: str

    _entries = field_validator("candidate", "final")(
        lambda v: None if v is None else check_entry_keys(v)
    )
    _clause = field_validator("guideline_clause")(_check_clause)
    _date = field_validator("decided_at")(_check_iso_day)

    @model_validator(mode="after")
    def _item_shape(self) -> AdjudicationLine:
        if self.item == "fact":
            if self.field is None:
                raise ValueError("item fact needs field")
            if self.field not in EXTRACTION_FIELDS:
                raise ValueError("unknown extraction field")
        else:
            if self.condition_id is None:
                raise ValueError("item condition needs condition_id")
            _check_condition_id(self.condition_id)
        return self


# --- expected.json (contract §8) ----------------------------------------------------------


class GoldFact(BaseModel):
    """One gold fact; value keys beyond the shared ones follow the L-01 value list."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    field: str
    doc_id: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    quote: str | None = None
    quote_sha256: str | None = Field(default=None, pattern=_SHA256.pattern)
    certainty: Certainty
    subject: Subject
    temporality: Temporality
    event_date: str | None
    relative_to_glp1_initiation: RelativeToInitiation
    origin: GoldOrigin
    review: Literal["human_verified"]
    guideline_clause: str | None
    # optional value keys (L-01 value list minus the shared keys above)
    kind: str | None = None
    concept: str | None = None
    norm_value: float | int | None = None
    norm_unit: str | None = None
    sbp: int | None = None
    dbp: int | None = None
    period_start: str | None = None
    period_end: str | None = None
    end_kind: str | None = None
    drug_canonical: str | None = None
    program_type: str | None = None
    attendance: str | None = None
    osa_severity: str | None = None
    ahi: float | int | None = None
    fibrosis_stage: str | None = None
    cirrhosis: bool | None = None
    ckd_stage: str | None = None
    symptomatic: str | None = None
    payer: str | None = None
    purpose: str | None = None
    claim_id: str | None = None
    claimed_value: str | None = None
    target_doc_id: str | None = None
    date: str | None = None
    identity_match: IdentityMatch | None = None
    # gold-only scoring keys (contract §8 matching table); never in adjudication lines
    complete: bool | None = None
    list_id: str | None = None
    compounded: bool | None = None
    stated_age: int | None = Field(default=None, ge=0, le=130)  # normalized age (C-01)
    patient_id: str | None = None
    dob: str | None = None

    _event = field_validator("event_date")(_check_event_date)
    _dob = field_validator("dob")(lambda v: None if v is None else _check_iso_day(v))
    _clause = field_validator("guideline_clause")(_check_clause)
    _period = field_validator("period_start", "period_end", "date")(_check_event_date)

    @field_validator("field")
    @classmethod
    def _known_field(cls, value: str) -> str:
        if value not in EXTRACTION_FIELDS:
            raise ValueError("unknown extraction field")
        return value

    @model_validator(mode="after")
    def _quote_form(self) -> GoldFact:
        if not self.start < self.end:
            raise ValueError("start must be less than end")
        present = self.model_fields_set
        if self.doc_id.startswith(MTSAMPLES_DOC_ID_PREFIX):
            if "quote" in present:
                raise ValueError("MTSamples fact must not contain quote (store quote_sha256)")
            if self.quote_sha256 is None:
                raise ValueError("MTSamples fact must contain quote_sha256")
            if self.patient_id is not None or self.dob is not None:
                raise ValueError("identity values are text for an MTSamples document")
        else:
            if self.quote is None:
                raise ValueError("fact must contain quote")
            if "quote_sha256" in present:
                raise ValueError("quote_sha256 is only for MTSamples facts")
        shared = {
            k: getattr(self, k)
            for k in ALLOWED_ENTRY_KEYS
            if k in type(self).model_fields and getattr(self, k) is not None
        }
        check_entry_values(shared)
        return self


assert GOLD_REVIEW == "human_verified"
assert set(POSITION_KEYS) - {"sha8"} <= set(GoldFact.model_fields)


class ExpectedAbsent(_Strict):
    field: str
    kind: str | None = None
    concept: str | None = None

    @model_validator(mode="after")
    def _shape(self) -> ExpectedAbsent:
        if self.field not in EXTRACTION_FIELDS:
            raise ValueError("unknown extraction field")
        if (self.kind is None) == (self.concept is None):
            raise ValueError("exactly one of kind / concept is required")
        return self


class GoldCondition(_Strict):
    id: str
    status: Status
    flags: list[str] = Field(default_factory=list)
    reason: str

    _id = field_validator("id")(_check_condition_id)

    @model_validator(mode="after")
    def _exclusion(self) -> GoldCondition:
        _check_exclusion_status(self.id, self.status)
        return self

    @field_validator("flags")
    @classmethod
    def _known_flags(cls, flags: list[str]) -> list[str]:
        unknown = [i for i, f in enumerate(flags) if f not in FLAGS]
        if unknown:
            raise ValueError(f"unknown flag(s) at index {unknown} (allowed: {', '.join(FLAGS)})")
        return flags


class GoldClaim(_Strict):
    id: str = Field(pattern=rf"^{re.escape(CLAIM_PREFIX)}[a-z0-9_.]+$")
    status: Status


class Gold(_Strict):
    variant_id: str = Field(min_length=1)
    guideline_version: int = Field(ge=0)
    facts: list[GoldFact]
    expected_absent: list[ExpectedAbsent] = Field(default_factory=list)
    conditions: list[GoldCondition]
    case_flags: list[str] = Field(default_factory=list)
    claims: list[GoldClaim] = Field(default_factory=list)
    gold_version: int = Field(ge=1)
    changes: list[Any] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_conditions(self) -> Gold:
        ids = [c.id for c in self.conditions]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate condition id")
        return self


# --- error rendering without values ----------------------------------------------------


def format_errors(exc: ValidationError) -> list[str]:
    """`<loc>: <type>: <msg>` per error. Messages come from this module or Pydantic's
    type names; the offending input value is never included."""
    lines: list[str] = []
    for err in exc.errors(include_input=False, include_url=False, include_context=False):
        parts = [str(p) for p in err["loc"]]
        if err["type"] == "extra_forbidden" and parts:
            parts[-1] = "<unexpected key>"  # an arbitrary key could itself be text
        loc = ".".join(parts) or "<root>"
        msg = err["msg"]
        if err["type"] == "value_error":
            msg = msg.removeprefix("Value error, ")
        lines.append(f"{loc}: {err['type']}: {msg}")
    return lines
