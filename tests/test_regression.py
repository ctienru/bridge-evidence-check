"""The regression detector (contract §11): each of the four kinds, run failures, missing
cases, skipped variants, and the cases that are not regressions."""

from __future__ import annotations

from typing import Any

from conftest import ROOT

from bridge_check.baseline import regressions
from bridge_check.baseline_schema import Baseline
from bridge_check.rules_schema import load_rules
from bridge_check.scoring import (
    CaseFlagsScore,
    CaseScore,
    CitationCounts,
    Counts,
    FactCounts,
    FalseSupportCounts,
    PositionCounts,
    RowScore,
    SplitScore,
    score_split,
)

RULES = load_rules(ROOT / "rules" / "bridge-v1.yaml")
SHA = "0" * 64


def _before(
    status: str, gold: str, *, flags: list[str] | None = None, gold_flags: list[str] | None = None
) -> dict[str, Any]:
    flags, gold_flags = flags or [], gold_flags or []
    return {
        "status": status,
        "flags": flags,
        "gold_status": gold,
        "gold_flags": gold_flags,
        "correct": status == gold and sorted(flags) == sorted(gold_flags),
    }


def _baseline(
    conditions: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]] | None = None,
    *,
    case_flags_ok: bool = True,
    vid: str = "case-x",
) -> Baseline:
    claims = claims or {}
    case = {
        "input_hash": SHA,
        "gold_sha256": SHA,
        "replay": None,
        "conditions": conditions,
        "claims": claims,
        "case_flags": {
            "gold": [],
            "live": [] if case_flags_ok else ["mace_purpose"],
            "correct": case_flags_ok,
        },
        "conditions_correct": sum(r["correct"] for r in conditions.values()),
        "claims_correct": sum(r["correct"] for r in claims.values()),
        "false_support_count": sum(
            r["status"] == "supported" and r["gold_status"] != "supported"
            for r in conditions.values()
        ),
        "claims_false_support_count": sum(
            r["status"] == "supported" and r["gold_status"] != "supported" for r in claims.values()
        ),
        "missed_exclusion_count": sum(
            c.startswith("exclusion.")
            and r["gold_status"] == "review"
            and r["status"] in ("insufficient", "not_supported")
            for c, r in conditions.items()
        ),
    }
    return Baseline.model_validate(
        {
            "baseline_version": 1,
            "split": "dev",
            "manifest_sha256": SHA,
            "generated_from": {
                "code_sha": "x",
                "prompt_version": "p",
                "schema_version": "s",
                "rules_version": "r",
                "model_returned": "m",
            },
            "cases": {vid: case},
            "totals": {
                "cases": 1,
                "conditions_correct": case["conditions_correct"],
                "conditions_total": len(conditions),
                "claims_correct": case["claims_correct"],
                "claims_total": len(claims),
                "false_support_count": case["false_support_count"],
                "claims_false_support_count": case["claims_false_support_count"],
                "missed_exclusion_count": case["missed_exclusion_count"],
            },
        }
    )


def _row(
    cid: str,
    status: str | None,
    gold: str,
    *,
    flags: list[str] | None = None,
    gold_flags: list[str] | None = None,
) -> RowScore:
    flags, gold_flags = flags or [], gold_flags or []
    kind = (
        "exclusion"
        if cid.startswith("exclusion.")
        else ("claim" if cid.startswith("claim.") else "condition")
    )
    return RowScore(
        id=cid,
        kind=kind,
        gold_status=gold,  # type: ignore[arg-type]
        gold_flags=gold_flags,
        status=status,  # type: ignore[arg-type]
        flags=flags,
        correct=status == gold and sorted(flags) == sorted(gold_flags),
        first_error=None if status == gold else "rules",
        false_support=status == "supported" and gold != "supported",
        missed_exclusion=cid.startswith("exclusion.")
        and gold == "review"
        and status in ("insufficient", "not_supported"),
        policy_source=None,
    )


