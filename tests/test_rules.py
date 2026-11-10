"""Decision tables of contract §3 over computed facts, the §3.4 worked checks, the registry
against `rules/bridge-v1.yaml`, and the ban on threshold literals in `rules.py`."""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from conftest import INITIATION, ROOT, checked, ctx, decide, policy

from bridge_check import rules as rules_module
from bridge_check.compute import ComputedFacts, compute
from bridge_check.enums import CONDITION_IDS
from bridge_check.rules import (
    LIFESTYLE_RULES,
    RULES,
    Decision,
    Policy,
    aggregate_path,
    evaluate_rules,
    human_workload,
)
from bridge_check.rules_schema import DrugTable, load_rules
from bridge_check.verify import CheckedEvidence

DOC_DATE_D1 = checked("doc_dates", target_doc_id="D1", date="2025-03-15", event_date="2025-03-15")
DOC_DATE_D2 = checked(
    "doc_dates", target_doc_id="D2", date="2025-03-15", event_date="2025-03-15", doc_id="D2"
)
BASE = [INITIATION, DOC_DATE_D1]


def _bmi(value: str, **over: Any) -> CheckedEvidence:
    return checked("anthropometrics", kind="bmi", raw_value=value, **over)


def _flipped(**over: object) -> Policy:
    table = load_rules(ROOT / "rules" / "bridge-v1.yaml")
    return Policy.model_validate(
        {
            **table.project_policies,
            "thresholds": table.thresholds,
            "rules_version": table.version,
            **over,
        }
    )


# --- registry and policy (contract §7.3)  ---------------------------------------------------------


def test_rules_registry_matches_yaml() -> None:
    table = load_rules(ROOT / "rules" / "bridge-v1.yaml")
    yaml_ids = {c.id for c in table.conditions}
    assert yaml_ids == set(RULES)
    assert set(RULES) | set(LIFESTYLE_RULES) == set(CONDITION_IDS)
    facts = compute([], ctx())
    for cond in table.conditions:
        for name in cond.requires:
            target: object = facts
            for part in name.split("."):
                if isinstance(target, dict):
                    target = next(iter(target.values()), None)
                    assert target is not None, name
                assert hasattr(target, part), f"{cond.id} requires {name}"
                target = getattr(target, part)


def test_every_condition_gets_exactly_one_decision() -> None:
    decisions = evaluate_rules(compute([], ctx()), policy())
    assert [d.condition for d in decisions] == list(CONDITION_IDS)
    assert all(d.rules_version == "bridge-v1" for d in decisions)
    assert all(d.rule_id.startswith(d.condition + ":") for d in decisions)


THRESHOLD_LITERALS = {15, 18, 27, 30, 35, 60, 90, 126, 140, 5.7, 6.4, 6.5}


def test_no_threshold_literals_in_rules() -> None:
    tree = ast.parse(Path(rules_module.__file__).read_text(encoding="utf-8"))
    found: list[tuple[int, object]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and not isinstance(node.value, bool):
            value = node.value
            if isinstance(value, int | float) and value in THRESHOLD_LITERALS:
                found.append((node.lineno, value))
            if isinstance(value, str) and value in {str(x) for x in THRESHOLD_LITERALS}:
                found.append((node.lineno, value))
    assert found == []


def test_exclusion_decisions_are_never_supported() -> None:
    with pytest.raises(ValueError):
        Decision(
            condition="exclusion.t2dm",
            kind="exclusion",
            status="supported",
            reason="x",
            rule_id="exclusion.t2dm:1",
            rules_version="bridge-v1",
        )


# --- §3.4 worked checks  --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "bmi", "comorbidities", "expected"),
    [
        (
            "07 pathway B",
            "insufficient",
            ["insufficient", "not_supported", "insufficient"],
            "insufficient",
        ),
        ("15 pathway B", "insufficient", ["supported", "insufficient", "review"], "insufficient"),
        ("13 pathway C", "supported", ["supported"], "supported"),
        (
            "05 pathway C",
            "supported",
            ["supported", "supported"],
            "supported",
        ),  # downgrade tested below
        ("17 pathway C", "insufficient", ["supported"], "insufficient"),
        ("E11", "not_supported", ["insufficient", "insufficient", "insufficient"], "not_supported"),
        ("hypothetical review", "supported", ["review", "insufficient", "insufficient"], "review"),
        (
            "hypothetical all not_supported",
            "review",
            ["not_supported", "not_supported"],
            "not_supported",
        ),
    ],
)
def test_pathway_aggregation_table(
    label: str, bmi: str, comorbidities: list[str], expected: str
) -> None:
    status, _ = aggregate_path(bmi, comorbidities)  # type: ignore[arg-type]
    assert status == expected, label


def test_pathway_c_cv_history_only_is_review() -> None:
    rows = BASE + [_bmi("36"), checked("diagnoses", concept="mi", temporality="historical")]
    d = decide(rows)
    assert d["bmi_path_c.mi"].status == "supported"
    assert d["bmi_path_c"].status == "review" and d["bmi_path_c"].flags == ("cv_history_only",)
    assert d["bmi_path_c"].rule_id == "bmi_path_c:downgrade.cv_history_only"
    relaxed = decide(rows, policy=_flipped(path_c_cv_history_requires_review=False))
    assert relaxed["bmi_path_c"].status == "supported"


