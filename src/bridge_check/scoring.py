"""Deterministic scoring of one case and of a split (planning section 3.1, contract §8).

Everything here is a count, never a percentage. Inputs are the comparison report of
`bridge_check.compare` (facts assigned one-to-one on the contract §8 keys), the scoring view
of the evidence rows (`Store.facts_for_run`), the gold file and the hidden case metadata
(`bridge_check.casemeta`). Outputs carry ids, enum values and counts only.

Two levels (planning section 3.1, "two-level scoring"):

- case level: every condition and claim of the gold, correct or not, with the class of the
  first upstream error (`compare.ERROR_CLASSES`) of each miss; a failed run keeps every row
  in the denominator and marks each one wrong with `run_failed`;
- trap level: every `trap_id` the variant lists in `case.yaml` passes when the run completed
  and every id under `tests:` is correct; a failing trap is tagged with the most upstream
  error among the failing rows, once per (trap, variant), so the rows a miss drags down are
  not counted again. Traps of one variant therefore share one verdict; the matrix says which
  isolated test covers each trap.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from bridge_check.casemeta import SECTIONS, CaseMeta
from bridge_check.compare import ERROR_CLASSES, compare_stored_run
from bridge_check.compute import DrugIndex
from bridge_check.enums import Status
from bridge_check.gold_schema import Gold
from bridge_check.rules import kind_of
from bridge_check.rules_schema import RulesTable
from bridge_check.store import Store

SCORING_VERSION = 1

RUN_FAILED = "run_failed"
"""The first-error tag of every row of a run that did not complete."""

FIRST_ERROR_STAGE: dict[str, str] = {
    "gold_question": "gold",
    "extraction_missed": "extract",
    "extraction_wrong_value": "extract",
    "extraction_extra": "extract",
    "verify_excluded": "verify",
    "compute_timepoint": "compute",
    "rules": "rules",
}
"""Pipeline stage of each first-upstream-error class (planning section 3.6.1)."""

TOP_LEVEL_KINDS: frozenset[str] = frozenset({"condition", "path", "exclusion"})
"""The rows a human reads first (contract §3.5): the same set `bridge check` counts."""
HUMAN_STATUSES: frozenset[str] = frozenset({"review", "conflict", "insufficient"})
AUTOMATABLE: frozenset[str] = frozenset({"supported", "not_supported"})
"""Gold statuses a system may settle without a human (the conclusions of contract §1)."""
LOCATED: frozenset[str] = frozenset({"verbatim", "normalized"})
POSITION_STATUSES: tuple[str, ...] = ("verbatim", "normalized", "candidate", "not_found")

TEST_TYPES: tuple[str, ...] = (
    "isolated_real",
    "isolated_minimal_pair",
    "rules_fixture",
    "integrated_case",
    "ladder_level",
)
"""Columns of the coverage matrix (planning section 3.6.1 rule 4)."""

OUT_OF_SCOPE: tuple[str, ...] = ("verifier_ablation", "rules_only_unit_tests")
"""Rows of planning section 3.1 this module does not produce yet."""


class _Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class Counts(_Strict):
    n: int = Field(ge=0)
    of: int = Field(ge=0)


def _counts(n: int, of: int) -> Counts:
    return Counts(n=n, of=of)


def _add(a: Counts, b: Counts) -> Counts:
    return Counts(n=a.n + b.n, of=a.of + b.of)


class RowScore(_Strict):
    id: str
    kind: str
    gold_status: Status
    gold_flags: list[str]
    status: Status | None
    flags: list[str]
    correct: bool
    first_error: str | None
    false_support: bool
    missed_exclusion: bool
    policy_source: str | None


class FalseSupportCounts(_Strict):
    """A false support next to its denominators (planning section 3.1): the rows gold does
    not support (the opportunities), the rows the system supports, and the gold-automatable
    top-level rows the system settled correctly."""

    count: int = Field(ge=0)
    gold_non_supported: int = Field(ge=0)
    system_supported: int = Field(ge=0)
    correctly_automated: Counts


class FactCounts(_Strict):
    gold_facts: int = Field(ge=0)
    matched: int = Field(ge=0)
    matched_but_excluded: int = Field(ge=0)
    wrong_value: int = Field(ge=0)
    wrong_value_timing_only: int = Field(ge=0)
    missed: int = Field(ge=0)
    false_positives: int = Field(ge=0)
    excluded_unmatched: int = Field(ge=0)
    absent_correct: int = Field(ge=0)
    absent_false_positive: int = Field(ge=0)


class CitationCounts(_Strict):
    """The three citation measures (planning section 3.1): quotes the verifier located
    (`verbatim` or `normalized`) over all evidence rows; gold facts the system reproduced
    with every key (`matched`) over all gold facts; gold facts whose span a located system
    row overlaps, whatever its value, over all gold facts."""

    quotes_located: Counts
    facts_correct: Counts
    gold_evidence_recalled: Counts


class PositionCounts(_Strict):
    verbatim: int = Field(ge=0)
    normalized: int = Field(ge=0)
    candidate: int = Field(ge=0)
    not_found: int = Field(ge=0)


class CaseFlagsScore(_Strict):
    gold: list[str]
    live: list[str]
    correct: bool


class TrapResult(_Strict):
    trap_id: str
    variant_id: str
    passed: bool
    first_error: str | None
    stage: str | None
    failing_rows: list[str]


class CaseScore(_Strict):
    variant_id: str
    case_id: str
    section: str
    gold_sha256: str
    run_id: int | None
    run_status: str
    failed_stage: str | None
    extraction_source: str | None
    conditions: dict[str, RowScore]
    claims: dict[str, RowScore]
    case_flags: CaseFlagsScore
    conditions_correct: Counts
    claims_correct: Counts
    false_supports: FalseSupportCounts
    claims_false_supports: FalseSupportCounts
    missed_exclusions: Counts
    exclusion_evidence_found: int = Field(ge=0)
    human_workload: int | None
    needs_human: bool
    first_errors: dict[str, int]
    facts: FactCounts
    citations: CitationCounts
    positions: PositionCounts
    exclusion_reasons: dict[str, int]
    traps: list[TrapResult]
    gold_origin: dict[str, int]
    gold_with_clause: Counts
    cost_usd: float | None


class MicroTotals(_Strict):
    variants: int = Field(ge=0)
    case_families: int = Field(ge=0)
    runs_failed: int = Field(ge=0)
    conditions_correct: Counts
    claims_correct: Counts
    false_supports: FalseSupportCounts
    claims_false_supports: FalseSupportCounts
    missed_exclusions: Counts
    exclusion_evidence_found: int = Field(ge=0)
    human_workload: int = Field(ge=0)
    packets_needing_human: Counts
    first_errors: dict[str, int]
    facts: FactCounts
    citations: CitationCounts
    positions: PositionCounts
    exclusion_reasons: dict[str, int]


class ConditionMacro(_Strict):
    id: str
    kind: str
    correct: Counts
    false_supports: int = Field(ge=0)
    policy_source: str | None
    by_variant: dict[str, str | None]


class SectionScore(_Strict):
    section: str
    variants: list[str]
    micro: MicroTotals


class TrapScore(_Strict):
    trap_id: str
    opportunities: int = Field(ge=0)
    passed: int = Field(ge=0)
    results: list[TrapResult]
    first_errors: dict[str, int]


class CoverageMatrix(_Strict):
    traps: list[str]
    test_types: list[str]
    cells: dict[str, dict[str, list[str]]]
    filled: Counts
    not_covered: list[dict[str, str]]


class PolicySourceRow(_Strict):
    id: str
    last_modified: str | None


class SplitScore(_Strict):
    scoring_version: int
    split: Literal["dev"]
    manifest_sha256: str
    cases: dict[str, CaseScore]
    micro: MicroTotals
    macro: dict[str, list[ConditionMacro]]
    sections: dict[str, SectionScore]
    traps: list[TrapScore]
    coverage: CoverageMatrix
    gold_origin: dict[str, int]
    gold_with_clause: Counts
    rules_version: str
    policy_sources: list[PolicySourceRow]
    condition_sources: dict[str, str]
    out_of_scope: list[str]


# --- one case ---------------------------------------------------------------------------------


def condition_sources(rules: RulesTable) -> dict[str, str]:
    return {c.id: c.source.id for c in rules.conditions}


def _row(
    cid: str, r: Mapping[str, Any], sources: Mapping[str, str], *, first_error: str | None
) -> RowScore:
    status = r["status"]
    return RowScore(
        id=cid,
        kind=kind_of(cid),
        gold_status=r["gold_status"],
        gold_flags=sorted(r["gold_flags"]),
        status=status,
        flags=sorted(r["flags"]),
        correct=bool(r["correct"]),
        first_error=first_error,
        false_support=status == "supported" and r["gold_status"] != "supported",
        missed_exclusion=(
            cid.startswith("exclusion.")
            and r["gold_status"] == "review"
            and status in ("insufficient", "not_supported")
        ),
        policy_source=sources.get(cid),
    )


def human_workload(rows: Iterable[RowScore]) -> int:
    """Top-level rows that are review, conflict or insufficient (contract §3.5); the same
    count `bridge check` prints."""
    return sum(1 for r in rows if r.kind in TOP_LEVEL_KINDS and r.status in HUMAN_STATUSES)


def false_support_counts(rows: Iterable[RowScore]) -> FalseSupportCounts:
    rows = list(rows)
    automatable = [r for r in rows if r.kind in TOP_LEVEL_KINDS and r.gold_status in AUTOMATABLE]
    return FalseSupportCounts(
        count=sum(r.false_support for r in rows),
        gold_non_supported=sum(r.gold_status != "supported" for r in rows),
        system_supported=sum(r.status == "supported" for r in rows),
        correctly_automated=_counts(sum(r.correct for r in automatable), len(automatable)),
    )


def _first_errors(rows: Iterable[RowScore]) -> dict[str, int]:
    out = dict.fromkeys((*ERROR_CLASSES, RUN_FAILED), 0)
    for r in rows:
        if r.first_error is not None:
            out[r.first_error] += 1
    return out


def _positions(facts_rows: Sequence[Mapping[str, Any]]) -> PositionCounts:
    counts = {s: 0 for s in POSITION_STATUSES}
    for r in facts_rows:
        counts[str(r["position_status"])] += 1
    return PositionCounts(**counts)


def _exclusion_reasons(facts_rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in facts_rows:
        for reason in r["exclusion_reasons"]:
            out[str(reason)] = out.get(str(reason), 0) + 1
    return dict(sorted(out.items()))


def _citations(
    gold: Gold, report: Mapping[str, Any], facts_rows: Sequence[Mapping[str, Any]]
) -> CitationCounts:
    located = [
        r
        for r in facts_rows
        if r["position_status"] in LOCATED
        and isinstance(r["offset_start"], int)
        and isinstance(r["offset_end"], int)
    ]
    recalled = 0
    for g in gold.facts:
        if any(
            r["doc_id"] == g.doc_id and r["offset_start"] < g.end and g.start < r["offset_end"]
            for r in located
        ):
            recalled += 1
    return CitationCounts(
        quotes_located=_counts(len(located), len(facts_rows)),
        facts_correct=_counts(int(report["totals"]["matched"]), len(gold.facts)),
        gold_evidence_recalled=_counts(recalled, len(gold.facts)),
    )


def _fact_counts(report: Mapping[str, Any]) -> FactCounts:
    t = report["totals"]
    return FactCounts(
        gold_facts=int(t["gold_facts"]),
        matched=int(t["matched"]),
        matched_but_excluded=int(t["matched_but_excluded"]),
        wrong_value=int(t["wrong_value"]),
        wrong_value_timing_only=sum(
            1 for f in report["facts"] if f["outcome"] == "wrong_value" and f["timing_only"]
        ),
        missed=int(t["missed"]),
        false_positives=int(t["false_positives"]),
        excluded_unmatched=int(t["excluded_unmatched"]),
        absent_correct=int(t["absent_correct"]),
        absent_false_positive=int(t["absent_false_positive"]),
    )


def _gold_origin(gold: Gold) -> tuple[dict[str, int], Counts]:
    origin: dict[str, int] = {}
    for f in gold.facts:
        origin[f.origin] = origin.get(f.origin, 0) + 1
    with_clause = sum(f.guideline_clause is not None for f in gold.facts)
    return dict(sorted(origin.items())), _counts(with_clause, len(gold.facts))


def trap_results(
    meta: CaseMeta,
    rows: Mapping[str, RowScore],
    run_status: str,
    failed_stage: str | None,
) -> list[TrapResult]:
    """One verdict per trap the variant lists (see the module docstring)."""
    failing = [cid for cid in meta.tests if cid in rows and not rows[cid].correct]
    first: str | None
    stage: str | None
    if run_status != "completed":
        first, stage = RUN_FAILED, failed_stage
        failing = list(meta.tests)
    elif failing:
        classes = {rows[cid].first_error for cid in failing} - {None}
        ordered = [c for c in ERROR_CLASSES if c in classes]
        first = ordered[0] if ordered else None
        stage = FIRST_ERROR_STAGE.get(first) if first else None
    else:
        first, stage = None, None
    return [
        TrapResult(
            trap_id=t,
            variant_id=meta.variant_id,
            passed=first is None,
            first_error=first,
            stage=stage,
            failing_rows=failing,
        )
        for t in meta.traps
    ]


def _case_flags(report: Mapping[str, Any]) -> CaseFlagsScore:
    cf = report["case_flags"]
    return CaseFlagsScore(gold=sorted(cf["gold"]), live=sorted(cf["live"]), correct=cf["correct"])


def score_case(
    report: Mapping[str, Any],
    *,
    gold: Gold,
    meta: CaseMeta,
    rules: RulesTable,
    facts_rows: Sequence[Mapping[str, Any]],
    cost_usd: float | None,
) -> CaseScore:
    """Score one completed run from its comparison report (`compare.compare_case`)."""
    sources = condition_sources(rules)
    run = report["run"]
    conditions = {
        cid: _row(cid, r, sources, first_error=r["first_error"])
        for cid, r in report["conditions"].items()
    }
    claims = {
        cid: _row(cid, r, sources, first_error=r["first_error"])
        for cid, r in report["claims"].items()
    }
    rows = {**conditions, **claims}
    exclusions = [r for r in conditions.values() if r.kind == "exclusion"]
    gold_review = [r for r in exclusions if r.gold_status == "review"]
    missed = sum(r.missed_exclusion for r in gold_review)
    workload = human_workload(conditions.values())
    origin, with_clause = _gold_origin(gold)
    return CaseScore(
        variant_id=meta.variant_id,
        case_id=meta.case_id,
        section=meta.section,
        gold_sha256=str(report["gold_sha256"]),
        run_id=int(run["run_id"]),
        run_status=str(run["status"]),
        failed_stage=None,
        extraction_source=run.get("extraction_source"),
        conditions=conditions,
        claims=claims,
        case_flags=_case_flags(report),
        conditions_correct=_counts(sum(r.correct for r in conditions.values()), len(conditions)),
        claims_correct=_counts(sum(r.correct for r in claims.values()), len(claims)),
        false_supports=false_support_counts(conditions.values()),
        claims_false_supports=false_support_counts(claims.values()),
        missed_exclusions=_counts(missed, len(gold_review)),
        exclusion_evidence_found=len(gold_review) - missed,
        human_workload=workload,
        needs_human=workload > 0,
        first_errors=_first_errors(rows.values()),
        facts=_fact_counts(report),
        citations=_citations(gold, report, facts_rows),
        positions=_positions(facts_rows),
        exclusion_reasons=_exclusion_reasons(facts_rows),
        traps=trap_results(meta, rows, str(run["status"]), None),
        gold_origin=origin,
        gold_with_clause=with_clause,
        cost_usd=cost_usd,
    )


def score_failed_case(
    *,
    gold: Gold,
    meta: CaseMeta,
    rules: RulesTable,
    gold_sha256: str,
    run_id: int | None,
    run_status: str,
    failed_stage: str | None,
    cost_usd: float | None,
) -> CaseScore:
    """A run that did not complete: every condition and claim stays in its denominator and
    counts as wrong (`run_failed`); nothing is credited, not even expected-absent rows."""
    sources = condition_sources(rules)
    blank: dict[str, Any] = {"status": None, "flags": [], "correct": False}
    conditions = {
        c.id: _row(
            c.id,
            {**blank, "gold_status": c.status, "gold_flags": list(c.flags)},
            sources,
            first_error=RUN_FAILED,
        )
        for c in gold.conditions
    }
    claims = {
        c.id: _row(
            c.id,
            {**blank, "gold_status": c.status, "gold_flags": []},
            sources,
            first_error=RUN_FAILED,
        )
        for c in gold.claims
    }
    rows = {**conditions, **claims}
    gold_review = [
        r for r in conditions.values() if r.kind == "exclusion" and r.gold_status == "review"
    ]
    origin, with_clause = _gold_origin(gold)
    zero = FalseSupportCounts(
        count=0,
        gold_non_supported=0,
        system_supported=0,
        correctly_automated=_counts(0, 0),
    )
    return CaseScore(
        variant_id=meta.variant_id,
        case_id=meta.case_id,
        section=meta.section,
        gold_sha256=gold_sha256,
        run_id=run_id,
        run_status=run_status,
        failed_stage=failed_stage,
        extraction_source=None,
        conditions=conditions,
        claims=claims,
        case_flags=CaseFlagsScore(gold=sorted(gold.case_flags), live=[], correct=False),
        conditions_correct=_counts(0, len(conditions)),
        claims_correct=_counts(0, len(claims)),
        false_supports=false_support_counts(conditions.values()),
        claims_false_supports=false_support_counts(claims.values()) if claims else zero,
        missed_exclusions=_counts(len(gold_review), len(gold_review)),
        exclusion_evidence_found=0,
        human_workload=None,
        needs_human=True,
        first_errors=_first_errors(rows.values()),
        facts=FactCounts(
            gold_facts=len(gold.facts),
            matched=0,
            matched_but_excluded=0,
            wrong_value=0,
            wrong_value_timing_only=0,
            missed=len(gold.facts),
            false_positives=0,
            excluded_unmatched=0,
            absent_correct=0,
            absent_false_positive=0,
        ),
        citations=CitationCounts(
            quotes_located=_counts(0, 0),
            facts_correct=_counts(0, len(gold.facts)),
            gold_evidence_recalled=_counts(0, len(gold.facts)),
        ),
        positions=PositionCounts(verbatim=0, normalized=0, candidate=0, not_found=0),
        exclusion_reasons={},
        traps=trap_results(meta, rows, run_status, failed_stage),
        gold_origin=origin,
        gold_with_clause=with_clause,
        cost_usd=cost_usd,
    )


def score_stored_run(
    store: Store,
    run_id: int,
    *,
    gold: Gold,
    gold_sha256: str,
    meta: CaseMeta,
    rules: RulesTable,
    drugs: DrugIndex,
    questions: frozenset[tuple[str, str]] = frozenset(),
) -> CaseScore:
    """Score a stored run; a run that did not complete every stage is scored as failed."""
    run = store.case_run(run_id)
    cost = store.cost_for_run(run_id)
    if run["status"] != "completed" or run["stopped_after"] is not None:
        return score_failed_case(
            gold=gold,
            meta=meta,
            rules=rules,
            gold_sha256=gold_sha256,
            run_id=run_id,
            run_status=str(run["status"]) if run["stopped_after"] is None else "stopped",
            failed_stage=run["failed_stage"] or run["stopped_after"],
            cost_usd=cost,
        )
    report = compare_stored_run(
        store,
        run_id,
        gold=gold,
        gold_sha256=gold_sha256,
        rules=rules,
        drugs=drugs,
        questions=questions,
    )
    return score_case(
        report,
        gold=gold,
        meta=meta,
        rules=rules,
        facts_rows=store.facts_for_run(run_id),
        cost_usd=cost,
    )


# --- a split ----------------------------------------------------------------------------------


def _sum_dicts(dicts: Iterable[Mapping[str, int]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for d in dicts:
        for k, v in d.items():
            out[k] = out.get(k, 0) + v
    return dict(sorted(out.items()))


def _sum_false(items: Iterable[FalseSupportCounts]) -> FalseSupportCounts:
    items = list(items)
    return FalseSupportCounts(
        count=sum(i.count for i in items),
        gold_non_supported=sum(i.gold_non_supported for i in items),
        system_supported=sum(i.system_supported for i in items),
        correctly_automated=Counts(
            n=sum(i.correctly_automated.n for i in items),
            of=sum(i.correctly_automated.of for i in items),
        ),
    )


def _sum_model(cls: type[Any], items: Sequence[Any]) -> Any:
    fields = list(cls.model_fields)
    return cls(**{f: sum(getattr(i, f) for i in items) for f in fields})


def micro_totals(cases: Sequence[CaseScore]) -> MicroTotals:
    """Pooled counts over `cases` (an empty section gives zeros)."""
    zero = _counts(0, 0)

    def total(get: Any) -> Counts:
        out = zero
        for c in cases:
            out = _add(out, get(c))
        return out

    return MicroTotals(
        variants=len(cases),
        case_families=len({c.case_id for c in cases}),
        runs_failed=sum(c.run_status != "completed" for c in cases),
        conditions_correct=total(lambda c: c.conditions_correct),
        claims_correct=total(lambda c: c.claims_correct),
        false_supports=_sum_false(c.false_supports for c in cases),
        claims_false_supports=_sum_false(c.claims_false_supports for c in cases),
        missed_exclusions=total(lambda c: c.missed_exclusions),
        exclusion_evidence_found=sum(c.exclusion_evidence_found for c in cases),
        human_workload=sum(c.human_workload or 0 for c in cases),
        packets_needing_human=_counts(sum(c.needs_human for c in cases), len(cases)),
        first_errors=_sum_dicts(c.first_errors for c in cases),
        facts=_sum_model(FactCounts, [c.facts for c in cases])
        if cases
        else FactCounts(
            gold_facts=0,
            matched=0,
            matched_but_excluded=0,
            wrong_value=0,
            wrong_value_timing_only=0,
            missed=0,
            false_positives=0,
            excluded_unmatched=0,
            absent_correct=0,
            absent_false_positive=0,
        ),
        citations=CitationCounts(
            quotes_located=total(lambda c: c.citations.quotes_located),
            facts_correct=total(lambda c: c.citations.facts_correct),
            gold_evidence_recalled=total(lambda c: c.citations.gold_evidence_recalled),
        ),
        positions=_sum_model(PositionCounts, [c.positions for c in cases])
        if cases
        else PositionCounts(verbatim=0, normalized=0, candidate=0, not_found=0),
        exclusion_reasons=_sum_dicts(c.exclusion_reasons for c in cases),
    )


def macro_rows(
    cases: Sequence[CaseScore], group: str, sources: Mapping[str, str]
) -> list[ConditionMacro]:
    """One row per condition (or claim) id over every variant whose gold scores it."""
    ids: list[str] = []
    for c in cases:
        for cid in getattr(c, group):
            if cid not in ids:
                ids.append(cid)
    out = []
    for cid in sorted(ids):
        rows = [(c.variant_id, getattr(c, group)[cid]) for c in cases if cid in getattr(c, group)]
        out.append(
            ConditionMacro(
                id=cid,
                kind=kind_of(cid),
                correct=_counts(sum(r.correct for _, r in rows), len(rows)),
                false_supports=sum(r.false_support for _, r in rows),
                policy_source=sources.get(cid),
                by_variant={vid: r.status for vid, r in rows},
            )
        )
    return out


def coverage_matrix(
    metas: Sequence[CaseMeta], fixture_traps: Mapping[str, Sequence[str]]
) -> CoverageMatrix:
    """Trap × test type; a cell lists the variants or fixtures covering it. Columns no
    public test type fills yet stay empty and are listed under `not_covered`."""
    cells: dict[str, dict[str, list[str]]] = {}

    def cell(trap: str, test_type: str) -> list[str]:
        return cells.setdefault(trap, {t: [] for t in TEST_TYPES})[test_type]

    for m in metas:
        for t in m.traps:
            cell(t, "ladder_level" if m.dirty else "integrated_case").append(m.variant_id)
    for name in sorted(fixture_traps):
        for t in fixture_traps[name]:
            cell(t, "rules_fixture").append(name)
    traps = sorted(cells)
    not_covered = [
        {"trap_id": t, "test_type": tt} for t in traps for tt in TEST_TYPES if not cells[t][tt]
    ]
    filled = sum(bool(cells[t][tt]) for t in traps for tt in TEST_TYPES)
    return CoverageMatrix(
        traps=traps,
        test_types=list(TEST_TYPES),
        cells={t: {tt: sorted(cells[t][tt]) for tt in TEST_TYPES} for t in traps},
        filled=_counts(filled, len(traps) * len(TEST_TYPES)),
        not_covered=not_covered,
    )


def trap_scores(cases: Sequence[CaseScore]) -> list[TrapScore]:
    results: dict[str, list[TrapResult]] = {}
    for c in cases:
        for r in c.traps:
            results.setdefault(r.trap_id, []).append(r)
    out = []
    for trap in sorted(results):
        rs = sorted(results[trap], key=lambda r: r.variant_id)
        errors: dict[str, int] = {}
        for r in rs:
            if r.first_error:
                errors[r.first_error] = errors.get(r.first_error, 0) + 1
        out.append(
            TrapScore(
                trap_id=trap,
                opportunities=len(rs),
                passed=sum(r.passed for r in rs),
                results=rs,
                first_errors=dict(sorted(errors.items())),
            )
        )
    return out


def score_split(
    cases: Sequence[CaseScore],
    *,
    manifest_sha256: str,
    rules: RulesTable,
    metas: Sequence[CaseMeta],
    fixture_traps: Mapping[str, Sequence[str]],
) -> SplitScore:
    """The dev split: pooled (micro) and per-condition (macro) counts, one section per
    text origin with its own counts (never summed across sections), traps and coverage."""
    sources = condition_sources(rules)
    by_id = {c.variant_id: c for c in sorted(cases, key=lambda c: c.variant_id)}
    sections = {}
    for s in SECTIONS:
        subset = [c for c in by_id.values() if c.section == s]
        sections[s] = SectionScore(
            section=s, variants=[c.variant_id for c in subset], micro=micro_totals(subset)
        )
    origin = _sum_dicts(c.gold_origin for c in cases)
    with_clause = _counts(0, 0)
    for c in cases:
        with_clause = _add(with_clause, c.gold_with_clause)
    return SplitScore(
        scoring_version=SCORING_VERSION,
        split="dev",
        manifest_sha256=manifest_sha256,
        cases=by_id,
        micro=micro_totals(list(by_id.values())),
        macro={
            "conditions": macro_rows(list(by_id.values()), "conditions", sources),
            "claims": macro_rows(list(by_id.values()), "claims", sources),
        },
        sections=sections,
        traps=trap_scores(list(by_id.values())),
        coverage=coverage_matrix(metas, fixture_traps),
        gold_origin=origin,
        gold_with_clause=with_clause,
        rules_version=rules.version,
        policy_sources=[
            PolicySourceRow(
                id=s.id,
                last_modified=s.last_modified.isoformat() if s.last_modified else None,
            )
            for s in rules.policy_snapshot.sources
        ],
        condition_sources=sources,
        out_of_scope=list(OUT_OF_SCOPE),
    )
