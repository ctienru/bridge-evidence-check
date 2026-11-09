from __future__ import annotations

from bridge_check.dataside.candidates import (
    JSON_INSTRUCTION,
    OUTPUT_KEYS,
    build_messages,
    extract_candidates,
    locate_candidate,
    sanitize,
)
from bridge_check.enums import ALLOWED_ENTRY_KEYS, FORBIDDEN_ENTRY_KEYS
from bridge_check.text import sha8

DOCS = {"D1": "Her BMI was 41.2 kg/m2. She denies any stroke. She denies any stroke."}
BASE = {
    "doc_id": "D1",
    "field": "anthropometrics",
    "kind": "bmi",
    "norm_value": 41.2,
    "norm_unit": "kg/m2",
    "certainty": "present",
    "subject": "patient",
    "temporality": "current",
    "event_date": None,
    "description": "free text the model added",
}


def test_located() -> None:
    line, dropped = locate_candidate(DOCS, {**BASE, "quote": "BMI was 41.2 kg/m2"})
    assert dropped == 1  # description
    assert (line["start"], line["end"]) == (4, 22)
    assert line["sha8"] == sha8("BMI was 41.2 kg/m2")
    assert line["location"] == "located"


def test_not_found_and_ambiguous_keep_the_candidate() -> None:
    nf, _ = locate_candidate(DOCS, {**BASE, "quote": "BMI was 41.3"})
    assert nf["location"] == "not_found" and nf["start"] is nf["end"] is nf["sha8"] is None
    amb, _ = locate_candidate(DOCS, {**BASE, "quote": "She denies any stroke."})
    assert amb["location"] == "ambiguous" and amb["start"] is None
    unknown_doc, _ = locate_candidate(DOCS, {**BASE, "doc_id": "D2", "quote": "BMI"})
    assert unknown_doc["location"] == "invalid" and unknown_doc["start"] is None


def test_output_keys_are_allow_listed_and_never_quote() -> None:
    line, _ = locate_candidate(DOCS, {**BASE, "quote": "BMI was 41.2 kg/m2", "raw_value": "41.2"})
    assert set(line) <= OUTPUT_KEYS
    assert set(line) - {"location"} <= ALLOWED_ENTRY_KEYS
    assert "dropped_keys" not in line
    assert not set(line) & set(FORBIDDEN_ENTRY_KEYS)
    assert "quote" not in line and "description" not in line
    assert sanitize({"quote": "x", "field": "labs"}) == ({"field": "labs"}, 1)


def test_free_text_under_value_keys_is_dropped_and_counted() -> None:
    cand = {
        **BASE,
        "quote": "BMI was 41.2 kg/m2",
        "kind": "a sentence copied from the note",
        "claimed_value": {"nested": "prose copied from the form"},
        "payer": "the patient's insurance card says Part D",
        "norm_unit": "kg/m2",
    }
    line, dropped = locate_candidate(DOCS, cand)
    assert "kind" not in line and "claimed_value" not in line and "payer" not in line
    assert line["norm_unit"] == "kg/m2"
    assert line["location"] == "invalid"  # anthropometrics without a valid kind gets no offsets
    assert dropped == 4  # description, kind, claimed_value, payer
    assert "copied" not in str(line) and "insurance" not in str(line)


def test_unknown_doc_id_is_nulled() -> None:
    line, _ = locate_candidate(DOCS, {**BASE, "doc_id": "../../etc", "quote": "BMI"})
    assert line["doc_id"] is None and line["location"] == "invalid"
    assert "etc" not in str(line)


def test_candidate_without_required_fields_gets_no_offsets() -> None:
    bare, _ = locate_candidate(DOCS, {"doc_id": "D1", "quote": "BMI was 41.2 kg/m2"})
    assert bare["location"] == "invalid" and bare["start"] is None and bare["end"] is None
    no_axis, _ = locate_candidate(
        DOCS, {k: v for k, v in BASE.items() if k != "subject"} | {"quote": "BMI was 41.2 kg/m2"}
    )
    assert no_axis["location"] == "invalid"
    bad_field, _ = locate_candidate(
        DOCS, {**BASE, "field": "vitals", "quote": "BMI was 41.2 kg/m2"}
    )
    assert bad_field["location"] == "invalid"


