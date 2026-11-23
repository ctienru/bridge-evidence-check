"""Property tests (hypothesis): monotone BMI thresholds, order-independent conflict detection,
pathway aggregation never exceeding the BMI sub-result, deterministic decisions, `age_18` never
`supported` without a verified start, and `unrecognized` evidence behind no strong status."""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from conftest import INITIATION, checked, ctx, decide, policy
from hypothesis import given, settings
from hypothesis import strategies as st

from bridge_check.compute import BMI_TOLERANCE, compare_values, compute
from bridge_check.enums import STATUS_CODES
from bridge_check.rules import aggregate_path, evaluate_rules

pytestmark = pytest.mark.slow

DOC_DATE = checked("doc_dates", target_doc_id="D1", date="2025-03-15", event_date="2025-03-15")
statuses = st.sampled_from(STATUS_CODES)
weights = st.decimals(min_value=Decimal("40"), max_value=Decimal("250"), places=1)


def _bmi_decisions(weight: Decimal) -> dict[str, str]:
    rows = [
        INITIATION,
        DOC_DATE,
        checked("anthropometrics", kind="height", raw_value="170", raw_unit="cm"),
        checked("anthropometrics", kind="weight", raw_value=str(weight), raw_unit="kg"),
    ]
    return {k: d.status for k, d in decide(rows).items() if k.endswith(".bmi") or k == "bmi_path_a"}


@settings(deadline=None, max_examples=60)
@given(weights, weights)
def test_bmi_threshold_is_monotone(w1: Decimal, w2: Decimal) -> None:
    lo, hi = sorted((w1, w2))
    low, high = _bmi_decisions(lo), _bmi_decisions(hi)
    for cid in low:
        assert not (low[cid] == "supported" and high[cid] == "not_supported"), cid


@settings(deadline=None, max_examples=60)
@given(
    st.lists(
        st.decimals(min_value=Decimal("15"), max_value=Decimal("60"), places=2),
        min_size=1,
        max_size=6,
    ),
    st.randoms(),
)
def test_conflict_detection_is_symmetric(values: list[Decimal], rnd: random.Random) -> None:
    thresholds = [Decimal("27"), Decimal("30"), Decimal("35")]
    shuffled = list(values)
    rnd.shuffle(shuffled)
    assert compare_values(values, thresholds, BMI_TOLERANCE) == compare_values(
        shuffled, thresholds, BMI_TOLERANCE
    )


@settings(deadline=None, max_examples=100)
@given(statuses, st.lists(statuses, min_size=1, max_size=4))
def test_pathway_never_supported_without_a_supported_bmi(
    bmi: str, comorbidities: list[str]
) -> None:
    status, _ = aggregate_path(bmi, comorbidities)  # type: ignore[arg-type]
    if bmi != "supported":
        assert status != "supported"
    if all(c == "not_supported" for c in comorbidities):
        assert status == "not_supported"


_ROWS = [
    INITIATION,
    DOC_DATE,
    checked("patient_identity", dob="1961-04-02", patient_id="P-1"),
    checked("anthropometrics", kind="height", raw_value="172.7", raw_unit="cm"),
    checked("anthropometrics", kind="weight", raw_value="240", raw_unit="lb"),
    checked("anthropometrics", kind="bmi", raw_value="36"),
    checked("bp_readings", sbp=152, dbp=94, event_date="2025-03-15"),
    checked("medication_lists", list_id="L1"),
    checked("medications", name="amlodipine", list_id="L1", end_kind="ongoing"),
    checked("medications", name="metoprolol", list_id="L1", end_kind="ongoing"),
    checked("diagnoses", concept="mi", temporality="historical"),
    checked("diagnoses", concept="t2dm", certainty="negated"),
    checked("labs", kind="a1c", raw_value="6.0", raw_unit="%"),
    checked("lifestyle", kind="nutrition", program_type="commercial", end_kind="ongoing"),
    checked("pa_form_claims", claim_id="claim.bmi_bracket", claimed_value="35+", doc_id="D0"),
]


@settings(deadline=None, max_examples=25)
@given(st.permutations(list(range(len(_ROWS)))))
def test_decisions_are_deterministic_under_evidence_shuffling(order: list[int]) -> None:
    context = ctx(
        doc_roles={"D0": "pa_draft", "D1": "clinical"}, doc_identity={"D0": "match", "D1": "match"}
    )
    baseline = evaluate_rules(
        compute(
            _ROWS,
            ctx(
                evidence_ids=list(range(len(_ROWS))),
                doc_roles=context.doc_roles,
                doc_identity=context.doc_identity,
            ),
        ),
        policy(),
    )
    shuffled_rows = [_ROWS[i] for i in order]
    shuffled = evaluate_rules(
        compute(
            shuffled_rows,
            ctx(evidence_ids=order, doc_roles=context.doc_roles, doc_identity=context.doc_identity),
        ),
        policy(),
    )
    assert [d.model_dump() for d in shuffled] == [d.model_dump() for d in baseline]


# --- age_18 without a verified start (contract §3.5)  ---------------------------------------------

