"""Frozen cue table (`rules/cues-v1.yaml`, guide §3.2) and the drafting cue check.

`cue_in_sentence` is the route 1 drafting check only (planning 05 §5.2 step 3): it asks
whether the sentence holding a quote contains *some* cue for each non-default axis value
the spec asked for. The scope-aware `check_assertion` of contract §6 (cue direction,
terminators, right-hand patterns, `matched` / `mismatch` / `unrecognized`) is plan item 5
and is not implemented here.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from bridge_check.enums import AXES, AXIS_DEFAULTS

DEFAULT_CUES_PATH = Path(__file__).resolve().parents[3] / "rules" / "cues-v1.yaml"


class Cues(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    version: str = Field(pattern=r"^cues-v\d+$")
    axes: dict[str, dict[str, list[str]]]
    terminators: list[str] = Field(min_length=1)
    sentence_end: bool
    list_item_boundary: bool
    right_hand_patterns: list[str]

    @model_validator(mode="after")
    def _known_axes_and_values(self) -> Cues:
        for axis, values in self.axes.items():
            if axis not in AXES:
                raise ValueError(f"unknown axis {axis!r}")
            for value, cues in values.items():
                if value not in AXES[axis]:
                    raise ValueError(f"unknown value {value!r} for axis {axis!r}")
                if value == AXIS_DEFAULTS[axis]:
                    raise ValueError(f"default value {value!r} must not have cues")
                if not cues or any(not c for c in cues):
                    raise ValueError(f"{axis}.{value}: cue list has an empty entry")
        return self


def load_cues(path: Path = DEFAULT_CUES_PATH) -> Cues:
    with path.open(encoding="utf-8") as fh:
        return Cues.model_validate(yaml.safe_load(fh))


def _pattern(cue: str) -> re.Pattern[str]:
    escaped = re.escape(cue)
    if cue.isalpha():
        escaped = rf"\b{escaped}\b"
    return re.compile(escaped, re.IGNORECASE)


def cue_in_sentence(sentence: str, axis: str, value: str, cues: Cues) -> bool:
    """True if `sentence` contains a cue for `axis` = `value`.

    Default values are always satisfied (A-05). Matching is case-insensitive and
    word-bounded when the cue is purely alphabetic; cues with punctuation (`?`, `r/o`,
    `s/p`) match as plain substrings. Scope is not considered (see module docstring).
    """
    if axis not in AXES:
        raise ValueError(f"unknown axis {axis!r}")
    if value not in AXES[axis]:
        raise ValueError(f"unknown value {value!r} for axis {axis!r}")
    if value == AXIS_DEFAULTS[axis]:
        return True
    return any(_pattern(cue).search(sentence) for cue in cues.axes.get(axis, {}).get(value, []))
