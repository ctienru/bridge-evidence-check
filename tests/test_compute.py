"""`compute`: timepoints, document dates, normalization, BMI candidates, ages, medication
periods and the value-comparison helper (contract §4, §5, §7.3; guide T-02–T-09)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from conftest import INITIATION, checked, ctx, decide

from bridge_check.compute import (
    BMI_TOLERANCE,
    EXACT,
    DateInterval,
    Tolerance,
    compare_values,
    compute,
    glp1_canonical,
    normalize_value,
    parse_bracket,
    years_between,
)
from bridge_check.verify import CheckedEvidence

DOC_DATE_D1 = checked("doc_dates", target_doc_id="D1", date="2025-03-15", event_date="2025-03-15")


# --- dates -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("iso", "start", "end", "precision"),
    [
        ("2024", date(2024, 1, 1), date(2024, 12, 31), "year"),
        ("2024-02", date(2024, 2, 1), date(2024, 2, 29), "month"),
        ("2024-02-10", date(2024, 2, 10), date(2024, 2, 10), "day"),
    ],
)
def test_date_interval_parse(iso: str, start: date, end: date, precision: str) -> None:
    iv = DateInterval.parse(iso)
    assert iv == DateInterval(start, end, precision)
    assert iv.iso() == iso


def _iv(iso: str) -> DateInterval:
    iv = DateInterval.parse(iso)
    assert iv is not None
    return iv


def test_date_interval_relative_to_initiation() -> None:
    s = DateInterval.day(date(2025, 3, 15))
    assert _iv("2025-03-15").relative_to(s) == "at"
    assert _iv("2025-02-28").relative_to(s) == "before"
    assert _iv("2025-04-02").relative_to(s) == "after"
    assert _iv("2025-03").relative_to(s) == "unknown"  # T-03
    assert _iv("2025").relative_to(s) == "unknown"
    assert DateInterval.parse("not a date") is None


def test_years_between_counts_completed_years() -> None:
    assert years_between(date(1961, 4, 2), date(2025, 3, 15)) == 63
    assert years_between(date(1961, 4, 2), date(2025, 4, 2)) == 64


# --- timepoints (T-02, T-05, T-06) --------------------------------------------------------------


def test_t05_explicitly_dated_measurement_never_inherits_the_document_date() -> None:
    bmi = checked(
        "anthropometrics",
        kind="bmi",
        raw_value="36.5",
        event_date="2025-03-16",
        relative_llm="at",
    )
    facts = compute([INITIATION, DOC_DATE_D1, bmi], ctx(evidence_ids=[1, 2, 3]))
    (cand,) = facts.bmi_candidates
    assert cand.tp.relative == "after"
    assert cand.tp.source == "llm"
    update = next(u for u in facts.evidence_updates if u.evidence_id == 3)
    assert update.relative_computed == "after"
    assert update.event_date_source is None  # verify's `llm` stays
    assert update.event_date is None  # the column already holds the model's date
    assert "timing_disagreement" in update.flags


def test_quote_date_without_model_date_is_used_and_never_inherits() -> None:
    weight = checked(
        "anthropometrics",
        kind="weight",
        raw_value="98.0",
        raw_unit="kg",
        event_date_source="none",
        quote_date="2024-11",
        relative_llm="at",
    )
    facts = compute([INITIATION, DOC_DATE_D1, weight], ctx(evidence_ids=[1, 2, 3]))
    update = next(u for u in facts.evidence_updates if u.evidence_id == 3)
    assert update.relative_computed == "before"
    assert update.event_date_source is None
    assert "timing_disagreement" in update.flags
    assert facts.weights[0].src.tp.source == "quote"


def test_t05_undated_measurement_inherits_the_verified_document_date() -> None:
    bmi = checked("anthropometrics", kind="bmi", raw_value="36.5", relative_llm="at")
    facts = compute([INITIATION, DOC_DATE_D1, bmi], ctx(evidence_ids=[1, 2, 3]))
    (cand,) = facts.bmi_candidates
    assert cand.tp.relative == "at"
    assert cand.tp.source == "doc_date"
    assert cand.tp.source_evidence_id == 2
    update = next(u for u in facts.evidence_updates if u.evidence_id == 3)
    assert update.event_date_source == "doc_dates:2"
    assert update.event_date == "2025-03-15"
    assert update.date_precision == "day"
    assert "timing_disagreement" not in update.flags
    assert facts.doc_facts["D1"].doc_date == DateInterval.day(date(2025, 3, 15))
    assert facts.doc_facts["D1"].doc_date_evidence_id == 2


def test_excluded_doc_dates_row_dates_nothing() -> None:
    bad = checked(
        "doc_dates",
        target_doc_id="D1",
        date="2025-03-15",
        event_date="2025-03-15",
        exclusion_reasons=("claim_document",),
    )
    bmi = checked("anthropometrics", kind="bmi", raw_value="36.5", relative_llm="at")
    facts = compute([INITIATION, bad, bmi], ctx())
    assert facts.doc_facts["D1"].doc_date is None
    assert facts.bmi_candidates[0].tp.relative == "unknown"
    # the model's undated `at` is not trusted and not flagged (contract §5 item 2)
    assert "timing_disagreement" not in facts.evidence_updates[2].flags


def test_disagreeing_doc_dates_date_nothing() -> None:
    other = checked("doc_dates", target_doc_id="D1", date="2025-03-20", event_date="2025-03-20")
    facts = compute([INITIATION, DOC_DATE_D1, other], ctx(evidence_ids=[1, 2, 3]))
    assert facts.doc_facts["D1"].doc_date is None
    assert facts.doc_facts["D1"].doc_date_disagreement == (2, 3)


def test_model_unknown_is_not_a_disagreement_with_the_computed_timepoint() -> None:
    """Contract §5 item 1: the model's `unknown` states nothing, so it never contradicts."""
    bp = checked("bp_readings", sbp=152, dbp=94, event_date="2025-03-15", relative_llm="unknown")
    facts = compute([INITIATION, bp], ctx())
    assert facts.bp_readings[0].src.tp.relative == "at"
    assert facts.evidence_updates[1].relative_computed == "at"
    assert facts.evidence_updates[1].flags == ()


