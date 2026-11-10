"""Public outputs carry no MTSamples text (contract §11), and replays are what they claim.

- `test_public_outputs_contain_no_mtsamples_text`: no file under `reports/` or `replays/`,
  and no `cases/*/expected.json`, shares a 40-character window with a fetched MTSamples
  document (skips when none is fetched).
- A planted sentinel in an MTSamples-named document, its quotes, its free-text fields and
  the reply's thinking block never reaches `export_public_run()`'s output.
- Every committed replay sits at its contract path, names the frozen document hashes, and
  restores to a valid extraction.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import FIXTURES, ROOT
from leakcheck import WINDOW, assert_no_shared_windows, mtsamples_files, read_exact, windows

from bridge_check.cli import main as bridge_main
from bridge_check.export import (
    UNLOCATABLE_PREFIX,
    dump_replay,
    export_public_run,
    replay_path,
    restore_extraction,
)
from bridge_check.input import load_case
from bridge_check.store import open_store

SMOKE = FIXTURES / "case-smoke"
VALID_REPLY = FIXTURES / "extract" / "response_valid.json"
SENTINEL = "SENTINEL-41d9e0b7-never-publish-this-line"
MTS_DOC = "D2-mtsamples-0001"


def _public_files() -> list[Path]:
    files = [p for d in ("reports", "replays") for p in (ROOT / d).rglob("*") if p.is_file()]
    return sorted(files + list((ROOT / "cases").glob("*/expected.json")))


def test_public_outputs_contain_no_mtsamples_text() -> None:
    sources = mtsamples_files()
    if not sources:
        pytest.skip("no local MTSamples documents under cases/*/docs/")
    texts = {s.name: read_exact(s) for s in sources}
    for path in _public_files():
        body = path.read_text(encoding="utf-8")
        for name, text in texts.items():
            assert_no_shared_windows(body, path.relative_to(ROOT).as_posix(), text, name)


def test_public_outputs_exist() -> None:
    assert (ROOT / "reports" / "baseline-dev.json").is_file()
    assert list((ROOT / "replays").glob("*/*.json"))


# --- planted sentinel ---------------------------------------------------------------------


def _leak_case(tmp: Path) -> Path:
    """A copy of the smoke case whose clinical note is named like an MTSamples document and
    carries the sentinel, with a fake reply that quotes it in every possible place."""
    case = tmp / "case-leak"
    shutil.copytree(SMOKE, case)
    note = case / "docs" / "D2-clinical.txt"
    text = read_exact(note) + f"Additional line {SENTINEL} for the export test.\n"
    note.unlink()
    (case / "docs" / f"{MTS_DOC}.txt").write_text(text, encoding="utf-8", newline="")
    inp = (case / "input.yaml").read_text(encoding="utf-8")
    inp = inp.replace("D2-clinical", MTS_DOC).replace(
        "variant_id: case-smoke", "variant_id: case-leak"
    )
    (case / "input.yaml").write_text(inp, encoding="utf-8")

    reply: dict[str, Any] = json.loads(
        VALID_REPLY.read_text(encoding="utf-8").replace("D2-clinical", MTS_DOC)
    )
    for block in reply["content"]:
        if block["type"] == "thinking":
            block["thinking"] = f"thinking about {SENTINEL}"
        if block["type"] != "tool_use":
            continue
        ext = block["input"]
        base = {k: ext["diagnoses"][0][k] for k in ext["diagnoses"][0]}
        ext["diagnoses"].append(
            {
                **base,
                "quote": f"Additional line {SENTINEL} for the export test.",
                "concept": "other",
            }
        )
        ext["diagnoses"].append({**base, "quote": f"{SENTINEL} not in any document"})
        ext["medications"][0]["indication"] = f"for {SENTINEL}"
        ext["medication_lists"][0]["section_title"] = f"{SENTINEL} list"
    (case / "fake-reply.json").write_text(json.dumps(reply), encoding="utf-8")
    return case


@pytest.fixture
def leak_export(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Any], Path]:
    monkeypatch.setenv("BRIDGE_FAKE_CLIENT", "1")
    case = _leak_case(tmp_path)
    db = tmp_path / "bridge.db"
    assert bridge_main(["check", str(case), "--db", str(db)]) == 0
    store = open_store(db)
    try:
        run_id = store.latest_completed_run("case-leak")
        assert run_id is not None
        payload = export_public_run(store, run_id, load_case(case).texts)
    finally:
        store.close()
    return payload, case


def test_export_never_carries_the_sentinel(leak_export: tuple[dict[str, Any], Path]) -> None:
    payload, case = leak_export
    body = dump_replay(payload)
    assert SENTINEL not in body
    assert "thinking" not in body
    doc = read_exact(case / "docs" / f"{MTS_DOC}.txt")
    assert_no_shared_windows(body, "replay", doc, MTS_DOC)
    mts_quotes = [
        f["quote"]
        for rows in payload["extraction"].values()
        for f in rows
        if f["doc_id"] == MTS_DOC
    ]
    assert mts_quotes and all("text" not in q for q in mts_quotes)
    assert payload["lossy_quote_count"] == 1  # the quote that is in no document
    assert payload["mtsamples_doc_ids"] == [MTS_DOC]


def test_export_restores_exact_quotes_and_placeholders(
    leak_export: tuple[dict[str, Any], Path],
) -> None:
    payload, case = leak_export
    texts = load_case(case).texts
    restored = restore_extraction(json.loads(dump_replay(payload)), texts)
    quotes = [d.quote for d in restored.diagnoses]
    assert f"Additional line {SENTINEL} for the export test." in quotes
    assert sum(q.startswith(UNLOCATABLE_PREFIX) for q in quotes) == 1
    assert restored.medications[0].indication == ""
    assert restored.medication_lists[0].section_title == ""


def test_export_is_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRIDGE_FAKE_CLIENT", "1")
    db = tmp_path / "bridge.db"
    assert bridge_main(["check", str(SMOKE), "--db", str(db)]) == 0
    assert bridge_main(["check", str(SMOKE), "--db", str(db)]) == 0
    store = open_store(db)
    try:
        texts = load_case(SMOKE).texts
        one, two = (dump_replay(export_public_run(store, r, texts)) for r in (1, 2))
    finally:
        store.close()
    assert one == two


# --- committed replays --------------------------------------------------------------------


def _manifest() -> dict[str, dict[str, Any]]:
    data: Any = yaml.safe_load((ROOT / "splits.yaml").read_text(encoding="utf-8"))
    return {str(v["variant_id"]): v for v in data["variants"]}


def _replays() -> list[Path]:
    return sorted((ROOT / "replays").glob("*/*.json"))


@pytest.mark.parametrize("path", _replays(), ids=lambda p: p.parent.name)
def test_committed_replay_matches_manifest_and_path(path: Path) -> None:
    replay = json.loads(path.read_text(encoding="utf-8"))
    manifest = _manifest()
    vid = replay["variant_id"]
    assert manifest[vid]["split"] == "dev"
    expected = replay_path(
        ROOT / "replays",
        vid,
        replay["input_hash"],
        replay["prompt_version"],
        replay["schema_version"],
    )
    assert path == expected
    frozen = {
        k.removeprefix("docs/").removesuffix(".txt"): v
        for k, v in manifest[vid]["files"].items()
        if k.startswith("docs/")
    }
    assert replay["doc_sha256"] == frozen
    assert path.read_text(encoding="utf-8") == dump_replay(replay)


@pytest.mark.parametrize("path", _replays(), ids=lambda p: p.parent.name)
def test_committed_replay_restores(path: Path) -> None:
    replay = json.loads(path.read_text(encoding="utf-8"))
    case_dir = ROOT / "cases" / replay["variant_id"]
    if replay["mtsamples_doc_ids"] and not mtsamples_files():
        pytest.skip("MTSamples documents not fetched")
    case = load_case(case_dir)
    assert case.input_hash == replay["input_hash"]
    restored = restore_extraction(replay, case.texts)
    restored_quotes = [
        f.quote for fld in type(restored).model_fields for f in getattr(restored, fld)
    ]
    assert len(restored_quotes) == replay["quote_count"]
    lossy = sum(q.startswith(UNLOCATABLE_PREFIX) for q in restored_quotes)
    assert lossy <= replay["lossy_quote_count"]
    for q in restored_quotes:
        if not q.startswith(UNLOCATABLE_PREFIX):
            digest = hashlib.sha256(q.encode("utf-8")).hexdigest()
            assert any(
                digest == f["quote"]["sha256"]
                for rows in replay["extraction"].values()
                for f in rows
            )


def test_window_helper_matches_contract_width() -> None:
    assert WINDOW == 40 and len(next(iter(windows("x" * 50)))) == 40
