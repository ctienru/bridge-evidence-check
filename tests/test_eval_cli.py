"""`bridge eval --split dev --offline` on a synthetic data root (contract §1, §11): the
public report files, exit codes 0 / 1 / 3 / 4, replay seeding without an API call, the
temporary database, holdout rows never opened, MTSamples-unavailable rows skipped, hash-only
dev rows skipped and evaluated only when the data root holds their directory."""

from __future__ import annotations

import builtins
import hashlib
import io
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Any

import pytest
from conftest import FIXTURES

from bridge_check import evalrun
from bridge_check.baseline_schema import Baseline
from bridge_check.cli import EXIT_FAILED, EXIT_LOCKED, EXIT_OK, EXIT_REGRESSION
from bridge_check.cli import main as bridge_main
from bridge_check.evalrun import EvalOptions, NoApiClient, run_eval
from bridge_check.export import ExportError, dump_replay, export_public_run, replay_path
from bridge_check.extract import PROMPT_VERSION
from bridge_check.input import InputError, load_case
from bridge_check.manifest import CHECKOUT_ROOT
from bridge_check.runlock import exclusive_run_lock
from bridge_check.schema import SCHEMA_VERSION
from bridge_check.store import open_store

SMOKE = FIXTURES / "case-smoke"
GOLD = FIXTURES / "compare_gold" / "case-smoke-gold.json"
SENTINEL = "SENTINEL-c4b1e7d2-holdout-never-read"
MANIFEST = """version: 1
variants:
  - case_id: case-smoke
    variant_id: case-smoke
    split: dev
    frozen_at: 2026-11-09
    gold_version: 1
    files: {{input.yaml: {sha}, expected.json: {sha}}}
  - case_id: case-hold
    variant_id: case-hold
    split: holdout
    frozen_at: 2026-11-09
    gold_version: 1
    files: {{input.yaml: {sha}, expected.json: {sha}}}
{extra}"""
MTS_ROW = f"""  - case_id: case-mts
    variant_id: case-mts
    split: dev
    frozen_at: 2026-11-09
    gold_version: 1
    files:
      input.yaml: {"0" * 64}
      docs/D2-mtsamples-9999.txt: {"0" * 64}
      expected.json: {"0" * 64}
"""
HASH_ONLY_ROWS = f"""  - case_id: case-hashonly
    variant_id: case-hashonly
    split: dev
    frozen_at: 2026-11-10
    gold_version: 1
    files: {{input.yaml: {"1" * 64}, expected.json: {"1" * 64}}}
  - case_id: case-hold2
    variant_id: case-hold2
    split: holdout
    frozen_at: 2026-11-10
    gold_version: 1
    files: {{input.yaml: {"2" * 64}, expected.json: {"2" * 64}}}
"""


def _data_root(tmp_path: Path, *, with_replay: bool = True, extra_rows: str = "") -> Path:
    """A data root: the smoke case as a dev variant with its gold and a hidden `case.yaml`,
    a holdout variant whose directory is unreadable, and (optionally) its replay."""
    root = tmp_path / "data"
    case_dir = root / "cases" / "case-smoke"
    shutil.copytree(SMOKE, case_dir)
    shutil.copy(GOLD, case_dir / "expected.json")
    (case_dir / "case.yaml").write_text(
        "case_id: case-smoke\nsplit: dev\nsource: synthetic\ndocuments:\n"
        "  - {doc_id: D1-referral, doc_origin: authored}\n"
        "traps: [T-smoke-one]\ntests: [claim.drug, bmi_path_c.stroke]\n",
        encoding="utf-8",
    )
    hold = root / "cases" / "case-hold"
    hold.mkdir()
    for name in ("input.yaml", "expected.json", "case.yaml"):
        (hold / name).write_text(f"{SENTINEL}\n", encoding="utf-8")
    gold_sha = hashlib.sha256((case_dir / "expected.json").read_bytes()).hexdigest()
    (root / "splits.yaml").write_text(
        MANIFEST.format(sha=gold_sha, extra=extra_rows), encoding="utf-8"
    )
    if with_replay:
        db = tmp_path / "record.db"
        os.environ["BRIDGE_FAKE_CLIENT"] = "1"
        try:
            assert bridge_main(["check", str(case_dir), "--db", str(db)]) == 0
        finally:
            del os.environ["BRIDGE_FAKE_CLIENT"]
        store = open_store(db)
        try:
            run_id = store.latest_completed_run("case-smoke")
            assert run_id is not None
            case = load_case(case_dir, root)
            payload = export_public_run(store, run_id, case.texts)
        finally:
            store.close()
        path = replay_path(
            root / "replays",
            "case-smoke",
            payload["input_hash"],
            payload["prompt_version"],
            payload["schema_version"],
        )
        path.parent.mkdir(parents=True)
        path.write_text(dump_replay(payload), encoding="utf-8")
    return root


def _add_dev_variant(root: Path, tmp_path: Path, vid: str) -> None:
    """Give the data root a directory and a replay for dev variant `vid`: a copy of the
    smoke case under that id, recorded once through the fake client."""
    case_dir = root / "cases" / vid
    shutil.copytree(SMOKE, case_dir)
    shutil.copy(GOLD, case_dir / "expected.json")
    inp = case_dir / "input.yaml"
    inp.write_text(
        inp.read_text(encoding="utf-8").replace("variant_id: case-smoke", f"variant_id: {vid}"),
        encoding="utf-8",
    )
    (case_dir / "case.yaml").write_text(
        f"case_id: {vid}\nsplit: dev\nsource: synthetic\ndocuments:\n"
        "  - {doc_id: D1-referral, doc_origin: authored}\ntraps: []\ntests: [claim.drug]\n",
        encoding="utf-8",
    )
    db = tmp_path / f"record-{vid}.db"
    os.environ["BRIDGE_FAKE_CLIENT"] = "1"
    try:
        assert bridge_main(["check", str(case_dir), "--db", str(db)]) == 0
    finally:
        del os.environ["BRIDGE_FAKE_CLIENT"]
    store = open_store(db)
    try:
        run_id = store.latest_completed_run(vid)
        assert run_id is not None
        case = load_case(case_dir, root)
        payload = export_public_run(store, run_id, case.texts)
    finally:
        store.close()
    path = replay_path(
        root / "replays",
        vid,
        payload["input_hash"],
        payload["prompt_version"],
        payload["schema_version"],
    )
    path.parent.mkdir(parents=True)
    path.write_text(dump_replay(payload), encoding="utf-8")


@pytest.fixture
def unreadable_holdout(tmp_path: Path) -> Any:
    """Make `cases/case-hold` unreadable for the test; restore it for cleanup."""
    made: list[Path] = []

    def lock(root: Path) -> None:
        hold = root / "cases" / "case-hold"
        os.chmod(hold, 0)
        made.append(hold)

    yield lock
    for hold in made:
        os.chmod(hold, stat.S_IRWXU)


