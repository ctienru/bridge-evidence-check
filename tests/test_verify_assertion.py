"""Layer 4 sentence-level assertion check (contract §6; guide A-01–A-11, §3.3)."""

from __future__ import annotations

import ast

import pytest
from conftest import ROOT, fact, run_verify

from bridge_check.cues import load_cues
from bridge_check.enums import CONCEPTS, EXTRACTION_DATE_PRECISIONS
from bridge_check.verify import CheckedEvidence, check_assertion, load_terms

DEFAULTS = ("present", "patient", "current")

# Guide §3.3 minimal pairs: (text, concept, expected (certainty, subject, temporality)).
MINIMAL_PAIRS = [
    ("r/o HFpEF", "hfpef", ("uncertain", "patient", "current")),
    ("Negative for HFpEF", "hfpef", ("negated", "patient", "current")),
    ("HFpEF", "hfpef", DEFAULTS),
    ("Mother with suspected HFpEF", "hfpef", ("uncertain", "family", "current")),
    ("OSA s/p surgery", "osa", DEFAULTS),
    ("Resolved OSA on repeat sleep study after surgery", "osa", ("present", "patient", "resolved")),
    ("Denies type 2 diabetes", "t2dm", ("negated", "patient", "current")),
    ("Mother has type 2 diabetes", "t2dm", ("present", "family", "current")),
    ("Remission of T2DM after bariatric surgery", "t2dm", ("present", "patient", "resolved")),
    ("History of MI in 2019", "mi", ("present", "patient", "historical")),
    ("Surgical risks include MI and stroke", "mi", ("present", "patient", "hypothetical")),
    ("Surgical risks include MI and stroke", "stroke", ("present", "patient", "hypothetical")),
    ("No history of stroke, but a prior TIA", "stroke", ("negated", "patient", "historical")),
    ("Possible prediabetes, A1c pending", "prediabetes", ("uncertain", "patient", "current")),
]


def _axes(**kw: str) -> dict[str, str]:
    return kw


def _check(
    doc: str, concept: str, claimed: tuple[str, str, str], quote: str | None = None
) -> CheckedEvidence:
    c, s, t = claimed
    f = fact("diagnoses", quote or doc, concept=concept, certainty=c, subject=s, temporality=t)
    return run_verify({"D1": doc}, {"diagnoses": [f]}).evidence[0]


def _checked(ev: CheckedEvidence) -> tuple[str | None, str | None, str | None]:
    return (ev.certainty_checked, ev.subject_checked, ev.temporality_checked)


@pytest.mark.parametrize(("text", "concept", "expected"), MINIMAL_PAIRS)
def test_minimal_pair_matches_the_guide(
    text: str, concept: str, expected: tuple[str, str, str]
) -> None:
    ev = _check(text, concept, expected)
    assert _checked(ev) == expected
    assert ev.assertion_check == "matched"
    assert ev.exclusion_reasons == ()


@pytest.mark.parametrize(
    ("text", "concept", "expected"), [p for p in MINIMAL_PAIRS if p[2] != DEFAULTS]
)
def test_minimal_pair_claimed_as_defaults_is_a_mismatch(
    text: str, concept: str, expected: tuple[str, str, str]
) -> None:
    # The "common-sense completion" risk (A-11): the cue contradicts present/patient/current.
    ev = _check(text, concept, DEFAULTS)
    assert ev.assertion_check == "mismatch"
    assert "assertion_mismatch" in ev.exclusion_reasons


def test_non_default_claim_without_a_cue_is_unrecognized() -> None:
    ev = _check("HFpEF on echo.", "hfpef", ("negated", "patient", "current"))
    assert ev.assertion_check == "unrecognized"
    assert "unrecognized" in ev.flags
    assert ev.exclusion_reasons == ()


