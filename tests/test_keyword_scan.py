from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from conftest import ROOT, load_script

from bridge_check.text import sha8


def _span(text: str, start: int, end: int) -> tuple[int, int, str]:
    return (start, end, sha8(text[start:end]))


scan = load_script("keyword_scan")


DRUGS_V2 = ROOT / "rules" / "drugs-v2.yaml"
SCAN_TERMS = ROOT / "rules" / "scan-terms-v1.yaml"
_DRUG_NAMES: list[str] = [
    str(n)
    for d in yaml.safe_load(DRUGS_V2.read_text(encoding="utf-8"))["drugs"]
    for n in d["names"]
]


@pytest.fixture(scope="module")
def scan_terms_casefolded() -> set[str]:
    return {t.casefold() for t in scan.load_terms(SCAN_TERMS, DRUGS_V2)}


@pytest.mark.parametrize("name", _DRUG_NAMES)
def test_scan_terms_include_drug_name(name: str, scan_terms_casefolded: set[str]) -> None:
    assert name.casefold() in scan_terms_casefolded


def test_scan_terms_follow_the_table_named_in_scan_terms_file() -> None:
    # Without an explicit drugs path the scan reads `include_drug_names_from`.
    lowered = {t.casefold() for t in scan.load_terms(SCAN_TERMS, None)}
    assert {n.casefold() for n in _DRUG_NAMES} <= lowered


def test_terms_include_every_drug_name() -> None:
    terms = scan.load_terms(ROOT / "rules" / "scan-terms-v1.yaml", ROOT / "rules" / "drugs-v2.yaml")
    drugs = yaml.safe_load((ROOT / "rules" / "drugs-v2.yaml").read_text(encoding="utf-8"))
    names = {n.casefold() for d in drugs["drugs"] for n in d["names"]}
    lowered = {t.casefold() for t in terms}
    assert names <= lowered
    assert "sedentary" in lowered and "diabetes" in lowered and "glp-1" in lowered


def test_word_boundary_for_alphanumeric_terms() -> None:
    assert scan.term_pattern("EF").search("EF 55%")
    assert not scan.term_pattern("EF").search("left arm")
    assert not scan.term_pattern("MI").search("Miami")
    assert scan.term_pattern("GLP-1").search("on a GLP-1 agonist")
    assert scan.term_pattern("Part D").search("covered under part d")
    assert not scan.term_pattern("A1c").search("HbA1c 5.9")  # alphanumeric: word-bounded
    assert scan.term_pattern("HbA1c").search("HbA1c 5.9")  # its own W-01 term
    assert scan.term_pattern("A1c").search("A1c 5.9%")


def test_covered_vs_uncovered_sentence() -> None:
    doc = "Her A1c was 5.9 percent. She takes amlodipine daily. No stroke history."
    terms = ["A1c", "amlodipine", "stroke"]
    uncovered = scan.scan_document("D9", doc, terms, covered=[])
    assert [(h["term"], doc[h["start"] : h["end"]]) for h in uncovered] == [
        ("A1c", "Her A1c was 5.9 percent."),
        ("amlodipine", "She takes amlodipine daily."),
        ("stroke", "No stroke history."),
    ]
    assert all(set(h) == {"doc_id", "start", "end", "sha8", "term"} for h in uncovered)
    assert uncovered[0]["sha8"] == sha8("Her A1c was 5.9 percent.")
    # a candidate quote overlapping the second sentence covers it
    start = doc.index("amlodipine")
    covered = scan.scan_document("D9", doc, terms, covered=[_span(doc, start, start + 5)])
    assert [h["term"] for h in covered] == ["A1c", "stroke"]


def test_first_is_not_an_abbreviation_so_bmi_hit_is_uncovered() -> None:
    doc = "The patient came first. BMI 41 was recorded."
    covered = [_span(doc, 0, 23)]  # a candidate quote on the first sentence only
    hits = scan.scan_document("D9", doc, ["BMI"], covered)
    assert [doc[h["start"] : h["end"]] for h in hits] == ["BMI 41 was recorded."]


