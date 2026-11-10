"""`bridge eval --split dev|holdout [--offline] [--data-root] [--json]` (contract §1, §11).

Builds the list of variants from `splits.yaml`, runs or replays each dev variant through the
whole pipeline (`cli.check_case`), scores every run (`bridge_check.scoring`), writes the
public report through `export_public_report()`, compares the result with the baseline of
the PR base (`bridge_check.baseline`) and exits 0 (no regression), 1 (regression), 3 (a run
failed or the evaluation could not run) or 4 (another run holds the lock).

Holdout: a manifest row whose `split` is not `dev` is skipped with a logged reason and
nothing under its directory is resolved or opened. A dev row whose `cases/<variant_id>/`
directory is absent from the data root is a hash-only row (its files live in the private
repo): it is skipped with reason `hash_only`, listed under `skipped`, never opened and never
scored, and it does not make the report incomplete; with `--data-root` pointing at a
checkout that holds the directory it is evaluated like any other dev row. A dev row whose
directory, any file beneath it or its replay resolves into a holdout variant (a link) is
refused before any read (`manifest.read_problem`) and the evaluation exits 3. A dev
evaluation never reads a holdout file and never scores one.

`--split holdout` (the one-shot holdout evaluation, contract §11) requires `--data-root`
naming a directory outside this checkout (the private data); without it, or with a data
root inside this checkout, the evaluation is refused before anything is read. Rows of any
other split are skipped (`other_split`) without being named. The report is written as
`eval-holdout.json` and `eval-holdout.md`; there is no holdout baseline, so
`--baseline-from` and `--write-baseline` are refused. `bridge check` and `bridge history`
still refuse holdout variants.

`--offline`: no API call. Each variant's extraction is the committed replay
`replays/<variant_id>/<input_hash>-<prompt_version>-<schema_version>.json`, restored and
seeded into the run's own attempt (`attempt_no = 0`, `response_saved`, cost NULL), parsed
with the same classifier as a live reply and stored under a replay-scoped cache key, so the
run's `extraction_source` is `replay` (or `cache` when the same replay was seeded earlier
in the same database) and a live extraction cached by a previous `check` is never used. A
variant without a replay for the current input hash, prompt and schema is a failed run
(`extract` stage) and stays in every denominator, whatever the database holds.
`fixtures/synthetic/` is never a replay source. The database is a fresh temporary file
unless `--db` is given; `./bridge.db` is never touched.

Online (no `--offline`): the real client, cache and saved responses first; the per-eval
cost ceiling (ADR 0001) is enforced by passing what the earlier runs of this evaluation
spent to `extract()`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bridge_check import cli
from bridge_check.baseline import (
    BASELINE_PATH,
    RegressionItem,
    build,
    dump,
    load_baseline_at,
    regressions,
)
from bridge_check.casemeta import CaseMeta, fixture_traps, load_case_meta
from bridge_check.compute import DrugIndex
from bridge_check.evalreport import render_eval_markdown
from bridge_check.export import (
    ExportError,
    export_public_report,
    link_problem,
    replay_path,
    restore_extraction,
    write_public_file,
)
from bridge_check.extract import (
    LIMITS,
    PROMPT_VERSION,
    TOOL_NAME,
    ExtractionFailed,
    ExtractResult,
    build_request,
    cache_key,
    classify_response,
    extract,
    load_system_prompt,
)
from bridge_check.gold_schema import Gold
from bridge_check.input import InputError, LoadedCase, canonical_json, load_input
from bridge_check.logs import log_event
from bridge_check.manifest import (
    CHECKOUT_ROOT,
    MANIFEST_NAME,
    UnreadableYaml,
    _within,
    containment_problem,
    manifest_variants,
    read_problem,
    write_problem,
)
from bridge_check.rules_schema import load_drugs, load_rules
from bridge_check.runlock import RunLockHeld, exclusive_run_lock, lock_path, resolve_db_path
from bridge_check.schema import SCHEMA_VERSION, Extraction
from bridge_check.scoring import CaseScore, Split, score_split, score_stored_run
from bridge_check.store import (
    DatabaseHasLinks,
    SchemaVersionMismatch,
    SqliteTooOld,
    Store,
    open_store,
    recover_orphaned_runs,
    require_sqlite_version,
    sidecar_paths,
)

EVAL_VERSION = 1
SKIP_HOLDOUT = "holdout_never_read"
SKIP_OTHER_SPLIT = "other_split"
"""A row of another split in a holdout evaluation: never named, never opened."""
SKIP_HOLDOUT_MISSING = "holdout_missing"
"""A holdout row whose `cases/<variant_id>/` directory is absent from the data root: the
holdout evaluation fails (exit 3), since a frozen holdout variant went unscored."""
SKIP_VARIANT_MISMATCH = "variant_mismatch"
"""A holdout row whose `input.yaml` names another variant: refused, exit 3."""
SKIP_BATCH_REFUSED = "batch_refused"
"""A holdout row that passed every check but was not run because another row of the batch
was refused: every row is checked before the first extraction, so the batch stays at zero
attempts."""
SKIP_MTSAMPLES = "mtsamples_unavailable"
SKIP_REFUSED = "holdout_path_refused"
SKIP_HASH_ONLY = "hash_only"
"""A dev row without a `cases/<variant_id>/` directory in the data root (contract §11):
skipped, never opened, never scored; the report stays complete."""
"""A dev row whose directory, or a file under it, resolves into a holdout variant (a link).
Nothing of it is opened; the evaluation fails (exit 3) because a dev variant went unscored."""
MTSAMPLES_DOC = "docs/D2-mtsamples-"
FIXTURES_RULES = CHECKOUT_ROOT / "fixtures" / "synthetic" / "rules"


class NoApiClient:
    """A client for `--offline`: any request is a bug and fails the run as `api_error`."""

    def with_options(self, **_: Any) -> NoApiClient:
        return self

    @property
    def messages(self) -> NoApiClient:
        return self

    def create(self, **_: Any) -> Any:
        raise RuntimeError("offline evaluation: an API call was attempted")


class ReplayExtractor:
    """`cli.Extractor` that seeds the committed replay of the case (module docstring).

    The committed replay is required for every variant, every time: an extraction a
    previous `check` cached for the same request is never used, because a live cache would
    mask a missing or changed replay and move the regression result. Replay-derived
    extractions are stored under their own cache key, derived from the request key and the
    replay file's hash, so they and the live cache never meet."""

    def __init__(
        self,
        replays_root: Path,
        root: Path = CHECKOUT_ROOT,
        *,
        holdout: bool = False,
        anchor: Path | None = None,
    ) -> None:
        self.replays_root = replays_root
        self.root = root
        self.holdout = holdout
        # holdout: the verified replay directory; `<anchor>/<variant_id>/` is built from it
        # lexically, so a link at `replays/` or at `replays/<variant_id>/` is refused
        self.anchor = anchor if anchor is not None else replays_root.resolve()

    def __call__(self, case: LoadedCase, store: Store, run_id: int) -> ExtractResult:
        request = build_request(case, load_system_prompt(), LIMITS)
        path = replay_path(
            self.replays_root, case.case_id, case.input_hash, PROMPT_VERSION, SCHEMA_VERSION
        )
        if read_problem(self.root, path, allow_holdout=self.holdout) is not None:
            raise ExtractionFailed(
                "extract", "HoldoutRefused", "the replay path resolves into a holdout variant"
            )
        if self.holdout and not path.resolve().is_relative_to(self.anchor / case.case_id):
            raise ExtractionFailed(
                "extract", "HoldoutRefused", "the replay path resolves outside its variant"
            )
        if not path.is_file():
            raise ExtractionFailed(
                "extract",
                "ReplayMissing",
                "no committed replay for this input hash, prompt and schema version",
            )
        raw = path.read_bytes()
        replay: dict[str, Any] = json.loads(raw.decode("utf-8"))
        if replay.get("doc_sha256") != case.doc_sha256:
            raise ExtractionFailed(
                "extract", "ReplayDocMismatch", "replay names other document hashes"
            )
        key = replay_cache_key(cache_key(request), raw)
        hit = store.find_extraction(key)
        if hit is not None:  # this same replay, seeded by an earlier offline run in this DB
            log_event("extract_cache_hit", run_id=run_id, case_id=case.case_id, stage="extract")
            return ExtractResult(
                int(hit["id"]),
                "cache",
                key,
                int(hit["attempt_id"]),
                Extraction.model_validate_json(hit["parsed_json"]),
            )
        extraction = restore_extraction(replay, case.texts)
        usage = (replay.get("response") or {}).get("usage") or {}
        message = {
            "id": "msg_replay",
            "type": "message",
            "role": "assistant",
            "model": replay.get("model_returned"),
            "stop_reason": "tool_use",
            "stop_sequence": None,
            "usage": {
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
            },
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_replay",
                    "name": TOOL_NAME,
                    "input": extraction.model_dump(mode="json"),
                }
            ],
        }
        attempt_id = store.insert_attempt(
            case_run_id=run_id, cache_key=key, attempt_no=0, request_json=canonical_json(request)
        )
        store.save_response(
            attempt_id,
            response_json=json.dumps(message, ensure_ascii=False, sort_keys=True),
            model_returned=replay.get("model_returned"),
            latency_ms=0,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            cost_usd=None,
        )
        log_event("replay_seeded", run_id=run_id, case_id=case.case_id, stage="extract")
        outcome = classify_response(message)
        if outcome.status != "parsed" or outcome.extraction is None:
            store.set_attempt_status(
                attempt_id, outcome.status, error_type=outcome.error_type, error=outcome.message
            )
            store.insert_dead_letter(
                case_run_id=run_id,
                attempt_id=attempt_id,
                stage="parse",
                error_type=outcome.error_type or "ParseError",
                fact_path=outcome.fact_path,
                message=outcome.message or outcome.status,
            )
            raise ExtractionFailed("parse", outcome.error_type or "ParseError", "replay rejected")
        extraction_id = store.mark_parsed(
            attempt_id,
            cache_key=key,
            parsed_json=outcome.extraction.model_dump_json(),
            schema_version=SCHEMA_VERSION,
            prompt_version=PROMPT_VERSION,
        )
        log_event("attempt_parsed", run_id=run_id, case_id=case.case_id, stage="parse")
        return ExtractResult(extraction_id, "replay", key, attempt_id, outcome.extraction)


