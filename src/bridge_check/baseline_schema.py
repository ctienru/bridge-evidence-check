"""`reports/baseline-dev.json`: the regression baseline of the dev split (contract §11).

For every dev variant of `splits.yaml` that has a directory in the checkout: the gold hash
(from the manifest), the replay file and its hash, the input hash, the status and flags of
every condition and claim next to gold, whether each is correct, and the false-support and
missed-exclusion counts. The eval job compares a new run against this file;
`scripts/build_baseline.py` writes it. Hash-only dev rows (no directory) are listed by id
under `hash_only`.

Definitions (`docs/eval.md` §1, contract §11):
- correct: same status, and for conditions the same sorted flags (gold claims carry none);
- false support: gold is not `supported` and the system says `supported`;
- missed exclusion: an `exclusion.*` row gold marks `review` (exclusion evidence exists)
  that the system marks `insufficient` or `not_supported`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bridge_check.enums import Status

BASELINE_VERSION = 1
_SHA256 = r"^[0-9a-f]{64}$"


class _Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class GeneratedFrom(_Strict):
    """The versions that produced the baseline: code, prompt, schema, rules, and the model the API
    reported (contract §11)."""

    code_sha: str
    prompt_version: str
    schema_version: str
    rules_version: str
    model_returned: str


class ResultRow(_Strict):
    """One condition or claim of one variant: the live status and flags next to gold, and whether
    they are correct (contract §11)."""

    status: Status | None
    flags: list[str]
    gold_status: Status
    gold_flags: list[str]
    correct: bool


class Replay(_Strict):
    """The replay file a variant was scored from: repository path and sha256 (contract §11)."""

    path: str
    sha256: str = Field(pattern=_SHA256)


class CaseFlags(_Strict):
    """The case-level flags (contract §2) in gold and in the live run, and whether they match."""

    gold: list[str]
    live: list[str]
    correct: bool


class CaseBaseline(_Strict):
    """One dev variant of the baseline (contract §11): its hashes, every condition and claim row,
    and counts that must equal the rows."""

    input_hash: str = Field(pattern=_SHA256)
    gold_sha256: str = Field(pattern=_SHA256)
    replay: Replay | None
    conditions: dict[str, ResultRow]
    claims: dict[str, ResultRow]
    case_flags: CaseFlags
    conditions_correct: int = Field(ge=0)
    claims_correct: int = Field(ge=0)
    false_support_count: int = Field(ge=0)
    claims_false_support_count: int = Field(ge=0)
    missed_exclusion_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _counts(self) -> CaseBaseline:
        if self.conditions_correct != sum(r.correct for r in self.conditions.values()):
            raise ValueError("conditions_correct does not match the rows")
        if self.claims_correct != sum(r.correct for r in self.claims.values()):
            raise ValueError("claims_correct does not match the rows")
        if self.false_support_count != false_support(self.conditions):
            raise ValueError("false_support_count does not match the rows")
        if self.claims_false_support_count != false_support(self.claims):
            raise ValueError("claims_false_support_count does not match the rows")
        if self.missed_exclusion_count != missed_exclusion(self.conditions):
            raise ValueError("missed_exclusion_count does not match the rows")
        for rows, claim in ((self.conditions, False), (self.claims, True)):
            for row in rows.values():
                if row.correct != is_correct(row, claim=claim):
                    raise ValueError("a row's correct flag does not match its statuses")
        return self


class Totals(_Strict):
    """Sums over all cases; `Baseline` rejects totals that do not match its cases."""

    cases: int = Field(ge=0)
    conditions_correct: int = Field(ge=0)
    conditions_total: int = Field(ge=0)
    claims_correct: int = Field(ge=0)
    claims_total: int = Field(ge=0)
    false_support_count: int = Field(ge=0)
    claims_false_support_count: int = Field(ge=0)
    missed_exclusion_count: int = Field(ge=0)


class Baseline(_Strict):
    """The whole of `reports/baseline-dev.json` (contract §11)."""

    baseline_version: Literal[1]
    split: Literal["dev"]
    manifest_sha256: str = Field(pattern=_SHA256)
    generated_from: GeneratedFrom
    hash_only: list[str] = Field(default_factory=list)
    """Dev variants of the manifest whose directory is absent from the checkout (hash-only
    rows, contract §11): recorded by id, never scored, no case entry."""
    cases: dict[str, CaseBaseline]
    totals: Totals

    @model_validator(mode="after")
    def _totals(self) -> Baseline:
        cases = self.cases.values()
        expected = Totals(
            cases=len(self.cases),
            conditions_correct=sum(c.conditions_correct for c in cases),
            conditions_total=sum(len(c.conditions) for c in cases),
            claims_correct=sum(c.claims_correct for c in cases),
            claims_total=sum(len(c.claims) for c in cases),
            false_support_count=sum(c.false_support_count for c in cases),
            claims_false_support_count=sum(c.claims_false_support_count for c in cases),
            missed_exclusion_count=sum(c.missed_exclusion_count for c in cases),
        )
        if expected != self.totals:
            raise ValueError("totals do not match the cases")
        return self


def is_correct(row: ResultRow, *, claim: bool) -> bool:
    """Same status as gold; a condition also needs the same flags in any order, a claim only the
    status (`docs/eval.md` §1)."""
    return row.status == row.gold_status and (claim or sorted(row.flags) == sorted(row.gold_flags))


def false_support(rows: dict[str, ResultRow]) -> int:
    """Number of rows the system marks `supported` where gold does not (`docs/eval.md` §1)."""
    return sum(r.status == "supported" and r.gold_status != "supported" for r in rows.values())


def missed_exclusion(rows: dict[str, ResultRow]) -> int:
    """Number of `exclusion.*` rows gold marks `review` that the system marks `insufficient` or
    `not_supported` (contract §11, definition of regression)."""
    return sum(
        cid.startswith("exclusion.")
        and r.gold_status == "review"
        and r.status in ("insufficient", "not_supported")
        for cid, r in rows.items()
    )
