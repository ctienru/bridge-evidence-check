"""Decision rules over `ComputedFacts` (contract §1–§3, §10).

Every table is evaluated top to bottom and the first matching row is the result; step 0
(dropping excluded evidence) already happened in `compute`. Thresholds and policies come from
`rules/bridge-v1.yaml` through `Policy`; no threshold is written in this module. The registry
`RULES` holds exactly the condition ids of the rules table; lifestyle and claim decisions are
produced by `LIFESTYLE_RULES` and `claim_rule` and are reported separately (contract §2).

Reasons name evidence as `doc_id[start:end] sha8` plus machine codes and numbers; no document
text, drug names or patient data appear in a decision.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from bridge_check.compute import (
    AGE_TOLERANCE_YEARS,
    BMI_TOLERANCE,
    EXACT,
    GLP1_BRANDS,
    AgeInterval,
    ComputedFacts,
    DateInterval,
    Dx,
    LabValue,
    Source,
    compare_values,
    glp1_canonical,
    parse_bracket,
    same_timepoint,
)
from bridge_check.enums import (
    CLAIM_PREFIX,
    CONDITION_EXCLUSION_REASONS,
    CONDITION_IDS,
    DecisionKind,
    Flag,
    Status,
)
from bridge_check.rules_schema import RulesTable, Thresholds

# --- Policy ---------------------------------------------------------------------------------------


class UnsupportedPolicyValue(Exception):
    """A `project_policies` key or value that `rules.py` does not implement."""

    def __init__(self, key: str, value: object) -> None:
        super().__init__(f"project_policies.{key}: {value!r} is not implemented")
        self.key = key
        self.value = value


# Implemented values per policy key. Booleans are implemented both ways; enum policies only
# with the listed values (contract §7.3). Lists are compared as tuples.
IMPLEMENTED: dict[str, frozenset[object]] = {
    "bmi_comparison": frozenset({"unrounded"}),
    "bmi_precision_unknown": frozenset({"review"}),
    "bmi_bucket_from_raw": frozenset({True, False}),
    "initiation_bmi_accepts": frozenset({("at",)}),
    "path_c_cv_history_requires_review": frozenset({True, False}),
    "htn_not_supported_by_complete_list": frozenset({True, False}),
    "htn_not_supported_by_readings": frozenset({False}),
    "lab_in_diabetes_range_without_dx": frozenset({"review"}),
    "unknown_med_period": frozenset({"not_ongoing"}),
    "combination_pill_counts_as_two": frozenset({"review"}),
    "fatty_liver_is_mash": frozenset({False}),
    "pediatric_bmi_percentile_is_bmi": frozenset({False}),
    "mash_noninvasive_staging_counts": frozenset({"review"}),
    "payer_from_amount_only": frozenset({"unknown"}),
    "pa_draft_claims_support_alone": frozenset({False}),
    "mace_purpose_all_pathways": frozenset({"review"}),
    "a1c_prediabetes_range_without_dx": frozenset({"review"}),
    "ckd_dx_egfr_only": frozenset({"review"}),
    "bp_threshold_strict": frozenset({True}),
    "infer_dx_from_drug": frozenset({False}),
}


def _d(value: float | int) -> Decimal:
    return Decimal(str(value))


class Policy(BaseModel):
    """The project policies of `rules/bridge-v1.yaml` as typed switches, plus the thresholds."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    thresholds: Thresholds
    rules_version: str
    bmi_comparison: Literal["unrounded"]
    bmi_precision_unknown: Literal["review"]
    bmi_bucket_from_raw: bool
    initiation_bmi_accepts: list[Literal["at"]]
    path_c_cv_history_requires_review: bool
    htn_not_supported_by_complete_list: bool
    htn_not_supported_by_readings: Literal[False]
    lab_in_diabetes_range_without_dx: Literal["review"]
    unknown_med_period: Literal["not_ongoing"]
    combination_pill_counts_as_two: Literal["review"]
    fatty_liver_is_mash: Literal[False]
    pediatric_bmi_percentile_is_bmi: Literal[False]
    mash_noninvasive_staging_counts: Literal["review"]
    payer_from_amount_only: Literal["unknown"]
    pa_draft_claims_support_alone: Literal[False]
    mace_purpose_all_pathways: Literal["review"]
    a1c_prediabetes_range_without_dx: Literal["review"]
    ckd_dx_egfr_only: Literal["review"]
    bp_threshold_strict: Literal[True]
    infer_dx_from_drug: Literal[False]

    @model_validator(mode="before")
    @classmethod
    def _implemented(cls, data: Any) -> Any:
        if isinstance(data, Mapping):
            for key, value in data.items():
                if key in ("thresholds", "rules_version"):
                    continue
                allowed = IMPLEMENTED.get(str(key))
                probe = tuple(value) if isinstance(value, list) else value
                if allowed is None or probe not in allowed:
                    raise UnsupportedPolicyValue(str(key), value)
        return data

    @classmethod
    def from_rules(cls, table: RulesTable) -> Policy:
        return cls.model_validate(
            {
                **table.project_policies,
                "thresholds": table.thresholds,
                "rules_version": table.version,
            }
        )

    # Decimal views of the thresholds (contract §10); compared with the unrounded values.
    @property
    def bmi_thresholds(self) -> tuple[Decimal, Decimal, Decimal]:
        a, b, c = self.thresholds.bmi
        return _d(a), _d(b), _d(c)

    @property
    def age_years(self) -> int:
        return self.thresholds.age

    @property
    def prediabetes_a1c(self) -> tuple[Decimal, Decimal]:
        lo, hi = self.thresholds.prediabetes.a1c_pct
        return _d(lo), _d(hi)

    @property
    def prediabetes_fpg(self) -> tuple[Decimal, Decimal]:
        lo, hi = self.thresholds.prediabetes.fpg_mg_dl
        return _d(lo), _d(hi)

    @property
    def diabetes_a1c(self) -> Decimal:
        return _d(self.thresholds.diabetes.a1c_pct_ge)

    @property
    def diabetes_fpg(self) -> Decimal:
        return _d(self.thresholds.diabetes.fpg_mg_dl_ge)

    @property
    def ckd_egfr_lt(self) -> Decimal:
        return _d(self.thresholds.ckd_3a_egfr_lt)

    @property
    def osa_ahi_ge(self) -> Decimal:
        return _d(self.thresholds.osa_moderate_ahi_ge)


# --- Decision ------------------------------------------------------------------------------------


class ExcludedEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: int
    reason: str

    @field_validator("reason")
    @classmethod
    def _known(cls, v: str) -> str:
        if v not in CONDITION_EXCLUSION_REASONS:
            raise ValueError(f"unknown condition-level exclusion reason {v!r}")
        return v


