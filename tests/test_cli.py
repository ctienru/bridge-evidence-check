"""`bridge check` / `bridge history` with the fake client: exit codes, `--json`, history,
and no document text in logs or JSON output (contract §1, §11)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from bridge_check import cli, verify
from bridge_check.cli import EXIT_FAILED, EXIT_OK, main
from bridge_check.enums import CONDITION_IDS
from bridge_check.fake_client import FakeClient, fixture
from bridge_check.input import InputError, load_case
from bridge_check.logs import LOG_KEYS, log_event
from bridge_check.store import open_store

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


def test_full_check_completes_with_decisions(db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, report, _ = _json(capsys, "check", str(SMOKE), "--db", str(db), "--json")
    assert code == EXIT_OK
    assert report["status"] == "completed"
    assert report["failed_stage"] is None
    assert "decisions" in report["message"]
    assert report["extraction"]["source"] == "api"
    assert report["attempt_summary"]["by_status"] == {"parsed": 1}
    assert report["dead_letters"] == []
    assert report["verification"]["evidence_count"] == 16
    assert report["versions"]["splitter"] == "sentences-v1"
    by_id = {d["condition"]: d for d in report["decisions"]}
    assert set(by_id) >= set(CONDITION_IDS)
    assert set(by_id) - set(CONDITION_IDS) == {
        "claim.drug",
        "claim.bmi_bracket",
        "claim.exclusion.t2dm",
    }
    # the referral's weight and height inherit the referral's own date (2025-03-20): after
    # initiation, so no BMI sub-result is supported and the model's `at` is flagged
    assert by_id["bmi_path_a"]["status"] == "insufficient"
    assert {x["reason"] for x in by_id["bmi_path_a"]["excluded_evidence"]} == {"after_initiation"}
    assert by_id["bmi_path_c.stroke"]["status"] == "not_supported"
    assert by_id["patient_identity"] == {
        **by_id["patient_identity"],
        "status": "review",
        "flags": ["id_missing"],
    }
    assert by_id["claim.drug"]["status"] == "supported"
    assert report["case_flags"] == []
    assert report["human_workload"] == 8
    for d in report["decisions"]:
        assert d["rule_id"].startswith(d["condition"] + ":")
        for u in d["used_evidence"]:
            assert re.fullmatch(r"[A-Za-z0-9_-]+\[\d+:\d+\] [0-9a-f]{8}", u["ref"])


def test_stop_after_verify_completes_with_a_summary(
    db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, report, _ = _json(
        capsys, "check", str(SMOKE), "--db", str(db), "--json", "--stop-after", "verify"
    )
    assert code == EXIT_OK
    assert report["status"] == "completed"
    assert report["stopped_after"] == "verify"
    assert report["dead_letters"] == []
    ver = report["verification"]
    assert ver["by_position_status"] == {"verbatim": 16}
    assert ver["by_assertion_check"] == {"matched": 16}
    assert ver["by_exclusion_reason"] == {"claim_document": 1}
    assert ver["by_flag"] == {}
    assert ver["doc_identity"] == {
        "D0-pa-form-draft": "match",
        "D1-referral": "match",
        "D2-clinical": "missing",
    }
    assert "evidence" not in report  # only with --explain


def test_explain_lists_evidence_refs_only(db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, report, _ = _json(
        capsys,
        "check",
        str(SMOKE),
        "--db",
        str(db),
        "--json",
        "--explain",
        "--stop-after",
        "verify",
    )
    assert code == EXIT_OK
    refs = [e["ref"] for e in report["evidence"]]
    assert len(refs) == 16
    assert all(re.fullmatch(r"[A-Za-z0-9_-]+\[\d+:\d+\] [0-9a-f]{8}", r) for r in refs)
    main(["check", str(SMOKE), "--db", str(db), "--explain", "--stop-after", "verify"])
    text = capsys.readouterr().out
    assert "D2-clinical[78:99]" in text and "position=verbatim" in text


def test_exception_in_verify_fails_the_run_with_a_fact_path(
    db: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    real = verify.verify_fact

    def boom(fact_field: str, fact_path: str, *args: Any, **kwargs: Any) -> Any:
        if fact_path == "diagnoses[1]":
            raise ValueError(f"cannot handle {SENTINEL}")
        return real(fact_field, fact_path, *args, **kwargs)

    monkeypatch.setattr(verify, "verify_fact", boom)
    code, report, err = _json(capsys, "check", str(SMOKE), "--db", str(db), "--json")
    assert code == EXIT_FAILED
    assert report["failed_stage"] == "verify"
    assert [(d["stage"], d["error_type"], d["fact_path"]) for d in report["dead_letters"]] == [
        ("verify", "ValueError", "diagnoses[1]")
    ]
    assert report["verification"] is None  # nothing was written
    store = open_store(db)
    try:
        assert store.count("evidence") == 0 and store.count("doc_facts") == 0
    finally:
        store.close()
    _assert_absent(json.dumps(report) + err, "--json output or logs")


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
        ("completed", None, "api"),
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
    monkeypatch.setenv("BRIDGE_FAKE_CLIENT", "no_tool_call")
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
    block = next(b for b in resp["content"] if b["type"] == "tool_use")
    ext = block["input"]
    ext["diagnoses"].append({**ext["diagnoses"][0], "quote": f"Note: {SENTINEL}."})
    # A quote the documents do not contain: reported as `doc_id[-:-] sha8` only.
    ext["diagnoses"].append({**ext["diagnoses"][0], "quote": f"Absent {SENTINEL} quote."})
    # Chart text copied into `doc_id` (it fits the id pattern): never echoed in a ref.
    ext["diagnoses"].append({**ext["diagnoses"][0], "doc_id": SENTINEL, "quote": "Anything."})
    ext["patient_identity"][0]["name"] = SENTINEL
    valid = tmp_path / "valid.json"
    valid.write_text(json.dumps(resp), encoding="utf-8")
    ext["diagnoses"][0][SENTINEL] = SENTINEL
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
    monkeypatch.setattr(cli, "make_client", lambda case_dir=None: FakeClient([reply]))
    db = tmp_path / "s.db"
    outputs = []
    for argv in (
        ["check", str(case), "--db", str(db), "--json"],
        ["check", str(case), "--db", str(db), "--json", "--explain"],
        ["check", str(case), "--db", str(db), "--explain"],
        ["check", str(case), "--db", str(db), "--stop-after", "extract"],
        ["check", str(case), "--db", str(db), "--json", "--explain", "--stop-after", "verify"],
        ["check", str(case), "--db", str(db), "--explain", "--stop-after", "verify"],
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
    store = open_store(db)
    try:
        letters = [
            d for r in store.history("case-smoke") for d in store.dead_letters_for_run(r["id"])
        ]
        _assert_absent(json.dumps(letters), "dead letters")
        decisions = [
            d for r in store.history("case-smoke") for d in store.decisions_for_run(r["id"])
        ]
        _assert_absent(json.dumps(decisions), "decisions")
        if scenario == "valid":
            assert decisions  # the full runs completed and published decisions
            # The quotes really were verified: one located, one not found.
            assert "D2-clinical[-:-]" in joined and "position=not_found" in joined
            assert "unresolved-doc[-:-]" in joined
    finally:
        store.close()
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
def make_client(case_dir=None):
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
    assert result.returncode == EXIT_OK
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


def test_old_schema_database_fails_before_any_call(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import sqlite3

    db = tmp_path / "bridge.db"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()
    before = db.read_bytes()

    def no_client(case_dir: Path | None = None) -> Any:
        pytest.fail("the client must not be created when the database is refused")

    monkeypatch.setattr(cli, "make_client", no_client)
    code = main(["check", str(SMOKE), "--db", str(db), "--json"])
    out = capsys.readouterr()
    assert code == EXIT_FAILED
    assert out.out == ""
    assert (
        "the database file was created by an older schema (user_version 1, expected 2)" in out.err
    )
    assert str(db) not in out.err and db.name not in out.err  # the path is never printed
    assert "point BRIDGE_DB at a new file" in out.err
    assert db.read_bytes() == before
    assert main(["history", str(SMOKE), "--db", str(db)]) == EXIT_FAILED


def test_cost_ceiling_refuses_with_exit_3_and_no_attempt(
    db: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from bridge_check import cli
    from bridge_check.extract import Limits

    monkeypatch.setattr(cli, "LIMITS", Limits(run_cost_ceiling_usd=0.0))
    code, report, err = _json(capsys, "check", str(SMOKE), "--db", str(db), "--json")
    assert code == EXIT_FAILED
    assert report["status"] == "failed" and report["failed_stage"] == "extract"
    assert report["attempt_summary"]["count"] == 0
    assert report["decisions"] == [] and report["verification"] is None
    assert [d["error_type"] for d in report["dead_letters"]] == ["RunCostCeiling"]
    assert "bridge check: refused: run cost ceiling" in err and "no request sent" in err


# --- Initiation anchoring regression (checkpoint A): the start sentence's temporality ------


def _scripted_decisions(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    **start: str,
) -> dict[str, dict[str, Any]]:
    """`bridge check` on the smoke case with the valid reply, its start sentence edited."""
    resp = json.loads(fixture("valid").read_text(encoding="utf-8"))
    ext = next(b for b in resp["content"] if b["type"] == "tool_use")["input"]
    ext["glp1_start"][0].update(start)
    reply = tmp_path / f"{name}.json"
    reply.write_text(json.dumps(resp), encoding="utf-8")
    monkeypatch.setattr(cli, "make_client", lambda case_dir=None: FakeClient([reply]))
    code, report, _ = _json(
        capsys, "check", str(SMOKE), "--db", str(tmp_path / f"{name}.db"), "--json"
    )
    assert code == EXIT_OK and report["status"] == "completed"
    return {d["condition"]: d for d in report["decisions"]}


def _anchored(decisions: dict[str, dict[str, Any]]) -> bool:
    # The referral's measurements are dated after the start: that reason exists only when an
    # initiation date is anchored; without one their timepoint is unknown.
    reasons = {x["reason"] for x in decisions["bmi_path_a"]["excluded_evidence"]}
    return reasons == {"after_initiation"}


def test_historical_start_sentence_anchors_like_a_current_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    current = _scripted_decisions(tmp_path, capsys, monkeypatch, "current")
    historical = _scripted_decisions(
        tmp_path, capsys, monkeypatch, "historical", temporality="historical"
    )
    assert _anchored(current)
    assert historical == current


@pytest.mark.parametrize(
    "start",
    [{"certainty": "negated"}, {"subject": "family"}],
    ids=["negated", "family"],
)
def test_negated_or_family_start_sentence_anchors_nothing(
    start: dict[str, str],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decisions = _scripted_decisions(
        tmp_path, capsys, monkeypatch, "edited", temporality="historical", **start
    )
    assert not _anchored(decisions)
    for cid in ("bmi_path_a", "bmi_path_b.bmi", "bmi_path_c.bmi", "bmi_path_b", "bmi_path_c"):
        assert decisions[cid]["status"] != "supported", cid


def test_historical_start_without_its_date_in_the_quote_anchors_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Contract §3.1: the date must still be inside the verified quote.
    resp = json.loads(fixture("valid").read_text(encoding="utf-8"))
    ext = next(b for b in resp["content"] if b["type"] == "tool_use")["input"]
    quote = str(ext["glp1_start"][0]["quote"])
    cut = quote[: quote.index(str(ext["glp1_start"][0]["date"]))].rstrip()
    decisions = _scripted_decisions(
        tmp_path, capsys, monkeypatch, "undated", temporality="historical", quote=cut
    )
    assert not _anchored(decisions)
    for cid in ("bmi_path_a", "bmi_path_b.bmi", "bmi_path_c.bmi", "bmi_path_b", "bmi_path_c"):
        assert decisions[cid]["status"] != "supported", cid


# --- check and history never open a holdout case outside the checkout -------------------------


def _external_holdout(tmp_path: Path) -> Path:
    """A private-style layout outside the checkout: `splits.yaml` marking `case-hold` as
    holdout and the case under `holdout/case-hold` (the private repository's layout)."""
    priv = tmp_path / "private"
    hold = priv / "holdout" / "case-hold"
    shutil.copytree(SMOKE, hold)
    inp = hold / "input.yaml"
    inp.write_text(
        inp.read_text(encoding="utf-8").replace("variant_id: case-smoke", "variant_id: case-hold"),
        encoding="utf-8",
    )
    (priv / "splits.yaml").write_text(
        "version: 1\nvariants:\n  - {variant_id: case-hold, split: holdout}\n", encoding="utf-8"
    )
    return hold


def _named_like_public_holdout(tmp_path: Path) -> Path:
    """A copy outside every manifest whose directory carries a public holdout id."""
    from bridge_check.manifest import CHECKOUT_ROOT, holdout_variants

    vid = sorted(holdout_variants(CHECKOUT_ROOT))[0]
    where = tmp_path / "elsewhere" / vid
    shutil.copytree(SMOKE, where)
    return where


def _opens_under(monkeypatch: pytest.MonkeyPatch, inside: Path) -> list[str]:
    import builtins
    import io
    import os

    seen: list[str] = []
    real = builtins.open

    def spy(file: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            if Path(os.fspath(file)).resolve().is_relative_to(inside.resolve()):
                seen.append(Path(os.fspath(file)).name)
        except (TypeError, OSError):
            pass
        return real(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy)
    monkeypatch.setattr(io, "open", spy)
    return seen


@pytest.mark.parametrize("layout", ["private_manifest", "public_holdout_name"])
def test_check_refuses_an_external_holdout_case_before_opening_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    layout: str,
) -> None:
    case = (
        _external_holdout(tmp_path)
        if layout == "private_manifest"
        else (_named_like_public_holdout(tmp_path))
    )
    monkeypatch.setenv("BRIDGE_FAKE_CLIENT", "1")
    opened = _opens_under(monkeypatch, case)
    db = tmp_path / "check.db"
    assert main(["check", str(case), "--db", str(db)]) == EXIT_FAILED
    assert opened == []
    assert "holdout" in capsys.readouterr().err
    assert not db.exists()


@pytest.mark.parametrize("layout", ["private_manifest", "public_holdout_name", "bare_id"])
def test_history_refuses_a_holdout_case_before_opening_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    layout: str,
) -> None:
    from bridge_check.manifest import CHECKOUT_ROOT, holdout_variants

    db = tmp_path / "history.db"
    open_store(db).close()
    if layout == "private_manifest":
        case = _external_holdout(tmp_path)
        arg = str(case)
    elif layout == "public_holdout_name":
        case = _named_like_public_holdout(tmp_path)
        arg = str(case)
    else:
        case = tmp_path
        arg = sorted(holdout_variants(CHECKOUT_ROOT))[0]
    opened = _opens_under(monkeypatch, case)
    assert main(["history", arg, "--db", str(db)]) == EXIT_FAILED
    assert opened == []
    captured = capsys.readouterr()
    assert "holdout" in captured.err and "runs for" not in captured.out


