"""Shared test helpers: load a script as a module so its `main(argv)` runs in-process."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from bridge_check.compute import CaseContext
    from bridge_check.rules import Decision, Policy
    from bridge_check.verify import CheckedEvidence, VerifyResult

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures" / "synthetic"


def load_script(name: str) -> ModuleType:
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"script_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES


# --- Verify helpers: synthetic facts and documents -------------------------------------------

_FACT_DEFAULTS: dict[str, dict[str, object]] = {
    "patient_identity": {"patient_id": "", "name": "", "dob": None, "stated_age": None},
    "doc_dates": {"target_doc_id": "D1", "date": "2025-03-15"},
    "glp1_start": {"drug": "Wegovy", "date": None, "purpose": "unknown"},
    "prior_glp1": {"drug": "Wegovy", "date": None, "payer": "unknown", "compounded": None},
    "anthropometrics": {"kind": "bmi", "raw_value": "30", "raw_unit": ""},
    "bp_readings": {"sbp": 140, "dbp": 90},
    "labs": {"kind": "a1c", "raw_value": "6.1", "raw_unit": "%"},
    "medications": {
        "name": "amlodipine",
        "dose": "",
        "indication": "",
        "start": None,
        "start_precision": None,
        "end": None,
        "end_precision": None,
        "end_kind": "unknown",
        "list_id": "",
    },
    "medication_lists": {"list_id": "L1", "complete": False, "section_title": ""},
    "diagnoses": {
        "concept": "other",
        "osa_severity": "unspecified",
        "ahi": None,
        "fibrosis_stage": "",
        "cirrhosis": None,
        "ckd_stage": "",
        "symptomatic": "unknown",
    },
    "lifestyle": {
        "kind": "nutrition",
        "program_type": "advice_only",
        "attendance": "unknown",
        "start": None,
        "end": None,
        "end_kind": "unknown",
        "limitation": "",
        "description": "diet advice",
    },
    "pa_form_claims": {"claim_id": "claim.drug", "claimed_value": "Wegovy"},
}


def fact(fact_field: str, quote: str, **fields: object) -> dict[str, object]:
    """One synthetic fact in document `D1` (override with `doc_id=`), default axes, no date."""
    return {
        "doc_id": "D1",
        "quote": quote,
        "certainty": "present",
        "subject": "patient",
        "temporality": "current",
        "event_date": "",
        "date_precision": "none",
        "relative_to_glp1_initiation": "unknown",
        **_FACT_DEFAULTS[fact_field],
        **fields,
    }


def run_verify(
    docs: Mapping[str, str | tuple[str, str]],
    facts: Mapping[str, list[dict[str, object]]],
    *,
    patient_id: str = "P-0001",
    dob: str = "1960-01-01",
) -> VerifyResult:
    """`verify_case` over synthetic documents (`doc_id -> text` or `(role, text)`)."""
    from bridge_check.input import PrimaryPatient
    from bridge_check.schema import Extraction
    from bridge_check.text import sha256_hex
    from bridge_check.verify import Document, VerifyContext, verify_case

    documents = {}
    for doc_id, value in docs.items():
        role, text = value if isinstance(value, tuple) else ("clinical", value)
        documents[doc_id] = Document(doc_id, role, text, sha256_hex(text))
    ext = Extraction.model_validate(facts)
    primary = PrimaryPatient.model_validate(
        {"patient_id": patient_id, "name": "Synthetic Patient", "dob": dob}
    )
    return verify_case(ext, documents, VerifyContext.load(primary))


# --- Compute and rules helpers: CheckedEvidence and CaseContext without a database ----------

_VALUE_FIELDS = frozenset({"anthropometrics", "labs"})


def checked(
    fact_field: str,
    *,
    doc_id: str = "D1",
    evidence_id: int | None = None,
    event_date: str | None = None,
    event_date_source: str | None = None,
    quote_date: str | None = None,
    relative_llm: str = "at",
    certainty: str = "present",
    subject: str = "patient",
    temporality: str = "current",
    position_status: str = "verbatim",
    assertion_check: str | None = "matched",
    exclusion_reasons: tuple[str, ...] = (),
    flags: tuple[str, ...] = (),
    **attrs: object,
) -> CheckedEvidence:
    """One already-verified fact with the field's defaults; `attrs` override the attributes
    (`kind`, `concept`, `raw_value`, `raw_unit` go to their own columns). The model's
    timepoint defaults to `at` (the usual test fact sits on the initiation day); pass
    `relative_llm` when the fact is dated elsewhere."""
    from bridge_check.verify import CheckedEvidence

    attributes: dict[str, object] = {**_FACT_DEFAULTS[fact_field], **attrs}
    kind = attributes.pop("kind", None) if fact_field in _VALUE_FIELDS | {"lifestyle"} else None
    concept = attributes.pop("concept", None) if fact_field == "diagnoses" else None
    raw_value = attributes.pop("raw_value", None) if fact_field in _VALUE_FIELDS else None
    raw_unit = attributes.pop("raw_unit", None) if fact_field in _VALUE_FIELDS else None
    if fact_field == "medication_lists":
        attributes.setdefault("list_status", "current")  # what verify reads off the heading
    if quote_date is not None:
        attributes["quote_date"] = {
            "date": quote_date,
            "precision": {4: "year", 7: "month", 10: "day"}[len(quote_date)],
        }
    if event_date is not None and event_date_source is None:
        event_date_source = "llm"
    precision = {4: "year", 7: "month", 10: "day"}[len(event_date)] if event_date else None
    tag = evidence_id if evidence_id is not None else 0
    return CheckedEvidence(
        field=fact_field,
        fact_path=f"{fact_field}[{tag}]",
        kind=str(kind) if kind is not None else None,
        concept=str(concept) if concept is not None else None,
        doc_id=doc_id,
        doc_sha256="0" * 64,
        start=0 if position_status != "not_found" else None,
        end=1 if position_status != "not_found" else None,
        quote="x",
        raw_value=str(raw_value) if raw_value is not None else None,
        raw_unit=str(raw_unit) if raw_unit is not None else None,
        event_date=event_date,
        date_precision=precision,
        certainty_llm=certainty,
        subject_llm=subject,
        temporality_llm=temporality,
        certainty_checked=certainty if assertion_check else None,
        subject_checked=subject if assertion_check else None,
        temporality_checked=temporality if assertion_check else None,
        relative_llm=relative_llm,
        position_status=position_status,
        assertion_check=assertion_check,
        exclusion_reasons=exclusion_reasons,
        flags=flags,
        ref=f"{doc_id}[0:1] {tag:08x}",
        event_date_source=event_date_source,
        attributes=attributes,
    )


def ctx(**overrides: object) -> CaseContext:
    """A `CaseContext` for a Wegovy course started 2025-03-15, assessed 2026-10-15, with the
    committed drug table and documents `D1` (clinical) and `D2` (clinical), both `match`."""
    from datetime import date

    from bridge_check.compute import CaseContext
    from bridge_check.rules_schema import load_drugs

    values: dict[str, object] = {
        "target_drug": "Wegovy",
        "target_start": date(2025, 3, 15),
        "assessment_date": date(2026, 10, 15),
        "doc_roles": {"D1": "clinical", "D2": "clinical"},
        "doc_identity": {"D1": "match", "D2": "match"},
        "drugs": load_drugs(ROOT / "rules" / "drugs-v1.yaml"),
        "evidence_ids": None,
    }
    values.update(overrides)
    return CaseContext(**values)  # type: ignore[arg-type]


def policy() -> Policy:
    from bridge_check.rules import Policy
    from bridge_check.rules_schema import load_rules

    return Policy.from_rules(load_rules(ROOT / "rules" / "bridge-v1.yaml"))


def decide(evidence: Sequence[CheckedEvidence], **overrides: object) -> dict[str, Decision]:
    """compute + evaluate_rules over `evidence`, keyed by condition id."""
    from bridge_check.compute import compute
    from bridge_check.rules import evaluate_rules

    pol = overrides.pop("policy", None)
    facts = compute(evidence, ctx(**overrides))
    return {d.condition: d for d in evaluate_rules(facts, pol or policy())}  # type: ignore[arg-type]


INITIATION = checked(
    "glp1_start",
    drug="Wegovy",
    date="2025-03-15",
    event_date="2025-03-15",
    relative_llm="at",
    purpose="weight",
)
"""A verified start of the target course on 2025-03-15 in `D1`."""
