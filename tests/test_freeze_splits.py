"""Tests for scripts/freeze_splits.py using a throwaway git repo in tmp_path."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
FREEZE = ROOT / "scripts" / "freeze_splits.py"
ZERO_SHA = "0" * 40


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(repo: Path, *args: str) -> str:
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "HOME": str(repo),
        "PATH": "/usr/bin:/bin:/usr/local/bin",
    }
    result = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True, env=env
    )
    return result.stdout.strip()


def _run(repo: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(FREEZE), "--check", "--root", str(repo), *extra]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _write_manifest(repo: Path, variants: list[dict[str, Any]]) -> None:
    (repo / "splits.yaml").write_text(
        yaml.safe_dump({"version": 1, "variants": variants}, sort_keys=False), encoding="utf-8"
    )


def _make_variant(repo: Path, variant_id: str, *, mtsamples: bool = False) -> dict[str, Any]:
    case_dir = repo / "cases" / variant_id
    (case_dir / "docs").mkdir(parents=True)
    (case_dir / "input.yaml").write_text(f"variant_id: {variant_id}\n", encoding="utf-8")
    (case_dir / "docs" / "D1-referral.txt").write_text("referral\n", encoding="utf-8")
    facts: list[dict[str, Any]] = [
        {"field": "anthropometrics", "doc_id": "D1-referral", "quote": "BMI 36"},
    ]
    files = ["input.yaml", "docs/D1-referral.txt", "expected.json"]
    if mtsamples:
        (case_dir / "docs" / "D2-mtsamples-4985.txt").write_text("transcript\n", encoding="utf-8")
        facts.append(
            {"field": "anthropometrics", "doc_id": "D2-mtsamples-4985", "quote_sha256": "ab" * 32}
        )
        files.insert(2, "docs/D2-mtsamples-4985.txt")
    (case_dir / "expected.json").write_text(json.dumps({"facts": facts}), encoding="utf-8")
    return {
        "case_id": variant_id,
        "variant_id": variant_id,
        "split": "dev",
        "frozen_at": "2026-11-08",
        "gold_version": 1,
        "files": {rel: _sha(case_dir / rel) for rel in files},
    }


def _rehash(repo: Path, variant: dict[str, Any]) -> None:
    case_dir = repo / "cases" / variant["variant_id"]
    variant["files"] = {rel: _sha(case_dir / rel) for rel in variant["files"]}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo with one frozen variant committed on `main`."""
    _git(tmp_path, "init", "-q", "-b", "main")
    variant = _make_variant(tmp_path, "case-01")
    _write_manifest(tmp_path, [variant])
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "freeze case-01")
    return tmp_path


def _load_variants(repo: Path) -> list[dict[str, Any]]:
    data: dict[str, Any] = yaml.safe_load((repo / "splits.yaml").read_text(encoding="utf-8"))
    variants: list[dict[str, Any]] = data["variants"]
    return variants


def test_bootstrap_mode_when_base_missing_empty_or_zero(repo: Path) -> None:
    for base in ([], ["--base", ""], ["--base", ZERO_SHA], ["--base", "no-such-ref"]):
        result = _run(repo, *base)
        assert result.returncode == 0, result.stderr
        assert "bootstrap mode" in result.stdout


def test_unchanged_manifest_passes_against_base(repo: Path) -> None:
    result = _run(repo, "--base", "main")
    assert result.returncode == 0, result.stderr
    assert "bootstrap" not in result.stdout
    assert "1 variants" in result.stdout


def test_adding_a_variant_passes(repo: Path) -> None:
    variants = _load_variants(repo)
    variants.append(_make_variant(repo, "case-02"))
    _write_manifest(repo, variants)
    result = _run(repo, "--base", "main")
    assert result.returncode == 0, result.stderr


def test_removing_a_variant_fails(repo: Path) -> None:
    _write_manifest(repo, [])
    result = _run(repo, "--base", "main")
    assert result.returncode == 1
    assert "frozen variant removed" in result.stderr


def test_changing_split_fails(repo: Path) -> None:
    variants = _load_variants(repo)
    variants[0]["split"] = "holdout"
    _write_manifest(repo, variants)
    result = _run(repo, "--base", "main")
    assert result.returncode == 1
    assert "split changed" in result.stderr


def test_changing_non_gold_file_fails_even_with_gold_bump(repo: Path) -> None:
    variants = _load_variants(repo)
    (repo / "cases" / "case-01" / "input.yaml").write_text("changed\n", encoding="utf-8")
    variants[0]["gold_version"] = 2
    _rehash(repo, variants[0])
    _write_manifest(repo, variants)
    result = _run(repo, "--base", "main")
    assert result.returncode == 1
    assert "without a new gold" in result.stderr


def test_changing_gold_with_higher_version_passes(repo: Path) -> None:
    variants = _load_variants(repo)
    gold = repo / "cases" / "case-01" / "expected.json"
    gold.write_text(json.dumps({"facts": [], "changes": ["fix"]}), encoding="utf-8")
    variants[0]["gold_version"] = 2
    _rehash(repo, variants[0])
    _write_manifest(repo, variants)
    result = _run(repo, "--base", "main")
    assert result.returncode == 0, result.stderr


