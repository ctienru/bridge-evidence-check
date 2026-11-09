from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import FIXTURES, load_script

validate = load_script("validate_gold")


def test_valid_fixtures_ok(capsys: pytest.CaptureFixture[str]) -> None:
    code = validate.main(
        [
            "--blind",
            str(FIXTURES / "blind_draft_valid.json"),
            "--adjudication",
            str(FIXTURES / "adjudication_valid.jsonl"),
            "--gold",
            str(FIXTURES / "expected_valid.json"),
        ]
    )
    out = capsys.readouterr()
    assert code == 0
    assert out.out.count("OK ") == 3 and out.err == ""


def test_invalid_files_exit_1_without_echoing_values(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    gold = json.loads((FIXTURES / "expected_valid.json").read_text("utf-8"))
    gold["facts"][0]["quote"] = "leaked transcript text"
    gold["conditions"][0]["reason"] = "secret reason text"
    gold["conditions"][0]["flags"].append("bogus_flag")
    bad_gold = tmp_path / "expected.json"
    bad_gold.write_text(json.dumps(gold), encoding="utf-8")

    lines = (FIXTURES / "adjudication_valid.jsonl").read_text("utf-8").splitlines()
    line = json.loads(lines[0])
    line["final"]["quote"] = "leaked quote"
    line["note"] = "secret note"
    bad_adj = tmp_path / "adjudication.jsonl"
    bad_adj.write_text(lines[1] + "\n" + json.dumps(line) + "\nnot json\n", encoding="utf-8")

    blind = json.loads((FIXTURES / "blind_draft_valid.json").read_text("utf-8"))
    blind["inventory"][0]["location"] = "secret location"
    blind["conditions"].append({"id": "claim.x", "status": "supported"})
    bad_blind = tmp_path / "blind_draft.json"
    bad_blind.write_text(json.dumps(blind), encoding="utf-8")

    code = validate.main(
        ["--blind", str(bad_blind), "--adjudication", str(bad_adj), "--gold", str(bad_gold)]
    )
    out = capsys.readouterr()
    assert code == 1
    assert "OK" not in out.out
    assert f"{bad_adj}:2: final" in out.err and f"{bad_adj}:3: invalid JSON" in out.err
    assert "facts.0" in out.err and "conditions.0.flags" in out.err
    assert "conditions.20.id" in out.err
    for secret in ("leaked", "secret", "bogus_flag"):
        assert secret not in out.err


def test_holdout_gold_is_refused_unread(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path
    hold = root / "cases" / "case-hold"
    hold.mkdir(parents=True)
    gold = hold / "expected.json"
    gold.write_text("not even json but never read", encoding="utf-8")
    (root / "splits.yaml").write_text(
        "version: 1\nvariants:\n  - {case_id: case-hold, variant_id: case-hold, split: holdout, "
        "frozen_at: '2026-11-08', gold_version: 1, files: {input.yaml: 'ab'}}\n",
        encoding="utf-8",
    )
    assert validate.main(["--gold", str(gold), "--root", str(root)]) == 1
    err = capsys.readouterr().err
    assert "holdout" in err and "cannot read" not in err


def test_missing_file_and_no_args(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert validate.main(["--gold", str(tmp_path / "nope.json")]) == 1
    assert "cannot read JSON" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        validate.main([])
