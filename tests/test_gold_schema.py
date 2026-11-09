from __future__ import annotations

import json
from typing import Any

import pytest
from conftest import FIXTURES
from pydantic import ValidationError

from bridge_check.enums import FORBIDDEN_ENTRY_KEYS
from bridge_check.gold_schema import AdjudicationLine, BlindDraft, Gold, format_errors


def _blind() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / "blind_draft_valid.json").read_text("utf-8"))
    return data


def _lines() -> list[dict[str, Any]]:
    text = (FIXTURES / "adjudication_valid.jsonl").read_text("utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _gold() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / "expected_valid.json").read_text("utf-8"))
    return data


def test_valid_fixtures_pass() -> None:
    BlindDraft.model_validate(_blind())
    for line in _lines():
        AdjudicationLine.model_validate(line)
    Gold.model_validate(_gold())


def test_blind_draft_rejects_claims_and_extra_keys() -> None:
    data = _blind()
    data["conditions"].append({"id": "claim.bmi_bracket", "status": "supported"})
    with pytest.raises(ValidationError) as exc:
        BlindDraft.model_validate(data)
    assert any("claim.*" in line for line in format_errors(exc.value))
    data = _blind()
    data["inventory"][0]["quote"] = "text"
    with pytest.raises(ValidationError):
        BlindDraft.model_validate(data)
    data = _blind()
    data["conditions"][0]["status"] = "eligible"
    with pytest.raises(ValidationError):
        BlindDraft.model_validate(data)


@pytest.mark.parametrize("key", FORBIDDEN_ENTRY_KEYS)
def test_adjudication_rejects_forbidden_keys_and_names_them(key: str) -> None:
    line = _lines()[0]
    line["final"][key] = "secret value"
    with pytest.raises(ValidationError) as exc:
        AdjudicationLine.model_validate(line)
    rendered = "\n".join(format_errors(exc.value))
    assert "final" in rendered and key in rendered and "quote" in rendered
    assert "secret value" not in rendered


def test_adjudication_rejects_unknown_key_bad_clause_bad_scan_hit() -> None:
    line = _lines()[0]
    line["candidate"]["sentence_id"] = 3
    with pytest.raises(ValidationError):
        AdjudicationLine.model_validate(line)
    line = _lines()[0]
    line["guideline_clause"] = "X-01"
    with pytest.raises(ValidationError):
        AdjudicationLine.model_validate(line)
    line = _lines()[2]
    line["scan_hit"]["text"] = "the sentence"
    with pytest.raises(ValidationError):
        AdjudicationLine.model_validate(line)
    line = _lines()[3]
    del line["condition_id"]
    with pytest.raises(ValidationError):
        AdjudicationLine.model_validate(line)


def test_gold_mtsamples_fact_with_quote_is_rejected() -> None:
    gold = _gold()
    gold["facts"][0]["quote"] = "leaked text"
    with pytest.raises(ValidationError) as exc:
        Gold.model_validate(gold)
    rendered = "\n".join(format_errors(exc.value))
    assert "facts.0" in rendered and "quote" in rendered and "leaked" not in rendered
    gold = _gold()
    del gold["facts"][0]["quote_sha256"]
    with pytest.raises(ValidationError):
        Gold.model_validate(gold)


def test_gold_non_mtsamples_fact_needs_quote_not_hash() -> None:
    gold = _gold()
    gold["facts"][1]["quote_sha256"] = "ab" * 32
    with pytest.raises(ValidationError):
        Gold.model_validate(gold)
    gold = _gold()
    del gold["facts"][1]["quote"]
    with pytest.raises(ValidationError):
        Gold.model_validate(gold)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda g: g["conditions"][0]["flags"].append("looks_fine"),
        lambda g: g["facts"][0].__setitem__("review", "model_verified"),
        lambda g: g["facts"][0].__setitem__("origin", "guess"),
        lambda g: g["facts"][0].__setitem__("event_date", "2025-3-14"),
        lambda g: g["facts"][0].__setitem__("event_date", "2025-13"),
        lambda g: g["facts"][0].__setitem__("relative_to_glp1_initiation", "later"),
        lambda g: g["facts"][0].__setitem__("raw_value", "285.4"),
        lambda g: g["facts"][0].__setitem__("end", 812),
        lambda g: g["conditions"][0].__setitem__("id", "claim.bmi_bracket"),
        lambda g: g["claims"][0].__setitem__("id", "bmi_bracket"),
        lambda g: g["expected_absent"].append({"field": "labs"}),
        lambda g: g.__setitem__("gold_version", 0),
    ],
)
def test_gold_invalid_variants(mutate: Any) -> None:
    gold = _gold()
    mutate(gold)
    with pytest.raises(ValidationError):
        Gold.model_validate(gold)


def test_mtsamples_quote_null_is_rejected_by_presence() -> None:
    gold = _gold()
    gold["facts"][0]["quote"] = None
    with pytest.raises(ValidationError):
        Gold.model_validate(gold)
    gold = _gold()
    gold["facts"][1]["quote_sha256"] = None
    with pytest.raises(ValidationError):
        Gold.model_validate(gold)


def test_exclusion_supported_is_rejected_in_gold_and_blind() -> None:
    gold = _gold()
    gold["conditions"][1]["status"] = "supported"  # exclusion.osa
    with pytest.raises(ValidationError, match="never supported"):
        Gold.model_validate(gold)
    blind = _blind()
    blind["conditions"][13]["status"] = "supported"  # exclusion.t2dm
    with pytest.raises(ValidationError, match="never supported"):
        BlindDraft.model_validate(blind)


