"""Command-line entry point: `bridge`.

`check <case>` runs input → extract → store. verify, compute and rules are W09 / W10 and
are not implemented yet, so a full `check` ends `failed` with `failed_stage=verify` and a
`NotImplemented` dead letter: it never reports a run as completed when later stages did
not run. The hidden `--stop-after extract` (tests only) ends the run `completed` at the
extraction boundary and records `stopped_after=extract` on the run.

Exit codes (contract §1): 0 = completed, 3 = failed, 4 = another run holds the lock.
Output never contains document text, quotes or patient names.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from bridge_check import __version__
from bridge_check.extract import PROMPT_VERSION, ExtractionFailed, extract
from bridge_check.input import InputError, LoadedCase, case_id_of, load_case, resolve_case_dir
from bridge_check.logs import configure_logging, log_event
from bridge_check.manifest import CHECKOUT_ROOT
from bridge_check.runlock import RunLockHeld, exclusive_run_lock, resolve_db_path
from bridge_check.schema import SCHEMA_VERSION
from bridge_check.store import (
    DatabaseHasLinks,
    SqliteTooOld,
    Store,
    open_store,
    recover_orphaned_runs,
    require_sqlite_version,
)

EXIT_OK = 0
EXIT_FAILED = 3
EXIT_LOCKED = 4

DB_ENV = "BRIDGE_DB"
DEFAULT_DB = "bridge.db"
RULES_PATH = CHECKOUT_ROOT / "rules" / "bridge-v1.yaml"
NOT_IMPLEMENTED = (
    "verify, compute and rules are not implemented yet (W09/W10); "
    "the run stops after extraction and is recorded as failed at verify"
)

_STUB_COMMANDS = {
    "eval": "Evaluate a split against frozen gold.",
    "excerpts": "Run the excerpt tests.",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bridge",
        description="Medicare GLP-1 Bridge pre-attestation chart evidence checker.",
    )
    parser.add_argument("--version", action="version", version=f"bridge {__version__}")
    sub = parser.add_subparsers(dest="command")

    check = sub.add_parser("check", help="Check one case and print evidence statuses.")
    check.add_argument("case", help="case directory, or a variant id under cases/")
    check.add_argument("--explain", action="store_true", help="explain each status")
    check.add_argument("--json", action="store_true", help="print the run as JSON")
    check.add_argument("--db", help=f"SQLite database (default: ${DB_ENV} or ./{DEFAULT_DB})")
    check.add_argument("--stop-after", choices=["extract"], help=argparse.SUPPRESS)

    history = sub.add_parser("history", help="Show past runs for one case.")
    history.add_argument("case", help="case directory, or a variant id")
    history.add_argument("--json", action="store_true", help="print the runs as JSON")
    history.add_argument("--db", help=f"SQLite database (default: ${DB_ENV} or ./{DEFAULT_DB})")

    for name, help_text in _STUB_COMMANDS.items():
        sub.add_parser(name, help=help_text)
    return parser


def _db_path(arg: str | None) -> Path:
    """The resolved DB path: the lock and the connection use the same file."""
    return resolve_db_path(arg or os.environ.get(DB_ENV) or DEFAULT_DB)


def rules_version(path: Path = RULES_PATH) -> str:
    data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    return str(data["version"])


def code_sha(root: Path = CHECKOUT_ROOT) -> str:
    """HEAD of the checkout, with `-dirty` when the working tree has changes."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{sha}-dirty" if dirty else sha


def make_client() -> Any:
    """The fake client when `BRIDGE_FAKE_CLIENT` is set, else the real SDK client with SDK
    retries disabled (AGENTS.md)."""
    from bridge_check.fake_client import ENV_VAR, FakeClient, scenario

    name = os.environ.get(ENV_VAR, "").strip()
    if name:
        return FakeClient([scenario(name)])
    import anthropic

    return anthropic.Anthropic(max_retries=0)


# --- check -------------------------------------------------------------------------------------