@pytest.mark.parametrize("command", ["check", "history"])
@pytest.mark.parametrize("linked", ["input", "document"])
def test_dev_named_case_with_a_file_linked_into_a_private_holdout_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
    linked: str,
) -> None:
    """A directory with an innocent name outside every manifest whose `input.yaml` or a
    document links into a manifest-marked private holdout: refused before anything opens."""
    hold = _external_holdout(tmp_path)
    case = tmp_path / "devlike" / "case-x"
    shutil.copytree(SMOKE, case)
    rel = Path("input.yaml") if linked == "input" else Path("docs") / "D1-referral.txt"
    (case / rel).unlink()
    (case / rel).symlink_to(hold / rel)
    db = tmp_path / f"{command}.db"
    if command == "history":
        open_store(db).close()
    monkeypatch.setenv("BRIDGE_FAKE_CLIENT", "1")
    opened = _opens_under(monkeypatch, hold)
    assert main([command, str(case), "--db", str(db)]) == EXIT_FAILED
    assert opened == []
    assert "holdout" in capsys.readouterr().err
    assert command == "history" or not db.exists()


@pytest.mark.parametrize("command", ["check", "history"])
def test_differently_cased_spelling_of_a_holdout_case_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    hold = _external_holdout(tmp_path)
    upper = hold.parent / hold.name.upper()
    if not upper.exists():
        pytest.skip("case-sensitive file system: the other spelling names nothing")
    db = tmp_path / f"{command}.db"
    if command == "history":
        open_store(db).close()
    monkeypatch.setenv("BRIDGE_FAKE_CLIENT", "1")
    opened = _opens_under(monkeypatch, hold)
    assert main([command, str(upper), "--db", str(db)]) == EXIT_FAILED
    assert opened == []
    assert "holdout" in capsys.readouterr().err