def test_field_specific_required_keys() -> None:
    dx = {**BASE, "field": "diagnoses", "quote": "She denies any stroke."}
    dx.pop("kind")
    dx.pop("norm_value")
    dx.pop("norm_unit")
    no_concept, _ = locate_candidate(DOCS, dx)
    assert no_concept["location"] == "invalid"
    with_concept, _ = locate_candidate(DOCS, {**dx, "concept": "stroke"})
    assert with_concept["location"] == "ambiguous"  # the sentence appears twice
    bp = {**BASE, "field": "bp_readings", "quote": "BMI was 41.2 kg/m2", "sbp": 140}
    assert locate_candidate(DOCS, bp)[0]["location"] == "invalid"  # dbp missing
    assert locate_candidate(DOCS, {**bp, "dbp": 90})[0]["location"] == "located"


def test_identity_candidate_is_located_without_identity_match() -> None:
    ident = {
        "doc_id": "D1",
        "field": "patient_identity",
        "quote": "BMI was 41.2 kg/m2",
        "certainty": "present",
        "subject": "patient",
        "temporality": "current",
        "name": "Jane Doe",
        "patient_id": "P-1",
    }
    line, dropped = locate_candidate(DOCS, ident)
    assert line["location"] == "located" and dropped == 2
    assert "name" not in line and "patient_id" not in line and "Jane" not in str(line)


def test_measurements_need_a_normalized_value_to_cover() -> None:
    bmi = {**BASE, "quote": "BMI was 41.2 kg/m2"}
    assert locate_candidate(DOCS, bmi)[0]["location"] == "located"
    no_value = {k: v for k, v in bmi.items() if k != "norm_value"}
    assert locate_candidate(DOCS, no_value)[0]["location"] == "invalid"
    bad_unit = {**bmi, "norm_unit": "stone"}
    assert locate_candidate(DOCS, bad_unit)[0]["location"] == "invalid"


def test_pa_form_values_pass_per_claim() -> None:
    pa_docs = {"D0": "Drug: Wegovy. BMI bracket: Less than 27."}
    base = {
        "doc_id": "D0",
        "field": "pa_form_claims",
        "certainty": "present",
        "subject": "patient",
        "temporality": "current",
    }
    drug, _ = locate_candidate(
        pa_docs,
        {**base, "quote": "Drug: Wegovy.", "claim_id": "claim.drug", "claimed_value": "Wegovy"},
    )
    assert drug["claimed_value"] == "Wegovy" and drug["location"] == "located"
    bracket, _ = locate_candidate(
        pa_docs,
        {**base, "quote": "Less than 27.", "claim_id": "claim.bmi_bracket", "claimed_value": "<27"},
    )
    assert bracket["claimed_value"] == "<27"
    wrong, dropped = locate_candidate(
        pa_docs,
        {**base, "quote": "Drug: Wegovy.", "claim_id": "claim.age_18", "claimed_value": "Wegovy"},
    )
    assert "claimed_value" not in wrong and dropped == 1
    numeric, dropped = locate_candidate(
        pa_docs,
        {**base, "quote": "Drug: Wegovy.", "claim_id": "claim.age_18", "claimed_value": 1234567890},
    )
    assert "claimed_value" not in numeric and dropped == 1  # a number is never a yes/no option


def test_names_cannot_hide_in_closed_value_keys() -> None:
    cand = {
        **BASE,
        "quote": "BMI was 41.2 kg/m2",
        "drug_canonical": "jane doe",
        "claimed_value": "JaneDoe",
        "claim_id": "claim.jane_doe",
        "target_doc_id": "jane-doe-note",
    }
    line, dropped = locate_candidate(DOCS, cand)
    assert "jane" not in str(line).lower() and "doe" not in str(line).lower()
    assert dropped == 5
    ok, _ = locate_candidate(
        DOCS,
        {
            **BASE,
            "quote": "BMI was 41.2 kg/m2",
            "drug_canonical": "semaglutide",
            "claimed_value": "35+",
            "claim_id": "claim.bmi_bracket",
            "target_doc_id": "D1",
        },
    )
    assert ok["drug_canonical"] == "semaglutide" and ok["claim_id"] == "claim.bmi_bracket"
    assert ok["claimed_value"] == "35+" and ok["target_doc_id"] == "D1"


def test_messages_always_ask_for_json() -> None:
    messages = build_messages({"D1": "text"}, {"D1": "clinical"}, "GUIDE", "a prompt with no hint")
    assert JSON_INSTRUCTION in messages[0]["content"] and "JSON" in messages[0]["content"]


def test_extract_candidates_accepts_list_or_wrapper() -> None:
    assert extract_candidates([{"a": 1}]) == [{"a": 1}]
    assert extract_candidates({"candidates": [{"a": 1}]}) == [{"a": 1}]
    for bad in ({"candidates": "x"}, [1, 2], "text"):
        try:
            extract_candidates(bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad!r}")
