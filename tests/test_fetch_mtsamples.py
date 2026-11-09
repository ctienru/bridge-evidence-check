"""Offline tests for scripts/fetch_mtsamples.py with a synthetic CSV (no network)."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import pytest
import yaml
from conftest import load_script

fetch = load_script("fetch_mtsamples")

NAME = "Synthetic Consult - 1"
TEXT = "SUBJECTIVE:,  Synthetic transcript line one.\r\nPLAN:,  Line two with trailing spaces.   "
OTHER = "A different synthetic transcript."


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_csv(path: Path, rows: list[tuple[str, str]]) -> str:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["", "description", "medical_specialty", "sample_name", "transcription", "keywords"]
        )
        for index, (name, text) in enumerate(rows):
            writer.writerow([str(index), "desc", "spec", f" {name} ", text, "kw"])
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_case(root: Path, *, csv_sha: str, prefix: str | None = None, row: int = 1) -> Path:
    case_dir = root / "cases" / "case-syn"
    case_dir.mkdir(parents=True)
    block = {
        "dataset": "synthetic",
        "url": "https://example.invalid/mtsamples.csv",
        "dataset_sha256": csv_sha,
        "row": row,
        "sample_name": NAME,
        "transcription_sha256_prefix": prefix or _sha(TEXT)[:12],
        "doc_id": "D2-mtsamples-0001",
    }
    (case_dir / "case.yaml").write_text(
        yaml.safe_dump({"case_id": "case-syn", "mtsamples": block}, sort_keys=False),
        encoding="utf-8",
    )
    return case_dir


def _run(root: Path, csv_path: Path) -> int:
    return int(
        fetch.main(["--case", "case-syn", "--offline", "--csv", str(csv_path), "--root", str(root)])
    )


def test_success_writes_byte_exact_file_with_crlf(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    csv_path = tmp_path / "m.csv"
    sha = _write_csv(csv_path, [("Other Note", OTHER), (NAME, TEXT), (NAME, OTHER)])
    _make_case(tmp_path, csv_sha=sha)
    assert _run(tmp_path, csv_path) == 0
    out = tmp_path / "cases" / "case-syn" / "docs" / "D2-mtsamples-0001.txt"
    assert out.read_bytes() == TEXT.encode("utf-8")  # CRLF and trailing spaces preserved
    printed = capsys.readouterr()
    assert "written" in printed.out and "row 1" in printed.out
    assert "Synthetic transcript" not in printed.out + printed.err


def test_refetch_over_existing_file_passes_and_keeps_bytes(tmp_path: Path) -> None:
    csv_path = tmp_path / "m.csv"
    sha = _write_csv(csv_path, [(NAME, TEXT)])
    _make_case(tmp_path, csv_sha=sha)
    assert _run(tmp_path, csv_path) == 0
    assert _run(tmp_path, csv_path) == 0  # fetch may replace its own verified document
    out = tmp_path / "cases" / "case-syn" / "docs" / "D2-mtsamples-0001.txt"
    assert out.read_bytes() == TEXT.encode("utf-8")


def test_duplicate_identical_rows_are_accepted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    csv_path = tmp_path / "m.csv"
    sha = _write_csv(csv_path, [(NAME, TEXT), ("x", OTHER), (NAME, TEXT)])
    _make_case(tmp_path, csv_sha=sha, row=2)
    assert _run(tmp_path, csv_path) == 0
    assert "row 2" in capsys.readouterr().out


def test_wrong_dataset_hash_exits_1_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    csv_path = tmp_path / "m.csv"
    _write_csv(csv_path, [(NAME, TEXT)])
    _make_case(tmp_path, csv_sha="0" * 64)
    assert _run(tmp_path, csv_path) == 1
    assert "dataset_sha256 failed" in capsys.readouterr().err
    assert not (tmp_path / "cases" / "case-syn" / "docs").exists()


def test_wrong_prefix_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    csv_path = tmp_path / "m.csv"
    sha = _write_csv(csv_path, [(NAME, TEXT)])
    _make_case(tmp_path, csv_sha=sha, prefix="deadbeefcafe")
    assert _run(tmp_path, csv_path) == 1
    assert "no_matching_row failed" in capsys.readouterr().err


def test_differing_duplicates_are_ambiguous(tmp_path: Path) -> None:
    """Two rows with the same name whose texts differ but share the hash prefix → error.

    Real texts never share a 12-hex prefix by accident, so the hash function is injected.
    """
    csv_path = tmp_path / "m.csv"
    sha = _write_csv(csv_path, [(NAME, TEXT), (NAME, OTHER)])
    case_dir = _make_case(tmp_path, csv_sha=sha, prefix="deadbeefcafe")
    block = fetch.load_block(case_dir / "case.yaml")
    assert block is not None
    with pytest.raises(fetch.FetchError) as excinfo:
        fetch.select_transcription(csv_path, block, text_hash=lambda _text: "deadbeefcafe" * 5)
    assert excinfo.value.check == "ambiguous_rows"
    assert "Synthetic" not in excinfo.value.detail
    # identical duplicates with the injected hash are fine
    sha = _write_csv(csv_path, [(NAME, TEXT), (NAME, TEXT)])
    text, rows = fetch.select_transcription(csv_path, block, text_hash=lambda _t: "deadbeefcafe")
    assert text == TEXT and rows == [0, 1]


def test_manifest_hash_mismatch_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    csv_path = tmp_path / "m.csv"
    sha = _write_csv(csv_path, [(NAME, TEXT)])
    _make_case(tmp_path, csv_sha=sha)
    manifest = {
        "version": 1,
        "variants": [
            {
                "case_id": "case-syn",
                "variant_id": "case-syn",
                "split": "dev",
                "frozen_at": "2026-11-08",
                "gold_version": 1,
                "files": {"docs/D2-mtsamples-0001.txt": "ab" * 32},
            }
        ],
    }
    (tmp_path / "splits.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    assert _run(tmp_path, csv_path) == 1
    assert "manifest_sha256 failed" in capsys.readouterr().err
    manifest["variants"][0]["files"]["docs/D2-mtsamples-0001.txt"] = _sha(TEXT)  # type: ignore[index]
    (tmp_path / "splits.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    assert _run(tmp_path, csv_path) == 0
    assert "matches splits.yaml" in capsys.readouterr().out


def _manifest(files: dict[str, str], split: str = "dev") -> dict[str, object]:
    return {
        "version": 1,
        "variants": [
            {
                "case_id": "case-syn",
                "variant_id": "case-syn",
                "split": split,
                "frozen_at": "2026-11-08",
                "gold_version": 1,
                "files": files,
            }
        ],
    }


def test_manifest_mismatch_leaves_existing_file_untouched(tmp_path: Path) -> None:
    csv_path = tmp_path / "m.csv"
    sha = _write_csv(csv_path, [(NAME, TEXT)])
    case_dir = _make_case(tmp_path, csv_sha=sha)
    out = case_dir / "docs" / "D2-mtsamples-0001.txt"
    out.parent.mkdir()
    out.write_bytes(b"previously frozen bytes\r\n")
    (tmp_path / "splits.yaml").write_text(
        yaml.safe_dump(_manifest({"docs/D2-mtsamples-0001.txt": "ab" * 32})), encoding="utf-8"
    )
    assert _run(tmp_path, csv_path) == 1
    assert out.read_bytes() == b"previously frozen bytes\r\n"
    assert list(out.parent.iterdir()) == [out]  # no temp file left behind


def test_frozen_variant_without_doc_entry_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    csv_path = tmp_path / "m.csv"
    sha = _write_csv(csv_path, [(NAME, TEXT)])
    _make_case(tmp_path, csv_sha=sha)
    (tmp_path / "splits.yaml").write_text(
        yaml.safe_dump(_manifest({"input.yaml": "ab" * 32})), encoding="utf-8"
    )
    assert _run(tmp_path, csv_path) == 1
    assert "manifest_entry_missing failed" in capsys.readouterr().err
    assert not (tmp_path / "cases" / "case-syn" / "docs").exists()


def test_holdout_variant_is_skipped_or_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    csv_path = tmp_path / "m.csv"
    sha = _write_csv(csv_path, [(NAME, TEXT)])
    _make_case(tmp_path, csv_sha=sha)
    (tmp_path / "splits.yaml").write_text(
        yaml.safe_dump(_manifest({"docs/D2-mtsamples-0001.txt": _sha(TEXT)}, split="holdout")),
        encoding="utf-8",
    )
    assert _run(tmp_path, csv_path) == 1
    assert "holdout variant, refused" in capsys.readouterr().err
    assert fetch.main(["--offline", "--csv", str(csv_path), "--root", str(tmp_path)]) == 0
    assert "skipped (holdout)" in capsys.readouterr().out
    assert not (tmp_path / "cases" / "case-syn" / "docs").exists()


def test_symlinked_dev_name_into_holdout_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    csv_path = tmp_path / "m.csv"
    sha = _write_csv(csv_path, [(NAME, TEXT)])
    hold = _make_case(tmp_path, csv_sha=sha)  # cases/case-syn becomes the holdout
    (tmp_path / "splits.yaml").write_text(
        yaml.safe_dump(_manifest({"docs/D2-mtsamples-0001.txt": _sha(TEXT)}, split="holdout")),
        encoding="utf-8",
    )
    (hold / "docs").mkdir()
    frozen = hold / "docs" / "D2-mtsamples-0001.txt"
    frozen.write_bytes(b"frozen holdout bytes")
    (tmp_path / "cases" / "case-dev").symlink_to(hold, target_is_directory=True)
    code = fetch.main(
        ["--case", "case-dev", "--offline", "--csv", str(csv_path), "--root", str(tmp_path)]
    )
    assert code == 1
    assert "holdout" in capsys.readouterr().err
    assert frozen.read_bytes() == b"frozen holdout bytes"
    # batch mode: the link is refused as well, the real holdout dir is skipped
    assert fetch.main(["--offline", "--csv", str(csv_path), "--root", str(tmp_path)]) == 1
    assert frozen.read_bytes() == b"frozen holdout bytes"


def test_holdout_directory_linked_from_outside_is_still_holdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "repo"
    outside = tmp_path / "elsewhere" / "case-syn"
    (outside / "docs").mkdir(parents=True)
    csv_path = tmp_path / "m.csv"
    sha = _write_csv(csv_path, [(NAME, TEXT)])
    (root / "cases").mkdir(parents=True)
    (root / "cases" / "case-syn").symlink_to(outside, target_is_directory=True)
    block = {
        "dataset": "synthetic",
        "url": "https://example.invalid/m.csv",
        "dataset_sha256": sha,
        "row": 0,
        "sample_name": NAME,
        "transcription_sha256_prefix": _sha(TEXT)[:12],
        "doc_id": "D2-mtsamples-0001",
    }
    (outside / "case.yaml").write_text(yaml.safe_dump({"mtsamples": block}), encoding="utf-8")
    (root / "splits.yaml").write_text(
        yaml.safe_dump(_manifest({"docs/D2-mtsamples-0001.txt": _sha(TEXT)}, split="holdout")),
        encoding="utf-8",
    )
    assert (
        fetch.main(["--case", "case-syn", "--offline", "--csv", str(csv_path), "--root", str(root)])
        == 1
    )
    assert "holdout" in capsys.readouterr().err
    assert not (outside / "docs" / "D2-mtsamples-0001.txt").exists()
    # and a CSV that lives inside a holdout case is refused as input
    inside_csv = outside / "m.csv"
    inside_csv.write_bytes(csv_path.read_bytes())
    code = fetch.main(
        ["--offline", "--csv", str(root / "cases" / "case-syn" / "m.csv"), "--root", str(root)]
    )
    assert code == 1 and "--csv" in capsys.readouterr().err


def test_linked_docs_dir_cannot_overwrite_another_frozen_case(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    csv_path = tmp_path / "m.csv"
    sha = _write_csv(csv_path, [(NAME, TEXT)])
    case_a = _make_case(tmp_path, csv_sha=sha)  # cases/case-syn
    case_b = tmp_path / "cases" / "case-other" / "docs"
    case_b.mkdir(parents=True)
    frozen = case_b / "D2-mtsamples-0001.txt"
    frozen.write_bytes(b"frozen bytes of the other case")
    (case_a / "docs").symlink_to(case_b, target_is_directory=True)
    assert _run(tmp_path, csv_path) == 1
    assert "destination_alias" in capsys.readouterr().err
    assert frozen.read_bytes() == b"frozen bytes of the other case"


def test_case_yaml_linked_into_holdout_is_not_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    csv_path = tmp_path / "m.csv"
    sha = _write_csv(csv_path, [(NAME, TEXT)])
    hold = _make_case(tmp_path, csv_sha=sha)  # cases/case-syn is the holdout
    (tmp_path / "splits.yaml").write_text(
        yaml.safe_dump(_manifest({"docs/D2-mtsamples-0001.txt": _sha(TEXT)}, split="holdout")),
        encoding="utf-8",
    )
    dev = tmp_path / "cases" / "case-dev"
    dev.mkdir()
    (dev / "case.yaml").symlink_to(hold / "case.yaml")
    code = fetch.main(
        ["--case", "case-dev", "--offline", "--csv", str(csv_path), "--root", str(tmp_path)]
    )
    assert code == 1 and "holdout" in capsys.readouterr().err
    assert not (dev / "docs").exists()


def test_bad_case_yaml_prints_no_snippet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    csv_path = tmp_path / "m.csv"
    _write_csv(csv_path, [(NAME, TEXT)])
    case_dir = tmp_path / "cases" / "case-syn"
    case_dir.mkdir(parents=True)
    (case_dir / "case.yaml").write_text("mtsamples: [secret line\n  - :: bad", encoding="utf-8")
    assert _run(tmp_path, csv_path) == 1
    err = capsys.readouterr().err
    assert "case_yaml_invalid failed" in err and "secret" not in err


def test_temp_file_name_is_covered_by_gitignore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The temp file is created under the ignored `D2-mtsamples-*.txt` pattern and removed."""
    import fnmatch

    seen: list[Path] = []
    real_replace = fetch.os.replace

    def spy(src: str | Path, dst: str | Path) -> None:
        seen.append(Path(src))
        real_replace(src, dst)

    monkeypatch.setattr(fetch.os, "replace", spy)
    target = tmp_path / "cases" / "case-syn" / "docs" / "D2-mtsamples-0001.txt"
    fetch.write_doc(TEXT, target, _sha(TEXT))
    assert target.read_bytes() == TEXT.encode("utf-8")
    assert len(seen) == 1 and seen[0].parent == target.parent
    assert fnmatch.fnmatch(seen[0].name, "D2-mtsamples-*.txt") and not seen[0].exists()


def test_case_alias_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    csv_path = tmp_path / "m.csv"
    sha = _write_csv(csv_path, [(NAME, TEXT)])
    _make_case(tmp_path, csv_sha=sha)
    code = fetch.main(
        ["--case", "./case-syn", "--offline", "--csv", str(csv_path), "--root", str(tmp_path)]
    )
    assert code == 1 and "plain variant id" in capsys.readouterr().err


def test_case_without_block_is_skipped_and_missing_case_fails(tmp_path: Path) -> None:
    csv_path = tmp_path / "m.csv"
    _write_csv(csv_path, [(NAME, TEXT)])
    plain = tmp_path / "cases" / "case-plain"
    plain.mkdir(parents=True)
    (plain / "case.yaml").write_text("case_id: case-plain\n", encoding="utf-8")
    assert fetch.main(["--offline", "--csv", str(csv_path), "--root", str(tmp_path)]) == 0
    assert (
        fetch.main(["--case", "nope", "--offline", "--csv", str(csv_path), "--root", str(tmp_path)])
        == 1
    )