def test_mace_purpose_downgrades_every_supported_pathway() -> None:
    mace = checked(
        "glp1_start", drug="Wegovy", date="2025-03-15", event_date="2025-03-15", purpose="mace"
    )
    rows = [mace, DOC_DATE_D1, _bmi("36"), checked("diagnoses", concept="hfpef")]
    d = decide(rows)
    assert d["bmi_path_a"].status == "review" and d["bmi_path_a"].rule_id.endswith(
        "downgrade.mace_purpose"
    )
    assert d["bmi_path_b"].status == "review"
    assert d["bmi_path_b.bmi"].status == "supported"  # sub-results stay


# --- BMI (contract §3.1)  -------------------------------------------------------------------------


def test_bmi_without_initiation_is_insufficient() -> None:
    d = decide([DOC_DATE_D1, _bmi("46", relative_llm="at")])
    for cid in ("bmi_path_a", "bmi_path_b.bmi", "bmi_path_c.bmi", "bmi_path_b", "bmi_path_c"):
        assert d[cid].status == "insufficient", cid


def test_bmi_conflict_when_candidates_straddle_the_threshold() -> None:
    d = decide(BASE + [_bmi("29.9"), _bmi("30.1")])
    assert d["bmi_path_b.bmi"].status == "conflict"
    assert d["bmi_path_c.bmi"].status == "supported"
    assert d["bmi_path_c.bmi"].flags == ()  # within tolerance
    assert d["bmi_path_a"].status == "not_supported"
    assert d["bmi_path_b"].status == "conflict"


def test_bmi_same_side_beyond_tolerance_adds_inconsistent_values() -> None:
    d = decide(BASE + [_bmi("34.6"), _bmi("36")])
    assert d["bmi_path_a"].status == "conflict"
    assert d["bmi_path_b.bmi"].status == "supported" and d["bmi_path_b.bmi"].flags == (
        "inconsistent_values",
    )


def test_integer_bmi_without_height_and_weight_is_review() -> None:
    d = decide(BASE + [_bmi("30")])
    assert d["bmi_path_b.bmi"].status == "review" and d["bmi_path_b.bmi"].flags == (
        "imprecise_source",
    )
    assert d["bmi_path_c.bmi"].status == "supported"
    assert d["bmi_path_a"].status == "not_supported"
    assert d["bmi_path_b.bmi"].computed["bmi_raw"] == "30"


def test_integer_bmi_with_height_and_weight_uses_the_computed_value() -> None:
    rows = BASE + [
        _bmi("41"),
        checked("anthropometrics", kind="height", raw_value="172.7", raw_unit="cm"),
        checked("anthropometrics", kind="weight", raw_value="122", raw_unit="kg"),
    ]
    d = decide(rows)
    assert d["bmi_path_a"].status == "supported"
    assert d["bmi_path_a"].computed["bmi_raw"].startswith("40.9")


def test_bmi_before_only_is_review_and_after_is_excluded() -> None:
    before = decide(BASE + [_bmi("36", event_date="2025-02-28")])
    assert before["bmi_path_a"].status == "review"
    assert before["bmi_path_a"].excluded_evidence[0].reason == "before_initiation"
    after = decide(BASE + [_bmi("36", event_date="2025-04-02")])
    assert after["bmi_path_a"].status == "insufficient"
    assert after["bmi_path_a"].excluded_evidence[0].reason == "after_initiation"


@pytest.mark.parametrize("flag", ["table_source", "timing_disagreement", "unrecognized"])
def test_supported_bmi_with_a_risky_flag_is_review(flag: str) -> None:
    if flag == "timing_disagreement":
        row = _bmi("36", relative_llm="before")  # the model said before, the date says at
    else:
        row = _bmi("36", flags=(flag,))
    d = decide(BASE + [row])
    assert d["bmi_path_a"].status == "review" and flag in d["bmi_path_a"].flags
    assert d["bmi_path_a"].rule_id == "bmi_path_a:8"


def test_candidate_position_is_excluded_as_candidate_only() -> None:
    d = decide(BASE + [_bmi("36", position_status="candidate")])
    assert d["bmi_path_a"].status == "insufficient"
    assert d["bmi_path_a"].excluded_evidence[0].reason == "candidate_only"


def test_bracket_policy_switch() -> None:
    d = decide(BASE + [_bmi("36.5")])
    assert d["bmi_path_a"].computed["bracket"] == "[35,40)"
    off = decide(BASE + [_bmi("36.5")], policy=_flipped(bmi_bucket_from_raw=False))
    assert "bracket" not in off["bmi_path_a"].computed


# --- hypertension (contract §3.2)  ----------------------------------------------------------------


def _htn_rows(sbp: int, dbp: int, *drugs: str, complete: bool = False) -> list[CheckedEvidence]:
    rows = BASE + [
        checked("bp_readings", sbp=sbp, dbp=dbp, event_date="2025-03-15", relative_llm="at"),
        checked("medication_lists", list_id="L1", complete=complete),
    ]
    rows += [checked("medications", name=n, list_id="L1", end_kind="ongoing") for n in drugs]
    return rows