def _eval(root: Path, out: Path, *more: str) -> int:
    return bridge_main(
        ["eval", "--split", "dev", "--offline", "--data-root", str(root), "--out", str(out), *more]
    )


def test_offline_eval_writes_the_public_report(
    tmp_path: Path, unreadable_holdout: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _data_root(tmp_path)
    unreadable_holdout(root)
    out = tmp_path / "out"
    db = tmp_path / "eval.db"
    capsys.readouterr()  # drop the recording `check`'s output
    assert _eval(root, out, "--db", str(db), "--json") == EXIT_OK
    printed = json.loads(capsys.readouterr().out)
    report = json.loads((out / "eval-dev.json").read_text(encoding="utf-8"))
    assert printed == report
    md = (out / "eval-dev.md").read_text(encoding="utf-8")
    assert report["mode"] == "offline" and report["split"] == "dev"
    assert report["skipped"] == [{"variant_id": "case-hold", "reason": "holdout_never_read"}]
    assert not report["incomplete"]
    assert report["baseline"] == {
        "bootstrap": True,
        "found": False,
        "gold_changed": [],
        "problem": None,
        "ref": None,
        "sha256": None,
    }
    assert report["regression"] == {"detected": False, "items": []}
    case = report["score"]["cases"]["case-smoke"]
    assert case["extraction_source"] == "replay" and case["run_status"] == "completed"
    assert case["conditions_correct"] == {"n": 15, "of": 20}
    assert case["false_supports"]["count"] == 1
    assert [t["passed"] for t in case["traps"]] == [True]
    assert report["score"]["coverage"]["cells"]["T-smoke-one"]["integrated_case"] == ["case-smoke"]
    assert "case-hold" not in json.dumps(report["score"]) and "case-hold" in md
    for body in (json.dumps(report), md):
        assert SENTINEL not in body and "SENTINEL" not in body
    # the run used the seeded replay: one attempt, attempt_no 0, no API attempt
    store = open_store(db)
    try:
        [run] = store.history("case-smoke")
        attempts = store.attempts_for_run(run["id"])
    finally:
        store.close()
    assert run["extraction_source"] == "replay"
    assert [a["attempt_no"] for a in attempts] == [0] and attempts[0]["status"] == "parsed"
    assert attempts[0]["cost_usd"] is None and report["cost_usd"] == 0.0


def test_offline_eval_is_deterministic(tmp_path: Path) -> None:
    root = _data_root(tmp_path)
    a, b = tmp_path / "a", tmp_path / "b"
    assert _eval(root, a, "--db", str(tmp_path / "a.db")) == EXIT_OK
    assert _eval(root, b, "--db", str(tmp_path / "b.db")) == EXIT_OK
    for name in ("eval-dev.json", "eval-dev.md"):
        assert (a / name).read_bytes() == (b / name).read_bytes()


def test_default_database_is_temporary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _data_root(tmp_path)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setenv("BRIDGE_DB", str(cwd / "env.db"))
    assert _eval(root, tmp_path / "out") == EXIT_OK
    assert list(cwd.iterdir()) == []


def test_missing_replay_is_a_failed_run_and_no_api_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _data_root(tmp_path, with_replay=False)
    monkeypatch.setenv("BRIDGE_FAKE_CLIENT", "1")  # must be ignored offline
    db = tmp_path / "eval.db"
    assert _eval(root, tmp_path / "out", "--db", str(db)) == EXIT_FAILED
    report = json.loads((tmp_path / "out" / "eval-dev.json").read_text(encoding="utf-8"))
    case = report["score"]["cases"]["case-smoke"]
    assert case["run_status"] == "failed" and case["failed_stage"] == "extract"
    assert case["conditions_correct"] == {"n": 0, "of": 20}
    assert case["first_errors"]["run_failed"] == 22
    assert [t["first_error"] for t in case["traps"]] == ["run_failed"]
    assert report["score"]["micro"]["runs_failed"] == 1
    store = open_store(db)
    try:
        [run] = store.history("case-smoke")
        assert store.attempts_for_run(run["id"]) == []
        failed = store.case_run(run["id"])
    finally:
        store.close()
    assert failed["status"] == "failed" and str(failed["error"]).startswith("ReplayMissing")
    assert "quote" not in capsys.readouterr().err


def test_no_api_client_refuses_every_call() -> None:
    client = NoApiClient()
    with pytest.raises(RuntimeError):
        client.with_options(timeout=1).messages.create(model="x")


def test_lock_held_exits_4(tmp_path: Path) -> None:
    root = _data_root(tmp_path)
    db = tmp_path / "eval.db"
    with exclusive_run_lock(db):
        assert _eval(root, tmp_path / "out", "--db", str(db)) == EXIT_LOCKED
    assert not (tmp_path / "out").exists()


def test_mtsamples_unavailable_variant_is_skipped_and_report_incomplete(tmp_path: Path) -> None:
    root = _data_root(tmp_path, extra_rows=MTS_ROW)
    # the variant has its directory (as every MTSamples case does); only the document is absent
    (root / "cases" / "case-mts").mkdir()
    assert _eval(root, tmp_path / "out") == EXIT_OK
    report = json.loads((tmp_path / "out" / "eval-dev.json").read_text(encoding="utf-8"))
    assert {s["variant_id"]: s["reason"] for s in report["skipped"]} == {
        "case-hold": "holdout_never_read",
        "case-mts": "mtsamples_unavailable",
    }
    assert report["incomplete"] and "case-mts" not in report["score"]["cases"]


def test_hash_only_dev_row_is_skipped_never_opened_and_not_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dev row without a `cases/<variant_id>/` directory (contract §11) is skipped with
    reason `hash_only`, listed under `skipped`, never named on disk, never scored, and the
    report stays complete; a holdout row without a directory keeps its own reason."""
    root = _data_root(tmp_path, extra_rows=HASH_ONLY_ROWS)
    opened = _record_opens(monkeypatch, root / "cases" / "case-hashonly")
    out = tmp_path / "out"
    assert _eval(root, out, "--db", str(tmp_path / "eval.db")) == EXIT_OK
    assert opened == []
    report = json.loads((out / "eval-dev.json").read_text(encoding="utf-8"))
    assert {s["variant_id"]: s["reason"] for s in report["skipped"]} == {
        "case-hold": "holdout_never_read",
        "case-hashonly": "hash_only",
        "case-hold2": "holdout_never_read",
    }
    assert not report["incomplete"]
    assert set(report["score"]["cases"]) == {"case-smoke"}
    md = (out / "eval-dev.md").read_text(encoding="utf-8")
    assert "`case-hashonly`: hash_only" in md


def test_hash_only_dev_row_is_evaluated_when_the_data_root_has_its_directory(
    tmp_path: Path,
) -> None:
    """The same manifest against a data root that holds the directory (`--data-root`): the
    row is a normal dev variant, scored from its replay and absent from `skipped`."""
    root = _data_root(tmp_path, extra_rows=HASH_ONLY_ROWS)
    _add_dev_variant(root, tmp_path, "case-hashonly")
    out = tmp_path / "out"
    assert _eval(root, out, "--db", str(tmp_path / "eval.db")) == EXIT_OK
    report = json.loads((out / "eval-dev.json").read_text(encoding="utf-8"))
    assert {s["variant_id"]: s["reason"] for s in report["skipped"]} == {
        "case-hold": "holdout_never_read",
        "case-hold2": "holdout_never_read",
    }
    assert set(report["score"]["cases"]) == {"case-smoke", "case-hashonly"}
    assert report["score"]["cases"]["case-hashonly"]["extraction_source"] == "replay"
    assert not report["incomplete"]


def test_baseline_builder_records_hash_only_dev_rows_by_id(tmp_path: Path) -> None:
    from bridge_check.baseline import build

    root = _data_root(tmp_path, extra_rows=HASH_ONLY_ROWS)
    store = open_store(tmp_path / "record.db")  # the run `_data_root` recorded
    try:
        data = build(store, {}, root)
    finally:
        store.close()
    assert data["hash_only"] == ["case-hashonly"] and set(data["cases"]) == {"case-smoke"}
    assert data["totals"]["cases"] == 1
    Baseline.model_validate(data)


def _baseline_from(report: dict[str, Any], vid: str) -> Baseline:
    """A baseline that records this report's rows as they are."""
    case = report["score"]["cases"][vid]

    def rows(group: str) -> dict[str, Any]:
        return {
            cid: {k: r[k] for k in ("status", "flags", "gold_status", "gold_flags", "correct")}
            for cid, r in case[group].items()
        }

    conditions, claims = rows("conditions"), rows("claims")
    data = {
        "baseline_version": 1,
        "split": "dev",
        "manifest_sha256": report["manifest_sha256"],
        "generated_from": {
            "code_sha": "x",
            "prompt_version": "p",
            "schema_version": "s",
            "rules_version": "r",
            "model_returned": "m",
        },
        "cases": {
            vid: {
                "input_hash": "0" * 64,
                "gold_sha256": case["gold_sha256"],
                "replay": None,
                "conditions": conditions,
                "claims": claims,
                "case_flags": case["case_flags"],
                "conditions_correct": case["conditions_correct"]["n"],
                "claims_correct": case["claims_correct"]["n"],
                "false_support_count": case["false_supports"]["count"],
                "claims_false_support_count": case["claims_false_supports"]["count"],
                "missed_exclusion_count": case["missed_exclusions"]["n"],
            }
        },
        "totals": {
            "cases": 1,
            "conditions_correct": case["conditions_correct"]["n"],
            "conditions_total": 20,
            "claims_correct": case["claims_correct"]["n"],
            "claims_total": len(claims),
            "false_support_count": case["false_supports"]["count"],
            "claims_false_support_count": case["claims_false_supports"]["count"],
            "missed_exclusion_count": case["missed_exclusions"]["n"],
        },
    }
    return Baseline.model_validate(data)


def test_regression_against_the_base_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _data_root(tmp_path)
    assert _eval(root, tmp_path / "first") == EXIT_OK
    report = json.loads((tmp_path / "first" / "eval-dev.json").read_text(encoding="utf-8"))
    same = _baseline_from(report, "case-smoke")
    # pretend the base had exclusion.osa right (review) where this run says insufficient
    data = same.model_dump()
    data["cases"]["case-smoke"]["conditions"]["exclusion.osa"].update(
        {"status": "review", "correct": True}
    )
    data["cases"]["case-smoke"]["conditions_correct"] += 1
    data["cases"]["case-smoke"]["missed_exclusion_count"] -= 1
    data["totals"]["conditions_correct"] += 1
    data["totals"]["missed_exclusion_count"] -= 1
    better = Baseline.model_validate(data)
    raw = json.dumps(data).encode("utf-8")

    monkeypatch.setattr(evalrun, "load_baseline_at", lambda ref, root: (better, raw, None))
    assert _eval(root, tmp_path / "second", "--baseline-from", "fake") == EXIT_REGRESSION
    report = json.loads((tmp_path / "second" / "eval-dev.json").read_text(encoding="utf-8"))
    assert report["baseline"]["found"] and not report["baseline"]["bootstrap"]
    kinds = {(i["row"], i["kind"]) for i in report["regression"]["items"]}
    assert kinds == {("exclusion.osa", "status"), ("exclusion.osa", "exclusion_downgrade")}
    md = (tmp_path / "second" / "eval-dev.md").read_text(encoding="utf-8")
    assert "Regression detected" in md

    monkeypatch.setattr(evalrun, "load_baseline_at", lambda ref, root: (same, raw, None))
    assert _eval(root, tmp_path / "third", "--baseline-from", "fake") == EXIT_OK


def _record_opens(monkeypatch: pytest.MonkeyPatch, inside: Path) -> list[str]:
    """Every file opened (built-in `open`, `io.open`, hence `Path.open` / `read_text` /
    `read_bytes`) whose resolved path lies under `inside`."""
    seen: list[str] = []
    real = builtins.open

    def spy(file: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            resolved = Path(os.fspath(file)).resolve()
            if resolved.is_relative_to(inside.resolve()):
                seen.append(resolved.name)
        except (TypeError, OSError):
            pass
        return real(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy)
    monkeypatch.setattr(io, "open", spy)
    return seen


def test_dev_alias_into_holdout_is_refused_without_opening(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _data_root(tmp_path, with_replay=False)
    hold = root / "cases" / "case-hold"
    # the holdout variant holds a complete, readable case; the dev name is a link to it
    shutil.rmtree(hold)
    shutil.copytree(SMOKE, hold)
    shutil.copy(GOLD, hold / "expected.json")
    (hold / "case.yaml").write_text(f"case_id: case-hold\ntraps: [{SENTINEL}]\n", encoding="utf-8")
    dev = root / "cases" / "case-smoke"
    shutil.rmtree(dev)
    dev.symlink_to(hold, target_is_directory=True)
    opened = _record_opens(monkeypatch, hold)
    out = tmp_path / "out"
    assert _eval(root, out, "--db", str(tmp_path / "eval.db")) == EXIT_FAILED
    assert opened == []
    report = json.loads((out / "eval-dev.json").read_text(encoding="utf-8"))
    assert {s["variant_id"]: s["reason"] for s in report["skipped"]} == {
        "case-smoke": "holdout_path_refused",
        "case-hold": "holdout_never_read",
    }
    assert report["score"]["cases"] == {} and report["exit_code"] == EXIT_FAILED
    assert SENTINEL not in (out / "eval-dev.md").read_text(encoding="utf-8")


def test_single_file_link_into_holdout_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _data_root(tmp_path)
    hold = root / "cases" / "case-hold"
    gold = root / "cases" / "case-smoke" / "expected.json"
    gold.unlink()
    gold.symlink_to(hold / "expected.json")
    opened = _record_opens(monkeypatch, hold)
    assert _eval(root, tmp_path / "out") == EXIT_FAILED
    assert opened == []


def test_replay_link_into_holdout_fails_the_run(tmp_path: Path) -> None:
    root = _data_root(tmp_path)
    [replay] = list((root / "replays" / "case-smoke").glob("*.json"))
    target = root / "cases" / "case-hold" / "replay.json"
    shutil.move(replay, target)
    replay.symlink_to(target)
    db = tmp_path / "eval.db"
    assert _eval(root, tmp_path / "out", "--db", str(db)) == EXIT_FAILED
    store = open_store(db)
    try:
        [run] = store.history("case-smoke")
        failed = store.case_run(run["id"])
    finally:
        store.close()
    assert failed["status"] == "failed" and str(failed["error"]).startswith("HoldoutRefused")


def test_unresolvable_base_ref_exits_3(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _data_root(tmp_path)
    out = tmp_path / "out"
    capsys.readouterr()
    assert _eval(root, out, "--baseline-from", "no-such-ref-anywhere") == EXIT_FAILED
    report = json.loads((out / "eval-dev.json").read_text(encoding="utf-8"))
    assert report["baseline"]["problem"] == "unreadable" and not report["baseline"]["bootstrap"]
    assert report["exit_code"] == EXIT_FAILED and report["score"]["cases"]  # still scored
    assert "does not resolve" in capsys.readouterr().err


def test_invalid_baseline_at_base_exits_3(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _data_root(tmp_path)
    monkeypatch.setattr(
        evalrun, "load_baseline_at", lambda ref, root: (None, b"{}", "baseline is not valid")
    )
    assert _eval(root, tmp_path / "out", "--baseline-from", "x") == EXIT_FAILED


def test_write_baseline_refuses_a_link_to_gold(tmp_path: Path) -> None:
    root = _data_root(tmp_path)
    gold = root / "cases" / "case-smoke" / "expected.json"
    before = gold.read_bytes()
    link = tmp_path / "reports" / "baseline-dev.json"
    link.parent.mkdir()
    link.symlink_to(gold)
    # the smoke case is not a dev variant of the real manifest, so `build` would refuse
    # anyway; point the data root's manifest at it by running the build on that root
    opts = EvalOptions(
        offline=True, data_root=root, out=tmp_path / "out", write_baseline=True, baseline_out=link
    )
    with pytest.raises(Exception, match="refused"):
        run_eval(opts)
    assert gold.read_bytes() == before
    assert not (tmp_path / "reports" / "x").exists()


def test_write_baseline_writes_a_plain_file(tmp_path: Path) -> None:
    root = _data_root(tmp_path)
    target = tmp_path / "reports" / "baseline-dev.json"
    code, report, _ = run_eval(
        EvalOptions(
            offline=True,
            data_root=root,
            out=tmp_path / "out",
            write_baseline=True,
            baseline_out=target,
        )
    )
    assert code == EXIT_OK and target.is_file()
    data = Baseline.model_validate_json(target.read_bytes())
    assert set(data.cases) == {"case-smoke"}
    assert data.cases["case-smoke"].conditions_correct == 15


def test_malformed_case_yaml_exits_3_without_the_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _data_root(tmp_path)
    (root / "cases" / "case-smoke" / "case.yaml").write_text(
        f'case_id: case-smoke\ntraps: [T-a, "{SENTINEL}\n  - oops: [\n', encoding="utf-8"
    )
    capsys.readouterr()
    assert _eval(root, tmp_path / "out") == EXIT_FAILED
    captured = capsys.readouterr()
    assert SENTINEL not in captured.err and SENTINEL not in captured.out
    assert "case.yaml: not valid YAML" in captured.err


def test_malformed_manifest_exits_3_without_the_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _data_root(tmp_path)
    (root / "splits.yaml").write_text(
        f'version: 1\nvariants: [{{a: "{SENTINEL}\n', encoding="utf-8"
    )
    capsys.readouterr()
    assert _eval(root, tmp_path / "out") == EXIT_FAILED
    captured = capsys.readouterr()
    assert SENTINEL not in captured.err and "splits.yaml: not valid YAML" in captured.err


def _full_holdout_copy(root: Path, where: Path) -> Path:
    """A complete, readable copy of the smoke case at `where`, with a sentinel in a
    document, for a holdout variant to point at."""
    if where.exists():
        shutil.rmtree(where)
    shutil.copytree(SMOKE, where)
    shutil.copy(GOLD, where / "expected.json")
    doc = where / "docs" / "D2-clinical.txt"
    doc.write_text(doc.read_text(encoding="utf-8") + f"\n{SENTINEL}\n", encoding="utf-8")
    return where


def test_document_link_through_a_neutral_directory_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`docs/` of the dev case is a link to a neutral directory whose document is a link
    into the holdout variant: `rglob` never sees it, the exact-path check must."""
    root = _data_root(tmp_path)
    hold = _full_holdout_copy(root, root / "cases" / "case-hold")
    neutral = tmp_path / "neutral"
    neutral.mkdir()
    for name in ("D0-pa-form-draft.txt", "D1-referral.txt"):
        shutil.copy(SMOKE / "docs" / name, neutral / name)
    (neutral / "D2-clinical.txt").symlink_to(hold / "docs" / "D2-clinical.txt")
    docs = root / "cases" / "case-smoke" / "docs"
    shutil.rmtree(docs)
    docs.symlink_to(neutral, target_is_directory=True)
    opened = _record_opens(monkeypatch, hold)
    out = tmp_path / "out"
    db = tmp_path / "eval.db"
    assert _eval(root, out, "--db", str(db)) == EXIT_FAILED
    assert opened == []
    report = json.loads((out / "eval-dev.json").read_text(encoding="utf-8"))
    case = report["score"]["cases"]["case-smoke"]
    assert case["run_status"] == "failed" and case["failed_stage"] == "input"
    assert SENTINEL not in (out / "eval-dev.md").read_text(encoding="utf-8")


def test_holdout_directory_alias_is_recognised_by_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The holdout directory is itself a link to a directory outside `cases/`, and the dev
    name links to that same directory: neither string check sees it, `samefile` does."""
    root = _data_root(tmp_path, with_replay=False)
    real = _full_holdout_copy(root, tmp_path / "elsewhere" / "real-hold")
    for name in ("case-hold", "case-smoke"):
        alias = root / "cases" / name
        shutil.rmtree(alias)
        alias.symlink_to(real, target_is_directory=True)
    opened = _record_opens(monkeypatch, real)
    out = tmp_path / "out"
    assert _eval(root, out, "--db", str(tmp_path / "eval.db")) == EXIT_FAILED
    assert opened == []
    report = json.loads((out / "eval-dev.json").read_text(encoding="utf-8"))
    assert {s["variant_id"]: s["reason"] for s in report["skipped"]} == {
        "case-smoke": "holdout_path_refused",
        "case-hold": "holdout_never_read",
    }


def test_outputs_under_the_data_root_holdout_are_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _data_root(tmp_path)
    hold = root / "cases" / "case-hold"
    before = sorted(p.name for p in hold.iterdir())
    out = hold / "out"
    db = hold / "eval.db"
    capsys.readouterr()
    assert _eval(root, out, "--db", str(db)) == EXIT_FAILED
    assert sorted(p.name for p in hold.iterdir()) == before  # no report, db, lock or dir
    assert "holdout" in capsys.readouterr().err
    # the report alone, into a holdout directory, is refused too
    assert _eval(root, out) == EXIT_FAILED
    assert sorted(p.name for p in hold.iterdir()) == before
    # a baseline target inside the data root's holdout is refused before any run
    with pytest.raises(Exception, match="holdout"):
        run_eval(
            EvalOptions(
                offline=True,
                data_root=root,
                out=tmp_path / "ok",
                write_baseline=True,
                baseline_out=hold / "baseline-dev.json",
            )
        )
    assert sorted(p.name for p in hold.iterdir()) == before and not (tmp_path / "ok").exists()


def test_baseline_builder_guards_gold_and_replay_before_hashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bridge_check.baseline import build

    root = _data_root(tmp_path)
    hold = _full_holdout_copy(root, root / "cases" / "case-hold")
    gold = root / "cases" / "case-smoke" / "expected.json"
    gold.unlink()
    gold.symlink_to(hold / "expected.json")
    opened = _record_opens(monkeypatch, hold)
    store = open_store(tmp_path / "record.db")  # the run `_data_root` recorded
    try:
        with pytest.raises(ValueError, match="holdout"):
            build(store, {}, root)
        assert opened == []
        gold.unlink()
        shutil.copy(GOLD, gold)
        [replay] = list((root / "replays" / "case-smoke").glob("*.json"))
        target = hold / "replay.json"
        shutil.move(replay, target)
        replay.symlink_to(target)
        with pytest.raises(ValueError, match="holdout"):
            build(store, {}, root)
        assert opened == []
    finally:
        store.close()


def _nlink(path: Path) -> int:
    return os.lstat(path).st_nlink


def test_hard_linked_report_destination_never_truncates_holdout_gold(tmp_path: Path) -> None:
    root = _data_root(tmp_path)
    hold = _full_holdout_copy(root, root / "cases" / "case-hold")
    gold = hold / "expected.json"
    before = gold.read_bytes()
    out = tmp_path / "out"
    out.mkdir()
    os.link(gold, out / "eval-dev.json")  # same inode, a dev-looking name
    assert _nlink(gold) == 2
    assert _eval(root, out, "--db", str(tmp_path / "eval.db")) == EXIT_FAILED
    assert gold.read_bytes() == before and _nlink(gold) == 2
    assert not (out / "eval-dev.md").exists() and not list(out.glob(".*.tmp"))


def test_hard_linked_baseline_destination_is_refused(tmp_path: Path) -> None:
    root = _data_root(tmp_path)
    hold = _full_holdout_copy(root, root / "cases" / "case-hold")
    gold = hold / "expected.json"
    before = gold.read_bytes()
    target = tmp_path / "reports" / "baseline-dev.json"
    target.parent.mkdir()
    os.link(gold, target)
    with pytest.raises(Exception, match="hard links"):
        run_eval(
            EvalOptions(
                offline=True,
                data_root=root,
                out=tmp_path / "ok",
                write_baseline=True,
                baseline_out=target,
            )
        )
    assert gold.read_bytes() == before and not (tmp_path / "ok").exists()


def test_symlinked_report_destination_is_refused(tmp_path: Path) -> None:
    root = _data_root(tmp_path)
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_text("{}\n", encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    (out / "eval-dev.json").symlink_to(elsewhere)
    assert _eval(root, out) == EXIT_FAILED
    assert elsewhere.read_text(encoding="utf-8") == "{}\n"


def test_reports_are_replaced_atomically_as_plain_files(tmp_path: Path) -> None:
    root = _data_root(tmp_path)
    out = tmp_path / "out"
    assert _eval(root, out, "--db", str(tmp_path / "a.db")) == EXIT_OK
    first = (out / "eval-dev.json").read_bytes()
    assert _eval(root, out, "--db", str(tmp_path / "b.db")) == EXIT_OK
    for name in ("eval-dev.json", "eval-dev.md"):
        path = out / name
        assert path.is_file() and not path.is_symlink() and _nlink(path) == 1
    assert (out / "eval-dev.json").read_bytes() == first
    assert sorted(p.name for p in out.iterdir()) == ["eval-dev.json", "eval-dev.md"]


def test_input_link_into_holdout_is_refused_before_case_id_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from bridge_check import cli
    from bridge_check.input import case_id_of

    root = _data_root(tmp_path, with_replay=False)
    hold = _full_holdout_copy(root, root / "cases" / "case-hold")
    dev = root / "cases" / "case-smoke"
    (dev / "input.yaml").unlink()
    (dev / "input.yaml").symlink_to(hold / "input.yaml")
    opened = _record_opens(monkeypatch, hold)
    # the shared loader refuses before the read: the id lookup falls back without opening
    assert case_id_of(str(dev), root).startswith("unresolved-")
    assert opened == []
    # through check_case, the way eval and check call it
    db = tmp_path / "check.db"
    store = open_store(db)
    try:
        run_id, summary = cli.check_case(store, str(dev), None, root=root)
        run = store.case_run(run_id)
    finally:
        store.close()
    assert summary is None and run["status"] == "failed" and run["failed_stage"] == "input"
    assert opened == []
    # and through the CLI, with the checkout as root (the dev name is outside it, so the
    # manifest of `root` is what names the holdout): eval exits 3 with zero opens
    assert _eval(root, tmp_path / "out", "--db", str(tmp_path / "eval.db")) == EXIT_FAILED
    assert opened == []
    assert SENTINEL not in capsys.readouterr().err


@pytest.mark.parametrize("what", ["document", "gold", "case_yaml", "replay"])
def test_hard_linked_holdout_input_is_refused_before_opening(tmp_path: Path, what: str) -> None:
    """A hard link shares an inode, not a directory: no path check sees it, the link count
    does. Each kind of input the evaluation opens is refused when multiply linked."""
    root = _data_root(tmp_path)
    hold = _full_holdout_copy(root, root / "cases" / "case-hold")
    dev = root / "cases" / "case-smoke"
    if what == "document":
        target, source = dev / "docs" / "D2-clinical.txt", hold / "docs" / "D2-clinical.txt"
    elif what == "gold":
        target, source = dev / "expected.json", hold / "expected.json"
    elif what == "case_yaml":
        target, source = dev / "case.yaml", hold / "case.yaml"
        source.write_text(f"case_id: case-hold\ntraps: [{SENTINEL}]\n", encoding="utf-8")
    else:
        [target] = list((root / "replays" / "case-smoke").glob("*.json"))
        source = hold / "replay.json"
        shutil.copy(target, source)
    target.unlink()
    os.link(source, target)
    out = tmp_path / "out"
    db = tmp_path / "eval.db"
    assert _eval(root, out, "--db", str(db)) == EXIT_FAILED
    assert SENTINEL not in (out / "eval-dev.md").read_text(encoding="utf-8")
    report = json.loads((out / "eval-dev.json").read_text(encoding="utf-8"))
    if what == "replay":  # outside the case directory: refused when the extractor reaches it
        case = report["score"]["cases"]["case-smoke"]
        assert case["run_status"] == "failed" and case["failed_stage"] == "extract"
    else:  # under the case directory: refused by the early sweep, nothing opened
        assert "case-smoke" not in report["score"]["cases"]
        reasons = {s["variant_id"]: s["reason"] for s in report["skipped"]}
        assert reasons["case-smoke"] == "holdout_path_refused"


def test_offline_requires_the_replay_even_with_a_cached_live_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _data_root(tmp_path)
    dev = root / "cases" / "case-smoke"
    db = tmp_path / "shared.db"
    # a live-style check (fake client) fills the extraction cache for this exact request
    monkeypatch.setenv("BRIDGE_FAKE_CLIENT", "1")
    assert bridge_main(["check", str(dev), "--db", str(db)]) == EXIT_OK
    monkeypatch.delenv("BRIDGE_FAKE_CLIENT")
    # with the replay present the offline run still comes from the replay, not the cache
    out = tmp_path / "out1"
    assert _eval(root, out, "--db", str(db)) == EXIT_OK
    report = json.loads((out / "eval-dev.json").read_text(encoding="utf-8"))
    assert report["score"]["cases"]["case-smoke"]["extraction_source"] == "replay"
    # a second offline run in the same database reuses its own seeded replay, nothing else
    out = tmp_path / "out2"
    assert _eval(root, out, "--db", str(db)) == EXIT_OK
    report = json.loads((out / "eval-dev.json").read_text(encoding="utf-8"))
    assert report["score"]["cases"]["case-smoke"]["extraction_source"] == "cache"
    store = open_store(db)
    try:
        runs = store.history("case-smoke")
        seeded = [a for r in runs for a in store.attempts_for_run(r["id"]) if a["attempt_no"] == 0]
        live = [a for r in runs for a in store.attempts_for_run(r["id"]) if a["attempt_no"] >= 1]
    finally:
        store.close()
    assert len(runs) == 3 and len(seeded) == 1 and len(live) == 1
    # history lists runs oldest first: live check, offline replay, offline cache hit
    assert [r["extraction_source"] for r in runs] == ["api", "replay", "cache"]
    # without the replay the cached live extraction must not stand in for it
    for replay in (root / "replays" / "case-smoke").glob("*.json"):
        replay.unlink()
    out = tmp_path / "out3"
    assert _eval(root, out, "--db", str(db)) == EXIT_FAILED
    report = json.loads((out / "eval-dev.json").read_text(encoding="utf-8"))
    case = report["score"]["cases"]["case-smoke"]
    assert case["run_status"] == "failed" and case["failed_stage"] == "extract"
    assert case["conditions_correct"] == {"n": 0, "of": 20}


def test_symlink_to_a_hard_linked_holdout_document_is_refused(tmp_path: Path) -> None:
    """Both link types at once: the dev document is a symbolic link to a neutral file that
    shares its inode with a holdout document. Only the resolved inode's link count sees it."""
    root = _data_root(tmp_path)
    hold = _full_holdout_copy(root, root / "cases" / "case-hold")
    neutral = tmp_path / "neutral.txt"
    os.link(hold / "docs" / "D2-clinical.txt", neutral)
    dev_doc = root / "cases" / "case-smoke" / "docs" / "D2-clinical.txt"
    dev_doc.unlink()
    dev_doc.symlink_to(neutral)
    out = tmp_path / "out"
    assert _eval(root, out, "--db", str(tmp_path / "eval.db")) == EXIT_FAILED
    report = json.loads((out / "eval-dev.json").read_text(encoding="utf-8"))
    assert "case-smoke" not in report["score"]["cases"]
    assert {s["variant_id"]: s["reason"] for s in report["skipped"]}["case-smoke"] == (
        "holdout_path_refused"
    )
    assert SENTINEL not in (out / "eval-dev.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("suffix", ["-shm", "-wal", "-journal"])
@pytest.mark.parametrize("link", ["hard", "symbolic"])
def test_linked_sqlite_sidecar_is_refused_before_any_connection(
    tmp_path: Path, suffix: str, link: str
) -> None:
    root = _data_root(tmp_path)
    hold = _full_holdout_copy(root, root / "cases" / "case-hold")
    gold = hold / "expected.json"
    before = gold.read_bytes()
    db = tmp_path / "fresh" / "eval.db"
    db.parent.mkdir()
    sidecar = db.with_name(db.name + suffix)
    if link == "hard":
        os.link(gold, sidecar)
    else:
        sidecar.symlink_to(gold)
    out = tmp_path / "out"
    assert _eval(root, out, "--db", str(db)) == EXIT_FAILED
    assert gold.read_bytes() == before
    assert not db.exists() and not out.exists()
    assert sorted(p.name for p in db.parent.iterdir()) == [sidecar.name]  # no lock either


def test_sidecar_inside_the_data_root_holdout_is_refused(tmp_path: Path) -> None:
    root = _data_root(tmp_path)
    hold = root / "cases" / "case-hold"
    before = sorted(p.name for p in hold.iterdir())
    # the database itself is elsewhere; only a sidecar name points into holdout
    db = tmp_path / "eval.db"
    (hold / "eval.db-shm").write_text("", encoding="utf-8")
    shm = db.with_name("eval.db-shm")
    shm.symlink_to(hold / "eval.db-shm")
    assert _eval(root, tmp_path / "out", "--db", str(db)) == EXIT_FAILED
    assert sorted(p.name for p in hold.iterdir()) == sorted([*before, "eval.db-shm"])
    assert not db.exists()


def test_linked_sidecar_at_the_resolved_database_path_is_refused(tmp_path: Path) -> None:
    root = _data_root(tmp_path)
    hold = _full_holdout_copy(root, root / "cases" / "case-hold")
    gold = hold / "expected.json"
    before = gold.read_bytes()
    real = tmp_path / "real"
    real.mkdir()
    actual = real / "actual.db"
    actual.write_bytes(b"")
    os.link(gold, real / "actual.db-shm")
    alias = tmp_path / "alias.db"
    alias.symlink_to(actual)
    assert _eval(root, tmp_path / "out", "--db", str(alias)) == EXIT_FAILED
    assert gold.read_bytes() == before
    assert not (tmp_path / "out").exists()
    assert sorted(p.name for p in real.iterdir()) == ["actual.db", "actual.db-shm"]


# --- --split holdout (the one-shot holdout evaluation) -----------------------------------------


def _holdout_case(root: Path) -> Path:
    """Replace the sentinel `cases/case-hold` with a real copy of the smoke case under the
    holdout id, so a holdout evaluation has something to run."""
    hold = root / "cases" / "case-hold"
    shutil.rmtree(hold)
    shutil.copytree(SMOKE, hold)
    shutil.copy(GOLD, hold / "expected.json")
    inp = hold / "input.yaml"
    inp.write_text(
        inp.read_text(encoding="utf-8").replace("variant_id: case-smoke", "variant_id: case-hold"),
        encoding="utf-8",
    )
    (hold / "case.yaml").write_text(
        "case_id: case-hold\nsplit: holdout\nsource: mixed\ndocuments:\n"
        "  - {doc_id: D1-referral, doc_origin: authored}\n"
        "traps: [T-hold-one]\ntests: [claim.drug]\n",
        encoding="utf-8",
    )
    return hold


def _eval_holdout(root: Path | None, out: Path, *more: str) -> int:
    where = ["--data-root", str(root)] if root is not None else []
    return bridge_main(["eval", "--split", "holdout", *where, "--out", str(out), *more])


def test_holdout_without_data_root_is_refused_before_any_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("BRIDGE_FAKE_CLIENT", "1")
    opened = _record_opens(monkeypatch, CHECKOUT_ROOT)
    out = tmp_path / "out"
    assert _eval_holdout(None, out) == EXIT_FAILED
    assert "--data-root is required" in capsys.readouterr().err
    assert opened == [] and not out.exists()


def test_holdout_data_root_inside_the_checkout_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("BRIDGE_FAKE_CLIENT", "1")
    opened = _record_opens(monkeypatch, CHECKOUT_ROOT)
    out = tmp_path / "out"
    assert _eval_holdout(CHECKOUT_ROOT / "fixtures" / "synthetic", out) == EXIT_FAILED
    assert "must lie outside this checkout" in capsys.readouterr().err
    assert opened == [] and not out.exists()


@pytest.mark.parametrize("more", [["--write-baseline"], ["--baseline-from", "HEAD"]])
def test_holdout_refuses_baseline_options(
    tmp_path: Path, more: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    root = _data_root(tmp_path, with_replay=False)
    _holdout_case(root)
    baseline = CHECKOUT_ROOT / "reports" / "baseline-dev.json"
    before = baseline.read_bytes()
    out = tmp_path / "out"
    assert _eval_holdout(root, out, *more) == EXIT_FAILED
    assert "no holdout baseline" in capsys.readouterr().err
    assert not out.exists() and baseline.read_bytes() == before
    with pytest.raises(ExportError):
        run_eval(
            EvalOptions(split="holdout", data_root=root, out=out, baseline_out=tmp_path / "b.json")
        )


def test_holdout_run_scores_only_the_holdout_variant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One call per holdout variant through the (fake) client; dev rows are skipped as
    `other_split` without being opened; the report files are `eval-holdout.*`."""
    root = _data_root(tmp_path, with_replay=False)
    _holdout_case(root)
    monkeypatch.setenv("BRIDGE_FAKE_CLIENT", "1")
    opened = _record_opens(monkeypatch, root / "cases" / "case-smoke")
    out = tmp_path / "out"
    db = tmp_path / "holdout.db"
    assert _eval_holdout(root, out, "--db", str(db)) == EXIT_OK
    assert opened == []
    assert sorted(p.name for p in out.iterdir()) == ["eval-holdout.json", "eval-holdout.md"]
    report = json.loads((out / "eval-holdout.json").read_text(encoding="utf-8"))
    assert report["split"] == "holdout" and report["score"]["split"] == "holdout"
    assert report["mode"] == "online"
    assert report["skipped"] == [{"variant_id": "case-smoke", "reason": "other_split"}]
    assert set(report["score"]["cases"]) == {"case-hold"}
    case = report["score"]["cases"]["case-hold"]
    assert case["extraction_source"] == "api" and case["run_status"] == "completed"
    assert report["cost_usd"] > 0
    md = (out / "eval-holdout.md").read_text(encoding="utf-8")
    assert md.startswith("# Eval report, split=holdout, mode=online")
    assert "1 holdout variants, frozen before the run" in md
    store = open_store(db)
    try:
        [run] = store.history("case-hold")
        attempts = store.attempts_for_run(run["id"])
    finally:
        store.close()
    assert [a["attempt_no"] for a in attempts] == [1] and attempts[0]["cost_usd"] > 0
    # `check` (no allow_holdout) still refuses the same directory
    with pytest.raises(InputError):
        load_case(root / "cases" / "case-hold", root)


def test_second_holdout_pass_in_the_same_database_is_a_cache_hit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _data_root(tmp_path, with_replay=False)
    _holdout_case(root)
    monkeypatch.setenv("BRIDGE_FAKE_CLIENT", "1")
    db = tmp_path / "holdout.db"
    assert _eval_holdout(root, tmp_path / "pass1", "--db", str(db)) == EXIT_OK
    assert _eval_holdout(root, tmp_path / "pass2", "--db", str(db)) == EXIT_OK
    first, second = (
        json.loads((tmp_path / p / "eval-holdout.json").read_text(encoding="utf-8"))
        for p in ("pass1", "pass2")
    )
    assert second["score"]["cases"]["case-hold"]["extraction_source"] == "cache"
    assert second["cost_usd"] == 0.0
    store = open_store(db)
    try:
        runs = store.history("case-hold")
        attempts = [a for r in runs for a in store.attempts_for_run(r["id"])]
    finally:
        store.close()
    assert sorted(r["extraction_source"] for r in runs) == ["api", "cache"]
    assert len(attempts) == 1
    # scores are identical; only the source, run id and cost differ
    for report in (first, second):
        case = report["score"]["cases"]["case-hold"]
        for key in ("extraction_source", "run_id", "cost_usd"):
            case.pop(key)
        report.pop("cost_usd")
    assert first["score"] == second["score"]


def _attempt_count(db: Path) -> int:
    if not db.exists():
        return 0
    store = open_store(db)
    try:
        return store.count("attempts")
    finally:
        store.close()


def _holdout_refused(
    root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reason: str
) -> dict[str, Any]:
    """Run a holdout evaluation that must refuse `case-hold`: exit 3, no attempt, nothing
    of the dev variant opened; returns the report."""
    monkeypatch.setenv("BRIDGE_FAKE_CLIENT", "1")
    opened = _record_opens(monkeypatch, root / "cases" / "case-smoke")
    out = tmp_path / "out"
    db = tmp_path / "holdout.db"
    assert _eval_holdout(root, out, "--db", str(db)) == EXIT_FAILED
    assert opened == []
    assert _attempt_count(db) == 0
    report: dict[str, Any] = json.loads((out / "eval-holdout.json").read_text(encoding="utf-8"))
    assert {"variant_id": "case-hold", "reason": reason} in report["skipped"]
    assert report["score"]["cases"] == {}
    return report


def test_holdout_directory_linked_to_a_dev_variant_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _data_root(tmp_path, with_replay=False)
    hold = root / "cases" / "case-hold"
    shutil.rmtree(hold)
    hold.symlink_to(root / "cases" / "case-smoke", target_is_directory=True)
    _holdout_refused(root, tmp_path, monkeypatch, "holdout_path_refused")


def test_holdout_document_linked_to_a_dev_document_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _data_root(tmp_path, with_replay=False)
    hold = _holdout_case(root)
    doc = hold / "docs" / "D1-referral.txt"
    doc.unlink()
    doc.symlink_to(root / "cases" / "case-smoke" / "docs" / "D1-referral.txt")
    _holdout_refused(root, tmp_path, monkeypatch, "holdout_path_refused")


def test_holdout_input_naming_another_variant_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _data_root(tmp_path, with_replay=False)
    hold = _holdout_case(root)
    inp = hold / "input.yaml"
    inp.write_text(
        inp.read_text(encoding="utf-8").replace("variant_id: case-hold", "variant_id: case-smoke"),
        encoding="utf-8",
    )
    _holdout_refused(root, tmp_path, monkeypatch, "variant_mismatch")


def test_missing_holdout_directory_fails_the_evaluation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _data_root(tmp_path, with_replay=False)
    shutil.rmtree(root / "cases" / "case-hold")
    _holdout_refused(root, tmp_path, monkeypatch, "holdout_missing")


@pytest.mark.parametrize("name", ["holdout.sqlite", "sub/holdout.db"])
def test_holdout_database_inside_the_public_checkout_is_refused(
    tmp_path: Path, name: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """The holdout database holds every raw request and response (document text): it, its
    lock and its SQLite sidecars never land in the public checkout."""
    root = _data_root(tmp_path, with_replay=False)
    _holdout_case(root)
    db = CHECKOUT_ROOT / ".holdout-db-test" / name
    try:
        assert _eval_holdout(root, tmp_path / "out", "--db", str(db)) == EXIT_FAILED
        assert "inside the public checkout" in capsys.readouterr().err
        assert not (CHECKOUT_ROOT / ".holdout-db-test").exists()
        assert not (tmp_path / "out").exists()
    finally:
        shutil.rmtree(CHECKOUT_ROOT / ".holdout-db-test", ignore_errors=True)


# --- holdout anchors, temporary database and batch preflight (second review) ------------------


def test_holdout_cases_parent_linked_elsewhere_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`<data-root>/cases` itself is a link: the anchor comes from the verified data root,
    so the real `case-hold` behind the link is never opened."""
    root = _data_root(tmp_path, with_replay=False)
    _holdout_case(root)
    other = tmp_path / "other"
    other.mkdir()
    shutil.move(str(root / "cases"), str(other / "cases"))
    (root / "cases").symlink_to(other / "cases", target_is_directory=True)
    opened = _record_opens(monkeypatch, other)
    _holdout_refused(root, tmp_path, monkeypatch, "holdout_path_refused")
    assert opened == []


@pytest.mark.parametrize("linked", ["variant_dir", "replays_dir"])
def test_holdout_replay_behind_a_link_is_never_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, linked: str
) -> None:
    """Offline holdout: `replays/<vid>/` or the whole `replays/` is a link; the file at the
    expected replay name behind it is refused before it is opened."""
    root = _data_root(tmp_path, with_replay=False)
    hold = _holdout_case(root)
    input_hash = load_case(hold, root, allow_holdout=True).input_hash
    elsewhere = tmp_path / "elsewhere" / "replays"
    target = replay_path(elsewhere, "case-hold", input_hash, PROMPT_VERSION, SCHEMA_VERSION)
    target.parent.mkdir(parents=True)
    target.write_text("{}", encoding="utf-8")
    if linked == "variant_dir":
        (root / "replays").mkdir()
        (root / "replays" / "case-hold").symlink_to(target.parent, target_is_directory=True)
    else:
        (root / "replays").symlink_to(elsewhere, target_is_directory=True)
    opened = _record_opens(monkeypatch, tmp_path / "elsewhere")
    out = tmp_path / "out"
    db = tmp_path / "holdout.db"
    assert _eval_holdout(root, out, "--offline", "--db", str(db)) == EXIT_FAILED
    assert opened == []
    report = json.loads((out / "eval-holdout.json").read_text(encoding="utf-8"))
    assert report["score"]["cases"]["case-hold"]["run_status"] == "failed"


def test_holdout_default_database_in_a_checkout_tmpdir_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without `--db` the database is a temporary file; when the temporary directory lies
    in the public checkout, the holdout evaluation is refused before it is created."""
    root = _data_root(tmp_path, with_replay=False)
    _holdout_case(root)
    monkeypatch.setenv("BRIDGE_FAKE_CLIENT", "1")
    inside = CHECKOUT_ROOT / ".holdout-tmpdir-test"
    inside.mkdir()
    try:
        monkeypatch.setattr(tempfile, "tempdir", str(inside))
        assert _eval_holdout(root, tmp_path / "out") == EXIT_FAILED
        assert "public checkout" in capsys.readouterr().err
        assert list(inside.iterdir()) == []
    finally:
        shutil.rmtree(inside, ignore_errors=True)


def _holdout_pair_manifest(root: Path, order: list[str]) -> None:
    rows = "".join(
        f"  - case_id: {vid}\n    variant_id: {vid}\n    split: holdout\n"
        f"    frozen_at: 2026-11-10\n    gold_version: 1\n"
        f"    files: {{input.yaml: {'3' * 64}, expected.json: {'3' * 64}}}\n"
        for vid in order
    )
    (root / "splits.yaml").write_text(f"version: 1\nvariants:\n{rows}", encoding="utf-8")


@pytest.mark.parametrize("order", [["case-hold", "case-gone"], ["case-gone", "case-hold"]])
def test_holdout_batch_with_a_refused_row_runs_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, order: list[str]
) -> None:
    """Every selected holdout row is checked before the first extraction: one refused row
    (here a missing directory) leaves the whole batch at zero attempts."""
    root = _data_root(tmp_path, with_replay=False)
    _holdout_case(root)
    _holdout_pair_manifest(root, order)
    monkeypatch.setenv("BRIDGE_FAKE_CLIENT", "1")
    out = tmp_path / "out"
    db = tmp_path / "holdout.db"
    assert _eval_holdout(root, out, "--db", str(db)) == EXIT_FAILED
    assert _attempt_count(db) == 0
    report = json.loads((out / "eval-holdout.json").read_text(encoding="utf-8"))
    assert {s["variant_id"]: s["reason"] for s in report["skipped"]} == {
        "case-gone": "holdout_missing",
        "case-hold": "batch_refused",
    }
    assert report["score"]["cases"] == {}