def test_holdout_paths_and_cases_are_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path
    (root / "splits.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "variants": [
                    {
                        "case_id": "case-h",
                        "variant_id": "case-h",
                        "split": "holdout",
                        "frozen_at": "2026-11-08",
                        "gold_version": 1,
                        "files": {"input.yaml": "ab" * 32},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    doc = root / "cases" / "case-h" / "docs" / "D1.txt"
    doc.parent.mkdir(parents=True)
    doc.write_text("secret holdout text", encoding="utf-8")
    out = tmp_path / "u.jsonl"
    code = scan.main(["--doc", str(doc), "--doc-id", "D1", "--out", str(out), "--root", str(root)])
    assert code == 1
    err = capsys.readouterr().err
    assert "holdout" in err and "secret" not in err and not out.exists()
    assert scan.main(["--case", "case-h", "--out", str(out), "--root", str(root)]) == 1
    assert "holdout variant" in capsys.readouterr().err


def test_invalid_candidates_never_cover_hits(tmp_path: Path) -> None:
    doc = "Her A1c was 5.9 percent. Takes metoprolol daily."
    cands = tmp_path / "c.jsonl"
    cands.write_text(
        "\n".join(
            json.dumps(item)
            for item in (
                {
                    "doc_id": "D9",
                    "start": 0,
                    "end": 24,
                    "sha8": sha8(doc[0:24]),
                    "location": "invalid",
                },
                {
                    "doc_id": "D9",
                    "start": 25,
                    "end": 48,
                    "sha8": "00000000",
                    "location": "not_found",
                },
                {"doc_id": "D9", "start": 30, "end": 20, "sha8": "00000000"},
                {"doc_id": "D9", "start": -5, "end": 48, "sha8": "00000000"},
                {"doc_id": "D9", "start": "0", "end": 48, "sha8": "00000000"},
                {"doc_id": "D9", "start": 0, "end": 24},  # no sha8: cannot be verified
                {"doc_id": "D9", "start": 0, "end": 5000, "sha8": "00000000"},
                {"doc_id": "D9", "start": 25, "end": 48, "sha8": "deadbeef"},  # stale text
            )
        )
        + "\n",
        encoding="utf-8",
    )
    spans = scan.load_candidate_spans(cands)
    assert spans == {"D9": [(0, 5000, "00000000"), (25, 48, "deadbeef")]}
    hits = scan.scan_document("D9", doc, ["A1c", "metoprolol"], spans["D9"])
    assert [h["term"] for h in hits] == ["A1c", "metoprolol"]  # out of bounds / stale → ignored
    fresh = [_span(doc, 25, 48)]
    assert [h["term"] for h in scan.scan_document("D9", doc, ["A1c", "metoprolol"], fresh)] == [
        "A1c"
    ]


def test_symlinked_case_cannot_reach_holdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path
    hold = root / "cases" / "case-hold"
    (hold / "docs").mkdir(parents=True)
    (hold / "input.yaml").write_text(
        "documents: [{doc_id: D1, role: clinical}]\n", encoding="utf-8"
    )
    (hold / "docs" / "D1.txt").write_text("secret holdout text", encoding="utf-8")
    (root / "cases" / "case-dev").symlink_to(hold, target_is_directory=True)
    (root / "splits.yaml").write_text(
        "version: 1\nvariants:\n  - {case_id: case-hold, variant_id: case-hold, split: holdout, "
        "frozen_at: '2026-11-08', gold_version: 1, files: {input.yaml: 'ab'}}\n",
        encoding="utf-8",
    )
    out = tmp_path / "u.jsonl"
    assert scan.main(["--case", "case-dev", "--out", str(out), "--root", str(root)]) == 1
    err = capsys.readouterr().err
    assert "holdout" in err and "secret" not in err and not out.exists()
    # outputs: into the holdout dir, onto a symlinked expected.json, onto splits.yaml, onto a doc
    plain = root / "cases" / "case-plain" / "docs"
    plain.mkdir(parents=True)
    (plain / "D1.txt").write_text("a plain dev document", encoding="utf-8")
    link = tmp_path / "harmless.jsonl"
    link.symlink_to(root / "cases" / "case-plain" / "expected.json")
    for bad_out in (hold / "u.jsonl", link, root / "splits.yaml", plain / "D1.txt"):
        code = scan.main(
            [
                "--doc",
                str(plain / "D1.txt"),
                "--doc-id",
                "D1",
                "--out",
                str(bad_out),
                "--root",
                str(root),
            ]
        )
        assert code == 1, bad_out
        assert "refused" in capsys.readouterr().err
    assert (plain / "D1.txt").read_text(encoding="utf-8") == "a plain dev document"
    assert not (root / "cases" / "case-plain" / "expected.json").exists()


def test_holdout_linked_from_outside_is_refused_as_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "repo"
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (root / "cases").mkdir(parents=True)
    (root / "cases" / "case-hold").symlink_to(outside, target_is_directory=True)
    (root / "splits.yaml").write_text(
        "version: 1\nvariants:\n  - {case_id: case-hold, variant_id: case-hold, split: holdout, "
        "frozen_at: '2026-11-08', gold_version: 1, files: {input.yaml: 'ab'}}\n",
        encoding="utf-8",
    )
    doc = tmp_path / "d.txt"
    doc.write_text("plain text", encoding="utf-8")
    out = root / "cases" / "case-hold" / "u.jsonl"
    code = scan.main(["--doc", str(doc), "--doc-id", "D1", "--out", str(out), "--root", str(root)])
    assert code == 1 and "holdout" in capsys.readouterr().err
    assert not (outside / "u.jsonl").exists()


def test_bad_input_yaml_prints_no_snippet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    case = tmp_path / "cases" / "case-x"
    case.mkdir(parents=True)
    (case / "input.yaml").write_text("documents: [secret text here\n  - :: bad", encoding="utf-8")
    out = tmp_path / "u.jsonl"
    assert scan.main(["--case", "case-x", "--out", str(out), "--root", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "invalid YAML" in err and "secret" not in err


def test_cli_with_doc_and_candidates(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    text = "BMI 41 noted. Takes metoprolol. Unrelated sentence."
    doc = tmp_path / "jane-doe-visit.txt"  # the file name is never used as the id
    doc.write_text(text, encoding="utf-8")
    cands = tmp_path / "candidates.jsonl"
    cands.write_text(
        json.dumps({"doc_id": "D7-note", "start": 0, "end": 13, "sha8": sha8(text[0:13])}) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "uncovered.jsonl"
    with pytest.raises(SystemExit):  # --doc without --doc-id is refused by argparse
        scan.main(["--doc", str(doc), "--out", str(out)])
    with pytest.raises(SystemExit):
        scan.main(["--doc", str(doc), "--doc-id", "jane doe", "--out", str(out)])
    capsys.readouterr()
    code = scan.main(
        ["--doc", str(doc), "--doc-id", "D7-note", "--candidates", str(cands), "--out", str(out)]
    )
    assert code == 0
    printed = capsys.readouterr().out
    assert "D7-note" in printed and "jane" not in printed
    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [line["term"] for line in lines] == ["metoprolol"]  # drug name from drugs-v2.yaml
    assert lines[0]["doc_id"] == "D7-note"
    assert "jane" not in out.read_text(encoding="utf-8")