def test_htn_boundary_reading_with_ambiguous_diuretics_is_insufficient() -> None:
    d = decide(_htn_rows(140, 88, "amiloride/HCTZ", "furosemide"))["bmi_path_b.htn"]
    assert d.status == "insufficient" and d.flags == ("boundary_value",)
    assert d.rule_id == "bmi_path_b.htn:2"


def test_htn_above_threshold_through_an_ambiguous_drug_is_review() -> None:
    d = decide(_htn_rows(152, 94, "amlodipine", "furosemide"))["bmi_path_b.htn"]
    assert d.status == "review" and "class_ambiguous" in d.flags


def test_htn_two_products_on_the_same_note_list_is_supported() -> None:
    d = decide(_htn_rows(152, 94, "Norvasc", "metoprolol tartrate"))["bmi_path_b.htn"]
    assert d.status == "supported" and d.flags == ("same_note_list",)
    # the reading, both drugs, their list, the note's date sentence and the start sentence
    assert len(d.used_evidence) == 6


def test_htn_combination_pill_alone_is_review() -> None:
    table = DrugTable.model_validate(
        {
            "version": 1,
            "drugs": [
                {
                    "names": ["Exforge", "valsartan/amlodipine"],
                    "drug_canonical": "valsartan/amlodipine",
                    "class": "arb",
                    "components": [
                        {"drug_canonical": "valsartan", "class": "arb"},
                        {"drug_canonical": "amlodipine", "class": "calcium_channel_blocker"},
                    ],
                },
                # drugs-v2 schema: every component needs a standalone entry of the same class.
                {"names": ["valsartan"], "drug_canonical": "valsartan", "class": "arb"},
                {
                    "names": ["amlodipine"],
                    "drug_canonical": "amlodipine",
                    "class": "calcium_channel_blocker",
                },
            ],
        }
    )
    d = decide(_htn_rows(152, 94, "Exforge"), drugs=table)["bmi_path_b.htn"]
    assert d.status == "review" and "combination_pill" in d.flags
    assert d.rule_id == "bmi_path_b.htn:3b"


def test_htn_complete_list_with_one_drug_is_not_supported_only_by_policy() -> None:
    rows = _htn_rows(152, 94, "amlodipine", complete=True)
    assert decide(rows)["bmi_path_b.htn"].status == "not_supported"
    relaxed = decide(rows, policy=_flipped(htn_not_supported_by_complete_list=False))
    assert relaxed["bmi_path_b.htn"].status == "insufficient"


def test_htn_no_reading_at_initiation_is_insufficient() -> None:
    rows = BASE + [checked("bp_readings", sbp=160, dbp=100, event_date="2024-01-10")]
    d = decide(rows)["bmi_path_b.htn"]
    assert d.status == "insufficient" and d.rule_id == "bmi_path_b.htn:1"
    assert d.excluded_evidence[0].reason == "before_initiation"


# --- other comorbidities  -------------------------------------------------------------------------


def test_hfpef_table() -> None:
    assert (
        decide(BASE + [checked("diagnoses", concept="hfpef")])["bmi_path_b.hfpef"].status
        == "supported"
    )
    assert (
        decide(BASE + [checked("diagnoses", concept="hfpef", certainty="uncertain")])[
            "bmi_path_b.hfpef"
        ].status
        == "review"
    )
    assert (
        decide(BASE + [checked("diagnoses", concept="hfpef", certainty="negated")])[
            "bmi_path_b.hfpef"
        ].status
        == "not_supported"
    )
    assert (
        decide(BASE + [checked("diagnoses", concept="hfpef", subject="family")])[
            "bmi_path_b.hfpef"
        ].status
        == "insufficient"
    )


def test_dx_conflict_at_the_same_timepoint() -> None:
    rows = BASE + [
        checked("diagnoses", concept="mi", temporality="historical"),
        checked("diagnoses", concept="mi", certainty="negated"),
    ]
    assert decide(rows)["bmi_path_c.mi"].status == "conflict"


def test_ckd_table() -> None:
    def ckd(**o: Any) -> CheckedEvidence:
        return checked("diagnoses", concept="ckd", **o)

    assert decide(BASE + [ckd(ckd_stage="3a")])["bmi_path_b.ckd"].status == "supported"
    assert decide(BASE + [ckd(ckd_stage="2")])["bmi_path_b.ckd"].status == "not_supported"
    egfr_only = decide(BASE + [ckd(), checked("labs", kind="egfr", raw_value="48", raw_unit="")])
    assert (
        egfr_only["bmi_path_b.ckd"].status == "review"
        and "48" in egfr_only["bmi_path_b.ckd"].reason
    )
    assert (
        decide(BASE + [checked("labs", kind="egfr", raw_value="48", raw_unit="")])[
            "bmi_path_b.ckd"
        ].status
        == "insufficient"
    )