def test_model_definite_value_contradicting_the_computed_timepoint_is_flagged() -> None:
    bp = checked("bp_readings", sbp=152, dbp=94, event_date="2025-03-15", relative_llm="before")
    facts = compute([INITIATION, bp], ctx())
    assert facts.evidence_updates[1].relative_computed == "at"
    assert facts.evidence_updates[1].flags == ("timing_disagreement",)


def test_case01_undated_measurements_labelled_unknown_are_not_capped() -> None:
    """case-01: height, weight and BMI in an undated document whose date another document
    gives; the model labels all three `unknown`, compute derives `at` from the document date.
    No `timing_disagreement`, so the BMI decisions are not capped at `review` (§3.1 step 8)."""
    rows = [
        checked(
            "anthropometrics",
            doc_id="D2",
            kind="height",
            raw_value="167.6",
            raw_unit="cm",
            relative_llm="unknown",
        ),
        checked(
            "anthropometrics",
            doc_id="D2",
            kind="weight",
            raw_value="129.5",
            raw_unit="kg",
            relative_llm="unknown",
        ),
        checked(
            "anthropometrics",
            doc_id="D2",
            kind="bmi",
            raw_value="46",
            raw_unit="",
            relative_llm="unknown",
        ),
    ]
    doc_date_d2 = checked(
        "doc_dates", target_doc_id="D2", date="2025-03-15", event_date="2025-03-15"
    )
    evidence = [INITIATION, doc_date_d2, *rows]
    facts = compute(evidence, ctx(evidence_ids=[1, 2, 3, 4, 5]))
    for u in facts.evidence_updates[2:]:
        assert u.relative_computed == "at", u.evidence_id
        assert "timing_disagreement" not in u.flags, u.evidence_id
    decisions = decide(evidence)
    for cid in ("bmi_path_a", "bmi_path_b.bmi", "bmi_path_c.bmi"):
        assert decisions[cid].status == "supported", cid
        assert "timing_disagreement" not in decisions[cid].flags, cid
    assert decisions["bmi_path_a"].rule_id == "bmi_path_a:7"


