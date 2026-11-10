"""Compare one completed run against gold (contract §8), deterministically.

Facts: every gold fact is assigned at most one evidence row (`eval_match.is_match`, greedy
one-to-one in gold order, lowest `evidence_id` first). A row with any evidence-level
exclusion reason never counts as a match; when it is the only match it is reported as
`matched_but_excluded`. Leftover rows without exclusion reasons are false positives.

Conditions and claims: live status and flags against gold; every mismatch gets the class of
the first upstream error, in the order of `classify_condition`.

Outputs carry enums, counts, key names and evidence references (`doc_id[start:end] sha8`)
only: never a quote, a value read from a document, or an identifier.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from bridge_check.compute import DrugIndex, glp1_canonical
from bridge_check.enums import CONDITION_IDS, MTSAMPLES_DOC_ID_PREFIX
from bridge_check.eval_match import DIAGNOSIS_OPTIONAL, MATCH_KEYS, is_match
from bridge_check.eval_match import _values_equal as values_equal
from bridge_check.gold_schema import ExpectedAbsent, Gold, GoldFact
from bridge_check.rules_schema import ANTIHYPERTENSIVE_CLASSES, RulesTable
from bridge_check.store import Store
from bridge_check.text import sha8

COMPARE_VERSION = 1

ERROR_CLASSES: tuple[str, ...] = (
    "gold_question",
    "extraction_missed",
    "extraction_wrong_value",
    "verify_excluded",
    "compute_timepoint",
    "rules",
)
"""First-upstream-error classes, in the order `classify_condition` tests them."""

TIMING_REASONS: frozenset[str] = frozenset(
    {"after_initiation", "before_initiation", "timing_unknown", "period_unknown"}
)

LABEL_KEYS: frozenset[str] = frozenset({"list_id"})
"""Keys whose values are labels each side invents (a list id). Gold labels are translated to
the system label of the matched `medication_lists` fact (`align_list_ids`); a system label
is ignored where gold states none."""

NOT_STATED: frozenset[str] = frozenset({"unknown", "none_stated", "unspecified"})
"""Enum values that mean "the document does not say"; gold leaves those keys out."""
NOT_STATED_KEYS: tuple[str, ...] = (
    "attendance",
    "end_kind",
    "payer",
    "program_type",
    "purpose",
    "osa_severity",
    "symptomatic",
)
TIMING_KEYS: frozenset[str] = frozenset({"event_date", "relative_to_glp1_initiation"})

Selector = tuple[str, str | None]
"""`(field, kind or concept or claim id)`; None matches every fact of the field."""


# --- views fed to `is_match` ------------------------------------------------------------------


def gold_ref(fact: GoldFact) -> str:
    """`doc_id[start:end] sha8` of the gold span (sha8 of the quote, or of its stored hash)."""
    short = fact.quote_sha256[:8] if fact.quote_sha256 is not None else sha8(fact.quote or "")
    return f"{fact.doc_id}[{fact.start}:{fact.end}] {short}"


def _selector_value(row: Mapping[str, Any]) -> str | None:
    if row.get("field") == "pa_form_claims":
        value = row.get("claim_id")
    else:
        value = row.get("kind") or row.get("concept")
    return str(value) if value is not None else None


def _not_stated(view: dict[str, Any]) -> dict[str, Any]:
    for key in NOT_STATED_KEYS:
        if view.get(key) in NOT_STATED:
            view[key] = None
    return view


def gold_view(fact: GoldFact) -> dict[str, Any]:
    """The gold fact in the key space of `MATCH_KEYS`. Quote offsets move to `offset_*`;
    a medication's `start`/`end` are its period dates (`period_start`/`period_end`)."""
    view = fact.model_dump(
        exclude={"quote", "quote_sha256", "origin", "review", "guideline_clause"}
    )
    view["offset_start"], view["offset_end"] = view.pop("start"), view.pop("end")
    if fact.field == "medications":
        view["start"], view["end"] = fact.period_start, fact.period_end
    return _not_stated(view)


def _blank(value: Any) -> Any:
    return None if value == "" else value


