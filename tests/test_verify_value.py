"""Layer 3 value-in-quote (06 §3): the raw value as written must be readable from the span."""

from __future__ import annotations

import pytest
from conftest import fact, run_verify

from bridge_check.verify import dates_in, parse_raw_number


def _reasons(
    doc: str, fact_field: str, quote: str | None = None, **fields: object
) -> tuple[str, ...]:
    result = run_verify({"D1": doc}, {fact_field: [fact(fact_field, quote or doc, **fields)]})
    ev = result.evidence[0]
    assert ev.position_status in ("verbatim", "normalized"), ev.fact_path
    return tuple(
        r for r in ev.exclusion_reasons if r in ("value_not_in_quote", "unparseable_value")
    )


@pytest.mark.parametrize(
    ("doc", "raw_value", "raw_unit", "expected"),
    [
        ("Weight 98.0 kg.", "98.0", "kg", ()),
        ("Weight 98.0 kg.", "98", "kg", ("value_not_in_quote",)),  # as written: 98.0 is not 98
        ("Weight 98 kg.", "98.0", "kg", ("value_not_in_quote",)),
        ("Weight 1,204 lb.", "1204", "lb", ()),  # thousands separator
        ("Weight 1,204 lb.", "1,204", "lb", ()),
        ("eGFR >90 mL/min.", ">90", "mL/min", ()),
        ("eGFR >90 mL/min.", "90", "mL/min", ("value_not_in_quote",)),  # comparator dropped
        ("eGFR ≥ 60 mL/min.", ">=60", "mL/min", ()),
        ("A1c < 5.7 %.", "<5.7", "%", ()),
        ("BMI 34,6 noted.", "34.6", "", ("value_not_in_quote",)),  # decimal comma: format
        ("BMI 34,6 noted.", "34,6", "", ("unparseable_value",)),
        ("BMI 34.6 noted.", "34.6.1", "", ("unparseable_value",)),
        ("Weight 98.0 kg.", "98.0", "lb", ("value_not_in_quote",)),  # unit not written
        ("BMI 31.2 kg/m².", "31.2", "kg/m2", ()),  # NFKC superscript two
        ("Weight 130 kg a year ago, 128 kg now.", "128", "kg", ()),
    ],
)
def test_numbers_and_units(
    doc: str, raw_value: str, raw_unit: str, expected: tuple[str, ...]
) -> None:
    # The fact's kind is the label the sentence starts with (values bind to their label).
    field, kind = _KINDS[doc.split()[0]]
    assert _reasons(doc, field, kind=kind, raw_value=raw_value, raw_unit=raw_unit) == expected


_KINDS = {
    "Weight": ("anthropometrics", "weight"),
    "BMI": ("anthropometrics", "bmi"),
    "eGFR": ("labs", "egfr"),
    "A1c": ("labs", "a1c"),
}


def test_raw_number_grammar() -> None:
    assert parse_raw_number("1,204.5") == "1204.5"
    assert parse_raw_number(">= 30") == "≥30"
    assert parse_raw_number("30-34.9") is None
    assert parse_raw_number("34,6") is None


def test_converted_value_needs_no_conversion_in_the_quote() -> None:
    # The raw value is the pounds as written; the kg conversion is compute's job.
    assert (
        _reasons("Weight 216 lb.", "anthropometrics", kind="weight", raw_value="216", raw_unit="lb")
        == ()
    )


@pytest.mark.parametrize(
    ("doc", "sbp", "dbp", "expected"),
    [
        ("BP 146/92 mmHg.", 146, 92, ()),
        ("BP 146 / 92.", 146, 92, ()),
        ("BP 146 over 92.", 146, 92, ()),
        ("BP 146/92 mmHg.", 146, 94, ("value_not_in_quote",)),
        ("BP 1146/92.", 146, 92, ("value_not_in_quote",)),
    ],
)
def test_bp(doc: str, sbp: int, dbp: int, expected: tuple[str, ...]) -> None:
    assert _reasons(doc, "bp_readings", sbp=sbp, dbp=dbp) == expected


