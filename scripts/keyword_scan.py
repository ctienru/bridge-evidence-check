"""Deterministic keyword scan (annotation guide W-01, W-03; planning 05 §5.2 step 3).

Terms: `rules/scan-terms-v1.yaml` plus every `names:` entry of `rules/drugs-v1.yaml`.
Matching is case-insensitive; alphanumeric terms match on word boundaries (so `EF` does
not match `left`), terms with other characters (`GLP-1`, `A1c`, `Part D`) match as plain
substrings. Every document is split into sentences; a sentence is covered when any
candidate quote span (`doc_id`, `start`, `end`) overlaps it. One JSON line per uncovered
hit: `{"doc_id", "start", "end", "sha8", "term"}` — the sentence span, the sha8 of the
sentence and the term; never the text. A count per document is printed. Holdout variants
are refused, whether named with `--case` or reached through a `--doc` path (AGENTS.md).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from bridge_check.dataside.sentences import split_sentences
from bridge_check.manifest import inputs_problem, is_safe_id, read_problem, write_problem
from bridge_check.rules_schema import load_drugs
from bridge_check.text import read_doc, sha8

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TERMS = ROOT / "rules" / "scan-terms-v1.yaml"
DEFAULT_DRUGS = ROOT / "rules" / "drugs-v1.yaml"
_ALNUM = re.compile(r"^[A-Za-z0-9]+$")


def load_terms(terms_path: Path, drugs_path: Path | None) -> list[str]:
    data: Any = yaml.safe_load(terms_path.read_text(encoding="utf-8"))
    terms: list[str] = [str(t) for t in data["terms"]]
    include = data.get("include_drug_names_from")
    if include is not None:
        path = drugs_path if drugs_path is not None else terms_path.parent.parent / str(include)
        for drug in load_drugs(path).drugs:
            terms.extend(drug.names)
    seen: dict[str, str] = {}
    for term in terms:
        seen.setdefault(term.casefold(), term)
    return list(seen.values())


def term_pattern(term: str) -> re.Pattern[str]:
    escaped = re.escape(term)
    if _ALNUM.match(term):
        escaped = rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])"
    return re.compile(escaped, re.IGNORECASE)


Span = tuple[int, int, str]
"""A candidate quote span with the sha8 of its text, as written to candidates.jsonl."""


def load_candidate_spans(path: Path | None) -> dict[str, list[Span]]:
    """Coverage spans from candidates.jsonl: only `located` lines with integer offsets
    `0 <= start < end` and a `sha8` count; anything else never hides a keyword hit."""
    spans: dict[str, list[Span]] = {}
    if path is None:
        return spans
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if item.get("location", "located") != "located":
            continue
        start, end, digest = item.get("start"), item.get("end"), item.get("sha8")
        if not (isinstance(start, int) and isinstance(end, int)) or isinstance(start, bool):
            continue
        if not (0 <= start < end) or not isinstance(item.get("doc_id"), str):
            continue
        if not isinstance(digest, str):
            continue
        spans.setdefault(item["doc_id"], []).append((start, end, digest))
    return spans


def scan_document(
    doc_id: str, text: str, terms: list[str], covered: list[Span]
) -> list[dict[str, Any]]:
    """Uncovered hits. A candidate span covers a sentence only if it is in bounds and its
    `sha8` still matches the current text, so a stale candidates file hides nothing."""
    patterns = [(term, term_pattern(term)) for term in terms]
    hits: list[dict[str, Any]] = []
    valid = [
        (s, e) for s, e, digest in covered if 0 <= s < e <= len(text) and sha8(text[s:e]) == digest
    ]
    for start, end in split_sentences(text):
        if any(c_start < end and start < c_end for c_start, c_end in valid):
            continue
        sentence = text[start:end]
        for term, pattern in patterns:
            if pattern.search(sentence):
                hits.append(
                    {
                        "doc_id": doc_id,
                        "start": start,
                        "end": end,
                        "sha8": sha8(sentence),
                        "term": term,
                    }
                )
    return hits


def documents_for_case(root: Path, variant_id: str) -> dict[str, Path]:
    """Documents of `input.yaml`; every path is checked (resolved) before it is read."""
    case_dir = root / "cases" / variant_id
    input_yaml = case_dir / "input.yaml"
    problem = read_problem(root, input_yaml)
    if problem is not None:
        raise ValueError(problem)
    try:
        data: Any = yaml.safe_load(input_yaml.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"input.yaml: invalid YAML ({type(exc).__name__})") from None
    docs: dict[str, Path] = {}
    for entry in data["documents"]:
        doc_id = str(entry["doc_id"])
        if not is_safe_id(doc_id):
            raise ValueError("input.yaml: doc_id is not a plain id")
        docs[doc_id] = case_dir / "docs" / f"{doc_id}.txt"
    return docs


def access_problem(root: Path, case: str | None, docs: list[Path], out: Path) -> str | None:
    """Refuse before reading or writing: holdout reads (resolved paths), protected outputs."""
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
    return write_problem(root, out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--case", default=None, help="variant id; documents from input.yaml")
    parser.add_argument("--doc", type=Path, action="append", default=[], help="document file")
    parser.add_argument(
        "--doc-id", action="append", default=[], help="de-identified id, one per --doc"
    )
    parser.add_argument("--candidates", type=Path, default=None, help="candidates.jsonl")
    parser.add_argument("--out", type=Path, required=True, help="uncovered.jsonl")
    parser.add_argument("--terms", type=Path, default=DEFAULT_TERMS)
    parser.add_argument("--drugs", type=Path, default=DEFAULT_DRUGS)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    if (args.case is None) == (not args.doc):
        parser.error("give exactly one of --case or --doc")

    root: Path = args.root.resolve()
    if args.doc and len(args.doc) != len(args.doc_id):
        parser.error("each --doc needs a --doc-id (file names are never used as ids)")
    if any(not is_safe_id(d) for d in args.doc_id):
        parser.error("--doc-id must be a plain id")
    problem = access_problem(root, args.case, args.doc, args.out)
    if problem is None:
        inputs = {"--terms": args.terms, "--drugs": args.drugs}
        if args.candidates is not None:
            inputs["--candidates"] = args.candidates
        problem = inputs_problem(root, inputs)
    if problem is not None:
        print(f"keyword_scan: {problem}", file=sys.stderr)
        return 1
    try:
        docs = (
            documents_for_case(root, args.case)
            if args.case
            else dict(zip(args.doc_id, args.doc, strict=True))
        )
    except ValueError as exc:
        print(f"keyword_scan: {exc}", file=sys.stderr)
        return 1
    for path in docs.values():  # documents derived from input.yaml are checked too
        problem = read_problem(root, path)
        if problem is not None:
            print(f"keyword_scan: {problem}", file=sys.stderr)
            return 1
    terms = load_terms(args.terms, args.drugs)
    covered = load_candidate_spans(args.candidates)
    total = 0
    with args.out.open("w", encoding="utf-8") as out:
        for doc_id, path in docs.items():
            hits = scan_document(doc_id, read_doc(path), terms, covered.get(doc_id, []))
            for hit in hits:
                out.write(json.dumps(hit) + "\n")
            total += len(hits)
            print(f"keyword_scan: {doc_id}: {len(hits)} uncovered hit(s)")
    print(f"keyword_scan: {total} uncovered hit(s) in {len(docs)} document(s) -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
