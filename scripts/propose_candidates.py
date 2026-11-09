"""Route 2: propose candidate facts on real documents (planning 05 §5.2 step 2).

Documents come from `--case <variant_id>` (`cases/<id>/input.yaml` `documents[]`, texts
under `cases/<id>/docs/`) or from `--doc <path> --doc-id <id>` pairs. The annotation guide
(`--guide`) and the private prompt (`--prompt`) form the system message.

Order of operations, fixed: holdout check → private-path check → API call → the complete
raw reply (`model`, `finish_reason`, `refusal`, `content`) is written to `--raw-out`
→ only then refusal / truncation / JSON parsing are handled → each candidate's `quote` is
located verbatim (one hit → `start`, `end`, `sha8`; otherwise null offsets and
`location: not_found | ambiguous`) → `--out` receives only L-01 allow-list keys with
controlled values plus `location` (dropped keys are only counted on the console).
`--raw-out` must lie outside the public checkout (the real one, whatever `--root` says),
no two outputs may coincide, and no output may be an annotator-owned file. Without
`OPENAI_API_KEY` exit 2.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

from bridge_check.dataside.candidates import (
    RESPONSE_SCHEMA,
    build_messages,
    extract_candidates,
    locate_candidate,
)
from bridge_check.dataside.openai_client import (
    DEFAULT_MODEL,
    EXIT_NO_KEY,
    chat_json,
    json_schema_format,
    make_client,
    read_api_key,
)
from bridge_check.manifest import (
    CHECKOUT_ROOT,
    inputs_problem,
    is_safe_id,
    outputs_problem,
    read_problem,
)
from bridge_check.text import read_doc

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GUIDE = ROOT / "docs" / "annotation-guide.md"


def load_case_documents(root: Path, variant_id: str) -> tuple[dict[str, str], dict[str, str]]:
    """Documents of `input.yaml`; every file is checked (resolved path) before it is read."""
    case_dir = root / "cases" / variant_id
    input_yaml = case_dir / "input.yaml"
    _refuse_unless_readable(root, input_yaml)
    try:
        data: Any = yaml.safe_load(input_yaml.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"input.yaml: invalid YAML ({type(exc).__name__})") from None
    docs: dict[str, str] = {}
    roles: dict[str, str] = {}
    for entry in data["documents"]:
        doc_id = str(entry["doc_id"])
        if not is_safe_id(doc_id):
            raise ValueError("input.yaml: doc_id is not a plain id")
        path = case_dir / "docs" / f"{doc_id}.txt"
        _refuse_unless_readable(root, path)
        docs[doc_id] = read_doc(path)
        roles[doc_id] = str(entry.get("role", "clinical"))
    return docs, roles


def _refuse_unless_readable(root: Path, path: Path) -> None:
    problem = read_problem(root, path)
    if problem is not None:
        raise ValueError(problem)


def access_problem(root: Path, case: str | None, docs: list[Path]) -> str | None:
    if case is not None and not is_safe_id(case):
        return "--case must be a plain variant id"
    if case is not None:
        problem = read_problem(root, root / "cases" / case)
        if problem is not None:
            return problem
    for path in docs:
        problem = read_problem(root, path)
        if problem is not None:
            return problem
    return None


def open_archive(path: Path) -> tuple[Any, Path]:
    """Open a private temp file next to `--raw-out` **before** the API call, so an
    unwritable destination costs zero calls. The caller replaces `--raw-out` with it only
    after the complete reply is on disk; a failed call leaves the previous archive intact."""
    if path.exists() and not path.is_file():
        raise IsADirectoryError(str(path.name))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    return os.fdopen(fd, "w", encoding="utf-8"), Path(name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--case", default=None)
    parser.add_argument("--doc", type=Path, action="append", default=[])
    parser.add_argument("--doc-id", action="append", default=[], help="one per --doc")
    parser.add_argument("--guide", type=Path, default=DEFAULT_GUIDE)
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--out", type=Path, required=True, help="candidates.jsonl (sanitized)")
    parser.add_argument("--raw-out", type=Path, required=True, help="full raw reply (private)")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--env", type=Path, default=Path(".env"))
    args = parser.parse_args(argv)
    if (args.case is None) == (not args.doc):
        parser.error("give exactly one of --case or --doc")
    if args.doc and len(args.doc) != len(args.doc_id):
        parser.error("each --doc needs a --doc-id")
    root: Path = args.root.resolve()

    problem = access_problem(root, args.case, args.doc)
    if problem is None:
        problem = inputs_problem(root, {"--prompt": args.prompt, "--guide": args.guide})
    if problem is None:
        problem = outputs_problem(
            root, {"--raw-out": args.raw_out}, {"--out": args.out}, [CHECKOUT_ROOT]
        )
    if problem is not None:
        print(f"propose_candidates: {problem}", file=sys.stderr)
        return 1
    api_key = read_api_key(args.env)
    if api_key is None:
        print("propose_candidates: OPENAI_API_KEY not set (environment or .env)", file=sys.stderr)
        return EXIT_NO_KEY
    try:
        if args.case:
            docs, roles = load_case_documents(root, args.case)
        else:
            for doc_id in args.doc_id:
                if not is_safe_id(doc_id):
                    raise ValueError("--doc-id is not a plain id")
            docs = {
                doc_id: read_doc(path) for doc_id, path in zip(args.doc_id, args.doc, strict=True)
            }
            roles = dict.fromkeys(docs, "clinical")
    except ValueError as exc:
        print(f"propose_candidates: {exc}", file=sys.stderr)
        return 1

    messages = build_messages(
        docs, roles, args.guide.read_text(encoding="utf-8"), args.prompt.read_text(encoding="utf-8")
    )
    try:
        archive, tmp = open_archive(args.raw_out)
    except OSError as exc:  # nothing has been sent yet
        print(f"propose_candidates: cannot open --raw-out ({type(exc).__name__})", file=sys.stderr)
        return 1
    try:
        with archive:
            try:
                reply = chat_json(
                    make_client(api_key),
                    args.model,
                    messages,
                    json_schema_format("candidates", RESPONSE_SCHEMA),
                )
            except Exception as exc:  # noqa: BLE001 - SDK errors may carry request text
                print(f"propose_candidates: api_error ({type(exc).__name__})", file=sys.stderr)
                return 1
            archive.write(json.dumps(reply.as_record(), ensure_ascii=False, indent=2) + "\n")
        os.replace(tmp, args.raw_out)  # complete reply on disk: now replace the old archive
    finally:
        if tmp.exists():
            tmp.unlink()
    print(f"propose_candidates: model {reply.model}: raw reply -> {args.raw_out}")
    problem = reply.problem()
    if problem is not None:
        print(
            f"propose_candidates: reply {problem}; nothing written to {args.out}", file=sys.stderr
        )
        return 1
    try:
        candidates = extract_candidates(json.loads(reply.content))
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"propose_candidates: parse_failed ({type(exc).__name__})", file=sys.stderr)
        return 1
    counts = {"located": 0, "not_found": 0, "ambiguous": 0}
    dropped_total = 0
    with args.out.open("w", encoding="utf-8") as out:
        for candidate in candidates:
            line, dropped = locate_candidate(docs, candidate)
            counts[line["location"]] = counts.get(line["location"], 0) + 1
            dropped_total += dropped
            out.write(json.dumps(line, ensure_ascii=False) + "\n")
    print(
        f"propose_candidates: {len(candidates)} candidate(s): {counts['located']} located, "
        f"{counts['not_found']} not found, {counts['ambiguous']} ambiguous; "
        f"{dropped_total} non-allow-list key(s) dropped -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
