"""Matching-side invariants of contract §8 against the key-comparison stub (no scoring)."""

from __future__ import annotations

from bridge_check.enums import EXTRACTION_FIELDS
from bridge_check.eval_match import is_match, match_keys

_AXES = {"certainty": "present", "subject": "patient", "temporality": "current"}


def _bp(**over: object) -> dict[str, object]:
    return {
        "field": "bp_readings",
        **_AXES,
        "doc_id": "D2",
        "sbp": 152,
        "dbp": 94,
        "relative_to_glp1_initiation": "at",
        **over,
    }


def test_every_field_has_match_keys() -> None:
    for field in EXTRACTION_FIELDS:
        assert set(match_keys(field)) >= {"certainty", "subject", "temporality", "field"}


def test_family_bp_is_not_patient_tp() -> None:
    gold = _bp(subject="family")
    assert not is_match(gold, _bp(subject="patient"))
    assert is_match(gold, _bp(subject="family"))


def test_wrong_med_period_is_not_tp() -> None:
    gold = {
        "field": "medications",
        **_AXES,
        "doc_id": "D2",
        "drug_canonical": "amlodipine",
        "start": "2024-01",
        "end": None,
        "end_kind": "ongoing",
        "list_id": "L1",
    }
    assert is_match(gold, dict(gold))
    assert not is_match(gold, {**gold, "start": "2025-01"})
    assert not is_match(gold, {**gold, "end_kind": "unknown"})


def test_ckd2_is_not_ckd3a_tp() -> None:
    gold = {"field": "diagnoses", **_AXES, "doc_id": "D2", "concept": "ckd", "ckd_stage": "3a"}
    assert not is_match(gold, {**gold, "ckd_stage": "2"})
    assert is_match(gold, {**gold, "ckd_stage": "3a"})
    # an attribute gold does not state is not compared
    assert is_match({**gold, "ckd_stage": ""}, {**gold, "ckd_stage": "2"})


def test_missing_gold_date_is_not_tp() -> None:
    gold = {
        "field": "anthropometrics",
        **_AXES,
        "doc_id": "D2",
        "kind": "bmi",
        "norm_value": 46.0,
        "relative_to_glp1_initiation": "at",
        "event_date": "2025-03-15",
    }
    assert not is_match(gold, {**gold, "event_date": None})
    assert not is_match(gold, {**gold, "event_date": "2025-03-16"})
    assert is_match(gold, {**gold, "norm_value": "46.1"})  # within the BMI tolerance
    assert not is_match(gold, {**gold, "norm_value": "46.3"})


def test_labs_compare_exactly() -> None:
    gold = {
        "field": "labs",
        **_AXES,
        "doc_id": "D2",
        "kind": "a1c",
        "norm_value": "6.1",
        "relative_to_glp1_initiation": "before",
    }
    assert is_match(gold, {**gold, "norm_value": 6.1})
    assert not is_match(gold, {**gold, "norm_value": "6.10001"})