def system_view(
    row: Mapping[str, Any],
    med_periods: Mapping[int, Mapping[str, Any]],
    drugs: DrugIndex,
) -> dict[str, Any]:
    """One evidence row (`Store.facts_for_run`) in the key space of `MATCH_KEYS`."""
    attrs = {k: _blank(v) for k, v in dict(row["attrs"]).items()}
    view: dict[str, Any] = {
        k: row[k]
        for k in (
            "evidence_id",
            "field",
            "kind",
            "concept",
            "doc_id",
            "event_date",
            "certainty",
            "subject",
            "temporality",
        )
    }
    view.update({k: v for k, v in attrs.items() if k not in ("name", "drug")})
    view["norm_value"] = row.get("norm_value")
    view["relative_to_glp1_initiation"] = row.get("relative_computed") or row.get("relative_llm")
    for key in ("relative_llm", "relative_computed", "event_date_source"):
        view[key] = row.get(key)
    field_name = row["field"]
    if field_name == "medications":
        period = med_periods.get(int(row["evidence_id"]))
        name = str(attrs.get("name") or "")
        if period is not None:
            view["drug_canonical"] = period["drug_canonical"]
        else:
            drug = drugs.lookup(name) if name else None
            view["drug_canonical"] = drug.drug_canonical if drug else name.casefold() or None
    if field_name in ("glp1_start", "prior_glp1"):
        drug_name = attrs.get("drug")
        view["drug_canonical"] = glp1_canonical(str(drug_name)) if drug_name else None
    if field_name == "glp1_start":
        view.setdefault("payer", None)
    if field_name == "patient_identity" and str(row["doc_id"]).startswith(MTSAMPLES_DOC_ID_PREFIX):
        view["patient_id"] = None
        view["dob"] = None
    return _not_stated(view)


def _labels_aligned(gold: Mapping[str, Any], system: dict[str, Any]) -> dict[str, Any]:
    """`system` with label keys copied from gold where gold states none (`LABEL_KEYS`)."""
    out = dict(system)
    for key in LABEL_KEYS:
        if gold.get(key) is None:
            out[key] = None
    return out