def replay_cache_key(request_key: str, replay_bytes: bytes) -> str:
    """The cache key of a replay-derived extraction: the request key and the replay file
    together, so a live extraction of the same request is never a hit here and a changed
    replay is a new key."""
    return hashlib.sha256(
        b"replay:" + request_key.encode("ascii") + b":" + replay_bytes
    ).hexdigest()


class ApiExtractor:
    """`cli.Extractor` for an online evaluation: the per-eval cost ceiling sees what the
    earlier runs of this evaluation spent (`spent`, updated by the caller)."""

    def __init__(self) -> None:
        self.spent = 0.0

    def __call__(self, case: LoadedCase, store: Store, run_id: int) -> ExtractResult:
        client = cli.make_client(case.case_dir)
        return extract(case, client, store, run_id=run_id, limits=LIMITS, eval_spent_usd=self.spent)


@dataclass(frozen=True)
class EvalOptions:
    split: Split = "dev"
    offline: bool = False
    data_root: Path = CHECKOUT_ROOT
    replays_root: Path | None = None
    db: Path | None = None
    baseline_ref: str | None = None
    out: Path | None = None
    write_baseline: bool = False
    baseline_out: Path | None = None
    json_output: bool = False
    skip: tuple[str, ...] = field(default_factory=tuple)


