from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from conftest import FIXTURES

from bridge_check.dataside.cues import Cues, load_cues
from bridge_check.dataside.drafting import (
    CheckResult,
    DraftSpec,
    build_messages,
    build_record,
    failed_fact_ids,
    format_table,
    load_spec,
    parse_response,
    run_checks,
    write_documents,
)

DRAFTING = FIXTURES / "drafting"


@pytest.fixture(scope="module")
def spec() -> DraftSpec:
    return load_spec(DRAFTING / "spec.yaml")


@pytest.fixture(scope="module")
def cues() -> Cues:
    return load_cues()


def _results(spec: DraftSpec, cues: Cues, name: str) -> list[CheckResult]:
    raw = json.loads((DRAFTING / f"response_{name}.json").read_text(encoding="utf-8"))
    return run_checks(spec, parse_response(raw), cues)


def test_passing_response(spec: DraftSpec, cues: Cues) -> None:
    results = _results(spec, cues, "ok")
    assert results and all(r.passed for r in results)
    assert {r.check for r in results} == {
        "quote_unique",
        "value_in_quote",
        "cue_in_sentence",
        "must_use_present",
    }
    assert failed_fact_ids(results) == []


@pytest.mark.parametrize(
    ("name", "fact_id", "check"),
    [
        ("quote_not_found", "F2", "quote_not_found"),
        ("quote_ambiguous", "F2", "quote_ambiguous"),
        ("value_in_quote", "F1", "value_in_quote"),
        ("cue_in_sentence", "F3", "cue_in_sentence"),
        ("must_use_present", "F1", "must_use_present"),
    ],
)
def test_each_check_has_a_failing_fixture(
    spec: DraftSpec, cues: Cues, name: str, fact_id: str, check: str
) -> None:
    results = _results(spec, cues, name)
    failed = [(r.fact_id, r.check) for r in results if not r.passed]
    assert failed == [(fact_id, check)]
    assert failed_fact_ids(results) == [fact_id]


def test_missing_document_is_reported(spec: DraftSpec, cues: Cues) -> None:
    results = run_checks(spec, parse_response({"documents": {}, "quote_map": {}}), cues)
    assert ("<document D1-referral>", "document_missing") in {(r.fact_id, r.check) for r in results}
    assert all(r.check == "quote_not_found" for r in results if r.fact_id.startswith("F"))


def test_table_and_record_contain_no_document_text(spec: DraftSpec, cues: Cues) -> None:
    raw = json.loads((DRAFTING / "response_quote_not_found.json").read_text(encoding="utf-8"))
    results = run_checks(spec, parse_response(raw), cues)
    table = format_table(results)
    assert "FAIL" in table and "F2" in table
    assert "stroke" not in table and "referring" not in table
    record = build_record("model-x", parse_response(raw), results, today=date(2026, 11, 8))
    assert record["drafted_by"] == "model-x" and record["drafted_at"] == "2026-11-08"
    assert set(record["quote_map"]) == {"F1", "F2", "F3"}
    assert {c["check"] for c in record["checks"]} >= {"quote_not_found"}


def test_messages_carry_spec_and_failed_ids(spec: DraftSpec) -> None:
    messages = build_messages(spec, "SYSTEM PROMPT", ["F2"])
    assert messages[0]["role"] == "system"
    assert messages[0]["content"].startswith("SYSTEM PROMPT")
    assert "JSON" in messages[0]["content"]  # JSON mode needs the word even if the prompt lacks it
    user = json.loads(messages[1]["content"])
    assert user["case_id"] == "case-synthetic"
    assert user["revise"]["failed_fact_ids"] == ["F2"]
    assert "revise" not in json.loads(build_messages(spec, "p")[1]["content"])


def test_array_shaped_response_is_normalised(spec: DraftSpec) -> None:
    raw = json.loads((DRAFTING / "response_ok.json").read_text(encoding="utf-8"))
    arrays = {
        "documents": [{"doc_id": k, "text": v} for k, v in raw["documents"].items()],
        "quote_map": [{"fact_id": k, "quote": v} for k, v in raw["quote_map"].items()],
    }
    assert parse_response(arrays, spec) == parse_response(raw, spec)
    arrays["quote_map"].append({"fact_id": "F1", "quote": "again"})
    with pytest.raises(ValueError, match="duplicate"):
        parse_response(arrays, spec)


def test_response_must_match_spec_sets(spec: DraftSpec) -> None:
    raw = json.loads((DRAFTING / "response_ok.json").read_text(encoding="utf-8"))
    parse_response(raw, spec)  # exact match passes
    extra = json.loads(json.dumps(raw))
    extra["documents"]["../evil"] = "x"
    with pytest.raises(ValueError, match="documents do not match"):
        parse_response(extra, spec)
    missing = json.loads(json.dumps(raw))
    del missing["quote_map"]["F2"]
    with pytest.raises(ValueError, match="quote_map does not match"):
        parse_response(missing, spec)


def test_write_documents_refuses_unsafe_ids_before_writing(tmp_path: Path) -> None:
    response = parse_response({"documents": {"D1-ok": "fine", "../escape": "bad"}, "quote_map": {}})
    out = tmp_path / "out"
    with pytest.raises(ValueError):
        write_documents(response, out)
    assert not out.exists() and not (tmp_path / "escape.txt").exists()


def test_quote_spanning_two_sentences_fails_cue_check(spec: DraftSpec, cues: Cues) -> None:
    doc = (
        "I am referring this 54 y.o. patient. She denies any heart disease. "
        "A stroke was noted in the family. On 2025-03-15 her BMI was 41.2 kg/m2. "
        "Her mother has diabetes."
    )
    # F2 (negated stroke): the quote spans two sentences and would borrow `denies`
    response = parse_response(
        {
            "documents": {"D1-referral": doc},
            "quote_map": {
                "F1": "On 2025-03-15 her BMI was 41.2 kg/m2.",
                "F2": "She denies any heart disease. A stroke was noted in the family.",
                "F3": "Her mother has diabetes.",
            },
        }
    )
    results = run_checks(spec, response, cues)
    failed = [(r.fact_id, r.check) for r in results if not r.passed]
    assert failed == [("F2", "cue_in_sentence")]


def test_spec_yaml_error_names_only_the_type(tmp_path: Path) -> None:
    bad = tmp_path / "spec.yaml"
    bad.write_text("facts: [secret patient line\n  - :: bad", encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        load_spec(bad)
    assert "invalid YAML" in str(excinfo.value) and "secret" not in str(excinfo.value)


def test_write_documents_is_byte_exact(tmp_path: Path) -> None:
    response = parse_response({"documents": {"D1-referral": "a\r\nb\n"}, "quote_map": {}})
    (path,) = write_documents(response, tmp_path / "out")
    assert path.name == "D1-referral.txt"
    assert path.read_bytes() == b"a\r\nb\n"


def test_spec_rejects_unknown_doc_or_field() -> None:
    base = {
        "case_id": "c",
        "documents": [{"doc_id": "D1", "role": "referral", "instructions": "x"}],
        "facts": [
            {
                "fact_id": "F1",
                "doc_id": "D9",
                "field": "labs",
                "value": "5.9",
                "certainty": "present",
                "subject": "patient",
                "temporality": "current",
            }
        ],
    }
    with pytest.raises(ValueError):
        DraftSpec.model_validate(base)
    base["facts"][0]["doc_id"] = "D1"  # type: ignore[index]
    base["facts"][0]["field"] = "vitals"  # type: ignore[index]
    with pytest.raises(ValueError):
        DraftSpec.model_validate(base)
