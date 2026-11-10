"""`reports/baseline-dev.json` may change only with `[update baseline]` in the PR title,
and never disappear (contract §11): `baseline.baseline_change_problem`,
`scripts/check_baseline_title.py`, `load_baseline_at` bootstrap, and the thin
`scripts/build_baseline.py` wrapper."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
from conftest import FIXTURES, ROOT, load_script

from bridge_check.baseline import (
    BASELINE_PATH,
    UPDATE_MARKER,
    ZERO_SHA,
    baseline_change_problem,
    load_baseline_at,
)
from bridge_check.baseline_schema import Baseline

COMMITTED = ROOT / BASELINE_PATH


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@x",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@x",
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        },
    )


def _baseline_json() -> str:
    data: dict[str, Any] = json.loads(COMMITTED.read_text(encoding="utf-8"))
    return json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo whose `main` holds the committed baseline."""
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "reports").mkdir()
    (tmp_path / BASELINE_PATH).write_text(_baseline_json(), encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "baseline")
    return tmp_path


def test_unchanged_baseline_is_fine(repo: Path) -> None:
    assert baseline_change_problem("main", "feat: anything", repo) is None


def test_changed_baseline_needs_the_marker(repo: Path) -> None:
    path = repo / BASELINE_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    data["generated_from"]["code_sha"] = "0" * 40
    path.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    problem = baseline_change_problem("main", "fix: something", repo)
    assert problem is not None and UPDATE_MARKER in problem
    assert baseline_change_problem("main", f"fix: something {UPDATE_MARKER}", repo) is None


def test_deleted_baseline_always_fails(repo: Path) -> None:
    (repo / BASELINE_PATH).unlink()
    for title in ("chore: x", f"chore: x {UPDATE_MARKER}"):
        problem = baseline_change_problem("main", title, repo)
        assert problem is not None and "deleted" in problem


