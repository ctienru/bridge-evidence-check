"""Property tests (hypothesis): monotone BMI thresholds, order-independent conflict detection,
pathway aggregation never exceeding the BMI sub-result, and deterministic decisions."""

from __future__ import annotations

import random
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