def test_step0_drops_excluded_and_keeps_candidates_apart() -> None:
    excluded = checked(
        "anthropometrics", kind="bmi", raw_value="40", exclusion_reasons=("wrong_patient",)
    )
    cand = checked("anthropometrics", kind="bmi", raw_value="41", position_status="candidate")
    not_found = checked(
        "anthropometrics",
        kind="bmi",
        raw_value="42",
        position_status="not_found",
        assertion_check=None,
        exclusion_reasons=("quote_not_found",),
    )
    facts = compute([INITIATION, excluded, cand, not_found], ctx(evidence_ids=[1, 2, 3, 4]))
    assert facts.bmi_candidates == ()
    assert [s.evidence_id for s in facts.candidate_only] == [3]
    assert facts.evidence_updates[1].relative_computed is None
    assert facts.evidence_updates[3].relative_computed is None


# --- initiation ----------------------------------------------------------------------------------


def test_initiation_needs_the_target_course() -> None:
    other_drug = checked("glp1_start", drug="Zepbound", date="2025-03-15", event_date="2025-03-15")
    other_date = checked("glp1_start", drug="Wegovy", date="2024-01-10", event_date="2024-01-10")
    assert compute([other_drug, other_date], ctx()).initiation is None
    facts = compute([INITIATION], ctx())
    assert facts.initiation is not None
    assert facts.initiation_date == DateInterval.day(date(2025, 3, 15))
    assert facts.initiation_purpose == "weight"
    assert facts.case_flags == ()


def test_month_precision_start_containing_the_target_day_counts() -> None:
    start = checked("glp1_start", drug="Ozempic", date="2025-03", event_date="2025-03")
    facts = compute([start], ctx(target_drug="semaglutide"))
    assert facts.initiation is not None
    assert facts.initiation.date.precision == "month"


def test_mace_purpose_sets_the_case_flag() -> None:
    mace = checked(
        "glp1_start", drug="Wegovy", date="2025-03-15", event_date="2025-03-15", purpose="mace"
    )
    assert compute([mace], ctx()).case_flags == ("mace_purpose",)


def test_glp1_canonical_maps_brands() -> None:
    assert glp1_canonical("Wegovy") == glp1_canonical("semaglutide") == "semaglutide"
    assert glp1_canonical("Mounjaro") == "tirzepatide"
    assert glp1_canonical("Foundayo") == "foundayo"


# --- normalization --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "raw", "unit", "expected", "integer_only"),
    [
        ("weight", "240", "lb", Decimal("108.8621688"), False),
        ("weight", "98.0", "kg", Decimal("98.0"), False),
        ("height", "68", "in", Decimal("172.72"), False),
        ("height", "1.72", "m", Decimal("172.00"), False),
        ("bmi", "30", "", Decimal("30"), True),
        ("bmi", "30.0", "kg/m2", Decimal("30.0"), False),
        ("a1c", "6.1", "%", Decimal("6.1"), False),
        ("fpg", "1.1", "g/L", Decimal("110.0"), False),
        ("fpg", "7", "mmol/L", Decimal("126.112"), False),
        ("egfr", "48", "mL/min/1.73m2", Decimal("48"), True),
    ],
)
def test_normalize_value(
    kind: str, raw: str, unit: str, expected: Decimal, integer_only: bool
) -> None:
    assert normalize_value(kind, raw, unit) == (expected, integer_only)