def test_pad_takes_the_record_closest_to_initiation() -> None:
    rows = BASE + [
        checked("diagnoses", concept="pad", symptomatic="no", event_date="2025-03-15"),
        checked("diagnoses", concept="pad", symptomatic="yes", event_date="2021-05"),
    ]
    d = decide(rows)["bmi_path_c.pad"]
    assert d.status == "not_supported"
    assert d.excluded_evidence[0].reason == "superseded_by_at"
    assert decide(BASE + [checked("diagnoses", concept="pad")])["bmi_path_c.pad"].status == "review"


def test_prediabetes_table() -> None:
    def a1c(v: str) -> CheckedEvidence:
        return checked("labs", kind="a1c", raw_value=v, raw_unit="%")

    assert (
        decide(BASE + [checked("diagnoses", concept="prediabetes")])[
            "bmi_path_c.prediabetes"
        ].status
        == "supported"
    )
    in_range = decide(BASE + [a1c("6.0")])
    assert in_range["bmi_path_c.prediabetes"].status == "review"
    assert in_range["exclusion.t2dm"].status == "insufficient"
    diabetic = decide(BASE + [a1c("6.5")])
    assert diabetic["bmi_path_c.prediabetes"].status == "insufficient"
    assert diabetic["exclusion.t2dm"].status == "review"
    assert diabetic["exclusion.t2dm"].rule_id == "exclusion.t2dm:4-lab"
    assert decide(BASE + [a1c("5.4")])["bmi_path_c.prediabetes"].status == "insufficient"
    assert (
        decide(BASE + [checked("diagnoses", concept="prediabetes", certainty="negated")])[
            "bmi_path_c.prediabetes"
        ].status
        == "not_supported"
    )


def test_lab_conflict_across_a_threshold_on_the_same_day() -> None:
    rows = BASE + [
        checked("labs", kind="a1c", raw_value="6.4", raw_unit="%", event_date="2025-03-01"),
        checked("labs", kind="a1c", raw_value="6.6", raw_unit="%", event_date="2025-03-01"),
    ]
    assert decide(rows)["bmi_path_c.prediabetes"].status == "conflict"


# --- exclusions (contract §3.3)  ------------------------------------------------------------------


def test_exclusion_table() -> None:
    def t2dm(**o: Any) -> CheckedEvidence:
        return checked("diagnoses", concept="t2dm", **o)

    assert decide(BASE + [t2dm()])["exclusion.t2dm"].status == "review"
    assert decide(BASE + [t2dm(temporality="resolved")])["exclusion.t2dm"].status == "review"
    assert decide(BASE + [t2dm(certainty="negated")])["exclusion.t2dm"].status == "not_supported"
    assert decide(BASE)["exclusion.t2dm"].status == "insufficient"
    after = decide(BASE + [t2dm(event_date="2025-07")])["exclusion.t2dm"]
    assert after.status == "review" and after.flags == ("post_initiation_exclusion",)
    both = decide(BASE + [t2dm(), t2dm(certainty="negated")])["exclusion.t2dm"]
    assert both.status == "conflict"


def test_osa_and_mash_special_staging() -> None:
    assert (
        decide(BASE + [checked("diagnoses", concept="osa", osa_severity="mild")])[
            "exclusion.osa"
        ].status
        == "not_supported"
    )
    assert (
        decide(BASE + [checked("diagnoses", concept="osa", ahi=12)])["exclusion.osa"].status
        == "not_supported"
    )
    assert (
        decide(BASE + [checked("diagnoses", concept="osa", ahi=22)])["exclusion.osa"].status
        == "review"
    )
    assert decide(BASE + [checked("diagnoses", concept="osa")])["exclusion.osa"].status == "review"
    assert (
        decide(BASE + [checked("diagnoses", concept="mash", fibrosis_stage="F1")])[
            "exclusion.mash"
        ].status
        == "not_supported"
    )
    assert (
        decide(BASE + [checked("diagnoses", concept="mash", cirrhosis=True)])[
            "exclusion.mash"
        ].status
        == "not_supported"
    )
    assert (
        decide(BASE + [checked("diagnoses", concept="mash", fibrosis_stage="F2")])[
            "exclusion.mash"
        ].status
        == "review"
    )


def test_part_d_table() -> None:
    def prior(**o: Any) -> CheckedEvidence:
        return checked("prior_glp1", drug="Ozempic", **o)

    assert (
        decide(BASE + [prior(payer="part_d", date="2026-02")])["exclusion.part_d_glp1"].status
        == "review"
    )
    assert decide(BASE + [prior(payer="part_d")])["exclusion.part_d_glp1"].status == "review"
    assert (
        decide(BASE + [prior(payer="part_d", date="2025")])["exclusion.part_d_glp1"].status
        == "not_supported"
    )
    assert (
        decide(BASE + [prior(payer="medicaid", date="2026-02")])["exclusion.part_d_glp1"].status
        == "not_supported"
    )
    assert (
        decide(BASE + [prior(payer="unknown", date="2026-02")])["exclusion.part_d_glp1"].status
        == "insufficient"
    )
    assert decide(BASE)["exclusion.part_d_glp1"].status == "insufficient"


