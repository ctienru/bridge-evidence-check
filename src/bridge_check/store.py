"""SQLite storage. Every SQL statement in the project lives in this module (contract §11).

- Every table is `STRICT`; every enum column has a `CHECK (col IN (...))` generated from
  `bridge_check.enums` through `ENUM_COLUMNS` (one source, never a hand-written list).
- `connect()` is the only connection factory: it turns on `PRAGMA foreign_keys=ON` for
  every connection. WAL is set once, when the database is created.
- SQL is Postgres-compatible: standard type names, `INSERT … ON CONFLICT`, no
  `INSERT OR REPLACE`, `AUTOINCREMENT` or `rowid`.
- Connections run in autocommit mode; multi-statement writes use `transaction()`, so no
  write transaction is ever left open while the caller waits on the API.
- Schema version: `SCHEMA_VERSION` is written to `PRAGMA user_version` when a database is
  created and compared on every open. A database from another version raises
  `SchemaVersionMismatch` before any row is written or any API call is made. There are no
  migrations: delete the file or point `BRIDGE_DB` at a new one. Version 1 was the first
  store; version 2 added `--stop-after verify` and the evidence columns written by verify.

The table design follows planning 06 §4; where it and `docs/contracts.md` differ, the
contract wins.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

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

if TYPE_CHECKING:
    from bridge_check.compute import ComputedFacts
    from bridge_check.rules import Decision
    from bridge_check.verify import VerifyResult

MIN_SQLITE = (3, 37, 0)
"""`STRICT` tables need SQLite 3.37 (06 §4)."""

SCHEMA_VERSION = 2
"""Store schema version, kept in `PRAGMA user_version`. Bump on any change to `schema_sql()`
or to an enum CHECK list; see the module docstring."""

SCORING_ATTRIBUTE_KEYS: tuple[str, ...] = (
    "sbp",
    "dbp",
    "start",
    "end",
    "end_kind",
    "list_id",
    "complete",
    "program_type",
    "attendance",
    "osa_severity",
    "ahi",
    "fibrosis_stage",
    "cirrhosis",
    "ckd_stage",
    "symptomatic",
    "payer",
    "purpose",
    "claim_id",
    "claimed_value",
    "target_doc_id",
    "date",
    "dob",
    "stated_age",
    "compounded",
    "patient_id",
    "drug",
    "name",
)
"""Evidence attributes `facts_for_run` returns: the contract §8 match keys plus the names the
comparison canonicalizes in memory. Free text (`dose`, `indication`, `section_title`,
`limitation`, `description`) is never returned."""


class SchemaVersionMismatch(RuntimeError):
    """The database was created by another store schema version (no migrations)."""

    def __init__(self, found: int, expected: int) -> None:
        super().__init__(
            f"the database was created by an older schema (user_version {found}, expected "
            f"{expected}). Delete it or point BRIDGE_DB at a new file."
        )
        self.found = found
        self.expected = expected

    def for_file(self) -> str:
        """The message with the leading "the database", for use after a file name."""
        return str(self).removeprefix("the database ")


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


SIDECAR_SUFFIXES: tuple[str, ...] = ("-wal", "-shm", "-journal")
"""Files SQLite creates or truncates next to the database, by name."""


def _sidecar_bases(db_path: Path | str) -> list[Path]:
    """The path as given and the file it resolves to (deduplicated). SQLite derives the
    journal and WAL names from the resolved database path, so a database reached through
    a link has its sidecars next to the target, not next to the link."""
    given = Path(db_path)
    try:
        resolved = given.resolve()
    except OSError:
        resolved = given
    return [given] if resolved == given else [given, resolved]


def sidecar_paths(db_path: Path | str) -> list[Path]:
    """Every sidecar SQLite may create or truncate for `db_path`, by name."""
    return [
        base.with_name(base.name + suffix)
        for base in _sidecar_bases(db_path)
        for suffix in SIDECAR_SUFFIXES
    ]


def require_single_link(db_path: Path | str) -> None:
    """Refuse a DB file with more than one hard link, and any sidecar (`-wal`, `-shm`,
    `-journal`, next to the given path and next to the resolved one) that is a symbolic
    link or has more than one hard link: SQLite writes and truncates those by name, so a
    linked sidecar would reach another file's bytes. A missing file is fine."""
    try:
        links = os.stat(db_path).st_nlink
    except FileNotFoundError:
        links = 1
    if links > 1:
        raise DatabaseHasLinks(
            f"the database file has {links} hard links; SQLite finds its WAL by path, so a "
            "database must have exactly one name. Remove the extra links and use one path."
        )
    for base in _sidecar_bases(db_path):
        for suffix in SIDECAR_SUFFIXES:
            sidecar = base.with_name(base.name + suffix)
            if sidecar.is_symlink():
                raise DatabaseHasLinks(
                    f"a database sidecar ({suffix}) is a symbolic link; SQLite would write "
                    "through it. Remove it and use one path."
                )
            try:
                side_links = os.stat(sidecar).st_nlink
            except FileNotFoundError:
                continue
            if side_links > 1:
                raise DatabaseHasLinks(
                    f"a database sidecar ({suffix}) has {side_links} hard links; SQLite "
                    "would truncate a shared file. Remove the extra links and use one path."
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


def user_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def create_schema(conn: sqlite3.Connection, *, new_database: bool) -> None:
    """Create every table that does not exist yet. A new database is switched to WAL once and
    stamped with `SCHEMA_VERSION`; an existing one must carry exactly that version."""
    if new_database:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION:d}")
    else:
        found = user_version(conn)
        if found != SCHEMA_VERSION:
            raise SchemaVersionMismatch(found, SCHEMA_VERSION)
    with transaction(conn):
        for stmt in schema_sql():
            conn.execute(stmt)


