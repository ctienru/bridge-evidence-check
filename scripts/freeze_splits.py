"""Check the frozen-split manifest (`splits.yaml`).

Manifest format (version 1)::

    version: 1
    variants:
      - case_id: case-01
        variant_id: case-01
        split: dev            # dev | holdout
        frozen_at: 2026-11-20
        gold_version: 1
        files:
          input.yaml: <sha256>
          docs/D1-referral.txt: <sha256>
          docs/D2-mtsamples-4985.txt: <sha256>
          expected.json: <sha256>

`--check` does three things (planning doc 13 §11):

(a) require `input.yaml`, `expected.json` and every file under `docs/` to be listed, then
    recompute the sha256 of every listed file (relative to `cases/<variant_id>/`) and
    compare; a missing file is an error, except MTSamples documents
    (`docs/D2-mtsamples-*.txt`), which are downloaded at runtime and report
    "run scripts/fetch_mtsamples.py first";
(b) with `--base <git-ref>`, load the manifest from that ref (`git show <ref>:splits.yaml`)
    and compare: variants may only be added; an existing variant may not be removed and
    its `split` may not change; its file hashes may change only if `gold_version`
    increased and only the `expected.json` hash changed. A missing, empty or all-zero
    ref runs in bootstrap mode (no comparison);
(c) for every listed `expected.json`, a fact whose `doc_id` starts with `D2-mtsamples`
    must carry `quote_sha256` and must not carry `quote` (MTSamples text is never
    committed).

Exit code 0 when everything passes, 1 otherwise. Output never includes document text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

DEFAULT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_NAME = "splits.yaml"
ZERO_SHA = "0" * 40
MTSAMPLES_DOC = re.compile(r"^docs/D2-mtsamples-[^/]+\.txt$")
MTSAMPLES_DOC_ID_PREFIX = "D2-mtsamples"
FETCH_HINT = "run scripts/fetch_mtsamples.py first"
SHA256_HEX = r"^[0-9a-f]{64}$"
# A variant_id is a single directory name under cases/: no separators, no dots, no leading dash.
SAFE_ID = r"^[A-Za-z0-9][A-Za-z0-9_-]*$"
REQUIRED_FILES: tuple[str, ...] = ("input.yaml", "expected.json")
# git stderr fragments that mean "no manifest at that ref" (bootstrap), as opposed to a
# broken repository or a permission problem (which must fail).
_MISSING_BASE_MARKERS: tuple[str, ...] = (
    "invalid object name",
    "bad revision",
    "unknown revision",
    "does not exist in",
    "exists on disk, but not in",
    "not a valid object name",
)


class Variant(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    case_id: str = Field(pattern=SAFE_ID)
    variant_id: str = Field(pattern=SAFE_ID)
    split: Literal["dev", "holdout"]
    frozen_at: str = Field(min_length=1)
    gold_version: int = Field(ge=1)
    files: dict[str, str] = Field(min_length=1)


class Manifest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    version: Literal[1]
    variants: list[Variant]

    def by_id(self) -> dict[str, Variant]:
        return {v.variant_id: v for v in self.variants}


def _coerce_dates(data: Any) -> Any:
    """YAML parses bare dates into `date`; the manifest stores them as ISO strings."""
    if isinstance(data, dict):
        out: dict[str, Any] = {}
        for key, value in data.items():
            if key == "frozen_at" and hasattr(value, "isoformat"):
                out[key] = value.isoformat()
            else:
                out[key] = _coerce_dates(value)
        return out
    if isinstance(data, list):
        return [_coerce_dates(item) for item in data]
    return data


def parse_manifest(text: str, label: str) -> Manifest | list[str]:
    """Parse manifest text; return the Manifest or a list of problems."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return [f"{label}: invalid YAML: {exc}"]
    try:
        manifest = Manifest.model_validate(_coerce_dates(data))
    except ValidationError as exc:
        return [
            f"{label}: {'.'.join(str(p) for p in err['loc']) or '<root>'}: {err['msg']}"
            for err in exc.errors()
        ]
    problems: list[str] = []
    seen: set[str] = set()
    for variant in manifest.variants:
        if variant.variant_id in seen:
            problems.append(f"{label}: duplicate variant_id {variant.variant_id!r}")
        seen.add(variant.variant_id)
        for rel, digest in variant.files.items():
            if not re.match(SHA256_HEX, digest):
                problems.append(f"{label}: {variant.variant_id}: {rel}: hash is not sha256 hex")
            if rel.startswith("/") or ".." in Path(rel).parts:
                problems.append(f"{label}: {variant.variant_id}: {rel}: path must be relative")
    return problems or manifest


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --- (a) file hashes ------------------------------------------------------------------


