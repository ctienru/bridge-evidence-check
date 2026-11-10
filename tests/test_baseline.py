"""`reports/baseline-dev.json` (contract §11): the shape the eval job reads, consistent with
the manifest, the gold files and the committed replays."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import ROOT
from pydantic import ValidationError

from bridge_check.baseline_schema import Baseline
from bridge_check.enums import CONDITION_IDS

BASELINE = ROOT / "reports" / "baseline-dev.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def raw() -> dict[str, Any]:
    if not BASELINE.is_file():
        pytest.skip("no baseline yet (report only, contract §11)")
    data: dict[str, Any] = json.loads(BASELINE.read_text(encoding="utf-8"))
    return data


@pytest.fixture(scope="module")
def baseline(raw: dict[str, Any]) -> Baseline:
    return Baseline.model_validate(raw)


def _dev() -> dict[str, dict[str, Any]]:
    data: Any = yaml.safe_load((ROOT / "splits.yaml").read_text(encoding="utf-8"))
    return {str(v["variant_id"]): v for v in data["variants"] if v["split"] == "dev"}


def test_file_is_canonical(raw: dict[str, Any]) -> None:
    text = json.dumps(raw, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    assert BASELINE.read_text(encoding="utf-8") == text


def test_covers_every_dev_variant_and_condition(baseline: Baseline) -> None:
    """Every dev variant that has a directory in the checkout has a case entry; a hash-only
    dev row (no directory, contract §11) is recorded by id under `hash_only` only."""
    dev = _dev()
    with_dir = {vid for vid in dev if (ROOT / "cases" / vid).is_dir()}
    assert set(baseline.cases) == with_dir
    assert set(baseline.hash_only) == set(dev) - with_dir
    assert not (set(baseline.hash_only) & set(baseline.cases))
    for case in baseline.cases.values():
        assert set(case.conditions) == set(CONDITION_IDS)


def test_hashes_match_manifest_gold_and_replays(baseline: Baseline) -> None:
    assert baseline.manifest_sha256 == _sha(ROOT / "splits.yaml")
    dev = _dev()
    for vid, case in baseline.cases.items():
        assert case.gold_sha256 == dev[vid]["files"]["expected.json"]
        assert case.gold_sha256 == _sha(ROOT / "cases" / vid / "expected.json")
        assert case.replay is not None
        replay = ROOT / case.replay.path
        assert replay.parent.name == vid and case.input_hash in replay.name
        assert case.replay.sha256 == _sha(replay)


def test_gold_side_equals_the_gold_files(baseline: Baseline) -> None:
    for vid, case in baseline.cases.items():
        gold = json.loads((ROOT / "cases" / vid / "expected.json").read_text(encoding="utf-8"))
        for c in gold["conditions"]:
            row = case.conditions[c["id"]]
            assert (row.gold_status, sorted(row.gold_flags)) == (c["status"], sorted(c["flags"]))
        assert {c["id"]: c["status"] for c in gold["claims"]} == {
            cid: r.gold_status for cid, r in case.claims.items()
        }


def test_schema_rejects_inconsistent_counts(raw: dict[str, Any]) -> None:
    broken = json.loads(json.dumps(raw))
    first = next(iter(broken["cases"]))
    broken["cases"][first]["false_support_count"] += 1
    with pytest.raises(ValidationError):
        Baseline.model_validate(broken)
    broken = json.loads(json.dumps(raw))
    broken["totals"]["conditions_correct"] += 1
    with pytest.raises(ValidationError):
        Baseline.model_validate(broken)
    broken = json.loads(json.dumps(raw))
    row = next(iter(broken["cases"][first]["conditions"].values()))
    row["correct"] = not row["correct"]
    with pytest.raises(ValidationError):
        Baseline.model_validate(broken)
