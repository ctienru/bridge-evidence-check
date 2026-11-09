"""Review regressions: tokens read whole, values bound to their fact, identity read from the
text, cues matched on normalized text, and A-09 limited to negations confined to a treatment.

Each case was a verified support before the fix; each must now be excluded, unrecognized or
a mismatch.
"""

from __future__ import annotations

import pytest
from conftest import fact, run_verify

from bridge_check.verify import UNRESOLVED_DOC, CheckedEvidence, VerifyResult


def _ev(doc: str, fact_field: str, quote: str | None = None, **fields: object) -> CheckedEvidence:
    return run_verify(
        {"D1": doc}, {fact_field: [fact(fact_field, quote or doc, **fields)]}
    ).evidence[0]


def _identity(doc: str, **fields: object) -> tuple[CheckedEvidence, str]:
    quote = str(fields.pop("quote", doc.strip()))
    result: VerifyResult = run_verify(
        {"D1": doc}, {"patient_identity": [fact("patient_identity", quote, **fields)]}
    )
    return result.evidence[0], result.doc_facts[0].identity_status


# --- Unresolved document ids stay out of public refs -------------------------------------------


def test_unknown_doc_id_is_replaced_in_the_ref() -> None:
    ev = run_verify(
        {"D1": "x"}, {"diagnoses": [fact("diagnoses", "x", doc_id="ChartToken-42")]}
    ).evidence[0]
    assert ev.position_status == "not_found"
    assert ev.ref.startswith(f"{UNRESOLVED_DOC}[-:-] ")
    assert "ChartToken" not in ev.ref
    assert ev.attributes["doc_unresolved"] is True


# --- Identity: complete identifier under its own label; each identifier on its own ---------


def test_payer_label_does_not_change_the_mrn_type() -> None:
    ev, status = _identity("Insurance: Medicare\nMRN: P-0002\n", patient_id="P-0002")
    assert status == "mismatch"
    assert "wrong_patient" in ev.exclusion_reasons


def test_identifier_is_read_in_full_not_as_a_prefix() -> None:
    ev, status = _identity("MRN: P-0001-A\n", quote="MRN: P-0001", patient_id="P-0001")
    assert status != "match"
    assert "value_not_in_quote" in ev.exclusion_reasons
    # The whole quote names the other identifier: a mismatch.
    _, status = _identity("MRN: P-0001-A\n", patient_id="P-0001-A")
    assert status == "mismatch"


def test_explicit_label_wins_over_the_mbi_shape() -> None:
    # An MBI-shaped value under an MRN label is compared as a local id.
    _, status = _identity("MRN: 1EG4TE5MK73\n", patient_id="1EG4TE5MK73")
    assert status == "mismatch"


def test_identifier_mismatch_survives_a_failed_dob_on_the_same_fact() -> None:
    ev, status = _identity("MRN: P-0002\n", patient_id="P-0002", dob="1960-01-01")
    assert status == "mismatch"
    assert ev.exclusion_reasons == ("value_not_in_quote", "wrong_patient")


def test_negated_identifier_cannot_establish_a_match() -> None:
    _, status = _identity("Not MRN P-0001.\n", patient_id="P-0001", certainty="negated")
    assert status == "missing"


def test_dob_is_read_from_its_label() -> None:
    _, status = _identity("Visit 1960-01-01. DOB 1958-06-01.\n", dob="1960-01-01")
    assert status == "mismatch"  # the DOB in the text is 1958-06-01


# --- Tokens are read whole, against the source document ------------------------------------


def test_clipped_comparator_is_not_an_exact_value() -> None:
    ev = _ev(
        "BMI <35.1 kg/m² today.",
        "anthropometrics",
        "35.1 kg/m²",
        raw_value="35.1",
        raw_unit="kg/m²",
    )
    assert ev.position_status == "verbatim"
    assert "value_not_in_quote" in ev.exclusion_reasons


def test_part_of_a_word_is_not_a_concept_mention() -> None:
    ev = _ev(
        "History of heatstroke.", "diagnoses", "stroke", concept="stroke", temporality="historical"
    )
    assert "value_not_in_quote" in ev.exclusion_reasons


# --- Values bound to the fact they describe -------------------------------------------------


@pytest.mark.parametrize(
    ("doc", "raw_value", "raw_unit", "excluded"),
    [
        ("BMI 30 and age 35.", "35", "", True),
        ("BMI 30 and age 35.", "30", "", False),
        ("Age 35, BMI 30.", "35", "", True),
        ("BMI 35 kg/m2.", "35", "kg/m2", False),
        ("Weight 98 kg, BMI 35.", "98", "", True),  # label says weight, fact says BMI
    ],
)
def test_number_belongs_to_its_label(
    doc: str, raw_value: str, raw_unit: str, excluded: bool
) -> None:
    ev = _ev(doc, "anthropometrics", kind="bmi", raw_value=raw_value, raw_unit=raw_unit)
    assert ("value_not_in_quote" in ev.exclusion_reasons) is excluded


@pytest.mark.parametrize(
    ("doc", "stage", "excluded"),
    [
        ("CKD stage 2. Fibrosis stage 4.", "4", True),
        ("CKD stage 2, fibrosis stage 4.", "4", True),
        ("CKD stage 3a.", "3a", False),
        ("Stage 3b chronic kidney disease.", "3b", False),
    ],
)
def test_stage_belongs_to_its_diagnosis(doc: str, stage: str, excluded: bool) -> None:
    ev = _ev(doc, "diagnoses", concept="ckd", ckd_stage=stage)
    assert ("value_not_in_quote" in ev.exclusion_reasons) is excluded


def test_severity_belongs_to_its_diagnosis() -> None:
    assert (
        _ev(
            "Moderate-to-severe OSA.", "diagnoses", concept="osa", osa_severity="severe"
        ).exclusion_reasons
        == ()
    )
    ev = _ev("Mild OSA and severe asthma.", "diagnoses", concept="osa", osa_severity="severe")
    assert "value_not_in_quote" in ev.exclusion_reasons