def check_coverage(manifest: Manifest, root: Path) -> list[str]:
    """Every variant must freeze input.yaml, expected.json and every file under docs/."""
    problems: list[str] = []
    for variant in manifest.variants:
        for required in REQUIRED_FILES:
            if required not in variant.files:
                problems.append(f"{variant.variant_id}: {required} is not listed in files")
        docs_dir = root / "cases" / variant.variant_id / "docs"
        if docs_dir.is_dir():
            on_disk = sorted(
                p.relative_to(docs_dir.parent).as_posix()
                for p in docs_dir.rglob("*")
                if p.is_file()
            )
            for rel in on_disk:
                if rel not in variant.files:
                    problems.append(
                        f"{variant.variant_id}: {rel} exists but is not listed in files"
                    )
    return problems


def check_hashes(manifest: Manifest, root: Path) -> list[str]:
    problems: list[str] = []
    for variant in manifest.variants:
        case_dir = root / "cases" / variant.variant_id
        for rel, expected in variant.files.items():
            path = case_dir / rel
            if not path.is_file():
                if MTSAMPLES_DOC.match(rel):
                    problems.append(f"{variant.variant_id}: {rel}: missing; {FETCH_HINT}")
                else:
                    problems.append(f"{variant.variant_id}: {rel}: file missing")
                continue
            actual = sha256_file(path)
            if actual != expected:
                problems.append(
                    f"{variant.variant_id}: {rel}: sha256 mismatch "
                    f"(manifest {expected[:8]}, file {actual[:8]})"
                )
    return problems


# --- (b) comparison against the base ref ------------------------------------------------