@pytest.mark.parametrize(
    ("kind", "raw", "unit"), [("weight", "98", "stone"), ("a1c", ">7", "%"), ("bmi", "abc", "")]
)
def test_unparseable_values_are_excluded(kind: str, raw: str, unit: str) -> None:
    row = checked(
        "anthropometrics" if kind != "a1c" else "labs", kind=kind, raw_value=raw, raw_unit=unit
    )
    facts = compute([INITIATION, row], ctx())
    assert facts.evidence_updates[1].exclusion_reasons == ("unparseable_value",)
    assert facts.bmi_candidates == () and facts.a1c == () and facts.weights == ()


def test_bmi_percentile_is_never_a_bmi() -> None:
    row = checked(
        "anthropometrics", kind="bmi_percentile", raw_value="140", raw_unit="%", relative_llm="at"
    )
    facts = compute([INITIATION, DOC_DATE_D1, row], ctx())
    assert facts.bmi_candidates == ()
    assert facts.evidence_updates[2].norm_value is None


# --- BMI candidates (C-02, C-04)  -----------------------------------------------------------------


def test_bmi_candidates_computed_and_stated() -> None:
    rows = [
        INITIATION,
        DOC_DATE_D1,
        checked("anthropometrics", kind="height", raw_value="172.7", raw_unit="cm"),
        checked("anthropometrics", kind="weight", raw_value="240", raw_unit="lb"),
        checked("anthropometrics", kind="bmi", raw_value="36"),
    ]
    facts = compute(rows, ctx(evidence_ids=[1, 2, 3, 4, 5]))
    computed = next(c for c in facts.bmi_candidates if c.origin == "computed")
    stated = next(c for c in facts.bmi_candidates if c.origin == "stated")
    assert computed.value.quantize(Decimal("0.01")) == Decimal("36.50")
    assert computed.evidence_ids == (4, 3)
    assert computed.tp.relative == "at"
    assert computed.flags == ()
    assert stated.integer_only and stated.value == Decimal("36")
    assert facts.bmi_bracket is not None and facts.bmi_bracket.label() == "[35,40)"


def test_height_from_another_date_is_flagged() -> None:
    rows = [
        INITIATION,
        DOC_DATE_D1,
        checked(
            "anthropometrics",
            kind="height",
            raw_value="170",
            raw_unit="cm",
            event_date="2023-01-10",
        ),
        checked("anthropometrics", kind="weight", raw_value="98", raw_unit="kg"),
    ]
    facts = compute(rows, ctx())
    (cand,) = facts.bmi_candidates
    assert cand.flags == ("height_from_other_date",)
    assert cand.tp.relative == "at"
    assert facts.evidence_updates[2].relative_computed == "before"


def test_bmi_bracket_is_ambiguous_when_candidates_straddle_an_edge() -> None:
    rows = [
        INITIATION,
        DOC_DATE_D1,
        checked("anthropometrics", kind="bmi", raw_value="29.9"),
        checked("anthropometrics", kind="bmi", raw_value="30.1"),
    ]
    facts = compute(rows, ctx())
    assert facts.bmi_bracket is None and facts.bmi_bracket_ambiguous


# --- age (C-01, contract §3.5)  -------------------------------------------------------------------


def test_stated_age_is_an_interval_shifted_to_initiation() -> None:
    # 79 in a note dated 2023-05-10, initiation 2021-05-10 → [77, 78) (guide C-01)
    start = checked("glp1_start", drug="Wegovy", date="2021-05-10", event_date="2021-05-10")
    age = checked("patient_identity", stated_age=79, event_date="2023-05-10")
    facts = compute([start, age], ctx(target_start=date(2021, 5, 10)))
    (iv,) = facts.age_interval_at_initiation
    assert (iv.lo_years, iv.hi_years, iv.origin) == (77, 77, "stated_age")


