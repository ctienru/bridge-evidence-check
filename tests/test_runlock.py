"""Run lock and orphan recovery across real processes (contract §1, §11)."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from bridge_check.cli import EXIT_FAILED, EXIT_LOCKED, EXIT_OK
from bridge_check.runlock import RunLockHeld, exclusive_run_lock, lock_path

ROOT = Path(__file__).resolve().parent.parent
SMOKE = ROOT / "fixtures" / "synthetic" / "case-smoke"

# Holds the lock and leaves a `running` run with a `started` attempt, like a run whose
# request is in flight (the response has not reached disk).
HOLDER = """
import sys, time
from bridge_check.runlock import exclusive_run_lock
from bridge_check.store import open_store
db = sys.argv[1]
with exclusive_run_lock(db):
    store = open_store(db)
    run_id = store.insert_case_run(case_id="case-smoke", rules_version="bridge-v1",
                                   code_sha="holder", prompt_version="extract-v1",
                                   schema_version="v1")
    store.insert_attempt(case_run_id=run_id, cache_key="in-flight", attempt_no=1,
                         request_json="{}")
    print("ready", flush=True)
    time.sleep(120)
"""


def _env() -> dict[str, str]:
    return {**os.environ, "BRIDGE_FAKE_CLIENT": "1"}


def _bridge(*args: str) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", "bridge_check.cli", *args]
    return subprocess.run(cmd, capture_output=True, text=True, env=_env(), check=False, timeout=60)


@pytest.fixture
def holder(tmp_path: Path) -> Iterator[tuple[subprocess.Popen[str], Path]]:
    db = tmp_path / "runs.db"
    proc = subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(db)], stdout=subprocess.PIPE, text=True, env=_env()
    )
    assert proc.stdout is not None
    assert proc.stdout.readline().strip() == "ready"
    yield proc, db
    if proc.poll() is None:
        proc.kill()
        proc.wait()


def _attempts(db: Path) -> list[tuple[object, ...]]:
    conn = sqlite3.connect(db)
    try:
        return [
            tuple(r)
            for r in conn.execute(
                "SELECT id, case_run_id, status, cost_usd, error_type FROM attempts ORDER BY id"
            )
        ]
    finally:
        conn.close()


def _rows(db: Path) -> list[tuple[object, ...]]:
    conn = sqlite3.connect(db)
    try:
        return [
            tuple(r)
            for r in conn.execute(
                "SELECT id, status, failed_stage, code_sha FROM case_runs ORDER BY id"
            )
        ]
    finally:
        conn.close()


def test_lock_is_exclusive_within_a_process(tmp_path: Path) -> None:
    db = tmp_path / "x.db"
    with exclusive_run_lock(db), pytest.raises(RunLockHeld), exclusive_run_lock(db):
        pass
    with exclusive_run_lock(db):  # released after the block
        pass
    assert lock_path(db).name == "x.db.lock"


def test_second_process_exits_4_and_touches_nothing(
    holder: tuple[subprocess.Popen[str], Path],
) -> None:
    _, db = holder
    before = _rows(db)
    result = _bridge("check", str(SMOKE), "--db", str(db))
    assert result.returncode == EXIT_LOCKED, result.stderr
    assert "another run in progress" in result.stderr
    assert _rows(db) == before == [(1, "running", None, "holder")]
    assert _attempts(db) == [(1, 1, "started", None, None)]


def test_a_symlink_to_the_same_db_shares_the_lock(
    holder: tuple[subprocess.Popen[str], Path], tmp_path: Path
) -> None:
    _, db = holder
    link_dir = tmp_path / "elsewhere"
    link_dir.mkdir()
    link = link_dir / "alias.db"
    link.symlink_to(db)
    assert lock_path(link) == lock_path(db)
    before = _rows(db)
    result = _bridge("check", str(SMOKE), "--db", str(link))
    assert result.returncode == EXIT_LOCKED, result.stderr
    assert _rows(db) == before
    assert _attempts(db) == [(1, 1, "started", None, None)]


def test_a_hard_link_to_a_running_db_is_refused(
    holder: tuple[subprocess.Popen[str], Path], tmp_path: Path
) -> None:
    _, db = holder
    link_dir = tmp_path / "elsewhere"
    link_dir.mkdir()
    link = link_dir / "alias.db"
    os.link(db, link)
    before = _rows(db)
    result = _bridge("check", str(SMOKE), "--db", str(link))
    assert result.returncode == EXIT_FAILED, result.stderr
    assert "hard links" in result.stderr
    assert str(link_dir) not in result.stderr
    assert _rows(db) == before
    assert _attempts(db) == [(1, 1, "started", None, None)]


# Commits a `response_saved` attempt for the smoke case's real cache key, then waits to be
# killed: the committed rows stay in the original path's WAL (never checkpointed).
SAVED_THEN_KILLED = """
import sys, time
from pathlib import Path
from bridge_check.extract import build_request, cache_key, load_system_prompt
from bridge_check.input import load_case
from bridge_check.runlock import exclusive_run_lock
from bridge_check.store import open_store
db, case, reply = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
with exclusive_run_lock(db):
    store = open_store(db)
    key = cache_key(build_request(load_case(case), load_system_prompt()))
    run_id = store.insert_case_run(case_id="case-smoke", rules_version="bridge-v1",
                                   code_sha="killed", prompt_version="extract-v1",
                                   schema_version="v1")
    aid = store.insert_attempt(case_run_id=run_id, cache_key=key, attempt_no=1,
                               request_json="{}")
    store.save_response(aid, response_json=reply.read_text(encoding="utf-8"),
                        model_returned="claude-sonnet-5-5", latency_ms=1, input_tokens=1,
                        output_tokens=1, cost_usd=0.0)
    print("ready", flush=True)
    time.sleep(120)
