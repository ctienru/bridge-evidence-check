"""Extraction output schema v2 (contract §7.2).

The model returns one JSON object with twelve arrays; a fact the documents do not contain
is simply absent (an empty array). The local Pydantic models keep every constraint; the
API receives `pydantic_json_schema()` as the `input_schema` of the `record_extraction`
tool (`extract.py`, ADR 0002). `extraction_json_schema()`, the same schema passed through
the SDK's `transform_schema()`, is no longer sent: it is kept as a local check that the
schema still compiles under the structured-output rules. v2 differs from v1 only in that
`claim_id` carries its allowed values as an `enum` in the JSON schema (the Python validator
already enforced them); the version marks the change of output mode.

Empty and placeholder values. Numeric fields are typed numbers and the strict config
rejects strings, so `"unknown"`, `"N/A"` and `""` never pass. Date fields accept only
`YYYY`, `YYYY-MM` or `YYYY-MM-DD`; the string `"unknown"` is legal only in the enum fields
listed in contract §6 (`payer`, `purpose`, `end_kind`, `symptomatic`, `attendance`,
`relative_to_glp1_initiation`).

Union limit fallback (contract §7.2). Structured outputs allow at most 16 union-typed
parameters per request, and `["string", "null"]` counts as one. A nullable `event_date`
and `date_precision` on every fact would need 24 unions on their own, so the fallback is
applied to `event_date` only: a fact the document does not date has `event_date == ""`
with `date_precision == "none"`, and a validator enforces `none` ⇔ `""`. That is the only
place an empty string is accepted in a date. Every other date field (`dob`, the GLP-1
dates, medication and lifestyle start and end, and the medication date precisions) is
nullable: 9 unions, plus `stated_age`, `ahi`, `cirrhosis` and `compounded`, 13 in all.
Optional free-text fields (`name`, `dose`, …) use `""` for "not stated".
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bridge_check.enums import (
    BMI_BRACKET_PATTERN,
    CKD_STAGE_PATTERN,
    CLAIM_IDS,
    CLAIMED_VALUE_TOKENS,
    DATE_PRECISIONS,
    FIBROSIS_STAGE_PATTERN,
    GLP1_NAMES,
    SAFE_ID_PATTERN,
    AnthropometricKind,
    Attendance,
    Certainty,
    Concept,
    DatePrecision,
    EndKind,
    ExtractionDatePrecision,
    LabKind,
    LifestyleKind,
    OsaSeverity,
    Payer,
    ProgramType,
    Purpose,
    RelativeToInitiation,
    Subject,
    Symptomatic,
    Temporality,
)

SCHEMA_VERSION = "v2"
UNION_LIMIT = 16
"""Structured outputs: at most 16 union-typed parameters per request. Not enforced on a
non-strict tool schema; checked locally so the schema could still be sent that way."""

_DATE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")
_SAFE_ID = re.compile(SAFE_ID_PATTERN)
_FIBROSIS = re.compile(FIBROSIS_STAGE_PATTERN)
_CKD = re.compile(CKD_STAGE_PATTERN)
_BMI_BRACKET = re.compile(BMI_BRACKET_PATTERN)
_HAS_DIGIT = re.compile(r"\d")
_PRECISION_BY_LENGTH = {4: "year", 7: "month", 10: "day"}


def _date_problem(value: str) -> str | None:
    """Why `value` is not `YYYY[-MM[-DD]]`, or None. Never echoes the value."""
    if not _DATE.match(value):
        return "must be YYYY, YYYY-MM or YYYY-MM-DD"
    padded = [*value.split("-"), "01", "01"][:3]
    try:
        date.fromisoformat("-".join(padded))
    except ValueError:
        return "is not a calendar date"
    return None


def check_date(value: str) -> str:
    problem = _date_problem(value)
    if problem is not None:
        raise ValueError(f"date {problem}")
    return value


def check_optional_date(value: str | None) -> str | None:
    """A nullable date: null when not stated, never `""` or a placeholder."""
    return None if value is None else check_date(value)


def check_event_date_precision(value: str, precision: str) -> None:
    """§7.2 fallback: `precision == "none"` ⇔ `event_date == ""`; else shape = precision."""
    if (precision == "none") != (value == ""):
        raise ValueError("event_date: precision 'none' is used exactly when the date is empty")
    if value and _PRECISION_BY_LENGTH[len(value)] != precision:
        raise ValueError("event_date: precision does not match the date's shape")


def check_nullable_precision(value: str | None, precision: str | None, name: str) -> None:
    """Both null, or a date whose shape matches its precision."""
    if (value is None) != (precision is None):
        raise ValueError(f"{name}: date and precision are both null or both set")
    if value is not None and _PRECISION_BY_LENGTH[len(value)] != precision:
        raise ValueError(f"{name}: precision does not match the date's shape")


assert set(_PRECISION_BY_LENGTH.values()) == set(DATE_PRECISIONS)


class _Strict(BaseModel):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        frozen=True,
        json_schema_serialization_defaults_required=True,
    )


class Fact(_Strict):
    """Fields every fact shares (contract §7.2)."""

    doc_id: str = Field(description="doc_id of the document the quote comes from")
    quote: str = Field(description="Verbatim span copied from that document")
    certainty: Certainty
    subject: Subject
    temporality: Temporality
    event_date: str = Field(description='YYYY, YYYY-MM or YYYY-MM-DD; "" when not stated')
    date_precision: ExtractionDatePrecision = Field(
        description='"none" exactly when event_date is ""'
    )
    relative_to_glp1_initiation: RelativeToInitiation

    @field_validator("doc_id")
    @classmethod
    def _doc_id(cls, v: str) -> str:
        if not _SAFE_ID.match(v):
            raise ValueError("doc_id must be a safe id")
        return v

    @field_validator("quote")
    @classmethod
    def _quote(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("quote must not be empty")
        return v

    @field_validator("event_date")
    @classmethod
    def _event_date(cls, v: str) -> str:
        return v if v == "" else check_date(v)

    @model_validator(mode="after")
    def _event_precision(self) -> Self:
        check_event_date_precision(self.event_date, self.date_precision)
        return self


def _non_empty(v: str, name: str) -> str:
    if not v.strip():
        raise ValueError(f"{name} must not be empty")
    return v


def _raw_number(v: str) -> str:
    """A raw value as written: non-empty and contains a digit (rejects unknown, N/A, "")."""
    if not _HAS_DIGIT.search(v):
        raise ValueError("raw_value must contain the number as written")
    return v


class PatientIdentity(Fact):
    patient_id: str = Field(description='Identifier as written; "" when not stated')
    name: str = Field(description='Name as written; "" when not stated')
    dob: str | None = Field(description="YYYY-MM-DD; null when not stated")
    stated_age: int | None = Field(ge=0, description="Age in years as stated; null when absent")

    @field_validator("dob")
    @classmethod
    def _dob(cls, v: str | None) -> str | None:
        if v is not None:
            check_date(v)
            if len(v) != 10:
                raise ValueError("dob must be YYYY-MM-DD")
        return v


class DocDate(Fact):
    target_doc_id: str
    date: str = Field(description="YYYY, YYYY-MM or YYYY-MM-DD")

    @field_validator("target_doc_id")
    @classmethod
    def _target(cls, v: str) -> str:
        if not _SAFE_ID.match(v):
            raise ValueError("target_doc_id must be a safe id")
        return v

    @field_validator("date")
    @classmethod
    def _date(cls, v: str) -> str:
        return check_date(v)


class Glp1Start(Fact):
    drug: str = Field(description="Drug name as written")
    date: str | None = Field(description="Start date YYYY, YYYY-MM or YYYY-MM-DD; null if absent")
    purpose: Purpose

    @field_validator("drug")
    @classmethod
    def _drug(cls, v: str) -> str:
        return _non_empty(v, "drug")

    @field_validator("date")
    @classmethod
    def _date(cls, v: str | None) -> str | None:
        return check_optional_date(v)


class PriorGlp1(Fact):
    drug: str = Field(description="Drug name as written")
    date: str | None = Field(description="Fill date YYYY, YYYY-MM or YYYY-MM-DD; null if absent")
    payer: Payer
    compounded: bool | None = Field(description="null when the document does not say")

    @field_validator("drug")
    @classmethod
    def _drug(cls, v: str) -> str:
        return _non_empty(v, "drug")

    @field_validator("date")
    @classmethod
    def _date(cls, v: str | None) -> str | None:
        return check_optional_date(v)


class Anthropometric(Fact):
    kind: AnthropometricKind
    raw_value: str = Field(description="Value exactly as written in the quote")
    raw_unit: str = Field(description='Unit exactly as written; "" when none is written')

    @field_validator("raw_value")
    @classmethod
    def _raw(cls, v: str) -> str:
        return _raw_number(v)


class BpReading(Fact):
    sbp: int = Field(gt=0)
    dbp: int = Field(gt=0)


class Lab(Fact):
    kind: LabKind
    raw_value: str = Field(description="Value exactly as written in the quote")
    raw_unit: str = Field(description='Unit exactly as written; "" when none is written')

    @field_validator("raw_value")
    @classmethod
    def _raw(cls, v: str) -> str:
        return _raw_number(v)


class Medication(Fact):
    name: str = Field(description="Drug name as written")
    dose: str = Field(description='Dose as written; "" when not stated')
    indication: str = Field(description='Indication as written; "" when not stated')
    start: str | None = Field(description="YYYY, YYYY-MM or YYYY-MM-DD; null when not stated")
    start_precision: DatePrecision | None = Field(description="null exactly when start is null")
    end: str | None = Field(description="YYYY, YYYY-MM or YYYY-MM-DD; null when not stated")
    end_precision: DatePrecision | None = Field(description="null exactly when end is null")
    end_kind: EndKind
    list_id: str = Field(description='medication_lists[].list_id this entry belongs to; "" if none')

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return _non_empty(v, "name")

    @field_validator("start", "end")
    @classmethod
    def _dates(cls, v: str | None) -> str | None:
        return check_optional_date(v)

    @model_validator(mode="after")
    def _precisions(self) -> Self:
        check_nullable_precision(self.start, self.start_precision, "start")
        check_nullable_precision(self.end, self.end_precision, "end")
        return self


class MedicationList(Fact):
    list_id: str
    complete: bool = Field(description="true only when the document says the list is complete")
    section_title: str = Field(description='Section heading as written; "" when none')

    @field_validator("list_id")
    @classmethod
    def _list_id(cls, v: str) -> str:
        return _non_empty(v, "list_id")


class Diagnosis(Fact):
    concept: Concept
    osa_severity: OsaSeverity = Field(description='"unspecified" unless OSA severity is written')
    ahi: float | None = Field(ge=0, description="Apnea-hypopnea index; null when absent")
    fibrosis_stage: str = Field(description='F0 to F4 as written; "" when not stated')
    cirrhosis: bool | None = Field(description="null when the document does not say")
    ckd_stage: str = Field(description='1, 2, 3a, 3b, 4 or 5; "" when not stated')
    symptomatic: Symptomatic

    @field_validator("fibrosis_stage")
    @classmethod
    def _fibrosis(cls, v: str) -> str:
        if v and not _FIBROSIS.match(v):
            raise ValueError("fibrosis_stage must be F0 to F4 or empty")
        return v

    @field_validator("ckd_stage")
    @classmethod
    def _ckd(cls, v: str) -> str:
        if v and not _CKD.match(v):
            raise ValueError("ckd_stage must be 1, 2, 3a, 3b, 4, 5 or empty")
        return v


class Lifestyle(Fact):
    kind: LifestyleKind
    program_type: ProgramType
    attendance: Attendance
    start: str | None = Field(description="YYYY, YYYY-MM or YYYY-MM-DD; null when not stated")
    end: str | None = Field(description="YYYY, YYYY-MM or YYYY-MM-DD; null when not stated")
    end_kind: EndKind
    limitation: str = Field(description='Medical limitation as written; "" when none')
    description: str = Field(description="Short description of the program or activity")

    @field_validator("start", "end")
    @classmethod
    def _dates(cls, v: str | None) -> str | None:
        return check_optional_date(v)


class PaFormClaim(Fact):
    claim_id: str = Field(
        description="Which form field the claim is; one of the listed ids",
        json_schema_extra={"enum": list(CLAIM_IDS)},
    )
    claimed_value: str = Field(
        description=(
            "Box or bracket as written on the form: the drug name for claim.drug, the BMI "
            "bracket for claim.bmi_bracket, else yes / no / checked / unchecked / unknown"
        )
    )

    @field_validator("claim_id")
    @classmethod
    def _claim_id(cls, v: str) -> str:
        if v not in CLAIM_IDS:
            raise ValueError("unknown claim_id")
        return v

    @model_validator(mode="after")
    def _claimed_value(self) -> Self:
        v = self.claimed_value
        if self.claim_id == "claim.drug":
            ok = v in GLP1_NAMES
        elif self.claim_id == "claim.bmi_bracket":
            ok = _BMI_BRACKET.match(v) is not None
        else:
            ok = v in CLAIMED_VALUE_TOKENS
        if not ok:
            raise ValueError("claimed_value does not fit this claim")
        return self


class Extraction(_Strict):
    """The whole model reply. Every array is required in the API schema; locally a missing
    array is an empty one (contract §7.2)."""

    patient_identity: list[PatientIdentity] = Field(default_factory=list)
    doc_dates: list[DocDate] = Field(default_factory=list)
    glp1_start: list[Glp1Start] = Field(default_factory=list)
    prior_glp1: list[PriorGlp1] = Field(default_factory=list)
    anthropometrics: list[Anthropometric] = Field(default_factory=list)
    bp_readings: list[BpReading] = Field(default_factory=list)
    labs: list[Lab] = Field(default_factory=list)
    medications: list[Medication] = Field(default_factory=list)
    medication_lists: list[MedicationList] = Field(default_factory=list)
    diagnoses: list[Diagnosis] = Field(default_factory=list)
    lifestyle: list[Lifestyle] = Field(default_factory=list)
    pa_form_claims: list[PaFormClaim] = Field(default_factory=list)


def _strip_defaults(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _strip_defaults(v) for k, v in node.items() if k != "default"}
    if isinstance(node, list):
        return [_strip_defaults(v) for v in node]
    return node


def pydantic_json_schema() -> dict[str, Any]:
    """The local JSON schema with every property required (serialization mode)."""
    schema: dict[str, Any] = _strip_defaults(Extraction.model_json_schema(mode="serialization"))
    return schema


def extraction_json_schema() -> dict[str, Any]:
    """`transform_schema()` output of the local schema. Not sent (ADR 0002); a local check
    that the schema still compiles under the structured-output rules, and its size."""
    from anthropic import transform_schema

    return transform_schema(pydantic_json_schema())


def count_union_params(schema: Any) -> int:
    """Number of union-typed parameters (`anyOf`, `oneOf` or a list-valued `type`)."""
    count = 0
    if isinstance(schema, dict):
        if "anyOf" in schema or "oneOf" in schema or isinstance(schema.get("type"), list):
            count += 1
        for value in schema.values():
            count += count_union_params(value)
    elif isinstance(schema, list):
        for value in schema:
            count += count_union_params(value)
    return count


def count_optional_params(schema: Any) -> int:
    """Number of object properties not listed in `required`."""
    count = 0
    if isinstance(schema, dict):
        props = schema.get("properties")
        if isinstance(props, dict):
            required = set(schema.get("required", []))
            count += sum(1 for k in props if k not in required)
        for value in schema.values():
            count += count_optional_params(value)
    elif isinstance(schema, list):
        for value in schema:
            count += count_optional_params(value)
    return count