@pytest.mark.parametrize(
    ("doc", "drug", "date", "excluded"),
    [
        ("Started metformin on 2025-01-02 and Wegovy on 2025-03-15.", "Wegovy", "2025-01-02", True),
        # The shared start verb is cut off by the first date: not excluded, but
        # `unrecognized` (asserted in test_shared_start_verb_behind_another_date_is_unrecognized).
        (
            "Started metformin on 2025-01-02 and Wegovy on 2025-03-15.",
            "Wegovy",
            "2025-03-15",
            False,
        ),
        ("Semaglutide (Wegovy) was started on 2025-03-15.", "Semaglutide", "2025-03-15", False),
        ("On 2025-03-15 she started Wegovy.", "Wegovy", "2025-03-15", False),
        ("Metformin since 2020; Wegovy started 2025.", "Wegovy", "2020", True),
    ],
)
def test_start_date_belongs_to_its_drug(doc: str, drug: str, date: str, excluded: bool) -> None:
    ev = _ev(doc, "glp1_start", drug=drug, date=date)
    assert ("value_not_in_quote" in ev.exclusion_reasons) is excluded


# --- Event dates ---------------------------------------------------------------------------


def test_event_date_must_match_the_date_in_the_quote() -> None:
    ev = _ev(
        "BMI 36.5 measured 2025-03-16.",
        "anthropometrics",
        raw_value="36.5",
        event_date="2025-03-15",
        date_precision="day",
    )
    assert "value_not_in_quote" in ev.exclusion_reasons
    ok = _ev(
        "BMI 36.5 measured 2025-03-15.",
        "anthropometrics",
        raw_value="36.5",
        event_date="2025-03-15",
        date_precision="day",
    )
    assert ok.exclusion_reasons == () and ok.event_date_source == "llm"


def test_undated_quote_leaves_the_event_date_to_the_document_date_path() -> None:
    ev = _ev(
        "BMI 36.5 today.",
        "anthropometrics",
        raw_value="36.5",
        event_date="2025-03-15",
        date_precision="day",
    )
    assert ev.exclusion_reasons == ()
    assert ev.event_date_source == "none"


# --- PAD symptoms and MASH cirrhosis qualifiers ---------------------------------------------


@pytest.mark.parametrize(
    ("doc", "symptomatic", "excluded"),
    [
        ("PAD is asymptomatic.", "yes", True),
        ("PAD is asymptomatic.", "no", False),
        ("PAD with claudication.", "yes", False),
        ("PAD; denies claudication.", "yes", True),
        ("PAD, denies claudication.", "no", False),
        ("PAD noted.", "yes", True),
    ],
)
def test_pad_symptom_qualifier_needs_text(doc: str, symptomatic: str, excluded: bool) -> None:
    ev = _ev(doc, "diagnoses", concept="pad", symptomatic=symptomatic)
    assert ("value_not_in_quote" in ev.exclusion_reasons) is excluded


def test_cirrhosis_qualifier_needs_text() -> None:
    assert (
        _ev(
            "Non-cirrhotic MASH, F2.",
            "diagnoses",
            concept="mash",
            fibrosis_stage="F2",
            cirrhosis=False,
        ).exclusion_reasons
        == ()
    )
    ev = _ev("MASH, F2.", "diagnoses", concept="mash", fibrosis_stage="F2", cirrhosis=False)
    assert "value_not_in_quote" in ev.exclusion_reasons


# --- Cues on normalized text -----------------------------------------------------------------


def test_right_hand_pattern_broken_across_lines() -> None:
    ev = _ev("HFpEF was ruled\nout.", "diagnoses", concept="hfpef")
    assert ev.assertion_check == "mismatch"
    assert ev.certainty_checked == "negated"


def test_full_width_negation_cue() -> None:
    ev = _ev(
        "Ｎｏ history of stroke.",
        "diagnoses",
        "No history of stroke.",
        concept="stroke",
        temporality="historical",
    )
    assert ev.position_status == "normalized"
    assert ev.assertion_check == "mismatch"
    assert ev.certainty_checked == "negated"


# --- A-09 only when the negation is confined to the treatment ---------------------------------


@pytest.mark.parametrize(
    "doc",
    [
        "No insulin use or history of stroke.",
        "No CPAP, and prior stroke.",
        "Not on insulin nor stroke.",
    ],
)
def test_coordinated_diagnosis_after_a_negated_treatment_is_unrecognized(doc: str) -> None:
    ev = _ev(
        doc,
        "diagnoses",
        concept="stroke",
        temporality="historical" if "prior" in doc or "history" in doc else "current",
    )
    assert ev.assertion_check == "unrecognized"
    assert ev.certainty_checked is None


# --- Second review round ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("doc", "excluded", "unrecognized"),
    [
        ("Wegovy was not started on 2025-03-15.", True, False),
        ("Wegovy was restarted on 2025-03-15.", True, False),
        ("Wegovy was stopped on 2025-03-15.", True, False),
        ("Semaglutide (Wegovy) was started on 2025-03-15 for weight.", False, False),
        ("Wegovy since 2025-03-15.", False, False),
        ("Wegovy 2025-03-15.", False, True),  # no event word: the date's meaning is unknown
    ],
)
def test_initiation_date_needs_a_non_negated_start_word(
    doc: str, excluded: bool, unrecognized: bool
) -> None:
    ev = _ev(doc, "glp1_start", drug="Wegovy", date="2025-03-15")
    assert ("value_not_in_quote" in ev.exclusion_reasons) is excluded
    assert ("unrecognized" in ev.flags) is unrecognized


def test_medication_stop_date_is_not_a_start_date() -> None:
    doc = "Amlodipine stopped 2025-03-15."
    start = _ev(
        doc,
        "medications",
        name="amlodipine",
        start="2025-03-15",
        start_precision="day",
        end_kind="ongoing",
    )
    assert "value_not_in_quote" in start.exclusion_reasons
    end = _ev(
        doc,
        "medications",
        name="amlodipine",
        end="2025-03-15",
        end_precision="day",
        end_kind="ended",
    )
    assert end.exclusion_reasons == ()


def test_event_date_belongs_to_the_selected_measurement() -> None:
    doc = "BMI 29 on 2025-03-15, BMI 36.5 on 2025-03-16."
    wrong = _ev(
        doc, "anthropometrics", raw_value="36.5", event_date="2025-03-15", date_precision="day"
    )
    assert "value_not_in_quote" in wrong.exclusion_reasons and wrong.event_date_source == "none"
    right = _ev(
        doc, "anthropometrics", raw_value="36.5", event_date="2025-03-16", date_precision="day"
    )
    assert right.exclusion_reasons == () and right.event_date_source == "llm"