def run_report(store: Store, run_id: int, extraction: dict[str, Any] | None) -> dict[str, Any]:
    """The structure printed by `--json` (and later used by the report)."""
    run = store.case_run(run_id)
    if run["status"] == "failed" and run["failed_stage"] == "verify":
        message = NOT_IMPLEMENTED
    elif run["stopped_after"] == "extract":
        message = (
            "completed at the extraction boundary (--stop-after extract); "
            "verify, compute and rules did not run"
        )
    elif run["status"] == "failed":
        message = f"failed at {run['failed_stage']}"
    else:
        message = run["status"]
    attempts = [
        {
            "attempt_id": a["id"],
            "attempt_no": a["attempt_no"],
            "status": a["status"],
            "latency_ms": a["latency_ms"],
            "error_type": a["error_type"],
            "input_tokens": a["input_tokens"],
            "output_tokens": a["output_tokens"],
            "cost_usd": a["cost_usd"],
        }
        for a in store.attempts_for_run(run_id)
    ]
    dead_letters = [
        {
            "stage": d["stage"],
            "error_type": d["error_type"],
            "attempt_id": d["attempt_id"],
            "fact_path": d["fact_path"],
            "evidence_id": d["evidence_id"],
            "message": d["message"],
        }
        for d in store.dead_letters_for_run(run_id)
    ]
    return {
        "run_id": run_id,
        "case_id": run["case_id"],
        "status": run["status"],
        "failed_stage": run["failed_stage"],
        "stopped_after": run["stopped_after"],
        "message": message,
        "extraction": extraction,
        "attempts": attempts,
        "attempt_summary": {
            "count": len(attempts),
            "by_status": _count_by(attempts, "status"),
            "cost_usd": _sum_cost(attempts),
        },
        "dead_letters": dead_letters,
        "versions": {
            "prompt": run["prompt_version"],
            "schema": run["schema_version"],
            "rules": run["rules_version"],
            "splitter": run["splitter_version"],
            "code_sha": run["code_sha"],
        },
        "input_hash": run["input_hash"],
        "started_at": run["started_at"],
        "finished_at": run["finished_at"],
    }


def _count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        out[str(r[key])] = out.get(str(r[key]), 0) + 1
    return out


def _sum_cost(rows: list[dict[str, Any]]) -> float | None:
    costs = [r["cost_usd"] for r in rows if r["cost_usd"] is not None]
    return round(sum(costs), 6) if costs else None


def _fail(
    store: Store, run_id: int, case_id: str, stage: str, error_type: str, message: str
) -> None:
    store.insert_dead_letter(
        case_run_id=run_id, stage=stage, error_type=error_type, message=message
    )
    store.finish_case_run(
        run_id, status="failed", failed_stage=stage, error=f"{error_type}: {message}"
    )
    log_event("run_failed", run_id=run_id, case_id=case_id, stage=stage, error_type=error_type)


def check_case(
    store: Store, case_arg: str, stop_after: str | None
) -> tuple[int, dict[str, Any] | None]:
    """One run under the lock. Returns (run_id, extraction summary)."""
    cid = case_id_of(case_arg)
    run_id = store.insert_case_run(
        case_id=cid,
        rules_version=rules_version(),
        code_sha=code_sha(),
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
    )
    log_event("run_started", run_id=run_id, case_id=cid, stage="input")

    case: LoadedCase
    try:
        case = load_case(resolve_case_dir(case_arg))
    except InputError as exc:
        _fail(store, run_id, cid, "input", "InputError", str(exc))
        return run_id, None
    store.set_case_run_input(
        run_id, input_hash=case.input_hash, assessment_date=case.input.assessment_date.isoformat()
    )
    store.upsert_documents(
        case.case_id,
        {r.doc_id: (case.doc_sha256[r.doc_id], r.role) for r in case.input.documents},
    )

    try:
        client = make_client()
        result = extract(case, client, store, run_id=run_id)
    except ExtractionFailed as exc:
        store.finish_case_run(
            run_id,
            status="failed",
            failed_stage=exc.stage,
            error=f"{exc.error_type}: {exc.message}",
        )
        log_event(
            "run_failed",
            run_id=run_id,
            case_id=case.case_id,
            stage=exc.stage,
            error_type=exc.error_type,
        )
        return run_id, None
    except Exception as exc:  # noqa: BLE001 - any other error fails the run, recorded
        _fail(
            store, run_id, cid, "extract", type(exc).__name__, "unexpected error during extraction"
        )
        return run_id, None

    store.set_case_run_extraction(run_id, result.extraction_id, result.source)
    summary = {
        "id": result.extraction_id,
        "source": result.source,
        "source_attempt_id": result.source_attempt_id,
        "cache_key_sha8": result.cache_key[:8],
        "fact_counts": {k: len(v) for k, v in result.extraction.model_dump().items()},
    }
    log_event("extraction_ready", run_id=run_id, case_id=case.case_id, stage="extract")

    if stop_after == "extract":
        store.finish_case_run(run_id, status="completed", stopped_after="extract")
        log_event("run_completed", run_id=run_id, case_id=case.case_id, stage="extract")
        return run_id, summary

    _fail(store, run_id, cid, "verify", "NotImplemented", NOT_IMPLEMENTED)
    return run_id, summary


