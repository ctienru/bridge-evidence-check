"""The seven committed dev replays, replayed offline through the whole pipeline and scored,
reproduce the committed baseline row for row (contract §11). A mismatch here is a bug in
scoring or in the pipeline, never a reason to edit a report."""

from __future__ import annotations

import json

import pytest
from conftest import ROOT
from leakcheck import assert_no_shared_windows, mtsamples_files, read_exact

from bridge_check.baseline import BASELINE_PATH, regressions
from bridge_check.baseline_schema import Baseline
from bridge_check.evalrun import EvalOptions, run_eval
from bridge_check.export import export_public_report


@pytest.fixture(scope="module")
def offline(tmp_path_factory: pytest.TempPathFactory) -> tuple[int, dict, str]:  # type: ignore[type-arg]
    if not mtsamples_files():
        pytest.skip("MTSamples documents not fetched (scripts/fetch_mtsamples.py)")
    out = tmp_path_factory.mktemp("eval")
    return run_eval(EvalOptions(offline=True, out=out, baseline_ref=None))


def test_reproduces_the_committed_baseline(offline: tuple[int, dict, str]) -> None:  # type: ignore[type-arg]
    code, report, _ = offline
    assert code == 0 and report["skipped"] == [] and not report["incomplete"]
    m = report["score"]["micro"]
    baseline = Baseline.model_validate_json((ROOT / BASELINE_PATH).read_bytes())
    t = baseline.totals
    assert m["conditions_correct"] == {"n": t.conditions_correct, "of": t.conditions_total}
    assert m["claims_correct"] == {"n": t.claims_correct, "of": t.claims_total}
    assert m["false_supports"]["count"] == t.false_support_count == 0
    assert m["claims_false_supports"]["count"] == t.claims_false_support_count == 0
    assert m["missed_exclusions"]["n"] == t.missed_exclusion_count == 0
    assert (m["conditions_correct"]["n"], m["claims_correct"]["n"]) == (133, 36)
    for vid, case in baseline.cases.items():
        scored = report["score"]["cases"][vid]
        assert scored["extraction_source"] == "replay"
        for group in ("conditions", "claims"):
            rows = getattr(case, group)
            for cid, row in rows.items():
                after = scored[group][cid]
                assert (after["status"], sorted(after["flags"])) == (
                    row.status,
                    sorted(row.flags),
                ), f"{vid} {cid}"
                assert after["correct"] == row.correct, f"{vid} {cid}"


def test_no_regression_against_the_committed_baseline(offline: tuple[int, dict, str]) -> None:  # type: ignore[type-arg]
    _, report, _ = offline
    from bridge_check.scoring import SplitScore

    split = SplitScore.model_validate(report["score"])
    baseline = Baseline.model_validate_json((ROOT / BASELINE_PATH).read_bytes())
    assert regressions(baseline, split) == []


def test_report_passes_the_public_gate_and_names_no_text(offline: tuple[int, dict, str]) -> None:  # type: ignore[type-arg]
    _, report, markdown = offline
    assert export_public_report(report) == report
    for source in mtsamples_files():
        text = read_exact(source)
        assert_no_shared_windows(json.dumps(report), "eval-dev.json", text, source.name)
        assert_no_shared_windows(markdown, "eval-dev.md", text, source.name)
    assert markdown.startswith("# Eval report, split=dev, mode=offline")
    assert "## Coverage matrix" in markdown and "### Not covered" in markdown


def test_committed_snapshot_matches_this_run(offline: tuple[int, dict, str]) -> None:  # type: ignore[type-arg]
    """`reports/eval-dev.json` is the committed snapshot of this very computation, except
    for the code sha, the baseline block and the exit code, which depend on the checkout."""
    _, report, _ = offline
    path = ROOT / "reports" / "eval-dev.json"
    if not path.is_file():
        pytest.skip("no committed eval-dev.json yet")
    committed = json.loads(path.read_text(encoding="utf-8"))
    for d in (committed, report):
        d["generated_from"].pop("code_sha", None)
        d.pop("baseline", None)
        d.pop("exit_code", None)
    assert committed == report
