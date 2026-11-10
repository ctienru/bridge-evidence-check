"""Failure recovery: the three fixed scenarios and the rerun after a cache hit (contract §1,
§11; `docs/recovery.md`).

Each scenario runs `bridge check` in-process on `fixtures/synthetic/case-smoke` with the fake
client and a fresh database, stops the first run at a named boundary (`BRIDGE_FAKE_FAULT`, or
a monkeypatched failure), reruns it, and asserts the exact table counts before and after.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from bridge_check import cli
from bridge_check.cli import EXIT_FAILED, EXIT_OK, main
from bridge_check.extract import Limits
from bridge_check.fake_client import (
    FAULT_ENV,
    FakeClient,
    InjectedFault,
    fault_hook,
    fault_point,
)
from bridge_check.store import Store, open_store

ROOT = Path(__file__).resolve().parent.parent
SMOKE = ROOT / "fixtures" / "synthetic" / "case-smoke"
TABLES = (
    "case_runs",
    "attempts",
    "extractions",
    "evidence",
    "med_periods",
    "doc_facts",
    "decisions",
    "dead_letters",
)
EMPTY = dict.fromkeys(TABLES, 0)
EVIDENCE, MED_PERIODS, DOC_FACTS, DECISIONS = 16, 2, 3, 23
"""Rows one completed run of the smoke case writes with the valid reply."""
COST = 0.0244
"""Recorded cost of the valid reply: 5200 input and 1400 output tokens at list prices."""


class Clients:
    """Wraps `cli.make_client` and keeps every fake client it builds, so a test can assert
    that a run made no API call (`calls == []`)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.made: list[FakeClient] = []
        real: Callable[..., Any] = cli.make_client

        def make(case_dir: Path | None = None) -> Any:
            client = real(case_dir)
            assert isinstance(client, FakeClient)
            self.made.append(client)
            return client

        monkeypatch.setattr(cli, "make_client", make)

    def calls_of_last(self) -> int:
        return len(self.made[-1].calls) if self.made else 0


@pytest.fixture
def clients(monkeypatch: pytest.MonkeyPatch) -> Clients:
    monkeypatch.setenv("BRIDGE_FAKE_CLIENT", "1")
    monkeypatch.delenv(FAULT_ENV, raising=False)
    return Clients(monkeypatch)


def _check(db: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, Any], str]:
    code = main(["check", str(SMOKE), "--db", str(db), "--json"])
    out = capsys.readouterr()
    return code, (json.loads(out.out) if out.out else {}), out.err


def _counts(db: Path) -> dict[str, int]:
    store = open_store(db)
    try:
        return {t: store.count(t) for t in TABLES}
    finally:
        store.close()


def _attempts(db: Path) -> list[tuple[int, int, str, float | None]]:
    store = open_store(db)
    try:
        rows = store.conn.execute(
            "SELECT id, case_run_id, status, cost_usd FROM attempts ORDER BY id"
        ).fetchall()
        # cost rounded to 6 places (the precision `extract` records); NULL stays None
        return [(r[0], r[1], r[2], None if r[3] is None else round(r[3], 6)) for r in rows]
    finally:
        store.close()


def _history(db: Path, capsys: pytest.CaptureFixture[str]) -> list[tuple[Any, ...]]:
    assert main(["history", str(SMOKE), "--db", str(db), "--json"]) == EXIT_OK
    runs = json.loads(capsys.readouterr().out)["runs"]
    return [
        (
            r["id"],
            r["status"],
            r["failed_stage"],
            r["extraction_source"],
            r["source_attempt_id"],
            r["attempts"],
            r["unknown_outcomes"],
        )
        for r in runs
    ]


def _decisions(report: dict[str, Any]) -> list[tuple[Any, ...]]:
    return sorted(
        (d["condition"], d["status"], tuple(d["flags"]), d["rule_id"]) for d in report["decisions"]
    )


@pytest.fixture
def clean(
    tmp_path: Path, clients: Clients, capsys: pytest.CaptureFixture[str]
) -> list[tuple[Any, ...]]:
    """The decisions of one uninterrupted run in its own database: the correctness oracle."""
    code, report, _ = _check(tmp_path / "clean.db", capsys)
    assert code == EXIT_OK
    assert len(report["decisions"]) == DECISIONS
    clients.made.clear()
    return _decisions(report)


def _after_one_clean_run(**changes: int) -> dict[str, int]:
    return {
        **EMPTY,
        "evidence": EVIDENCE,
        "med_periods": MED_PERIODS,
        "doc_facts": DOC_FACTS,
        "decisions": DECISIONS,
        **changes,
    }


# --- (a) full raw response saved, parse interrupted --------------------------------------------


