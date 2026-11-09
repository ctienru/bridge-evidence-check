"""The frozen cases through compute and rules with a hand-written extraction reply.

This is a rules test, not an extractor test: the scripted reply carries exactly the facts of
`cases/<variant>/expected.json` (quotes are read from the case documents at the gold offsets
at test time, so no document text is stored here; structured values are written by hand), and
every condition status, flag and claim status of the gold must come back from `bridge check`.
Case-15-L0 runs only when `BRIDGE_PRIVATE_CHECKOUT` points at the private checkout; its
hand-written reply lives there as `ladder/case-15-L0/fake-reply.json`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from conftest import ROOT

from bridge_check import cli
from bridge_check.cli import EXIT_OK, main
from bridge_check.extract import TOOL_NAME
from bridge_check.fake_client import FakeClient
from bridge_check.input import DOCS_DIR, load_input

CASE_01 = ROOT / "cases" / "case-01"
PRIVATE_ENV = "BRIDGE_PRIVATE_CHECKOUT"

# Hand-written structured fields per gold fact index of case-01 (values as the quotes spell
# them; the gold itself holds only normalized values and offsets).
_CASE_01_FIELDS: dict[int, dict[str, Any]] = {
    0: {"patient_id": "P-1042", "name": "", "dob": None, "stated_age": None},
    1: {"patient_id": "", "name": "", "dob": "1961-04-02", "stated_age": None},
    11: {"patient_id": "P-1042", "name": "", "dob": None, "stated_age": None},
    12: {"patient_id": "", "name": "", "dob": "1961-04-02", "stated_age": None},
    13: {"drug": "Wegovy", "date": "2025-03-15", "purpose": "weight"},
    14: {"target_doc_id": "D2-mtsamples-4985", "date": "2025-03-15"},
    15: {"patient_id": "", "name": "", "dob": None, "stated_age": 55},
    16: {"kind": "bmi", "raw_value": "46", "raw_unit": ""},
    23: {"name": "Norvasc", "list_id": "L1"},
    24: {"name": "Lopressor", "list_id": "L1"},
    25: {"list_id": "L1", "complete": False, "section_title": ""},
    28: {"kind": "height", "raw_value": "5'6\"", "raw_unit": ""},
    29: {"kind": "weight", "raw_value": "285.4", "raw_unit": "pounds"},
}


def _skip_unless_fetched(case_dir: Path) -> None:
    """Skip when a document listed in `input.yaml` is absent (MTSamples documents are never
    committed; the `tests` CI job fetches them when the mirror is up)."""
    docs = case_dir / DOCS_DIR
    missing = [
        d for d in load_input(case_dir).documents if not (docs / f"{d.doc_id}.txt").is_file()
    ]
    if missing:
        pytest.skip(f"{len(missing)} MTSamples document(s) not fetched (fetch_mtsamples.py)")


def _reply_from_gold(case_dir: Path, fields: dict[int, dict[str, Any]]) -> dict[str, Any]:
    gold = json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))
    texts = {}
    for path in (case_dir / "docs").glob("*.txt"):
        with path.open(encoding="utf-8", newline="") as fh:
            texts[path.stem] = fh.read()
    extraction: dict[str, list[dict[str, Any]]] = {}
    for i, f in enumerate(gold["facts"]):
        field = f["field"]
        quote = texts[f["doc_id"]][f["start"] : f["end"]]
        fact: dict[str, Any] = {
            "doc_id": f["doc_id"],
            "quote": quote,
            "certainty": f["certainty"],
            "subject": f["subject"],
            "temporality": f["temporality"],
            "event_date": "",
            "date_precision": "none",
            "relative_to_glp1_initiation": f["relative_to_glp1_initiation"],
        }
        if field == "glp1_start":
            fact["event_date"], fact["date_precision"] = f["date"], "day"
        if field == "doc_dates":
            fact["event_date"], fact["date_precision"] = f["date"], "day"
        if field == "pa_form_claims":
            fact |= {"claim_id": f["claim_id"], "claimed_value": f["claimed_value"]}
        elif field == "diagnoses":
            fact |= {
                "concept": f["concept"],
                "osa_severity": "unspecified",
                "ahi": None,
                "fibrosis_stage": "",
                "cirrhosis": None,
                "ckd_stage": "",
                "symptomatic": "unknown",
            }
        elif field == "medications":
            fact |= {
                "dose": "",
                "indication": "",
                "start": None,
                "start_precision": None,
                "end": None,
                "end_precision": None,
                "end_kind": f["end_kind"],
            }
        elif field == "lifestyle":
            fact |= {
                "kind": f["kind"],
                "program_type": f["program_type"],
                "attendance": "unknown",
                "start": None,
                "end": None,
                "end_kind": f["end_kind"],
                "limitation": "",
                "description": f["program_type"],
            }
        fact |= fields.get(i, {})
        extraction.setdefault(field, []).append(fact)
    return {
        "id": "msg_synthetic_gold_reply",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5-5",
        "content": [
            {
                "type": "tool_use",
                "id": "toolu_synthetic_gold_reply",
                "name": TOOL_NAME,
                "input": extraction,
            }
        ],
        "stop_reason": "tool_use",
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


def _run(
    case_dir: Path, reply: Path, db: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> dict[str, Any]:
    monkeypatch.setattr(cli, "make_client", lambda case_dir=None: FakeClient([reply]))
    code = main(["check", str(case_dir), "--db", str(db), "--json"])
    report: dict[str, Any] = json.loads(capsys.readouterr().out)
    assert code == EXIT_OK, report["dead_letters"]
    return report


def _compare(
    report: dict[str, Any],
    gold: dict[str, Any],
    gaps_claims: set[str],
    gaps_flags: dict[str, list[str]],
) -> None:
    by_id = {d["condition"]: d for d in report["decisions"]}
    mismatched_status = {
        c["id"]: (by_id[c["id"]]["status"], c["status"])
        for c in gold["conditions"]
        if by_id[c["id"]]["status"] != c["status"]
    }
    assert mismatched_status == {}
    mismatched_flags = {
        c["id"]: (by_id[c["id"]]["flags"], c["flags"])
        for c in gold["conditions"]
        if sorted(by_id[c["id"]]["flags"]) != sorted(c["flags"]) and c["id"] not in gaps_flags
    }
    assert mismatched_flags == {}
    assert report["case_flags"] == gold["case_flags"]
    claims = {
        c["id"]: (by_id.get(c["id"], {}).get("status"), c["status"])
        for c in gold["claims"]
        if c["id"] not in gaps_claims
    }
    assert {k: v for k, v in claims.items() if v[0] != v[1]} == {}


def test_case_01_gold_statuses_are_reproduced_by_the_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _skip_unless_fetched(CASE_01)
    reply = tmp_path / "reply.json"
    reply.write_text(json.dumps(_reply_from_gold(CASE_01, _CASE_01_FIELDS)), encoding="utf-8")
    report = _run(CASE_01, reply, tmp_path / "c.db", monkeypatch, capsys)
    gold = json.loads((CASE_01 / "expected.json").read_text(encoding="utf-8"))
    _compare(report, gold, set(), {})


def test_case_15_l0_gold_statuses_are_reproduced_by_the_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    private = os.environ.get(PRIVATE_ENV)
    if not private:
        pytest.skip(f"{PRIVATE_ENV} not set")
    case_dir, reply = _private_case(private)
    report = _run(case_dir, reply, tmp_path / "p.db", monkeypatch, capsys)
    gold = json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))
    _compare(report, gold, set(), {})


def _private_case(private: str) -> tuple[Path, Path]:
    case_dir = Path(private) / "ladder" / "case-15-L0"
    reply = case_dir / "fake-reply.json"
    # With the checkout given, a missing case or reply is a failure, not a skip.
    assert case_dir.is_dir(), "case-15-L0 is not in the private checkout"
    assert reply.is_file(), "case-15-L0 has no hand-written fake-reply.json in the private checkout"
    return case_dir, reply