def test_doc_date_quote_must_name_the_target_document() -> None:
    docs: dict[str, str | tuple[str, str]] = {
        "D1": "The attached D3 consult is dated 2025-03-15.",
        "D2": "x",
        "D3": "y",
    }
    quote = "The attached D3 consult is dated 2025-03-15."
    f = fact("doc_dates", quote, target_doc_id="D2", date="2025-03-15")
    ev = run_verify(docs, {"doc_dates": [f]}).evidence[0]
    assert "value_not_in_quote" in ev.exclusion_reasons  # it names D3
    f = fact("doc_dates", quote, target_doc_id="D3", date="2025-03-15")
    assert run_verify(docs, {"doc_dates": [f]}).evidence[0].exclusion_reasons == ()
    docs = {"D1": "Dated 2025-03-15.", "D2": "x"}
    f = fact("doc_dates", "Dated 2025-03-15.", target_doc_id="D2", date="2025-03-15")
    ev = run_verify(docs, {"doc_dates": [f]}).evidence[0]
    assert ev.exclusion_reasons == () and "unrecognized" in ev.flags  # names nothing
    docs = {"D1": ("referral", "The attached consult is dated 2025-03-15."), "D2": "x"}
    f = fact(
        "doc_dates",
        "The attached consult is dated 2025-03-15.",
        target_doc_id="D2",
        date="2025-03-15",
    )
    assert run_verify(docs, {"doc_dates": [f]}).evidence[0].flags == ()  # role word, one doc
    # Two clinical documents: "the attached consult" does not resolve to one target.
    docs["D3"] = "y"
    assert "unrecognized" in run_verify(docs, {"doc_dates": [f]}).evidence[0].flags


def test_identifier_with_underscore_suffix_is_read_whole() -> None:
    _, status = _identity("MRN: P-0001_A\n", patient_id="P-0001")
    assert status == "mismatch"


def test_clipped_identity_quote_still_screens_on_the_full_source_id() -> None:
    doc = "MRN: P-0001-A\nHistory of stroke.\n"
    result = run_verify(
        {"D1": doc},
        {
            "patient_identity": [fact("patient_identity", "MRN: P-0001", patient_id="P-0001")],
            "diagnoses": [
                fact("diagnoses", "History of stroke.", concept="stroke", temporality="historical")
            ],
        },
    )
    assert result.doc_facts[0].identity_status == "mismatch"
    assert "wrong_patient" in result.evidence[1].exclusion_reasons


def test_each_identifier_has_its_own_subject() -> None:
    doc = "MRN: P-0002. Mother has MRN: P-0001.\nHistory of stroke.\n"
    result = run_verify(
        {"D1": doc},
        {
            "patient_identity": [
                fact("patient_identity", doc.split("\n")[0], patient_id="P-0001", subject="family")
            ],
            "diagnoses": [
                fact("diagnoses", "History of stroke.", concept="stroke", temporality="historical")
            ],
        },
    )
    assert result.doc_facts[0].identity_status == "mismatch"  # the patient's own MRN differs
    assert "wrong_patient" in result.evidence[1].exclusion_reasons


@pytest.mark.parametrize(
    ("doc", "kind", "raw_value", "raw_unit", "excluded"),
    [
        ("BMI 36th percentile.", "bmi", "36", "", True),
        ("BMI 36th percentile.", "bmi_percentile", "36", "", False),
        ("BMI 28–36.5 kg/m².", "bmi", "36.5", "kg/m²", True),
        ("BMI 28-36.5 kg/m2.", "bmi", "28", "", True),
        ("BMI 36.5 kg/m².", "bmi", "36.5", "kg/m²", False),
    ],
)
def test_percentiles_and_ranges_are_not_absolute_values(
    doc: str, kind: str, raw_value: str, raw_unit: str, excluded: bool
) -> None:
    ev = _ev(doc, "anthropometrics", kind=kind, raw_value=raw_value, raw_unit=raw_unit)
    assert ("value_not_in_quote" in ev.exclusion_reasons) is excluded


def test_bp_behind_a_comparator_is_not_a_reading() -> None:
    assert (
        "value_not_in_quote" in _ev("BP <145/98.", "bp_readings", sbp=145, dbp=98).exclusion_reasons
    )
    assert _ev("BP 145/98.", "bp_readings", sbp=145, dbp=98).exclusion_reasons == ()


def test_pad_symptom_must_be_the_patients_own_in_the_same_clause() -> None:
    ev = _ev(
        "Patient has PAD, but mother has claudication.",
        "diagnoses",
        concept="pad",
        symptomatic="yes",
    )
    assert "value_not_in_quote" in ev.exclusion_reasons
    ev = _ev(
        "PAD with claudication; mother had a stroke.", "diagnoses", concept="pad", symptomatic="yes"
    )
    assert ev.exclusion_reasons == ()


def test_heading_cue_governs_the_entries_under_it() -> None:
    ev = _ev("Family history:\nStroke: yes.\n", "diagnoses", "Stroke: yes.", concept="stroke")
    assert ev.assertion_check == "mismatch" and ev.subject_checked == "family"
    ok = _ev(
        "Family history:\nStroke: yes.\n",
        "diagnoses",
        "Stroke: yes.",
        concept="stroke",
        subject="family",
    )
    assert ok.assertion_check == "matched"
    # A form title that is not a heading (no trailing colon) still does not reach the fields.
    form = "PRIOR AUTHORIZATION REQUEST\nPatient ID: P-0001\nDrug requested: Wegovy\n"
    f = fact(
        "pa_form_claims", "Drug requested: Wegovy", claim_id="claim.drug", claimed_value="Wegovy"
    )
    assert (
        run_verify({"D1": ("pa_draft", form)}, {"pa_form_claims": [f]}).evidence[0].assertion_check
        == "matched"
    )


def test_a09_needs_the_treatment_as_the_object_of_the_negation() -> None:
    ev = _ev(
        "No prior treatment-related stroke.",
        "diagnoses",
        concept="stroke",
        certainty="negated",
        temporality="historical",
    )
    assert ev.assertion_check == "matched" and ev.certainty_checked == "negated"
    ev = _ev("Not on insulin for diabetes.", "diagnoses", concept="t2dm")
    assert ev.assertion_check == "matched" and ev.certainty_checked == "present"


