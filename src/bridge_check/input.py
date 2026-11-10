"""Case input visible to the system: `<case dir>/input.yaml` and `docs/` (contract §7.1).

Documents are read byte-exactly (`text.read_doc`: UTF-8, `newline=""`). `input_hash`
identifies the input version: the parsed `input.yaml` and the sha256 of every document.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, field_validator

from bridge_check.enums import SAFE_ID_PATTERN, DocRole
from bridge_check.manifest import CHECKOUT_ROOT, holdout_variants, is_safe_id, read_problem
from bridge_check.text import read_doc, sha256_hex

INPUT_NAME = "input.yaml"
DOCS_DIR = "docs"


class InputError(Exception):
    """The case input cannot be used.

    Messages use fixed file names (`input.yaml`, `docs/`), schema field names and list
    indices only: never the case path, a directory or file name taken from disk, a key or
    value from the file, or document text. A case directory may be named after a person.
    """


def canonical_json(obj: Any) -> str:
    """The one JSON serialization used for hashing (contract §11)."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_canonical(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TargetCourse(_Model):
    drug: str
    start: date


class PrimaryPatient(_Model):
    patient_id: str
    name: str
    dob: date


class DocumentRef(_Model):
    doc_id: str
    role: DocRole

    @field_validator("doc_id")
    @classmethod
    def _safe(cls, v: str) -> str:
        if not is_safe_id(v):
            raise ValueError(f"doc_id must match {SAFE_ID_PATTERN}")
        return v


class CaseInput(_Model):
    variant_id: str
    assessment_date: date
    target_course: TargetCourse
    primary_patient: PrimaryPatient
    documents: list[DocumentRef]

    @field_validator("variant_id")
    @classmethod
    def _safe(cls, v: str) -> str:
        if not is_safe_id(v):
            raise ValueError(f"variant_id must match {SAFE_ID_PATTERN}")
        return v

    @field_validator("documents")
    @classmethod
    def _unique(cls, v: list[DocumentRef]) -> list[DocumentRef]:
        if not v:
            raise ValueError("at least one document is required")
        ids = [d.doc_id for d in v]
        if len(set(ids)) != len(ids):
            raise ValueError("doc_id values must be unique")
        return v


@dataclass(frozen=True)
class LoadedCase:
    """A case input with its documents read."""

    case_dir: Path
    input: CaseInput
    texts: dict[str, str]
    doc_sha256: dict[str, str]

    @property
    def case_id(self) -> str:
        return self.input.variant_id

    @property
    def input_hash(self) -> str:
        return sha256_canonical(
            {"input": self.input.model_dump(mode="json"), "doc_sha256": self.doc_sha256}
        )


def resolve_case_dir(case: str, root: Path = CHECKOUT_ROOT) -> Path:
    """`case` is a case directory, or a variant id under `<root>/cases/`."""
    path = Path(case)
    if path.is_dir():
        return path
    candidate = root / "cases" / case
    if is_safe_id(case) and candidate.is_dir():
        return candidate
    raise InputError("case directory not found")


UNRESOLVED_PREFIX = "unresolved-"


def case_id_of(case: str, root: Path = CHECKOUT_ROOT) -> str:
    """The `variant_id` from the case's `input.yaml`.

    When that file cannot be read or validated, the id is `unresolved-<sha8>` of the
    resolved case path: stable, so `history` finds the run again, and free of the path
    itself, which may contain a name.
    """
    try:
        return load_input(resolve_case_dir(case, root), root).variant_id
    except InputError:
        resolved = str(Path(case).expanduser().resolve())
        return UNRESOLVED_PREFIX + hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:8]


def _refuse_holdout(root: Path, path: Path, what: str) -> None:
    """Every exact path is checked, as written and as it resolves, right before it is
    opened: a link anywhere along the way into a holdout variant is refused here."""
    if read_problem(root, path) is not None:
        raise InputError(f"{what} lies in a holdout variant; it is never read here")


def load_input(case_dir: Path, root: Path = CHECKOUT_ROOT) -> CaseInput:
    """Read `input.yaml`; the directory and the file are guarded before the read, so every
    caller (`case_id_of`, `load_case`) refuses a holdout path without opening it."""
    _refuse_holdout(root, case_dir, "case directory")
    _refuse_holdout(root, case_dir / INPUT_NAME, INPUT_NAME)
    path = case_dir / INPUT_NAME
    if not path.is_file():
        raise InputError(f"{INPUT_NAME} not found")
    try:
        data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        return CaseInput.model_validate(data)
    except yaml.YAMLError as exc:
        raise InputError(f"{INPUT_NAME}: not valid YAML ({type(exc).__name__})") from None
    except ValueError as exc:
        fields = sorted({_safe_loc(e["loc"]) for e in _errors(exc)})
        raise InputError(f"{INPUT_NAME}: invalid fields: {', '.join(fields) or '?'}") from None


def _errors(exc: ValueError) -> list[dict[str, Any]]:
    errors = getattr(exc, "errors", None)
    return list(errors()) if callable(errors) else []


_KNOWN_KEYS = frozenset(
    name
    for model in (CaseInput, TargetCourse, PrimaryPatient, DocumentRef)
    for name in model.model_fields
)


def _safe_loc(loc: tuple[int | str, ...]) -> str:
    """An error location with only indices and schema field names; anything else (an
    unknown key the file used, which could be any text) is shown as `?`."""
    return ".".join(str(p) if isinstance(p, int) or p in _KNOWN_KEYS else "?" for p in loc)


def load_case(case_dir: Path, root: Path = CHECKOUT_ROOT) -> LoadedCase:
    """Read `input.yaml` and every listed document. Holdout variants are refused by
    variant id and by every path about to be opened."""
    inp = load_input(case_dir, root)
    if inp.variant_id in holdout_variants(root):
        raise InputError("holdout variant; it is never run here")
    texts: dict[str, str] = {}
    hashes: dict[str, str] = {}
    for index, ref in enumerate(inp.documents):
        path = case_dir / DOCS_DIR / f"{ref.doc_id}.txt"
        _refuse_holdout(root, path, f"documents.{index}")
        if not path.is_file():
            raise InputError(f"document file missing for documents.{index}")
        text = read_doc(path)
        texts[ref.doc_id] = text
        hashes[ref.doc_id] = sha256_hex(text)
    return LoadedCase(case_dir=case_dir, input=inp, texts=texts, doc_sha256=hashes)