def add_eval_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--split",
        choices=["dev", "holdout"],
        required=True,
        help="dev, or holdout (requires --data-root outside this checkout; no baseline)",
    )
    parser.add_argument("--offline", action="store_true", help="replays only; no API call")
    parser.add_argument(
        "--data-root", help="directory holding splits.yaml and cases/ (default: this checkout)"
    )
    parser.add_argument("--replays", help="replay directory (default: <data-root>/replays)")
    parser.add_argument("--db", help="SQLite database (default: a fresh temporary file)")
    parser.add_argument(
        "--baseline-from",
        help="git ref whose reports/baseline-dev.json is the regression baseline",
    )
    parser.add_argument(
        "--out", help="directory for eval-<split>.json and eval-<split>.md (default: reports/)"
    )
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="also rewrite reports/baseline-dev.json from these runs",
    )
    parser.add_argument("--json", action="store_true", help="print the public report as JSON")


def options_from_args(args: argparse.Namespace) -> EvalOptions:
    data_root = Path(args.data_root).expanduser().resolve() if args.data_root else CHECKOUT_ROOT
    return EvalOptions(
        split=args.split,
        offline=bool(args.offline),
        data_root=data_root,
        replays_root=Path(args.replays).expanduser().resolve() if args.replays else None,
        db=resolve_db_path(args.db) if args.db else None,
        baseline_ref=args.baseline_from,
        out=Path(args.out).expanduser().resolve() if args.out else None,
        write_baseline=bool(args.write_baseline),
        json_output=bool(args.json),
    )


