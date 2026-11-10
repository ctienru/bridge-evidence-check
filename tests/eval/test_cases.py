"""DeepEval shell (planning section 5.1): one test case per frozen dev variant that has a
directory in this checkout (hash-only dev rows are not cases, contract §11), scored by
`DeterministicCaseMetric`, whose success is "no false support" and whose score is the
condition accuracy of `bridge_check.scoring`. Runs offline from the committed replays and
needs the `eval` dependency group; without `deepeval`, the replays or the MTSamples
documents the module is skipped. The report stays `bridge eval`'s; DeepEval only records
the run. No LLM judge is involved anywhere."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
deepeval = pytest.importorskip("deepeval")

from deepeval import assert_test  # noqa: E402
from deepeval.metrics import BaseMetric  # noqa: E402
from deepeval.test_case import LLMTestCase  # noqa: E402

from bridge_check.evalrun import EvalOptions, run_eval  # noqa: E402
from bridge_check.export import replay_path  # noqa: E402
from bridge_check.extract import PROMPT_VERSION  # noqa: E402
from bridge_check.manifest import CHECKOUT_ROOT, dev_variants  # noqa: E402
from bridge_check.schema import SCHEMA_VERSION  # noqa: E402

ROOT = CHECKOUT_ROOT


def _dev_with_directory() -> list[dict[str, Any]]:
    """The dev rows this checkout can run: a dev row without a `cases/<variant_id>/`
    directory is a hash-only row (contract §11), skipped by `bridge eval`, never a case."""
    return [v for v in dev_variants(ROOT) if (ROOT / "cases" / str(v["variant_id"])).is_dir()]


DEV = [str(v["variant_id"]) for v in _dev_with_directory()]


def _ready() -> str | None:
    for v in _dev_with_directory():
        vid = str(v["variant_id"])
        if any(
            rel.startswith("docs/D2-mtsamples-") and not (ROOT / "cases" / vid / rel).is_file()
            for rel in v.get("files", {})
        ):
            return f"{vid}: MTSamples document not fetched"
        if not list((ROOT / "replays" / vid).glob(f"*-{PROMPT_VERSION}-{SCHEMA_VERSION}.json")):
            return f"{vid}: no replay for {PROMPT_VERSION}/{SCHEMA_VERSION}"
    return None


@pytest.fixture(scope="module")
def report(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    reason = _ready()
    if reason is not None:
        pytest.skip(reason)
    out = tmp_path_factory.mktemp("deepeval")
    _, public, _ = run_eval(EvalOptions(offline=True, out=out, baseline_ref=None))
    return public


class DeterministicCaseMetric(BaseMetric):  # type: ignore[misc]
    """Score = conditions correct / conditions scored; success = no false support and a
    completed run. `threshold` is not what decides success (see `is_successful`)."""

    threshold = 1.0

    def __init__(self, case: dict[str, Any]) -> None:
        self.case = case
        self.score: float | None = None
        self.success: bool | None = None
        self.reason: str | None = None
        self.error: str | None = None
        self.async_mode = False
        self.strict_mode = False
        self.verbose_mode = False
        self.include_reason = True
        self.evaluation_model = "deterministic"

    def measure(self, test_case: LLMTestCase, *args: Any, **kwargs: Any) -> float:
        c = self.case
        correct, total = c["conditions_correct"]["n"], c["conditions_correct"]["of"]
        false_supports = c["false_supports"]["count"] + c["claims_false_supports"]["count"]
        self.score = correct / total if total else 0.0
        self.success = false_supports == 0 and c["run_status"] == "completed"
        self.reason = (
            f"conditions {correct}/{total}; false supports {false_supports}; "
            f"missed exclusions {c['missed_exclusions']['n']}; run {c['run_status']}"
        )
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args: Any, **kwargs: Any) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return bool(self.success)

    @property
    def __name__(self) -> str:
        return "Deterministic case metric"


@pytest.mark.parametrize("variant_id", DEV)
def test_dev_variant(report: dict[str, Any], variant_id: str) -> None:
    case = report["score"]["cases"][variant_id]
    statuses = {cid: r["status"] for cid, r in case["conditions"].items()}
    gold = {cid: r["gold_status"] for cid, r in case["conditions"].items()}
    test_case = LLMTestCase(
        input=variant_id,
        actual_output=json.dumps(statuses, sort_keys=True),
        expected_output=json.dumps(gold, sort_keys=True),
    )
    assert_test(test_case, [DeterministicCaseMetric(case)], run_async=False)


def test_replay_files_are_what_the_cases_ran(report: dict[str, Any]) -> None:
    for vid in DEV:
        assert report["score"]["cases"][vid]["extraction_source"] == "replay"
        assert Path(
            replay_path(ROOT / "replays", vid, "x", PROMPT_VERSION, SCHEMA_VERSION)
        ).parent.is_dir()