def test_lifestyle_values_need_cues() -> None:
    ev = _ev(
        "Counseled on healthy eating.",
        "lifestyle",
        kind="nutrition",
        program_type="structured_clinical",
        attendance="regular",
        start="2025-01-01",
        end_kind="ongoing",
    )
    assert "unrecognized" in ev.flags
    assert "value_not_in_quote" in ev.exclusion_reasons  # the start date is not in the quote
    advice = _ev(
        "Counseled on healthy eating.", "lifestyle", kind="nutrition", program_type="advice_only"
    )
    assert advice.flags == () and advice.exclusion_reasons == ()
    full = _ev(
        "Sees a dietitian weekly since 2025-01-01, ongoing.",
        "lifestyle",
        kind="nutrition",
        program_type="structured_clinical",
        attendance="regular",
        start="2025-01-01",
        end_kind="ongoing",
    )
    assert full.flags == () and full.exclusion_reasons == ()


# --- Third review round -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("doc", "excluded"),
    [
        ("Wegovy would be started on 2025-03-15.", True),  # hypothetical start
        ("Wegovy was resumed on 2025-03-15 and taken since 2025-03-15.", True),  # resumption
        ("Wegovy was started on 2025-03-15.", False),
    ],
)
def test_initiation_needs_an_actual_start_and_no_resumption(doc: str, excluded: bool) -> None:
    ev = _ev(doc, "glp1_start", drug="Wegovy", date="2025-03-15")
    assert ("value_not_in_quote" in ev.exclusion_reasons) is excluded


def test_purpose_needs_a_cue_and_mace_cannot_be_overwritten() -> None:
    doc = "Wegovy started 2025-03-15 to reduce major adverse cardiovascular events."
    weight = _ev(doc, "glp1_start", drug="Wegovy", date="2025-03-15", purpose="weight")
    assert "value_not_in_quote" in weight.exclusion_reasons
    unknown = _ev(doc, "glp1_start", drug="Wegovy", date="2025-03-15", purpose="unknown")
    assert "value_not_in_quote" in unknown.exclusion_reasons
    mace = _ev(doc, "glp1_start", drug="Wegovy", date="2025-03-15", purpose="mace")
    assert mace.exclusion_reasons == () and mace.flags == ()
    no_cue = _ev(
        "Wegovy started 2025-03-15.",
        "glp1_start",
        drug="Wegovy",
        date="2025-03-15",
        purpose="weight",
    )
    assert "unrecognized" in no_cue.flags and no_cue.exclusion_reasons == ()


def test_stopped_drug_is_not_ongoing() -> None:
    doc = "Amlodipine started 2025-03-10 and stopped 2025-03-14."
    ev = _ev(
        doc,
        "medications",
        name="amlodipine",
        start="2025-03-10",
        start_precision="day",
        end_kind="ongoing",
    )
    assert "value_not_in_quote" in ev.exclusion_reasons
    ok = _ev(
        doc,
        "medications",
        name="amlodipine",
        start="2025-03-10",
        start_precision="day",
        end="2025-03-14",
        end_precision="day",
        end_kind="ended",
    )
    assert ok.exclusion_reasons == ()


def test_follow_up_date_is_not_the_measurement_date() -> None:
    doc = "BMI 36.5 measured 2025-03-14, follow-up scheduled 2025-03-15."
    wrong = _ev(
        doc, "anthropometrics", raw_value="36.5", event_date="2025-03-15", date_precision="day"
    )
    assert "value_not_in_quote" in wrong.exclusion_reasons
    right = _ev(
        doc, "anthropometrics", raw_value="36.5", event_date="2025-03-14", date_precision="day"
    )
    assert right.exclusion_reasons == () and right.event_date_source == "llm"


def test_doc_date_is_the_one_bound_to_the_named_document() -> None:
    docs = {
        "D1": (
            "This referral letter dated 2025-03-15 encloses the D2 consult note dated 2025-03-16."
        ),
        "D2": "x",
    }
    wrong = run_verify(
        docs, {"doc_dates": [fact("doc_dates", docs["D1"], target_doc_id="D2", date="2025-03-15")]}
    ).evidence[0]
    assert "value_not_in_quote" in wrong.exclusion_reasons
    right = run_verify(
        docs, {"doc_dates": [fact("doc_dates", docs["D1"], target_doc_id="D2", date="2025-03-16")]}
    ).evidence[0]
    assert right.exclusion_reasons == () and right.flags == ()


def test_every_located_identity_occurrence_is_screened() -> None:
    doc = "MRN: P-0001. MRN: P-0002.\nHistory of stroke.\n"
    result = run_verify(
        {"D1": doc},
        {
            "patient_identity": [fact("patient_identity", "MRN:", patient_id="P-0001")],
            "diagnoses": [
                fact("diagnoses", "History of stroke.", concept="stroke", temporality="historical")
            ],
        },
    )
    assert result.doc_facts[0].identity_status == "mismatch"
    assert "wrong_patient" in result.evidence[1].exclusion_reasons


@pytest.mark.parametrize("doc", ["MRN: P-0001/2\n", "MRN: P-0001é\n"])
def test_unresolvable_identifier_never_matches(doc: str) -> None:
    ev, status = _identity(doc, patient_id="P-0001")
    assert status == "missing" and "id_missing" in ev.flags
    assert "value_not_in_quote" in ev.exclusion_reasons


def test_bp_goal_is_not_a_reading() -> None:
    doc = "BP goal 145/98, measured BP 130/80."
    assert "value_not_in_quote" in _ev(doc, "bp_readings", sbp=145, dbp=98).exclusion_reasons
    assert _ev(doc, "bp_readings", sbp=130, dbp=80).exclusion_reasons == ()


@pytest.mark.parametrize(
    "doc", ["BMI 28 to 36.5 kg/m².", "BMI below 36.5 kg/m².", "BMI between 28 and 36.5 kg/m²."]
)
def test_written_bounds_and_ranges_are_not_exact_values(doc: str) -> None:
    ev = _ev(doc, "anthropometrics", raw_value="36.5", raw_unit="kg/m²")
    assert "value_not_in_quote" in ev.exclusion_reasons


def test_hypothetical_symptom_does_not_make_pad_symptomatic() -> None:
    ev = _ev(
        "Patient has PAD and may develop claudication.",
        "diagnoses",
        concept="pad",
        symptomatic="yes",
    )
    assert "value_not_in_quote" in ev.exclusion_reasons


