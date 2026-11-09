"""SQLite store: STRICT tables, generated enum CHECKs, foreign keys (contract §11)."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

from bridge_check.store import (
    ENUM_COLUMNS,
    DatabaseHasLinks,
    SqliteTooOld,
    Store,
    connect,
    open_store,
    recover_orphaned_runs,
    require_sqlite_version,
    schema_sql,
)

TABLES = (
    "documents",
    "case_runs",
    "attempts",
    "extractions",
    "evidence",
    "med_periods",
    "decisions",
    "doc_facts",
    "dead_letters",
)


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return open_store(tmp_path / "t.db")


def _run(store: Store) -> int:
    return store.insert_case_run(
        case_id="case-x",
        rules_version="bridge-v1",
        code_sha="abc",
        prompt_version="extract-v1",
        schema_version="v1",
    )


def _table_sql(conn: sqlite3.Connection, table: str) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    assert row is not None, table
    return str(row[0])


def test_every_table_exists_and_is_strict(store: Store) -> None:
    for table in TABLES:
        assert _table_sql(store.conn, table).rstrip().endswith("STRICT"), table
    idx = store.conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'idx_attempts_cache_key'"
    ).fetchone()
    assert idx is not None


def test_new_database_uses_wal(store: Store) -> None:
    assert store.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_connection_factory_turns_on_foreign_keys(tmp_path: Path) -> None:
    open_store(tmp_path / "t.db").close()
    conn = connect(tmp_path / "t.db")
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_db_rejects_unknown_enum_value(store: Store) -> None:
    run_id = _run(store)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        store.conn.execute("UPDATE case_runs SET status = 'success' WHERE id = ?", (run_id,))
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        store.insert_attempt(case_run_id=run_id, cache_key="k", attempt_no=1, request_json="{}")
        store.conn.execute("UPDATE attempts SET status = 'done'")
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        store.insert_dead_letter(case_run_id=run_id, stage="unknown", error_type="X", message="m")
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        store.conn.execute(
            "INSERT INTO decisions (case_run_id, condition, kind, status, rules_version) "
            "VALUES (?, 'bmi_path_a', 'path', 'eligible', 'bridge-v1')",
            (run_id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        store.conn.execute(
            "INSERT INTO decisions (case_run_id, condition, kind, status, rules_version) "
            "VALUES (?, 'overall', 'condition', 'supported', 'bridge-v1')",
            (run_id,),
        )


def test_claim_conditions_are_accepted(store: Store) -> None:
    run_id = _run(store)
    store.conn.execute(
        "INSERT INTO decisions (case_run_id, condition, kind, status, rules_version) "
        "VALUES (?, 'claim.drug', 'claim', 'supported', 'bridge-v1')",
        (run_id,),
    )


def test_db_rejects_wrong_type(store: Store) -> None:
    run_id = _run(store)
    with pytest.raises(sqlite3.IntegrityError, match="cannot store"):
        store.insert_attempt(
            case_run_id=run_id,
            cache_key="k",
            attempt_no="first",  # type: ignore[arg-type]
            request_json="{}",
        )
    with pytest.raises(sqlite3.IntegrityError, match="cannot store"):
        store.conn.execute("UPDATE case_runs SET extraction_id = 'one' WHERE id = ?", (run_id,))


def test_foreign_keys_enforced(store: Store) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        store.insert_attempt(case_run_id=999, cache_key="k", attempt_no=1, request_json="{}")
    run_id = _run(store)
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        store.conn.execute(
            "INSERT INTO extractions (cache_key, attempt_id, parsed_json, schema_version, "
            "prompt_version, created_at) VALUES ('k', 12345, '{}', 'v1', 'extract-v1', 'now')"
        )
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        store.insert_dead_letter(
            case_run_id=run_id, attempt_id=777, stage="parse", error_type="X", message="m"
        )


_CHECK_IN = re.compile(r"\b(\"?\w+\"?) IN \(([^)]*)\)")


def _check_lists(sql: str) -> dict[str, tuple[str, ...]]:
    found: dict[str, tuple[str, ...]] = {}
    for col, values in _CHECK_IN.findall(sql):
        col = col.strip('"')
        found[col] = tuple(v.strip().strip("'") for v in values.split(","))
    return found


def test_check_lists_match_enums(store: Store) -> None:
    seen: set[tuple[str, str]] = set()
    for table in TABLES:
        lists = _check_lists(_table_sql(store.conn, table))
        for col, values in lists.items():
            if (table, col) in ENUM_COLUMNS:
                assert values == ENUM_COLUMNS[(table, col)][0], (table, col)
                seen.add((table, col))
    assert seen == set(ENUM_COLUMNS), set(ENUM_COLUMNS) - seen


def test_sql_is_postgres_compatible() -> None:
    text = "\n".join(schema_sql()).upper()
    for banned in ("AUTOINCREMENT", "INSERT OR REPLACE", "ROWID", "WITHOUT ROWID"):
        assert banned not in text
    source = Path(__file__).resolve().parent.parent / "src" / "bridge_check" / "store.py"
    code = source.read_text(encoding="utf-8").upper()
    # SQL string literals only (the module docstring names the banned forms).
    assert not re.search(r"[\"']\s*INSERT OR ", code)
    assert not re.search(r"[\"'][^\"'\n]*\bAUTOINCREMENT\b", code)


def test_sql_lives_only_in_store() -> None:
    src = Path(__file__).resolve().parent.parent / "src" / "bridge_check"
    pattern = re.compile(r"\b(SELECT|INSERT INTO|UPDATE \w+ SET|CREATE TABLE)\b")
    offenders = [
        p.name
        for p in src.rglob("*.py")
        if p.name != "store.py" and pattern.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_sqlite_version_check_message() -> None:
    require_sqlite_version("3.45.3")
    with pytest.raises(SqliteTooOld, match=r">= 3\.37"):
        require_sqlite_version("3.31.1")


def test_unknown_outcome_cost_is_null(store: Store) -> None:
    run_id = _run(store)
    aid = store.insert_attempt(case_run_id=run_id, cache_key="k", attempt_no=1, request_json="{}")
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        store.conn.execute(
            "UPDATE attempts SET status = 'unknown_outcome', cost_usd = 0.0 WHERE id = ?", (aid,)
        )
    store.set_attempt_status(aid, "unknown_outcome", error_type="APITimeoutError")
    assert store.attempt(aid)["cost_usd"] is None


def test_extractions_on_conflict_do_nothing_reads_back(store: Store) -> None:
    run_id = _run(store)
    a1 = store.insert_attempt(case_run_id=run_id, cache_key="k", attempt_no=1, request_json="{}")
    a2 = store.insert_attempt(case_run_id=run_id, cache_key="k", attempt_no=2, request_json="{}")
    for aid in (a1, a2):
        store.save_response(
            aid,
            response_json="{}",
            model_returned="m",
            latency_ms=1,
            input_tokens=1,
            output_tokens=1,
            cost_usd=0.1,
        )
    e1 = store.mark_parsed(
        a1, cache_key="k", parsed_json='{"a":1}', schema_version="v1", prompt_version="p"
    )
    e2 = store.mark_parsed(
        a2, cache_key="k", parsed_json='{"a":2}', schema_version="v1", prompt_version="p"
    )
    assert e1 == e2
    found = store.find_extraction("k")
    assert found is not None and found["attempt_id"] == a1
    assert store.count("extractions") == 1


def test_failed_run_needs_a_stage(store: Store) -> None:
    run_id = _run(store)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        store.finish_case_run(run_id, status="failed")
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        store.finish_case_run(run_id, status="completed", failed_stage="verify")


def test_recover_orphaned_runs(store: Store) -> None:
    r1 = _run(store)
    r2 = _run(store)
    store.finish_case_run(r2, status="completed")
    assert recover_orphaned_runs(store.conn) == 1
    assert store.case_run(r1)["status"] == "failed"
    assert store.case_run(r1)["failed_stage"] == "interrupted"
    assert store.case_run(r2)["status"] == "completed"


def test_recovery_marks_started_attempts_unknown_outcome(store: Store) -> None:
    run_id = _run(store)
    started = store.insert_attempt(
        case_run_id=run_id, cache_key="k", attempt_no=1, request_json="{}"
    )
    saved = store.insert_attempt(case_run_id=run_id, cache_key="k", attempt_no=2, request_json="{}")
    store.save_response(
        saved,
        response_json="{}",
        model_returned="m",
        latency_ms=1,
        input_tokens=1,
        output_tokens=1,
        cost_usd=0.1,
    )
    assert recover_orphaned_runs(store.conn) == 1
    assert store.attempt(started)["status"] == "unknown_outcome"
    assert store.attempt(started)["cost_usd"] is None
    assert store.attempt(saved)["status"] == "response_saved"  # replayable, untouched
    letters = store.dead_letters_for_run(run_id)
    assert [(d["attempt_id"], d["stage"], d["error_type"]) for d in letters] == [
        (started, "interrupted", "Interrupted")
    ]


def test_db_with_more_than_one_link_is_refused(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    open_store(db).close()
    other = tmp_path / "sub"
    other.mkdir()
    link = other / "alias.db"
    import os

    os.link(db, link)
    for path in (db, link):
        with pytest.raises(DatabaseHasLinks) as info:
            connect(path)
        assert "2 hard links" in str(info.value)
        assert str(tmp_path) not in str(info.value)
    link.unlink()
    connect(db).close()
