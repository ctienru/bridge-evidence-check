"""`bridge_check.scoring` (planning section 3.1, contract §8): the four matching tests the
contract names, case scores on the synthetic smoke run, failed runs, trap verdicts, the
coverage matrix, gold origin, sections, determinism, and the public-report gate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import FIXTURES, ROOT

from bridge_check import cli
from bridge_check.casemeta import CaseMeta, fixture_traps, load_case_meta, section_of
from bridge_check.cli import main as bridge_main
from bridge_check.compare import ERROR_CLASSES
from bridge_check.compute import DrugIndex
from bridge_check.enums import CONDITION_IDS
from bridge_check.eval_match import is_match
from bridge_check.export import ExportError, export_public_report
from bridge_check.gold_schema import Gold
from bridge_check.rules_schema import load_drugs, load_rules
from bridge_check.scoring import (
    RUN_FAILED,
    TEST_TYPES,
    CaseScore,
    coverage_matrix,
    human_workload,
    score_split,
    score_stored_run,
    trap_results,
)
from bridge_check.store import open_store

SMOKE = FIXTURES / "case-smoke"
GOLD = FIXTURES / "compare_gold" / "case-smoke-gold.json"
RULES = load_rules(ROOT / "rules" / "bridge-v1.yaml")
DRUGS = DrugIndex(load_drugs(ROOT / "rules" / "drugs-v2.yaml"))
_AXES = {"certainty": "present", "subject": "patient", "temporality": "current"}


# --- the four matching tests of contract §8 --------------------------------------------------


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


# --- the smoke run ----------------------------------------------------------------------------


def _meta(**over: Any) -> CaseMeta:
    base: dict[str, Any] = {
        "variant_id": "case-smoke",
        "case_id": "case-smoke",
        "source": "synthetic",
        "doc_origins": {"D1-referral": "authored"},
        "traps": ("T-one", "T-two"),
        "tests": ("age_18", "bmi_path_a", "claim.drug"),
        "invalid_ids": 0,
        "section": "authored",
    }
    base.update(over)
    return CaseMeta(**base)


@pytest.fixture
def smoke_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("BRIDGE_FAKE_CLIENT", "1")
    db = tmp_path / "bridge.db"
    assert bridge_main(["check", str(SMOKE), "--db", str(db)]) == 0
    return db


def _gold() -> tuple[Gold, str]:
    raw = GOLD.read_bytes()
    return Gold.model_validate_json(raw), "0" * 64


def _score(db: Path, meta: CaseMeta | None = None) -> tuple[CaseScore, int, Path]:
    store = open_store(db)
    try:
        run_id = store.latest_completed_run("case-smoke")
        assert run_id is not None
        gold, sha = _gold()
        score = score_stored_run(
            store,
            run_id,
            gold=gold,
            gold_sha256=sha,
            meta=meta or _meta(),
            rules=RULES,
            drugs=DRUGS,
        )
    finally:
        store.close()
    return score, run_id, db


def test_smoke_case_counts(smoke_db: Path) -> None:
    score, _, _ = _score(smoke_db)
    assert set(score.conditions) == set(CONDITION_IDS)
    assert (score.conditions_correct.n, score.conditions_correct.of) == (15, 20)
    assert score.claims_correct.of == 2
    # age_18: gold review, live supported -> the one false support, with its denominators
    fs = score.false_supports
    assert fs.count == 1 and score.conditions["age_18"].false_support
    assert fs.gold_non_supported == sum(
        r.gold_status != "supported" for r in score.conditions.values()
    )
    assert fs.system_supported == sum(r.status == "supported" for r in score.conditions.values())
    automatable = [
        r
        for r in score.conditions.values()
        if r.kind in ("condition", "path", "exclusion")
        and r.gold_status in ("supported", "not_supported")
    ]
    assert fs.correctly_automated.of == len(automatable)
    assert fs.correctly_automated.n == sum(r.correct for r in automatable)
    # exclusion.osa: gold review, live insufficient -> missed exclusion evidence
    assert (score.missed_exclusions.n, score.missed_exclusions.of) == (1, 1)
    assert score.exclusion_evidence_found == 0
    assert score.conditions["exclusion.osa"].missed_exclusion
    assert score.first_errors["verify_excluded"] >= 1 and score.first_errors[RUN_FAILED] == 0
    assert set(score.first_errors) == set(ERROR_CLASSES) | {RUN_FAILED}
    assert score.conditions["bmi_path_a"].policy_source
    assert score.run_status == "completed" and score.failed_stage is None
    assert score.extraction_source == "api"
    assert score.cost_usd is not None


def test_human_workload_matches_bridge_check(smoke_db: Path) -> None:
    score, run_id, db = _score(smoke_db)
    store = open_store(db)
    try:
        decisions = cli._decision_rows(store, run_id)
    finally:
        store.close()
    assert (
        score.human_workload
        == cli._workload(decisions)
        == human_workload(score.conditions.values())
    )
    assert score.needs_human


def test_citation_and_position_counts(smoke_db: Path) -> None:
    score, _, _ = _score(smoke_db)
    c, p = score.citations, score.positions
    assert c.facts_correct.of == c.gold_evidence_recalled.of == score.facts.gold_facts == 6
    assert c.facts_correct.n == score.facts.matched
    assert c.gold_evidence_recalled.n >= c.facts_correct.n  # a located span counts, any value
    assert c.quotes_located.of == p.verbatim + p.normalized + p.candidate + p.not_found
    assert c.quotes_located.n == p.verbatim + p.normalized
    assert score.facts.wrong_value_timing_only <= score.facts.wrong_value
    assert all(v > 0 for v in score.exclusion_reasons.values())
    assert "claim_document" in score.exclusion_reasons


def test_gold_origin_and_clause_counts(smoke_db: Path) -> None:
    score, _, _ = _score(smoke_db)
    gold, _ = _gold()
    assert sum(score.gold_origin.values()) == len(gold.facts)
    assert score.gold_with_clause.of == len(gold.facts)
    assert score.gold_with_clause.n == sum(f.guideline_clause is not None for f in gold.facts)


def test_trap_fails_with_the_most_upstream_error_once(smoke_db: Path) -> None:
    # age_18 -> verify_excluded, bmi_path_a -> compute_timepoint, claim.drug correct
    score, _, _ = _score(smoke_db)
    assert [t.trap_id for t in score.traps] == ["T-one", "T-two"]
    for t in score.traps:
        assert not t.passed
        assert (t.first_error, t.stage) == ("verify_excluded", "verify")
        assert t.failing_rows == ["age_18", "bmi_path_a"]
    passing, _, _ = _score(smoke_db, _meta(tests=("claim.drug",)))
    assert all(t.passed and t.first_error is None for t in passing.traps)
    none, _, _ = _score(smoke_db, _meta(traps=()))
    assert none.traps == []


def test_failed_run_counts_every_row_wrong(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRIDGE_FAKE_CLIENT", "no_tool_call")
    db = tmp_path / "bridge.db"
    assert bridge_main(["check", str(SMOKE), "--db", str(db)]) == 3
    store = open_store(db)
    try:
        run_id = store.history("case-smoke")[0]["id"]
        gold, sha = _gold()
        score = score_stored_run(
            store, run_id, gold=gold, gold_sha256=sha, meta=_meta(), rules=RULES, drugs=DRUGS
        )
    finally:
        store.close()
    assert score.run_status == "failed" and score.failed_stage == "parse"
    assert (score.conditions_correct.n, score.conditions_correct.of) == (0, 20)
    assert (score.claims_correct.n, score.claims_correct.of) == (0, 2)
    assert all(r.first_error == RUN_FAILED and r.status is None for r in score.conditions.values())
    assert score.first_errors[RUN_FAILED] == 22
    assert score.false_supports.count == 0 and score.false_supports.correctly_automated.n == 0
    assert (score.missed_exclusions.n, score.missed_exclusions.of) == (1, 1)
    assert score.human_workload is None and score.needs_human
    assert score.facts.missed == score.facts.gold_facts == 6 and score.facts.absent_correct == 0
    assert [(t.passed, t.first_error, t.stage) for t in score.traps] == [
        (False, RUN_FAILED, "parse"),
        (False, RUN_FAILED, "parse"),
    ]


def test_trap_results_do_not_double_count_downstream_rows() -> None:
    from bridge_check.scoring import RowScore

    def row(cid: str, correct: bool, first: str | None) -> RowScore:
        return RowScore(
            id=cid,
            kind="path" if cid == "bmi_path_b" else "sub",
            gold_status="supported",
            gold_flags=[],
            status="supported" if correct else "insufficient",
            flags=[],
            correct=correct,
            first_error=first,
            false_support=False,
            missed_exclusion=False,
            policy_source=None,
        )

    rows = {
        "bmi_path_b.bmi": row("bmi_path_b.bmi", False, "extraction_missed"),
        "bmi_path_b": row("bmi_path_b", False, "rules"),
        "bmi_path_b.htn": row("bmi_path_b.htn", True, None),
    }
    meta = _meta(traps=("T-x",), tests=("bmi_path_b.bmi", "bmi_path_b", "bmi_path_b.htn"))
    [result] = trap_results(meta, rows, "completed", None)
    assert (result.passed, result.first_error, result.stage) == (
        False,
        "extraction_missed",
        "extract",
    )
    assert result.failing_rows == ["bmi_path_b.bmi", "bmi_path_b"]


# --- split level ------------------------------------------------------------------------------


def test_split_pools_counts_and_keeps_sections_apart(smoke_db: Path) -> None:
    score, _, _ = _score(smoke_db)
    other = score.model_copy(update={"variant_id": "case-smoke-b", "section": "mtsamples"})
    split = score_split(
        [score, other],
        manifest_sha256="0" * 64,
        rules=RULES,
        metas=[_meta(), _meta(variant_id="case-smoke-b", section="mtsamples")],
        fixture_traps={"htn-two-drugs": ["T-one"]},
    )
    assert split.split == "dev"
    assert split.micro.variants == 2 and split.micro.case_families == 1
    assert split.micro.conditions_correct.n == 30 and split.micro.conditions_correct.of == 40
    assert split.micro.false_supports.count == 2
    assert split.micro.packets_needing_human.n == 2
    assert set(split.sections) == {"mtsamples", "case_report", "authored", "dirty"}
    assert split.sections["authored"].variants == ["case-smoke"]
    assert split.sections["mtsamples"].variants == ["case-smoke-b"]
    assert split.sections["dirty"].variants == [] and split.sections["dirty"].micro.variants == 0
    assert split.sections["authored"].micro.false_supports.count == 1
    macro = {m.id: m for m in split.macro["conditions"]}
    assert macro["age_18"].correct.of == 2 and macro["age_18"].false_supports == 2
    assert macro["age_18"].by_variant == {"case-smoke": "supported", "case-smoke-b": "supported"}
    traps = {t.trap_id: t for t in split.traps}
    assert traps["T-one"].opportunities == 2 and traps["T-one"].passed == 0
    assert split.coverage.cells["T-one"]["rules_fixture"] == ["htn-two-drugs"]
    assert split.condition_sources["age_18"] and split.policy_sources
    assert split.out_of_scope == ["verifier_ablation", "rules_only_unit_tests"]


def test_coverage_matrix_lists_empty_cells() -> None:
    metas = [
        _meta(traps=("T-a", "T-b")),
        _meta(variant_id="case-15-L5", section="dirty", traps=("T-a",)),
    ]
    matrix = coverage_matrix(metas, {"osa-mild": ["T-c"], "part-d-2025": ["T-a"]})
    assert matrix.traps == ["T-a", "T-b", "T-c"] and matrix.test_types == list(TEST_TYPES)
    assert matrix.cells["T-a"]["integrated_case"] == ["case-smoke"]
    assert matrix.cells["T-a"]["ladder_level"] == ["case-15-L5"]
    assert matrix.cells["T-a"]["rules_fixture"] == ["part-d-2025"]
    assert matrix.cells["T-c"]["integrated_case"] == []
    assert matrix.filled.of == 15 and matrix.filled.n == 5
    assert {"trap_id": "T-c", "test_type": "integrated_case"} in matrix.not_covered
    assert {"trap_id": "T-a", "test_type": "integrated_case"} not in matrix.not_covered
    assert len(matrix.not_covered) == 10


def test_committed_fixture_metadata_and_case_yaml_reduce_to_ids() -> None:
    traps = fixture_traps(FIXTURES / "rules")
    assert set(traps) == {p.name for p in (FIXTURES / "rules").iterdir() if p.is_dir()}
    assert "T-combination-pill" in traps["htn-combination-pill"]
    for vid in ("case-07", "case-17"):
        meta = load_case_meta(ROOT / "cases" / vid, vid)
        assert meta.traps and meta.tests and meta.invalid_ids == 0
        assert meta.section in ("authored", "case_report")
    meta = load_case_meta(ROOT / "cases" / "case-01", "case-01")
    assert meta.traps == () and meta.section == "mtsamples"


def test_case_meta_drops_free_text(tmp_path: Path) -> None:
    (tmp_path / "case.yaml").write_text(
        "case_id: case-x\nsource: 'not an id!'\ndocuments:\n"
        "  - {doc_id: D1, doc_origin: authored}\n"
        "  - {doc_id: 'D 2', doc_origin: authored}\ntraps: [T-ok, 'free text here', T-ok]\n"
        "tests: [age_18, not_a_condition]\n",
        encoding="utf-8",
    )
    meta = load_case_meta(tmp_path, "case-x")
    assert meta.source is None and meta.doc_origins == {"D1": "authored"}
    assert meta.traps == ("T-ok",) and meta.tests == ("age_18",)
    assert meta.invalid_ids == 4
    assert section_of({"a": "authored", "b": "case_report"}) == "case_report"
    assert section_of({"a": "mtsamples", "b": "case_report"}) == "mtsamples"
    assert section_of({}, dirty=True) == "dirty"


def test_scores_are_deterministic(smoke_db: Path) -> None:
    a, _, _ = _score(smoke_db)
    b, _, _ = _score(smoke_db)
    assert a.model_dump() == b.model_dump()
    assert json.dumps(a.model_dump(), sort_keys=True) == json.dumps(b.model_dump(), sort_keys=True)


# --- the public gate ----------------------------------------------------------------------------


def test_export_public_report_refuses_free_text() -> None:
    ok = {
        "score": {"ids": ["case-01", "T-x", "claim.bmi_path_b.htn"], "ref": "D2-x[12:40] 0ab12cd3"}
    }
    assert export_public_report(ok) == ok
    assert export_public_report({"b": 1, "a": None, "c": [True, 1.5]}) == {
        "a": None,
        "b": 1,
        "c": [True, 1.5],
    }
    for bad in (
        {"note": "the patient denies diabetes"},
        {"x": ["ok", "two words"]},
        {"a key with spaces": 1},
        {"x": {"y": 'quote: "text"'}},
    ):
        with pytest.raises(ExportError) as exc:
            export_public_report(bad)
        assert "patient" not in str(exc.value) and "quote" not in str(exc.value)
    with pytest.raises(ExportError):
        export_public_report({"x": object()})


@pytest.mark.parametrize(
    ("level", "section", "column"),
    [("L0", "case_report", "integrated_case"), ("L1", "dirty", "ladder_level")],
)
def test_ladder_level_l0_is_grouped_by_document_origin(
    tmp_path: Path, level: str, section: str, column: str
) -> None:
    """Ladder membership is recorded on its own (`ladder_level`); only a dirtied level
    (L1 and up) is reported in the `dirty` section and fills the `ladder_level` coverage
    column. L0, the clean base, is grouped by its documents' origin and counts as an
    integrated case."""
    (tmp_path / "case.yaml").write_text(
        "case_id: case-x\nsplit: holdout\nsource: mixed\ndocuments:\n"
        "  - {doc_id: D1-referral, doc_origin: authored}\n"
        "  - {doc_id: D2-case-report-x, doc_origin: case_report}\n"
        f"ladder: {{level: {level}, operations: []}}\ntraps: [T-x]\ntests: []\n",
        encoding="utf-8",
    )
    meta = load_case_meta(tmp_path, "case-x")
    assert meta.ladder_level == level
    assert meta.section == section
    matrix = coverage_matrix([meta], {})
    assert matrix.cells["T-x"][column] == ["case-x"]


def test_case_without_ladder_has_no_ladder_level(tmp_path: Path) -> None:
    (tmp_path / "case.yaml").write_text(
        "case_id: case-x\ndocuments:\n  - {doc_id: D2-x, doc_origin: case_report}\n",
        encoding="utf-8",
    )
    meta = load_case_meta(tmp_path, "case-x")
    assert meta.ladder_level is None and meta.section == "case_report"