def test_heading_governs_every_entry_under_it() -> None:
    doc = "Family history:\nDiabetes: yes\nStroke: yes.\n"
    ev = _ev(doc, "diagnoses", "Stroke: yes.", concept="stroke")
    assert ev.assertion_check == "mismatch" and ev.subject_checked == "family"


def test_treatment_modifier_keeps_the_negation() -> None:
    ev = _ev("No treatment-related stroke.", "diagnoses", concept="stroke")
    assert ev.assertion_check == "mismatch" and ev.certainty_checked == "negated"


def test_referral_and_participation_cues_together_are_unrecognized() -> None:
    doc = "Currently referred to a dietitian, with visits scheduled weekly starting 2025-01-01."
    ev = _ev(
        doc,
        "lifestyle",
        kind="nutrition",
        program_type="structured_clinical",
        attendance="regular",
        start="2025-01-01",
        end_kind="ongoing",
    )
    assert "unrecognized" in ev.flags


# --- Fourth review round --------------------------------------------------------------------------


def test_start_word_must_belong_to_the_named_drug() -> None:
    # "and" cuts the start verb off from the date, and "continued" is no event word: the date
    # has no known action, so the fact is unrecognized (review), never an initiation.
    doc = "Metformin was started and Wegovy was continued on 2025-03-15."
    ev = _ev(doc, "glp1_start", drug="Wegovy", date="2025-03-15")
    assert "unrecognized" in ev.flags and ev.exclusion_reasons == ()
    doc = "Metformin was continued and Wegovy was started on 2025-03-15."
    assert _ev(doc, "glp1_start", drug="Wegovy", date="2025-03-15").exclusion_reasons == ()


def test_clipped_quote_does_not_hide_a_mace_cue() -> None:
    doc = "Wegovy started 2025-03-15 to reduce major adverse cardiovascular events."
    ev = _ev(doc, "glp1_start", "Wegovy started 2025-03-15", drug="Wegovy", date="2025-03-15")
    assert "value_not_in_quote" in ev.exclusion_reasons


def test_ongoing_contradicted_by_an_end_date_or_a_clipped_stop() -> None:
    doc = "Amlodipine started 2025-03-10 and stopped 2025-03-14."
    with_end = _ev(
        doc,
        "medications",
        name="amlodipine",
        start="2025-03-10",
        start_precision="day",
        end="2025-03-14",
        end_precision="day",
        end_kind="ongoing",
    )
    assert "value_not_in_quote" in with_end.exclusion_reasons
    clipped = _ev(
        doc,
        "medications",
        "Amlodipine started 2025-03-10",
        name="amlodipine",
        start="2025-03-10",
        start_precision="day",
        end_kind="ongoing",
    )
    assert "value_not_in_quote" in clipped.exclusion_reasons


def test_role_only_reference_needs_a_unique_document() -> None:
    quote = "The attached consult is dated 2025-03-15."
    docs: dict[str, str | tuple[str, str]] = {"D1": ("referral", quote), "D2": "x", "D3": "y"}
    f = fact("doc_dates", quote, target_doc_id="D2", date="2025-03-15")
    ev = run_verify(docs, {"doc_dates": [f]}).evidence[0]
    assert "unrecognized" in ev.flags


def test_candidate_identity_row_still_screens_for_a_mismatch() -> None:
    doc = "MRN: P-0002. Mother has MRN: P-0001.\nHistory of stroke.\n"
    result = run_verify(
        {"D1": doc},
        {
            "patient_identity": [fact("patient_identity", "MRN:", patient_id="P-0001")],
            "diagnoses": [
                fact("diagnoses", "History of stroke.", concept="stroke", temporality="historical")
            ],
        },
    )
    assert result.evidence[0].position_status == "candidate"
    assert result.doc_facts[0].identity_status == "mismatch"
    assert "wrong_patient" in result.evidence[1].exclusion_reasons


def test_hypothetical_identifier_cannot_establish_identity() -> None:
    _, status = _identity(
        "If MRN: P-0001 is provided.\n", patient_id="P-0001", temporality="hypothetical"
    )
    assert status == "missing"


def test_signed_number_is_not_a_measurement() -> None:
    ev = _ev(
        "BMI \u221236.5 kg/m\u00b2.", "anthropometrics", raw_value="36.5", raw_unit="kg/m\u00b2"
    )
    assert "value_not_in_quote" in ev.exclusion_reasons
    ev = _ev(
        "BMI \u221236.5 kg/m\u00b2.", "anthropometrics", raw_value="-36.5", raw_unit="kg/m\u00b2"
    )
    assert "unparseable_value" in ev.exclusion_reasons


def test_heading_scope_survives_a_sentence_break() -> None:
    doc = "Family history:\nDiabetes: yes.\nStroke: yes.\n"
    ev = _ev(doc, "diagnoses", "Stroke: yes.", concept="stroke")
    assert ev.assertion_check == "mismatch" and ev.subject_checked == "family"
    # A blank line ends the section.
    doc = "Family history:\nDiabetes: yes.\n\nStroke: yes.\n"
    assert _ev(doc, "diagnoses", "Stroke: yes.", concept="stroke").assertion_check == "matched"


def test_documented_lifestyle_status_left_unknown_is_unrecognized() -> None:
    doc = "Completed a structured nutrition program started 2025-01-01."
    ev = _ev(
        doc,
        "lifestyle",
        kind="nutrition",
        program_type="structured_clinical",
        start="2025-01-01",
        end_kind="unknown",
    )
    assert "unrecognized" in ev.flags


# --- Fifth review round --------------------------------------------------------------------------


def test_fuzzy_candidate_identity_row_cannot_mark_wrong_patient() -> None:
    doc = "MRN: P-0001. Visit code V-0002-X today. Denies stroke.\n"
    result = run_verify(
        {"D1": doc},
        {
            "patient_identity": [
                fact("patient_identity", "MRN: P-0001.", patient_id="P-0001"),
                fact("patient_identity", "Visit code V-0002-X todya.", patient_id="V-0002-X"),
            ],
            "diagnoses": [
                fact("diagnoses", "Denies stroke.", concept="stroke", certainty="negated")
            ],
        },
    )
    fuzzy = result.evidence[1]
    assert fuzzy.position_status == "candidate" and "candidate_ratio" in fuzzy.attributes
    assert result.doc_facts[0].identity_status == "match"
    assert result.evidence[2].exclusion_reasons == ()