@pytest.mark.parametrize(
    ("doc", "concept", "expected"),
    [
        ("History of T2DM.", "t2dm", ()),
        ("History of type 2 diabetes.", "t2dm", ()),
        ("Long-standing HTN.", "hypertension", ()),
        ("Biopsy-proven NASH.", "mash", ()),
        ("Prior CVA.", "stroke", ()),
        ("Type 1 diabetes since childhood.", "t2dm", ("value_not_in_quote",)),
        ("Prior TIA.", "stroke", ("value_not_in_quote",)),
        ("Pre-diabetes on labs.", "t2dm", ("value_not_in_quote",)),
        ("Pre-diabetes on labs.", "prediabetes", ()),
        ("Knee pad used.", "pad", ("value_not_in_quote",)),  # "pad" is not PAD
        ("Hypertension noted.", "stroke", ("value_not_in_quote",)),
        ("Anything at all.", "other", ()),
    ],
)
def test_concept_aliases(doc: str, concept: str, expected: tuple[str, ...]) -> None:
    assert _reasons(doc, "diagnoses", concept=concept) == expected


def test_diagnosis_details_must_be_written() -> None:
    assert _reasons("CKD stage 3a.", "diagnoses", concept="ckd", ckd_stage="3a") == ()
    assert _reasons("CKD stage 3b.", "diagnoses", concept="ckd", ckd_stage="3a") == (
        "value_not_in_quote",
    )
    assert (
        _reasons(
            "Moderate OSA, AHI 22.", "diagnoses", concept="osa", osa_severity="moderate", ahi=22.0
        )
        == ()
    )
    assert _reasons("OSA, AHI 22.", "diagnoses", concept="osa", osa_severity="severe") == (
        "value_not_in_quote",
    )
    assert _reasons("MASH with F2 fibrosis.", "diagnoses", concept="mash", fibrosis_stage="F3") == (
        "value_not_in_quote",
    )


@pytest.mark.parametrize(
    ("doc", "value", "expected"),
    [
        ("Started Wegovy on 2025-03-15.", "2025-03-15", ()),
        ("Started Wegovy on 3/15/2025.", "2025-03-15", ()),
        ("Started Wegovy on March 15, 2025.", "2025-03-15", ()),
        ("Started Wegovy on 15 March 2025.", "2025-03-15", ()),
        ("Started Wegovy on Mar. 15, 2025.", "2025-03-15", ()),
        ("Started Wegovy in March 2025.", "2025-03", ()),
        ("Started Wegovy in 2025.", "2025", ()),
        ("Started Wegovy on 2025-03-15.", "2025-03-16", ("value_not_in_quote",)),
        ("Started Wegovy in March 2025.", "2025-03-15", ("value_not_in_quote",)),  # precision
        ("Started Wegovy in mid-March.", "2025-03", ("value_not_in_quote",)),
    ],
)
def test_glp1_dates(doc: str, value: str, expected: tuple[str, ...]) -> None:
    assert _reasons(doc, "glp1_start", date=value) == expected


def test_dates_in_ignores_impossible_dates() -> None:
    assert dates_in("2025-02-30") == []


def test_identity_values() -> None:
    doc = "Patient ID: P-0001. DOB 01/01/1960. Age 65."
    assert (
        _reasons(doc, "patient_identity", patient_id="P-0001", dob="1960-01-01", stated_age=65)
        == ()
    )
    assert _reasons(doc, "patient_identity", patient_id="P0001") == ()  # hyphen-insensitive
    assert _reasons(doc, "patient_identity", patient_id="P-0002") == ("value_not_in_quote",)
    assert _reasons(doc, "patient_identity", dob="1960-01-02") == ("value_not_in_quote",)


def test_medication_and_claim_values() -> None:
    assert _reasons("Amlodipine 5 mg daily.", "medications", name="amlodipine", dose="5 mg") == ()
    assert _reasons("Amlodipine 5 mg daily.", "medications", name="lisinopril") == (
        "value_not_in_quote",
    )
    assert (
        _reasons(
            "BMI bracket: 30–34.9",
            "pa_form_claims",
            claim_id="claim.bmi_bracket",
            claimed_value="30-34.9",
        )
        == ()
    )
    assert _reasons("Drug: Zepbound", "pa_form_claims", claimed_value="Wegovy") == (
        "value_not_in_quote",
    )
