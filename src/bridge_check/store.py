"""SQLite storage. Every SQL statement in the project lives in this module (contract §11).

- Every table is `STRICT`; every enum column has a `CHECK (col IN (...))` generated from
  `bridge_check.enums` through `ENUM_COLUMNS` (one source, never a hand-written list).
- `connect()` is the only connection factory: it turns on `PRAGMA foreign_keys=ON` for
  every connection. WAL is set once, when the database is created.
- SQL is Postgres-compatible: standard type names, `INSERT … ON CONFLICT`, no
  `INSERT OR REPLACE`, `AUTOINCREMENT` or `rowid`.
- Connections run in autocommit mode; multi-statement writes use `transaction()`, so no
  write transaction is ever left open while the caller waits on the API.

The table design follows planning 06 §4; where it and `docs/contracts.md` differ, the
contract wins (see the W08 PR for the list).
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bridge_check.enums import (
    ASSERTION_CHECKS,
    ATTEMPT_STATUSES,
    CERTAINTY,
    CONCEPTS,
    CONDITION_IDS,
    DATE_PRECISIONS,
    DECISION_KINDS,
    DOC_ROLES,
    END_KINDS,
    EXTRACTION_FIELDS,
    EXTRACTION_SOURCES,
    FAILED_STAGES,
    IDENTITY_MATCH,
    KINDS,
    NORM_UNITS,
    POSITION_STATUSES,
    RELATIVE_TO_INITIATION,
    RUN_STATUSES,
    STATUS_CODES,
    STOP_AFTER_STAGES,
    SUBJECT,
    TEMPORALITY,
)

MIN_SQLITE = (3, 37, 0)
"""`STRICT` tables need SQLite 3.37 (06 §4)."""


class SqliteTooOld(RuntimeError):
    pass


class DatabaseHasLinks(RuntimeError):
    """The DB file has more than one hard link.

    SQLite finds the WAL and shared-memory files by the path it opened, so two names of
    one file can see different WALs: a committed `response_saved` attempt can be missed
    (and the API called again) or the database corrupted
    (https://sqlite.org/howtocorrupt.html#multiple_links_to_the_same_file). Such a file is
    never opened. The message carries the link count only, never the path.
    """


def require_single_link(db_path: Path | str) -> None:
    """Refuse a DB file with more than one hard link (a missing file is fine)."""
    try:
        links = os.stat(db_path).st_nlink
    except FileNotFoundError:
        return
    if links > 1:
        raise DatabaseHasLinks(
            f"the database file has {links} hard links; SQLite finds its WAL by path, so a "
            "database must have exactly one name. Remove the extra links and use one path."
        )


def require_sqlite_version(version: str = sqlite3.sqlite_version) -> None:
    parts = tuple(int(p) for p in version.split(".")[:3])
    if parts < MIN_SQLITE:
        need = ".".join(str(p) for p in MIN_SQLITE)
        raise SqliteTooOld(
            f"SQLite {version} is too old: STRICT tables need SQLite >= {need}. "
            "Use a Python build linked against a newer SQLite."
        )


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


# --- Enum columns: the single map from column to enum ------------------------------------

# (table, column) -> (allowed values, nullable)
ENUM_COLUMNS: dict[tuple[str, str], tuple[tuple[str, ...], bool]] = {
    ("documents", "role"): (DOC_ROLES, False),
    ("case_runs", "status"): (RUN_STATUSES, False),
    ("case_runs", "failed_stage"): (FAILED_STAGES, True),
    ("case_runs", "extraction_source"): (EXTRACTION_SOURCES, True),
    ("case_runs", "stopped_after"): (STOP_AFTER_STAGES, True),
    ("attempts", "status"): (ATTEMPT_STATUSES, False),
    ("evidence", "field"): (EXTRACTION_FIELDS, False),
    ("evidence", "kind"): (KINDS, True),
    ("evidence", "concept"): (CONCEPTS, True),
    ("evidence", "norm_unit"): (NORM_UNITS, True),
    ("evidence", "date_precision"): (DATE_PRECISIONS, True),
    ("evidence", "certainty_llm"): (CERTAINTY, False),
    ("evidence", "subject_llm"): (SUBJECT, False),
    ("evidence", "temporality_llm"): (TEMPORALITY, False),
    ("evidence", "certainty_checked"): (CERTAINTY, True),
    ("evidence", "subject_checked"): (SUBJECT, True),
    ("evidence", "temporality_checked"): (TEMPORALITY, True),
    ("evidence", "relative_llm"): (RELATIVE_TO_INITIATION, False),
    ("evidence", "relative_computed"): (RELATIVE_TO_INITIATION, True),
    ("evidence", "position_status"): (POSITION_STATUSES, True),
    ("evidence", "assertion_check"): (ASSERTION_CHECKS, True),
    ("med_periods", "start_precision"): (DATE_PRECISIONS, True),
    ("med_periods", "end_precision"): (DATE_PRECISIONS, True),
    ("med_periods", "end_kind"): (END_KINDS, False),
    ("decisions", "kind"): (DECISION_KINDS, False),
    ("decisions", "status"): (STATUS_CODES, False),
    ("doc_facts", "identity_status"): (IDENTITY_MATCH, True),
    ("dead_letters", "stage"): (FAILED_STAGES, False),
}


def _quote_list(values: Sequence[str]) -> str:
    for v in values:
        if "'" in v:
            raise ValueError("enum values may not contain a quote character")
    return ", ".join(f"'{v}'" for v in values)


def enum_column(table: str, column: str) -> str:
    """Column definition `<name> TEXT [NOT NULL] CHECK (...)` from `ENUM_COLUMNS`."""
    values, nullable = ENUM_COLUMNS[(table, column)]
    name = f'"{column}"' if column in ("end",) else column
    check = f"{name} IN ({_quote_list(values)})"
    if nullable:
        return f"{name} TEXT CHECK ({name} IS NULL OR {check})"
    return f"{name} TEXT NOT NULL CHECK ({check})"


def _e(table: str, column: str) -> str:
    return enum_column(table, column)


def schema_sql() -> list[str]:
    """`CREATE` statements in dependency order (no foreign-key cycles)."""
    condition_check = (
        f"CHECK (condition IN ({_quote_list(CONDITION_IDS)}) OR condition LIKE 'claim.%')"
    )
    return [
        f"""CREATE TABLE IF NOT EXISTS documents (
  case_id TEXT NOT NULL,
  doc_id TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  {_e("documents", "role")},
  PRIMARY KEY (case_id, doc_id, sha256)
) STRICT""",
        f"""CREATE TABLE IF NOT EXISTS case_runs (
  id INTEGER PRIMARY KEY,
  case_id TEXT NOT NULL,
  input_hash TEXT,
  extraction_id INTEGER,
  {_e("case_runs", "extraction_source")},
  rules_version TEXT NOT NULL,
  code_sha TEXT NOT NULL,
  {_e("case_runs", "status")},
  {_e("case_runs", "failed_stage")},
  {_e("case_runs", "stopped_after")},
  error TEXT,
  case_flags TEXT NOT NULL DEFAULT '[]',
  prompt_version TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  splitter_version TEXT,
  assessment_date TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  CHECK ((status = 'failed') = (failed_stage IS NOT NULL)),
  CHECK (stopped_after IS NULL OR status = 'completed')
) STRICT""",
        f"""CREATE TABLE IF NOT EXISTS attempts (
  id INTEGER PRIMARY KEY,
  case_run_id INTEGER NOT NULL REFERENCES case_runs(id),
  cache_key TEXT NOT NULL,
  attempt_no INTEGER NOT NULL,
  request_json TEXT NOT NULL,
  response_json TEXT,
  model_returned TEXT,
  {_e("attempts", "status")},
  error_type TEXT,
  error TEXT,
  latency_ms INTEGER,
  input_tokens INTEGER,
  output_tokens INTEGER,
  cost_usd REAL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK (status <> 'unknown_outcome' OR cost_usd IS NULL),
  CHECK (response_json IS NOT NULL OR status = 'started' OR status = 'api_error'
         OR status = 'unknown_outcome')
) STRICT""",
        "CREATE INDEX IF NOT EXISTS idx_attempts_cache_key ON attempts(cache_key)",
        """CREATE TABLE IF NOT EXISTS extractions (
  id INTEGER PRIMARY KEY,
  cache_key TEXT NOT NULL UNIQUE,
  attempt_id INTEGER NOT NULL REFERENCES attempts(id),
  parsed_json TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  created_at TEXT NOT NULL
) STRICT""",
        f"""CREATE TABLE IF NOT EXISTS evidence (
  id INTEGER PRIMARY KEY,
  case_run_id INTEGER NOT NULL REFERENCES case_runs(id),
  {_e("evidence", "field")},
  {_e("evidence", "kind")},
  {_e("evidence", "concept")},
  doc_id TEXT NOT NULL,
  doc_sha256 TEXT NOT NULL,
  start INTEGER,
  "end" INTEGER,
  quote TEXT NOT NULL,
  attributes TEXT NOT NULL DEFAULT '{{}}',
  raw_value TEXT,
  raw_unit TEXT,
  norm_value TEXT,
  {_e("evidence", "norm_unit")},
  event_date TEXT,
  {_e("evidence", "date_precision")},
  {_e("evidence", "certainty_llm")},
  {_e("evidence", "subject_llm")},
  {_e("evidence", "temporality_llm")},
  {_e("evidence", "certainty_checked")},
  {_e("evidence", "subject_checked")},
  {_e("evidence", "temporality_checked")},
  {_e("evidence", "relative_llm")},
  {_e("evidence", "relative_computed")},
  event_date_source TEXT,
  {_e("evidence", "position_status")},
  {_e("evidence", "assertion_check")},
  exclusion_reasons TEXT NOT NULL DEFAULT '[]',
  flags TEXT NOT NULL DEFAULT '[]'
) STRICT""",
        f"""CREATE TABLE IF NOT EXISTS med_periods (
  id INTEGER PRIMARY KEY,
  case_run_id INTEGER NOT NULL REFERENCES case_runs(id),
  drug_canonical TEXT NOT NULL,
  class TEXT,
  start TEXT,
  {_e("med_periods", "start_precision")},
  "end" TEXT,
  {_e("med_periods", "end_precision")},
  {_e("med_periods", "end_kind")},
  evidence_id INTEGER NOT NULL REFERENCES evidence(id)
) STRICT""",
        f"""CREATE TABLE IF NOT EXISTS decisions (
  case_run_id INTEGER NOT NULL REFERENCES case_runs(id),
  condition TEXT NOT NULL {condition_check},
  {_e("decisions", "kind")},
  {_e("decisions", "status")},
  reason TEXT,
  rule_id TEXT,
  rules_version TEXT NOT NULL,
  used_evidence TEXT NOT NULL DEFAULT '[]',
  excluded_evidence TEXT NOT NULL DEFAULT '[]',
  computed TEXT NOT NULL DEFAULT '{{}}',
  flags TEXT NOT NULL DEFAULT '[]',
  PRIMARY KEY (case_run_id, condition)
) STRICT""",
        f"""CREATE TABLE IF NOT EXISTS doc_facts (
  case_run_id INTEGER NOT NULL REFERENCES case_runs(id),
  doc_id TEXT NOT NULL,
  doc_date TEXT,
  doc_date_evidence_id INTEGER REFERENCES evidence(id),
  {_e("doc_facts", "identity_status")},
  identity_evidence_id INTEGER REFERENCES evidence(id),
  PRIMARY KEY (case_run_id, doc_id)
) STRICT""",
        f"""CREATE TABLE IF NOT EXISTS dead_letters (
  id INTEGER PRIMARY KEY,
  case_run_id INTEGER REFERENCES case_runs(id),
  attempt_id INTEGER REFERENCES attempts(id),
  {_e("dead_letters", "stage")},
  error_type TEXT NOT NULL,
  fact_path TEXT,
  evidence_id INTEGER REFERENCES evidence(id),
  message TEXT NOT NULL,
  created_at TEXT NOT NULL,
  CHECK (case_run_id IS NOT NULL OR attempt_id IS NOT NULL)
) STRICT""",
    ]


# --- Connections ----------------------------------------------------------------------------


def connect(db_path: Path | str) -> sqlite3.Connection:
    """The only connection factory: autocommit, `foreign_keys=ON`, rows as mappings.

    Refuses a DB file with more than one hard link before SQLite opens it."""
    require_sqlite_version()
    require_single_link(db_path)
    conn = sqlite3.connect(str(db_path), isolation_level=None, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def create_schema(conn: sqlite3.Connection, *, new_database: bool) -> None:
    """Create every table that does not exist yet. A new database is switched to WAL once."""
    if new_database:
        conn.execute("PRAGMA journal_mode=WAL")
    with transaction(conn):
        for stmt in schema_sql():
            conn.execute(stmt)


def open_store(db_path: Path | str) -> Store:
    path = Path(db_path)
    new_database = not path.exists() or path.stat().st_size == 0
    conn = connect(path)
    create_schema(conn, new_database=new_database)
    return Store(conn)


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    conn.execute("BEGIN")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def recover_orphaned_runs(conn: sqlite3.Connection) -> int:
    """Clean up after a crash; returns the number of runs recovered (contract §1, §11).

    - leftover `running` runs become `failed` + `interrupted`;
    - leftover `started` attempts become `unknown_outcome` (cost NULL): the request may
      have been sent and billed, but its response never reached disk. Each one also gets
      a dead letter so `history` and the report count it.

    `response_saved` attempts are left alone: their raw response is on disk and the next
    check replays it. Call only while holding the run lock: with the lock held, nothing
    else can be in flight, so every `running` run and `started` attempt is a crash.
    """
    now = utc_now()
    with transaction(conn):
        cur = conn.execute(
            "UPDATE case_runs SET status = 'failed', failed_stage = 'interrupted', "
            "finished_at = ? WHERE status = 'running'",
            (now,),
        )
        runs = cur.rowcount
        orphans = conn.execute(
            "UPDATE attempts SET status = 'unknown_outcome', error_type = 'Interrupted', "
            "error = 'interrupted before the response reached disk', cost_usd = NULL, "
            "updated_at = ? WHERE status = 'started' RETURNING id, case_run_id",
            (now,),
        ).fetchall()
        for attempt_id, case_run_id in orphans:
            conn.execute(
                "INSERT INTO dead_letters (case_run_id, attempt_id, stage, error_type, "
                "message, created_at) VALUES (?, ?, 'interrupted', 'Interrupted', "
                "'attempt interrupted before the response reached disk', ?)",
                (case_run_id, attempt_id, now),
            )
    return runs


# --- Store -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class SavedAttempt:
    id: int
    case_run_id: int
    response_json: str


class Store:
    """Typed access to the tables used by the pipeline."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def close(self) -> None:
        self.conn.close()

    # case_runs

    def insert_case_run(
        self,
        *,
        case_id: str,
        rules_version: str,
        code_sha: str,
        prompt_version: str,
        schema_version: str,
        splitter_version: str | None = None,
    ) -> int:
        with transaction(self.conn):
            cur = self.conn.execute(
                "INSERT INTO case_runs (case_id, rules_version, code_sha, status, "
                "prompt_version, schema_version, splitter_version, started_at) "
                "VALUES (?, ?, ?, 'running', ?, ?, ?, ?) RETURNING id",
                (
                    case_id,
                    rules_version,
                    code_sha,
                    prompt_version,
                    schema_version,
                    splitter_version,
                    utc_now(),
                ),
            )
            run_id: int = cur.fetchone()[0]
        return run_id

    def set_case_run_input(self, run_id: int, *, input_hash: str, assessment_date: str) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE case_runs SET input_hash = ?, assessment_date = ? WHERE id = ?",
                (input_hash, assessment_date, run_id),
            )

    def set_case_run_extraction(self, run_id: int, extraction_id: int, source: str) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE case_runs SET extraction_id = ?, extraction_source = ? WHERE id = ?",
                (extraction_id, source, run_id),
            )

    def finish_case_run(
        self,
        run_id: int,
        *,
        status: str,
        failed_stage: str | None = None,
        stopped_after: str | None = None,
        error: str | None = None,
    ) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE case_runs SET status = ?, failed_stage = ?, stopped_after = ?, "
                "error = ?, finished_at = ? WHERE id = ?",
                (status, failed_stage, stopped_after, error, utc_now(), run_id),
            )

    def case_run(self, run_id: int) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM case_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return dict(row)

    def history(self, case_id: str) -> list[dict[str, Any]]:
        """Every run of `case_id` with its extraction, source attempt and attempt counts."""
        rows = self.conn.execute(
            "SELECT r.id, r.status, r.failed_stage, r.stopped_after, r.extraction_id, "
            "r.extraction_source, e.attempt_id AS source_attempt_id, r.started_at, "
            "r.finished_at, r.code_sha, r.prompt_version, r.schema_version, "
            "(SELECT count(*) FROM attempts a WHERE a.case_run_id = r.id) AS attempts, "
            "(SELECT count(*) FROM attempts a WHERE a.case_run_id = r.id "
            " AND a.status = 'unknown_outcome') AS unknown_outcomes "
            "FROM case_runs r LEFT JOIN extractions e ON e.id = r.extraction_id "
            "WHERE r.case_id = ? ORDER BY r.id",
            (case_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # documents

    def upsert_documents(self, case_id: str, docs: Mapping[str, tuple[str, str]]) -> None:
        """`docs`: doc_id -> (sha256, role)."""
        with transaction(self.conn):
            for doc_id, (sha, role) in sorted(docs.items()):
                self.conn.execute(
                    "INSERT INTO documents (case_id, doc_id, sha256, role) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT (case_id, doc_id, sha256) DO NOTHING",
                    (case_id, doc_id, sha, role),
                )

    # attempts

    def insert_attempt(
        self, *, case_run_id: int, cache_key: str, attempt_no: int, request_json: str
    ) -> int:
        """Write the `started` row before the request is sent; committed on return."""
        now = utc_now()
        with transaction(self.conn):
            cur = self.conn.execute(
                "INSERT INTO attempts (case_run_id, cache_key, attempt_no, request_json, "
                "status, created_at, updated_at) VALUES (?, ?, ?, ?, 'started', ?, ?) "
                "RETURNING id",
                (case_run_id, cache_key, attempt_no, request_json, now, now),
            )
            attempt_id: int = cur.fetchone()[0]
        return attempt_id

    def save_response(
        self,
        attempt_id: int,
        *,
        response_json: str,
        model_returned: str | None,
        latency_ms: int,
        input_tokens: int | None,
        output_tokens: int | None,
        cost_usd: float | None,
    ) -> None:
        """The complete raw response is on disk: `response_saved`, committed on return."""
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE attempts SET response_json = ?, model_returned = ?, status = "
                "'response_saved', latency_ms = ?, input_tokens = ?, output_tokens = ?, "
                "cost_usd = ?, updated_at = ? WHERE id = ? AND status = 'started'",
                (
                    response_json,
                    model_returned,
                    latency_ms,
                    input_tokens,
                    output_tokens,
                    cost_usd,
                    utc_now(),
                    attempt_id,
                ),
            )

    def set_attempt_status(
        self,
        attempt_id: int,
        status: str,
        *,
        error_type: str | None = None,
        error: str | None = None,
        latency_ms: int | None = None,
    ) -> None:
        """A terminal state other than `parsed`. `unknown_outcome` keeps `cost_usd` NULL."""
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE attempts SET status = ?, error_type = ?, error = ?, "
                "latency_ms = COALESCE(?, latency_ms), "
                "cost_usd = CASE WHEN ? = 'unknown_outcome' THEN NULL ELSE cost_usd END, "
                "updated_at = ? WHERE id = ?",
                (status, error_type, error, latency_ms, status, utc_now(), attempt_id),
            )

    def mark_parsed(
        self,
        attempt_id: int,
        *,
        cache_key: str,
        parsed_json: str,
        schema_version: str,
        prompt_version: str,
    ) -> int:
        """`parsed` and the `extractions` row in one transaction; returns the extraction id.

        `ON CONFLICT (cache_key) DO NOTHING` and a read-back: when another run already
        stored this key, its row is the one returned (contract §11).
        """
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE attempts SET status = 'parsed', updated_at = ? WHERE id = ?",
                (utc_now(), attempt_id),
            )
            self.conn.execute(
                "INSERT INTO extractions (cache_key, attempt_id, parsed_json, schema_version, "
                "prompt_version, created_at) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (cache_key) DO NOTHING",
                (cache_key, attempt_id, parsed_json, schema_version, prompt_version, utc_now()),
            )
            row = self.conn.execute(
                "SELECT id FROM extractions WHERE cache_key = ?", (cache_key,)
            ).fetchone()
        extraction_id: int = row[0]
        return extraction_id

    def find_extraction(self, cache_key: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT id, attempt_id, parsed_json FROM extractions WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
        return dict(row) if row is not None else None

    def latest_response_saved(self, cache_key: str) -> SavedAttempt | None:
        row = self.conn.execute(
            "SELECT id, case_run_id, response_json FROM attempts "
            "WHERE cache_key = ? AND status = 'response_saved' ORDER BY id DESC LIMIT 1",
            (cache_key,),
        ).fetchone()
        if row is None:
            return None
        return SavedAttempt(int(row[0]), int(row[1]), str(row[2]))

    def attempts_for_run(self, run_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, attempt_no, status, latency_ms, error_type, input_tokens, "
            "output_tokens, cost_usd FROM attempts WHERE case_run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def attempt(self, attempt_id: int) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
        if row is None:
            raise KeyError(attempt_id)
        return dict(row)

    # dead letters

    def insert_dead_letter(
        self,
        *,
        stage: str,
        error_type: str,
        message: str,
        case_run_id: int | None = None,
        attempt_id: int | None = None,
        fact_path: str | None = None,
        evidence_id: int | None = None,
    ) -> int:
        """`message` must already be sanitized: no document text, no quotes."""
        with transaction(self.conn):
            cur = self.conn.execute(
                "INSERT INTO dead_letters (case_run_id, attempt_id, stage, error_type, "
                "fact_path, evidence_id, message, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                (
                    case_run_id,
                    attempt_id,
                    stage,
                    error_type,
                    fact_path,
                    evidence_id,
                    message,
                    utc_now(),
                ),
            )
            dl_id: int = cur.fetchone()[0]
        return dl_id

    def dead_letters_for_run(self, run_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT d.id, d.attempt_id, d.stage, d.error_type, d.fact_path, d.evidence_id, "
            "d.message FROM dead_letters d LEFT JOIN attempts a ON a.id = d.attempt_id "
            "WHERE d.case_run_id = ? OR a.case_run_id = ? ORDER BY d.id",
            (run_id, run_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def count(self, table: str) -> int:
        if table not in _TABLES:
            raise ValueError("unknown table")
        return int(self.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


_TABLES = frozenset(
    {
        "documents",
        "case_runs",
        "attempts",
        "extractions",
        "evidence",
        "med_periods",
        "decisions",
        "doc_facts",
        "dead_letters",
    }
)