class Decision(BaseModel):
    """One row of `decisions` (contract §2, §11)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    condition: str
    kind: DecisionKind
    status: Status
    reason: str
    rule_id: str
    rules_version: str
    used_evidence: tuple[int, ...] = ()
    excluded_evidence: tuple[ExcludedEvidence, ...] = ()
    computed: dict[str, Any] = {}
    flags: tuple[Flag, ...] = ()

    @field_validator("condition")
    @classmethod
    def _known_condition(cls, v: str) -> str:
        if v not in CONDITION_IDS and not v.startswith(CLAIM_PREFIX):
            raise ValueError(f"unknown condition id {v!r}")
        return v

    @model_validator(mode="after")
    def _invariants(self) -> Decision:
        if self.kind == "exclusion" and self.status == "supported":
            raise ValueError("exclusion sub-results are never supported")
        return self


@dataclass(frozen=True)
class RuleInput:
    facts: ComputedFacts
    policy: Policy
    decided: Mapping[str, Decision]

    def sources(self, evidence_ids: Iterable[int]) -> list[Source]:
        """The `Source` rows behind evidence ids (for a claim reading its condition)."""
        index = _source_index(self.facts)
        return [index[i] for i in evidence_ids if i in index]


def _source_index(facts: ComputedFacts) -> dict[int, Source]:
    out: dict[int, Source] = {}
    rows: list[Source] = [
        *(a.src for a in facts.age_interval_at_initiation),
        *(s for c in facts.bmi_candidates for s in c.sources),
        *(r.src for r in facts.bp_readings),
        *(p.src for p in facts.med_periods),
        *(m.src for m in facts.medication_lists),
        *(v.src for v in (*facts.a1c, *facts.fpg_mg_dl, *facts.egfr)),
        *(d.src for d in facts.dx),
        *(r.src for r in facts.prior_glp1),
        *(r.src for r in facts.lifestyle_applicable),
        *(c.src for c in facts.claims),
        *(f.doc_date_src for f in facts.doc_facts.values() if f.doc_date_src is not None),
    ]
    if facts.initiation is not None:
        rows.append(facts.initiation.src)
    for src in rows:
        out.setdefault(src.evidence_id, src)
    return out


RuleFn = Callable[[RuleInput], Decision]

# "How much a human needs to look" (contract §1); conclusions are not ranked.
_RANK: dict[str, int] = {"conflict": 3, "review": 2, "insufficient": 1}
_SUPPORT_RANK: dict[str, int] = {
    "not_supported": 0,
    "insufficient": 1,
    "review": 2,
    "conflict": 3,
    "supported": 4,
}
_STEP8_FLAGS = frozenset({"table_source", "timing_disagreement", "unrecognized"})
_TIMING_REASON: dict[str, str] = {
    "before": "before_initiation",
    "after": "after_initiation",
    "unknown": "timing_unknown",
}


def kind_of(condition: str) -> DecisionKind:
    """The `decisions.kind` of a condition, sub-result, exclusion, lifestyle or claim id."""
    if condition.startswith(CLAIM_PREFIX):
        return "claim"
    if condition.startswith("exclusion."):
        return "exclusion"
    if condition.startswith("lifestyle."):
        return "lifestyle"
    if "." in condition:
        return "sub"
    if condition.startswith("bmi_path_"):
        return "path"
    return "condition"


def _decision(
    ri: RuleInput,
    condition: str,
    status: Status,
    step: str,
    reason: str,
    *,
    used: Iterable[Source] = (),
    excluded: Iterable[tuple[Source, str]] = (),
    computed: Mapping[str, Any] | None = None,
    flags: Iterable[str] = (),
    timing_sensitive: bool = False,
) -> Decision:
    used_list = _with_anchors(ri, used)
    used_ids = tuple(sorted({s.evidence_id for s in used_list}))
    flag_set: set[str] = set(flags)
    # Flags of the evidence used are recorded on the decision; table-sourced or unrecognized
    # evidence caps any decision at `review` (contract §6), a timing disagreement only the
    # decisions that rest on the initiation timepoint (§3.1 step 8: BMI and its bracket).
    carried = {f for s in used_list for f in s.flags} & _STEP8_FLAGS
    capping = carried if timing_sensitive else carried - {"timing_disagreement"}
    if status == "supported" and capping:
        status = "review"
        step = f"{step}-flagged"
        reason = f"{reason}; evidence carries {sorted(capping)}"
        flag_set |= capping
    seen: dict[int, str] = {}
    for src, why in excluded:
        if src.evidence_id not in used_ids:
            seen.setdefault(src.evidence_id, why)
    return Decision(
        condition=condition,
        kind=kind_of(condition),
        status=status,
        reason=reason,
        rule_id=f"{condition}:{step}",
        rules_version=ri.policy.rules_version,
        used_evidence=used_ids,
        excluded_evidence=tuple(
            ExcludedEvidence(evidence_id=i, reason=seen[i]) for i in sorted(seen)
        ),
        computed=dict(computed or {}),
        flags=tuple(sorted(flag_set)),  # type: ignore[arg-type]
    )


def _with_anchors(ri: RuleInput, sources: Iterable[Source]) -> list[Source]:
    """`sources` plus the rows their timepoints rest on: the verified `doc_dates` row of an
    inherited date and the initiation sentence for any `at`/`before`/`after` judgement."""
    out = list(sources)
    seen = {s.evidence_id for s in out}
    for src in list(out):
        if src.tp.source == "doc_date":
            anchor = ri.facts.doc_facts.get(src.doc_id)
            date_src = anchor.doc_date_src if anchor else None
            if date_src is not None and date_src.evidence_id not in seen:
                out.append(date_src)
                seen.add(date_src.evidence_id)
        if src.tp.relative != "unknown" and ri.facts.initiation is not None:
            init = ri.facts.initiation.src
            if init.evidence_id not in seen:
                out.append(init)
                seen.add(init.evidence_id)
    return out


def _refs(sources: Iterable[Source]) -> str:
    return ", ".join(s.ref for s in sources) or "none"


def _candidates_of(ri: RuleInput, *fields: str) -> list[tuple[Source, str]]:
    return [(s, "candidate_only") for s in ri.facts.candidate_only if s.field in fields]


def _timing_excluded(sources: Iterable[Source], keep: tuple[str, ...]) -> list[tuple[Source, str]]:
    return [(s, _TIMING_REASON[s.tp.relative]) for s in sources if s.tp.relative not in keep]


# --- BMI (contract §3.1) --------------------------------------------------------------------------


def decide_bmi(ri: RuleInput, condition: str, threshold: Decimal) -> Decision:
    facts = ri.facts
    cands = facts.bmi_candidates
    accepted = tuple(ri.policy.initiation_bmi_accepts)
    at = [c for c in cands if c.tp.relative in accepted]
    all_sources = [s for c in cands for s in c.sources]
    excluded = _timing_excluded(
        (s for s in all_sources if s.field == "anthropometrics" and s.tp.relative not in accepted),
        accepted,
    ) + _candidates_of(ri, "anthropometrics")
    computed: dict[str, Any] = {"threshold": str(threshold)}
    if facts.initiation is None:
        computed["initiation_date"] = None
        return _decision(
            ri,
            condition,
            "insufficient",
            "2",
            "no verified GLP-1 initiation date; no measurement can be at initiation",
            excluded=excluded,
            computed=computed,
            timing_sensitive=True,
        )
    computed["initiation_date"] = facts.initiation.date.iso()
    if not at:
        if any(c.tp.relative == "before" for c in cands):
            return _decision(
                ri,
                condition,
                "review",
                "2",
                "no measurement at initiation; only measurements before initiation",
                excluded=excluded,
                computed=computed,
            )
        return _decision(
            ri,
            condition,
            "insufficient",
            "2",
            "no weight or BMI at initiation",
            excluded=excluded,
            computed=computed,
            timing_sensitive=True,
        )
    used = [s for c in at for s in c.sources] + [facts.initiation.src]
    computed["candidates"] = [
        {"value": str(c.value), "origin": c.origin, "evidence": list(c.evidence_ids)} for c in at
    ]
    values = [c.value for c in at]
    cmp = compare_values(values, [threshold], BMI_TOLERANCE)
    if threshold in cmp.straddled:
        return _decision(
            ri,
            condition,
            "conflict",
            "4",
            f"candidate BMI values {cmp.low} and {cmp.high} fall on both sides of {threshold}",
            used=used,
            excluded=excluded,
            computed=computed,
            timing_sensitive=True,
        )
    flags: set[str] = set()
    if cmp.inconsistent:
        flags.add("inconsistent_values")
    computed_cands = [c for c in at if c.origin == "computed"]
    chosen = computed_cands[0] if computed_cands else at[0]
    bmi_raw = chosen.value
    computed["bmi_raw"] = str(bmi_raw)
    if ri.policy.bmi_bucket_from_raw:
        computed["bracket"] = facts.bmi_bracket.label() if facts.bmi_bracket else None
    if not computed_cands and all(c.integer_only for c in at):
        imprecise = [
            c
            for c in at
            if c.value.to_integral_value("ROUND_FLOOR") <= threshold < c.value + Decimal("0.5")
        ]
        if imprecise:
            flags.add("imprecise_source")
            return _decision(
                ri,
                condition,
                "review",
                "6",
                f"integer BMI {imprecise[0].value} without height and weight may cross {threshold}",
                used=used,
                excluded=excluded,
                computed=computed,
                flags=flags,
            )
    for c in at:
        flags |= c.all_flags & {"height_from_other_date"}
    if bmi_raw >= threshold:
        risky = {f for c in at for f in c.all_flags} & _STEP8_FLAGS
        if risky:
            flags |= risky
            return _decision(
                ri,
                condition,
                "review",
                "8",
                f"bmi_raw {bmi_raw} >= {threshold} but the evidence carries {sorted(risky)}",
                used=used,
                excluded=excluded,
                computed=computed,
                flags=flags,
            )
        return _decision(
            ri,
            condition,
            "supported",
            "7",
            f"bmi_raw {bmi_raw} >= {threshold} at initiation ({_refs(used)})",
            used=used,
            excluded=excluded,
            computed=computed,
            flags=flags,
            timing_sensitive=True,
        )
    return _decision(
        ri,
        condition,
        "not_supported",
        "7",
        f"bmi_raw {bmi_raw} < {threshold} at initiation ({_refs(used)})",
        used=used,
        excluded=excluded,
        computed=computed,
        flags=flags,
    )


# --- Diagnoses (contract §3.2, §4) ----------------------------------------------------------------


def _patient_dx(
    ri: RuleInput, concept: str, *, pathway: bool
) -> tuple[list[Dx], list[tuple[Source, str]]]:
    """Patient-subject diagnoses of `concept`; pathway sub-results drop `after` rows."""
    rows = [d for d in ri.facts.dx if d.concept == concept and d.src.subject == "patient"]
    excluded = _candidates_of(ri, "diagnoses")
    if pathway:
        excluded += [(d.src, "after_initiation") for d in rows if d.src.tp.relative == "after"]
        rows = [d for d in rows if d.src.tp.relative != "after"]
    return rows, excluded


def _dx_conflict(rows: Sequence[Dx]) -> tuple[Dx, Dx] | None:
    positives = [d for d in rows if d.src.certainty == "present"]
    negatives = [d for d in rows if d.src.negated]
    for p in positives:
        for n in negatives:
            if same_timepoint(p.src.tp, n.src.tp, p.src.doc_id == n.src.doc_id):
                return p, n
    return None


def _dx_flags(rows: Iterable[Dx]) -> set[str]:
    """Flags that make a diagnosis-based result `review`; a diagnosis is judged by its own
    timepoint rules, so a timing disagreement is recorded but does not cap it."""
    return {f for d in rows for f in d.src.flags if f in _STEP8_FLAGS - {"timing_disagreement"}}


def _simple_dx(ri: RuleInput, condition: str, concept: str) -> Decision:
    rows, excluded = _patient_dx(ri, concept, pathway=True)
    pair = _dx_conflict(rows)
    if pair is not None:
        return _decision(
            ri,
            condition,
            "conflict",
            "conflict",
            f"{concept} asserted and denied at the same timepoint ({_refs(p.src for p in pair)})",
            used=(p.src for p in pair),
            excluded=excluded,
        )
    affirmed = [d for d in rows if d.src.affirmed]
    if affirmed:
        flags = _dx_flags(affirmed)
        status: Status = "review" if flags else "supported"
        return _decision(
            ri,
            condition,
            status,
            "1" if not flags else "1-review",
            f"patient diagnosis of {concept} present or historical "
            f"({_refs(d.src for d in affirmed)})",
            used=(d.src for d in affirmed),
            excluded=excluded,
            flags=flags,
        )
    uncertain = [d for d in rows if d.src.subject == "patient" and d.src.certainty == "uncertain"]
    if uncertain:
        return _decision(
            ri,
            condition,
            "review",
            "2",
            f"{concept} mentioned as uncertain ({_refs(d.src for d in uncertain)})",
            used=(d.src for d in uncertain),
            excluded=excluded,
        )
    negated = [d for d in rows if d.src.negated]
    if negated:
        return _decision(
            ri,
            condition,
            "not_supported",
            "3",
            f"{concept} explicitly denied ({_refs(d.src for d in negated)})",
            used=(d.src for d in negated),
            excluded=excluded,
        )
    return _decision(
        ri,
        condition,
        "insufficient",
        "4",
        f"no usable patient diagnosis of {concept}",
        used=(d.src for d in rows),
        excluded=excluded,
    )


def rule_hfpef(ri: RuleInput) -> Decision:
    return _simple_dx(ri, "bmi_path_b.hfpef", "hfpef")


def rule_mi(ri: RuleInput) -> Decision:
    return _simple_dx(ri, "bmi_path_c.mi", "mi")


def rule_stroke(ri: RuleInput) -> Decision:
    return _simple_dx(ri, "bmi_path_c.stroke", "stroke")


_CKD_3A_PLUS = frozenset({"3a", "3b", "4", "5"})
_CKD_EARLY = frozenset({"1", "2"})


def rule_ckd(ri: RuleInput) -> Decision:
    condition = "bmi_path_b.ckd"
    rows, excluded = _patient_dx(ri, "ckd", pathway=True)
    egfr = [v for v in ri.facts.egfr if v.src.tp.relative != "after"]
    excluded += _candidates_of(ri, "labs")
    pair = _dx_conflict(rows)
    if pair is not None:
        return _decision(
            ri,
            condition,
            "conflict",
            "conflict",
            f"ckd asserted and denied at the same timepoint ({_refs(p.src for p in pair)})",
            used=(p.src for p in pair),
            excluded=excluded,
        )
    affirmed = [d for d in rows if d.src.affirmed]
    egfr_text = ", ".join(f"{v.value} ({v.src.ref})" for v in egfr) or "none"
    for hi in [d for d in affirmed if d.ckd_stage in _CKD_3A_PLUS]:
        for lo in [d for d in affirmed if d.ckd_stage in _CKD_EARLY]:
            if same_timepoint(hi.src.tp, lo.src.tp, hi.src.doc_id == lo.src.doc_id):
                return _decision(
                    ri,
                    condition,
                    "conflict",
                    "conflict",
                    f"CKD stage {hi.ckd_stage} and stage {lo.ckd_stage} at the same timepoint "
                    f"({_refs((hi.src, lo.src))})",
                    used=(hi.src, lo.src),
                    excluded=excluded,
                )
    if any(d.ckd_stage in _CKD_3A_PLUS for d in affirmed):
        staged = [d for d in affirmed if d.ckd_stage in _CKD_3A_PLUS]
        flags = _dx_flags(staged)
        return _decision(
            ri,
            condition,
            "review" if flags else "supported",
            "1",
            f"CKD diagnosis with stage {staged[0].ckd_stage} ({_refs(d.src for d in staged)})",
            used=(d.src for d in staged),
            excluded=excluded,
            computed={"ckd_stage": staged[0].ckd_stage},
            flags=flags,
        )
    if affirmed and all(d.ckd_stage == "" for d in affirmed):
        return _decision(
            ri,
            condition,
            ri.policy.ckd_dx_egfr_only,
            "2",
            f"CKD diagnosis without a written stage; eGFR values: {egfr_text}",
            used=[d.src for d in affirmed] + [v.src for v in egfr],
            excluded=excluded,
            computed={"egfr": [str(v.value) for v in egfr]},
        )
    if any(d.ckd_stage in _CKD_EARLY for d in affirmed):
        early = [d for d in affirmed if d.ckd_stage in _CKD_EARLY]
        return _decision(
            ri,
            condition,
            "not_supported",
            "3",
            f"CKD diagnosis with explicit stage {early[0].ckd_stage} "
            f"({_refs(d.src for d in early)})",
            used=(d.src for d in early),
            excluded=excluded,
            computed={"ckd_stage": early[0].ckd_stage},
        )
    uncertain = [d for d in rows if d.src.certainty == "uncertain"]
    if uncertain:
        return _decision(
            ri,
            condition,
            "review",
            "2",
            f"ckd mentioned as uncertain ({_refs(d.src for d in uncertain)}); eGFR: {egfr_text}",
            used=[d.src for d in uncertain] + [v.src for v in egfr],
            excluded=excluded,
        )
    negated = [d for d in rows if d.src.negated]
    if negated:
        return _decision(
            ri,
            condition,
            "not_supported",
            "3",
            f"ckd explicitly denied ({_refs(d.src for d in negated)})",
            used=(d.src for d in negated),
            excluded=excluded,
        )
    return _decision(
        ri,
        condition,
        "insufficient",
        "4",
        f"no CKD diagnosis; eGFR values: {egfr_text}",
        used=(v.src for v in egfr),
        excluded=excluded,
        computed={"egfr": [str(v.value) for v in egfr]},
    )


def _closest_first(rows: Sequence[Dx], initiation: DateInterval | None) -> list[Dx]:
    def key(d: Dx) -> tuple[int, int, int]:
        if initiation is not None and d.src.tp.date is not None:
            return (0, d.src.tp.date.distance_days(initiation.start), d.src.evidence_id)
        return (1, 0, d.src.evidence_id)

    return sorted(rows, key=key)


def rule_pad(ri: RuleInput) -> Decision:
    condition = "bmi_path_c.pad"
    rows, excluded = _patient_dx(ri, "pad", pathway=True)
    pair = _dx_conflict(rows)
    if pair is not None:
        return _decision(
            ri,
            condition,
            "conflict",
            "conflict",
            f"pad asserted and denied at the same timepoint ({_refs(p.src for p in pair)})",
            used=(p.src for p in pair),
            excluded=excluded,
        )
    affirmed = _closest_first([d for d in rows if d.src.affirmed], ri.facts.initiation_date)
    if affirmed:
        chosen, rest = affirmed[0], affirmed[1:]
        excluded += [(d.src, "superseded_by_at") for d in rest]
        flags = _dx_flags([chosen])
        if chosen.symptomatic == "yes":
            return _decision(
                ri,
                condition,
                "review" if flags else "supported",
                "1",
                f"PAD diagnosis with symptoms stated ({chosen.src.ref})",
                used=[chosen.src],
                excluded=excluded,
                computed={"symptomatic": "yes"},
                flags=flags,
            )
        if chosen.symptomatic == "no":
            return _decision(
                ri,
                condition,
                "not_supported",
                "3",
                f"PAD diagnosis explicitly asymptomatic ({chosen.src.ref})",
                used=[chosen.src],
                excluded=excluded,
                computed={"symptomatic": "no"},
            )
        return _decision(
            ri,
            condition,
            "review",
            "2",
            f"PAD diagnosis with symptoms unclear ({chosen.src.ref})",
            used=[chosen.src],
            excluded=excluded,
            computed={"symptomatic": "unknown"},
        )
    uncertain = [d for d in rows if d.src.certainty == "uncertain"]
    if uncertain:
        return _decision(
            ri,
            condition,
            "review",
            "2",
            f"pad mentioned as uncertain ({_refs(d.src for d in uncertain)})",
            used=(d.src for d in uncertain),
            excluded=excluded,
        )
    negated = [d for d in rows if d.src.negated]
    if negated:
        return _decision(
            ri,
            condition,
            "not_supported",
            "3",
            f"pad explicitly denied ({_refs(d.src for d in negated)})",
            used=(d.src for d in negated),
            excluded=excluded,
        )
    return _decision(
        ri, condition, "insufficient", "4", "no usable PAD diagnosis", excluded=excluded
    )


# --- Labs ----------------------------------------------------------------------------------------


def _in_range(values: Iterable[LabValue], lo: Decimal, hi: Decimal) -> list[LabValue]:
    return [v for v in values if lo <= v.value <= hi]


def _at_least(values: Iterable[LabValue], bound: Decimal) -> list[LabValue]:
    return [v for v in values if v.value >= bound]


def _lab_straddle(values: Sequence[LabValue], thresholds: Iterable[Decimal]) -> list[LabValue]:
    """Same-fact labs (contract §4) with values on both sides of one of `thresholds`."""
    ts = list(thresholds)
    for i, a in enumerate(values):
        for b in values[i + 1 :]:
            if same_timepoint(a.src.tp, b.src.tp, a.src.doc_id == b.src.doc_id):
                cmp = compare_values([a.value, b.value], ts, EXACT)
                if cmp.straddled:
                    return [a, b]
    return []


def rule_prediabetes(ri: RuleInput) -> Decision:
    condition = "bmi_path_c.prediabetes"
    p = ri.policy
    rows, excluded = _patient_dx(ri, "prediabetes", pathway=True)
    a1c = [v for v in ri.facts.a1c if v.src.tp.relative != "after"]
    fpg = [v for v in ri.facts.fpg_mg_dl if v.src.tp.relative != "after"]
    labs = a1c + fpg
    excluded += _candidates_of(ri, "labs")
    excluded += [
        (v.src, "after_initiation")
        for v in (*ri.facts.a1c, *ri.facts.fpg_mg_dl)
        if v.src.tp.relative == "after"
    ]
    pair = _dx_conflict(rows)
    if pair is not None:
        return _decision(
            ri,
            condition,
            "conflict",
            "conflict",
            f"prediabetes asserted and denied at the same timepoint ({_refs(x.src for x in pair)})",
            used=(x.src for x in pair),
            excluded=excluded,
        )
    affirmed = [d for d in rows if d.src.affirmed]
    if affirmed:
        flags = _dx_flags(affirmed)
        return _decision(
            ri,
            condition,
            "review" if flags else "supported",
            "1",
            f"patient diagnosis of prediabetes ({_refs(d.src for d in affirmed)})",
            used=(d.src for d in affirmed),
            excluded=excluded,
            flags=flags,
        )
    uncertain = [d for d in rows if d.src.certainty == "uncertain"]
    if uncertain:
        return _decision(
            ri,
            condition,
            "review",
            "2",
            f"prediabetes mentioned as uncertain ({_refs(d.src for d in uncertain)})",
            used=(d.src for d in uncertain),
            excluded=excluded,
        )
    straddle = _lab_straddle(a1c, (p.prediabetes_a1c[0], p.diabetes_a1c)) or _lab_straddle(
        fpg, (p.prediabetes_fpg[0], p.diabetes_fpg)
    )
    if straddle:
        return _decision(
            ri,
            condition,
            "conflict",
            "conflict",
            "lab values on both sides of a threshold at the same timepoint "
            f"({_refs(v.src for v in straddle)})",
            used=(v.src for v in straddle),
            excluded=excluded,
        )
    computed = {"a1c": [str(v.value) for v in a1c], "fpg_mg_dl": [str(v.value) for v in fpg]}
    in_range = _in_range(a1c, *p.prediabetes_a1c) + _in_range(fpg, *p.prediabetes_fpg)
    negated = [d for d in rows if d.src.negated]
    if in_range and not negated:
        return _decision(
            ri,
            condition,
            p.a1c_prediabetes_range_without_dx,
            "3",
            f"no diagnosis; lab in the prediabetes range ({_refs(v.src for v in in_range)})",
            used=[v.src for v in in_range],
            excluded=excluded,
            computed=computed,
        )
    diabetic = _at_least(a1c, p.diabetes_a1c) + _at_least(fpg, p.diabetes_fpg)
    if diabetic and not negated:
        return _decision(
            ri,
            condition,
            "insufficient",
            "4",
            f"no diagnosis; lab in the diabetes range ({_refs(v.src for v in diabetic)}); "
            "see exclusion.t2dm",
            used=[v.src for v in diabetic],
            excluded=excluded,
            computed=computed,
        )
    if negated:
        return _decision(
            ri,
            condition,
            "not_supported",
            "5",
            f"prediabetes explicitly denied ({_refs(d.src for d in negated)})",
            used=(d.src for d in negated),
            excluded=excluded,
            computed=computed,
        )
    return _decision(
        ri,
        condition,
        "insufficient",
        "6",
        "no prediabetes diagnosis and no lab in range",
        used=[v.src for v in labs],
        excluded=excluded,
        computed=computed,
    )


# --- Hypertension (contract §3.2) -----------------------------------------------------------------


def rule_htn(ri: RuleInput) -> Decision:
    condition = "bmi_path_b.htn"
    facts, p = ri.facts, ri.policy
    sbp_gt, dbp_gt, min_drugs = (
        p.thresholds.htn.sbp_gt,
        p.thresholds.htn.dbp_gt,
        p.thresholds.htn.min_drugs,
    )
    at = facts.bp_at_initiation
    excluded = _timing_excluded((r.src for r in facts.bp_readings), ("at",)) + _candidates_of(
        ri, "bp_readings", "medications", "medication_lists"
    )
    if not at:
        return _decision(
            ri,
            condition,
            "insufficient",
            "1",
            "no blood pressure reading at initiation",
            excluded=excluded,
        )
    above = [r for r in at if r.sbp > sbp_gt or r.dbp > dbp_gt]
    computed: dict[str, Any] = {"readings_at": [[r.sbp, r.dbp] for r in at]}
    for i, a in enumerate(at):
        for b in at[i + 1 :]:
            if (a in above) != (b in above) and same_timepoint(
                a.src.tp, b.src.tp, a.src.doc_id == b.src.doc_id
            ):
                return _decision(
                    ri,
                    condition,
                    "conflict",
                    "conflict",
                    f"readings {a.sbp}/{a.dbp} and {b.sbp}/{b.dbp} at the same timepoint fall "
                    f"on both sides of {sbp_gt}/{dbp_gt} ({_refs((a.src, b.src))})",
                    used=(a.src, b.src),
                    excluded=excluded,
                    computed=computed,
                )
    if not above:
        flags = {"boundary_value"} if any(r.sbp == sbp_gt or r.dbp == dbp_gt for r in at) else set()
        return _decision(
            ri,
            condition,
            "insufficient",
            "2",
            f"no reading above {sbp_gt}/{dbp_gt} at initiation ({_refs(r.src for r in at)})",
            used=(r.src for r in at),
            excluded=excluded,
            computed=computed,
            flags=flags,
        )
    best_rank = -1
    best: tuple[Status, str, str, list[Source], set[str], list[tuple[Source, str]]] | None = None
    for r in above:
        assert r.src.tp.date is not None
        ov = facts.distinct_antihypertensives_overlapping(r.src.tp.date, doc_id=r.src.doc_id)
        unknown = [(m.src, "period_unknown") for m in ov.period_unknown]
        counted = list(ov.unambiguous)
        flags = {"same_note_list"} if any(m.same_note_list for m in counted) else set()
        list_rows = [
            ml.src
            for ml in facts.medication_lists
            if any(
                mp.same_note_list and mp.list_id == ml.list_id and mp.src.doc_id == ml.src.doc_id
                for mp in (*counted, *ov.ambiguous)
            )
        ]
        outcome: tuple[int, Status, str, str, list[Source], set[str]] | None = None
        if ov.products() >= min_drugs:
            outcome = (
                3,
                "supported",
                "3a",
                f"{ov.products()} distinct antihypertensives in use",
                [m.src for m in counted],
                flags,
            )
        elif ov.agents() >= min_drugs:
            outcome = (
                2,
                p.combination_pill_counts_as_two,
                "3b",
                "the second agent comes only from a combination pill",
                [m.src for m in counted],
                flags | {"combination_pill"},
            )
        elif ov.products_with_ambiguous() >= min_drugs:
            with_amb = counted + list(ov.ambiguous)
            outcome = (
                1,
                "review",
                "3c",
                "the second drug counts only through a class_ambiguous entry",
                [m.src for m in with_amb],
                flags | {"class_ambiguous"},
            )
        elif ov.complete_lists and p.htn_not_supported_by_complete_list:
            outcome = (
                0,
                "not_supported",
                "4",
                f"fewer than {min_drugs} antihypertensives in an explicitly complete list",
                [m.src for m in counted] + list(ov.complete_lists),
                flags,
            )
        if outcome is not None and outcome[0] > best_rank:
            best_rank = outcome[0]
            best = (
                outcome[1],
                outcome[2],
                outcome[3],
                [r.src, *outcome[4], *list_rows],
                outcome[5],
                unknown,
            )
        elif best is None:
            best = (
                "insufficient",
                "5",
                f"fewer than {min_drugs} recognized antihypertensives certainly in use on the "
                f"reading date ({ov.products()} counted)",
                [r.src, *(m.src for m in counted)],
                flags,
                unknown,
            )
    assert best is not None
    status, step, text, used, flags, unknown = best
    computed["above_threshold"] = [[r.sbp, r.dbp] for r in above]
    return _decision(
        ri,
        condition,
        status,
        step,
        f"{text} ({_refs(used)})",
        used=used,
        excluded=excluded + unknown,
        computed=computed,
        flags=flags,
    )


# --- Exclusions (contract §3.3) -------------------------------------------------------------------


def _positive(d: Dx) -> bool:
    return d.src.subject == "patient" and d.src.certainty in ("present", "uncertain")


def _exclusion(ri: RuleInput, condition: str, concept: str) -> Decision:
    p = ri.policy
    rows, excluded = _patient_dx(ri, concept, pathway=False)
    pair = _dx_conflict(rows)
    if pair is not None:
        return _decision(
            ri,
            condition,
            "conflict",
            "1",
            f"{concept} asserted and denied at the same timepoint ({_refs(x.src for x in pair)})",
            used=(x.src for x in pair),
            excluded=excluded,
            computed={"positive": True},
        )
    positive = [d for d in rows if _positive(d)]
    if concept == "mash":
        staged_out = [
            d for d in positive if d.fibrosis_stage in ("F0", "F1") or d.cirrhosis is True
        ]
        if positive and len(staged_out) == len(positive):
            return _decision(
                ri,
                condition,
                "not_supported",
                "2",
                f"MASH explicitly F0-F1 or cirrhotic ({_refs(d.src for d in staged_out)})",
                used=(d.src for d in staged_out),
                excluded=excluded,
                computed={"positive": False},
            )
    if concept == "osa":
        mild = [
            d
            for d in positive
            if d.osa_severity == "mild" or (d.ahi is not None and d.ahi < p.osa_ahi_ge)
        ]
        if positive and len(mild) == len(positive):
            return _decision(
                ri,
                condition,
                "not_supported",
                "2",
                f"OSA explicitly mild ({_refs(d.src for d in mild)})",
                used=(d.src for d in mild),
                excluded=excluded,
                computed={"positive": False},
            )
    if positive and all(d.src.tp.relative == "after" for d in positive):
        return _decision(
            ri,
            condition,
            "review",
            "3",
            f"{concept} appears only after initiation ({_refs(d.src for d in positive)})",
            used=(d.src for d in positive),
            excluded=excluded,
            flags={"post_initiation_exclusion"},
            computed={"positive": True},
        )
    if positive:
        flags = _dx_flags(positive) & {"unrecognized", "table_source"}
        return _decision(
            ri,
            condition,
            "review",
            "4",
            f"positive or suspected {concept} ({_refs(d.src for d in positive)})",
            used=(d.src for d in positive),
            excluded=excluded,
            flags=flags,
            computed={"positive": True},
        )
    if concept == "t2dm":
        diabetic = _at_least(ri.facts.a1c, p.diabetes_a1c) + _at_least(
            ri.facts.fpg_mg_dl, p.diabetes_fpg
        )
        excluded += _candidates_of(ri, "labs")
        if diabetic and not any(d.src.negated for d in rows):
            return _decision(
                ri,
                condition,
                p.lab_in_diabetes_range_without_dx,
                "4-lab",
                f"lab in the diabetes range without a diagnosis ({_refs(v.src for v in diabetic)})",
                used=[v.src for v in diabetic],
                excluded=excluded,
                computed={"positive": True, "labs": [str(v.value) for v in diabetic]},
            )
    negated = [d for d in rows if d.src.negated]
    if negated:
        return _decision(
            ri,
            condition,
            "not_supported",
            "5",
            f"{concept} explicitly denied ({_refs(d.src for d in negated)})",
            used=(d.src for d in negated),
            excluded=excluded,
            computed={"positive": False},
        )
    return _decision(
        ri,
        condition,
        "insufficient",
        "6",
        f"{concept} not mentioned",
        excluded=excluded,
        computed={"positive": False},
    )


def rule_t2dm(ri: RuleInput) -> Decision:
    return _exclusion(ri, "exclusion.t2dm", "t2dm")


def rule_osa(ri: RuleInput) -> Decision:
    return _exclusion(ri, "exclusion.osa", "osa")


def rule_mash(ri: RuleInput) -> Decision:
    return _exclusion(ri, "exclusion.mash", "mash")


_PART_D_YEAR = 2026
_NOT_TRIGGERING_PAYERS = frozenset({"medicaid", "self_pay", "bridge"})


def rule_part_d(ri: RuleInput) -> Decision:
    condition = "exclusion.part_d_glp1"
    rows = ri.facts.prior_glp1
    excluded = _candidates_of(ri, "prior_glp1")
    triggered = [
        r
        for r in rows
        if r.payer == "part_d"
        and (r.date is None or r.date.start.year <= _PART_D_YEAR <= r.date.end.year)
    ]
    if triggered:
        return _decision(
            ri,
            condition,
            "review",
            "1",
            f"GLP-1 paid by Part D in {_PART_D_YEAR} or undated "
            f"({_refs(r.src for r in triggered)})",
            used=(r.src for r in triggered),
            excluded=excluded,
            computed={"positive": True},
        )
    not_triggering = [
        r
        for r in rows
        if r.payer in _NOT_TRIGGERING_PAYERS
        or (r.payer == "part_d" and r.date is not None and r.date.end.year < _PART_D_YEAR)
    ]
    if not_triggering:
        return _decision(
            ri,
            condition,
            "not_supported",
            "2",
            "the mentioned GLP-1 use does not trigger this exclusion "
            f"({_refs(r.src for r in not_triggering)})",
            used=(r.src for r in not_triggering),
            excluded=excluded,
            computed={"positive": False},
        )
    return _decision(
        ri,
        condition,
        "insufficient",
        "3",
        "no prior GLP-1 with a known payer",
        used=(r.src for r in rows),
        excluded=excluded,
        computed={"positive": False},
    )


# --- Pathways (contract §3.4) ---------------------------------------------------------------------


def aggregate_path(bmi: Status, comorbidities: Sequence[Status]) -> tuple[Status, str]:
    """The four rows of contract §3.4 (before the downgrades); returns (status, step)."""
    if comorbidities and all(c == "not_supported" for c in comorbidities):
        return "not_supported", "1"
    if bmi == "not_supported":
        return "not_supported", "2"
    if bmi in ("insufficient", "conflict", "review"):
        return bmi, "3"
    if any(c == "supported" for c in comorbidities):
        return "supported", "4"
    ranked = max(
        (c for c in comorbidities if c in _RANK), key=lambda c: _RANK[c], default="insufficient"
    )
    return ranked, "4"  # type: ignore[return-value]


def _path(
    ri: RuleInput, condition: str, bmi_id: str, sub_ids: Sequence[str], cv_ids: Sequence[str]
) -> Decision:
    bmi = ri.decided[bmi_id]
    subs = [ri.decided[s] for s in sub_ids]
    status, step = aggregate_path(bmi.status, [s.status for s in subs])
    flags: set[str] = set()
    reason = f"bmi {bmi.status}; " + ", ".join(
        f"{s.condition.split('.')[-1]} {s.status}" for s in subs
    )
    if status == "supported" and cv_ids and ri.policy.path_c_cv_history_requires_review:
        prediabetes = ri.decided.get("bmi_path_c.prediabetes")
        if prediabetes is not None and prediabetes.status != "supported":
            status, step = "review", "downgrade.cv_history_only"
            flags.add("cv_history_only")
            reason += "; established only through cardiovascular history"
    if status == "supported" and "mace_purpose" in ri.facts.case_flags:
        status, step = ri.policy.mace_purpose_all_pathways, "downgrade.mace_purpose"
        reason += "; stated purpose is MACE reduction"
    used = {i for d in (bmi, *subs) for i in d.used_evidence}
    return Decision(
        condition=condition,
        kind="path",
        status=status,
        reason=reason,
        rule_id=f"{condition}:{step}",
        rules_version=ri.policy.rules_version,
        used_evidence=tuple(sorted(used)),
        excluded_evidence=(),
        computed={"bmi": bmi.status, "comorbidities": {s.condition: s.status for s in subs}},
        flags=tuple(sorted(flags)),  # type: ignore[arg-type]
    )


def rule_path_a(ri: RuleInput) -> Decision:
    d = decide_bmi(ri, "bmi_path_a", ri.policy.bmi_thresholds[2])
    if d.status == "supported" and "mace_purpose" in ri.facts.case_flags:
        return d.model_copy(
            update={
                "status": ri.policy.mace_purpose_all_pathways,
                "rule_id": "bmi_path_a:downgrade.mace_purpose",
                "reason": d.reason + "; stated purpose is MACE reduction",
            }
        )
    return d


def rule_path_b_bmi(ri: RuleInput) -> Decision:
    return decide_bmi(ri, "bmi_path_b.bmi", ri.policy.bmi_thresholds[1])


def rule_path_c_bmi(ri: RuleInput) -> Decision:
    return decide_bmi(ri, "bmi_path_c.bmi", ri.policy.bmi_thresholds[0])


def rule_path_b(ri: RuleInput) -> Decision:
    return _path(
        ri,
        "bmi_path_b",
        "bmi_path_b.bmi",
        ("bmi_path_b.hfpef", "bmi_path_b.htn", "bmi_path_b.ckd"),
        (),
    )


def rule_path_c(ri: RuleInput) -> Decision:
    return _path(
        ri,
        "bmi_path_c",
        "bmi_path_c.bmi",
        ("bmi_path_c.prediabetes", "bmi_path_c.mi", "bmi_path_c.stroke", "bmi_path_c.pad"),
        ("bmi_path_c.mi", "bmi_path_c.stroke", "bmi_path_c.pad"),
    )


# --- Age, identity, lifestyle (contract §3.5) -----------------------------------------------------


def age_inconsistent(intervals: Sequence[AgeInterval]) -> bool:
    for i, a in enumerate(intervals):
        for b in intervals[i + 1 :]:
            if (
                a.lo_years > b.hi_years + AGE_TOLERANCE_YEARS
                or b.lo_years > a.hi_years + AGE_TOLERANCE_YEARS
            ):
                return True
    return False


def rule_age(ri: RuleInput) -> Decision:
    condition = "age_18"
    years = ri.policy.age_years
    intervals = ri.facts.age_interval_at_initiation
    excluded = _candidates_of(ri, "patient_identity")
    if not intervals:
        return _decision(
            ri,
            condition,
            "insufficient",
            "4",
            "neither date of birth nor stated age",
            excluded=excluded,
        )
    used = [a.src for a in intervals]
    flags = {"inconsistent_values"} if age_inconsistent(intervals) else set()
    computed = {
        "intervals": [[a.lo_years, a.hi_years, a.origin, a.reference] for a in intervals],
        "initiation_date": ri.facts.initiation_date.iso() if ri.facts.initiation_date else None,
    }
    at_initiation = ri.facts.initiation is not None
    if all(a.whole_at_least(years) for a in intervals):
        return _decision(
            ri,
            condition,
            "supported",
            "1",
            f"age interval entirely >= {years} ({_refs(used)})",
            used=used,
            excluded=excluded,
            computed=computed,
            flags=flags,
        )
    if all(a.whole_below(years) for a in intervals):
        return _decision(
            ri,
            condition,
            "not_supported",
            "2",
            f"age interval entirely < {years} ({_refs(used)})",
            used=used,
            excluded=excluded,
            computed=computed,
            flags=flags,
        )
    if not at_initiation:
        return _decision(
            ri,
            condition,
            "insufficient",
            "4",
            f"no initiation date and the age interval straddles {years}",
            used=used,
            excluded=excluded,
            computed=computed,
            flags=flags,
        )
    return _decision(
        ri,
        condition,
        "review",
        "3",
        f"age interval straddles {years} at initiation ({_refs(used)})",
        used=used,
        excluded=excluded,
        computed=computed,
        flags=flags,
    )


def rule_identity(ri: RuleInput) -> Decision:
    condition = "patient_identity"
    statuses = {d: f.identity_status for d, f in ri.facts.doc_facts.items()}
    identity_sources = [s for s in _identity_sources(ri)]
    computed = {"documents": statuses}
    mismatched = sorted(d for d, s in statuses.items() if s == "mismatch")
    if mismatched:
        return _decision(
            ri,
            condition,
            "conflict",
            "1",
            f"patient identifier differs in {', '.join(mismatched)}",
            used=identity_sources,
            computed=computed,
        )
    if statuses and all(s == "missing" for s in statuses.values()):
        return _decision(
            ri,
            condition,
            "insufficient",
            "4",
            "no document carries a comparable identifier",
            used=identity_sources,
            computed=computed,
        )
    missing = sorted(d for d, s in statuses.items() if s == "missing")
    if missing:
        return _decision(
            ri,
            condition,
            "review",
            "2",
            f"no identifier or date of birth in {', '.join(missing)}",
            used=identity_sources,
            computed=computed,
            flags={"id_missing"},
        )
    return _decision(
        ri,
        condition,
        "supported",
        "3",
        "every document is consistent",
        used=identity_sources,
        computed=computed,
    )


def _identity_sources(ri: RuleInput) -> list[Source]:
    return [a.src for a in ri.facts.age_interval_at_initiation]


_LIFESTYLE_INSUFFICIENT = frozenset({"advice_only", "referral_pending", "declined"})


def _lifestyle(ri: RuleInput, kind: str) -> Decision:
    condition = f"lifestyle.{kind}"
    records = [r for r in ri.facts.lifestyle_applicable if r.kind == kind]
    excluded = _candidates_of(ri, "lifestyle")
    applicable = [r for r in records if r.applicable]
    excluded += [(r.src, "timing_unknown") for r in records if not r.applicable]
    if not applicable:
        return _decision(
            ri,
            condition,
            "insufficient",
            "4",
            f"no {kind} record applicable on {ri.facts.assessment_date.isoformat()}",
            excluded=excluded,
        )
    applicable.sort(
        key=lambda r: (r.distance_days is None, r.distance_days or 0, r.src.evidence_id)
    )
    chosen, rest = applicable[0], applicable[1:]
    excluded += [(r.src, "superseded_by_at") for r in rest]
    computed = {
        "program_type": chosen.program_type,
        "attendance": chosen.attendance,
        "end_kind": chosen.end_kind,
    }
    if chosen.program_type == "none_stated":
        return _decision(
            ri,
            condition,
            "not_supported",
            "2",
            f"document states no {kind} program at all ({chosen.src.ref})",
            used=[chosen.src],
            excluded=excluded,
            computed=computed,
        )
    if chosen.program_type in _LIFESTYLE_INSUFFICIENT:
        return _decision(
            ri,
            condition,
            "insufficient",
            "4",
            f"{chosen.program_type} only ({chosen.src.ref})",
            used=[chosen.src],
            excluded=excluded,
            computed=computed,
        )
    if (
        chosen.program_type == "commercial"
        or chosen.attendance == "irregular"
        or chosen.has_limitation
    ):
        return _decision(
            ri,
            condition,
            "review",
            "3",
            f"commercial program, irregular attendance or a limitation ({chosen.src.ref})",
            used=[chosen.src],
            excluded=excluded,
            computed=computed,
        )
    return _decision(
        ri,
        condition,
        "supported",
        "1",
        f"structured program ongoing on the assessment date ({chosen.src.ref})",
        used=[chosen.src],
        excluded=excluded,
        computed=computed,
    )


def rule_nutrition(ri: RuleInput) -> Decision:
    return _lifestyle(ri, "nutrition")


def rule_activity(ri: RuleInput) -> Decision:
    return _lifestyle(ri, "activity")


# --- Claims (contract §2; guide K-03, K-04) -------------------------------------------------------

_POSITIVE_BOXES = frozenset({"yes", "checked"})
_NEGATIVE_BOXES = frozenset({"no", "unchecked"})


def _claim_vs_condition(
    polarity: bool, condition: Decision, ri: RuleInput | None = None
) -> tuple[Status, str]:
    """Positive claim: supported↔supported, not_supported↔conflict; negative claim mirrored.
    What the chart leaves uncertain (`review`, `conflict`) stays so; an `insufficient`
    condition that still carries a flag (a boundary reading, a missing identifier) is an
    unclear mention → `review` (guide K-03). The Part D `not_supported` only says that the
    documented fill does not trigger the exclusion (contract §3.3): it supports no box."""
    status = condition.status
    if condition.condition == "exclusion.part_d_glp1" and status == "not_supported":
        return "insufficient", "the documented fill says nothing about the box"
    if status == "insufficient" and condition.flags:
        return "review", "chart mention is unclear (" + ",".join(condition.flags) + ")"
    if status in ("insufficient", "review", "conflict"):
        return status, "chart " + status
    agrees = (status == "supported") == polarity
    # The chart rows the condition rests on: table-sourced or unrecognized ones cannot carry
    # a clean agreement, whatever the condition's own status.
    risky: set[str] = {f for f in condition.flags if f in _STEP8_FLAGS - {"timing_disagreement"}}
    if ri is not None:
        risky |= {f for s in ri.sources(condition.used_evidence) for f in s.flags} & (
            _STEP8_FLAGS - {"timing_disagreement"}
        )
    if agrees and risky:
        return "review", "chart agrees but its evidence carries " + ",".join(sorted(risky))
    return (
        ("supported", "chart agrees with the box")
        if agrees
        else ("conflict", "chart contradicts the box")
    )


def claim_rule(claim_id: str) -> RuleFn:
    def rule(ri: RuleInput) -> Decision:
        records = [c for c in ri.facts.claims if c.claim_id == claim_id]
        used = [c.src for c in records]
        excluded = [
            (s, "candidate_only") for s in ri.facts.candidate_only if s.field == "pa_form_claims"
        ]
        values = sorted({c.claimed_value for c in records})
        computed: dict[str, Any] = {"claimed": values}
        if len(values) != 1:
            return _decision(
                ri,
                claim_id,
                "review",
                "0",
                "the draft carries different values for this box",
                used=used,
                excluded=excluded,
                computed=computed,
            )
        claimed = values[0]
        target = claim_id[len(CLAIM_PREFIX) :]
        if target == "drug":
            init = ri.facts.initiation
            if init is None:
                return _decision(
                    ri,
                    claim_id,
                    "insufficient",
                    "1",
                    "no verified initiation",
                    used=used,
                    excluded=excluded,
                    computed=computed,
                )
            claimed_name = re.sub(r"\s+", " ", claimed).strip().casefold()
            if claimed_name in GLP1_BRANDS and init.drug_name in GLP1_BRANDS:
                same = claimed_name == init.drug_name  # two products: compare the products
            else:
                same = glp1_canonical(claimed) == init.drug_canonical
            if same:
                return _decision(
                    ri,
                    claim_id,
                    "supported",
                    "2",
                    "claimed drug matches the verified course",
                    used=[*used, init.src],
                    excluded=excluded,
                    computed=computed,
                )
            return _decision(
                ri,
                claim_id,
                "conflict",
                "3",
                "claimed drug differs from the verified course",
                used=[*used, init.src],
                excluded=excluded,
                computed=computed,
            )
        if target == "bmi_bracket":
            bracket = parse_bracket(claimed)
            actual = ri.facts.bmi_bracket
            computed["bracket"] = actual.label() if actual else None
            if bracket is None:
                return _decision(
                    ri,
                    claim_id,
                    "review",
                    "1",
                    "unreadable bracket",
                    used=used,
                    excluded=excluded,
                    computed=computed,
                )
            if ri.facts.bmi_bracket_ambiguous:
                return _decision(
                    ri,
                    claim_id,
                    "review",
                    "2",
                    "initiation BMI candidates fall in different brackets",
                    used=used,
                    excluded=excluded,
                    computed=computed,
                )
            if actual is None:
                return _decision(
                    ri,
                    claim_id,
                    "insufficient",
                    "3",
                    "no BMI at initiation",
                    used=used,
                    excluded=excluded,
                    computed=computed,
                )
            agrees = actual.lo == bracket.lo and actual.hi == bracket.hi
            chart = [s for c in ri.facts.bmi_candidates if c.tp.relative == "at" for s in c.sources]
            return _decision(
                ri,
                claim_id,
                "supported" if agrees else "conflict",
                "4",
                f"chart bracket {actual.label()}",
                used=[*used, *chart],
                timing_sensitive=True,
                excluded=excluded,
                computed=computed,
            )
        condition = ri.decided.get(target)
        if condition is None:
            return _decision(
                ri,
                claim_id,
                "insufficient",
                "1",
                "no condition decided for this box",
                used=used,
                excluded=excluded,
                computed=computed,
            )
        if claimed in _POSITIVE_BOXES:
            polarity = True
        elif claimed in _NEGATIVE_BOXES:
            polarity = False
        else:
            return _decision(
                ri,
                claim_id,
                "insufficient",
                "1",
                "box not filled",
                used=used,
                excluded=excluded,
                computed=computed,
            )
        status, why = _claim_vs_condition(polarity, condition, ri)
        return _decision(
            ri,
            claim_id,
            status,
            "2",
            f"{why} ({target} {condition.status})",
            used=used,
            excluded=excluded,
            computed={**computed, "condition_status": condition.status},
        )

    return rule


# --- Registry and evaluation ----------------------------------------------------------------------

RULES: dict[str, RuleFn] = {
    "age_18": rule_age,
    "bmi_path_a": rule_path_a,
    "bmi_path_b": rule_path_b,
    "bmi_path_b.bmi": rule_path_b_bmi,
    "bmi_path_b.hfpef": rule_hfpef,
    "bmi_path_b.htn": rule_htn,
    "bmi_path_b.ckd": rule_ckd,
    "bmi_path_c": rule_path_c,
    "bmi_path_c.bmi": rule_path_c_bmi,
    "bmi_path_c.prediabetes": rule_prediabetes,
    "bmi_path_c.mi": rule_mi,
    "bmi_path_c.stroke": rule_stroke,
    "bmi_path_c.pad": rule_pad,
    "exclusion.t2dm": rule_t2dm,
    "exclusion.osa": rule_osa,
    "exclusion.mash": rule_mash,
    "exclusion.part_d_glp1": rule_part_d,
    "patient_identity": rule_identity,
}
"""Exactly the condition ids of `rules/bridge-v1.yaml` (contract §2)."""

LIFESTYLE_RULES: dict[str, RuleFn] = {
    "lifestyle.nutrition": rule_nutrition,
    "lifestyle.activity": rule_activity,
}

EVALUATION_ORDER: tuple[str, ...] = (
    "bmi_path_b.bmi",
    "bmi_path_b.hfpef",
    "bmi_path_b.htn",
    "bmi_path_b.ckd",
    "bmi_path_c.bmi",
    "bmi_path_c.prediabetes",
    "bmi_path_c.mi",
    "bmi_path_c.stroke",
    "bmi_path_c.pad",
    "age_18",
    "patient_identity",
    "exclusion.t2dm",
    "exclusion.osa",
    "exclusion.mash",
    "exclusion.part_d_glp1",
    "bmi_path_a",
    "bmi_path_b",
    "bmi_path_c",
    "lifestyle.nutrition",
    "lifestyle.activity",
)


def evaluate_rules(facts: ComputedFacts, policy: Policy) -> list[Decision]:
    """Every condition of contract §2 plus one decision per claim id present in the evidence,
    in the fixed order of `CONDITION_IDS` followed by the claim ids."""
    decided: dict[str, Decision] = {}
    ri = RuleInput(facts, policy, decided)
    for condition in EVALUATION_ORDER:
        fn = RULES.get(condition) or LIFESTYLE_RULES[condition]
        decided[condition] = fn(ri)
    for claim_id in sorted({c.claim_id for c in facts.claims}):
        decided[claim_id] = claim_rule(claim_id)(ri)
    order = {cid: i for i, cid in enumerate(CONDITION_IDS)}
    return sorted(decided.values(), key=lambda d: (order.get(d.condition, len(order)), d.condition))


def human_workload(decisions: Iterable[Decision]) -> int:
    """Top-level rows that are review, conflict or insufficient (contract §3.5)."""
    return sum(
        1 for d in decisions if d.kind in ("condition", "path", "exclusion") and d.status in _RANK
    )