# --- age, identity, lifestyle (contract §3.5)  ----------------------------------------------------


def test_age_stated_after_initiation_uses_interval() -> None:
    start = checked("glp1_start", drug="Wegovy", date="2025-03-15", event_date="2025-03-15")

    def stated(age: int, event_date: str, relative: str) -> Decision:
        row = checked(
            "patient_identity", stated_age=age, event_date=event_date, relative_llm=relative
        )
        return decide([start, row])["age_18"]

    # 85 three years after initiation → at least 81 → supported
    assert stated(85, "2028-03-15", "after").status == "supported"
    # 19 three years after initiation (day precision) → 16 → not_supported
    assert stated(19, "2028-03-15", "after").status == "not_supported"
    # 19 in a note dated only by year, two years after → interval [16, 18] straddles → review
    straddle = stated(19, "2027", "after")
    assert straddle.status == "review" and straddle.computed["intervals"][0][:2] == [16, 18]
    # 13 ten years before initiation → about 23 → supported
    assert stated(13, "2015-03-15", "before").status == "supported"


@pytest.mark.parametrize("stated_age", [17, 16])
def test_age_conflict_when_verified_intervals_fall_on_opposite_sides(stated_age: int) -> None:
    rows = BASE + [
        checked("patient_identity", stated_age=stated_age),
        checked("patient_identity", dob="2007-03-15", patient_id="P-1"),
    ]
    d = decide(rows)["age_18"]
    assert d.status == "conflict"
    assert d.flags == ()
    assert d.used_evidence == (0, 1, 2, 3)


def test_age_review_with_clear_and_straddling_intervals() -> None:
    rows = BASE + [
        checked("patient_identity", dob="2007-03-15", patient_id="P-1"),
        checked("patient_identity", stated_age=19, event_date="2027", relative_llm="after"),
    ]
    d = decide(rows)["age_18"]
    assert d.status == "review"
    assert [interval[:2] for interval in d.computed["intervals"]] == [[18, 18], [16, 18]]


def test_age_from_dob_with_inconsistent_stated_age() -> None:
    rows = BASE + [
        checked("patient_identity", dob="1961-04-02", patient_id="P-1"),
        checked("patient_identity", stated_age=55),
    ]
    d = decide(rows)["age_18"]
    assert d.status == "supported" and d.flags == ("inconsistent_values",)


def test_age_without_initiation_date() -> None:
    # no verified start: the interval is taken at the document's own date
    assert (
        decide([checked("patient_identity", stated_age=64, event_date="2025-03-15")])[
            "age_18"
        ].status
        == "supported"
    )
    straddle = decide([checked("patient_identity", stated_age=18, event_date="2025")])["age_18"]
    assert straddle.status == "insufficient"
    mixed = decide(
        [
            DOC_DATE_D1,
            checked("patient_identity", stated_age=17),
            checked("patient_identity", stated_age=18),
        ]
    )["age_18"]
    assert mixed.status == "insufficient"
    assert decide([])["age_18"].status == "insufficient"


def test_identity_table() -> None:
    assert decide(BASE)["patient_identity"].status == "supported"
    mismatch = decide(BASE, doc_identity={"D1": "match", "D2": "mismatch"})["patient_identity"]
    assert mismatch.status == "conflict"
    missing = decide(BASE, doc_identity={"D1": "match", "D2": "missing"})["patient_identity"]
    assert missing.status == "review" and missing.flags == ("id_missing",)
    none = decide(BASE, doc_identity={"D1": "missing", "D2": "missing"})["patient_identity"]
    assert none.status == "insufficient"


def test_lifestyle_table() -> None:
    def life(**o: Any) -> CheckedEvidence:
        o.setdefault("event_date", "2026-09-01")
        return checked("lifestyle", kind="nutrition", **o)

    assert (
        decide([life(program_type="structured_clinical", end_kind="ongoing")])[
            "lifestyle.nutrition"
        ].status
        == "supported"
    )
    assert (
        decide([life(program_type="none_stated")])["lifestyle.nutrition"].status == "not_supported"
    )
    assert (
        decide([life(program_type="commercial", end_kind="ongoing")])["lifestyle.nutrition"].status
        == "review"
    )
    assert (
        decide(
            [life(program_type="structured_clinical", end_kind="ongoing", attendance="irregular")]
        )["lifestyle.nutrition"].status
        == "review"
    )
    assert (
        decide(
            [life(program_type="referral_pending", end_kind="unknown", event_date="2025-03-15")]
        )["lifestyle.nutrition"].status
        == "insufficient"
    )
    later = decide([life(program_type="structured_clinical", start="2026-12", end_kind="ongoing")])[
        "lifestyle.nutrition"
    ]
    assert later.status == "insufficient" and later.excluded_evidence[0].reason == "timing_unknown"
    assert decide([])["lifestyle.activity"].status == "insufficient"


# --- claims (contract §2; guide K-03, K-04)  ------------------------------------------------------


def _claim(claim_id: str, value: str) -> CheckedEvidence:
    return checked("pa_form_claims", claim_id=claim_id, claimed_value=value, doc_id="D0")