@dataclass
class _Scored:
    variant_id: str
    run_id: int
    score: CaseScore
    meta: CaseMeta


def holdout_problem(root: Path, case_dir: Path, *, allow_holdout: bool = False) -> str | None:
    """Why nothing under `case_dir` may be opened: the directory, or any path beneath it
    (links included, resolved), lies in a holdout variant. Only `stat` calls are made.
    `rglob` does not descend into a linked directory, so this is the early, cheap check;
    the exact path of every file is checked again right before it is opened
    (`input.load_case`, `ReplayExtractor`, `casemeta`, the gold read below). With
    `allow_holdout` (`--split holdout`) only the hard-link check remains."""
    problem = read_problem(root, case_dir, allow_holdout=allow_holdout)
    if problem is not None:
        return problem
    if allow_holdout and (case_dir.exists() or case_dir.is_symlink()):
        problem = containment_problem(root, case_dir, case_dir)
        if problem is not None:
            return problem
    if not case_dir.is_dir():
        return None
    for path in sorted(case_dir.rglob("*")):
        problem = read_problem(root, path, allow_holdout=allow_holdout)
        if problem is None and allow_holdout:
            problem = containment_problem(root, case_dir, path)
        if problem is not None:
            return problem
    return None


def _private_db_problem(db: Path, root: Path) -> str | None:
    """A holdout database, its lock and its SQLite sidecars hold raw requests and responses
    (document text): none may lie in the public checkout or in a holdout variant."""
    paths = {"database": db, "lock": lock_path(db)}
    paths |= {f"database-sidecar-{i}": s for i, s in enumerate(sidecar_paths(db))}
    for what, path in paths.items():
        for base in (CHECKOUT_ROOT, root):
            bad = write_problem(base, path, public_roots=[CHECKOUT_ROOT])
            if bad is not None:
                return f"{what}: {bad}"
    return None


def _input_variant(case_dir: Path, root: Path) -> str | None:
    """The `variant_id` a holdout case's own `input.yaml` names (None when unreadable);
    read with the holdout containment guard, so a link out of the directory is refused."""
    try:
        return load_input(case_dir, root, allow_holdout=True).variant_id
    except InputError:
        return None


def _mtsamples_missing(row: Mapping[str, Any], case_dir: Path) -> bool:
    files = row.get("files") or {}
    return any(
        rel.startswith(MTSAMPLES_DOC) and not (case_dir / rel).is_file()
        for rel in files
        if isinstance(rel, str)
    )