def test_dob_gives_the_exact_age_and_a_stated_age_its_interval() -> None:
    rows = [
        INITIATION,
        DOC_DATE_D1,
        checked("patient_identity", dob="1961-04-02", patient_id="P-1"),
        checked("patient_identity", stated_age=55),
    ]
    facts = compute(rows, ctx())
    by_origin = {a.origin: a for a in facts.age_interval_at_initiation}
    assert (by_origin["dob"].lo_years, by_origin["dob"].hi_years) == (63, 63)
    assert (by_origin["stated_age"].lo_years, by_origin["stated_age"].hi_years) == (55, 55)


def test_stated_age_without_a_date_gives_no_interval() -> None:
    facts = compute([INITIATION, checked("patient_identity", stated_age=55)], ctx())
    assert facts.age_interval_at_initiation == ()


def test_dob_bound_as_quote_date_is_not_the_identity_rows_date() -> None:
    row = checked("patient_identity", dob="1961-04-02", patient_id="P-1", quote_date="1961-04-02")
    facts = compute([INITIATION, DOC_DATE_D1, row], ctx())
    assert facts.age_interval_at_initiation[0].src.tp.source == "doc_date"


# --- medication periods (T-09)  -------------------------------------------------------------------


def _bp_and_list(
    *names: str, complete: bool = False, start: str | None = None
) -> list[CheckedEvidence]:
    rows = [
        INITIATION,
        DOC_DATE_D1,
        checked("bp_readings", sbp=152, dbp=94, event_date="2025-03-15"),
        checked("medication_lists", list_id="L1", complete=complete),
    ]
    for n in names:
        rows.append(
            checked(
                "medications",
                name=n,
                list_id="L1",
                end_kind="ongoing",
                start=start,
                start_precision="month" if start else None,
            )
        )
    return rows


def test_same_note_list_is_in_use_on_the_reading_date() -> None:
    facts = compute(_bp_and_list("amlodipine 5 mg", "Lopressor"), ctx())
    day = DateInterval.day(date(2025, 3, 15))
    ov = facts.distinct_antihypertensives_overlapping(day)
    assert {p.drug_canonical for p in ov.unambiguous} == {"amlodipine", "metoprolol"}
    assert all(p.same_note_list for p in ov.unambiguous)
    assert ov.products() == 2 and ov.agents() == 2
    assert "same_note_list" in facts.evidence_updates[4].flags


def test_unknown_drug_is_not_an_antihypertensive() -> None:
    facts = compute(_bp_and_list("lisinopril", "amlodipine"), ctx())
    ov = facts.distinct_antihypertensives_overlapping(DateInterval.day(date(2025, 3, 15)))
    assert ov.products() == 1
    unknown = next(p for p in facts.med_periods if p.drug_canonical == "lisinopril")
    assert not unknown.recognized and unknown.class_ is None


def test_class_ambiguous_and_combination_components() -> None:
    facts = compute(_bp_and_list("Moduretic", "Lasix"), ctx())
    ov = facts.distinct_antihypertensives_overlapping(DateInterval.day(date(2025, 3, 15)))
    assert ov.unambiguous == ()
    assert {p.drug_canonical for p in ov.ambiguous} == {
        "amiloride/hydrochlorothiazide",
        "furosemide",
    }
    combo = next(p for p in ov.ambiguous if p.components)
    assert combo.agents == ("amiloride", "hydrochlorothiazide")


def test_period_without_certain_overlap_is_unknown() -> None:
    # started in a known month but no date links it to the reading day
    rows = [
        INITIATION,
        checked("bp_readings", sbp=152, dbp=94, event_date="2025-03-15"),
        checked(
            "medications",
            name="amlodipine",
            start="2025-03",
            start_precision="month",
            end_kind="unknown",
        ),
        checked(
            "medications",
            name="metoprolol",
            start="2024-01",
            start_precision="month",
            end_kind="ended",
            end="2025-01",
            end_precision="month",
        ),
    ]
    facts = compute(rows, ctx())
    ov = facts.distinct_antihypertensives_overlapping(DateInterval.day(date(2025, 3, 15)))
    assert ov.unambiguous == () and len(ov.period_unknown) == 2