def open_store(db_path: Path | str) -> Store:
    path = Path(db_path)
    require_single_link(path)  # the file and its sidecars, before any SQLite connection
    new_database = not path.exists() or path.stat().st_size == 0
    if not new_database:
        # Read the version through a read-only connection first: a legacy file with WAL pages
        # is refused without SQLite checkpointing it on close.
        # `as_uri()` percent-encodes `#`, `?` and spaces, so the file name cannot change the
        # URI's meaning (a literal `#` would open a different file).
        ro = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            found = user_version(ro)
        finally:
            ro.close()
        if found != SCHEMA_VERSION:
            raise SchemaVersionMismatch(found, SCHEMA_VERSION)
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

    fault_hook: Callable[[str], None] | None = None
    """Fault injection for the failure-recovery tests (`fake_client.fault_hook`): called with
    `after_response_saved` and `in_rules` at those boundaries. Only `bridge check` under the
    fake client sets it; it is None everywhere else."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def _fault(self, point: str) -> None:
        hook = self.fault_hook
        if hook is not None:
            hook(point)

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
        self._fault("after_response_saved")  # committed: the raw response is on disk

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

    def cost_for_run(self, run_id: int, *, unknown_outcome_as: float = 0.0) -> float:
        """USD recorded on this run's attempts so far; an `unknown_outcome` attempt (cost
        NULL, possibly billed) counts as `unknown_outcome_as`; other NULL costs count 0."""
        row = self.conn.execute(
            "SELECT COALESCE(SUM(CASE WHEN status = 'unknown_outcome' THEN ? "
            "ELSE COALESCE(cost_usd, 0.0) END), 0.0) FROM attempts WHERE case_run_id = ?",
            (unknown_outcome_as, run_id),
        ).fetchone()
        return float(row[0])

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

    # scoring and export reads (compare against gold, public replays)

    def latest_completed_run(self, case_id: str) -> int | None:
        """The newest run of `case_id` that completed every stage, else None."""
        row = self.conn.execute(
            "SELECT id FROM case_runs WHERE case_id = ? AND status = 'completed' "
            "AND stopped_after IS NULL ORDER BY id DESC LIMIT 1",
            (case_id,),
        ).fetchone()
        return int(row[0]) if row is not None else None

    def extraction_for_run(self, run_id: int) -> dict[str, Any] | None:
        """The extraction a run used, with its source attempt; None when it has none."""
        row = self.conn.execute(
            "SELECT e.id, e.cache_key, e.attempt_id, e.parsed_json, e.prompt_version, "
            "e.schema_version FROM case_runs r JOIN extractions e ON e.id = r.extraction_id "
            "WHERE r.id = ?",
            (run_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def facts_for_run(self, run_id: int) -> list[dict[str, Any]]:
        """Scoring view of every evidence row (contract §8): columns plus the allow-listed
        attributes of `SCORING_ATTRIBUTE_KEYS`. No quote. `attrs` may hold identifiers and
        drug names, which callers use in memory and never write out."""
        rows = self.conn.execute(
            'SELECT id, field, kind, concept, doc_id, start, "end", norm_value, norm_unit, '
            "event_date, date_precision, certainty_llm, subject_llm, temporality_llm, "
            "assertion_check, relative_llm, relative_computed, event_date_source, "
            "position_status, exclusion_reasons, flags, attributes FROM evidence "
            "WHERE case_run_id = ? "
            "ORDER BY id",
            (run_id,),
        ).fetchall()
        out = []
        for r in rows:
            attributes = json.loads(r["attributes"])
            out.append(
                {
                    "evidence_id": r["id"],
                    "field": r["field"],
                    "kind": r["kind"],
                    "concept": r["concept"],
                    "doc_id": r["doc_id"],
                    "offset_start": r["start"],
                    "offset_end": r["end"],
                    "ref": attributes["ref"],
                    "fact_path": attributes["fact_path"],
                    "norm_value": r["norm_value"],
                    "norm_unit": r["norm_unit"],
                    "event_date": r["event_date"],
                    "date_precision": r["date_precision"],
                    "certainty": r["certainty_llm"],
                    "subject": r["subject_llm"],
                    "temporality": r["temporality_llm"],
                    "assertion_check": r["assertion_check"],
                    "relative_llm": r["relative_llm"],
                    "relative_computed": r["relative_computed"],
                    "event_date_source": r["event_date_source"],
                    "position_status": r["position_status"],
                    "exclusion_reasons": json.loads(r["exclusion_reasons"]),
                    "flags": json.loads(r["flags"]),
                    "attrs": {k: attributes[k] for k in SCORING_ATTRIBUTE_KEYS if k in attributes},
                }
            )
        return out

    # evidence and doc_facts

    def save_verification(self, run_id: int, result: VerifyResult) -> list[int]:
        """Every `evidence` and `doc_facts` row of the run in one transaction (06 §3.6).

        Returns the evidence ids in the order of `result.evidence`. Any error rolls the
        whole write back: a run never has part of its evidence.
        """
        ids: list[int] = []
        with transaction(self.conn):
            for ev in result.evidence:
                attributes = {**ev.attributes, "fact_path": ev.fact_path, "ref": ev.ref}
                cur = self.conn.execute(
                    "INSERT INTO evidence (case_run_id, field, kind, concept, doc_id, "
                    'doc_sha256, start, "end", quote, attributes, raw_value, raw_unit, '
                    "event_date, date_precision, certainty_llm, subject_llm, temporality_llm, "
                    "certainty_checked, subject_checked, temporality_checked, relative_llm, "
                    "event_date_source, position_status, assertion_check, exclusion_reasons, "
                    "flags) VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                    "?, ?) "
                    "RETURNING id",
                    (
                        run_id,
                        ev.field,
                        ev.kind,
                        ev.concept,
                        ev.doc_id,
                        ev.doc_sha256,
                        ev.start,
                        ev.end,
                        ev.quote,
                        json.dumps(attributes, sort_keys=True, ensure_ascii=False),
                        ev.raw_value,
                        ev.raw_unit,
                        ev.event_date,
                        ev.date_precision,
                        ev.certainty_llm,
                        ev.subject_llm,
                        ev.temporality_llm,
                        ev.certainty_checked,
                        ev.subject_checked,
                        ev.temporality_checked,
                        ev.relative_llm,
                        ev.event_date_source,
                        ev.position_status,
                        ev.assertion_check,
                        json.dumps(list(ev.exclusion_reasons)),
                        json.dumps(list(ev.flags)),
                    ),
                )
                ids.append(int(cur.fetchone()[0]))
            for df in result.doc_facts:
                evidence_id = (
                    ids[df.identity_evidence_index]
                    if df.identity_evidence_index is not None
                    else None
                )
                self.conn.execute(
                    "INSERT INTO doc_facts (case_run_id, doc_id, identity_status, "
                    "identity_evidence_id) VALUES (?, ?, ?, ?)",
                    (run_id, df.doc_id, df.identity_status, evidence_id),
                )
        return ids

    def evidence_for_run(self, run_id: int) -> list[dict[str, Any]]:
        """Statuses of every evidence row of the run; no quote, no attributes text."""
        rows = self.conn.execute(
            "SELECT id, field, doc_id, position_status, assertion_check, exclusion_reasons, "
            "flags, attributes FROM evidence WHERE case_run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
        out = []
        for r in rows:
            out.append(
                {
                    "evidence_id": r["id"],
                    "field": r["field"],
                    "doc_id": r["doc_id"],
                    "ref": json.loads(r["attributes"])["ref"],
                    "position_status": r["position_status"],
                    "assertion_check": r["assertion_check"],
                    "exclusion_reasons": json.loads(r["exclusion_reasons"]),
                    "flags": json.loads(r["flags"]),
                }
            )
        return out

    def doc_facts_for_run(self, run_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT doc_id, doc_date, identity_status, identity_evidence_id FROM doc_facts "
            "WHERE case_run_id = ? ORDER BY doc_id",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # compute and rules

    def save_computed(self, run_id: int, facts: ComputedFacts) -> None:
        """What compute adds to the run, in one transaction (contract §1): the computed columns
        of every `evidence` row, the `med_periods` rows and each document's date."""
        with transaction(self.conn):
            for u in facts.evidence_updates:
                self.conn.execute(
                    "UPDATE evidence SET relative_computed = ?, "
                    "event_date_source = COALESCE(?, event_date_source), "
                    "event_date = COALESCE(event_date, ?), "
                    "date_precision = COALESCE(date_precision, ?), "
                    "norm_value = ?, norm_unit = ?, flags = ?, exclusion_reasons = ? "
                    "WHERE id = ? AND case_run_id = ?",
                    (
                        u.relative_computed,
                        u.event_date_source,
                        u.event_date,
                        u.date_precision,
                        u.norm_value,
                        u.norm_unit,
                        json.dumps(list(u.flags)),
                        json.dumps(list(u.exclusion_reasons)),
                        u.evidence_id,
                        run_id,
                    ),
                )
            for p in facts.med_periods:
                self.conn.execute(
                    "INSERT INTO med_periods (case_run_id, drug_canonical, class, start, "
                    'start_precision, "end", end_precision, end_kind, evidence_id) '
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        p.drug_canonical,
                        p.class_,
                        p.start.iso() if p.start else None,
                        p.start.precision if p.start else None,
                        p.end.iso() if p.end else None,
                        p.end.precision if p.end else None,
                        p.end_kind,
                        p.src.evidence_id,
                    ),
                )
            for doc_id, df in facts.doc_facts.items():
                if df.doc_date is not None:
                    self.conn.execute(
                        "UPDATE doc_facts SET doc_date = ?, doc_date_evidence_id = ? "
                        "WHERE case_run_id = ? AND doc_id = ?",
                        (df.doc_date.iso(), df.doc_date_evidence_id, run_id, doc_id),
                    )

    def save_decisions_and_complete(
        self, run_id: int, decisions: Sequence[Decision], *, case_flags: Sequence[str]
    ) -> None:
        """Every decision of the run and `status = completed` in one transaction (contract
        §1): there is no state "decisions written, status not updated"."""
        with transaction(self.conn):
            for d in decisions:
                self.conn.execute(
                    "INSERT INTO decisions (case_run_id, condition, kind, status, reason, "
                    "rule_id, rules_version, used_evidence, excluded_evidence, computed, flags) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT (case_run_id, condition) DO UPDATE SET kind = excluded.kind, "
                    "status = excluded.status, reason = excluded.reason, "
                    "rule_id = excluded.rule_id, rules_version = excluded.rules_version, "
                    "used_evidence = excluded.used_evidence, "
                    "excluded_evidence = excluded.excluded_evidence, "
                    "computed = excluded.computed, flags = excluded.flags",
                    (
                        run_id,
                        d.condition,
                        d.kind,
                        d.status,
                        d.reason,
                        d.rule_id,
                        d.rules_version,
                        json.dumps(list(d.used_evidence)),
                        json.dumps([e.model_dump() for e in d.excluded_evidence]),
                        json.dumps(d.computed, sort_keys=True, ensure_ascii=False, default=str),
                        json.dumps(list(d.flags)),
                    ),
                )
            self._fault("in_rules")  # inside the transaction: the decisions roll back
            self.conn.execute(
                "UPDATE case_runs SET status = 'completed', case_flags = ?, finished_at = ? "
                "WHERE id = ?",
                (json.dumps(list(case_flags)), utc_now(), run_id),
            )

    def decisions_for_run(self, run_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT condition, kind, status, reason, rule_id, rules_version, used_evidence, "
            "excluded_evidence, computed, flags FROM decisions WHERE case_run_id = ? "
            "ORDER BY condition",
            (run_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for key in ("used_evidence", "excluded_evidence", "computed", "flags"):
                d[key] = json.loads(d[key])
            out.append(d)
        return out

    def med_periods_for_run(self, run_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            'SELECT drug_canonical, class, start, start_precision, "end", end_precision, '
            "end_kind, evidence_id FROM med_periods WHERE case_run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def evidence_timing_for_run(self, run_id: int) -> list[dict[str, Any]]:
        """Timing columns of every evidence row (tests and `--explain`); no quote."""
        rows = self.conn.execute(
            "SELECT id, field, relative_llm, relative_computed, event_date, date_precision, "
            "event_date_source, norm_value, norm_unit, flags, exclusion_reasons FROM evidence "
            "WHERE case_run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["flags"] = json.loads(d["flags"])
            d["exclusion_reasons"] = json.loads(d["exclusion_reasons"])
            out.append(d)
        return out

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