def _generated_from(store: Store, scored: list[_Scored]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "code_sha": cli.code_sha(),
        "prompt_version": PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "rules_version": cli.rules_version(),
        "splitter_version": None,
        "model_returned": None,
    }
    for s in scored:
        run = store.case_run(s.run_id)
        out["splitter_version"] = run["splitter_version"]
        ext = store.extraction_for_run(s.run_id)
        if ext is not None and ext["attempt_id"] is not None:
            out["model_returned"] = store.attempt(int(ext["attempt_id"]))["model_returned"]
            break
    return out


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_eval(opts: EvalOptions) -> tuple[int, dict[str, Any], str]:
    """Run the evaluation; returns `(exit code, public report, markdown)`. Raises
    `RunLockHeld`, `SqliteTooOld`, `DatabaseHasLinks`, `SchemaVersionMismatch` and
    `ExportError` to the caller (`cmd_eval` maps them to exit codes and messages)."""
    root = opts.data_root
    holdout = opts.split == "holdout"
    if holdout:
        # refused before any destination is checked, any directory created or any file
        # read: holdout data is never looked for in this checkout
        if _within(root.resolve(), CHECKOUT_ROOT):  # also a differently cased spelling
            raise ExportError(
                "--split holdout: --data-root is required and must lie outside this checkout"
            )
        if opts.write_baseline or opts.baseline_ref is not None or opts.baseline_out is not None:
            raise ExportError(
                "--split holdout: there is no holdout baseline; "
                "--baseline-from and --write-baseline are refused"
            )
        if opts.db is None and _within(Path(tempfile.gettempdir()).resolve(), CHECKOUT_ROOT):
            # the default database is a temporary file; it holds the raw requests
            raise ExportError(
                "--split holdout: the temporary directory lies inside the public checkout; "
                "pass --db outside it"
            )
    stem = f"eval-{opts.split}"
    replays_root = opts.replays_root or root / "replays"
    out_dir = opts.out or CHECKOUT_ROOT / "reports"
    baseline_target = opts.baseline_out or CHECKOUT_ROOT / BASELINE_PATH
    # Every destination is checked against the checkout and the selected data root before
    # a directory is created, a lock taken or a database opened: a report, a baseline, the
    # database, its lock file or a SQLite sidecar (`-wal`, `-shm`, `-journal`, which SQLite
    # writes and truncates by name) must never land in a holdout variant or be a link.
    destinations = {
        f"{stem}.json": out_dir / f"{stem}.json",
        f"{stem}.md": out_dir / f"{stem}.md",
        **({"baseline": baseline_target} if opts.write_baseline else {}),
        **(
            {
                "database": opts.db,
                "lock": lock_path(opts.db),
                **{f"database-sidecar-{i}": s for i, s in enumerate(sidecar_paths(opts.db))},
            }
            if opts.db is not None
            else {}
        ),
    }
    raw_text = {"database", "lock"} | {w for w in destinations if w.startswith("database-")}
    for what, path in destinations.items():
        # in a holdout evaluation the database holds every raw request and response (the
        # document text): it, its lock and its sidecars are private outputs
        public_roots = [CHECKOUT_ROOT] if holdout and what in raw_text else None
        for base in (CHECKOUT_ROOT, root):
            bad = write_problem(base, path, public_roots=public_roots)
            if bad is not None:
                raise ExportError(f"{what}: {bad}")
        linked = link_problem(path)
        if linked is not None and what != "database":  # the store checks the file itself
            raise ExportError(f"{what}: {linked}")
    require_sqlite_version()
    rules = load_rules(cli.RULES_PATH)
    drugs = DrugIndex(load_drugs(cli.DRUGS_PATH))
    manifest_path = root / MANIFEST_NAME
    manifest_sha = _sha256(manifest_path.read_bytes()) if manifest_path.is_file() else ""

    skipped: list[dict[str, str]] = []
    scored: list[_Scored] = []
    failed_runs = 0
    refused = 0
    cost = 0.0
    tmp: tempfile.TemporaryDirectory[str] | None = None
    db = opts.db
    if db is None:
        tmp = tempfile.TemporaryDirectory(prefix="bridge-eval-")
        db = Path(tmp.name) / "eval.db"
        if holdout:
            problem = _private_db_problem(db, root)
            if problem is not None:
                tmp.cleanup()
                raise ExportError(problem)
    replays_anchor = (
        opts.replays_root.resolve() if opts.replays_root else root.resolve() / "replays"
    )
    extractor: ReplayExtractor | ApiExtractor = (
        ReplayExtractor(replays_root, root, holdout=holdout, anchor=replays_anchor)
        if opts.offline
        else ApiExtractor()
    )
    try:
        with exclusive_run_lock(db, blocking=False):
            store = open_store(db)
            try:
                if recover_orphaned_runs(store.conn):
                    log_event("recovered_orphaned_runs", stage="interrupted")
                # pass 1 decides every row; pass 2 runs the selected ones
                selected: list[tuple[str, Path]] = []
                for row in manifest_variants(root):
                    vid = str(row.get("variant_id") or "")
                    if row.get("split") != opts.split:
                        # never resolved, never opened: the directory is not even named
                        reason = SKIP_OTHER_SPLIT if holdout else SKIP_HOLDOUT
                        skipped.append({"variant_id": vid, "reason": reason})
                        log_event("eval_skipped", case_id=vid, stage="input")
                        continue
                    case_dir = root / "cases" / vid
                    if holdout_problem(root, case_dir, allow_holdout=holdout) is not None:
                        # a dev name that leads into a holdout variant: nothing is opened
                        skipped.append({"variant_id": vid, "reason": SKIP_REFUSED})
                        log_event("eval_refused", case_id=vid, stage="input")
                        refused += 1
                        continue
                    if not case_dir.is_dir() and holdout:
                        # a frozen holdout variant without its files: never a pass
                        skipped.append({"variant_id": vid, "reason": SKIP_HOLDOUT_MISSING})
                        log_event("eval_refused", case_id=vid, stage="input")
                        refused += 1
                        continue
                    if not case_dir.is_dir():
                        # a hash-only row: the files are not in this checkout
                        skipped.append({"variant_id": vid, "reason": SKIP_HASH_ONLY})
                        log_event("eval_skipped", case_id=vid, stage="input")
                        continue
                    if holdout and _input_variant(case_dir, root) != vid:
                        # the manifest row and `input.yaml` must name the same variant
                        skipped.append({"variant_id": vid, "reason": SKIP_VARIANT_MISMATCH})
                        log_event("eval_refused", case_id=vid, stage="input")
                        refused += 1
                        continue
                    if _mtsamples_missing(row, case_dir):
                        skipped.append({"variant_id": vid, "reason": SKIP_MTSAMPLES})
                        log_event("eval_skipped", case_id=vid, stage="input")
                        continue
                    selected.append((vid, case_dir))
                if holdout and refused:
                    # one refused holdout row stops the whole batch before any extraction
                    for vid, _ in selected:
                        skipped.append({"variant_id": vid, "reason": SKIP_BATCH_REFUSED})
                        log_event("eval_skipped", case_id=vid, stage="input")
                    selected = []
                for vid, case_dir in selected:
                    run_id, _ = cli.check_case(
                        store,
                        str(case_dir),
                        None,
                        extractor=extractor,
                        root=root,
                        allow_holdout=holdout,
                    )
                    run_cost = store.cost_for_run(run_id)
                    cost += run_cost
                    if isinstance(extractor, ApiExtractor):
                        extractor.spent = cost
                    gold_path = case_dir / "expected.json"
                    for exact in (gold_path, case_dir / "case.yaml"):
                        if read_problem(root, exact, allow_holdout=holdout) is not None:
                            raise ExportError(f"{exact.name} resolves into a holdout variant")
                        if holdout and containment_problem(root, case_dir, exact) is not None:
                            raise ExportError(f"{exact.name} resolves outside its case directory")
                    gold_raw = gold_path.read_bytes()
                    gold = Gold.model_validate_json(gold_raw)
                    meta = load_case_meta(case_dir, vid)
                    score = score_stored_run(
                        store,
                        run_id,
                        gold=gold,
                        gold_sha256=_sha256(gold_raw),
                        meta=meta,
                        rules=rules,
                        drugs=drugs,
                    )
                    failed_runs += score.run_status != "completed"
                    scored.append(_Scored(vid, run_id, score, meta))
                split = score_split(
                    [s.score for s in scored],
                    manifest_sha256=manifest_sha,
                    rules=rules,
                    metas=[s.meta for s in scored],
                    fixture_traps=fixture_traps(FIXTURES_RULES),
                    split=opts.split,
                )
                generated = _generated_from(store, scored)
                baseline_data: dict[str, Any] | None = None
                complete = (
                    failed_runs == 0
                    and refused == 0
                    and not any(s["reason"] == SKIP_MTSAMPLES for s in skipped)
                )  # holdout and hash-only rows are always skipped and never block the write
                if opts.write_baseline and complete:
                    baseline_data = build(store, {s.variant_id: s.run_id for s in scored}, root)
            finally:
                store.close()
    finally:
        if tmp is not None:
            tmp.cleanup()

    baseline, raw, problem = load_baseline_at(opts.baseline_ref, CHECKOUT_ROOT)
    if problem is not None:
        print(f"bridge eval: baseline: {problem}", file=sys.stderr)
    items: list[RegressionItem] = (
        regressions(baseline, split, skipped=[s["variant_id"] for s in skipped])
        if baseline is not None
        else []
    )
    gold_changed = (
        sorted(
            vid
            for vid, case in baseline.cases.items()
            if vid in split.cases and split.cases[vid].gold_sha256 != case.gold_sha256
        )
        if baseline is not None
        else []
    )
    incomplete = any(s["reason"] == SKIP_MTSAMPLES for s in skipped)
    if failed_runs or refused or problem is not None:
        # a run failed, a dev variant could not be scored, or the requested comparison
        # could not run: never a pass
        code = cli.EXIT_FAILED
    elif items:
        code = cli.EXIT_REGRESSION
    else:
        code = cli.EXIT_OK
    report = {
        "eval_version": EVAL_VERSION,
        "split": opts.split,
        "mode": "offline" if opts.offline else "online",
        "generated_from": generated,
        "manifest_sha256": manifest_sha,
        "incomplete": incomplete,
        "skipped": skipped,
        "baseline": {
            "ref": opts.baseline_ref,
            "found": baseline is not None,
            "bootstrap": opts.baseline_ref is None or (baseline is None and problem is None),
            "problem": None if problem is None else "unreadable",
            "sha256": _sha256(raw) if raw is not None else None,
            "gold_changed": gold_changed,
        },
        "regression": {
            "detected": bool(items),
            "items": [i.model_dump() for i in items],
        },
        "exit_code": code,
        "cost_usd": round(cost, 6),
        "score": split.model_dump(),
    }
    public = export_public_report(report)
    markdown = render_eval_markdown(public)

    for name, text in ((f"{stem}.json", dump(public)), (f"{stem}.md", markdown)):
        write_public_file(out_dir / name, text)
    if opts.write_baseline:
        if baseline_data is None:
            print(
                "bridge eval: baseline not written (a run failed, a variant was refused "
                "or MTSamples was unavailable)",
                file=sys.stderr,
            )
        else:
            # checked above against both roots: a holdout path, an annotator-owned name or
            # a link that resolves to one never gets this far
            write_public_file(baseline_target, dump(baseline_data))
    return code, public, markdown


