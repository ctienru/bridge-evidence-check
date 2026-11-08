from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from bridge_check.rules_schema import (
    CONDITION_IDS,
    RulesTable,
    load_drugs,
    load_rules,
)

ROOT = Path(__file__).resolve().parent.parent
RULES = ROOT / "rules" / "bridge-v1.yaml"
DRUGS = ROOT / "rules" / "drugs-v1.yaml"
CHECK_RULES = ROOT / "scripts" / "check_rules.py"


@pytest.fixture
def rules_data() -> dict[str, Any]:
    with RULES.open(encoding="utf-8") as fh:
        data: dict[str, Any] = yaml.safe_load(fh)
    return data


def test_committed_rules_table_loads() -> None:
    rules = load_rules(RULES)
    assert rules.version == "bridge-v1"
    ids = {c.id for c in rules.conditions}
    expected = {i for i in CONDITION_IDS if not i.startswith("lifestyle.")}
    assert ids == expected
    assert rules.thresholds.bmi == [27, 30, 35]
    assert rules.thresholds.htn.sbp_gt == 140
    assert rules.thresholds.diabetes.a1c_pct_ge == 6.5
    assert rules.project_policies["lab_in_diabetes_range_without_dx"] == "review"
    for cond in rules.conditions:
        if cond.id.startswith("exclusion."):
            assert cond.max_status == "review"


def test_committed_drug_table_loads() -> None:
    drugs = load_drugs(DRUGS)
    assert drugs.version == 1
    combos = [d for d in drugs.drugs if d.components]
    for combo in combos:
        assert len(combo.components or []) >= 2


def test_unknown_condition_id_is_rejected(rules_data: dict[str, Any]) -> None:
    data = copy.deepcopy(rules_data)
    data["conditions"][0]["id"] = "bmi_path_d"
    with pytest.raises(ValidationError, match="unknown condition id"):
        RulesTable.model_validate(data)


def test_unknown_source_id_is_rejected(rules_data: dict[str, Any]) -> None:
    data = copy.deepcopy(rules_data)
    data["conditions"][0]["source"]["id"] = "blog"
    with pytest.raises(ValidationError, match="not in policy_snapshot.sources"):
        RulesTable.model_validate(data)


def test_max_status_other_than_review_is_rejected(rules_data: dict[str, Any]) -> None:
    data = copy.deepcopy(rules_data)
    exclusion = next(c for c in data["conditions"] if c["id"] == "exclusion.t2dm")
    exclusion["max_status"] = "supported"
    with pytest.raises(ValidationError, match="max_status"):
        RulesTable.model_validate(data)


def test_exclusion_without_max_status_is_rejected(rules_data: dict[str, Any]) -> None:
    data = copy.deepcopy(rules_data)
    exclusion = next(c for c in data["conditions"] if c["id"] == "exclusion.osa")
    del exclusion["max_status"]
    with pytest.raises(ValidationError, match="must declare max_status"):
        RulesTable.model_validate(data)


def test_unknown_requires_name_is_rejected(rules_data: dict[str, Any]) -> None:
    data = copy.deepcopy(rules_data)
    data["conditions"][0]["requires"] = ["bmi"]
    with pytest.raises(ValidationError, match="unknown compute names"):
        RulesTable.model_validate(data)


def test_display_word_as_policy_value_is_rejected(rules_data: dict[str, Any]) -> None:
    data = copy.deepcopy(rules_data)
    data["project_policies"]["bmi_precision_unknown"] = "needs review"
    with pytest.raises(ValidationError, match="machine status code"):
        RulesTable.model_validate(data)


def test_extra_field_is_rejected(rules_data: dict[str, Any]) -> None:
    data = copy.deepcopy(rules_data)
    data["conditions"][0]["note"] = "x"
    with pytest.raises(ValidationError):
        RulesTable.model_validate(data)


def _run_check_rules(*args: str) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(CHECK_RULES), *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=ROOT)


def test_check_rules_passes_on_committed_tables() -> None:
    result = _run_check_rules()
    assert result.returncode == 0, result.stderr
    assert "conditions: 18" in result.stdout


def _tables_without_markers(tmp_path: Path) -> tuple[Path, Path]:
    rules = tmp_path / "bridge-v1.yaml"
    drugs = tmp_path / "drugs-v1.yaml"
    for src, dst in ((RULES, rules), (DRUGS, drugs)):
        text = src.read_text(encoding="utf-8")
        dst.write_text(
            text.replace("REVIEW(terri)", "verified").replace("TODO(terri)", "verified"),
            encoding="utf-8",
        )
    return rules, drugs


@pytest.mark.parametrize("marker", ["TODO(terri)", "REVIEW(terri)"])
def test_check_rules_require_complete_fails_while_markers_remain(
    tmp_path: Path, marker: str
) -> None:
    rules, drugs = _tables_without_markers(tmp_path)
    drugs.write_text(
        drugs.read_text(encoding="utf-8") + f"# {marker}: add the case 02 drugs\n", encoding="utf-8"
    )
    result = _run_check_rules("--require-complete", "--rules", str(rules), "--drugs", str(drugs))
    assert result.returncode == 1
    assert "human-pending marker" in result.stderr
    assert "drugs-v1.yaml" in result.stderr
    # Without the flag the same tables pass: markers are not validation errors.
    assert _run_check_rules("--rules", str(rules), "--drugs", str(drugs)).returncode == 0


def test_check_rules_require_complete_passes_without_markers(tmp_path: Path) -> None:
    rules, drugs = _tables_without_markers(tmp_path)
    result = _run_check_rules("--require-complete", "--rules", str(rules), "--drugs", str(drugs))
    assert result.returncode == 0, result.stderr
    assert "no human-pending markers" in result.stdout


def test_check_rules_fails_on_invalid_table(tmp_path: Path) -> None:
    bad = tmp_path / "bridge-v1.yaml"
    bad.write_text("version: bridge-v1\n", encoding="utf-8")
    result = _run_check_rules("--rules", str(bad))
    assert result.returncode == 1
    assert "validation error" in result.stderr