def test_bootstrap_when_base_has_no_baseline(
    repo: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    for ref in (None, "", ZERO_SHA):
        assert baseline_change_problem(ref, "feat: x", repo) is None
        baseline, raw, problem = load_baseline_at(ref, repo)
        assert baseline is None and raw is None and problem is None
    # a valid ref whose commit has no baseline is bootstrap too
    _git(repo, "rm", "-q", BASELINE_PATH.as_posix())
    _git(repo, "commit", "-q", "-m", "no baseline")
    baseline, raw, problem = load_baseline_at("HEAD", repo)
    assert baseline is None and raw is None and problem is None
    assert baseline_change_problem("HEAD", "feat: x", repo) is None
    baseline, raw, problem = load_baseline_at("HEAD~1", repo)
    assert isinstance(baseline, Baseline) and raw is not None and problem is None
    outside = tmp_path_factory.mktemp("not-a-repo")  # a sibling of the repo, not inside it
    _, _, problem = load_baseline_at("main", outside)
    assert problem is not None  # a broken repository is not bootstrap


def test_unresolvable_ref_is_a_problem_not_bootstrap(repo: Path) -> None:
    for ref in ("no-such-ref", "0123456789abcdef0123456789abcdef01234567", "main:oops"):
        baseline, raw, problem = load_baseline_at(ref, repo)
        assert baseline is None and raw is None and problem is not None
        assert baseline_change_problem(ref, "feat: x", repo) == problem
    script = load_script("check_baseline_title")
    assert script.main(["--base", "no-such-ref", "--title", "x", "--root", str(repo)]) == 1


def test_invalid_baseline_at_base_is_a_problem(repo: Path) -> None:
    (repo / BASELINE_PATH).write_text("{}\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "broken")
    _, raw, problem = load_baseline_at("main", repo)
    assert raw is not None and problem is not None


def test_check_baseline_title_script(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    script = load_script("check_baseline_title")
    assert script.main(["--base", "main", "--title", "feat: x", "--root", str(repo)]) == 0
    (repo / BASELINE_PATH).unlink()
    assert script.main(["--base", "main", "--title", "feat: x", "--root", str(repo)]) == 1
    err = capsys.readouterr().err
    assert "deleted" in err and "feat: x" not in err


def test_committed_baseline_matches_its_own_base_shape() -> None:
    assert baseline_change_problem("HEAD", "x", ROOT) is None or COMMITTED.read_bytes() != b""


def test_build_baseline_script_still_builds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bridge_check.cli import main as bridge_main

    monkeypatch.setenv("BRIDGE_FAKE_CLIENT", "1")
    db = tmp_path / "bridge.db"
    assert bridge_main(["check", str(FIXTURES / "case-smoke"), "--db", str(db)]) == 0
    script = load_script("build_baseline")
    out = tmp_path / "baseline.json"
    # the smoke case is not a dev variant of the real manifest: every dev variant must have
    # a completed run, so the build is refused with exit 1 and nothing is written
    assert script.main(["--db", str(db), "--out", str(out)]) == 1
    assert not out.exists()


def _record_opens(monkeypatch: pytest.MonkeyPatch, inside: Path) -> list[str]:
    import builtins
    import io

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


def test_linked_head_baseline_is_refused_before_any_read(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hold = repo / "cases" / "case-hold"
    hold.mkdir(parents=True)
    gold = hold / "expected.json"
    gold.write_text('{"synthetic": "holdout gold"}\n', encoding="utf-8")
    (repo / "splits.yaml").write_text(
        "version: 1\nvariants:\n  - {case_id: case-hold, variant_id: case-hold, split: holdout}\n",
        encoding="utf-8",
    )
    head = repo / BASELINE_PATH
    head.unlink()
    head.symlink_to(gold)
    opened = _record_opens(monkeypatch, hold)
    for title in ("feat: x", f"feat: x {UPDATE_MARKER}"):
        problem = baseline_change_problem("main", title, repo)
        assert problem is not None and "link" in problem
    assert opened == []
    script = load_script("check_baseline_title")
    assert script.main(["--base", "main", "--title", UPDATE_MARKER, "--root", str(repo)]) == 1
    assert opened == []
    # a hard-linked head is refused the same way
    head.unlink()
    os.link(gold, head)
    problem = baseline_change_problem("main", UPDATE_MARKER, repo)
    assert problem is not None and "hard links" in problem


def test_build_baseline_script_uses_the_protected_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--out` as a hard link to a synthetic holdout gold: refused, gold untouched; a
    symbolic link likewise; a plain path is written atomically."""
    script = load_script("build_baseline")
    data = json.loads(COMMITTED.read_text(encoding="utf-8"))
    monkeypatch.setattr(script, "build", lambda store, runs, root: data)
    db = tmp_path / "any.db"
    db.write_bytes(b"")  # exists; `open_store` creates the schema, `build` is stubbed
    gold = tmp_path / "expected-synthetic.json"
    gold.write_text('{"synthetic": "holdout gold"}\n', encoding="utf-8")
    before = gold.read_bytes()
    out = tmp_path / "out" / "baseline-dev.json"
    out.parent.mkdir()
    os.link(gold, out)
    assert script.main(["--db", str(db), "--out", str(out)]) == 2
    assert gold.read_bytes() == before and os.lstat(gold).st_nlink == 2
    out.unlink()
    out.symlink_to(gold)
    assert script.main(["--db", str(db), "--out", str(out)]) == 2
    assert gold.read_bytes() == before
    out.unlink()
    assert script.main(["--db", str(db), "--out", str(out)]) == 0
    assert out.is_file() and not out.is_symlink() and os.lstat(out).st_nlink == 1
    assert json.loads(out.read_text(encoding="utf-8")) == data
    assert sorted(p.name for p in out.parent.iterdir()) == ["baseline-dev.json"]


def test_build_baseline_script_refuses_a_linked_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = load_script("build_baseline")
    monkeypatch.setattr(script, "build", lambda store, runs, root: {})
    gold = tmp_path / "expected-synthetic.json"
    gold.write_text('{"synthetic": "holdout gold"}\n', encoding="utf-8")
    before = gold.read_bytes()
    db = tmp_path / "any.db"
    db.write_bytes(b"")
    os.link(gold, db.with_name("any.db-shm"))
    assert script.main(["--db", str(db), "--out", str(tmp_path / "b.json")]) == 2
    assert gold.read_bytes() == before and not (tmp_path / "b.json").exists()


def test_build_baseline_script_checks_sidecars_at_the_resolved_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--db alias.db` is a link to `actual.db`; `actual.db-shm` shares its inode with a
    synthetic gold. SQLite would use the resolved path, so the guard must look there."""
    script = load_script("build_baseline")
    monkeypatch.setattr(script, "build", lambda store, runs, root: {})
    gold = tmp_path / "expected-synthetic.json"
    gold.write_text('{"synthetic": "holdout gold"}\n', encoding="utf-8")
    before = gold.read_bytes()
    real = tmp_path / "real"
    real.mkdir()
    actual = real / "actual.db"
    actual.write_bytes(b"")
    os.link(gold, real / "actual.db-shm")
    alias = tmp_path / "alias.db"
    alias.symlink_to(actual)
    assert script.main(["--db", str(alias), "--out", str(tmp_path / "b.json")]) == 2
    assert gold.read_bytes() == before and os.lstat(gold).st_nlink == 2
    assert not (tmp_path / "b.json").exists()
    assert sorted(p.name for p in real.iterdir()) == ["actual.db", "actual.db-shm"]
