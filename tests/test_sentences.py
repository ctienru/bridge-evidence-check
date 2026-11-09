from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bridge_check.sentences import SPLITTER_VERSION, sentence_containing, split_sentences


def _texts(doc: str) -> list[str]:
    return [doc[s:e] for s, e in split_sentences(doc)]


def test_version_string() -> None:
    assert SPLITTER_VERSION == "sentences-v1"


def test_plain_sentences_split_on_terminal_punctuation() -> None:
    doc = "She denies stroke. Her mother has diabetes! Any chest pain? None reported."
    assert _texts(doc) == [
        "She denies stroke.",
        "Her mother has diabetes!",
        "Any chest pain?",
        "None reported.",
    ]


@pytest.mark.parametrize(
    "doc",
    [
        "Dr. Smith saw the patient. Follow up soon.",
        "Takes metoprolol 50 mg b.i.d. and amlodipine. Follow up soon.",
        "Height approx. 170 cm was measured today. Follow up soon.",
        "She is 54 y.o. and well. Follow up soon.",
    ],
)
def test_abbreviations_do_not_split(doc: str) -> None:
    texts = _texts(doc)
    assert texts[-1] == "Follow up soon."
    assert len(texts) == 2


def test_unit_abbreviations_at_sentence_end_do_not_split() -> None:
    # Known limitation of sentences-v1: `kg.` / `cm.` / `mg.` are in the abbreviation list,
    # so a sentence that ends with a bare unit is joined to the next one.
    assert _texts("Weight 96 kg. Height 170 cm. Follow up soon.") == [
        "Weight 96 kg. Height 170 cm. Follow up soon."
    ]


def test_abbreviation_match_is_whole_token() -> None:
    assert _texts("She came first. BMI 41 noted.") == ["She came first.", "BMI 41 noted."]
    assert _texts("Seen by (Dr. Lee). Follow up soon.") == ["Seen by (Dr. Lee).", "Follow up soon."]
    assert _texts('Seen by "Dr. Lee" today. Follow up soon.') == [
        'Seen by "Dr. Lee" today.',
        "Follow up soon.",
    ]


def test_lowercase_after_period_does_not_split() -> None:
    assert _texts("The value was 5.2. the end") == ["The value was 5.2. the end"]


def test_list_items_and_blank_lines_split() -> None:
    doc = "PLAN:\n- Dietitian referral\n- Medifast for 6 weeks\n\n1. Labs\n2) Follow up"
    assert _texts(doc) == [
        "PLAN:",
        "- Dietitian referral",
        "- Medifast for 6 weeks",
        "1. Labs",
        "2) Follow up",
    ]


def test_table_rows_are_separate_sentences() -> None:
    doc = "Medications\n| drug | dose |\n| metoprolol | 50 mg |\nShe denies stroke."
    assert _texts(doc) == [
        "Medications",
        "| drug | dose |",
        "| metoprolol | 50 mg |",
        "She denies stroke.",
    ]


def test_crlf_boundaries() -> None:
    doc = "First line.\r\n\r\nSecond para.\r\n- item"
    assert _texts(doc) == ["First line.", "Second para.", "- item"]


def test_sentence_containing() -> None:
    doc = "One two. Three four."
    spans = split_sentences(doc)
    assert sentence_containing(spans, 0) == (0, 8)
    assert sentence_containing(spans, 10) == (9, 20)
    assert sentence_containing(spans, 8) == (0, 8)  # inter-sentence whitespace → previous
    with pytest.raises(ValueError):
        sentence_containing([(2, 5)], 0)


@settings(max_examples=200, deadline=None)
@given(st.text(alphabet=st.sampled_from(list("ab .?!\n\r-*|1)Z")), max_size=60))
def test_spans_cover_non_whitespace_and_are_ordered(doc: str) -> None:
    spans = split_sentences(doc)
    last_end = -1
    for start, end in spans:
        assert 0 <= start < end <= len(doc)
        assert start >= last_end
        assert not doc[start].isspace() and not doc[end - 1].isspace()
        last_end = end
    covered = {i for s, e in spans for i in range(s, e)}
    for i, ch in enumerate(doc):
        if not ch.isspace():
            assert i in covered