def test_normalization_equivalent_occurrences_are_screened() -> None:
    doc = "MRN: P-0001. mrn: P-0002.\n"
    result = run_verify(
        {"D1": doc}, {"patient_identity": [fact("patient_identity", "MRN:", patient_id="P-0001")]}
    )
    ev = result.evidence[0]
    assert ev.attributes["occurrences"] == [[0, 4], [13, 17]]
    assert result.doc_facts[0].identity_status == "mismatch"


def test_hypothetical_identifier_is_not_a_mismatch_either() -> None:
    doc = "MRN: P-0001. If MRN: P-0002 is provided, note it.\nDenies stroke.\n"
    result = run_verify(
        {"D1": doc},
        {
            "patient_identity": [fact("patient_identity", doc.split("\n")[0], patient_id="P-0001")],
            "diagnoses": [
                fact("diagnoses", "Denies stroke.", concept="stroke", certainty="negated")
            ],
        },
    )
    assert result.doc_facts[0].identity_status == "match"
    assert result.evidence[1].exclusion_reasons == ()


def test_earlier_entry_cues_stay_local_under_a_heading() -> None:
    doc = "Family history:\nDiabetes: no, but details unavailable.\nStroke: yes.\n"
    ev = _ev(doc, "diagnoses", "Stroke: yes.", concept="stroke")
    assert ev.assertion_check == "mismatch" and ev.subject_checked == "family"
    assert ev.certainty_checked == "present"  # the earlier entry's "no" does not reach it


def test_start_verb_binds_to_its_nearest_drug() -> None:
    doc = "Patient continued Wegovy and on 2025-03-15 started metformin."
    assert (
        "value_not_in_quote"
        in _ev(doc, "glp1_start", drug="Wegovy", date="2025-03-15").exclusion_reasons
    )
    doc = "Patient continued metformin and on 2025-03-15 started Wegovy."
    assert _ev(doc, "glp1_start", drug="Wegovy", date="2025-03-15").exclusion_reasons == ()


def test_shared_start_verb_behind_another_date_is_unrecognized() -> None:
    doc = "Started metformin on 2025-01-02 and Wegovy on 2025-03-15."
    ev = _ev(doc, "glp1_start", drug="Wegovy", date="2025-03-15")
    assert ev.assertion_check == "matched" and ev.exclusion_reasons == ()
    assert "unrecognized" in ev.flags  # this is what sends the fact to review


# --- Sixth review round ---------------------------------------------------------------------------


def test_uncertain_identifier_cannot_contradict_a_verified_one() -> None:
    doc = "MRN: P-0001. Possible MRN: P-0002.\nDenies stroke.\n"
    result = run_verify(
        {"D1": doc},
        {
            "patient_identity": [fact("patient_identity", doc.split("\n")[0], patient_id="P-0001")],
            "diagnoses": [
                fact("diagnoses", "Denies stroke.", concept="stroke", certainty="negated")
            ],
        },
    )
    assert result.doc_facts[0].identity_status == "match"
    assert result.evidence[1].exclusion_reasons == ()


def test_heading_scope_applies_to_each_identifier() -> None:
    doc = "MRN: P-0001.\nFamily history:\nMRN: P-0002.\nDenies stroke.\n"
    result = run_verify(
        {"D1": doc},
        {
            "patient_identity": [
                fact("patient_identity", "MRN: P-0001.", patient_id="P-0001"),
                fact("patient_identity", "MRN: P-0002.", patient_id="P-0002", subject="family"),
            ],
            "diagnoses": [
                fact("diagnoses", "Denies stroke.", concept="stroke", certainty="negated")
            ],
        },
    )
    assert result.evidence[1].attributes["identifiers"][0][2] == "family"
    assert result.doc_facts[0].identity_status == "match"
    assert result.evidence[2].exclusion_reasons == ()


def test_dated_stop_is_not_the_earlier_start() -> None:
    doc = "Wegovy was started, and on 2025-03-15 it was stopped."
    ev = _ev(doc, "glp1_start", drug="Wegovy", date="2025-03-15")
    assert "value_not_in_quote" in ev.exclusion_reasons


def test_start_verb_object_wins_over_a_closer_preceding_drug() -> None:
    doc = "Patient continued Wegovy, started taking metformin on 2025-03-15."
    ev = _ev(doc, "glp1_start", drug="Wegovy", date="2025-03-15")
    assert "value_not_in_quote" in ev.exclusion_reasons
    doc = "Patient continued metformin, started taking Wegovy on 2025-03-15."
    assert _ev(doc, "glp1_start", drug="Wegovy", date="2025-03-15").exclusion_reasons == ()


# --- Seventh review round -------------------------------------------------------------------------


def test_each_explicit_date_stays_with_its_own_action() -> None:
    doc = "Stopped metformin on 2025-03-15 and started Wegovy on 2025-03-20."
    march15 = _ev(doc, "glp1_start", drug="Wegovy", date="2025-03-15")
    assert "value_not_in_quote" in march15.exclusion_reasons  # the stop's date
    march20 = _ev(doc, "glp1_start", drug="Wegovy", date="2025-03-20")
    assert march20.exclusion_reasons == () and march20.flags == ()


def test_forward_date_binding_stays_within_its_action_phrase() -> None:
    doc = "Continued metformin on 2025-03-15 and started Wegovy on 2025-03-20."
    march15 = _ev(doc, "glp1_start", drug="Wegovy", date="2025-03-15")
    assert "unrecognized" in march15.flags and march15.exclusion_reasons == ()
    march20 = _ev(doc, "glp1_start", drug="Wegovy", date="2025-03-20")
    assert march20.exclusion_reasons == () and march20.flags == ()
    # The fronted date still binds forward when nothing separates it from the verb.
    assert _ev(
        "Wegovy: on 2025-03-15 it was stopped.", "glp1_start", drug="Wegovy", date="2025-03-15"
    ).exclusion_reasons == ("value_not_in_quote",)


# --- attributes.quote_date ------------------------------------------------------------------------


def test_quote_date_is_recorded_independently_of_model_event_date() -> None:
    doc = "BMI 36.5 measured 2025-03-16."
    ev = _ev(doc, "anthropometrics", raw_value="36.5")  # the model omitted event_date
    assert ev.event_date is None and ev.event_date_source is None
    assert ev.attributes["quote_date"] == {"date": "2025-03-16", "precision": "day"}
    month = _ev("BMI 36.5 in March 2025.", "anthropometrics", raw_value="36.5")
    assert month.attributes["quote_date"] == {"date": "2025-03", "precision": "month"}


