from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from bridge_check.dataside.cues import DEFAULT_CUES_PATH, Cues, cue_in_sentence, load_cues
from bridge_check.enums import AXES, AXIS_DEFAULTS


@pytest.fixture(scope="module")
def cues() -> Cues:
    return load_cues()


def test_frozen_table_loads_with_every_non_default_value(cues: Cues) -> None:
    assert cues.version == "cues-v1"
    for axis, values in AXES.items():
        for value in values:
            if value != AXIS_DEFAULTS[axis]:
                assert cues.axes[axis][value], f"{axis}.{value} has no cues"
    assert cues.terminators == ["but", "however", "except", ";"]
    assert cues.sentence_end and cues.list_item_boundary
    assert "ruled out" in cues.right_hand_patterns and "?" in cues.right_hand_patterns


def test_negated_with_denies(cues: Cues) -> None:
    assert cue_in_sentence("She denies any stroke.", "certainty", "negated", cues)
    assert cue_in_sentence("Negative for chest pain.", "certainty", "negated", cues)


def test_family_with_mother(cues: Cues) -> None:
    assert cue_in_sentence("Her mother has diabetes.", "subject", "family", cues)


def test_default_values_always_true(cues: Cues) -> None:
    for axis, default in AXIS_DEFAULTS.items():
        assert cue_in_sentence("Weight 96 kg.", axis, default, cues)


def test_no_cue_is_false(cues: Cues) -> None:
    assert not cue_in_sentence("Her BMI was 41.2 kg/m2.", "certainty", "negated", cues)
    assert not cue_in_sentence("Her BMI was 41.2 kg/m2.", "subject", "family", cues)
    assert not cue_in_sentence("There is diabetes in the household.", "subject", "family", cues)


def test_alphabetic_cues_need_word_boundaries(cues: Cues) -> None:
    # "nothing" contains "no" but is not a negation cue; "?" has no boundary requirement
    assert not cue_in_sentence("Nothing abnormal was found", "certainty", "negated", cues)
    assert cue_in_sentence("?HFpEF on echo", "certainty", "uncertain", cues)
    assert cue_in_sentence("s/p CABG", "temporality", "historical", cues)


def test_unknown_axis_or_value_raises(cues: Cues) -> None:
    with pytest.raises(ValueError):
        cue_in_sentence("x", "mood", "negated", cues)
    with pytest.raises(ValueError):
        cue_in_sentence("x", "certainty", "maybe", cues)


def test_table_rejects_unknown_value_and_default_cues(tmp_path: Path) -> None:
    data = yaml.safe_load(DEFAULT_CUES_PATH.read_text(encoding="utf-8"))
    data["axes"]["certainty"]["present"] = ["yes"]
    with pytest.raises(ValidationError):
        Cues.model_validate(data)
    data = yaml.safe_load(DEFAULT_CUES_PATH.read_text(encoding="utf-8"))
    data["axes"]["certainty"]["maybe"] = ["perhaps"]
    with pytest.raises(ValidationError):
        Cues.model_validate(data)