def _case(
    conditions: dict[str, RowScore],
    claims: dict[str, RowScore] | None = None,
    *,
    run_status: str = "completed",
    case_flags_ok: bool = True,
    vid: str = "case-x",
) -> CaseScore:
    claims = claims or {}
    zero = Counts(n=0, of=0)
    fs = FalseSupportCounts(
        count=0, gold_non_supported=0, system_supported=0, correctly_automated=zero
    )
    return CaseScore(
        variant_id=vid,
        case_id=vid,
        section="authored",
        gold_sha256=SHA,
        run_id=1,
        run_status=run_status,
        failed_stage=None if run_status == "completed" else "verify",
        extraction_source="replay",
        conditions=conditions,
        claims=claims,
        case_flags=CaseFlagsScore(
            gold=[], live=[] if case_flags_ok else ["mace_purpose"], correct=case_flags_ok
        ),
        conditions_correct=Counts(
            n=sum(r.correct for r in conditions.values()), of=len(conditions)
        ),
        claims_correct=Counts(n=sum(r.correct for r in claims.values()), of=len(claims)),
        false_supports=fs,
        claims_false_supports=fs,
        missed_exclusions=zero,
        exclusion_evidence_found=0,
        human_workload=0,
        needs_human=False,
        first_errors={},
        facts=FactCounts(
            gold_facts=0,
            matched=0,
            matched_but_excluded=0,
            wrong_value=0,
            wrong_value_timing_only=0,
            missed=0,
            false_positives=0,
            excluded_unmatched=0,
            absent_correct=0,
            absent_false_positive=0,
        ),
        citations=CitationCounts(
            quotes_located=zero, facts_correct=zero, gold_evidence_recalled=zero
        ),
        positions=PositionCounts(verbatim=0, normalized=0, candidate=0, not_found=0),
        exclusion_reasons={},
        traps=[],
        gold_origin={},
        gold_with_clause=zero,
        cost_usd=None,
    )


def _split(*cases: CaseScore) -> SplitScore:
    return score_split(list(cases), manifest_sha256=SHA, rules=RULES, metas=[], fixture_traps={})


def _kinds(baseline: Baseline, split: SplitScore, **kw: Any) -> list[tuple[str, str]]:
    return [(i.row, i.kind) for i in regressions(baseline, split, **kw)]


def test_new_false_support_is_a_regression() -> None:
    before = _baseline({"bmi_path_a": _before("insufficient", "review")})
    after = _split(_case({"bmi_path_a": _row("bmi_path_a", "supported", "review")}))
    assert _kinds(before, after) == [("bmi_path_a", "false_support")]
    [item] = regressions(before, after)
    assert (item.before_status, item.after_status, item.variant_id) == (
        "insufficient",
        "supported",
        "case-x",
    )


def test_correct_to_wrong_status_is_a_regression() -> None:
    before = _baseline({"age_18": _before("supported", "supported")})
    after = _split(_case({"age_18": _row("age_18", "insufficient", "supported")}))
    assert _kinds(before, after) == [("age_18", "status")]


def test_correct_to_wrong_flags_is_a_regression() -> None:
    before = _baseline(
        {
            "age_18": _before(
                "supported",
                "supported",
                flags=["inconsistent_values"],
                gold_flags=["inconsistent_values"],
            )
        }
    )
    after = _split(
        _case(
            {
                "age_18": _row(
                    "age_18", "supported", "supported", flags=[], gold_flags=["inconsistent_values"]
                )
            }
        )
    )
    assert _kinds(before, after) == [("age_18", "flags")]
    # case flags are flags too
    before = _baseline({"age_18": _before("supported", "supported")}, case_flags_ok=True)
    after = _split(_case({"age_18": _row("age_18", "supported", "supported")}, case_flags_ok=False))
    assert _kinds(before, after) == [("case_flags", "flags")]