def test_quote_without_date_has_no_quote_date() -> None:
    ev = _ev("BMI 36.5 today.", "anthropometrics", raw_value="36.5")
    assert "quote_date" not in ev.attributes
    # A date in the same sentence that belongs to another measurement is not this quote's.
    ev = _ev(
        "BMI 29 on 2025-03-15, BMI 36.5 today.",
        "anthropometrics",
        "BMI 36.5 today",
        raw_value="36.5",
    )
    assert "quote_date" not in ev.attributes


def test_t05_explicitly_dated_measurement_never_inherits_the_document_date() -> None:
    # Verifier half of planning draft §5 case 1: the consult is dated 2025-03-15 elsewhere, the
    # extractor omitted the BMI's date; the quote's own date is what compute must keep.
    docs: dict[str, str | tuple[str, str]] = {
        "D1": ("referral", "I enclose the D2 consult note of 2025-03-15."),
        "D2": "BMI 36.5 measured 2025-03-16.",
    }
    result = run_verify(
        docs,
        {
            "doc_dates": [
                fact(
                    "doc_dates",
                    "I enclose the D2 consult note of 2025-03-15.",
                    target_doc_id="D2",
                    date="2025-03-15",
                )
            ],
            "anthropometrics": [
                fact(
                    "anthropometrics",
                    "BMI 36.5 measured 2025-03-16.",
                    doc_id="D2",
                    raw_value="36.5",
                )
            ],
        },
    )
    doc_date, bmi = result.evidence
    assert doc_date.exclusion_reasons == () and doc_date.flags == ()
    assert bmi.event_date_source is None
    assert bmi.attributes["quote_date"] == {"date": "2025-03-16", "precision": "day"}


# --- PA-form checkboxes bind to their own label (guide K-01, K-02) -------------------------------

FORM = "Prior authorization draft.\nType 2 diabetes: No\nPrevious stroke: Yes\n"


def _claim_ev(doc: str, role: str, quote: str, claim_id: str, value: str) -> CheckedEvidence:
    f = fact("pa_form_claims", quote, claim_id=claim_id, claimed_value=value)
    return run_verify({"D1": (role, doc)}, {"pa_form_claims": [f]}).evidence[0]


def test_claim_value_binds_to_its_own_checkbox() -> None:
    ev = _claim_ev(FORM, "pa_draft", "Type 2 diabetes: No", "claim.exclusion.t2dm", "no")
    assert ev.exclusion_reasons == () and ev.flags == () and ev.assertion_check == "matched"


def test_claim_value_from_another_checkbox_is_not_the_claim() -> None:
    ev = _claim_ev(FORM, "pa_draft", "Previous stroke: Yes", "claim.exclusion.t2dm", "yes")
    assert "value_not_in_quote" in ev.exclusion_reasons


def test_claim_without_its_field_is_not_in_the_quote() -> None:
    ev = _claim_ev(FORM, "pa_draft", "Previous stroke: Yes", "claim.bmi_path_b.hfpef", "yes")
    assert "value_not_in_quote" in ev.exclusion_reasons


def test_claim_from_a_clinical_document_is_unrecognized() -> None:
    doc = "Clinic note.\nType 2 diabetes: No\n"
    ev = _claim_ev(doc, "clinical", "Type 2 diabetes: No", "claim.exclusion.t2dm", "no")
    assert "unrecognized" in ev.flags


def test_blank_yes_no_pair_is_kept_as_unrecognized() -> None:
    form = "Prior authorization draft.\nType 2 diabetes: [ ] Yes [ ] No\n"
    ev = _claim_ev(form, "pa_draft", "No", "claim.exclusion.t2dm", "no")
    assert ev.exclusion_reasons == () and "unrecognized" in ev.flags
    marked = "Prior authorization draft.\nType 2 diabetes: [ ] Yes [X] No\n"
    ev = _claim_ev(marked, "pa_draft", "No", "claim.exclusion.t2dm", "no")
    assert ev.exclusion_reasons == () and ev.flags == ()
    other = _claim_ev(marked, "pa_draft", "Yes", "claim.exclusion.t2dm", "yes")
    assert "unrecognized" in other.flags


def test_two_unselected_drug_options_are_unrecognized() -> None:
    form = "Prior authorization draft.\nRequested drug: Wegovy / Ozempic\n"
    ev = _claim_ev(form, "pa_draft", "Requested drug: Wegovy / Ozempic", "claim.drug", "Wegovy")
    assert "unrecognized" in ev.flags


def test_value_of_a_later_unregistered_field_does_not_bind_back() -> None:
    form = "Prior authorization draft.\nType 2 diabetes: Yes   Smoker: No\n"
    ev = _claim_ev(form, "pa_draft", "Smoker: No", "claim.exclusion.t2dm", "no")
    assert "value_not_in_quote" in ev.exclusion_reasons


def test_relatives_question_is_not_the_patients_claim() -> None:
    form = "Prior authorization draft.\nDaughter's type 2 diabetes: Yes\n"
    ev = _claim_ev(
        form, "pa_draft", "Daughter's type 2 diabetes: Yes", "claim.exclusion.t2dm", "yes"
    )
    # the whole field label is not the patient's question: the value is not this claim's
    assert "value_not_in_quote" in ev.exclusion_reasons


def test_possessed_case_summary_dates_the_possessor() -> None:
    doc = "Referral letter.\nThe referral's case summary dated 2025-03-15 is enclosed.\n"
    f = fact(
        "doc_dates",
        "The referral's case summary dated 2025-03-15 is enclosed.",
        target_doc_id="D2",
        date="2025-03-15",
    )
    ev = run_verify(
        {"D1": ("referral", doc), "D2": ("clinical", "x")}, {"doc_dates": [f]}
    ).evidence[0]
    assert "value_not_in_quote" in ev.exclusion_reasons
    ok = fact(
        "doc_dates",
        "I enclose the case summary dated 2025-03-15.",
        target_doc_id="D2",
        date="2025-03-15",
    )
    ev = run_verify(
        {
            "D1": ("referral", "I enclose the case summary dated 2025-03-15.\n"),
            "D2": ("clinical", "x"),
        },
        {"doc_dates": [ok]},
    ).evidence[0]
    assert ev.exclusion_reasons == () and ev.flags == ()