def test_dated_start_and_end_bound_the_period() -> None:
    rows = [
        INITIATION,
        checked(
            "medications",
            name="amlodipine",
            start="2024-01",
            start_precision="month",
            end="2025-06",
            end_precision="month",
            end_kind="ended",
        ),
    ]
    facts = compute(rows, ctx())
    (p,) = facts.med_periods
    assert p.overlaps(DateInterval.day(date(2025, 3, 15)))
    assert not p.overlaps(DateInterval.day(date(2024, 1, 15)))  # a January start is uncertain
    assert not p.overlaps(DateInterval.day(date(2025, 6, 10)))


def test_complete_list_is_recorded() -> None:
    facts = compute(_bp_and_list("amlodipine", complete=True), ctx())
    ov = facts.distinct_antihypertensives_overlapping(
        DateInterval.day(date(2025, 3, 15)), doc_id="D1"
    )
    assert len(ov.complete_lists) == 1


# --- labs, dx, lifestyle, claims -----------------------------------------------------------------


def test_labs_are_normalized_decimals() -> None:
    rows = [
        checked("labs", kind="a1c", raw_value="6.1", raw_unit="%"),
        checked("labs", kind="fpg", raw_value="5.6", raw_unit="mmol/L"),
    ]
    facts = compute(rows, ctx())
    assert facts.a1c[0].value == Decimal("6.1")
    assert facts.fpg_mg_dl[0].value == Decimal("100.8896")
    assert facts.evidence_updates[1].norm_unit == "mg/dL"


def test_lifestyle_applicability_against_the_assessment_date() -> None:
    rows = [
        checked("lifestyle", program_type="commercial", end_kind="ended", temporality="historical"),
        checked(
            "lifestyle", program_type="structured_clinical", start="2026-12", end_kind="ongoing"
        ),
        checked(
            "lifestyle", program_type="structured_clinical", start="2026-01", end_kind="unknown"
        ),
        checked("lifestyle", program_type="structured_clinical", end_kind="ongoing"),
        checked("lifestyle", program_type="none_stated", end_kind="unknown"),
        checked(
            "lifestyle",
            program_type="structured_clinical",
            end_kind="ongoing",
            event_date="2026-09-01",
        ),
    ]
    facts = compute(rows, ctx())
    # an undated record, ongoing or not, never proves coverage of the assessment date
    assert [r.applicable for r in facts.lifestyle_applicable] == [
        False,
        False,
        True,
        False,
        False,
        True,
    ]


def test_claims_and_bracket_parsing() -> None:
    row = checked(
        "pa_form_claims", claim_id="claim.bmi_bracket", claimed_value="30-34.9", doc_id="D0"
    )
    facts = compute([row], ctx(doc_roles={"D0": "pa_draft"}, doc_identity={"D0": "match"}))
    assert facts.claims[0].claimed_value == "30-34.9"
    b = parse_bracket("30-34.9")
    assert b is not None and (b.lo, b.hi) == (Decimal("30"), Decimal("35.0"))
    assert (
        parse_bracket("<27") is not None
        and parse_bracket("≥40") is not None
        and parse_bracket("35+") is not None
    )
    assert parse_bracket("yes") is None


# --- comparison helper (contract §4) --------------------------------------------------------------


def test_compare_values_threshold_first_then_tolerance() -> None:
    thirty = Decimal("30")
    both_sides = compare_values([Decimal("29.9"), Decimal("30.1")], [thirty], BMI_TOLERANCE)
    assert both_sides.straddled == {thirty} and not both_sides.inconsistent
    same_side = compare_values(
        [Decimal("34.6"), Decimal("36")], [thirty, Decimal("35")], BMI_TOLERANCE
    )
    assert same_side.straddled == {Decimal("35")} and same_side.inconsistent
    equal = compare_values([Decimal("30"), Decimal("30.1")], [thirty], BMI_TOLERANCE)
    assert equal.straddled == frozenset()  # 30 is on the upper side of >= 30
    assert compare_values([Decimal("6.1"), Decimal("6.1")], [], EXACT).inconsistent is False
    assert (
        compare_values(
            [Decimal("100"), Decimal("100.5")], [], Tolerance(rel=Decimal("0.01"))
        ).inconsistent
        is False
    )
    assert (
        compare_values(
            [Decimal("100"), Decimal("102")], [], Tolerance(rel=Decimal("0.01"))
        ).inconsistent
        is True
    )