def load_base_manifest(base: str | None, root: Path) -> tuple[Manifest | None, list[str]]:
    """Return (base manifest, problems). `None` with no problems means bootstrap mode."""
    if base is None or base.strip() == "" or base == ZERO_SHA:
        return None, []
    result = subprocess.run(
        ["git", "show", f"{base}:{MANIFEST_NAME}"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if any(marker in stderr for marker in _MISSING_BASE_MARKERS):
            # Ref or file not present at that ref: first manifest on this branch.
            return None, []
        return None, [f"cannot read {MANIFEST_NAME} from {base!r}: {stderr or 'git error'}"]
    parsed = parse_manifest(result.stdout, f"{base}:{MANIFEST_NAME}")
    if isinstance(parsed, list):
        return None, parsed
    return parsed, []


def compare_with_base(current: Manifest, base: Manifest) -> list[str]:
    problems: list[str] = []
    current_by_id = current.by_id()
    for variant_id, old in base.by_id().items():
        new = current_by_id.get(variant_id)
        if new is None:
            problems.append(f"{variant_id}: frozen variant removed")
            continue
        if new.split != old.split:
            problems.append(f"{variant_id}: split changed {old.split} -> {new.split}")
        if new.case_id != old.case_id:
            problems.append(f"{variant_id}: case_id changed")
        if new.gold_version < old.gold_version:
            problems.append(f"{variant_id}: gold_version decreased")
        if set(old.files) != set(new.files):
            differing = sorted(set(old.files) ^ set(new.files))
            problems.append(f"{variant_id}: frozen file list changed ({', '.join(differing)})")
            continue
        changed = sorted(rel for rel in old.files if old.files[rel] != new.files[rel])
        if not changed:
            continue
        if changed != ["expected.json"]:
            problems.append(
                f"{variant_id}: frozen file hash changed without a new gold: {', '.join(changed)}"
            )
            continue
        if new.gold_version <= old.gold_version:
            problems.append(
                f"{variant_id}: expected.json changed but gold_version did not increase"
            )
    return problems


# --- (c) MTSamples quotes must be externalized ------------------------------------------


def check_gold_quotes(manifest: Manifest, root: Path) -> list[str]:
    problems: list[str] = []
    for variant in manifest.variants:
        for rel in variant.files:
            if Path(rel).name != "expected.json":
                continue
            path = root / "cases" / variant.variant_id / rel
            if not path.is_file():
                continue  # reported by check_hashes
            try:
                gold = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                problems.append(f"{variant.variant_id}: {rel}: invalid JSON: {exc.msg}")
                continue
            facts = gold.get("facts", []) if isinstance(gold, dict) else []
            if not isinstance(facts, list):
                problems.append(f"{variant.variant_id}: {rel}: 'facts' must be a list")
                continue
            for index, fact in enumerate(facts):
                if not isinstance(fact, dict):
                    continue
                doc_id = fact.get("doc_id")
                if not isinstance(doc_id, str) or not doc_id.startswith(MTSAMPLES_DOC_ID_PREFIX):
                    continue
                where = f"{variant.variant_id}: {rel}: facts[{index}]"
                if "quote" in fact:
                    problems.append(f"{where}: MTSamples fact must not contain 'quote'")
                if not isinstance(fact.get("quote_sha256"), str):
                    problems.append(f"{where}: MTSamples fact must contain 'quote_sha256'")
    return problems


# --- entry point ------------------------------------------------------------------------


def _display(path: Path, root: Path) -> str:
    """`path` relative to the repo root when it lies inside it (no home directory in logs)."""
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path)


def check(root: Path, manifest_path: Path, base: str | None) -> int:
    try:
        text = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"freeze_splits: cannot read {manifest_path}: {exc}", file=sys.stderr)
        return 1
    parsed = parse_manifest(text, str(manifest_path))
    if isinstance(parsed, list):
        for problem in parsed:
            print(f"freeze_splits: {problem}", file=sys.stderr)
        return 1
    manifest = parsed

    problems = check_coverage(manifest, root)
    problems.extend(check_hashes(manifest, root))
    base_manifest, base_problems = load_base_manifest(base, root)
    problems.extend(base_problems)
    if base_manifest is None and not base_problems:
        print("freeze_splits: bootstrap mode (no base manifest to compare against)")
    elif base_manifest is not None:
        problems.extend(compare_with_base(manifest, base_manifest))
    problems.extend(check_gold_quotes(manifest, root))

    for problem in problems:
        print(f"freeze_splits: {problem}", file=sys.stderr)
    if problems:
        return 1
    splits = {s: sum(1 for v in manifest.variants if v.split == s) for s in ("dev", "holdout")}
    print(
        f"freeze_splits: {_display(manifest_path, root)} OK ({len(manifest.variants)} variants: "
        f"{splits['dev']} dev, {splits['holdout']} holdout)"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the frozen-split manifest.")
    parser.add_argument("--check", action="store_true", required=True)
    parser.add_argument(
        "--root", type=Path, default=DEFAULT_ROOT, help="repo root (cases/ lives here)"
    )
    parser.add_argument(
        "--manifest", type=Path, default=None, help="defaults to <root>/splits.yaml"
    )
    parser.add_argument("--base", default=None, help="git ref holding the base splits.yaml")
    args = parser.parse_args(argv)
    root: Path = args.root.resolve()
    manifest_path: Path = args.manifest if args.manifest is not None else root / MANIFEST_NAME
    return check(root, manifest_path, args.base)


if __name__ == "__main__":
    raise SystemExit(main())
