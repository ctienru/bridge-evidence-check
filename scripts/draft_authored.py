"""Route 1: draft authored documents from a spec and check them (planning 05 §5.2).

Reads `--spec <yaml>` (a `DraftSpec`) and `--prompt <file>` (both kept in the private
repo) and calls the data-line model in JSON mode. Every round's complete raw reply is
appended to `--raw-out` (private) **before** parsing; refusal, truncation and bad JSON
then end the run with exit 1. The parsed reply must name exactly the spec's documents and
fact ids. The four deterministic checks of `bridge_check.drafting` run per fact; all pass
→ documents go to `--out-docs/<doc_id>.txt` (`newline=""`, ids checked to stay inside
that directory) and the drafting record (`drafted_by` = the reply's `model`, `drafted_at`,
`quote_map`, `checks`) to `--out-record`. Any failure → the per-fact table (fact_id,
check, pass/fail only) and exit 1; `--rounds N` re-prompts with the failed fact ids once
per extra round. `--raw-out` and `--out-record` must lie outside the public checkout.
Without `OPENAI_API_KEY` (environment or `.env`) exit 2. Nothing printed is document text.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from bridge_check.dataside.cues import load_cues
from bridge_check.dataside.drafting import (
    RESPONSE_SCHEMA,
    build_messages,
    build_record,
    failed_fact_ids,
    format_table,
    load_spec,
    parse_response,
    run_checks,
    write_documents,
)
from bridge_check.dataside.openai_client import (
    DEFAULT_MODEL,
    EXIT_NO_KEY,
    RawReply,
    chat_json,
    json_schema_format,
    make_client,
    read_api_key,
)
from bridge_check.manifest import CHECKOUT_ROOT, inputs_problem, outputs_problem

ROOT = Path(__file__).resolve().parent.parent


def append_raw(archive: Any, round_no: int, reply: RawReply) -> None:
    archive.write(json.dumps({"round": round_no, **reply.as_record()}, ensure_ascii=False) + "\n")
    archive.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--out-docs", type=Path, required=True)
    parser.add_argument("--out-record", type=Path, required=True, help="drafting record (private)")
    parser.add_argument("--raw-out", type=Path, required=True, help="raw replies, jsonl (private)")
    parser.add_argument("--root", type=Path, default=ROOT, help="public checkout root")
    parser.add_argument("--env", type=Path, default=Path(".env"))
    args = parser.parse_args(argv)
    if args.rounds < 1:
        parser.error("--rounds must be at least 1")

    problem = inputs_problem(args.root.resolve(), {"--spec": args.spec, "--prompt": args.prompt})
    if problem is not None:
        print(f"draft_authored: {problem}", file=sys.stderr)
        return 1
    try:
        spec = load_spec(args.spec)
    except ValidationError as exc:
        print(f"draft_authored: spec invalid ({exc.error_count()} error(s))", file=sys.stderr)
        return 1
    except ValueError as exc:  # YAML error: type name only, never the private spec text
        print(f"draft_authored: {exc}", file=sys.stderr)
        return 1
    # every file this run will create is known from the spec; check them all before the call
    planned = {
        f"--out-docs/{d.doc_id}.txt": args.out_docs / f"{d.doc_id}.txt" for d in spec.documents
    }
    root: Path = args.root.resolve()
    problem = outputs_problem(
        root,
        {"--raw-out": args.raw_out, "--out-record": args.out_record},
        planned,
        [CHECKOUT_ROOT],
    )
    if problem is not None:
        print(f"draft_authored: {problem}", file=sys.stderr)
        return 1
    api_key = read_api_key(args.env)
    if api_key is None:
        print("draft_authored: OPENAI_API_KEY not set (environment or .env)", file=sys.stderr)
        return EXIT_NO_KEY
    prompt_text = args.prompt.read_text(encoding="utf-8")
    cues = load_cues()
    try:  # open the private archive before any call: an unwritable path costs zero calls
        args.raw_out.parent.mkdir(parents=True, exist_ok=True)
        archive = args.raw_out.open("a", encoding="utf-8")
    except OSError as exc:
        print(f"draft_authored: cannot open --raw-out ({type(exc).__name__})", file=sys.stderr)
        return 1
    with archive:
        return _run_rounds(args, spec, prompt_text, cues, make_client(api_key), archive)


def _run_rounds(
    args: Any, spec: Any, prompt_text: str, cues: Any, client: Any, archive: Any
) -> int:
    failed: list[str] = []
    for round_no in range(1, args.rounds + 1):
        try:
            reply = chat_json(
                client,
                args.model,
                build_messages(spec, prompt_text, failed),
                json_schema_format("authored_documents", RESPONSE_SCHEMA),
            )
        except Exception as exc:  # noqa: BLE001 - SDK errors may carry request text
            print(
                f"draft_authored: round {round_no}: api_error ({type(exc).__name__})",
                file=sys.stderr,
            )
            return 1
        append_raw(archive, round_no, reply)  # before anything else looks at the reply
        problem = reply.problem()
        if problem is not None:
            print(f"draft_authored: round {round_no}: reply {problem}", file=sys.stderr)
            return 1
        try:
            response = parse_response(json.loads(reply.content), spec)
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            print(
                f"draft_authored: round {round_no}: response_shape failed ({type(exc).__name__})",
                file=sys.stderr,
            )
            return 1
        results = run_checks(spec, response, cues)
        failed = failed_fact_ids(results)
        print(
            f"draft_authored: round {round_no}: model {reply.model}, "
            f"{sum(not r.passed for r in results)} failing check(s)"
        )
        if all(r.passed for r in results):
            write_documents(response, args.out_docs)
            args.out_record.parent.mkdir(parents=True, exist_ok=True)
            record = build_record(reply.model, response, results)
            args.out_record.write_text(
                json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            print(
                f"draft_authored: wrote {len(response.documents)} document(s) to {args.out_docs} "
                f"and the record to {args.out_record}"
            )
            return 0
        print(format_table(results))
    return 1


if __name__ == "__main__":
    sys.exit(main())