# --- review items: family facts, anchored dates, purpose order, same-note anchoring -----------


def test_family_measurements_never_become_patient_facts() -> None:
    rows = [
        INITIATION,
        DOC_DATE_D1,
        checked("anthropometrics", kind="bmi", raw_value="36.5", subject="family"),
        checked("bp_readings", sbp=152, dbp=94, subject="family"),
        checked("labs", kind="a1c", raw_value="6.0", raw_unit="%", certainty="negated"),
        checked("medications", name="amlodipine", end_kind="ongoing", temporality="hypothetical"),
    ]
    facts = compute(rows, ctx())
    assert facts.bmi_candidates == () and facts.bp_readings == ()
    assert facts.a1c == () and facts.med_periods == ()


def test_unrecognized_start_or_date_row_anchors_nothing() -> None:
    start = checked(
        "glp1_start",
        drug="Wegovy",
        date="2025-03-15",
        event_date="2025-03-15",
        flags=("unrecognized",),
    )
    doc_date = checked(
        "doc_dates",
        target_doc_id="D1",
        date="2025-03-15",
        event_date="2025-03-15",
        flags=("unrecognized",),
    )
    bmi = checked("anthropometrics", kind="bmi", raw_value="36.5")
    facts = compute([start, doc_date, bmi], ctx())
    assert facts.initiation is None
    assert facts.doc_facts["D1"].doc_date is None
    assert facts.bmi_candidates[0].tp.relative == "unknown"


@pytest.mark.parametrize("temporality", ["current", "historical", "resolved"])
def test_event_rows_anchor_whatever_their_temporality(temporality: str) -> None:
    # Contract §5: for glp1_start, prior_glp1 and doc_dates the temporality axis is recorded
    # (`temporality_unverified`) and never blocks anchoring or date use.
    flags = () if temporality == "current" else ("temporality_unverified",)
    start = checked(
        "glp1_start",
        drug="Wegovy",
        date="2025-03-15",
        event_date="2025-03-15",
        temporality=temporality,
        flags=flags,
    )
    doc_date = checked(
        "doc_dates",
        target_doc_id="D1",
        date="2025-03-15",
        event_date="2025-03-15",
        temporality=temporality,
        flags=flags,
    )
    facts = compute([start, doc_date], ctx())
    assert facts.initiation is not None
    assert facts.initiation_date == DateInterval.day(date(2025, 3, 15))
    assert facts.doc_facts["D1"].doc_date is not None


@pytest.mark.parametrize(
    ("certainty", "subject", "temporality"),
    [
        ("negated", "patient", "current"),
        ("uncertain", "patient", "current"),
        ("present", "family", "current"),
        ("present", "other", "current"),
        ("present", "patient", "hypothetical"),
    ],
    ids=["negated", "uncertain", "family", "other", "hypothetical"],
)
def test_event_rows_still_need_present_patient_actual_assertion(
    certainty: str, subject: str, temporality: str
) -> None:
    start = checked(
        "glp1_start",
        drug="Wegovy",
        date="2025-03-15",
        event_date="2025-03-15",
        certainty=certainty,
        subject=subject,
        temporality=temporality,
    )
    doc_date = checked(
        "doc_dates",
        target_doc_id="D1",
        date="2025-03-15",
        event_date="2025-03-15",
        certainty=certainty,
        subject=subject,
        temporality=temporality,
    )
    facts = compute([start, doc_date], ctx())
    assert facts.initiation is None
    assert facts.doc_facts["D1"].doc_date is None


