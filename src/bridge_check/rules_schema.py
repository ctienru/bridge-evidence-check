"""Pydantic models for the human-maintained rules tables.

`rules/bridge-v1.yaml` holds the policy snapshot, thresholds, one entry per condition
and the project-specific policies; `rules/drugs-v1.yaml` holds the antihypertensive
drug table. Machine names (condition IDs, status codes) follow `docs/contracts.md`
(planning doc 13 §1–§2). The `rule` field of a condition is human-readable only; the
real decision functions live in `rules.py` (later item).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# --- Machine codes (13 §1) -----------------------------------------------------------

Status = Literal["supported", "not_supported", "insufficient", "conflict", "review"]
STATUS_CODES: tuple[str, ...] = ("supported", "not_supported", "insufficient", "conflict", "review")

# --- Condition and sub-result IDs (13 §2) --------------------------------------------

CONDITION_IDS: tuple[str, ...] = (
    "age_18",
    "bmi_path_a",
    "bmi_path_b",
    "bmi_path_b.bmi",
    "bmi_path_b.hfpef",
    "bmi_path_b.htn",
    "bmi_path_b.ckd",
    "bmi_path_c",
    "bmi_path_c.bmi",
    "bmi_path_c.prediabetes",
    "bmi_path_c.mi",
    "bmi_path_c.stroke",
    "bmi_path_c.pad",
    "exclusion.t2dm",
    "exclusion.osa",
    "exclusion.mash",
    "exclusion.part_d_glp1",
    "patient_identity",
    "lifestyle.nutrition",
    "lifestyle.activity",
)
"""Every fixed condition ID. `claim.<id>` entries are dynamic and are not rules-table rows."""

EXCLUSION_IDS: tuple[str, ...] = tuple(i for i in CONDITION_IDS if i.startswith("exclusion."))

# String values allowed in `project_policies`: a machine status code (13 §1) or one of the
# non-status enum values used by 06 §3.7.
POLICY_STRING_VALUES: frozenset[str] = frozenset(STATUS_CODES) | {
    "unrounded",
    "not_ongoing",
    "unknown",
}

# Names a condition may list in `requires` (13 §7.3, middle column).
COMPUTE_NAMES: tuple[str, ...] = (
    "doc_facts.identity_status",
    "wrong_patient",
    "initiation_date",
    "initiation_purpose",
    "doc_facts.doc_date",
    "age_interval_at_initiation",
    "bmi_candidates",
    "bp_at_initiation",
    "med_periods",
    "distinct_antihypertensives_overlapping",
    "a1c",
    "fpg_mg_dl",
    "egfr",
    "dx",
    "prior_glp1",
    "lifestyle_applicable",
    "bmi_bracket",
)

# Antihypertensive drug classes used in `rules/drugs-v1.yaml`. `class` only decides
# whether a drug is an antihypertensive; de-duplication uses `drug_canonical` (13 §3.2).
DrugClass = Literal[
    "ace_inhibitor",
    "arb",
    "beta_blocker",
    "calcium_channel_blocker",
    "thiazide_diuretic",
    "loop_diuretic",
    "potassium_sparing_diuretic",
    "mineralocorticoid_receptor_antagonist",
    "alpha_blocker",
    "central_alpha_agonist",
    "vasodilator",
    "sglt2_inhibitor",
    "other",
]
ANTIHYPERTENSIVE_CLASSES: frozenset[str] = frozenset(
    {
        "ace_inhibitor",
        "arb",
        "beta_blocker",
        "calcium_channel_blocker",
        "thiazide_diuretic",
        "loop_diuretic",
        "potassium_sparing_diuretic",
        "mineralocorticoid_receptor_antagonist",
        "alpha_blocker",
        "central_alpha_agonist",
        "vasodilator",
    }
)


class _Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


# --- rules/bridge-v1.yaml -----------------------------------------------------------


class PolicySource(_Strict):
    id: str = Field(min_length=1)
    doc: str = Field(min_length=1)
    url: str = Field(pattern=r"^https://")
    last_modified: date | None = None


class PolicySnapshot(_Strict):
    accessed: date
    sources: list[PolicySource] = Field(min_length=1)

    @field_validator("sources")
    @classmethod
    def _unique_ids(cls, sources: list[PolicySource]) -> list[PolicySource]:
        ids = [s.id for s in sources]
        if len(ids) != len(set(ids)):
            raise ValueError("policy_snapshot.sources ids must be unique")
        return sources


class HtnThresholds(_Strict):
    sbp_gt: int
    dbp_gt: int
    min_drugs: int


class PrediabetesThresholds(_Strict):
    a1c_pct: list[float] = Field(min_length=2, max_length=2)
    fpg_mg_dl: list[int] = Field(min_length=2, max_length=2)


class DiabetesThresholds(_Strict):
    a1c_pct_ge: float
    fpg_mg_dl_ge: int


class Thresholds(_Strict):
    bmi: list[int] = Field(min_length=3, max_length=3)
    age: int
    htn: HtnThresholds
    prediabetes: PrediabetesThresholds
    diabetes: DiabetesThresholds
    ckd_3a_egfr_lt: int
    osa_moderate_ahi_ge: int

    @field_validator("bmi")
    @classmethod
    def _bmi_ascending(cls, bmi: list[int]) -> list[int]:
        if bmi != sorted(bmi):
            raise ValueError("thresholds.bmi must be ascending")
        return bmi


class ConditionSource(_Strict):
    id: str = Field(min_length=1)
    quote: str = Field(min_length=1)


class Condition(_Strict):
    id: str
    requires: list[str] = Field(min_length=1)
    rule: str = Field(min_length=1)
    max_status: Literal["review"] | None = None
    source: ConditionSource

    @field_validator("id")
    @classmethod
    def _known_id(cls, value: str) -> str:
        if value not in CONDITION_IDS:
            raise ValueError(f"unknown condition id {value!r}")
        return value

    @field_validator("requires")
    @classmethod
    def _known_requires(cls, names: list[str]) -> list[str]:
        unknown = [n for n in names if n not in COMPUTE_NAMES]
        if unknown:
            raise ValueError(f"unknown compute names in requires: {unknown}")
        return names


class RulesTable(_Strict):
    version: str = Field(pattern=r"^bridge-v\d+$")
    policy_snapshot: PolicySnapshot
    thresholds: Thresholds
    conditions: list[Condition] = Field(min_length=1)
    project_policies: dict[str, bool | str | list[str]]

    @model_validator(mode="after")
    def _cross_checks(self) -> RulesTable:
        source_ids = {s.id for s in self.policy_snapshot.sources}
        seen: set[str] = set()
        for cond in self.conditions:
            if cond.id in seen:
                raise ValueError(f"duplicate condition id {cond.id!r}")
            seen.add(cond.id)
            if cond.source.id not in source_ids:
                raise ValueError(
                    f"condition {cond.id!r}: source.id {cond.source.id!r} "
                    "is not in policy_snapshot.sources"
                )
            if cond.id in EXCLUSION_IDS and cond.max_status != "review":
                raise ValueError(f"exclusion {cond.id!r} must declare max_status: review")
        for key, value in self.project_policies.items():
            if isinstance(value, str) and value not in POLICY_STRING_VALUES:
                raise ValueError(
                    f"project_policies.{key}: {value!r} is not a machine status code "
                    f"or a known policy value {sorted(POLICY_STRING_VALUES)}"
                )
        return self


# --- rules/drugs-v1.yaml ------------------------------------------------------------


class DrugComponent(_Strict):
    drug_canonical: str = Field(min_length=1)
    class_: DrugClass = Field(alias="class")


class Drug(_Strict):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, populate_by_name=True)

    names: list[str] = Field(min_length=1)
    drug_canonical: str = Field(min_length=1)
    class_: DrugClass = Field(alias="class")
    class_ambiguous: bool = False
    components: list[DrugComponent] | None = None

    @model_validator(mode="after")
    def _combination_shape(self) -> Drug:
        if self.components is not None and len(self.components) < 2:
            raise ValueError(f"drug {self.drug_canonical!r}: components needs at least 2 entries")
        return self


class DrugTable(_Strict):
    version: int
    drugs: list[Drug]

    @model_validator(mode="after")
    def _unique_names(self) -> DrugTable:
        seen: dict[str, str] = {}
        for drug in self.drugs:
            for name in drug.names:
                key = name.casefold()
                if key in seen and seen[key] != drug.drug_canonical:
                    raise ValueError(f"drug name {name!r} maps to two canonical drugs")
                seen[key] = drug.drug_canonical
        return self


# --- Loaders ------------------------------------------------------------------------


def _read_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_rules(path: Path) -> RulesTable:
    """Load and validate `rules/bridge-v1.yaml`. Raises `pydantic.ValidationError`."""
    return RulesTable.model_validate(_read_yaml(path))


def load_drugs(path: Path) -> DrugTable:
    """Load and validate `rules/drugs-v1.yaml`. Raises `pydantic.ValidationError`."""
    return DrugTable.model_validate(_read_yaml(path))
