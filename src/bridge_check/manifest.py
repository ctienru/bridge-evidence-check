"""Holdout lookup and path guards for the data-line tools.

AGENTS.md: never read or run variants marked `holdout`, never write gold. Every tool runs
`read_problem` on each file it is about to read and `write_problem` on each file it is
about to create, both on the **resolved** path (symlinks and `..` followed), before any
read, write or API call. Validation of the manifest itself is `scripts/freeze_splits.py`.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from bridge_check.enums import SAFE_ID_PATTERN

MANIFEST_NAME = "splits.yaml"
_SAFE_ID = re.compile(SAFE_ID_PATTERN)


def is_safe_id(value: str) -> bool:
    """A variant or document id is one path segment: no `/`, `.`, leading `-` or spaces."""
    return _SAFE_ID.match(value) is not None


def holdout_variants(root: Path) -> frozenset[str]:
    """variant_ids with `split: holdout`; empty when the manifest is missing or empty."""
    path = root / MANIFEST_NAME
    if not path.is_file():
        return frozenset()
    data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    variants = (data or {}).get("variants") or []
    return frozenset(
        str(v["variant_id"])
        for v in variants
        if isinstance(v, dict) and v.get("split") == "holdout" and "variant_id" in v
    )


def variant_of_path(root: Path, path: Path) -> str | None:
    """The `<variant_id>` of the **resolved** path under `<root>/cases/`, else None."""
    try:
        rel = path.resolve().relative_to((root / "cases").resolve())
    except ValueError:
        return None
    return rel.parts[0] if rel.parts else None


def variants_of_path(root: Path, path: Path) -> set[str]:
    """Variant ids a path touches, both as written (lexically, `..` collapsed but links
    not followed) and after resolving symlinks. A holdout directory linked from outside the
    checkout, or a dev-named link into a holdout directory, is caught either way."""
    found: set[str] = set()
    resolved = variant_of_path(root, path)
    if resolved is not None:
        found.add(resolved)
    cases = (root / "cases").resolve()
    lexical = Path(os.path.normpath(os.path.join(os.getcwd(), path)))
    try:
        rel = lexical.relative_to(cases)
    except ValueError:
        rel = None
    if rel is not None and rel.parts:
        found.add(rel.parts[0])
    return found


def is_holdout_path(root: Path, path: Path) -> bool:
    variant = variant_of_path(root, path)
    return variant is not None and variant in holdout_variants(root)


CHECKOUT_ROOT = Path(__file__).resolve().parent.parent.parent
"""The public checkout this code runs from; private outputs are checked against it
regardless of any `--root` argument, which only relocates `cases/`."""

# Files only the annotator writes (AGENTS.md); no tool may use them as an output path.
ANNOTATOR_FILES: frozenset[str] = frozenset(
    {"expected.json", "blind_draft.json", "adjudication.jsonl", "input.yaml", "case.yaml"}
)
PROTECTED_FILES: frozenset[str] = ANNOTATOR_FILES | {MANIFEST_NAME}


def _within(already_resolved: Path, directory: Path) -> bool:
    """`is_inside` for a landing spot whose links must NOT be followed again.

    Besides the string comparison, every existing ancestor of the spot is compared with
    `directory` by identity (`os.path.samefile`), so a spelling that names the same
    directory differently (case-insensitive file systems, `BRIDGE-EVIDENCE-CHECK`) is
    still recognised as inside the checkout, including for output subdirectories that do
    not exist yet.
    """
    target = directory.resolve()
    try:
        already_resolved.relative_to(target)
        return True
    except ValueError:
        pass
    for ancestor in (already_resolved, *already_resolved.parents):
        try:
            if ancestor.exists() and os.path.samefile(ancestor, target):
                return True
        except OSError:
            continue
    return False


def is_inside(path: Path, directory: Path) -> bool:
    try:
        path.resolve().relative_to(directory.resolve())
    except ValueError:
        return False
    return True


def read_problem(root: Path, path: Path) -> str | None:
    """Why `path` may not be read: as written or resolved, it lies in a holdout variant."""
    holdout = holdout_variants(root)
    for variant in sorted(variants_of_path(root, path)):
        if variant in holdout:
            return f"{path.name}: lies in holdout variant {variant}, refused"
    return None


def inputs_problem(root: Path, inputs: dict[str, Path]) -> str | None:
    """`read_problem` over every named input file (prompts, guides, specs, CSVs, ...)."""
    for name, path in inputs.items():
        problem = read_problem(root, path)
        if problem is not None:
            return f"{name}: {problem}"
    return None


def write_problem(
    root: Path,
    path: Path,
    *,
    public_roots: list[Path] | None = None,
    replace_existing_doc: bool = False,
) -> str | None:
    """Why `path` may not be written by a tool, judged on the resolved path.

    Refused: a holdout variant, an annotator-owned file or the manifest (by resolved
    name), an existing document under `cases/*/docs/` (frozen input) unless
    `replace_existing_doc` is set (only `fetch_mtsamples.py`, which verifies the hash
    first), and, when `public_roots` is given (private outputs), anything inside a public
    checkout.
    """
    resolved = path.resolve()
    problem = read_problem(root, path)  # lexical and resolved
    if problem is not None:
        return problem
    if resolved.name in PROTECTED_FILES:
        return f"{path.name}: annotator-owned or manifest file, refused as output"
    variant = variant_of_path(root, resolved)
    if (
        variant is not None
        and resolved.parent.name == "docs"
        and resolved.exists()
        and not replace_existing_doc
    ):
        return f"{path.name}: existing case document, refused as output"
    if public_roots is not None:
        # three places the write could land: the resolved file, the entry `os.replace()`
        # would create (a symlink is replaced in its own directory), and the lexical path
        landing = {
            resolved,
            path.parent.resolve() / path.name,
            Path(os.path.normpath(os.path.join(os.getcwd(), path))),
        }
        if any(_within(spot, r) for spot in landing for r in public_roots):
            return f"{path.name}: private output inside the public checkout, refused"
    return None


def outputs_problem(
    root: Path, private: dict[str, Path], public: dict[str, Path], public_roots: list[Path]
) -> str | None:
    """Check every planned output before an API call: each path individually, then that
    no two resolve to the same file."""
    for name, path in private.items():
        problem = write_problem(root, path, public_roots=public_roots)
        if problem is not None:
            return f"{name}: {problem}"
    for name, path in public.items():
        problem = write_problem(root, path)
        if problem is not None:
            return f"{name}: {problem}"
    resolved = {name: path.resolve() for name, path in {**private, **public}.items()}
    names = list(resolved)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            if resolved[a] == resolved[b]:
                return f"{a} and {b} are the same file"
    return None