def test_historical_start_whose_date_is_not_in_the_quote_anchors_nothing() -> None:
    # Contract §3.1 invariant: the start day must be bound inside the verified quote.
    start = checked(
        "glp1_start",
        drug="Wegovy",
        date="2025-03-15",
        event_date="2025-03-15",
        temporality="historical",
        exclusion_reasons=("value_not_in_quote",),
        flags=("temporality_unverified",),
    )
    assert compute([start], ctx()).initiation is None


@pytest.mark.parametrize("mace_first", [True, False])
def test_mace_purpose_is_resolved_across_matching_starts(mace_first: bool) -> None:
    weight = checked("glp1_start", drug="Wegovy", date="2025-03-15", event_date="2025-03-15")
    mace = checked(
        "glp1_start", drug="Wegovy", date="2025-03-15", event_date="2025-03-15", purpose="mace"
    )
    rows = [mace, weight] if mace_first else [weight, mace]
    facts = compute(rows, ctx(evidence_ids=[1, 2]))
    assert facts.case_flags == ("mace_purpose",)
    assert facts.initiation is not None and facts.initiation.src.evidence_id == 1


def test_same_note_list_uses_the_note_date_not_a_quoted_reading_date() -> None:
    # an April note quotes a March reading: its current list is in use in April only
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
            "medications", name="metoprolol", list_id="L1", end_kind="ended", relative_llm="after"
        ),
    ]
    facts = compute(rows, ctx())
    ov = facts.distinct_antihypertensives_overlapping(DateInterval.day(date(2025, 3, 15)))
    assert ov.unambiguous == () and len(ov.period_unknown) == 2
    ended = next(p for p in facts.med_periods if p.drug_canonical == "metoprolol")
    assert ended.in_use_on == () and not ended.same_note_list


def test_lifestyle_recorded_after_the_assessment_date_does_not_apply() -> None:
    row = checked(
        "lifestyle",
        kind="nutrition",
        program_type="structured_clinical",
        end_kind="ongoing",
        event_date="2027-01-10",
        relative_llm="after",
    )
    facts = compute([row], ctx())
    assert facts.lifestyle_applicable[0].applicable is False


# --- fourth review round ------------------------------------------------------------------------


def test_start_sentence_has_its_own_timepoint_and_timing_flag() -> None:
    # the start sentence carries its verified date value but no generic event date
    start = checked("glp1_start", drug="Wegovy", date="2025-03-15", relative_llm="before")
    facts = compute(
        [start, DOC_DATE_D1, checked("anthropometrics", kind="bmi", raw_value="36.5")], ctx()
    )
    assert facts.initiation is not None
    assert facts.initiation.src.tp.relative == "at"
    assert "timing_disagreement" in facts.initiation.src.flags


def test_explicitly_dated_list_keeps_its_own_date() -> None:
    rows = [
        INITIATION,
        DOC_DATE_D1,
        checked("bp_readings", sbp=152, dbp=94, event_date="2025-03-15"),
        checked("medication_lists", list_id="L1", event_date="2025-03-01", relative_llm="before"),
        checked("medications", name="amlodipine", list_id="L1", end_kind="ongoing"),
        checked("medications", name="metoprolol", list_id="L1", end_kind="ongoing"),
    ]
    facts = compute(rows, ctx())
    assert all(p.in_use_on == (DateInterval.day(date(2025, 3, 1)),) for p in facts.med_periods)
    ov = facts.distinct_antihypertensives_overlapping(DateInterval.day(date(2025, 3, 15)))
    assert ov.unambiguous == () and len(ov.period_unknown) == 2


def test_undated_ongoing_program_does_not_apply() -> None:
    row = checked(
        "lifestyle", kind="nutrition", program_type="structured_clinical", end_kind="ongoing"
    )
    assert compute([row], ctx()).lifestyle_applicable[0].applicable is False
