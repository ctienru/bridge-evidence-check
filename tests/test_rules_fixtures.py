"""Each single-factor fixture under `fixtures/synthetic/rules/` through a full `bridge check`
with the scripted reply: the decisions it demonstrates (contract §3)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import FIXTURES

from bridge_check.cli import EXIT_OK, main

RULES_FIXTURES = FIXTURES / "rules"

# fixture -> {condition: (status, flags)}; `case_flags` when the fixture sets one.
EXPECTED: dict[str, dict[str, tuple[str, list[str]]]] = {
    "bmi-29.9-vs-30.1": {
        "bmi_path_b.bmi": ("conflict", []),
        "bmi_path_c.bmi": ("supported", []),
        "bmi_path_a": ("not_supported", []),
        "bmi_path_b": ("conflict", []),
    },
    "bmi-integer-30": {
        "bmi_path_b.bmi": ("review", ["imprecise_source"]),
        "bmi_path_c.bmi": ("supported", []),
        "bmi_path_a": ("not_supported", []),
    },
    "bp-140-90-exact": {"bmi_path_b.htn": ("insufficient", ["boundary_value"])},
    "htn-two-drugs": {"bmi_path_b.htn": ("supported", ["same_note_list"])},
    "htn-combination-pill": {
        "bmi_path_b.htn": ("review", ["class_ambiguous", "same_note_list"]),
    },
    "prediabetes-a1c-only": {
        "bmi_path_c.prediabetes": ("review", []),
        "exclusion.t2dm": ("insufficient", []),
    },
    "a1c-6.5-no-dx": {
        "bmi_path_c.prediabetes": ("insufficient", []),
        "exclusion.t2dm": ("review", []),
    },
    "osa-mild": {"exclusion.osa": ("not_supported", [])},
    "part-d-2025": {"exclusion.part_d_glp1": ("not_supported", [])},
    "mace-purpose": {"bmi_path_a": ("review", [])},
    "cv-history-only": {
        "bmi_path_c": ("review", ["cv_history_only"]),
        "bmi_path_c.mi": ("supported", []),
        "bmi_path_a": ("supported", []),
    },
    "age-span-18": {"age_18": ("review", [])},
    "identity-mismatch": {
        "patient_identity": ("conflict", []),
        "bmi_path_a": ("insufficient", []),
        "bmi_path_b.bmi": ("insufficient", []),
    },
    "lifestyle-commercial": {"lifestyle.nutrition": ("review", [])},
}
CASE_FLAGS: dict[str, list[str]] = {"mace-purpose": ["mace_purpose"]}
RULE_STEPS: dict[str, dict[str, str]] = {
    "bmi-integer-30": {"bmi_path_b.bmi": "bmi_path_b.bmi:6"},
    "htn-two-drugs": {"bmi_path_b.htn": "bmi_path_b.htn:3a"},
    "htn-combination-pill": {"bmi_path_b.htn": "bmi_path_b.htn:3c"},
    "mace-purpose": {"bmi_path_a": "bmi_path_a:downgrade.mace_purpose"},
    "a1c-6.5-no-dx": {"exclusion.t2dm": "exclusion.t2dm:4-lab"},
}


def test_every_fixture_has_an_expectation() -> None:
    assert {p.name for p in RULES_FIXTURES.iterdir() if p.is_dir()} == set(EXPECTED)


def _check(fixture: Path, db: Path, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    code = main(["check", str(fixture), "--db", str(db), "--json"])
    report: dict[str, Any] = json.loads(capsys.readouterr().out)
    assert code == EXIT_OK, report["dead_letters"]
    return report


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_fixture(
    name: str, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BRIDGE_FAKE_CLIENT", "1")
    report = _check(RULES_FIXTURES / name, tmp_path / "x.db", capsys)
    assert report["status"] == "completed"
    assert report["verification"]["by_position_status"] == {
        "verbatim": report["verification"]["evidence_count"]
    }
    by_id = {d["condition"]: d for d in report["decisions"]}
    got = {cid: (by_id[cid]["status"], by_id[cid]["flags"]) for cid in EXPECTED[name]}
    assert got == EXPECTED[name]
    assert report["case_flags"] == CASE_FLAGS.get(name, [])
    for cid, rule_id in RULE_STEPS.get(name, {}).items():
        assert by_id[cid]["rule_id"] == rule_id
    first_line = (RULES_FIXTURES / name / "input.yaml").read_text(encoding="utf-8").splitlines()[0]
    assert first_line.startswith("# Synthetic rules fixture:")