def test_gold_only_scoring_keys() -> None:
    gold = _gold()
    gold["facts"].append(
        {
            "field": "medication_lists",
            "complete": True,
            "list_id": "L1",
            "doc_id": "D1-referral",
            "start": 10,
            "end": 40,
            "quote": "synthetic medication list header",
            "certainty": "present",
            "subject": "patient",
            "temporality": "current",
            "event_date": None,
            "relative_to_glp1_initiation": "unknown",
            "origin": "spec",
            "review": "human_verified",
            "guideline_clause": None,
        }
    )
    gold["facts"].append(
        {
            "field": "patient_identity",
            "patient_id": "P-1042",
            "dob": "1961-04-02",
            "stated_age": 55,
            "doc_id": "D1-referral",
            "start": 0,
            "end": 9,
            "quote": "synthetic",
            "certainty": "present",
            "subject": "patient",
            "temporality": "current",
            "event_date": None,
            "relative_to_glp1_initiation": "unknown",
            "origin": "spec",
            "review": "human_verified",
            "guideline_clause": None,
        }
    )
    Gold.model_validate(gold)
    # on an MTSamples document the normalized age is fine (C-01); id and dob are text
    gold["facts"][-1]["doc_id"] = "D2-mtsamples-0000"
    del gold["facts"][-1]["quote"]
    gold["facts"][-1]["quote_sha256"] = "ab" * 32
    with pytest.raises(ValidationError, match="identity values"):
        Gold.model_validate(gold)
    del gold["facts"][-1]["patient_id"]
    del gold["facts"][-1]["dob"]
    Gold.model_validate(gold)  # stated_age 55 remains
    gold["facts"][-1]["stated_age"] = 1961
    with pytest.raises(ValidationError):
        Gold.model_validate(gold)
    # these keys stay forbidden in adjudication lines
    line = _lines()[0]
    line["final"]["complete"] = True
    with pytest.raises(ValidationError):
        AdjudicationLine.model_validate(line)


@pytest.mark.parametrize("slot", ["candidate", "final"])
def test_unknown_entry_key_is_counted_not_named(slot: str) -> None:
    line = _lines()[0]
    line[slot]["janedoe_marker"] = 1
    with pytest.raises(ValidationError) as exc:
        AdjudicationLine.model_validate(line)
    rendered = "\n".join(format_errors(exc.value))
    assert slot in rendered and "1 key(s) not in the L-01 allow-list" in rendered
    assert "janedoe" not in rendered


def test_pa_form_values_in_adjudication_and_gold() -> None:
    line = _lines()[0]
    line["field"] = "pa_form_claims"
    del line["concept"]
    pairs = (("claim.drug", "Wegovy"), ("claim.bmi_bracket", "<27"), ("claim.age_18", "yes"))
    for claim_id, value in pairs:
        line["final"] = {
            "doc_id": "D0-pa",
            "start": 1,
            "end": 9,
            "sha8": "9b3c1e7a",
            "field": "pa_form_claims",
            "claim_id": claim_id,
            "claimed_value": value,
            "certainty": "present",
            "subject": "patient",
            "temporality": "current",
        }
        AdjudicationLine.model_validate(line)
    for bad in ("Wegovy", 1234567890, 27.5):  # drug name / numbers are not age_18 options
        line["final"]["claimed_value"] = bad
        with pytest.raises(ValidationError):
            AdjudicationLine.model_validate(line)
    line["final"]["claim_id"] = "claim.bmi_bracket"
    line["final"]["claimed_value"] = "yes"  # a bracket claim takes brackets only
    with pytest.raises(ValidationError):
        AdjudicationLine.model_validate(line)
    gold = _gold()
    gold["facts"].append(
        {
            "field": "pa_form_claims",
            "claim_id": "claim.bmi_bracket",
            "claimed_value": "<27",
            "doc_id": "D0-pa",
            "start": 1,
            "end": 9,
            "quote": "synthetic",
            "certainty": "present",
            "subject": "patient",
            "temporality": "current",
            "event_date": None,
            "relative_to_glp1_initiation": "unknown",
            "origin": "spec",
            "review": "human_verified",
            "guideline_clause": "K-04",
        }
    )
    Gold.model_validate(gold)
    gold["facts"][-1]["claimed_value"] = "jane doe"
    with pytest.raises(ValidationError):
        Gold.model_validate(gold)


def test_adjudication_values_are_controlled() -> None:
    for key, value in [
        ("kind", "a copied sentence"),
        ("claimed_value", {"nested": "prose"}),
        ("norm_value", "forty-six"),
        ("drug_canonical", "Weight Watchers program"),
        ("drug_canonical", "janedoe"),
        ("claimed_value", "JaneDoe"),
        ("claim_id", "claim.jane_doe"),
        ("target_doc_id", "jane doe"),
        ("event_date", "last spring"),
    ]:
        line = _lines()[0]
        line["final"][key] = value
        with pytest.raises(ValidationError) as exc:
            AdjudicationLine.model_validate(line)
        rendered = "\n".join(format_errors(exc.value))
        assert key in rendered and "copied" not in rendered and "prose" not in rendered
        assert "jane" not in rendered.lower()


@pytest.mark.parametrize("key", ["this key is itself a copied sentence", "janedoe", "sentence_id"])
def test_every_unexpected_key_is_masked_in_errors(key: str) -> None:
    data = _blind()
    data["inventory"][0][key] = 1
    with pytest.raises(ValidationError) as exc:
        BlindDraft.model_validate(data)
    rendered = "\n".join(format_errors(exc.value))
    assert "<unexpected key>" in rendered and key not in rendered


def test_event_date_precisions_accepted() -> None:
    for value in ("2025", "2025-03", "2025-03-15", None):
        gold = _gold()
        gold["facts"][0]["event_date"] = value
        Gold.model_validate(gold)
