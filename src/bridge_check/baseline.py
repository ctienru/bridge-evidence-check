"""The regression baseline (`reports/baseline-dev.json`, contract §11): building it,
reading it from the PR base, guarding changes to it, and detecting regressions.

Regression (contract §11, planning section 3.1), judged row by row against the baseline
rows of the same variant, conditions and claims alike:

1. `false_support`: a row the system now calls `supported` where gold does not, and the
   baseline did not (a row or variant the baseline lacks counts as no prior false support);
2. `status`: a row the baseline had correct whose status now differs from gold;
3. `flags`: a row (or the case flags) the baseline had correct whose status still matches
   but whose flags no longer do;
4. `exclusion_downgrade`: an `exclusion.*` row that was `review` in the baseline and is
   now `insufficient` or `not_supported`, whatever gold says;
5. `run_failed` / `case_missing`: a baseline variant whose run did not complete, or that
   the evaluation did not score at all (skipped variants excepted).

The file may change only in a PR whose title carries `[update baseline]`; a baseline the
base has and the head deletes always fails (`baseline_change_problem`).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Collection, Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from bridge_check.baseline_schema import BASELINE_VERSION, Baseline, ResultRow
from bridge_check.compare import compare_stored_run
from bridge_check.compute import DrugIndex
from bridge_check.enums import Status
from bridge_check.export import link_problem, replay_path
from bridge_check.gold_schema import Gold
from bridge_check.manifest import CHECKOUT_ROOT, MANIFEST_NAME, dev_variants, read_problem
from bridge_check.rules_schema import load_drugs, load_rules
from bridge_check.scoring import CaseScore, RowScore, SplitScore
from bridge_check.store import Store

BASELINE_PATH = Path("reports") / "baseline-dev.json"
UPDATE_MARKER = "[update baseline]"
ZERO_SHA = "0" * 40
RULES = CHECKOUT_ROOT / "rules" / "bridge-v1.yaml"
DRUGS = CHECKOUT_ROOT / "rules" / "drugs-v2.yaml"

# git stderr fragments that mean "the ref exists but has no such file" (bootstrap), once
# the ref itself has been resolved. A ref that does not resolve is never bootstrap.
_MISSING_FILE_MARKERS: tuple[str, ...] = (
    "does not exist in",
    "exists on disk, but not in",
)

RegressionKind = Literal[
    "false_support", "status", "flags", "exclusion_downgrade", "run_failed", "case_missing"
]


class RegressionItem(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    variant_id: str
    row: str
    kind: RegressionKind
    before_status: Status | None
    before_flags: list[str]
    after_status: Status | None
    after_flags: list[str]


# --- build ------------------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(data: Any) -> str:
    return json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def _rows(report_rows: Mapping[str, Any]) -> dict[str, Any]:
    return {
        cid: {k: r[k] for k in ("status", "flags", "gold_status", "gold_flags", "correct")}
        for cid, r in report_rows.items()
    }


def build(
    store: Store,
    runs: Mapping[str, int],
    root: Path = CHECKOUT_ROOT,
    *,
    rules_path: Path = RULES,
    drugs_path: Path = DRUGS,
) -> dict[str, Any]:
    """The baseline of every dev variant of `splits.yaml`, in manifest order: the newest
    completed run of each (or the run in `runs`) compared against its gold. The gold file
    must still have the manifest hash; every run must share one configuration."""
    manifest = root / MANIFEST_NAME
    rules = load_rules(rules_path)
    drugs = DrugIndex(load_drugs(drugs_path))
    cases: dict[str, Any] = {}
    generated: dict[str, str] = {}
    for entry in dev_variants(root):
        vid = str(entry["variant_id"])
        gold_path = root / "cases" / vid / "expected.json"
        if read_problem(root, gold_path) is not None:
            raise ValueError(f"{vid}: expected.json resolves into a holdout variant")
        gold_sha = sha256_file(gold_path)
        if gold_sha != entry["files"]["expected.json"]:
            raise ValueError(f"{vid}: expected.json differs from the manifest")
        run_id = runs.get(vid) or store.latest_completed_run(vid)
        if run_id is None:
            raise ValueError(f"{vid}: no completed run")
        report = compare_stored_run(
            store,
            run_id,
            gold=Gold.model_validate_json(gold_path.read_bytes()),
            gold_sha256=gold_sha,
            rules=rules,
            drugs=drugs,
        )
        run = report["run"]
        replay = replay_path(
            root / "replays", vid, run["input_hash"], run["prompt_version"], run["schema_version"]
        )
        if read_problem(root, replay) is not None:
            raise ValueError(f"{vid}: replay resolves into a holdout variant")
        ext = store.extraction_for_run(run_id)
        attempt = store.attempt(int(ext["attempt_id"])) if ext and ext["attempt_id"] else {}
        this = {
            "code_sha": run["code_sha"],
            "prompt_version": run["prompt_version"],
            "schema_version": run["schema_version"],
            "rules_version": run["rules_version"],
            "model_returned": str(attempt.get("model_returned") or ""),
        }
        if generated and this != generated:
            raise ValueError(f"{vid}: runs differ in versions or model")
        generated = this
        t = report["totals"]
        cases[vid] = {
            "input_hash": run["input_hash"],
            "gold_sha256": gold_sha,
            "replay": (
                {"path": replay.relative_to(root).as_posix(), "sha256": sha256_file(replay)}
                if replay.is_file()
                else None
            ),
            "conditions": _rows(report["conditions"]),
            "claims": _rows(report["claims"]),
            "case_flags": report["case_flags"],
            "conditions_correct": t["conditions_correct"],
            "claims_correct": t["claims_correct"],
            "false_support_count": t["false_support"],
            "claims_false_support_count": t["claims_false_support"],
            "missed_exclusion_count": t["missed_exclusion"],
        }
    c = cases.values()
    data = {
        "baseline_version": BASELINE_VERSION,
        "split": "dev",
        "manifest_sha256": sha256_file(manifest),
        "generated_from": generated,
        "cases": cases,
        "totals": {
            "cases": len(cases),
            "conditions_correct": sum(x["conditions_correct"] for x in c),
            "conditions_total": sum(len(x["conditions"]) for x in c),
            "claims_correct": sum(x["claims_correct"] for x in c),
            "claims_total": sum(len(x["claims"]) for x in c),
            "false_support_count": sum(x["false_support_count"] for x in c),
            "claims_false_support_count": sum(x["claims_false_support_count"] for x in c),
            "missed_exclusion_count": sum(x["missed_exclusion_count"] for x in c),
        },
    }
    Baseline.model_validate(data)
    return data


# --- the baseline at the PR base --------------------------------------------------------------


def resolve_ref(ref: str, root: Path) -> str | None:
    """The commit sha `ref` names in the repository at `root`, or None when it names
    nothing (an unknown ref, a typo, or no repository at all)."""
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    sha = result.stdout.decode("utf-8", errors="replace").strip()
    return sha or None


def git_show(ref: str, path: str, root: Path) -> tuple[bytes | None, str | None]:
    """The file at `<ref>:<path>` of an already resolved ref; `(None, None)` when the file
    does not exist at that commit (bootstrap), `(None, message)` on any other failure."""
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"], cwd=root, capture_output=True, check=False
    )
    if result.returncode == 0:
        return result.stdout, None
    err = result.stderr.decode("utf-8", errors="replace").lower()
    if any(marker in err for marker in _MISSING_FILE_MARKERS):
        return None, None
    return None, f"git show failed (exit {result.returncode})"


def load_baseline_at(
    ref: str | None, root: Path = CHECKOUT_ROOT
) -> tuple[Baseline | None, bytes | None, str | None]:
    """`(baseline, raw bytes, problem)` from the git ref.

    Bootstrap, `(None, None, None)`: no ref, the zero sha (a first push), or a ref that
    resolves to a commit without `reports/baseline-dev.json`. A ref that does not resolve,
    or a baseline that does not validate, is a problem: the comparison the caller asked
    for cannot run, and that is never silently treated as "no baseline"."""
    if ref is None or ref.strip() == "" or ref == ZERO_SHA:
        return None, None, None
    sha = resolve_ref(ref, root)
    if sha is None:
        return None, None, "base ref does not resolve to a commit"
    raw, problem = git_show(sha, BASELINE_PATH.as_posix(), root)
    if raw is None:
        return None, None, problem
    try:
        return Baseline.model_validate_json(raw), raw, None
    except ValueError as exc:
        return None, raw, f"baseline at the base ref is not valid: {type(exc).__name__}"


def baseline_change_problem(
    base_ref: str | None, pr_title: str, root: Path = CHECKOUT_ROOT
) -> str | None:
    """Why this head may not carry its `reports/baseline-dev.json` (contract §11): the base
    has one and the head deleted it, or the bytes differ and the PR title lacks
    `[update baseline]`. None when the file is unchanged, newly added at bootstrap, or the
    title carries the marker."""
    _, raw, problem = load_baseline_at(base_ref, root)
    if problem is not None:
        return problem
    head = root / BASELINE_PATH
    if raw is None:
        return None  # nothing in base: bootstrap, nothing to protect
    if not head.is_file():
        return "reports/baseline-dev.json exists in the base and is deleted in this change"
    linked = link_problem(head)
    if linked is not None:
        return f"reports/baseline-dev.json {linked}"  # refused before any read, marker or not
    if read_problem(root, head) is not None:
        return "reports/baseline-dev.json resolves into a holdout variant"
    if head.read_bytes() != raw and UPDATE_MARKER not in pr_title:
        return (
            "reports/baseline-dev.json differs from the base; the PR title must carry "
            f"{UPDATE_MARKER!r}"
        )
    return None


# --- regression -------------------------------------------------------------------------------


def _item(
    vid: str, row: str, kind: RegressionKind, before: ResultRow | None, after: RowScore | None
) -> RegressionItem:
    return RegressionItem(
        variant_id=vid,
        row=row,
        kind=kind,
        before_status=before.status if before else None,
        before_flags=sorted(before.flags) if before else [],
        after_status=after.status if after else None,
        after_flags=sorted(after.flags) if after else [],
    )


def _row_regressions(
    vid: str, row: str, before: ResultRow, after: RowScore, *, claim: bool
) -> list[RegressionItem]:
    out = []
    after_false = after.status == "supported" and after.gold_status != "supported"
    before_false = before.status == "supported" and before.gold_status != "supported"
    if after_false and not before_false:
        out.append(_item(vid, row, "false_support", before, after))
    if before.correct and after.status != after.gold_status:
        out.append(_item(vid, row, "status", before, after))
    elif (
        before.correct
        and not claim
        and after.status == after.gold_status
        and sorted(after.flags) != sorted(after.gold_flags)
    ):
        out.append(_item(vid, row, "flags", before, after))
    if (
        row.startswith("exclusion.")
        and before.status == "review"
        and after.status in ("insufficient", "not_supported")
    ):
        out.append(_item(vid, row, "exclusion_downgrade", before, after))
    return out


def regressions(
    baseline: Baseline, score: SplitScore, *, skipped: Collection[str] = ()
) -> list[RegressionItem]:
    """Every regression of `score` against `baseline` (see the module docstring). Variants
    in `skipped` are not compared; a baseline variant the evaluation lacks otherwise is a
    `case_missing` regression. Every current row is checked for a new false support, a row
    the baseline does not have included (its prior false support is "none")."""
    out: list[RegressionItem] = []
    for vid in sorted(baseline.cases):
        if vid in skipped:
            continue
        before_case = baseline.cases[vid]
        after_case: CaseScore | None = score.cases.get(vid)
        if after_case is None:
            out.append(_item(vid, "run", "case_missing", None, None))
            continue
        if after_case.run_status != "completed":
            out.append(_item(vid, "run", "run_failed", None, None))
        for group, claim in (("conditions", False), ("claims", True)):
            before_rows: Mapping[str, ResultRow] = getattr(before_case, group)
            after_rows: Mapping[str, RowScore] = getattr(after_case, group)
            for row in sorted(before_rows):
                if row in after_rows:
                    out.extend(
                        _row_regressions(vid, row, before_rows[row], after_rows[row], claim=claim)
                    )
        if before_case.case_flags.correct and not after_case.case_flags.correct:
            out.append(
                RegressionItem(
                    variant_id=vid,
                    row="case_flags",
                    kind="flags",
                    before_status=None,
                    before_flags=sorted(before_case.case_flags.live),
                    after_status=None,
                    after_flags=sorted(after_case.case_flags.live),
                )
            )
    for vid in sorted(score.cases):
        if vid in skipped:
            continue
        prior = baseline.cases.get(vid)
        for group in ("conditions", "claims"):
            known: Mapping[str, ResultRow] = getattr(prior, group) if prior else {}
            for row, after in sorted(getattr(score.cases[vid], group).items()):
                if row in known:
                    continue  # compared above
                if after.status == "supported" and after.gold_status != "supported":
                    out.append(_item(vid, row, "false_support", None, after))
    return out