def _print_check(report: dict[str, Any], explain: bool) -> None:
    ext = report["extraction"]
    print(f"run {report['run_id']} ({report['case_id']}): {report['status']}", end="")
    print(f" at {report['failed_stage']}" if report["failed_stage"] else "")
    print(f"  {report['message']}")
    if ext is not None:
        print(
            f"  extraction {ext['id']} from {ext['source']} "
            f"(source attempt {ext['source_attempt_id']}, key {ext['cache_key_sha8']})"
        )
    summary = report["attempt_summary"]
    by_status = ", ".join(f"{k}={v}" for k, v in summary["by_status"].items()) or "none"
    print(f"  attempts this run: {summary['count']} ({by_status})")
    for d in report["dead_letters"]:
        print(f"  dead letter: {d['stage']} {d['error_type']}: {d['message']}")
    if explain:
        print("  --explain: no condition statuses to explain; decisions are produced from W10 on")


def cmd_check(args: argparse.Namespace) -> int:
    db = _db_path(args.db)
    try:
        require_sqlite_version()
        with exclusive_run_lock(db, blocking=False):
            store = open_store(db)
            try:
                recovered = recover_orphaned_runs(store.conn)
                if recovered:
                    log_event("recovered_orphaned_runs", stage="interrupted")
                run_id, extraction = check_case(store, args.case, args.stop_after)
                report = run_report(store, run_id, extraction)
            finally:
                store.close()
    except RunLockHeld:
        print(
            "bridge check: another run in progress (lock held); nothing was changed",
            file=sys.stderr,
        )
        return EXIT_LOCKED
    except (SqliteTooOld, DatabaseHasLinks) as exc:
        print(f"bridge check: {exc}", file=sys.stderr)
        return EXIT_FAILED
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _print_check(report, args.explain)
    return EXIT_OK if report["status"] == "completed" else EXIT_FAILED


# --- history -----------------------------------------------------------------------------------


def cmd_history(args: argparse.Namespace) -> int:
    db = _db_path(args.db)
    if not db.exists():
        print("bridge history: no database at the given path", file=sys.stderr)
        return EXIT_FAILED
    case_id = case_id_of(args.case)
    try:
        store = open_store(db)
    except (SqliteTooOld, DatabaseHasLinks) as exc:
        print(f"bridge history: {exc}", file=sys.stderr)
        return EXIT_FAILED
    try:
        rows = store.history(case_id)
    finally:
        store.close()
    if args.json:
        print(json.dumps({"case_id": case_id, "runs": rows}, indent=2, ensure_ascii=False))
        return EXIT_OK
    if not rows:
        print(f"no runs for {case_id}")
        return EXIT_OK
    header = (
        "run",
        "status",
        "failed_stage",
        "extraction",
        "source",
        "src_attempt",
        "attempts",
        "unknown_outcome",
        "started_at",
    )
    lines = [header]
    for r in rows:
        status = r["status"] + ("(stop-after extract)" if r["stopped_after"] else "")
        lines.append(
            (
                str(r["id"]),
                status,
                r["failed_stage"] or "-",
                str(r["extraction_id"]) if r["extraction_id"] is not None else "-",
                {"cache": "cache hit", "replay": "replay", "api": "fresh call"}.get(
                    r["extraction_source"] or "", "-"
                ),
                str(r["source_attempt_id"]) if r["source_attempt_id"] is not None else "-",
                str(r["attempts"]),
                str(r["unknown_outcomes"]),
                r["started_at"],
            )
        )
    widths = [max(len(line[i]) for line in lines) for i in range(len(header))]
    print(f"runs for {case_id}")
    for line in lines:
        print("  ".join(cell.ljust(w) for cell, w in zip(line, widths, strict=True)).rstrip())
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse exits for --version / --help / bad args
        return int(exc.code) if isinstance(exc.code, int) else EXIT_OK
    if args.command is None:
        parser.print_help()
        return EXIT_OK
    configure_logging()
    if args.command == "check":
        return cmd_check(args)
    if args.command == "history":
        return cmd_history(args)
    print(f"bridge {args.command}: not implemented yet", file=sys.stderr)
    return EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