def align_list_ids(
    gold: Sequence[Mapping[str, Any]], system: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Gold views with each medication `list_id` replaced by the label of the system list
    matched to the gold list of that id; an unmatched gold list keeps an impossible label."""
    lists_g = [g for g in gold if g.get("field") == "medication_lists"]
    lists_s = [s for s in system if s.get("field") == "medication_lists"]
    mapping: dict[str, Any] = {}
    taken: set[int] = set()
    for g in lists_g:
        for s in sorted(lists_s, key=lambda r: int(r["evidence_id"])):
            if int(s["evidence_id"]) not in taken and is_match(g, {**s, "list_id": None}):
                taken.add(int(s["evidence_id"]))
                mapping[str(g.get("list_id"))] = s.get("list_id")
                break
    out = []
    for g in gold:
        view = dict(g)
        label = view.get("list_id")
        if label is not None:
            view["list_id"] = mapping.get(str(label), f"unmatched-gold-list:{label}")
        out.append(view)
    return out


def matches(gold: Mapping[str, Any], system: Mapping[str, Any]) -> bool:
    return is_match(gold, _labels_aligned(gold, dict(system)))


def mismatched_keys(gold: Mapping[str, Any], system: Mapping[str, Any]) -> list[str]:
    """Names of the keys that keep `system` from matching `gold` (names only, no values)."""
    field_name = str(gold.get("field"))
    aligned = _labels_aligned(gold, dict(system))
    keys = ["certainty", "subject", "temporality", *MATCH_KEYS.get(field_name, ())]
    if gold.get("event_date") is not None:
        keys.append("event_date")
    if field_name == "diagnoses":
        keys += [k for k in DIAGNOSIS_OPTIONAL if gold.get(k) not in (None, "")]
    out = []
    for key in keys:
        if key == "norm_value":
            kind = gold.get("kind")
            if not values_equal(
                str(kind) if kind is not None else None, gold.get(key), aligned.get(key)
            ):
                out.append(key)
            continue
        if aligned.get(key) != gold.get(key):
            out.append(key)
    return sorted(set(out)) or ["unknown"]


# --- fact assignment --------------------------------------------------------------------------


@dataclass
class FactOutcome:
    gold_index: int
    outcome: str  # matched | matched_but_excluded | wrong_value | missed
    evidence_id: int | None = None
    mismatched: list[str] = field(default_factory=list)
    timing_only: bool = False
    """A `wrong_value` whose only differences are timing keys that compute derived: the
    event date is not the extractor's own (`event_date_source != "llm"`) and the extractor's
    `relative_llm` equals gold."""


def timing_only(gold: Mapping[str, Any], system: Mapping[str, Any], keys: Sequence[str]) -> bool:
    if not keys or not set(keys) <= TIMING_KEYS:
        return False
    if "event_date" in keys and system.get("event_date_source") == "llm":
        return False
    return not (
        "relative_to_glp1_initiation" in keys
        and system.get("relative_llm") != gold.get("relative_to_glp1_initiation")
    )


@dataclass
class Assignment:
    facts: list[FactOutcome]
    false_positives: list[int]
    excluded_unmatched: list[int]

    def evidence_of(self, outcome: str) -> set[int]:
        return {
            f.evidence_id for f in self.facts if f.outcome == outcome and f.evidence_id is not None
        }


def _bucket(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (row.get("field"), _selector_value(row), row.get("doc_id"))


def assign(gold: Sequence[Mapping[str, Any]], system: Sequence[Mapping[str, Any]]) -> Assignment:
    """Greedy one-to-one assignment, deterministic (gold order, then ascending evidence id).

    Each system row needs `evidence_id` and `exclusion_reasons` besides its match keys."""
    rows = sorted(system, key=lambda r: int(r["evidence_id"]))
    taken: set[int] = set()
    out: list[FactOutcome] = []
    for i, g in enumerate(gold):
        hits = [r for r in rows if int(r["evidence_id"]) not in taken and matches(g, r)]
        included = [r for r in hits if not r["exclusion_reasons"]]
        if included:
            eid = int(included[0]["evidence_id"])
            taken.add(eid)
            out.append(FactOutcome(i, "matched", eid))
            continue
        if hits:
            eid = int(hits[0]["evidence_id"])
            taken.add(eid)
            out.append(FactOutcome(i, "matched_but_excluded", eid))
            continue
        same = [r for r in rows if int(r["evidence_id"]) not in taken and _bucket(r) == _bucket(g)]
        if same:
            # the closest row of the bucket: fewest differing keys, then lowest evidence id
            scored = [(len(mismatched_keys(g, r)), int(r["evidence_id"]), r) for r in same]
            _, eid, r = min(scored, key=lambda t: (t[0], t[1]))
            keys = mismatched_keys(g, r)
            out.append(FactOutcome(i, "wrong_value", eid, keys, timing_only(g, r, keys)))
        else:
            out.append(FactOutcome(i, "missed"))
    wrong = {f.evidence_id for f in out if f.outcome == "wrong_value"}
    leftover = [r for r in rows if int(r["evidence_id"]) not in taken | wrong]
    return Assignment(
        facts=out,
        false_positives=[int(r["evidence_id"]) for r in leftover if not r["exclusion_reasons"]],
        excluded_unmatched=[int(r["evidence_id"]) for r in leftover if r["exclusion_reasons"]],
    )


# --- expected_absent --------------------------------------------------------------------------


def absent_hits(
    entry: ExpectedAbsent,
    system: Sequence[Mapping[str, Any]],
    med_periods: Mapping[int, Mapping[str, Any]],
) -> list[Mapping[str, Any]] | None:
    """System rows that contradict one `expected_absent` entry; None for a selector this
    function does not know (reported as `unsupported_selector`)."""
    rows = [r for r in system if r["field"] == entry.field]
    if entry.concept is not None:
        return [r for r in rows if r.get("concept") == entry.concept]
    kind = entry.kind
    if entry.field in ("anthropometrics", "labs", "lifestyle"):
        return [r for r in rows if r.get("kind") == kind]
    if entry.field == "bp_readings" and kind == "bp":
        return rows
    if entry.field == "medications" and kind == "antihypertensive":
        return [
            r
            for r in rows
            if (med_periods.get(int(r["evidence_id"])) or {}).get("class")
            in ANTIHYPERTENSIVE_CLASSES
        ]
    if entry.field == "prior_glp1" and kind == "payer":
        return [r for r in rows if r["attrs"].get("payer") not in (None, "", "unknown")]
    if entry.field == "pa_form_claims":
        return [r for r in rows if r["attrs"].get("claim_id") == kind]
    return None


# --- condition dependencies -------------------------------------------------------------------

REQUIRES_TO_SELECTORS: dict[str, tuple[Selector, ...]] = {
    "age_interval_at_initiation": (("patient_identity", None),),
    "initiation_date": (("glp1_start", None), ("doc_dates", None)),
    "initiation_purpose": (("glp1_start", None),),
    "doc_facts.doc_date": (("doc_dates", None),),
    "doc_facts.identity_status": (("patient_identity", None),),
    "wrong_patient": (("patient_identity", None),),
    "bmi_candidates": (
        ("anthropometrics", "height"),
        ("anthropometrics", "weight"),
        ("anthropometrics", "bmi"),
    ),
    "bp_at_initiation": (("bp_readings", None),),
    "med_periods": (("medications", None), ("medication_lists", None)),
    "distinct_antihypertensives_overlapping": (("medications", None),),
    "a1c": (("labs", "a1c"),),
    "fpg_mg_dl": (("labs", "fpg"),),
    "egfr": (("labs", "egfr"),),
    "prior_glp1": (("prior_glp1", None),),
    "lifestyle_applicable": (("lifestyle", None),),
    "bmi_bracket": (("pa_form_claims", "claim.bmi_bracket"), ("anthropometrics", None)),
}

CONCEPT_OF: dict[str, str] = {
    "bmi_path_b.hfpef": "hfpef",
    "bmi_path_b.htn": "hypertension",
    "bmi_path_b.ckd": "ckd",
    "bmi_path_c.prediabetes": "prediabetes",
    "bmi_path_c.mi": "mi",
    "bmi_path_c.stroke": "stroke",
    "bmi_path_c.pad": "pad",
    "exclusion.t2dm": "t2dm",
    "exclusion.osa": "osa",
    "exclusion.mash": "mash",
}


def condition_dependencies(rules: RulesTable) -> dict[str, tuple[Selector, ...]]:
    """Gold selectors each condition depends on, from the `requires` of the rules table
    (contract §7.3); pathways add their sub-results, lifestyle rows their own kind."""
    deps: dict[str, list[Selector]] = {cid: [] for cid in CONDITION_IDS}
    for cond in rules.conditions:
        for name in cond.requires:
            if name == "dx":
                deps[cond.id].append(("diagnoses", CONCEPT_OF[cond.id]))
            else:
                deps[cond.id].extend(REQUIRES_TO_SELECTORS[name])
    for path in ("bmi_path_b", "bmi_path_c"):
        for cid in CONDITION_IDS:
            if cid.startswith(path + "."):
                deps[path].extend(deps[cid])
    for kind in ("nutrition", "activity"):
        deps[f"lifestyle.{kind}"].append(("lifestyle", kind))
    return {cid: tuple(dict.fromkeys(sel)) for cid, sel in deps.items()}


def claim_dependencies(
    claim_id: str, deps: Mapping[str, tuple[Selector, ...]]
) -> tuple[Selector, ...]:
    base = claim_id.removeprefix("claim.")
    own: list[Selector] = [("pa_form_claims", claim_id)]
    if base == "drug":
        own.append(("glp1_start", None))
    elif base == "bmi_bracket":
        own.extend(REQUIRES_TO_SELECTORS["bmi_bracket"])
        own.append(("glp1_start", None))
    else:
        own.extend(deps.get(base, ()))
    return tuple(dict.fromkeys(own))


def _selected(selectors: Iterable[Selector], row: Mapping[str, Any]) -> bool:
    for fld, value in selectors:
        if row.get("field") == fld and (value is None or _selector_value(row) == value):
            return True
    return False


# --- classification ---------------------------------------------------------------------------


class GoldQuestion(BaseModel):
    """One gold item that looks wrong. `item` is a condition or claim id (the row is then
    classified `gold_question`) or `fact:<field>` for a fact-level question."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    variant_id: str
    item: str
    note: str


class GoldQuestions(BaseModel):
    """`reports/gold-questions-dev.json`: rows whose gold looks wrong, listed for the next
    guide revision. Never applied to gold."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    questions: list[GoldQuestion]

    def keys(self) -> frozenset[tuple[str, str]]:
        return frozenset((q.variant_id, q.item) for q in self.questions)


def classify_condition(
    *,
    variant_id: str,
    condition: str,
    selectors: tuple[Selector, ...],
    decision: Mapping[str, Any] | None,
    gold_facts: Sequence[Mapping[str, Any]],
    system_rows: Mapping[int, Mapping[str, Any]],
    assignment: Assignment,
    absent: Sequence[Mapping[str, Any]],
    questions: frozenset[tuple[str, str]],
) -> str:
    """First upstream error of one mismatching condition or claim; the first hit wins:
    gold question; a dependent gold fact missed; a dependent fact with a wrong extracted
    value; a dependent fact matched but excluded by verify; a timing difference compute
    derived (timing-only wrong value, a timing exclusion of a matched fact, or a computed
    relative timepoint that differs from gold); a spurious dependent fact or expected-absent
    hit (counted as a wrong extracted value); otherwise rules."""
    if (variant_id, condition) in questions:
        return "gold_question"
    dep = [f for f in assignment.facts if _selected(selectors, gold_facts[f.gold_index])]
    if any(f.outcome == "missed" for f in dep):
        return "extraction_missed"
    if any(f.outcome == "wrong_value" and not f.timing_only for f in dep):
        return "extraction_wrong_value"
    if any(f.outcome == "matched_but_excluded" for f in dep):
        return "verify_excluded"
    if any(f.outcome == "wrong_value" and f.timing_only for f in dep):
        return "compute_timepoint"
    matched = {f.evidence_id for f in dep if f.outcome == "matched"}
    excluded = (decision or {}).get("excluded_evidence") or []
    if any(x["evidence_id"] in matched and x["reason"] in TIMING_REASONS for x in excluded):
        return "compute_timepoint"
    for f in dep:
        if f.outcome != "matched" or f.evidence_id is None:
            continue
        g = gold_facts[f.gold_index]
        row = system_rows[f.evidence_id]
        if g.get("relative_to_glp1_initiation") != row.get("relative_computed") and row.get(
            "relative_computed"
        ):
            return "compute_timepoint"
    spurious = [eid for eid in assignment.false_positives if _selected(selectors, system_rows[eid])]
    absent_fp = [a for a in absent if a["status"] == "false_positive" and _selected(selectors, a)]
    if spurious or absent_fp:
        return "extraction_wrong_value"
    return "rules"


# --- one case ---------------------------------------------------------------------------------


def _result_row(
    gold_status: str,
    gold_flags: Sequence[str] | None,
    decision: Mapping[str, Any] | None,
    refs: Mapping[int, str],
) -> dict[str, Any]:
    """One condition (gold flags compared) or claim (`gold_flags` None: status only)."""
    status = decision["status"] if decision else None
    flags = sorted(decision["flags"]) if decision else []
    flags_ok = gold_flags is None or flags == sorted(gold_flags)
    return {
        "gold_status": gold_status,
        "gold_flags": sorted(gold_flags or []),
        "status": status,
        "flags": flags,
        "correct": status == gold_status and flags_ok,
        "first_error": None,
        "used": [refs.get(e, f"evidence:{e}") for e in (decision or {}).get("used_evidence", [])],
        "excluded": [
            {
                "ref": refs.get(x["evidence_id"], f"evidence:{x['evidence_id']}"),
                "reason": x["reason"],
            }
            for x in (decision or {}).get("excluded_evidence", [])
        ],
    }


def compare_case(
    *,
    gold: Gold,
    gold_sha256: str,
    run: Mapping[str, Any],
    facts: Sequence[Mapping[str, Any]],
    med_periods: Sequence[Mapping[str, Any]],
    decisions: Sequence[Mapping[str, Any]],
    rules: RulesTable,
    drugs: DrugIndex,
    questions: frozenset[tuple[str, str]] = frozenset(),
) -> dict[str, Any]:
    """The comparison report of one run (see the module docstring)."""
    periods = {int(p["evidence_id"]): p for p in med_periods}
    system = [
        {**system_view(r, periods, drugs), "exclusion_reasons": r["exclusion_reasons"]}
        for r in facts
    ]
    by_id = {int(r["evidence_id"]): r for r in facts}
    sys_by_id = {int(s["evidence_id"]): s for s in system}
    refs = {eid: str(r["ref"]) for eid, r in by_id.items()}
    golds = align_list_ids([gold_view(f) for f in gold.facts], system)
    assignment = assign(golds, system)

    fact_rows = []
    for f in assignment.facts:
        g = gold.facts[f.gold_index]
        row = by_id.get(f.evidence_id) if f.evidence_id is not None else None
        fact_rows.append(
            {
                "gold_index": f.gold_index,
                "field": g.field,
                "selector": _selector_value(golds[f.gold_index]),
                "doc_id": g.doc_id,
                "gold_ref": gold_ref(g),
                "outcome": f.outcome,
                "evidence_ref": refs.get(f.evidence_id) if f.evidence_id is not None else None,
                "position_status": row["position_status"] if row else None,
                "assertion_check": row["assertion_check"] if row else None,
                "exclusion_reasons": list(row["exclusion_reasons"]) if row else [],
                "mismatched_keys": f.mismatched,
                "timing_only": f.timing_only,
            }
        )

    def _row_ref(eid: int) -> dict[str, Any]:
        r = by_id[eid]
        return {
            "evidence_ref": refs[eid],
            "field": r["field"],
            "selector": _selector_value({**r, **r["attrs"]}),
            "position_status": r["position_status"],
            "exclusion_reasons": list(r["exclusion_reasons"]),
        }

    absent = []
    for entry in gold.expected_absent:
        hits = absent_hits(entry, facts, periods)
        if hits is None:
            status, ids, excl = "unsupported_selector", [], []
        else:
            ids = [refs[int(h["evidence_id"])] for h in hits if not h["exclusion_reasons"]]
            excl = [refs[int(h["evidence_id"])] for h in hits if h["exclusion_reasons"]]
            status = "false_positive" if ids else "not_found_correct"
        absent.append(
            {
                "field": entry.field,
                "kind": entry.kind,
                "concept": entry.concept,
                "status": status,
                "evidence_refs": ids,
                "excluded_refs": excl,
            }
        )

    deps = condition_dependencies(rules)
    decided = {str(d["condition"]): d for d in decisions}

    def _classified(cid: str, row: dict[str, Any], selectors: tuple[Selector, ...]) -> None:
        if row["correct"]:
            return
        row["first_error"] = classify_condition(
            variant_id=gold.variant_id,
            condition=cid,
            selectors=selectors,
            decision=decided.get(cid),
            gold_facts=golds,
            system_rows=sys_by_id,
            assignment=assignment,
            absent=absent,
            questions=questions,
        )

    conditions: dict[str, Any] = {}
    for gc in gold.conditions:
        row = _result_row(gc.status, gc.flags, decided.get(gc.id), refs)
        _classified(gc.id, row, deps.get(gc.id, ()))
        conditions[gc.id] = row
    claims: dict[str, Any] = {}
    for cl in gold.claims:
        row = _result_row(cl.status, None, decided.get(cl.id), refs)
        _classified(cl.id, row, claim_dependencies(cl.id, deps))
        claims[cl.id] = row
    extra_claims = sorted(
        c for c in decided if c.startswith("claim.") and c not in {x.id for x in gold.claims}
    )

    live_flags = sorted(run.get("case_flags") or [])
    first_errors: dict[str, int] = dict.fromkeys(ERROR_CLASSES, 0)
    for row in (*conditions.values(), *claims.values()):
        if row["first_error"]:
            first_errors[row["first_error"]] += 1
    outcomes = [f.outcome for f in assignment.facts]
    return {
        "compare_version": COMPARE_VERSION,
        "variant_id": gold.variant_id,
        "gold_version": gold.gold_version,
        "gold_sha256": gold_sha256,
        "run": {
            "run_id": run["id"],
            "status": run["status"],
            "input_hash": run["input_hash"],
            "extraction_source": run["extraction_source"],
            "prompt_version": run["prompt_version"],
            "schema_version": run["schema_version"],
            "rules_version": run["rules_version"],
            "code_sha": run["code_sha"],
        },
        "facts": fact_rows,
        "false_positives": [_row_ref(e) for e in assignment.false_positives],
        "excluded_unmatched": [_row_ref(e) for e in assignment.excluded_unmatched],
        "expected_absent": absent,
        "conditions": conditions,
        "claims": claims,
        "claims_not_in_gold": extra_claims,
        "case_flags": {
            "gold": sorted(gold.case_flags),
            "live": live_flags,
            "correct": live_flags == sorted(gold.case_flags),
        },
        "totals": {
            "gold_facts": len(gold.facts),
            "matched": outcomes.count("matched"),
            "matched_but_excluded": outcomes.count("matched_but_excluded"),
            "wrong_value": outcomes.count("wrong_value"),
            "missed": outcomes.count("missed"),
            "false_positives": len(assignment.false_positives),
            "excluded_unmatched": len(assignment.excluded_unmatched),
            "absent_correct": sum(a["status"] == "not_found_correct" for a in absent),
            "absent_false_positive": sum(a["status"] == "false_positive" for a in absent),
            "conditions_correct": sum(r["correct"] for r in conditions.values()),
            "conditions_total": len(conditions),
            "claims_correct": sum(r["correct"] for r in claims.values()),
            "claims_total": len(claims),
            "false_support": false_support_count(conditions),
            "claims_false_support": false_support_count(claims),
            "missed_exclusion": missed_exclusion_count(conditions),
            "first_error": first_errors,
        },
    }


def false_support_count(rows: Mapping[str, Mapping[str, Any]]) -> int:
    """Rows the system calls `supported` where gold does not (planning §3.1)."""
    return sum(
        r["status"] == "supported" and r["gold_status"] != "supported" for r in rows.values()
    )


def missed_exclusion_count(rows: Mapping[str, Mapping[str, Any]]) -> int:
    """Exclusion rows where gold found exclusion evidence (`review`) and the system did not
    (`insufficient` / `not_supported`)."""
    return sum(
        cid.startswith("exclusion.")
        and r["gold_status"] == "review"
        and r["status"] in ("insufficient", "not_supported")
        for cid, r in rows.items()
    )


# --- markdown ---------------------------------------------------------------------------------


def _flags(flags: Sequence[str]) -> str:
    return ", ".join(flags) if flags else "–"


def render_markdown(report: Mapping[str, Any]) -> str:
    t = report["totals"]
    lines = [
        f"## {report['variant_id']} (run {report['run']['run_id']})",
        "",
        f"Facts: {t['matched']} of {t['gold_facts']} matched, {t['matched_but_excluded']} "
        f"matched but excluded, {t['wrong_value']} wrong value, {t['missed']} missed, "
        f"{t['false_positives']} false positive(s); expected-absent "
        f"{t['absent_correct']} correct, {t['absent_false_positive']} false positive(s). "
        f"Conditions {t['conditions_correct']}/{t['conditions_total']}, claims "
        f"{t['claims_correct']}/{t['claims_total']}.",
        "",
        "| Row | Gold | Gold flags | Live | Live flags | Match | First error |",
        "|---|---|---|---|---|---|---|",
    ]
    for group in ("conditions", "claims"):
        for cid, r in report[group].items():
            lines.append(
                f"| `{cid}` | {r['gold_status']} | {_flags(r['gold_flags'])} | {r['status']} | "
                f"{_flags(r['flags'])} | {'yes' if r['correct'] else 'no'} | "
                f"{r['first_error'] or ''} |"
            )
    lines += [
        "",
        "| Gold fact | Field | Outcome | Evidence | Reasons / keys |",
        "|---|---|---|---|---|",
    ]
    for f in report["facts"]:
        if f["outcome"] == "matched":
            continue
        detail = ", ".join(f["exclusion_reasons"] or f["mismatched_keys"]) or "–"
        sel = f"/{f['selector']}" if f["selector"] else ""
        lines.append(
            f"| `{f['gold_ref']}` | {f['field']}{sel} | {f['outcome']} | "
            f"{'`' + f['evidence_ref'] + '`' if f['evidence_ref'] else '–'} | {detail} |"
        )
    for fp in report["false_positives"]:
        sel = f"/{fp['selector']}" if fp["selector"] else ""
        lines.append(f"| – | {fp['field']}{sel} | false_positive | `{fp['evidence_ref']}` | – |")
    return "\n".join(lines) + "\n"


def upsert_markdown_section(path: Path, variant_id: str, section: str) -> None:
    """Write `section` into `path`, replacing an existing `## <variant_id> ` section."""
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    head = f"## {variant_id} "
    parts = text.split("\n## ")
    kept = [p if i == 0 else "## " + p for i, p in enumerate(parts) if p.strip()]
    kept = [p for p in kept if not p.startswith(head)]
    kept.append(section)
    path.write_text("\n".join(p.rstrip("\n") + "\n" for p in kept), encoding="utf-8")


def compare_stored_run(
    store: Store,
    run_id: int,
    *,
    gold: Gold,
    gold_sha256: str,
    rules: RulesTable,
    drugs: DrugIndex,
    questions: frozenset[tuple[str, str]] = frozenset(),
) -> dict[str, Any]:
    """`compare_case` over one stored run."""
    run = store.case_run(run_id)
    return compare_case(
        gold=gold,
        gold_sha256=gold_sha256,
        run={**run, "case_flags": json.loads(run["case_flags"] or "[]")},
        facts=store.facts_for_run(run_id),
        med_periods=store.med_periods_for_run(run_id),
        decisions=store.decisions_for_run(run_id),
        rules=rules,
        drugs=drugs,
        questions=questions,
    )