def test_a10_family_scope_then_denies_scope_gives_four_facts() -> None:
    doc = (
        "Family history: mother with diabetes, father with stroke; "
        "patient denies diabetes or stroke."
    )
    family, patient = ("present", "family", "current"), ("negated", "patient", "current")
    specs = [
        ("mother with diabetes", "t2dm", family),
        ("father with stroke", "stroke", family),
        ("patient denies diabetes", "t2dm", patient),
        ("denies diabetes or stroke", "stroke", patient),
    ]
    facts = [
        fact("diagnoses", q, concept=c, certainty=a[0], subject=a[1], temporality=a[2])
        for q, c, a in specs
    ]
    evidence = run_verify({"D1": doc}, {"diagnoses": facts}).evidence
    assert len(evidence) == 4
    assert [_checked(ev) for ev in evidence] == [a for _, _, a in specs]
    assert all(ev.assertion_check == "matched" for ev in evidence)


def test_cue_does_not_cross_a_full_stop() -> None:
    doc = "No diabetes. Prior MI."
    dm = _check(doc, "t2dm", ("negated", "patient", "current"), quote=doc)
    mi = _check(doc, "mi", ("present", "patient", "historical"), quote=doc)
    assert _checked(dm) == ("negated", "patient", "current")
    # The negation stops at the period; MI is historical only through its own "Prior" cue.
    assert _checked(mi) == ("present", "patient", "historical")
    assert dm.assertion_check == mi.assertion_check == "matched"


def test_but_terminates_the_negation_scope() -> None:
    doc = "No diabetes, but mother had MI"
    dm = _check(doc, "t2dm", ("negated", "patient", "current"))
    mi = _check(doc, "mi", ("present", "family", "current"))
    assert _checked(dm) == ("negated", "patient", "current")
    assert _checked(mi) == ("present", "family", "current")


@pytest.mark.parametrize(
    ("text", "concept", "expected"),
    [
        ("Stroke was ruled out.", "stroke", ("negated", "patient", "current")),
        ("Diabetes excluded on labs.", "t2dm", ("negated", "patient", "current")),
        ("HFpEF?", "hfpef", ("uncertain", "patient", "current")),
        ("?HFpEF on echo.", "hfpef", ("uncertain", "patient", "current")),
        (
            "Hypertension, resolved after weight loss.",
            "hypertension",
            ("present", "patient", "resolved"),
        ),
        ("Stroke; ruled out later.", "stroke", DEFAULTS),  # `;` ends the scope
    ],
)
def test_right_hand_patterns(text: str, concept: str, expected: tuple[str, str, str]) -> None:
    assert _checked(_check(text, concept, expected)) == expected


def test_right_hand_word_that_is_not_a_right_hand_pattern_does_not_apply() -> None:
    # "possible" is a cue only to its right; after the mention it does not apply.
    ev = _check("HFpEF possible.", "hfpef", DEFAULTS)
    assert _checked(ev) == DEFAULTS


def test_question_mark_ending_a_question_is_not_a_cue() -> None:
    ev = _check("Does she have HFpEF?", "hfpef", DEFAULTS)
    assert _checked(ev) == DEFAULTS and ev.assertion_check == "matched"


@pytest.mark.parametrize(
    ("text", "concept", "expected"),
    [
        ("Not on insulin for diabetes.", "t2dm", DEFAULTS),
        ("No CPAP for OSA.", "osa", DEFAULTS),
        ("Patient is not on any medications for hypertension.", "hypertension", DEFAULTS),
        ("No OSA, no CPAP.", "osa", ("negated", "patient", "current")),
        ("No diabetes or insulin use.", "t2dm", ("negated", "patient", "current")),
    ],
)
def test_a09_negated_treatment_is_not_a_negated_condition(
    text: str, concept: str, expected: tuple[str, str, str]
) -> None:
    assert _checked(_check(text, concept, expected)) == expected


