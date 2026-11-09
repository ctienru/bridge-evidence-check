"""`Policy`: typed switches from `rules/bridge-v1.yaml` (contract §7.3, §10)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from conftest import ROOT, policy

from bridge_check.rules import IMPLEMENTED, Policy, UnsupportedPolicyValue
from bridge_check.rules_schema import load_rules

RULES = load_rules(ROOT / "rules" / "bridge-v1.yaml")


def _data(**over: object) -> dict[str, object]:
    return {
        **RULES.project_policies,
        "thresholds": RULES.thresholds,
        "rules_version": RULES.version,
        **over,
    }


def test_policy_loads_the_committed_table() -> None:
    p = policy()
    assert p.rules_version == "bridge-v1"
    assert p.bmi_thresholds == (Decimal("27"), Decimal("30"), Decimal("35"))
    assert p.age_years == 18
    assert p.prediabetes_a1c == (Decimal("5.7"), Decimal("6.4"))
    assert p.diabetes_fpg == Decimal("126")
    assert p.ckd_egfr_lt == Decimal("60")
    assert p.osa_ahi_ge == Decimal("15")
    assert p.lab_in_diabetes_range_without_dx == "review"


def test_every_yaml_policy_key_is_implemented() -> None:
    assert set(RULES.project_policies) == set(IMPLEMENTED)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("bmi_comparison", "rounded"),
        ("htn_not_supported_by_readings", True),
        ("lab_in_diabetes_range_without_dx", "conflict"),
        ("initiation_bmi_accepts", ["at", "before"]),
        ("bp_threshold_strict", False),
        ("a_policy_nobody_implemented", "review"),
    ],
)
def test_policy_rejects_unimplemented_values(key: str, value: object) -> None:
    with pytest.raises(UnsupportedPolicyValue) as exc:
        Policy.model_validate(_data(**{key: value}))
    assert exc.value.key == key


BOOLEANS = [k for k, v in IMPLEMENTED.items() if v == frozenset({True, False})]


def test_three_policies_are_real_switches() -> None:
    assert sorted(BOOLEANS) == [
        "bmi_bucket_from_raw",
        "htn_not_supported_by_complete_list",
        "path_c_cv_history_requires_review",
    ]


@pytest.mark.parametrize("key", BOOLEANS)
@pytest.mark.parametrize("value", [True, False])
def test_boolean_policies_load_with_both_values(key: str, value: bool) -> None:
    p = Policy.model_validate(_data(**{key: value}))
    assert getattr(p, key) is value
