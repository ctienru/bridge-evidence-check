"""Holdout lookup and path guards for the data-line tools.

AGENTS.md: never read or run variants marked `holdout`, never write gold. Every tool runs
`read_problem` on each file it is about to read and `write_problem` on each file it is
about to create, both on the **resolved** path (symlinks and `..` followed), before any
read, write or API call. Validation of the manifest itself is `scripts/freeze_splits.py`.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Any

import yaml

from bridge_check.enums import SAFE_ID_PATTERN

MANIFEST_NAME = "splits.yaml"
_SAFE_ID = re.compile(SAFE_ID_PATTERN)


class UnreadableYaml(ValueError):
    """A YAML file that does not parse. The message names the file only: a parser error
    would quote the offending line, and case metadata may hold document excerpts."""


def safe_yaml(path: Path) -> Any:
    """`yaml.safe_load` of `path` with the parser's message dropped (`UnreadableYaml`)."""
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        raise UnreadableYaml(f"{path.name}: not valid YAML") from None


def is_safe_id(value: str) -> bool:
    """A variant or document id is one path segment: no `/`, `.`, leading `-` or spaces."""
    return _SAFE_ID.match(value) is not None


def holdout_variants(root: Path) -> frozenset[str]:
    """variant_ids with `split: holdout`; empty when the manifest is missing or empty."""
    path = root / MANIFEST_NAME
    if not path.is_file():
        return frozenset()
    data: Any = safe_yaml(path)
    variants = (data or {}).get("variants") or []
    return frozenset(
        str(v["variant_id"])
        for v in variants
        if isinstance(v, dict) and v.get("split") == "holdout" and "variant_id" in v
    )


def manifest_variants(root: Path) -> list[dict[str, Any]]:
    """Every row of `splits.yaml` in manifest order (raw mappings; validation is
    `scripts/freeze_splits.py`). Empty when the manifest is missing."""
    path = root / MANIFEST_NAME
    if not path.is_file():
        return []
    data: Any = safe_yaml(path)
    variants = (data or {}).get("variants") or []
    return [dict(v) for v in variants if isinstance(v, dict)]


def dev_variants(root: Path) -> list[dict[str, Any]]:
    """The `split: dev` rows only; a holdout row is never returned, so nothing that
    iterates this list can touch a holdout directory."""
    return [v for v in manifest_variants(root) if v.get("split") == "dev"]


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
    found |= _same_directory_as_holdout(root, path)
    return found


def _same_directory_as_holdout(root: Path, path: Path) -> set[str]:
    """Holdout variants whose directory, by file-system identity, contains the resolved
    `path`. Catches a holdout directory that is itself a link elsewhere and a dev-named
    link to that same place, which neither the lexical nor the resolved string check sees,
    and spellings that differ only in case on a case-insensitive file system."""
    try:
        resolved = path.resolve()
    except OSError:
        return set()
    found: set[str] = set()
    for vid in holdout_variants(root):
        target = root / "cases" / vid
        if not target.is_dir():
            continue
        for ancestor in (resolved, *resolved.parents):
            if not ancestor.exists():
                continue
            try:
                if os.path.samefile(ancestor, target):
                    found.add(vid)
                    break
            except OSError:
                continue
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


def read_problem(root: Path, path: Path, *, allow_holdout: bool = False) -> str | None:
    """Why `path` may not be read: as written or resolved, it lies in a holdout variant;
    or the regular file it resolves to (through any symbolic links) has more than one
    hard link, so its bytes may belong to a holdout name no path check can see.

    `allow_holdout` is passed only by `bridge eval --split holdout`, which has already
    refused a data root inside this checkout; the hard-link check still applies."""
    if not allow_holdout:
        holdout = holdout_variants(root)
        for variant in sorted(variants_of_path(root, path)):
            if variant in holdout:
                return f"{path.name}: lies in holdout variant {variant}, refused"
    try:
        st = os.stat(path)  # follows links: the inode that would actually be read
    except OSError:
        return None
    if stat.S_ISREG(st.st_mode) and st.st_nlink > 1:
        return f"{path.name}: resolves to a file with {st.st_nlink} hard links, refused"
    return None


def external_holdout_problem(path: Path, root: Path = CHECKOUT_ROOT) -> str | None:
    """Why `check` or `history` must not open `path` (a case directory or a file in it),
    judged as written and as resolved: a directory on its way is named as a holdout variant
    (compared case-insensitively) by this checkout's manifest, by `root`'s, or by a
    `splits.yaml` in any directory above it; or it is, by file-system identity, a holdout
    variant directory `<manifest dir>/cases/<id>` or `<manifest dir>/holdout/<id>` (the
    private repository keeps its holdout cases under `holdout/`). Only manifests are read,
    never `path` itself. A renamed copy outside every manifest cannot be recognised without
    opening it; that is the documented limit of this guard."""
    names: set[str] = set()
    places: list[Path] = []
    for base in (CHECKOUT_ROOT, root):
        ids = holdout_variants(base)
        names |= ids
        places += [base / "cases" / v for v in ids]
    spots = {path.resolve(), Path(os.path.normpath(os.path.join(os.getcwd(), path)))}
    for spot in spots:
        for ancestor in spot.parents:
            if (ancestor / MANIFEST_NAME).is_file():
                try:
                    ids = holdout_variants(ancestor)
                except UnreadableYaml:
                    return f"{path.name}: unreadable {MANIFEST_NAME} above the case, refused"
                names |= ids
                places += [ancestor / sub / v for v in ids for sub in ("cases", "holdout")]
    folded = {n.casefold() for n in names}
    chains = [(spot, *spot.parents) for spot in spots]
    if any(d.name.casefold() in folded for chain in chains for d in chain):
        return f"{path.name}: lies in a directory named as a holdout variant, refused"
    existing = [p for p in places if p.is_dir()]
    for chain in chains:
        for d in chain:
            if not d.exists():
                continue
            for place in existing:
                try:
                    if os.path.samefile(d, place):
                        return f"{path.name}: lies in a holdout variant directory, refused"
                except OSError:
                    continue
    return None


def containment_problem(root: Path, case_dir: Path, path: Path) -> str | None:
    """`bridge eval --split holdout` only: the case directory must be the real directory
    `<root>/cases/<name>` (not a link), and `path` must resolve inside it, so a holdout
    name can never lead to another variant's files. The hard-link check of `read_problem`
    is applied separately."""
    # anchored on the data root, which the caller resolved once: a link at `cases/`, at
    # the case directory or at any file beneath it resolves elsewhere and is refused
    expected = root.resolve() / "cases" / case_dir.name
    if case_dir.is_symlink() or case_dir.resolve() != expected:
        return f"{case_dir.name}: case directory is a link or lies elsewhere, refused"
    try:
        path.resolve().relative_to(expected)
    except ValueError:
        return f"{path.name}: resolves outside its case directory, refused"
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