def test_explicitly_unchecked_single_option_is_not_selected() -> None:
    form = "Prior authorization draft.\nType 2 diabetes: [ ] No\n"
    ev = _claim_ev(form, "pa_draft", "Type 2 diabetes: [ ] No", "claim.exclusion.t2dm", "no")
    assert ev.exclusion_reasons == () and "unrecognized" in ev.flags
    plain = _claim_ev(FORM, "pa_draft", "Type 2 diabetes: No", "claim.exclusion.t2dm", "no")
    assert plain.flags == ()


def test_mash_box_without_the_fibrosis_qualifier_is_not_the_claim() -> None:
    form = "Prior authorization draft.\nNoncirrhotic MASH: No\n"
    ev = _claim_ev(form, "pa_draft", "Noncirrhotic MASH: No", "claim.exclusion.mash", "no")
    assert "value_not_in_quote" in ev.exclusion_reasons
    full = "Prior authorization draft.\nNoncirrhotic MASH with fibrosis F2-F3: No\n"
    ev = _claim_ev(
        full, "pa_draft", "Noncirrhotic MASH with fibrosis F2-F3: No", "claim.exclusion.mash", "no"
    )
    assert ev.exclusion_reasons == () and ev.flags == ()


def test_case_summary_without_an_attachment_word_dates_nothing_else() -> None:
    doc = "Referral letter.\nThis case summary dated 2025-03-15 covers the course so far.\n"
    f = fact(
        "doc_dates",
        "This case summary dated 2025-03-15 covers the course so far.",
        target_doc_id="D2",
        date="2025-03-15",
    )
    ev = run_verify(
        {"D1": ("referral", doc), "D2": ("clinical", "x")}, {"doc_dates": [f]}
    ).evidence[0]
    assert "unrecognized" in ev.flags


def test_list_status_comes_from_the_heading_not_from_one_entry() -> None:
    doc = (
        "Current medications: amlodipine 5 mg; metoprolol 50 mg (stopped last week).\n"
        "Medications planned for the next visit: lisinopril.\n"
    )
    current = fact("medication_lists", doc.splitlines()[0], list_id="L1")
    planned = fact("medication_lists", doc.splitlines()[1], list_id="L2")
    rows = run_verify({"D1": doc}, {"medication_lists": [current, planned]}).evidence
    assert rows[0].attributes["list_status"] == "current"  # one stopped entry is that drug's
    assert rows[1].attributes["list_status"] == "unknown"  # "medications" alone is no label


def test_attachment_cue_must_be_about_the_dated_document() -> None:
    cases = {
        "This case summary dated 2025-03-15 is not attached to the letter.": "unrecognized",
        "This case summary dated 2025-03-15 covers the course; see the attached lab report.": (
            "unrecognized"
        ),
        "This case summary dated 2025-03-15 is not yet attached.": "unrecognized",
        "Please attach the case summary dated 2025-03-15.": "unrecognized",
        "Attach the case summary dated 2025-03-15.": "unrecognized",
        "Then attach the case summary dated 2025-03-15.": "unrecognized",
        "After review, attach the case summary dated 2025-03-15.": "unrecognized",
        "This letter encloses the case summary dated 2025-03-15.": "ok",
        "I didn't attach the case summary dated 2025-03-15.": "unrecognized",
        "We attach the case summary dated 2025-03-15.": "ok",
        "I will attach the case summary dated 2025-03-15 later.": "unrecognized",
        "The case summary dated 2025-03-15 mentions the attached lab result.": "unrecognized",
        "The attached lab result and the case summary dated 2025-03-15 agree.": "unrecognized",
        "The enclosed bariatric surgery case summary dated 2025-03-15 lists the course.": "ok",
        "The case summary dated 2025-03-15 is attached.": "ok",
        "The case summary dated 2025-03-15 is enclosed; the lab report is not.": "ok",
        "I enclose the case summary dated 2025-03-15.": "ok",
        "The attached case summary dated 2025-03-15 lists the course.": "ok",
    }
    for sentence, expected in cases.items():
        f = fact("doc_dates", sentence, target_doc_id="D2", date="2025-03-15")
        ev = run_verify(
            {"D1": ("referral", "Referral letter.\n" + sentence + "\n"), "D2": ("clinical", "x")},
            {"doc_dates": [f]},
        ).evidence[0]
        assert ("unrecognized" in ev.flags) == (expected == "unrecognized"), sentence


def test_empty_checkbox_syntax_is_normalized() -> None:
    for box in ("［ ］", "[  ]", "( )"):
        form = f"Prior authorization draft.\nType 2 diabetes: {box} No\n"
        ev = _claim_ev(form, "pa_draft", f"Type 2 diabetes: {box} No", "claim.exclusion.t2dm", "no")
        assert "unrecognized" in ev.flags, box
    marked = "Prior authorization draft.\nType 2 diabetes: ［Ｘ］ No\n"
    ev = _claim_ev(marked, "pa_draft", "Type 2 diabetes: ［Ｘ］ No", "claim.exclusion.t2dm", "no")
    assert ev.flags == () and ev.exclusion_reasons == ()


def test_medication_list_status_is_read_from_the_heading() -> None:
    doc = (
        "Discontinued medications: amlodipine 5 mg; metoprolol 50 mg.\n"
        "Current medications: aspirin.\n"
    )
    stopped = fact(
        "medication_lists",
        "Discontinued medications: amlodipine 5 mg; metoprolol 50 mg.",
        list_id="L1",
    )
    current = fact("medication_lists", "Current medications: aspirin.", list_id="L2")
    rows = run_verify({"D1": doc}, {"medication_lists": [stopped, current]}).evidence
    assert rows[0].attributes["list_status"] == "discontinued"
    assert rows[1].attributes["list_status"] == "current"


def test_date_must_belong_to_the_attached_mention() -> None:
    quote = "I enclose the consult note. The case summary dated 2025-03-15 is a separate record."
    f = fact("doc_dates", quote, target_doc_id="D2", date="2025-03-15")
    ev = run_verify(
        {"D1": ("referral", "Referral letter.\n" + quote + "\n"), "D2": ("clinical", "x")},
        {"doc_dates": [f]},
    ).evidence[0]
    assert "value_not_in_quote" in ev.exclusion_reasons