def test_a_saved_response_is_replayed_without_a_new_attempt(
    tmp_path: Path,
    clients: Clients,
    clean: list[tuple[Any, ...]],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = tmp_path / "r.db"
    monkeypatch.setenv(FAULT_ENV, "after_response_saved")
    code, report, err = _check(db, capsys)
    assert code == EXIT_FAILED and report == {}
    assert "injected fault at after_response_saved" in err
    assert _counts(db) == {**EMPTY, "case_runs": 1, "attempts": 1}
    assert _attempts(db) == [(1, 1, "response_saved", COST)]

    monkeypatch.delenv(FAULT_ENV)
    code, report, _ = _check(db, capsys)
    assert code == EXIT_OK and report["status"] == "completed"
    assert report["extraction"]["source"] == "replay"
    assert report["extraction"]["source_attempt_id"] == 1
    assert report["attempts"] == []
    assert clients.calls_of_last() == 0  # no API call
    assert _counts(db) == _after_one_clean_run(case_runs=2, attempts=1, extractions=1)
    assert [a[2] for a in _attempts(db)] == ["parsed"]
    assert _decisions(report) == clean
    assert _history(db, capsys) == [
        (1, "failed", "interrupted", None, None, 1, 0),
        (2, "completed", None, "replay", 1, 0, 0),
    ]


# --- (b) no full response: at-least-once -------------------------------------------------------


def test_b_kill_before_response_saved_calls_again(
    tmp_path: Path,
    clients: Clients,
    clean: list[tuple[Any, ...]],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = tmp_path / "r.db"
    monkeypatch.setenv(FAULT_ENV, "before_response_saved")
    code, _, err = _check(db, capsys)
    assert code == EXIT_FAILED
    assert "injected fault at before_response_saved" in err
    assert clients.calls_of_last() == 1  # the request left
    assert _counts(db) == {**EMPTY, "case_runs": 1, "attempts": 1}
    assert _attempts(db) == [(1, 1, "started", None)]

    monkeypatch.delenv(FAULT_ENV)
    code, report, _ = _check(db, capsys)
    assert code == EXIT_OK and report["status"] == "completed"
    assert report["extraction"]["source"] == "api"
    assert clients.calls_of_last() == 1  # called again: may be paid twice
    # recovery: the orphaned attempt is unknown_outcome, cost NULL, with one dead letter
    assert _attempts(db) == [
        (1, 1, "unknown_outcome", None),
        (2, 2, "parsed", COST),
    ]
    assert _counts(db) == _after_one_clean_run(
        case_runs=2, attempts=2, extractions=1, dead_letters=1
    )
    assert _decisions(report) == clean
    assert _history(db, capsys) == [
        (1, "failed", "interrupted", None, None, 1, 1),
        (2, "completed", None, "api", 2, 1, 0),
    ]


def test_b_timeout_calls_again(
    tmp_path: Path,
    clients: Clients,
    clean: list[tuple[Any, ...]],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = tmp_path / "r.db"
    monkeypatch.setenv("BRIDGE_FAKE_CLIENT", "timeout")
    monkeypatch.setattr(cli, "LIMITS", Limits(max_attempts=1))
    code, report, _ = _check(db, capsys)
    assert code == EXIT_FAILED
    assert (report["status"], report["failed_stage"]) == ("failed", "extract")
    assert report["attempt_summary"]["by_status"] == {"unknown_outcome": 1}
    assert report["attempt_summary"]["cost_usd"] is None  # unknown, not zero
    assert _counts(db) == {**EMPTY, "case_runs": 1, "attempts": 1, "dead_letters": 1}
    assert _attempts(db) == [(1, 1, "unknown_outcome", None)]

    monkeypatch.setenv("BRIDGE_FAKE_CLIENT", "1")
    code, report, _ = _check(db, capsys)
    assert code == EXIT_OK and report["extraction"]["source"] == "api"
    assert clients.calls_of_last() == 1
    assert _counts(db) == _after_one_clean_run(
        case_runs=2, attempts=2, extractions=1, dead_letters=1
    )
    assert _decisions(report) == clean
    assert _history(db, capsys) == [
        (1, "failed", "extract", None, None, 1, 1),
        (2, "completed", None, "api", 2, 1, 0),
    ]


# --- (c) extraction stored, rules failed -------------------------------------------------------


@pytest.mark.parametrize("failure", ["rolled_back", "raised"])
def test_c_rules_failure_reruns_on_the_cache(
    failure: str,
    tmp_path: Path,
    clients: Clients,
    clean: list[tuple[Any, ...]],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = tmp_path / "r.db"
    if failure == "rolled_back":
        # killed inside the decisions transaction: the decisions are rolled back
        monkeypatch.setenv(FAULT_ENV, "in_rules")
    else:

        def boom(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("synthetic rules failure")

        monkeypatch.setattr(cli, "evaluate_rules", boom)
    code, _, err = _check(db, capsys)
    assert code == EXIT_FAILED
    letters = 0 if failure == "rolled_back" else 1
    assert _counts(db) == _after_one_clean_run(
        case_runs=1, attempts=1, extractions=1, decisions=0, dead_letters=letters
    )
    if failure == "rolled_back":
        assert "injected fault at in_rules" in err
        assert _history(db, capsys) == [(1, "running", None, "api", 1, 1, 0)]

    monkeypatch.delenv(FAULT_ENV, raising=False)
    monkeypatch.undo()  # restores evaluate_rules and make_client; re-wrap the client
    monkeypatch.setenv("BRIDGE_FAKE_CLIENT", "1")
    clients = Clients(monkeypatch)
    code, report, _ = _check(db, capsys)
    assert code == EXIT_OK and report["status"] == "completed"
    assert report["extraction"]["source"] == "cache"
    assert report["attempts"] == []
    assert clients.calls_of_last() == 0  # no API call
    # verify, compute and rules ran again under the new run: their rows doubled
    assert _counts(db) == {
        **EMPTY,
        "case_runs": 2,
        "attempts": 1,
        "extractions": 1,
        "evidence": 2 * EVIDENCE,
        "med_periods": 2 * MED_PERIODS,
        "doc_facts": 2 * DOC_FACTS,
        "decisions": DECISIONS,
        "dead_letters": letters,
    }
    assert _attempts(db) == [(1, 1, "parsed", COST)]
    assert _decisions(report) == clean
    stage = "interrupted" if failure == "rolled_back" else "rules"
    assert _history(db, capsys) == [
        (1, "failed", stage, "api", 1, 1, 0),  # the failed run is still queryable
        (2, "completed", None, "cache", 1, 0, 0),
    ]


# --- leftover running run, rules upsert, history ------------------------------------------------


def test_leftover_running_run_is_failed_interrupted_and_a_new_one_opened(
    tmp_path: Path, clients: Clients, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "r.db"
    store = open_store(db)
    try:
        store.insert_case_run(
            case_id="case-smoke",
            rules_version="bridge-v1",
            code_sha="killed",
            prompt_version="extract-v4",
            schema_version="v1",
        )
    finally:
        store.close()
    assert _counts(db) == {**EMPTY, "case_runs": 1}
    code, report, _ = _check(db, capsys)
    assert code == EXIT_OK and report["run_id"] == 2
    assert _history(db, capsys) == [
        (1, "failed", "interrupted", None, None, 0, 0),
        (2, "completed", None, "api", 1, 1, 0),
    ]


def test_rules_redo_in_one_run_upserts(
    tmp_path: Path, clients: Clients, capsys: pytest.CaptureFixture[str]
) -> None:
    from bridge_check.rules import Decision

    db = tmp_path / "r.db"
    code, report, _ = _check(db, capsys)
    assert code == EXIT_OK
    run_id = report["run_id"]
    store = open_store(db)
    try:
        rows = store.decisions_for_run(run_id)
        first = rows[0]
        changed = "review" if first["status"] != "review" else "insufficient"
        redo = [
            Decision.model_validate(
                {
                    **{k: r[k] for k in ("condition", "kind", "status", "reason", "rule_id")},
                    "rules_version": r["rules_version"],
                    "used_evidence": r["used_evidence"],
                    "excluded_evidence": r["excluded_evidence"],
                    "computed": r["computed"],
                    "flags": r["flags"],
                }
            )
            for r in rows
        ]
        redo[0] = redo[0].model_copy(update={"status": changed})
        store.save_decisions_and_complete(run_id, redo, case_flags=())  # no UNIQUE failure
        assert store.count("decisions") == DECISIONS
        assert store.decisions_for_run(run_id)[0]["status"] == changed
        assert store.case_run(run_id)["status"] == "completed"
    finally:
        store.close()


def test_history_table_shows_source_and_unknown_outcome(
    tmp_path: Path,
    clients: Clients,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = tmp_path / "r.db"
    for fault in ("before_response_saved", None, None):  # kill, fresh call, cache hit
        if fault:
            monkeypatch.setenv(FAULT_ENV, fault)
        else:
            monkeypatch.delenv(FAULT_ENV, raising=False)
        _check(db, capsys)
    assert main(["history", str(SMOKE), "--db", str(db)]) == EXIT_OK
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "runs for case-smoke"
    assert re.split(r"\s{2,}", lines[1]) == [
        "run",
        "status",
        "failed_stage",
        "extraction",
        "source",
        "src_attempt",
        "attempts",
        "unknown_outcome",
        "started_at",
    ]
    # columns are separated by at least two spaces; "fresh call" and "cache hit" are one cell
    cells = [re.split(r"\s{2,}", line)[:8] for line in lines[2:]]
    assert cells == [
        ["1", "failed", "interrupted", "-", "-", "-", "1", "1"],
        ["2", "completed", "-", "1", "fresh call", "2", "1", "0"],
        ["3", "completed", "-", "1", "cache hit", "2", "0", "0"],
    ]


# --- the hook itself -----------------------------------------------------------------------------


def test_fault_hook_is_inert_without_the_fake_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BRIDGE_FAKE_CLIENT", raising=False)
    monkeypatch.setenv(FAULT_ENV, "in_rules")
    assert fault_point() is None
    assert fault_hook() is None
    assert Store.fault_hook is None
    monkeypatch.setenv("BRIDGE_FAKE_CLIENT", "1")
    hook = fault_hook()
    assert hook is not None
    hook("after_response_saved")  # another boundary: no effect
    with pytest.raises(InjectedFault):
        hook("in_rules")
    monkeypatch.setenv(FAULT_ENV, "in_rule")
    with pytest.raises(ValueError, match="unknown boundary"):
        fault_point()
