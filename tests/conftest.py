"""Shared test helpers: load a script as a module so its `main(argv)` runs in-process."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from bridge_check.verify import VerifyResult

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