def test_exclusion_dropping_from_review_is_a_regression_even_when_gold_differs() -> None:
    for after_status in ("insufficient", "not_supported"):
        before = _baseline(
            {"exclusion.osa": _before("review", "insufficient")}
        )  # was wrong already
        after = _split(
            _case({"exclusion.osa": _row("exclusion.osa", after_status, "insufficient")})
        )
        kinds = _kinds(before, after)
        assert ("exclusion.osa", "exclusion_downgrade") in kinds
        assert ("exclusion.osa", "status") not in kinds


def test_claims_count_too_but_without_flags() -> None:
    before = _baseline(
        {"age_18": _before("supported", "supported")},
        {"claim.drug": _before("insufficient", "supported")},
    )
    after = _split(
        _case(
            {"age_18": _row("age_18", "supported", "supported")},
            {"claim.drug": _row("claim.drug", "supported", "insufficient")},
        )
    )
    # claim: gold says insufficient in the new gold? no: gold is read from `after`; here the
    # system now says supported where gold does not -> false support
    assert _kinds(before, after) == [("claim.drug", "false_support")]


def test_failed_run_and_missing_case_are_regressions() -> None:
    before = _baseline({"age_18": _before("supported", "supported")})
    failed = _split(_case({"age_18": _row("age_18", None, "supported")}, run_status="failed"))
    assert _kinds(before, failed) == [("run", "run_failed"), ("age_18", "status")]
    assert _kinds(before, _split()) == [("run", "case_missing")]
    assert _kinds(before, _split(), skipped=["case-x"]) == []


def test_non_regressions() -> None:
    before = _baseline(
        {
            "age_18": _before("insufficient", "supported"),  # wrong before
            "bmi_path_a": _before("review", "supported"),  # wrong before
            "exclusion.osa": _before("review", "review"),
            "exclusion.t2dm": _before("supported", "review"),  # false support before
        }
    )
    after = _split(
        _case(
            {
                "age_18": _row("age_18", "review", "supported"),  # wrong -> still wrong
                "bmi_path_a": _row("bmi_path_a", "supported", "supported"),  # wrong -> correct
                "exclusion.osa": _row("exclusion.osa", "review", "review"),  # unchanged
                "exclusion.t2dm": _row("exclusion.t2dm", "supported", "review"),  # not new
            }
        )
    )
    assert regressions(before, after) == []


def test_rows_only_in_one_side_are_ignored() -> None:
    before = _baseline(
        {
            "age_18": _before("supported", "supported"),
            "bmi_path_a": _before("supported", "supported"),
        }
    )
    after = _split(_case({"age_18": _row("age_18", "supported", "supported")}))
    assert regressions(before, after) == []


def test_false_support_in_a_row_or_variant_the_baseline_lacks_is_a_regression() -> None:
    before = _baseline({"age_18": _before("supported", "supported")})
    # a new row of the baseline variant, and a whole new variant
    after = _split(
        _case(
            {
                "age_18": _row("age_18", "supported", "supported"),
                "bmi_path_a": _row("bmi_path_a", "supported", "review"),
            }
        ),
        _case({"exclusion.osa": _row("exclusion.osa", "supported", "review")}, vid="case-new"),
    )
    items = regressions(before, after)
    assert {(i.variant_id, i.row, i.kind) for i in items} == {
        ("case-x", "bmi_path_a", "false_support"),
        ("case-new", "exclusion.osa", "false_support"),
    }
    assert all(i.before_status is None and i.after_status == "supported" for i in items)
    # the same new rows without a false support are not regressions
    clean = _split(
        _case(
            {
                "age_18": _row("age_18", "supported", "supported"),
                "bmi_path_a": _row("bmi_path_a", "insufficient", "review"),
            }
        ),
        _case({"exclusion.osa": _row("exclusion.osa", "review", "review")}, vid="case-new"),
    )
    assert regressions(before, clean) == []
    assert (
        regressions(before, after, skipped=["case-new"]) == [items[0]]
        or len(regressions(before, after, skipped=["case-new"])) == 1
    )
