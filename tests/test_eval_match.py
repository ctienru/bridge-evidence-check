"""Matching-side invariants of contract §8 (`eval_match.is_match`). The four tests the contract
names (`test_family_bp_is_not_patient_tp`, ...) live in `tests/test_scoring.py`."""

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
