"""Each negative fixture under `fixtures/synthetic/verify/` through `bridge check`.

`BRIDGE_FAKE_CLIENT=1` makes the fake client use the fixture's own `fake-reply.json`, so
`bridge check <fixture> --json --stop-after verify` demonstrates one verifier behaviour.
Expected values are the per-evidence statuses in `--explain` order (extraction field order).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import FIXTURES

from bridge_check.cli import EXIT_OK, main

VERIFY = FIXTURES / "verify"

# fixture -> [(field, position_status, assertion_check, exclusion_reasons, flags)]
EXPECTED: dict[str, list[tuple[str, str, str | None, list[str], list[str]]]] = {
    "fabricated-quote": [
        ("patient_identity", "verbatim", "matched", [], []),
        ("diagnoses", "not_found", None, ["quote_not_found"], []),
    ],
    "paraphrased-quote": [
        ("patient_identity", "verbatim", "matched", [], []),
        ("diagnoses", "not_found", None, ["quote_not_found"], []),
    ],
    "value-changed": [
        ("patient_identity", "verbatim", "matched", [], []),
        ("anthropometrics", "candidate", "matched", ["value_not_in_quote"], []),
        ("anthropometrics", "verbatim", "matched", ["value_not_in_quote"], []),
    ],
    "negation-scope": [
        ("patient_identity", "verbatim", "matched", [], []),
        ("diagnoses", "verbatim", "mismatch", ["assertion_mismatch"], []),
        ("diagnoses", "verbatim", "matched", [], []),
    ],
    "family-history": [
        ("patient_identity", "verbatim", "matched", [], []),
        *[("diagnoses", "verbatim", "matched", [], [])] * 4,
    ],
    "repeated-quote": [
        ("patient_identity", "verbatim", "matched", [], []),
        ("diagnoses", "verbatim", "matched", [], ["ambiguous_match"]),
        ("diagnoses", "candidate", "mismatch", ["assertion_mismatch"], []),
    ],
    "table-line": [
        ("patient_identity", "verbatim", "matched", [], []),
        ("anthropometrics", "verbatim", "matched", [], ["table_source"]),
    ],
    "wrong-patient": [
        ("patient_identity", "verbatim", "matched", [], []),
        ("patient_identity", "verbatim", "matched", ["wrong_patient"], []),
        ("diagnoses", "verbatim", "matched", ["wrong_patient"], []),
    ],
    "pa-draft-only": [
        ("patient_identity", "verbatim", "matched", ["claim_document"], []),
        ("patient_identity", "verbatim", "matched", [], []),
        ("diagnoses", "verbatim", "matched", ["claim_document"], []),
        ("pa_form_claims", "verbatim", "matched", [], []),
    ],
    "crlf": [
        ("patient_identity", "verbatim", "matched", [], []),
        ("anthropometrics", "normalized", "matched", [], []),
        ("diagnoses", "normalized", "matched", [], []),
    ],
    "nfkc": [
        ("patient_identity", "verbatim", "matched", [], []),
        ("anthropometrics", "normalized", "matched", [], []),
        # "fit for surgery" carries no cue for `program_type: advice_only`: unrecognized.
        ("lifestyle", "normalized", "matched", [], ["unrecognized"]),
    ],
}

IDENTITY = {
    "wrong-patient": {"D1-referral": "match", "D2-clinical": "mismatch"},
    "pa-draft-only": {"D0-pa-form-draft": "match", "D2-clinical": "match"},
}


def _check(fixture: Path, db: Path, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    argv = ["check", str(fixture), "--db", str(db), "--json", "--explain", "--stop-after"]
    code = main([*argv, "verify"])
    report: dict[str, Any] = json.loads(capsys.readouterr().out)
    assert code == EXIT_OK, report["dead_letters"]
    return report


def test_every_fixture_has_an_expectation() -> None:
    assert sorted(p.name for p in VERIFY.iterdir() if p.is_dir()) == sorted(EXPECTED)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_fixture(
    name: str, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BRIDGE_FAKE_CLIENT", "1")
    report = _check(VERIFY / name, tmp_path / "f.db", capsys)
    got = [
        (
            e["field"],
            e["position_status"],
            e["assertion_check"],
            e["exclusion_reasons"],
            e["flags"],
        )
        for e in report["evidence"]
    ]
    assert got == EXPECTED[name]
    if name in IDENTITY:
        assert report["verification"]["doc_identity"] == IDENTITY[name]


def test_crlf_fixture_keeps_its_bytes() -> None:
    raw = (VERIFY / "crlf" / "docs" / "D2-clinical.txt").read_bytes()
    assert b"\r\n" in raw and raw.count(b"\n") == raw.count(b"\r\n")


def test_normalizations_are_recorded(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from bridge_check.store import open_store

    monkeypatch.setenv("BRIDGE_FAKE_CLIENT", "1")
    db = tmp_path / "n.db"
    found: dict[str, list[str]] = {}
    for name in ("crlf", "nfkc"):
        report = _check(VERIFY / name, db, capsys)
        store = open_store(db)
        try:
            rows = store.conn.execute(
                "SELECT attributes FROM evidence WHERE case_run_id = ? ORDER BY id",
                (report["run_id"],),
            ).fetchall()
        finally:
            store.close()
        found[name] = sorted({n for r in rows for n in json.loads(r[0]).get("normalizations", [])})
    assert found == {"crlf": ["whitespace"], "nfkc": ["nfkc"]}
