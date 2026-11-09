"""Document-level exclusions: `claim_document` and identity (contract §3.5, §7.3 step 0)."""

from __future__ import annotations

from conftest import fact, run_verify

from bridge_check.verify import VerifyResult


def _doc_status(result: VerifyResult) -> dict[str, str]:
    return {d.doc_id: d.identity_status for d in result.doc_facts}


def test_pa_draft_facts_are_claim_document_except_claims() -> None:
    doc = "PA REQUEST\nDiagnosis: HFpEF\nHFpEF: yes\n"
    result = run_verify(
        {"D0": ("pa_draft", doc)},
        {
            "diagnoses": [fact("diagnoses", "Diagnosis: HFpEF", doc_id="D0", concept="hfpef")],
            "pa_form_claims": [
                fact(
                    "pa_form_claims",
                    "HFpEF: yes",
                    doc_id="D0",
                    claim_id="claim.bmi_path_b.hfpef",
                    claimed_value="yes",
                )
            ],
        },
    )
    dx, claim = result.evidence
    assert dx.exclusion_reasons == ("claim_document",)
    assert claim.exclusion_reasons == ()


def test_id_mismatch_excludes_every_fact_of_that_document() -> None:
    docs = {
        "D1": "Patient ID: P-0001. Seen today.",
        "D2": "MRN: P-0010. Hypertension noted.",
    }
    result = run_verify(
        docs,
        {
            "patient_identity": [
                fact("patient_identity", "Patient ID: P-0001", doc_id="D1", patient_id="P-0001"),
                fact("patient_identity", "MRN: P-0010", doc_id="D2", patient_id="P-0010"),
            ],
            "diagnoses": [
                fact("diagnoses", "Hypertension noted.", doc_id="D2", concept="hypertension")
            ],
        },
    )
    assert _doc_status(result) == {"D1": "match", "D2": "mismatch"}
    d1_id, d2_id, dx = result.evidence
    assert d1_id.exclusion_reasons == ()
    assert d2_id.exclusion_reasons == ("wrong_patient",)
    assert dx.exclusion_reasons == ("wrong_patient",)
    assert result.doc_facts[1].identity_evidence_index == 1


def test_different_identifier_types_are_not_compared() -> None:
    # The primary id is a local id; an MBI is a different identifier and is not compared,
    # so the DOB decides.
    doc = "MBI: 1EG4TE5MK73. DOB 1960-01-01."
    f = fact("patient_identity", doc, patient_id="1EG4TE5MK73", dob="1960-01-01")
    result = run_verify({"D1": doc}, {"patient_identity": [f]})
    assert _doc_status(result) == {"D1": "match"}
    assert result.evidence[0].exclusion_reasons == ()


def test_dob_decides_only_without_a_comparable_id() -> None:
    doc = "DOB 1961-02-02. Seen today."
    f = fact("patient_identity", "DOB 1961-02-02.", dob="1961-02-02")
    result = run_verify({"D1": doc}, {"patient_identity": [f]})
    assert _doc_status(result) == {"D1": "mismatch"}
    assert result.evidence[0].exclusion_reasons == ("wrong_patient",)


def test_matching_id_wins_over_a_different_dob() -> None:
    doc = "Patient ID: P-0001. DOB 1961-02-02."
    f = fact("patient_identity", doc, patient_id="P-0001", dob="1961-02-02")
    assert _doc_status(run_verify({"D1": doc}, {"patient_identity": [f]})) == {"D1": "match"}


def test_nothing_to_compare_is_missing_with_id_missing() -> None:
    doc = "Name: Synthetic Patient. Seen today."
    f = fact("patient_identity", "Name: Synthetic Patient.", name="Synthetic Patient")
    result = run_verify({"D1": doc, "D2": "No identifiers here."}, {"patient_identity": [f]})
    assert _doc_status(result) == {"D1": "missing", "D2": "missing"}
    assert result.evidence[0].flags == ("id_missing",)
    assert result.evidence[0].exclusion_reasons == ()


def test_unverified_identity_fact_is_not_used() -> None:
    f = fact("patient_identity", "Patient ID: P-0999", patient_id="P-0999")
    result = run_verify({"D1": "Seen today."}, {"patient_identity": [f]})
    assert _doc_status(result) == {"D1": "missing"}
    assert result.evidence[0].exclusion_reasons == ("quote_not_found",)  # nothing added


def test_every_fact_becomes_exactly_one_evidence() -> None:
    doc = "BMI 31. BP 150/95."
    facts = {
        "anthropometrics": [fact("anthropometrics", "BMI 31", raw_value="31")],
        "bp_readings": [fact("bp_readings", "BP 150/95", sbp=150, dbp=95)],
        "labs": [fact("labs", "A1c 9.9 %", raw_value="9.9")],
    }
    result = run_verify({"D1": doc}, facts)
    assert [ev.fact_path for ev in result.evidence] == [
        "anthropometrics[0]",
        "bp_readings[0]",
        "labs[0]",
    ]