def _decide_claims(
    rows: list[CheckedEvidence], claims: list[CheckedEvidence]
) -> dict[str, Decision]:
    return decide(
        rows + claims,
        doc_roles={"D0": "pa_draft", "D1": "clinical", "D2": "clinical"},
        doc_identity={"D0": "match", "D1": "match", "D2": "match"},
    )


def test_claims_follow_the_condition_status() -> None:
    rows = BASE + [_bmi("46"), checked("diagnoses", concept="stroke", certainty="negated")]
    claims = [
        _claim("claim.age_18", "yes"),
        _claim("claim.drug", "Wegovy"),
        _claim("claim.bmi_bracket", "≥40"),
        _claim("claim.exclusion.t2dm", "no"),
        _claim("claim.bmi_path_c.stroke", "no"),
        _claim("claim.bmi_path_b.hfpef", "yes"),
        _claim("claim.lifestyle.nutrition", "yes"),
    ]
    d = _decide_claims(rows, claims)
    assert d["claim.age_18"].status == "insufficient"  # no age in the chart
    assert d["claim.drug"].status == "supported"
    assert d["claim.bmi_bracket"].status == "supported"
    assert d["claim.exclusion.t2dm"].status == "insufficient"
    assert d["claim.bmi_path_c.stroke"].status == "supported"  # chart denies, box says no
    assert d["claim.bmi_path_b.hfpef"].status == "insufficient"
    assert d["claim.lifestyle.nutrition"].status == "insufficient"
    assert all(x.kind == "claim" for x in d.values() if x.condition.startswith("claim."))


def test_claim_conflicts_and_review() -> None:
    rows = BASE + [
        _bmi("29.95"),
        checked("diagnoses", concept="t2dm"),
        checked("diagnoses", concept="hfpef", certainty="uncertain"),
    ]
    d = _decide_claims(
        rows,
        [
            _claim("claim.bmi_bracket", "30-34.9"),
            _claim("claim.exclusion.t2dm", "no"),
            _claim("claim.bmi_path_b.hfpef", "yes"),
            _claim("claim.drug", "Zepbound"),
        ],
    )
    assert d["claim.bmi_bracket"].status == "conflict"  # 29.95 is in [27,30) (guide K-04)
    assert d["claim.exclusion.t2dm"].status == "review"  # positive exclusion evidence stays review
    assert d["claim.bmi_path_b.hfpef"].status == "review"
    assert d["claim.drug"].status == "conflict"


def test_human_workload_counts_top_level_rows_only() -> None:
    decisions = evaluate_rules(compute([], ctx()), policy())
    top = [d for d in decisions if d.kind in ("condition", "path", "exclusion")]
    # on an empty case everything is insufficient except identity (both documents match)
    assert human_workload(decisions) == len(top) - 1
    assert human_workload(d for d in decisions if d.kind in ("sub", "lifestyle")) == 0


def test_facts_type_is_the_rules_input() -> None:
    assert isinstance(compute([], ctx(target_start=date(2025, 3, 15))), ComputedFacts)


# --- review items -----------------------------------------------------------------------------


def test_family_bmi_and_bp_support_nothing() -> None:
    rows = BASE + [
        _bmi("36.5", subject="family"),
        checked("bp_readings", sbp=152, dbp=94, event_date="2025-03-15", subject="family"),
        checked("medication_lists", list_id="L1"),
        checked("medications", name="amlodipine", list_id="L1", end_kind="ongoing"),
        checked("medications", name="metoprolol", list_id="L1", end_kind="ongoing"),
    ]
    d = decide(rows)
    assert d["bmi_path_a"].status == "insufficient"
    assert d["bmi_path_b.htn"].status == "insufficient" and d["bmi_path_b.htn"].rule_id.endswith(
        ":1"
    )


def test_bmi_decision_lists_the_inherited_date_evidence() -> None:
    d = decide([INITIATION, DOC_DATE_D1, _bmi("36.5")], evidence_ids=[1, 2, 3])["bmi_path_a"]
    assert d.status == "supported" and d.used_evidence == (1, 2, 3)


@pytest.mark.parametrize("mace_first", [True, False])
def test_mace_downgrade_survives_evidence_order(mace_first: bool) -> None:
    weight = checked("glp1_start", drug="Wegovy", date="2025-03-15", event_date="2025-03-15")
    mace = checked(
        "glp1_start", drug="Wegovy", date="2025-03-15", event_date="2025-03-15", purpose="mace"
    )
    rows = ([mace, weight] if mace_first else [weight, mace]) + [DOC_DATE_D1, _bmi("36.5")]
    d = decide(rows, evidence_ids=[1, 2, 3, 4])
    assert d["bmi_path_a"].status == "review" and d["bmi_path_a"].rule_id.endswith("mace_purpose")