_days = st.dates(min_value=date(1930, 1, 1), max_value=date(2026, 10, 15)).map(date.isoformat)
_note_days = st.dates(min_value=date(2000, 1, 1), max_value=date(2030, 12, 31)).map(date.isoformat)
_note_dates = st.one_of(
    _note_days, _note_days.map(lambda d: d[:7]), _note_days.map(lambda d: d[:4])
)
_identity_rows = st.one_of(
    _days.map(lambda d: checked("patient_identity", dob=d, patient_id="P-1")),
    st.builds(
        lambda age, day: checked("patient_identity", stated_age=age, event_date=day),
        st.integers(min_value=0, max_value=110),
        st.one_of(st.none(), _note_dates),
    ),
)
# Starts that anchor nothing: another course, another day, or a row the verifier did not recognize.
_UNVERIFIED_STARTS = [
    checked("glp1_start", drug="Zepbound", date="2025-03-15", event_date="2025-03-15"),
    checked("glp1_start", drug="Wegovy", date="2024-01-10", event_date="2024-01-10"),
    replace(INITIATION, flags=("unrecognized",)),
    replace(INITIATION, certainty_llm="uncertain"),
]


@settings(deadline=None, max_examples=200)
@given(
    st.lists(_identity_rows, min_size=1, max_size=4),
    st.lists(st.sampled_from(_UNVERIFIED_STARTS), max_size=2),
    st.booleans(),
)
def test_age_is_never_supported_without_a_verified_start(
    identity: list[object], starts: list[object], dated: bool
) -> None:
    rows = [*starts, *([DOC_DATE] if dated else []), *identity]
    facts = compute(rows, ctx())  # type: ignore[arg-type]
    assert facts.initiation is None
    age = {d.condition: d for d in evaluate_rules(facts, policy())}["age_18"]
    assert age.status in ("insufficient", "not_supported")


# --- `unrecognized` evidence (contract §6)  -------------------------------------------------------

_POOL = [
    INITIATION,
    DOC_DATE,
    checked("patient_identity", dob="1961-04-02", patient_id="P-1"),
    checked("patient_identity", dob="2012-04-02", patient_id="P-1"),
    checked("anthropometrics", kind="height", raw_value="172.7", raw_unit="cm"),
    checked("anthropometrics", kind="weight", raw_value="240", raw_unit="lb"),
    checked("anthropometrics", kind="bmi", raw_value="24.3"),
    checked("anthropometrics", kind="bmi", raw_value="36.2"),
    checked("bp_readings", sbp=152, dbp=94, event_date="2025-03-15"),
    checked("medication_lists", list_id="L1", complete=True),
    checked("medications", name="amlodipine", list_id="L1", end_kind="ongoing"),
    checked("medications", name="metoprolol", list_id="L1", end_kind="ongoing"),
    checked("diagnoses", concept="hfpef"),
    checked("diagnoses", concept="hfpef", certainty="negated", event_date="2024-06-01"),
    checked("diagnoses", concept="ckd", ckd_stage="2"),
    checked("diagnoses", concept="ckd", certainty="negated", event_date="2024-06-01"),
    checked("diagnoses", concept="mi", temporality="historical"),
    checked("diagnoses", concept="stroke", certainty="negated"),
    checked("diagnoses", concept="pad", symptomatic="no"),
    checked("diagnoses", concept="pad", symptomatic="yes", event_date="2021-05"),
    checked("diagnoses", concept="prediabetes"),
    checked("diagnoses", concept="prediabetes", certainty="negated", event_date="2024-06-01"),
    checked("diagnoses", concept="t2dm", certainty="negated"),
    checked("diagnoses", concept="osa", osa_severity="mild"),
    checked("diagnoses", concept="osa", certainty="negated", event_date="2024-06-01"),
    checked("diagnoses", concept="mash", fibrosis_stage="F1"),
    checked("labs", kind="a1c", raw_value="5.2", raw_unit="%"),
    checked("labs", kind="egfr", raw_value="71", raw_unit=""),
    checked("prior_glp1", drug="Ozempic", payer="medicaid", date="2026-02"),
    checked("lifestyle", kind="nutrition", program_type="none_stated", end_kind="ongoing"),
    checked("lifestyle", kind="activity", program_type="structured", end_kind="ongoing"),
    checked("pa_form_claims", claim_id="claim.bmi_bracket", claimed_value="35+", doc_id="D0"),
    checked("pa_form_claims", claim_id="claim.exclusion.t2dm", claimed_value="no", doc_id="D0"),
    checked("pa_form_claims", claim_id="claim.drug", claimed_value="Wegovy", doc_id="D0"),
]
_picks = st.lists(
    st.sampled_from(["absent", "plain", "unrecognized"]),
    min_size=len(_POOL),
    max_size=len(_POOL),
)


@settings(deadline=None, max_examples=300)
@given(_picks)
def test_unrecognized_evidence_never_supports_a_strong_status(picks: list[str]) -> None:
    rows = [
        replace(row, flags=("unrecognized",)) if pick == "unrecognized" else row
        for row, pick in zip(_POOL, picks, strict=True)
        if pick != "absent"
    ]
    facts = compute(
        rows,
        ctx(
            doc_roles={"D0": "pa_draft", "D1": "clinical"},
            doc_identity={"D0": "match", "D1": "match"},
        ),
    )
    flagged = {i for i, row in enumerate(rows) if "unrecognized" in row.flags}
    for d in evaluate_rules(facts, policy()):
        # A pathway aggregates its sub-results' statuses; it does not rest on the flagged fact.
        if d.kind == "path":
            continue
        if flagged & set(d.used_evidence):
            assert d.status not in ("supported", "not_supported"), d.condition