"""


def test_saved_response_is_never_missed_through_a_hard_link(tmp_path: Path) -> None:
    db = tmp_path / "runs.db"
    reply = ROOT / "fixtures" / "synthetic" / "extract" / "response_valid.json"
    proc = subprocess.Popen(
        [sys.executable, "-c", SAVED_THEN_KILLED, str(db), str(SMOKE), str(reply)],
        stdout=subprocess.PIPE,
        text=True,
        env=_env(),
    )
    assert proc.stdout is not None
    assert proc.stdout.readline().strip() == "ready"
    proc.kill()
    proc.wait()
    assert (tmp_path / "runs.db-wal").exists()  # the saved response lives in the WAL
    link = tmp_path / "alias.db"
    os.link(db, link)
    # Through the hard link: refused before SQLite opens the file; no API call.
    via_link = _bridge("check", str(SMOKE), "--db", str(link), "--stop-after", "extract")
    assert via_link.returncode == EXIT_FAILED, via_link.stderr
    assert "hard links" in via_link.stderr
    link.unlink()
    # Through the one remaining name: the saved response is replayed, no new attempt.
    result = _bridge("check", str(SMOKE), "--db", str(db), "--stop-after", "extract", "--json")
    assert result.returncode == EXIT_OK, result.stderr
    report = __import__("json").loads(result.stdout)
    assert report["extraction"]["source"] == "replay"
    assert report["attempts"] == []
    assert [a[2] for a in _attempts(db)] == ["parsed"]


def test_after_kill_the_lock_is_free_and_the_next_run_recovers(
    holder: tuple[subprocess.Popen[str], Path],
) -> None:
    proc, db = holder
    proc.kill()
    proc.wait()
    result = _bridge("check", str(SMOKE), "--db", str(db), "--stop-after", "extract")
    assert result.returncode == EXIT_OK, result.stderr
    rows = _rows(db)
    assert rows[0] == (1, "failed", "interrupted", "holder")
    assert rows[1][1] == "completed"
    # The in-flight attempt may have been sent and billed: it is unknown_outcome, cost NULL.
    assert _attempts(db)[0] == (1, 1, "unknown_outcome", None, "Interrupted")
    history = _bridge("history", str(SMOKE), "--db", str(db), "--json")
    runs = __import__("json").loads(history.stdout)["runs"]
    assert runs[0]["unknown_outcomes"] == 1