def test_later_note_quoting_a_historical_reading_does_not_support_htn() -> None:
    april = checked("doc_dates", target_doc_id="D1", date="2025-04-10", event_date="2025-04-10")
    rows = [
        INITIATION,
        april,
        checked("bp_readings", sbp=152, dbp=94, event_date="2025-03-15"),
        checked("medication_lists", list_id="L1"),
        checked(
            "medications", name="amlodipine", list_id="L1", end_kind="ongoing", relative_llm="after"
        ),
        checked(
            "medications", name="metoprolol", list_id="L1", end_kind="ongoing", relative_llm="after"
        ),
    ]
    d = decide(rows)["bmi_path_b.htn"]
    assert d.status == "insufficient" and d.rule_id == "bmi_path_b.htn:5"
    assert {x.reason for x in d.excluded_evidence} == {"period_unknown"}


@pytest.mark.parametrize("high_first", [True, False])
def test_contradictory_same_day_readings_are_a_conflict(high_first: bool) -> None:
    high = checked("bp_readings", sbp=152, dbp=94, event_date="2025-03-15")
    low = checked("bp_readings", sbp=139, dbp=89, event_date="2025-03-15")
    rows = (
        BASE
        + ([high, low] if high_first else [low, high])
        + [
            checked("medication_lists", list_id="L1"),
            checked("medications", name="amlodipine", list_id="L1", end_kind="ongoing"),
            checked("medications", name="metoprolol", list_id="L1", end_kind="ongoing"),
        ]
    )
    d = decide(rows)["bmi_path_b.htn"]
    assert d.status == "conflict" and len(d.used_evidence) == 3  # both readings and the start


def test_dated_bmi_with_an_unknown_model_timepoint_is_not_capped() -> None:
    """Contract §5 item 1: the model's `unknown` is "not stated", not a disagreement."""
    d = decide(BASE + [_bmi("36.5", event_date="2025-03-15", relative_llm="unknown")])["bmi_path_a"]
    assert d.status == "supported" and "timing_disagreement" not in d.flags


def test_claims_keep_the_charts_uncertainty() -> None:
    claims = [_claim("claim.exclusion.t2dm", "yes"), _claim("claim.exclusion.part_d_glp1", "no")]
    suspected = _decide_claims(
        BASE + [checked("diagnoses", concept="t2dm", certainty="uncertain")], claims
    )
    assert suspected["claim.exclusion.t2dm"].status == "review"
    lab_only = _decide_claims(
        BASE + [checked("labs", kind="a1c", raw_value="6.7", raw_unit="%")], claims
    )
    assert lab_only["claim.exclusion.t2dm"].status == "review"
    fill_2025 = _decide_claims(
        BASE + [checked("prior_glp1", drug="Ozempic", payer="part_d", date="2025")], claims
    )
    assert fill_2025["exclusion.part_d_glp1"].status == "not_supported"
    assert fill_2025["claim.exclusion.part_d_glp1"].status == "insufficient"


def test_future_dated_lifestyle_record_cannot_support() -> None:
    row = checked(
        "lifestyle",
        kind="nutrition",
        program_type="structured_clinical",
        end_kind="ongoing",
        event_date="2027-01-10",
        relative_llm="after",
    )
    d = decide([row])["lifestyle.nutrition"]
    assert d.status == "insufficient" and d.excluded_evidence[0].reason == "timing_unknown"


# --- second review round ------------------------------------------------------------------------


def test_historical_list_entries_are_not_in_use_on_the_note_date() -> None:
    rows = BASE + [
        checked("bp_readings", sbp=152, dbp=94, event_date="2025-03-15"),
        checked("medication_lists", list_id="L1", temporality="historical"),
        checked(
            "medications",
            name="amlodipine",
            list_id="L1",
            end_kind="unknown",
            temporality="historical",
        ),
        checked(
            "medications",
            name="metoprolol",
            list_id="L1",
            end_kind="unknown",
            temporality="historical",
        ),
    ]
    d = decide(rows)["bmi_path_b.htn"]
    assert d.status == "insufficient" and {x.reason for x in d.excluded_evidence} == {
        "period_unknown"
    }


def test_month_dated_ongoing_drugs_do_not_certainly_cover_a_day() -> None:
    month = checked(
        "doc_dates",
        target_doc_id="D2",
        date="2025-03",
        event_date="2025-03",
        doc_id="D2",
        relative_llm="unknown",
    )
    rows = [
        INITIATION,
        month,
        checked("bp_readings", sbp=152, dbp=94, event_date="2025-03-15"),
        checked("medication_lists", list_id="L1", doc_id="D2", relative_llm="unknown"),
        checked(
            "medications",
            name="amlodipine",
            list_id="L1",
            end_kind="ongoing",
            doc_id="D2",
            relative_llm="unknown",
        ),
        checked(
            "medications",
            name="metoprolol",
            list_id="L1",
            end_kind="ongoing",
            doc_id="D2",
            relative_llm="unknown",
        ),
    ]
    d = decide(rows)["bmi_path_b.htn"]
    assert d.status == "insufficient" and d.rule_id == "bmi_path_b.htn:5"


