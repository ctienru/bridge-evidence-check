"""Extraction schema v1 (contract §7.2): constraints, placeholders, and API compilation."""

from __future__ import annotations

import json
import typing
from pathlib import Path
from typing import Any

import pytest
from anthropic import transform_schema
from pydantic import ValidationError

from bridge_check import enums
from bridge_check.enums import EXTRACTION_FIELDS
from bridge_check.schema import (
    UNION_LIMIT,
    Extraction,
    count_optional_params,
    count_union_params,
    extraction_json_schema,
    pydantic_json_schema,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "synthetic" / "extract"


def _valid() -> dict[str, Any]:
    resp = json.loads((FIXTURES / "response_valid.json").read_text(encoding="utf-8"))
    text = next(b["text"] for b in resp["content"] if b["type"] == "text")
    data: dict[str, Any] = json.loads(text)
    return data


def _with(field: str, **changes: Any) -> dict[str, Any]:
    data = _valid()
    data[field] = [{**data[field][0], **changes}]
    return data


def test_valid_fixture_parses() -> None:
    ext = Extraction.model_validate(_valid())
    assert ext.bp_readings[0].sbp == 146


def test_missing_arrays_are_empty() -> None:
    ext = Extraction.model_validate({})
    for field in EXTRACTION_FIELDS:
        assert getattr(ext, field) == []


def test_model_has_exactly_the_contract_arrays() -> None:
    assert tuple(Extraction.model_fields) == EXTRACTION_FIELDS


def test_extra_keys_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Extraction.model_validate({**_valid(), "notes": []})
    with pytest.raises(ValidationError):
        Extraction.model_validate(_with("bp_readings", comment="x"))


@pytest.mark.parametrize("placeholder", ["unknown", "N/A", ""])
@pytest.mark.parametrize(
    ("field", "key"),
    [("bp_readings", "sbp"), ("bp_readings", "dbp"), ("patient_identity", "stated_age")],
)
def test_numeric_fields_reject_placeholders(field: str, key: str, placeholder: str) -> None:
    with pytest.raises(ValidationError):
        Extraction.model_validate(_with(field, **{key: placeholder}))


@pytest.mark.parametrize("placeholder", ["unknown", "N/A", ""])
def test_raw_values_reject_placeholders(placeholder: str) -> None:
    with pytest.raises(ValidationError):
        Extraction.model_validate(_with("anthropometrics", raw_value=placeholder))


@pytest.mark.parametrize(
    "placeholder", ["unknown", "N/A", "", "2025-13", "2025-02-30", "03/15/2025"]
)
@pytest.mark.parametrize(
    ("field", "key"),
    [
        ("glp1_start", "date"),
        ("doc_dates", "date"),
        ("patient_identity", "dob"),
        ("medications", "start"),
        ("lifestyle", "start"),
    ],
)
def test_date_fields_reject_placeholders(field: str, key: str, placeholder: str) -> None:
    data = _valid()
    if field == "lifestyle":
        data["lifestyle"] = [_lifestyle()]
    data[field] = [{**data[field][0], key: placeholder}]
    with pytest.raises(ValidationError):
        Extraction.model_validate(data)


def test_doc_dates_date_may_not_be_empty() -> None:
    with pytest.raises(ValidationError):
        Extraction.model_validate(_with("doc_dates", date=""))


@pytest.mark.parametrize("placeholder", ["unknown", "N/A"])
def test_event_date_rejects_placeholders(placeholder: str) -> None:
    with pytest.raises(ValidationError):
        Extraction.model_validate(_with("bp_readings", event_date=placeholder))


def test_fallback_empty_date_requires_precision_none() -> None:
    # §7.2 fallback: precision `none` exactly when event_date is "".
    Extraction.model_validate(_with("bp_readings", event_date="", date_precision="none"))
    with pytest.raises(ValidationError):
        Extraction.model_validate(_with("bp_readings", event_date="", date_precision="day"))
    with pytest.raises(ValidationError):
        Extraction.model_validate(
            _with("bp_readings", event_date="2025-03-15", date_precision="none")
        )
    with pytest.raises(ValidationError):
        Extraction.model_validate(_with("bp_readings", event_date="2025-03", date_precision="day"))
    with pytest.raises(ValidationError):
        Extraction.model_validate(_with("medications", start="2025", start_precision="none"))


def test_empty_string_is_accepted_only_in_event_date() -> None:
    # The fallback covers event_date alone (contract §7.2); other dates are null.
    base = _valid()["glp1_start"][0]
    assert base["event_date"]
    with pytest.raises(ValidationError):
        Extraction.model_validate(_with("glp1_start", date=""))
    Extraction.model_validate(_with("glp1_start", date=None))
    with pytest.raises(ValidationError):
        Extraction.model_validate(_with("patient_identity", dob=""))
    with pytest.raises(ValidationError):
        Extraction.model_validate(_with("medications", start="", start_precision=None))


def test_nullable_dates_pair_with_their_precision() -> None:
    Extraction.model_validate(_with("medications", start="2024-01", start_precision="month"))
    Extraction.model_validate(_with("medications", start=None, start_precision=None))
    with pytest.raises(ValidationError):
        Extraction.model_validate(_with("medications", start="2024-01", start_precision=None))
    with pytest.raises(ValidationError):
        Extraction.model_validate(_with("medications", start=None, start_precision="day"))
    with pytest.raises(ValidationError):
        Extraction.model_validate(_with("medications", end="2024", end_precision="month"))


def _lifestyle() -> dict[str, Any]:
    return {
        "doc_id": "D1-referral",
        "quote": "q",
        "certainty": "present",
        "subject": "patient",
        "temporality": "current",
        "event_date": "",
        "date_precision": "none",
        "relative_to_glp1_initiation": "unknown",
        "kind": "nutrition",
        "program_type": "advice_only",
        "attendance": "unknown",
        "start": None,
        "end": None,
        "end_kind": "unknown",
        "limitation": "",
        "description": "d",
    }


@pytest.mark.parametrize(
    ("field", "key"),
    [
        ("glp1_start", "purpose"),
        ("medications", "end_kind"),
        ("diagnoses", "symptomatic"),
        ("bp_readings", "relative_to_glp1_initiation"),
    ],
)
def test_unknown_is_legal_in_section_6_enum_fields(field: str, key: str) -> None:
    Extraction.model_validate(_with(field, **{key: "unknown"}))


def test_unknown_is_legal_for_payer_and_attendance() -> None:
    data = _valid()
    data["prior_glp1"] = [
        {**data["glp1_start"][0], "payer": "unknown", "compounded": None}
        | {"drug": "Ozempic", "date": None}
    ]
    del data["prior_glp1"][0]["purpose"]
    data["lifestyle"] = [_lifestyle()]
    Extraction.model_validate(data)


@pytest.mark.parametrize(
    ("field", "key"),
    [
        ("bp_readings", "certainty"),
        ("diagnoses", "concept"),
        ("diagnoses", "osa_severity"),
        ("anthropometrics", "kind"),
        ("medications", "start_precision"),
    ],
)
def test_unknown_is_rejected_in_other_enums(field: str, key: str) -> None:
    with pytest.raises(ValidationError):
        Extraction.model_validate(_with(field, **{key: "unknown"}))


def test_strict_types_reject_coercion() -> None:
    with pytest.raises(ValidationError):
        Extraction.model_validate(_with("bp_readings", sbp="146"))
    with pytest.raises(ValidationError):
        Extraction.model_validate(_with("bp_readings", sbp=True))
    with pytest.raises(ValidationError):
        Extraction.model_validate(_with("medication_lists", complete="false"))


def test_claimed_value_must_fit_the_claim() -> None:
    with pytest.raises(ValidationError):
        Extraction.model_validate(_with("pa_form_claims", claimed_value="the patient qualifies"))
    with pytest.raises(ValidationError):
        Extraction.model_validate(_with("pa_form_claims", claim_id="claim.eligible"))


def test_schema_compiles_with_transform_schema() -> None:
    schema = extraction_json_schema()
    assert schema == transform_schema(pydantic_json_schema())
    assert schema["type"] == "object"
    assert set(schema["required"]) == set(EXTRACTION_FIELDS)
    _assert_closed_objects(schema)


def test_schema_is_within_structured_output_limits() -> None:
    schema = extraction_json_schema()
    unions = count_union_params(schema)
    assert unions <= UNION_LIMIT, f"{unions} union-typed parameters (limit {UNION_LIMIT})"
    # 4 nullable scalars + 9 nullable dates and precisions; see the schema docstring.
    assert unions == 13
    assert count_optional_params(schema) == 0


def test_schema_has_no_patient_data_in_names_or_enums() -> None:
    text = json.dumps(extraction_json_schema())
    for needle in ("P-0000", "Synthetic Patient", "1958-06-01"):
        assert needle not in text


def _assert_closed_objects(node: Any) -> None:
    if isinstance(node, dict):
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False
        for v in node.values():
            _assert_closed_objects(v)
    elif isinstance(node, list):
        for v in node:
            _assert_closed_objects(v)


@pytest.mark.parametrize(
    ("literal", "values"),
    [
        (enums.Status, enums.STATUS_CODES),
        (enums.Certainty, enums.CERTAINTY),
        (enums.Subject, enums.SUBJECT),
        (enums.Temporality, enums.TEMPORALITY),
        (enums.RelativeToInitiation, enums.RELATIVE_TO_INITIATION),
        (enums.DocRole, enums.DOC_ROLES),
        (enums.RunStatus, enums.RUN_STATUSES),
        (enums.FailedStage, enums.FAILED_STAGES),
        (enums.AttemptStatus, enums.ATTEMPT_STATUSES),
        (enums.ExtractionSource, enums.EXTRACTION_SOURCES),
        (enums.ExtractionDatePrecision, enums.EXTRACTION_DATE_PRECISIONS),
        (enums.DatePrecision, enums.DATE_PRECISIONS),
        (enums.Concept, enums.CONCEPTS),
        (enums.Payer, enums.PAYERS),
        (enums.Purpose, enums.PURPOSES),
        (enums.EndKind, enums.END_KINDS),
        (enums.OsaSeverity, enums.OSA_SEVERITIES),
        (enums.Symptomatic, enums.SYMPTOMATIC),
        (enums.ProgramType, enums.PROGRAM_TYPES),
        (enums.Attendance, enums.ATTENDANCE),
    ],
)
def test_literal_types_match_value_tuples(literal: Any, values: tuple[str, ...]) -> None:
    assert typing.get_args(literal) == values


def test_kind_literals_partition_kinds() -> None:
    parts = (
        typing.get_args(enums.AnthropometricKind)
        + typing.get_args(enums.LabKind)
        + typing.get_args(enums.LifestyleKind)
    )
    assert parts == enums.KINDS