def test_changing_gold_with_same_version_fails(repo: Path) -> None:
    variants = _load_variants(repo)
    gold = repo / "cases" / "case-01" / "expected.json"
    gold.write_text(json.dumps({"facts": [], "changes": ["fix"]}), encoding="utf-8")
    _rehash(repo, variants[0])
    _write_manifest(repo, variants)
    result = _run(repo, "--base", "main")
    assert result.returncode == 1
    assert "gold_version did not increase" in result.stderr


def test_hash_mismatch_fails(repo: Path) -> None:
    (repo / "cases" / "case-01" / "docs" / "D1-referral.txt").write_text(
        "edited\n", encoding="utf-8"
    )
    result = _run(repo)
    assert result.returncode == 1
    assert "sha256 mismatch" in result.stderr
    assert "edited" not in result.stderr  # never print document text


def test_missing_non_mtsamples_file_fails(repo: Path) -> None:
    (repo / "cases" / "case-01" / "docs" / "D1-referral.txt").unlink()
    result = _run(repo)
    assert result.returncode == 1
    assert "file missing" in result.stderr


def test_mtsamples_fact_with_quote_fails(tmp_path: Path) -> None:
    variant = _make_variant(tmp_path, "case-01", mtsamples=True)
    gold = tmp_path / "cases" / "case-01" / "expected.json"
    data = json.loads(gold.read_text(encoding="utf-8"))
    data["facts"][1]["quote"] = "leaked text"
    gold.write_text(json.dumps(data), encoding="utf-8")
    _rehash(tmp_path, variant)
    _write_manifest(tmp_path, [variant])
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "must not contain 'quote'" in result.stderr
    assert "leaked text" not in result.stderr


def test_mtsamples_fact_without_quote_sha256_fails(tmp_path: Path) -> None:
    variant = _make_variant(tmp_path, "case-01", mtsamples=True)
    gold = tmp_path / "cases" / "case-01" / "expected.json"
    data = json.loads(gold.read_text(encoding="utf-8"))
    del data["facts"][1]["quote_sha256"]
    gold.write_text(json.dumps(data), encoding="utf-8")
    _rehash(tmp_path, variant)
    _write_manifest(tmp_path, [variant])
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "must contain 'quote_sha256'" in result.stderr


def test_mtsamples_variant_passes_when_externalized(tmp_path: Path) -> None:
    variant = _make_variant(tmp_path, "case-01", mtsamples=True)
    _write_manifest(tmp_path, [variant])
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr


def test_missing_mtsamples_doc_gives_fetch_hint(tmp_path: Path) -> None:
    variant = _make_variant(tmp_path, "case-01", mtsamples=True)
    _write_manifest(tmp_path, [variant])
    (tmp_path / "cases" / "case-01" / "docs" / "D2-mtsamples-4985.txt").unlink()
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "run scripts/fetch_mtsamples.py first" in result.stderr


def test_invalid_split_value_is_rejected(tmp_path: Path) -> None:
    variant = _make_variant(tmp_path, "case-01")
    variant["split"] = "test"
    _write_manifest(tmp_path, [variant])
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "split" in result.stderr


def test_variant_id_aliasing_a_frozen_directory_is_rejected(repo: Path) -> None:
    """A second entry pointing at the same directory via a path must not pass (P1)."""
    variants = _load_variants(repo)
    variants[0]["split"] = "holdout"
    _write_manifest(repo, variants)
    _git(repo, "commit", "-q", "-am", "holdout")
    alias = dict(variants[0])
    alias["variant_id"] = "../cases/case-01"
    alias["split"] = "dev"
    _write_manifest(repo, variants + [alias])
    result = _run(repo, "--base", "main")
    assert result.returncode == 1
    assert "variant_id" in result.stderr


@pytest.mark.parametrize("bad_id", ["a/b", "..", ".hidden", "-x", "case 01", ""])
def test_unsafe_variant_id_is_rejected(tmp_path: Path, bad_id: str) -> None:
    variant = _make_variant(tmp_path, "case-01")
    variant["variant_id"] = bad_id
    _write_manifest(tmp_path, [variant])
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "variant_id" in result.stderr


def test_unlisted_gold_is_rejected(tmp_path: Path) -> None:
    variant = _make_variant(tmp_path, "case-01")
    del variant["files"]["expected.json"]
    _write_manifest(tmp_path, [variant])
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "expected.json is not listed" in result.stderr


def test_unlisted_doc_on_disk_is_rejected(tmp_path: Path) -> None:
    variant = _make_variant(tmp_path, "case-01")
    (tmp_path / "cases" / "case-01" / "docs" / "D3-extra.txt").write_text("x\n", encoding="utf-8")
    _write_manifest(tmp_path, [variant])
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "docs/D3-extra.txt exists but is not listed" in result.stderr


def test_unexpected_git_error_fails_instead_of_bootstrapping(tmp_path: Path) -> None:
    """Not a git repository is not 'no base manifest' — it must fail (P2)."""
    variant = _make_variant(tmp_path, "case-01")
    _write_manifest(tmp_path, [variant])
    result = _run(tmp_path, "--base", "main")
    assert result.returncode == 1
    assert "cannot read splits.yaml" in result.stderr
    assert "bootstrap" not in result.stdout


def test_missing_manifest_at_valid_ref_is_bootstrap(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "README.md").write_text("x\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init")
    variant = _make_variant(tmp_path, "case-01")
    _write_manifest(tmp_path, [variant])
    result = _run(tmp_path, "--base", "main")
    assert result.returncode == 0, result.stderr
    assert "bootstrap mode" in result.stdout
