"""`bridge check` / `bridge history` with the fake client: exit codes, `--json`, history,
and no document text in logs or JSON output (contract §1, §11)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from bridge_check import cli
from bridge_check.cli import EXIT_FAILED, EXIT_OK, main
from bridge_check.fake_client import FakeClient, fixture
from bridge_check.input import InputError, load_case
from bridge_check.logs import LOG_KEYS, log_event

ROOT = Path(__file__).resolve().parent.parent
SMOKE = ROOT / "fixtures" / "synthetic" / "case-smoke"
SENTINEL = "SENTINEL-7f3a9c2e-do-not-log"


def _assert_absent(text: str, where: str) -> None:
    """Fail without echoing `text` (contract §11: test output carries no source text)."""
    leaked = SENTINEL in text or "SENTINEL" in text
    if leaked:
        pytest.fail(f"planted sentinel found in {where}", pytrace=False)


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("BRIDGE_FAKE_CLIENT", "1")
    return tmp_path / "bridge.db"


def _json(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict[str, Any], str]:
    code = main(list(argv))
    out = capsys.readouterr()
    return code, json.loads(out.out), out.err


def test_check_without_stop_after_fails_at_verify(
    db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, report, _ = _json(capsys, "check", str(SMOKE), "--db", str(db), "--json")
    assert code == EXIT_FAILED == 3
    assert report["status"] == "failed"
    assert report["failed_stage"] == "verify"
    assert "not implemented" in report["message"]
    assert report["extraction"]["source"] == "api"
    assert report["attempt_summary"]["by_status"] == {"parsed": 1}
    assert [(d["stage"], d["error_type"]) for d in report["dead_letters"]] == [
        ("verify", "NotImplemented")
    ]


def test_stop_after_extract_completes(db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, report, _ = _json(
        capsys, "check", str(SMOKE), "--db", str(db), "--json", "--stop-after", "extract"
    )
    assert code == EXIT_OK
    assert report["status"] == "completed"
    assert report["stopped_after"] == "extract"
    assert report["failed_stage"] is None
    assert "did not run" in report["message"]


def test_stop_after_is_hidden_from_help(capsys: pytest.CaptureFixture[str]) -> None:
    main(["check", "--help"])
    assert "--stop-after" not in capsys.readouterr().out


def test_history_lists_every_run_with_its_source(
    db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["check", str(SMOKE), "--db", str(db)])
    main(["check", str(SMOKE), "--db", str(db), "--stop-after", "extract"])
    capsys.readouterr()
    code, hist, _ = _json(capsys, "history", str(SMOKE), "--db", str(db), "--json")
    assert code == EXIT_OK
    runs = hist["runs"]
    assert [(r["status"], r["failed_stage"], r["extraction_source"]) for r in runs] == [
        ("failed", "verify", "api"),
        ("completed", None, "cache"),
    ]
    assert runs[0]["extraction_id"] == runs[1]["extraction_id"]
    assert runs[0]["source_attempt_id"] == runs[1]["source_attempt_id"] == 1
    main(["history", str(SMOKE), "--db", str(db)])
    table = capsys.readouterr().out
    assert "fresh call" in table and "cache hit" in table


def test_failed_parse_exits_3(
    db: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BRIDGE_FAKE_CLIENT", "bad_json")
    code, report, _ = _json(capsys, "check", str(SMOKE), "--db", str(db), "--json")
    assert code == EXIT_FAILED
    assert report["failed_stage"] == "parse"
    assert report["attempt_summary"]["by_status"] == {"parse_failed": 1}


def test_missing_document_fails_at_input(
    db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    case = tmp_path / "case"
    shutil.copytree(SMOKE, case)
    (case / "docs" / "D2-clinical.txt").unlink()
    code, report, _ = _json(capsys, "check", str(case), "--db", str(db), "--json")
    assert code == EXIT_FAILED
    assert report["failed_stage"] == "input"


def test_holdout_variant_is_refused(tmp_path: Path) -> None:
    (tmp_path / "splits.yaml").write_text(
        "version: 1\nvariants:\n  - {variant_id: case-smoke, split: holdout}\n", encoding="utf-8"
    )
    with pytest.raises(InputError, match="holdout"):
        load_case(SMOKE, root=tmp_path)


def test_log_lines_have_exactly_the_contract_keys(
    db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["check", str(SMOKE), "--db", str(db)])
    lines = [json.loads(line) for line in capsys.readouterr().err.splitlines() if line]
    assert lines
    for line in lines:
        assert tuple(line) == LOG_KEYS


def test_log_event_refuses_free_text_fields() -> None:
    with pytest.raises(TypeError):
        log_event("x", quote="anything")
    with pytest.raises(TypeError):
        log_event("x", stage=["not", "a", "scalar"])


def _plant_sentinel(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A copy of the smoke case with the sentinel in a document, the patient name, a valid
    reply quoting it, and an invalid reply using it as a key."""
    case = tmp_path / "case"
    shutil.copytree(SMOKE, case)
    doc = case / "docs" / "D2-clinical.txt"
    doc.write_text(doc.read_text(encoding="utf-8") + f"Note: {SENTINEL}.\n", encoding="utf-8")
    inp = case / "input.yaml"
    inp.write_text(
        inp.read_text(encoding="utf-8").replace("Synthetic Patient", SENTINEL), encoding="utf-8"
    )
    resp = json.loads(fixture("valid").read_text(encoding="utf-8"))
    block = next(b for b in resp["content"] if b["type"] == "text")
    ext = json.loads(block["text"])
    ext["diagnoses"].append({**ext["diagnoses"][0], "quote": f"Note: {SENTINEL}."})
    ext["patient_identity"][0]["name"] = SENTINEL
    block["text"] = json.dumps(ext)
    valid = tmp_path / "valid.json"
    valid.write_text(json.dumps(resp), encoding="utf-8")
    ext["diagnoses"][0][SENTINEL] = SENTINEL
    block["text"] = json.dumps(ext)
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps(resp), encoding="utf-8")
    return case, valid, invalid