def test_form_label_line_ends_a_scope() -> None:
    # "PRIOR" in the header would otherwise reach every field of a punctuation-free form.
    doc = "PRIOR AUTHORIZATION REQUEST\nPatient ID: P-0001\nDrug requested: Wegovy\n"
    f = fact(
        "pa_form_claims", "Drug requested: Wegovy", claim_id="claim.drug", claimed_value="Wegovy"
    )
    ev = run_verify({"D1": ("pa_draft", doc)}, {"pa_form_claims": [f]}).evidence[0]
    assert ev.assertion_check == "matched"
    assert _checked(ev) == DEFAULTS


def test_two_values_on_one_axis_are_undecidable() -> None:
    ev = _check("Possible stroke, ruled out.", "stroke", ("uncertain", "patient", "current"))
    assert ev.certainty_checked is None
    assert ev.assertion_check == "unrecognized"


def test_mentions_that_disagree_inside_one_quote_are_unrecognized() -> None:
    doc = "Mother with diabetes; patient denies diabetes."
    ev = _check(doc, "t2dm", ("present", "family", "current"), quote=doc)
    assert ev.assertion_check == "unrecognized"
    assert len(ev.attributes["mentions"]) == 2


def test_value_fact_uses_its_value_as_the_mention() -> None:
    f = fact("anthropometrics", "BMI 31, no diabetes", raw_value="31")
    ev = run_verify({"D1": "BMI 31, no diabetes."}, {"anthropometrics": [f]}).evidence[0]
    assert ev.assertion_check == "matched"  # the negation is to the right of the value


def test_check_assertion_is_pure_on_one_sentence() -> None:
    cues, terms = load_cues(), load_terms()
    sentence = "Patient denies chest pain or stroke."
    start = sentence.index("stroke")
    check = check_assertion(
        sentence,
        (start, start + len("stroke")),
        {"certainty": "negated", "subject": "patient", "temporality": "current"},
        cues,
        terms=terms,
        concept="stroke",
    )
    assert check.result == "matched"
    assert check.checked == {"certainty": "negated", "subject": "patient", "temporality": "current"}


@pytest.mark.parametrize(
    ("doc", "table"),
    [
        ("| BMI | 31.2 |\n", True),
        ("BMI\t31.2\tkg/m2\n", True),
        ("BMI   31.2   kg/m2   today\n", True),
        ("BMI 31.2 kg/m2 today\n", False),
    ],
)
def test_table_source_flag(doc: str, table: bool) -> None:
    f = fact("anthropometrics", "31.2", raw_value="31.2")
    ev = run_verify({"D1": doc}, {"anthropometrics": [f]}).evidence[0]
    assert ("table_source" in ev.flags) is table


def test_terms_table_loads_with_drug_and_glp1_names() -> None:
    terms = load_terms()
    assert terms.version == "verify-terms-v1"
    assert "other" not in terms.concept_terms
    assert {"insulin", "CPAP", "Wegovy", "amlodipine"} <= set(terms.treatment_terms)


def test_verify_hard_codes_no_cue_words() -> None:
    # The frozen cue table is the only source of cue words. `?` (A-08) is punctuation the
    # verifier must recognise by shape, so only cues with a letter are checked.
    source = (ROOT / "src" / "bridge_check" / "verify.py").read_text(encoding="utf-8")
    literals = {
        node.value.casefold()
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    cues = load_cues()
    words = {
        c.casefold()
        for values in cues.axes.values()
        for words_ in values.values()
        for c in words_
        if any(ch.isalpha() for ch in c)
    } | {t.casefold() for t in cues.terminators if any(ch.isalpha() for ch in t)}
    # Schema enum values that happen to spell a cue word (`date_precision: none`) are not cues.
    assert literals & words - set(EXTRACTION_DATE_PRECISIONS) == set()


def test_every_concept_except_other_has_a_term() -> None:
    terms = load_terms()
    assert set(terms.concept_terms) == set(CONCEPTS) - {"other"}
    assert all(terms.concept_terms[c] for c in terms.concept_terms)