@pytest.mark.parametrize("tall_first", [True, False])
def test_equally_near_heights_both_count_and_can_conflict(tall_first: bool) -> None:
    h170 = checked("anthropometrics", kind="height", raw_value="170", raw_unit="cm")
    h180 = checked("anthropometrics", kind="height", raw_value="180", raw_unit="cm")
    rows = (
        BASE
        + ([h180, h170] if tall_first else [h170, h180])
        + [checked("anthropometrics", kind="weight", raw_value="102", raw_unit="kg")]
    )
    d = decide(rows)
    assert d["bmi_path_a"].status == "conflict"  # 35.3 vs 31.5 straddle 35
    assert d["bmi_path_b.bmi"].status == "supported"


@pytest.mark.parametrize("high_first", [True, False])
def test_ckd_stages_on_both_sides_of_3a_conflict(high_first: bool) -> None:
    s3a = checked("diagnoses", concept="ckd", ckd_stage="3a")
    s2 = checked("diagnoses", concept="ckd", ckd_stage="2")
    d = decide(BASE + ([s3a, s2] if high_first else [s2, s3a]))
    assert d["bmi_path_b.ckd"].status == "conflict"
    assert d["bmi_path_b"].status != "supported"


def test_table_sourced_anchors_and_readings_cap_support_at_review() -> None:
    table_bp = decide(
        BASE
        + [
            checked(
                "bp_readings", sbp=152, dbp=94, event_date="2025-03-15", flags=("table_source",)
            ),
            checked("medication_lists", list_id="L1"),
            checked("medications", name="amlodipine", list_id="L1", end_kind="ongoing"),
            checked("medications", name="metoprolol", list_id="L1", end_kind="ongoing"),
        ]
    )["bmi_path_b.htn"]
    assert table_bp.status == "review" and "table_source" in table_bp.flags
    table_date = checked(
        "doc_dates",
        target_doc_id="D1",
        date="2025-03-15",
        event_date="2025-03-15",
        flags=("table_source",),
    )
    via_date = decide([INITIATION, table_date, _bmi("36.5")])["bmi_path_a"]
    assert via_date.status == "review" and "table_source" in via_date.flags
    table_start = checked(
        "glp1_start",
        drug="Wegovy",
        date="2025-03-15",
        event_date="2025-03-15",
        flags=("table_source",),
    )
    via_start = decide([table_start, DOC_DATE_D1, _bmi("36.5")])["bmi_path_a"]
    assert via_start.status == "review"
    bracket = _decide_claims(
        BASE + [_bmi("36.5", flags=("table_source",))], [_claim("claim.bmi_bracket", "35-39.9")]
    )
    assert bracket["claim.bmi_bracket"].status == "review"


def test_claims_come_only_from_the_pa_draft() -> None:
    rows = BASE + [checked("diagnoses", concept="t2dm", certainty="negated")]
    stray = checked(
        "pa_form_claims", claim_id="claim.exclusion.t2dm", claimed_value="no", doc_id="D1"
    )
    d = decide(rows + [stray])
    assert "claim.exclusion.t2dm" not in d


def test_negative_claim_on_a_table_only_denial_is_review() -> None:
    denial = checked("diagnoses", concept="t2dm", certainty="negated", flags=("table_source",))
    d = _decide_claims(BASE + [denial], [_claim("claim.exclusion.t2dm", "no")])
    assert d["exclusion.t2dm"].status == "not_supported"
    assert d["claim.exclusion.t2dm"].status == "review"


def test_decisions_record_only_the_flags_that_changed_them() -> None:
    row = checked(
        "lifestyle",
        kind="nutrition",
        program_type="referral_pending",
        end_kind="unknown",
        flags=("unrecognized",),
    )
    d = decide([row])["lifestyle.nutrition"]
    assert d.status == "insufficient" and d.flags == ()


def test_drug_claim_compares_products_when_both_sides_name_one() -> None:
    claims = [_claim("claim.drug", "Ozempic")]
    d = _decide_claims(BASE, claims)
    assert d["claim.drug"].status == "conflict"  # Wegovy started, Ozempic requested
    generic = checked("glp1_start", drug="semaglutide", date="2025-03-15", event_date="2025-03-15")
    d = _decide_claims([generic, DOC_DATE_D1], claims)
    assert d["claim.drug"].status == "supported"  # an ingredient covers its products


@pytest.mark.parametrize("status", ["discontinued", "unknown"])
def test_list_not_verified_as_current_does_not_place_its_drugs(status: str) -> None:
    rows = BASE + [
        checked("bp_readings", sbp=152, dbp=94, event_date="2025-03-15"),
        checked("medication_lists", list_id="L1", list_status=status),
        checked("medications", name="amlodipine", list_id="L1", end_kind="ongoing"),
        checked("medications", name="metoprolol", list_id="L1", end_kind="ongoing"),
    ]
    d = decide(rows)["bmi_path_b.htn"]
    assert d.status == "insufficient" and d.rule_id == "bmi_path_b.htn:5"


def test_mash_f1_chart_with_a_denied_full_mash_box() -> None:
    chart = checked("diagnoses", concept="mash", fibrosis_stage="F1")
    d = _decide_claims(BASE + [chart], [_claim("claim.exclusion.mash", "no")])
    assert d["exclusion.mash"].status == "not_supported"
    assert d["claim.exclusion.mash"].status == "supported"  # the full question is denied correctly