@pytest.mark.parametrize("scenario", ["valid", "invalid"])
def test_sentinel_never_reaches_logs_or_json(
    scenario: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case, valid, invalid = _plant_sentinel(tmp_path)
    reply = valid if scenario == "valid" else invalid
    monkeypatch.setattr(cli, "make_client", lambda: FakeClient([reply]))
    db = tmp_path / "s.db"
    outputs = []
    for argv in (
        ["check", str(case), "--db", str(db), "--json"],
        ["check", str(case), "--db", str(db), "--json", "--explain"],
        ["check", str(case), "--db", str(db), "--stop-after", "extract"],
        ["history", str(case), "--db", str(db)],
        ["history", str(case), "--db", str(db), "--json"],
    ):
        main(argv)
        out = capsys.readouterr()
        outputs.append(out.out)
        outputs.append(out.err)
    joined = "\n".join(outputs)
    assert joined.strip()
    _assert_absent(joined, "CLI output or logs")
    # The planted text does reach the request the model sees (it is a document).
    assert SENTINEL in (case / "docs" / "D2-clinical.txt").read_text(encoding="utf-8")


def test_unknown_input_key_is_not_echoed(
    db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    case = tmp_path / "case"
    shutil.copytree(SMOKE, case)
    inp = case / "input.yaml"
    inp.write_text(
        inp.read_text(encoding="utf-8")
        + f"{SENTINEL}: 1\nprimary_patient_extra: {{{SENTINEL}: x}}\n",
        encoding="utf-8",
    )
    code = main(["check", str(case), "--db", str(db), "--json"])
    out = capsys.readouterr()
    assert code == EXIT_FAILED
    report = json.loads(out.out)
    assert report["failed_stage"] == "input"
    assert "invalid fields: ?" in report["dead_letters"][0]["message"]
    _assert_absent(out.out, "--json output")
    _assert_absent(out.err, "stderr")


# Runs `bridge check` in a fresh interpreter with ANTHROPIC_LOG=debug set before the SDK
# is imported, and the real SDK client wired to a mock transport that returns the
# synthetic valid reply. The SDK would log the request (with document text) at DEBUG.
SDK_DEBUG = """
import json, sys
from pathlib import Path
import anthropic, httpx2
from bridge_check import cli
reply = Path(sys.argv[3]).read_text(encoding="utf-8")
seen = []
def handler(request):
    seen.append(request.url.path)
    return httpx2.Response(200, text=reply, headers={"content-type": "application/json"})
def make_client():
    http = anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler))
    return anthropic.Anthropic(api_key="test-key", max_retries=0, http_client=http)
cli.make_client = make_client
code = cli.main(["check", sys.argv[1], "--db", sys.argv[2], "--json"])
print("REQUESTS", len(seen), file=sys.stderr)
sys.exit(code)
"""


def test_sdk_debug_logging_cannot_leak_document_text(tmp_path: Path) -> None:
    case, valid, _ = _plant_sentinel(tmp_path)
    env = {k: v for k, v in os.environ.items() if k != "BRIDGE_FAKE_CLIENT"}
    env["ANTHROPIC_LOG"] = "debug"
    result = subprocess.run(
        [sys.executable, "-c", SDK_DEBUG, str(case), str(tmp_path / "d.db"), str(valid)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=60,
    )
    assert "REQUESTS 1" in result.stderr  # the request really went through the SDK
    assert result.returncode == EXIT_FAILED  # failed at verify, as every W08 full check
    assert json.loads(result.stdout)["extraction"]["source"] == "api"
    _assert_absent(result.stdout, "--json output")
    _assert_absent(result.stderr, "stderr")
    for line in result.stderr.splitlines():
        if line and not line.startswith("REQUESTS"):
            json.loads(line)  # only our JSON log lines reach stderr


@pytest.mark.parametrize("breakage", ["invalid_yaml", "invalid_field", "missing_doc"])
def test_case_directory_name_is_not_echoed(
    breakage: str, db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A case directory may be named after a person; input errors must not print it.
    case = tmp_path / SENTINEL
    shutil.copytree(SMOKE, case)
    inp = case / "input.yaml"
    if breakage == "invalid_yaml":
        inp.write_text("variant_id: [unclosed\n", encoding="utf-8")
    elif breakage == "invalid_field":
        inp.write_text(
            inp.read_text(encoding="utf-8").replace("2026-10-15", "someday"), encoding="utf-8"
        )
    else:
        (case / "docs" / "D1-referral.txt").unlink()
    code = main(["check", str(case), "--db", str(db), "--json"])
    out = capsys.readouterr()
    assert code == EXIT_FAILED
    report = json.loads(out.out)
    assert report["failed_stage"] == "input"
    _assert_absent(out.out, "--json output")
    _assert_absent(out.err, "stderr")
    if breakage != "missing_doc":
        assert report["case_id"].startswith("unresolved-")
    main(["history", str(case), "--db", str(db), "--json"])
    hist = capsys.readouterr()
    _assert_absent(hist.out + hist.err, "history output")
    assert [r["failed_stage"] for r in json.loads(hist.out)["runs"]] == ["input"]
