"""Comparison against gold (`bridge_check.compare`, `scripts/compare_gold.py`): fact
assignment, expected-absent checks, the first-upstream-error order, determinism, and no
quote text in the outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import FIXTURES, ROOT, load_script

from bridge_check.cli import main as bridge_main
from bridge_check.compare import (
    ERROR_CLASSES,
    Assignment,
    FactOutcome,
    align_list_ids,
    assign,
    classify_condition,
    condition_dependencies,
    mismatched_keys,
    timing_only,
)
from bridge_check.enums import CONDITION_IDS
from bridge_check.gold_schema import Gold
from bridge_check.rules_schema import COMPUTE_NAMES, load_rules
from bridge_check.store import SCORING_ATTRIBUTE_KEYS, open_store

SMOKE = FIXTURES / "case-smoke"
GOLD = FIXTURES / "compare_gold" / "case-smoke-gold.json"
QUESTIONS = FIXTURES / "compare_gold" / "gold-questions.json"
RULES = load_rules(ROOT / "rules" / "bridge-v1.yaml")


def _bp(eid: int, sbp: int, dbp: int, reasons: list[str] | None = None) -> dict[str, Any]:
    return {
        "evidence_id": eid,
        "field": "bp_readings",
        "doc_id": "D2",
        "sbp": sbp,
        "dbp": dbp,
        "certainty": "present",
        "subject": "patient",
        "temporality": "current",
        "relative_to_glp1_initiation": "at",
        "event_date": None,
        "exclusion_reasons": reasons or [],
    }


def _gold_bp(sbp: int, dbp: int) -> dict[str, Any]:
    g = _bp(0, sbp, dbp)
    del g["evidence_id"], g["exclusion_reasons"]
    return g


# --- assignment -------------------------------------------------------------------------------


def test_included_match_is_preferred_over_excluded() -> None:
    a = assign([_gold_bp(140, 90)], [_bp(1, 140, 90, ["wrong_patient"]), _bp(2, 140, 90)])
    assert [(f.outcome, f.evidence_id) for f in a.facts] == [("matched", 2)]
    assert a.excluded_unmatched == [1] and a.false_positives == []


def test_only_excluded_match_is_matched_but_excluded() -> None:
    a = assign([_gold_bp(140, 90)], [_bp(1, 140, 90, ["assertion_mismatch"])])
    assert [(f.outcome, f.evidence_id) for f in a.facts] == [("matched_but_excluded", 1)]


def test_assignment_is_one_to_one() -> None:
    a = assign([_gold_bp(140, 90), _gold_bp(140, 90)], [_bp(1, 140, 90)])
    assert [f.outcome for f in a.facts] == ["matched", "missed"]


def test_wrong_value_names_only_the_differing_keys() -> None:
    a = assign([_gold_bp(140, 90)], [_bp(1, 150, 95), _bp(2, 140, 91)])
    (f,) = a.facts
    assert (f.outcome, f.evidence_id, f.mismatched) == ("wrong_value", 2, ["dbp"])
    assert a.false_positives == [1]


def test_missed_when_no_row_shares_the_bucket() -> None:
    a = assign([_gold_bp(140, 90)], [])
    assert [f.outcome for f in a.facts] == ["missed"]


def test_timing_only_needs_the_extractors_own_values_right() -> None:
    g = {"relative_to_glp1_initiation": "at"}
    assert timing_only(g, {"relative_llm": "at"}, ["relative_to_glp1_initiation"])
    assert not timing_only(g, {"relative_llm": "before"}, ["relative_to_glp1_initiation"])
    assert timing_only(g, {"event_date_source": "none"}, ["event_date"])
    assert not timing_only(g, {"event_date_source": "llm"}, ["event_date"])
    assert not timing_only(g, {"relative_llm": "at"}, ["relative_to_glp1_initiation", "sbp"])


def test_not_stated_values_and_list_labels_do_not_count_as_mismatches() -> None:
    gold: list[dict[str, Any]] = [
        {"field": "medication_lists", "doc_id": "D2", "complete": True, "list_id": "G1"},
        {"field": "medications", "doc_id": "D2", "list_id": "G1"},
    ]
    system: list[dict[str, Any]] = [
        {"evidence_id": 7, "field": "medication_lists", "doc_id": "D2", "complete": True},
        {"evidence_id": 8, "field": "medication_lists", "doc_id": "D2", "complete": False},
    ]
    system[0]["list_id"], system[1]["list_id"] = "S9", "S1"
    aligned = align_list_ids(gold, system)
    assert aligned[1]["list_id"] == "S9"
    lifestyle_gold: dict[str, Any] = {
        "field": "lifestyle",
        "kind": "activity",
        "doc_id": "D1",
        "attendance": None,
    }
    for k in ("certainty", "subject", "temporality"):
        lifestyle_gold[k] = "x"
    sys_row = {**lifestyle_gold, "attendance": None, "end_kind": None, "program_type": None}
    assert mismatched_keys(lifestyle_gold, sys_row) == ["unknown"]  # nothing differs


# --- dependencies and classification ------------------------------------------------------------


def test_every_requires_name_and_condition_has_dependencies() -> None:
    deps = condition_dependencies(RULES)
    assert set(deps) == set(CONDITION_IDS)
    assert all(deps[cid] for cid in CONDITION_IDS)
    used = {name for c in RULES.conditions for name in c.requires}
    assert used <= set(COMPUTE_NAMES)


def _classify(facts: list[FactOutcome], **kw: Any) -> str:
    gold = [{"field": "bp_readings"}, {"field": "bp_readings"}]
    args: dict[str, Any] = {
        "variant_id": "v",
        "condition": "bmi_path_b.htn",
        "selectors": (("bp_readings", None),),
        "decision": None,
        "gold_facts": gold,
        "system_rows": {},
        "assignment": Assignment(facts, [], []),
        "absent": [],
        "questions": frozenset(),
    }
    args.update(kw)
    return classify_condition(**args)


def test_classification_order() -> None:
    missed = FactOutcome(0, "missed")
    wrong = FactOutcome(1, "wrong_value", 5, ["sbp"])
    timing = FactOutcome(1, "wrong_value", 5, ["event_date"], timing_only=True)
    excluded = FactOutcome(1, "matched_but_excluded", 5)
    matched = FactOutcome(1, "matched", 5)
    q = frozenset({("v", "bmi_path_b.htn")})
    assert _classify([missed], questions=q) == "gold_question"
    assert _classify([missed, wrong]) == "extraction_missed"
    assert _classify([wrong, excluded]) == "extraction_wrong_value"
    assert _classify([excluded, timing]) == "verify_excluded"
    assert _classify([timing]) == "compute_timepoint"
    decision = {"excluded_evidence": [{"evidence_id": 5, "reason": "after_initiation"}]}
    rows = {5: {"field": "bp_readings", "relative_computed": None}}
    assert _classify([matched], decision=decision, system_rows=rows) == "compute_timepoint"
    assert _classify([matched], system_rows=rows) == "rules"
    spurious = Assignment([matched], [9], [])
    rows9 = {**rows, 9: {"field": "bp_readings"}}
    assert _classify([], assignment=spurious, system_rows=rows9) == "extraction_extra"
    assert set(ERROR_CLASSES) == {
        "gold_question",
        "extraction_missed",
        "extraction_wrong_value",
        "verify_excluded",
        "compute_timepoint",
        "extraction_extra",
        "rules",
    }


# --- end to end on the synthetic smoke case -----------------------------------------------------


@pytest.fixture
def smoke_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("BRIDGE_FAKE_CLIENT", "1")
    db = tmp_path / "bridge.db"
    assert bridge_main(["check", str(SMOKE), "--db", str(db)]) == 0
    return db


def _run_compare(db: Path, out: Path, md: Path) -> int:
    script = load_script("compare_gold")
    code: int = script.main(
        [
            "--db",
            str(db),
            "--case",
            str(SMOKE),
            "--gold",
            str(GOLD),
            "--gold-questions",
            str(QUESTIONS),
            "--out",
            str(out),
            "--md",
            str(md),
        ]
    )
    return code


def test_compare_gold_end_to_end(smoke_db: Path, tmp_path: Path) -> None:
    out, md = tmp_path / "a.json", tmp_path / "a.md"
    assert _run_compare(smoke_db, out, md) == 0
    report = json.loads(out.read_text())
    assert set(report["conditions"]) == set(CONDITION_IDS)
    outcome = {(f["field"], f["selector"]): f for f in report["facts"]}
    assert outcome[("glp1_start", None)]["outcome"] == "matched"
    assert outcome[("diagnoses", "stroke")]["outcome"] == "matched"
    weight = outcome[("anthropometrics", "weight")]
    assert (weight["outcome"], weight["timing_only"]) == ("wrong_value", True)
    bp = outcome[("bp_readings", None)]
    assert (bp["outcome"], bp["mismatched_keys"], bp["timing_only"]) == (
        "wrong_value",
        ["dbp"],
        False,
    )
    identity = outcome[("patient_identity", None)]
    assert identity["outcome"] == "matched_but_excluded"
    assert identity["exclusion_reasons"] == ["claim_document"]
    assert {a["status"] for a in report["expected_absent"]} == {"not_found_correct"}
    first = {cid: r["first_error"] for cid, r in report["conditions"].items() if not r["correct"]}
    assert first == {
        "age_18": "verify_excluded",
        "bmi_path_a": "compute_timepoint",
        "bmi_path_b.htn": "extraction_wrong_value",
        "bmi_path_c.mi": "gold_question",
        "exclusion.osa": "rules",
    }
    assert report["claims"]["claim.bmi_bracket"]["first_error"] == "compute_timepoint"
    assert report["claims"]["claim.drug"]["correct"]
    totals = report["totals"]
    assert (totals["false_support"], totals["missed_exclusion"]) == (1, 1)  # age_18, osa
    assert totals["conditions_correct"] == 15 and totals["conditions_total"] == 20


def test_compare_gold_is_deterministic_and_carries_no_quote(smoke_db: Path, tmp_path: Path) -> None:
    first, second = tmp_path / "1.json", tmp_path / "2.json"
    md1, md2 = tmp_path / "1.md", tmp_path / "2.md"
    assert _run_compare(smoke_db, first, md1) == 0
    assert _run_compare(smoke_db, second, md2) == 0
    assert first.read_bytes() == second.read_bytes()
    assert md1.read_bytes() == md2.read_bytes()
    quotes = [f.quote for f in Gold.model_validate_json(GOLD.read_bytes()).facts if f.quote]
    for body, name in ((first.read_text(), "json"), (md1.read_text(), "markdown")):
        leaked = sum(q in body for q in quotes)
        assert leaked == 0, f"{leaked} gold quote(s) found in the {name} output"


def test_markdown_section_is_replaced_not_appended(smoke_db: Path, tmp_path: Path) -> None:
    out, md = tmp_path / "a.json", tmp_path / "a.md"
    assert _run_compare(smoke_db, out, md) == 0
    assert _run_compare(smoke_db, out, md) == 0
    assert md.read_text().count("## case-smoke ") == 1


def test_facts_for_run_returns_no_free_text(smoke_db: Path) -> None:
    store = open_store(smoke_db)
    try:
        run_id = store.latest_completed_run("case-smoke")
        assert run_id is not None
        rows = store.facts_for_run(run_id)
        ext = store.extraction_for_run(run_id)
    finally:
        store.close()
    assert ext is not None and ext["attempt_id"] is not None
    assert rows and all(set(r["attrs"]) <= set(SCORING_ATTRIBUTE_KEYS) for r in rows)
    assert all("quote" not in r for r in rows)
    meds = [r for r in rows if r["field"] == "medications"]
    assert meds and all("dose" not in r["attrs"] and "indication" not in r["attrs"] for r in meds)


def test_missing_database_is_an_error_and_creates_nothing(tmp_path: Path) -> None:
    script = load_script("compare_gold")
    db = tmp_path / "x.db"
    code: int = script.main(
        ["--db", str(db), "--case", str(SMOKE), "--gold", str(GOLD), "--out", str(tmp_path / "o")]
    )
    assert code == 1
    assert not db.exists() and not (tmp_path / "o").exists()