def cmd_eval(args: argparse.Namespace) -> int:
    opts = options_from_args(args)
    try:
        code, public, _ = run_eval(opts)
    except RunLockHeld:
        print(
            "bridge eval: another run in progress (lock held); nothing was changed",
            file=sys.stderr,
        )
        return cli.EXIT_LOCKED
    except (SqliteTooOld, DatabaseHasLinks, ExportError, UnreadableYaml) as exc:
        print(f"bridge eval: {exc}", file=sys.stderr)
        return cli.EXIT_FAILED
    except SchemaVersionMismatch as exc:
        print(f"bridge eval: {cli.DB_LABEL} {exc.for_file()}", file=sys.stderr)
        return cli.EXIT_FAILED
    except (OSError, ValueError) as exc:
        print(f"bridge eval: {type(exc).__name__}", file=sys.stderr)
        return cli.EXIT_FAILED
    if opts.json_output:
        print(json.dumps(public, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        m = public["score"]["micro"]
        print(
            f"bridge eval: {m['variants']} variants ({m['runs_failed']} failed), conditions "
            f"{m['conditions_correct']['n']}/{m['conditions_correct']['of']}, claims "
            f"{m['claims_correct']['n']}/{m['claims_correct']['of']}, false supports "
            f"{m['false_supports']['count']}, missed exclusions {m['missed_exclusions']['n']}; "
            f"regression: {'yes' if public['regression']['detected'] else 'no'}; "
            f"skipped {len(public['skipped'])}"
        )
    return code
