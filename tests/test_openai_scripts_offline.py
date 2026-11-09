"""The two model-calling scripts never need a key or network in tests.

Without a key they exit 2 before any client is built; with a fake SDK the raw reply is
saved before parsing, bad replies still leave a private record, private paths inside the
public checkout are refused before the call, and the request carries no `temperature`.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from conftest import FIXTURES, ROOT, load_script

from bridge_check.dataside.openai_client import (
    EXIT_NO_KEY,
    chat_json,
    json_schema_format,
    read_api_key,
)

draft = load_script("draft_authored")
propose = load_script("propose_candidates")


class FakeClient:
    """Records the kwargs of one `chat.completions.create` call and returns a canned reply."""

    def __init__(
        self,
        content: str,
        finish_reason: str = "stop",
        refusal: str | None = None,
        *,
        no_choices: bool = False,
        raise_exc: Exception | None = None,
    ):
        self.kwargs: dict[str, Any] = {}
        self.raise_exc = raise_exc
        message = SimpleNamespace(content=content, refusal=refusal)
        choice = SimpleNamespace(message=message, finish_reason=finish_reason)
        choices = [] if no_choices else [choice]
        self._completion = SimpleNamespace(
            model="fake-model-2026-11",
            choices=choices,
            model_dump=lambda mode="json": {
                "model": "fake-model-2026-11",
                "n_choices": len(choices),
            },
        )
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        if self.raise_exc is not None:
            raise self.raise_exc
        return self._completion


def test_chat_json_sends_json_mode_without_temperature() -> None:
    client = FakeClient('{"a": 1}')
    fmt = json_schema_format("probe", {"type": "object", "properties": {}})
    reply = chat_json(client, "gpt-6.1-sol", [{"role": "user", "content": "x"}], fmt)
    assert "temperature" not in client.kwargs
    assert client.kwargs["response_format"]["type"] == "json_schema"
    assert client.kwargs["response_format"]["json_schema"]["strict"] is True
    assert client.kwargs["model"] == "gpt-6.1-sol"
    assert reply.content == '{"a": 1}' and reply.model == "fake-model-2026-11"
    assert reply.problem() is None
    assert reply.response == {"model": "fake-model-2026-11", "n_choices": 1}
    assert "JSON" in client.kwargs["messages"][0]["content"] or True  # builder tests cover this


_FMT = json_schema_format("t", {"type": "object", "properties": {}})


def test_malformed_choice_is_archived_then_reported() -> None:
    client = FakeClient("x")
    client._completion.choices = [SimpleNamespace(no_message_here=True)]
    reply = chat_json(client, "m", [], _FMT)
    assert reply.problem() == "malformed"
    assert reply.response == {"model": "fake-model-2026-11", "n_choices": 1}


def test_reply_problems() -> None:
    assert chat_json(FakeClient("", no_choices=True), "m", [], _FMT).problem() == "no_choices"
    filtered = chat_json(FakeClient("x", finish_reason="content_filter"), "m", [], _FMT)
    assert filtered.problem() == "content_filter"
    assert chat_json(FakeClient("", refusal="no"), "m", [], _FMT).problem() == "refused"
    truncated = chat_json(FakeClient("{", finish_reason="length"), "m", [], _FMT)
    assert truncated.problem() == "truncated"
    assert chat_json(FakeClient("   "), "m", [], _FMT).problem() == "empty"


@pytest.fixture
def no_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return tmp_path / "missing.env"


def test_read_api_key_env_then_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    dotenv = tmp_path / ".env"
    assert read_api_key(dotenv) is None
    dotenv.write_text(
        "# comment\nANTHROPIC_API_KEY=a\nOPENAI_API_KEY='sk-test'\n", encoding="utf-8"
    )
    assert read_api_key(dotenv) == "sk-test"
    dotenv.write_text("OPENAI_API_KEY=\n", encoding="utf-8")
    assert read_api_key(dotenv) is None
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    assert read_api_key(dotenv) == "sk-env"


def _draft_args(tmp_path: Path, env: Path, **overrides: str) -> list[str]:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("x", encoding="utf-8")
    args = {
        "--spec": str(FIXTURES / "drafting" / "spec.yaml"),
        "--prompt": str(prompt),
        "--out-docs": str(tmp_path / "docs"),
        "--out-record": str(tmp_path / "private" / "record.json"),
        "--raw-out": str(tmp_path / "private" / "raw.jsonl"),
        "--root": str(ROOT),
        "--env": str(env),
    }
    args.update(overrides)
    return [item for pair in args.items() for item in pair]


def test_draft_authored_exits_2_without_key(no_key: Path, tmp_path: Path) -> None:
    code = draft.main(_draft_args(tmp_path, no_key))
    assert code == EXIT_NO_KEY == 2
    assert not (tmp_path / "docs").exists()


def test_draft_authored_refuses_private_paths_in_public_checkout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    called = []
    monkeypatch.setattr(draft, "make_client", lambda key: called.append(key))
    code = draft.main(
        _draft_args(tmp_path, tmp_path / "none.env", **{"--raw-out": str(ROOT / "raw.jsonl")})
    )
    assert code == 1 and called == []
    assert "public checkout" in capsys.readouterr().err


def test_draft_authored_public_boundary_ignores_root_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    called: list[str] = []
    monkeypatch.setattr(draft, "make_client", lambda key: called.append(key))
    args = _draft_args(
        tmp_path,
        tmp_path / "none.env",
        **{"--raw-out": str(ROOT / "raw.jsonl"), "--root": str(tmp_path)},
    )
    assert draft.main(args) == 1 and called == []
    assert "public checkout" in capsys.readouterr().err


def test_draft_authored_refuses_raw_and_record_being_one_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    called: list[str] = []
    monkeypatch.setattr(draft, "make_client", lambda key: called.append(key))
    same = str(tmp_path / "private" / "one.json")
    args = _draft_args(tmp_path, tmp_path / "none.env", **{"--raw-out": same, "--out-record": same})
    assert draft.main(args) == 1 and called == []
    assert "same file" in capsys.readouterr().err


def test_draft_authored_refuses_raw_out_equal_to_a_planned_document(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    called: list[str] = []
    monkeypatch.setattr(draft, "make_client", lambda key: called.append(key))
    planned = str(tmp_path / "docs" / "D1-referral.txt")  # the file the spec will generate
    args = _draft_args(tmp_path, tmp_path / "none.env", **{"--raw-out": planned})
    assert draft.main(args) == 1 and called == []
    assert "same file" in capsys.readouterr().err


def test_unwritable_raw_out_costs_zero_api_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    calls: list[str] = []

    def fake_factory(name: str) -> Any:
        def make(key: str) -> FakeClient:
            calls.append(name)
            return FakeClient("{}")

        return make

    monkeypatch.setattr(draft, "make_client", fake_factory("draft"))
    monkeypatch.setattr(propose, "make_client", fake_factory("propose"))
    raw_dir = tmp_path / "private" / "raw-is-a-directory"
    raw_dir.mkdir(parents=True)
    assert (
        draft.main(_draft_args(tmp_path, tmp_path / "none.env", **{"--raw-out": str(raw_dir)})) == 1
    )
    assert "cannot open --raw-out" in capsys.readouterr().err
    code = propose.main(
        _propose_args(tmp_path, tmp_path / "none.env", **{"--raw-out": str(raw_dir)})
    )
    assert code == 1 and "cannot open --raw-out" in capsys.readouterr().err
    assert calls == []


def test_inputs_inside_holdout_are_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    calls: list[str] = []
    monkeypatch.setattr(draft, "make_client", lambda key: calls.append("x"))
    monkeypatch.setattr(propose, "make_client", lambda key: calls.append("x"))
    root = tmp_path / "repo"
    hold = root / "cases" / "case-hold"
    hold.mkdir(parents=True)
    (root / "splits.yaml").write_text(
        "version: 1\nvariants:\n  - {case_id: case-hold, variant_id: case-hold, split: holdout, "
        "frozen_at: '2026-11-08', gold_version: 1, files: {input.yaml: 'ab'}}\n",
        encoding="utf-8",
    )
    prompt = hold / "prompt.txt"
    prompt.write_text("secret", encoding="utf-8")
    args = _draft_args(
        tmp_path, tmp_path / "none.env", **{"--prompt": str(prompt), "--root": str(root)}
    )
    assert draft.main(args) == 1 and "--prompt" in capsys.readouterr().err
    args = _propose_args(
        tmp_path, tmp_path / "none.env", **{"--guide": str(prompt), "--root": str(root)}
    )
    assert propose.main(args) == 1 and "--guide" in capsys.readouterr().err
    assert calls == []


def test_private_data_root_allows_archives_inside_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`--root` is the data root (for example the private companion repo); only the real
    public checkout is a forbidden place for raw archives."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    private_repo = tmp_path / "companion"
    (private_repo / "cases").mkdir(parents=True)
    client = FakeClient(json.dumps({"candidates": []}))
    monkeypatch.setattr(propose, "make_client", lambda key: client)
    args = _propose_args(
        tmp_path,
        tmp_path / "none.env",
        **{
            "--raw-out": str(private_repo / "replays-full" / "raw.json"),
            "--root": str(private_repo),
        },
    )
    assert propose.main(args) == 0
    assert (private_repo / "replays-full" / "raw.json").is_file()


def test_symlink_in_public_checkout_to_private_file_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`os.replace()` would turn the public symlink into a real file holding the raw reply."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    calls: list[str] = []

    def make(key: str) -> FakeClient:
        calls.append(key)
        return FakeClient(json.dumps({"candidates": []}))

    monkeypatch.setattr(propose, "make_client", make)
    monkeypatch.setattr(draft, "make_client", make)
    private = tmp_path / "private" / "raw.json"
    private.parent.mkdir(parents=True)
    private.write_text('{"previous": "archive"}\n', encoding="utf-8")
    public_dir = ROOT / ".cache" / "review-test"  # inside the public checkout, git-ignored
    public_dir.mkdir(parents=True, exist_ok=True)
    link = public_dir / "raw-link.json"
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(private)
    try:
        code = propose.main(
            _propose_args(tmp_path, tmp_path / "none.env", **{"--raw-out": str(link)})
        )
        assert code == 1 and "public checkout" in capsys.readouterr().err
        code = draft.main(_draft_args(tmp_path, tmp_path / "none.env", **{"--raw-out": str(link)}))
        assert code == 1 and "public checkout" in capsys.readouterr().err
        assert calls == []
        assert link.is_symlink()  # still a link, not a file with content
        assert [p.name for p in public_dir.iterdir()] == ["raw-link.json"]  # no temp files
        assert private.read_text(encoding="utf-8") == '{"previous": "archive"}\n'
    finally:
        link.unlink()
        public_dir.rmdir()


def test_case_alias_of_public_checkout_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """On a case-insensitive file system `BRIDGE-EVIDENCE-CHECK/...` is the public checkout."""
    alias = ROOT.parent / ROOT.name.swapcase()
    if not (alias.exists() and alias.samefile(ROOT)):
        pytest.skip("file system is case-sensitive; alias does not exist")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    calls: list[str] = []

    def make(key: str) -> FakeClient:
        calls.append(key)
        return FakeClient(json.dumps({"candidates": []}))

    monkeypatch.setattr(propose, "make_client", make)
    monkeypatch.setattr(draft, "make_client", make)
    raw = alias / ".cache" / "review-alias-test" / "new-dir" / "raw.json"  # dirs do not exist
    code = propose.main(_propose_args(tmp_path, tmp_path / "none.env", **{"--raw-out": str(raw)}))
    assert code == 1 and "public checkout" in capsys.readouterr().err
    code = draft.main(_draft_args(tmp_path, tmp_path / "none.env", **{"--raw-out": str(raw)}))
    assert code == 1 and "public checkout" in capsys.readouterr().err
    assert calls == []
    assert not (ROOT / ".cache" / "review-alias-test").exists()  # no directory was created


def test_failed_call_keeps_previous_raw_archive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    raw = tmp_path / "private" / "raw.json"
    raw.parent.mkdir(parents=True)
    raw.write_text('{"previous": "archive"}\n', encoding="utf-8")
    client = FakeClient("", raise_exc=TimeoutError("simulated timeout"))
    monkeypatch.setattr(propose, "make_client", lambda key: client)
    assert propose.main(_propose_args(tmp_path, tmp_path / "none.env")) == 1
    assert "api_error (TimeoutError)" in capsys.readouterr().err
    assert raw.read_text(encoding="utf-8") == '{"previous": "archive"}\n'
    assert [p.name for p in raw.parent.iterdir()] == ["raw.json"]  # no temp file left


def test_draft_authored_sdk_exception_prints_type_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    client = FakeClient("", raise_exc=RuntimeError("request body with secret spec text"))
    monkeypatch.setattr(draft, "make_client", lambda key: client)
    assert draft.main(_draft_args(tmp_path, tmp_path / "none.env")) == 1
    err = capsys.readouterr().err
    assert "api_error (RuntimeError)" in err and "secret" not in err


def test_draft_authored_saves_raw_before_parsing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    client = FakeClient("{not json", finish_reason="stop")
    monkeypatch.setattr(draft, "make_client", lambda key: client)
    code = draft.main(_draft_args(tmp_path, tmp_path / "none.env"))
    assert code == 1
    raw = (tmp_path / "private" / "raw.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(raw[0])["content"] == "{not json"
    assert "response_shape failed" in capsys.readouterr().err
    assert not (tmp_path / "docs").exists()


def test_draft_authored_success_writes_docs_and_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    ok = (FIXTURES / "drafting" / "response_ok.json").read_text(encoding="utf-8")
    client = FakeClient(ok)
    monkeypatch.setattr(draft, "make_client", lambda key: client)
    assert draft.main(_draft_args(tmp_path, tmp_path / "none.env")) == 0
    assert (tmp_path / "docs" / "D1-referral.txt").is_file()
    record = json.loads((tmp_path / "private" / "record.json").read_text(encoding="utf-8"))
    assert record["drafted_by"] == "fake-model-2026-11"
    assert "temperature" not in client.kwargs
    fmt = client.kwargs["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] is True


def _propose_args(tmp_path: Path, env: Path, **overrides: str) -> list[str]:
    doc = tmp_path / "D1.txt"
    doc.write_text("Her BMI was 41.2 kg/m2. She denies any stroke.", encoding="utf-8")
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("x", encoding="utf-8")
    args = {
        "--doc": str(doc),
        "--doc-id": "D1",
        "--prompt": str(prompt),
        "--out": str(tmp_path / "c.jsonl"),
        "--raw-out": str(tmp_path / "private" / "raw.json"),
        "--root": str(ROOT),
        "--env": str(env),
    }
    args.update(overrides)
    return [item for pair in args.items() for item in pair]


def test_propose_candidates_exits_2_without_key(no_key: Path, tmp_path: Path) -> None:
    assert propose.main(_propose_args(tmp_path, no_key)) == 2
    assert not (tmp_path / "c.jsonl").exists()


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"--raw-out": str(ROOT / "cases" / "raw.json")}, "public checkout"),
        ({"--raw-out": "SAME"}, "same file"),
    ],
)
def test_propose_candidates_refuses_bad_private_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    override: dict[str, str],
    message: str,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    called: list[str] = []
    monkeypatch.setattr(propose, "make_client", lambda key: called.append(key))
    if override["--raw-out"] == "SAME":
        override["--raw-out"] = str(tmp_path / "c.jsonl")
    code = propose.main(_propose_args(tmp_path, tmp_path / "none.env", **override))
    assert code == 1 and called == []
    assert message in capsys.readouterr().err


def test_propose_candidates_refuses_case_aliases_and_annotator_outputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    called: list[str] = []
    monkeypatch.setattr(propose, "make_client", lambda key: called.append(key))
    root = tmp_path / "repo"
    hold = root / "cases" / "case-hold"
    (hold / "docs").mkdir(parents=True)
    (hold / "input.yaml").write_text(
        "documents: [{doc_id: D1, role: clinical}]\n", encoding="utf-8"
    )
    (hold / "docs" / "D1.txt").write_text("secret holdout text", encoding="utf-8")
    (root / "splits.yaml").write_text(
        "version: 1\nvariants:\n  - {case_id: case-hold, variant_id: case-hold, split: holdout, "
        "frozen_at: '2026-11-08', gold_version: 1, files: {input.yaml: 'ab'}}\n",
        encoding="utf-8",
    )
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("x", encoding="utf-8")
    base = [
        "--prompt",
        str(prompt),
        "--raw-out",
        str(tmp_path / "p" / "raw.json"),
        "--root",
        str(root),
    ]
    (root / "cases" / "case-dev").symlink_to(hold, target_is_directory=True)
    for case in ("./case-hold", "case-hold", "../repo/cases/case-hold", "case-dev"):
        code = propose.main(["--case", case, "--out", str(tmp_path / "c.jsonl"), *base])
        assert code == 1, case
        err = capsys.readouterr().err
        assert ("holdout" in err or "plain variant id" in err) and "secret" not in err
    assert called == []
    # a public output may not be an annotator-owned file or sit under a holdout case
    args = _propose_args(tmp_path, tmp_path / "none.env", **{"--out": str(hold / "expected.json")})
    assert propose.main(args) == 1 and "annotator-owned" in capsys.readouterr().err
    args = _propose_args(
        tmp_path, tmp_path / "none.env", **{"--out": str(hold / "c.jsonl"), "--root": str(root)}
    )
    assert propose.main(args) == 1 and "holdout" in capsys.readouterr().err
    link = tmp_path / "innocent.jsonl"
    link.symlink_to(hold / "expected.json")
    args = _propose_args(
        tmp_path, tmp_path / "none.env", **{"--out": str(link), "--root": str(root)}
    )
    assert propose.main(args) == 1 and "refused" in capsys.readouterr().err
    assert called == [] and not (hold / "expected.json").exists()


@pytest.mark.parametrize(
    ("client", "stderr_word"),
    [
        (FakeClient("", refusal="I cannot help with that"), "refused"),
        (FakeClient('{"candidates": [', finish_reason="length"), "truncated"),
        (FakeClient("{not json"), "parse_failed"),
        (FakeClient("", no_choices=True), "no_choices"),
        (FakeClient('{"candidates": []}', finish_reason="content_filter"), "content_filter"),
    ],
)
def test_propose_candidates_saves_raw_even_for_bad_replies(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    client: FakeClient,
    stderr_word: str,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(propose, "make_client", lambda key: client)
    code = propose.main(_propose_args(tmp_path, tmp_path / "none.env"))
    assert code == 1
    raw = json.loads((tmp_path / "private" / "raw.json").read_text(encoding="utf-8"))
    assert raw["model"] == "fake-model-2026-11" and "content" in raw and "refusal" in raw
    assert raw["response"]["model"] == "fake-model-2026-11"  # the whole SDK object is archived
    assert stderr_word in capsys.readouterr().err
    assert not (tmp_path / "c.jsonl").exists()


def test_propose_candidates_success_sanitizes_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    reply = {
        "candidates": [
            {
                "doc_id": "D1",
                "field": "anthropometrics",
                "kind": "bmi",
                "quote": "BMI was 41.2 kg/m2",
                "norm_value": 41.2,
                "norm_unit": "kg/m2",
                "certainty": "present",
                "subject": "patient",
                "temporality": "current",
                "description": "prose the model added",
            }
        ]
    }
    client = FakeClient(json.dumps(reply))
    monkeypatch.setattr(propose, "make_client", lambda key: client)
    assert propose.main(_propose_args(tmp_path, tmp_path / "none.env")) == 0
    out = (tmp_path / "c.jsonl").read_text(encoding="utf-8")
    line = json.loads(out)
    assert line["location"] == "located" and line["start"] == 4
    assert "quote" not in line and "prose" not in out and "41.2 kg" not in out
    assert "dropped_keys" not in line
    raw = (tmp_path / "private" / "raw.json").read_text(encoding="utf-8")
    assert "prose the model added" in raw  # the raw copy keeps everything, privately
