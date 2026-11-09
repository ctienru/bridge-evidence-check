"""Fetch the MTSamples transcription of each case that declares an `mtsamples:` block.

For every `cases/*/case.yaml` with an `mtsamples:` block (or only `--case <id>`):

1. download the CSV from the block's `url` into `.cache/mtsamples/` (reused when its hash
   already matches), or take `--csv <path>` with `--offline`;
2. verify the whole-file sha256 against `dataset_sha256`;
3. select the rows whose `sample_name` (stripped: the mirror pads every name with spaces)
   equals the block's `sample_name` AND whose transcription sha256 starts with
   `transcription_sha256_prefix`. `row` is informational only; the mirror holds duplicate
   rows, so several matches are accepted when their transcriptions are byte-identical and
   rejected (`ambiguous_rows`) when they differ;
4. when the variant is listed in `splits.yaml`, verify the transcription's sha256 against
   the manifest entry **before** writing (a listed variant without an entry for the
   document fails too);
5. write the transcription verbatim (`newline=""`, no strip) to a temporary file next to
   `cases/<id>/docs/<doc_id>.txt`, re-hash it and replace the target atomically, so a
   previously fetched file is never altered by a failed run.

Holdout variants (`split: holdout` in `splits.yaml`) are skipped in batch runs and refused
when named with `--case` (AGENTS.md). Any failed check prints
`fetch_mtsamples: <case>: <check> failed` (never the text) and the script exits 1; when the
only failures are downloads (mirror unreachable) it exits 2 so CI can report instead of
block (contract §11). The CSV
columns are the mirror's: `sample_name`, `transcription`.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import sys
import tempfile
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from bridge_check.manifest import (
    holdout_variants,
    inputs_problem,
    is_safe_id,
    read_problem,
    variant_of_path,
    variants_of_path,
    write_problem,
)

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / ".cache" / "mtsamples"
EXIT_UNAVAILABLE = 2  # every failure was a download failure (mirror unreachable)
NAME_COLUMN = "sample_name"
TEXT_COLUMN = "transcription"


class MtsamplesBlock(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    dataset: str
    url: str = Field(pattern=r"^https://")
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    row: int = Field(ge=0)
    sample_name: str = Field(min_length=1)
    transcription_sha256_prefix: str = Field(pattern=r"^[0-9a-f]{8,64}$")
    doc_id: str = Field(pattern=r"^D2-mtsamples-[A-Za-z0-9_-]+$")


class FetchError(Exception):
    """A failed check; `check` names it, the message never contains document text."""

    def __init__(self, check: str, detail: str = "") -> None:
        super().__init__(check)
        self.check = check
        self.detail = detail


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_block(case_yaml: Path) -> MtsamplesBlock | None:
    try:
        with case_yaml.open(encoding="utf-8") as fh:
            data: Any = yaml.safe_load(fh)
    except yaml.YAMLError as exc:  # never print the YAML snippet
        raise FetchError("case_yaml_invalid", f"invalid YAML ({type(exc).__name__})") from None
    if not isinstance(data, dict) or "mtsamples" not in data:
        return None
    try:
        return MtsamplesBlock.model_validate(data["mtsamples"])
    except ValidationError as exc:
        locs = ", ".join(".".join(str(p) for p in e["loc"]) for e in exc.errors())
        raise FetchError("case_yaml_invalid", f"mtsamples block: {locs}") from None


def download(url: str, cache_dir: Path, expected_sha256: str) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / f"{expected_sha256[:12]}.csv"
    if target.is_file() and sha256_file(target) == expected_sha256:
        return target
    try:
        with urllib.request.urlopen(url, timeout=120) as resp:  # noqa: S310 (https enforced)
            data = resp.read()
    except OSError as exc:
        raise FetchError("download", type(exc).__name__) from None
    target.write_bytes(data)
    return target


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def select_transcription(
    csv_path: Path, block: MtsamplesBlock, text_hash: Callable[[str], str] = text_sha256
) -> tuple[str, list[int]]:
    """The transcription text and the indices of the rows that matched."""
    csv.field_size_limit(1 << 28)
    matches: dict[str, list[int]] = {}
    with csv_path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None or not {NAME_COLUMN, TEXT_COLUMN} <= set(reader.fieldnames):
            raise FetchError("csv_columns", f"need {NAME_COLUMN} and {TEXT_COLUMN}")
        for index, row in enumerate(reader):
            if (row.get(NAME_COLUMN) or "").strip() != block.sample_name.strip():
                continue
            text = row.get(TEXT_COLUMN) or ""
            if text_hash(text).startswith(block.transcription_sha256_prefix):
                matches.setdefault(text, []).append(index)
    if not matches:
        raise FetchError("no_matching_row", "sample_name + transcription hash prefix")
    if len(matches) > 1:
        rows = sorted(i for idx in matches.values() for i in idx)
        raise FetchError("ambiguous_rows", f"rows {rows} match but differ")
    text, rows = next(iter(matches.items()))
    return text, rows


def manifest_hash(root: Path, variant_id: str, rel: str) -> str | None:
    """The manifest hash for `rel`; None when the variant is not frozen.

    A frozen variant that lacks an entry for the document is an error: the manifest must
    list every file under `docs/` (freeze_splits.py check (a)).
    """
    manifest = root / "splits.yaml"
    if not manifest.is_file():
        return None
    try:
        data: Any = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise FetchError("manifest_invalid", f"invalid YAML ({type(exc).__name__})") from None
    for variant in (data or {}).get("variants", []) or []:
        if variant.get("variant_id") == variant_id:
            value = variant.get("files", {}).get(rel)
            if value is None:
                raise FetchError("manifest_entry_missing", f"{rel} not listed for {variant_id}")
            return str(value)
    return None


def write_doc(text: str, path: Path, expected_sha256: str) -> None:
    """Write to an exclusively created temp file in the same directory, verify it, then
    replace atomically. The temp name `D2-mtsamples-tmp-*.txt` matches the .gitignore rule
    for MTSamples text, so an interrupted run never leaves committable text behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="D2-mtsamples-tmp-", suffix=".txt", dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        written = sha256_file(tmp)
        if written != expected_sha256:
            raise FetchError("written_sha256", f"temp {written[:8]} != text {expected_sha256[:8]}")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def fetch_case(case_dir: Path, root: Path, *, csv_path: Path | None, cache_dir: Path) -> str | None:
    """Fetch one case; returns a one-line summary or None when the case has no block."""
    problem = read_problem(root, case_dir / "case.yaml")
    if problem is not None:
        raise FetchError("input_refused", problem)
    block = load_block(case_dir / "case.yaml")
    if block is None:
        return None
    source = (
        csv_path if csv_path is not None else download(block.url, cache_dir, block.dataset_sha256)
    )
    actual = sha256_file(source)
    if actual != block.dataset_sha256:
        raise FetchError(
            "dataset_sha256", f"file {actual[:8]} != expected {block.dataset_sha256[:8]}"
        )
    text, rows = select_transcription(source, block)
    rel = f"docs/{block.doc_id}.txt"
    text_sha = text_sha256(text)
    # the frozen hash belongs to the variant the directory really is, not to its name
    actual_variant = variant_of_path(root, case_dir)
    if actual_variant != case_dir.name:
        raise FetchError("case_dir_alias", f"{case_dir.name} resolves to another variant")
    expected = manifest_hash(root, actual_variant, rel)
    if expected is not None and text_sha != expected:
        raise FetchError("manifest_sha256", f"text {text_sha[:8]} != splits.yaml {expected[:8]}")
    target = case_dir / rel
    problem = write_problem(root, target, replace_existing_doc=True)
    if problem is not None:
        raise FetchError("output_refused", problem)
    # the file actually written (docs/ may be a link) must belong to the hashed variant
    destination = target.parent.resolve() / target.name
    if variants_of_path(root, destination) != {actual_variant}:
        raise FetchError("destination_alias", f"{rel} resolves outside {actual_variant}")
    write_doc(text, target, text_sha)
    written = text_sha
    note = f"row {block.row}" if block.row in rows else f"rows {rows} (case.yaml says {block.row})"
    frozen = "matches splits.yaml" if expected is not None else "not in splits.yaml"
    return f"{rel} written ({len(text)} chars, sha256 {written[:8]}, {note}, {frozen})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--case", default=None, help="only this variant id")
    parser.add_argument("--offline", action="store_true", help="use --csv, do not download")
    parser.add_argument(
        "--csv", type=Path, default=None, help="an already downloaded mtsamples.csv"
    )
    parser.add_argument("--root", type=Path, default=ROOT, help="repo root (cases/ lives here)")
    parser.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    args = parser.parse_args(argv)
    if args.offline and args.csv is None:
        parser.error("--offline needs --csv")

    root: Path = args.root.resolve()
    cases_dir = root / "cases"
    holdout = holdout_variants(root)
    if args.case and not is_safe_id(args.case):
        print("fetch_mtsamples: --case must be a plain variant id", file=sys.stderr)
        return 1
    if args.case and args.case in holdout:
        print(f"fetch_mtsamples: {args.case}: holdout variant, refused", file=sys.stderr)
        return 1
    if args.csv is not None:
        problem = inputs_problem(root, {"--csv": args.csv})
        if problem is not None:
            print(f"fetch_mtsamples: {problem}", file=sys.stderr)
            return 1
    case_dirs = (
        [cases_dir / args.case]
        if args.case
        else sorted(p for p in cases_dir.glob("*") if p.is_dir())
    )
    failures = 0
    fetched = 0
    unavailable = 0
    for case_dir in case_dirs:
        if case_dir.name in holdout:
            print(f"fetch_mtsamples: {case_dir.name}: skipped (holdout)")
            continue
        problem = read_problem(root, case_dir)  # a dev-named link into a holdout directory
        if problem is not None:
            print(f"fetch_mtsamples: {problem}", file=sys.stderr)
            failures += 1
            continue
        if not (case_dir / "case.yaml").is_file():
            print(f"fetch_mtsamples: {case_dir.name}: case.yaml missing", file=sys.stderr)
            failures += 1
            continue
        try:
            summary = fetch_case(case_dir, root, csv_path=args.csv, cache_dir=args.cache_dir)
        except FetchError as exc:
            detail = f" ({exc.detail})" if exc.detail else ""
            print(f"fetch_mtsamples: {case_dir.name}: {exc.check} failed{detail}", file=sys.stderr)
            failures += 1
            unavailable += exc.check == "download"
            continue
        if summary is not None:
            fetched += 1
            print(f"fetch_mtsamples: {case_dir.name}: {summary}")
    print(f"fetch_mtsamples: {fetched} document(s) written, {failures} failure(s)")
    if failures and failures == unavailable:
        return EXIT_UNAVAILABLE  # mirror unreachable: CI reports, does not block
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
