"""Hidden case configuration as the evaluation reads it (contract §7.1).

`cases/<variant_id>/case.yaml` is written by the annotator and never read by `bridge
check`; only the evaluation reads it, and only these keys: `case_id`, `source`,
`documents[].doc_origin`, `traps` and `tests`. Everything is reduced to ids and enum values
(`SAFE_ID_PATTERN`); any other value is dropped and counted in `invalid_ids`, so nothing
free-text can reach a report through this module. A file that does not parse raises
`manifest.UnreadableYaml`, whose message names the file and never quotes a line.

Rule fixtures (`fixtures/synthetic/rules/<name>/`) carry their trap ids in a sidecar
`meta.yaml` (`trap_ids: [...]`) because their `input.yaml` is a strict system input.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bridge_check.enums import CLAIM_IDS, CONDITION_IDS
from bridge_check.manifest import is_safe_id, safe_yaml

_FIXTURE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
"""A rules-fixture directory name: one path segment; dots allowed (`bmi-29.9-vs-30.1`)."""

CASE_META_NAME = "case.yaml"
FIXTURE_META_NAME = "meta.yaml"

SECTIONS: tuple[str, ...] = ("mtsamples", "case_report", "authored", "dirty")
"""Report sections (planning section 3.1): real text from MTSamples, real text from a
published case report, authored documents, and dirty-ladder variants (none public yet)."""

DOC_ORIGINS: tuple[str, ...] = ("mtsamples", "case_report", "authored")
SCORED_IDS: frozenset[str] = frozenset(CONDITION_IDS) | frozenset(CLAIM_IDS)


@dataclass(frozen=True)
class CaseMeta:
    variant_id: str
    case_id: str
    source: str | None
    doc_origins: dict[str, str]
    traps: tuple[str, ...]
    tests: tuple[str, ...]
    invalid_ids: int
    section: str
    ladder_level: str | None = None
    """Ladder membership (`ladder.level` in `case.yaml`), recorded whatever the level."""

    @property
    def dirty(self) -> bool:
        """A dirtied ladder level (L1 and up): the `dirty` report section and the
        `ladder_level` coverage column. L0 is the clean base; it is grouped by document
        origin and counts as an integrated case."""
        return self.section == "dirty"


def _ids(values: Any, allowed: Iterable[str] | None = None) -> tuple[tuple[str, ...], int]:
    """Validated ids from a YAML list; the second element counts what was dropped."""
    if not isinstance(values, list):
        return (), 0 if values is None else 1
    keep: list[str] = []
    dropped = 0
    allowed_set = set(allowed) if allowed is not None else None
    for v in values:
        # condition ids carry dots (`bmi_path_b.htn`): membership in `allowed` is the check
        ok = isinstance(v, str) and (v in allowed_set if allowed_set is not None else is_safe_id(v))
        if ok and v not in keep:
            keep.append(str(v))
        elif not ok:
            dropped += 1
    return tuple(keep), dropped


def section_of(doc_origins: dict[str, str], dirty: bool = False) -> str:
    if dirty:
        return "dirty"
    origins = set(doc_origins.values())
    if "mtsamples" in origins:
        return "mtsamples"
    if "case_report" in origins:
        return "case_report"
    return "authored"


def load_case_meta(case_dir: Path, variant_id: str) -> CaseMeta:
    """Read `case.yaml` of a dev variant; a missing or empty file yields no traps and no
    tests (the variant is still scored, it just covers nothing)."""
    path = case_dir / CASE_META_NAME
    data: Any = safe_yaml(path) if path.is_file() else None  # parser text never surfaces
    data = data if isinstance(data, dict) else {}
    invalid = 0
    case_id = data.get("case_id")
    if not (isinstance(case_id, str) and is_safe_id(case_id)):
        case_id, invalid = variant_id, invalid + (case_id is not None)
    source = data.get("source")
    if source is not None and not (isinstance(source, str) and is_safe_id(source)):
        source, invalid = None, invalid + 1
    doc_origins: dict[str, str] = {}
    for d in data.get("documents") or []:
        if not isinstance(d, dict):
            invalid += 1
            continue
        doc_id, origin = d.get("doc_id"), d.get("doc_origin")
        if isinstance(doc_id, str) and is_safe_id(doc_id) and origin in DOC_ORIGINS:
            doc_origins[doc_id] = str(origin)
        else:
            invalid += 1
    traps, dropped = _ids(data.get("traps"))
    invalid += dropped
    tests, dropped = _ids(data.get("tests"), SCORED_IDS)
    invalid += dropped
    ladder = data.get("ladder")
    ladder_level: str | None = None
    if isinstance(ladder, dict):  # a ladder level (contract §9)
        level = ladder.get("level")
        ladder_level = str(level) if isinstance(level, str) and is_safe_id(level) else "unknown"
    dirty = ladder_level is not None and ladder_level != "L0"  # L0 is the clean base
    return CaseMeta(
        variant_id=variant_id,
        case_id=str(case_id),
        source=source,
        doc_origins=doc_origins,
        traps=traps,
        tests=tests,
        invalid_ids=invalid,
        section=section_of(doc_origins, dirty),
        ladder_level=ladder_level,
    )


def fixture_traps(fixtures_root: Path) -> dict[str, list[str]]:
    """`{fixture name: [trap ids]}` for every rules fixture that has a `meta.yaml`."""
    out: dict[str, list[str]] = {}
    if not fixtures_root.is_dir():
        return out
    for meta in sorted(fixtures_root.glob(f"*/{FIXTURE_META_NAME}")):
        name = meta.parent.name
        if _FIXTURE_NAME.match(name) is None:
            continue
        data: Any = safe_yaml(meta)
        ids, _ = _ids((data or {}).get("trap_ids") if isinstance(data, dict) else None)
        out[name] = list(ids)
    return out
