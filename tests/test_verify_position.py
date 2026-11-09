"""Position status (contract §6, 06 §3): verbatim → normalized → candidate → not_found.

Every located span must round-trip: `doc[start:end]` is the original text, whatever the
normalization did. Fuzzy similarity never verifies a quote (AGENTS.md).
"""

from __future__ import annotations

import difflib

import pytest
from conftest import fact, run_verify

from bridge_check.verify import CANDIDATE_RATIO, CheckedEvidence, normalize


def _one(doc: str, quote: str, fact_field: str = "diagnoses", **fields: object) -> CheckedEvidence:
    result = run_verify({"D1": doc}, {fact_field: [fact(fact_field, quote, **fields)]})
    assert len(result.evidence) == 1
    return result.evidence[0]


def test_verbatim_offsets() -> None:
    doc = "Clinic visit.\nHistory of hypertension.\n"
    ev = _one(doc, "History of hypertension.", concept="hypertension", temporality="historical")
    assert ev.position_status == "verbatim"
    assert doc[ev.start : ev.end] == "History of hypertension."
    assert ev.exclusion_reasons == () and ev.assertion_check == "matched"


@pytest.mark.parametrize(
    ("doc", "quote", "original", "fired"),
    [
        # CRLF in the document, a plain space in the quote.
        (
            "Visit.\r\nBMI 31.2 kg/m2 at\r\ninitiation.\r\n",
            "BMI 31.2 kg/m2 at initiation",
            "BMI 31.2 kg/m2 at\r\ninitiation",
            {"whitespace"},
        ),
        # The fi ligature expands to two characters.
        ("Patient is ﬁt for surgery.", "fit for surgery", "ﬁt for surgery", {"nfkc"}),
        # Full-width digits.
        ("BMI ３１.２ today.", "BMI 31.2", "BMI ３１.２", {"nfkc"}),
        # A decomposed e + combining acute in the document, precomposed in the quote.
        ("Seen by the café nurse today.", "café nurse", "café nurse", {"nfkc"}),
        # Emoji are single code points; offsets after them still line up.
        (
            "Mood \U0001f600 good. BMI  31.2 noted.",
            "BMI 31.2 noted",
            "BMI  31.2 noted",
            {"whitespace"},
        ),
        # Curly quotes and an en dash.
        ("Bracket “30–34.9” ticked.", '"30-34.9"', "“30–34.9”", {"quotes_dashes"}),
        # Case-fold.
        (
            "BLOOD PRESSURE 150/95 MMHG.",
            "Blood pressure 150/95 mmHg",
            "BLOOD PRESSURE 150/95 MMHG",
            {"casefold"},
        ),
    ],
    ids=["crlf", "ligature", "fullwidth", "combining", "emoji", "quotes_dashes", "casefold"],
)
def test_normalized_offsets_round_trip(
    doc: str, quote: str, original: str, fired: set[str]
) -> None:
    ev = _one(doc, quote, "doc_dates")
    assert ev.position_status == "normalized"
    assert doc[ev.start : ev.end] == original
    assert fired <= set(ev.attributes["normalizations"])


def test_quote_spanning_a_line_break_with_crlf() -> None:
    doc = "No history of\r\nstroke.\r\n"
    ev = _one(
        doc,
        "No history of stroke.",
        concept="stroke",
        certainty="negated",
        temporality="historical",
    )
    assert ev.position_status == "normalized"
    assert doc[ev.start : ev.end] == "No history of\r\nstroke."
    assert ev.assertion_check == "matched"


def test_normalization_keeps_decimal_points_operators_and_negation() -> None:
    assert normalize("BMI > 34.6, no OSA").text == "bmi > 34.6, no osa"
    doc = "BMI > 34.6 measured."
    assert _one(doc, "BMI 346", "anthropometrics", raw_value="346").position_status != "normalized"
    assert (
        _one(doc, "BMI 34.6", "anthropometrics", raw_value="34.6").position_status != "normalized"
    )


def test_match_never_ends_inside_an_expansion() -> None:
    # "f" alone matches half of the ligature: not a normalized hit.
    ev = _one("Patient is ﬁt.", "Patient is f", "doc_dates")
    assert ev.position_status != "normalized"


def test_not_found_skips_layers_3_and_4() -> None:
    ev = _one("Clinic visit.", "BMI 41.0", "anthropometrics", raw_value="41.0")
    assert ev.position_status == "not_found"
    assert ev.exclusion_reasons == ("quote_not_found",)
    assert ev.start is None and ev.end is None
    assert ev.assertion_check is None and ev.certainty_checked is None
    assert ev.ref.startswith("D1[-:-] ")


def test_candidate_has_offsets_and_ratio() -> None:
    doc = "Assessment: patient reports a history of hypertension for years."
    ev = _one(doc, "history of hypertension for many years", concept="hypertension")
    assert ev.position_status == "candidate"
    assert ev.attributes["candidate_ratio"] >= CANDIDATE_RATIO
    assert ev.start is not None and ev.end is not None
    assert "hypertension" in doc[ev.start : ev.end]


def test_unknown_document_is_not_found() -> None:
    result = run_verify({"D1": "Text."}, {"diagnoses": [fact("diagnoses", "Text.", doc_id="D9")]})
    assert result.evidence[0].position_status == "not_found"


def test_repeated_quote_with_equal_assertions_is_ambiguous_match() -> None:
    doc = "Hypertension noted. Plan reviewed. Hypertension noted."
    ev = _one(doc, "Hypertension noted.", concept="hypertension")
    assert ev.position_status == "verbatim"
    assert "ambiguous_match" in ev.flags
    assert (ev.start, ev.end) == (0, 19)
    assert ev.attributes["occurrences"] == [[0, 19], [35, 54]]


def test_repeated_quote_with_differing_assertions_is_candidate() -> None:
    doc = "Mother: hypertension. Patient: no hypertension."
    ev = _one(doc, "hypertension", concept="hypertension")
    assert ev.position_status == "candidate"
    assert "ambiguous_match" not in ev.flags
    assert len(ev.attributes["occurrences"]) == 2


# --- 06 §3: similarity is not verification ----------------------------------------------------


def test_similarity_of_negated_stroke_is_high_but_assertion_catches_it() -> None:
    ratio = difflib.SequenceMatcher(None, "history of stroke", "no history of stroke").ratio()
    assert ratio > 0.9
    ev = _one(
        "No history of stroke.", "history of stroke", concept="stroke", temporality="historical"
    )
    # The substring is verbatim; the negation to its left makes it a mismatch, not support.
    assert ev.position_status == "verbatim"
    assert ev.assertion_check == "mismatch"
    assert "assertion_mismatch" in ev.exclusion_reasons


def test_changed_bmi_is_only_a_candidate_and_its_value_is_not_in_the_quote() -> None:
    ratio = difflib.SequenceMatcher(None, "BMI 35 kg/m2 at visit", "BMI 30 kg/m2 at visit").ratio()
    assert ratio > 0.9
    ev = _one(
        "BMI 30 kg/m2 at visit.",
        "BMI 35 kg/m2 at visit",
        "anthropometrics",
        raw_value="35",
        raw_unit="kg/m2",
    )
    assert ev.position_status == "candidate"
    assert "value_not_in_quote" in ev.exclusion_reasons
