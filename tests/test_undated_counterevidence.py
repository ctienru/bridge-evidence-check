"""Undated counter-evidence (contract §3.1 step 9, §2 claims): a verified BMI value of unknown
timing on the other side of a threshold turns a `supported` or `not_supported` BMI sub-result
into `review` + `undated_counterevidence`, and `claim.bmi_bracket` into `review` when the value
lies in another bracket. Every value and sentence here is invented."""

from __future__ import annotations

import json
import tempfile
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from conftest import FIXTURES, INITIATION, checked, decide
from leakcheck import mtsamples_files

from bridge_check import rules as rules_module
from bridge_check.cli import EXIT_OK, main
from bridge_check.evalrun import EvalOptions, run_eval
from bridge_check.rules import Decision, RuleInput
from bridge_check.verify import CheckedEvidence

FLAG = "undated_counterevidence"
BMI_IDS = ("bmi_path_a", "bmi_path_b.bmi", "bmi_path_c.bmi")

# `D1` carries a verified document date equal to the initiation date, so an undated fact in
# `D1` is at initiation; `D2` has no document date, so an undated fact in `D2` has unknown timing.
DOC_DATE_D1 = checked("doc_dates", target_doc_id="D1", date="2025-03-15", event_date="2025-03-15")
BASE = [INITIATION, DOC_DATE_D1]


def _bmi(value: str, **over: Any) -> CheckedEvidence:
    return checked("anthropometrics", kind="bmi", raw_value=value, **over)


def _height(cm: str, **over: Any) -> CheckedEvidence:
    return checked("anthropometrics", kind="height", raw_value=cm, raw_unit="cm", **over)


def _weight(kg: str, **over: Any) -> CheckedEvidence:
    return checked("anthropometrics", kind="weight", raw_value=kg, raw_unit="kg", **over)


def _undated(row_kind: Any, value: str, **over: Any) -> CheckedEvidence:
    return row_kind(value, doc_id="D2", relative_llm="unknown", **over)  # type: ignore[no-any-return]


def _statuses(d: dict[str, Decision]) -> dict[str, tuple[str, bool]]:
    return {cid: (d[cid].status, FLAG in d[cid].flags) for cid in BMI_IDS}


# id -> (rows after BASE, expected (status, flag present) for path A, B's BMI, C's BMI)
CASES: dict[str, tuple[list[CheckedEvidence], tuple[tuple[str, bool], ...]]] = {
    "above-with-undated-stated-below": (
        [_bmi("36.4"), _undated(_bmi, "26.1")],
        (("review", True), ("review", True), ("review", True)),
    ),
    "above-with-undated-weight-computing-below": (
        # at initiation 105 kg / 1.70 m -> 36.3; the undated 75 kg pairs with the only height
        # and computes 26.0
        [_height("170"), _weight("105"), _undated(_weight, "75")],
        (("review", True), ("review", True), ("review", True)),
    ),
    "below-with-undated-at-or-above": (
        [_bmi("25.2"), _undated(_bmi, "41.3")],
        (("review", True), ("review", True), ("review", True)),
    ),
    "same-side-far-apart": (
        [_bmi("36.4"), _undated(_bmi, "52.8")],
        (("supported", False), ("supported", False), ("supported", False)),
    ),
    "undated-exactly-at-the-threshold": (
        # 34.2 is below 35; an undated 35 is on the supporting side of 35 (>= is inclusive)
        [_bmi("34.2"), _undated(_bmi, "35.0")],
        (("review", True), ("supported", False), ("supported", False)),
    ),
    "undated-value-not-in-quote": (
        [_bmi("36.4"), _undated(_bmi, "26.1", exclusion_reasons=("value_not_in_quote",))],
        (("supported", False), ("supported", False), ("supported", False)),
    ),
    "undated-wrong-patient": (
        [_bmi("36.4"), _undated(_bmi, "26.1", exclusion_reasons=("wrong_patient",))],
        (("supported", False), ("supported", False), ("supported", False)),
    ),
    "other-side-but-before-initiation": (
        [_bmi("36.4"), _bmi("26.1", event_date="2025-02-10", relative_llm="before")],
        (("supported", False), ("supported", False), ("supported", False)),
    ),
    "other-side-but-after-initiation": (
        [_bmi("36.4"), _bmi("26.1", event_date="2025-04-20", relative_llm="after")],
        (("supported", False), ("supported", False), ("supported", False)),
    ),
    "already-conflict": (
        # 34.9 and 35.1 at initiation straddle 35: path A stays a conflict; the undated 28.4
        # crosses 30 and not 27
        [_bmi("34.9"), _bmi("35.1"), _undated(_bmi, "28.4")],
        (("conflict", False), ("review", True), ("supported", False)),
    ),
    "thresholds-judged-separately": (
        # the undated 32.3 crosses 35 but neither 30 nor 27
        [_bmi("36.4"), _undated(_bmi, "32.3")],
        (("review", True), ("supported", False), ("supported", False)),
    ),
    "case-a-stated-at-initiation-undated-weight-and-height": (
        # no stated BMI among the undated rows: 95 kg / 1.70 m -> 32.9
        [_bmi("36.4"), _undated(_height, "170"), _undated(_weight, "95")],
        (("review", True), ("supported", False), ("supported", False)),
    ),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_decide_bmi_with_undated_values(name: str) -> None:
    rows, expected = CASES[name]
    d = decide(BASE + rows)
    assert _statuses(d) == dict(zip(BMI_IDS, expected, strict=True))
    for cid in BMI_IDS:
        if FLAG in d[cid].flags:
            assert d[cid].rule_id == f"{cid}:9"
            assert "inconsistent_values" not in d[cid].flags
        else:
            assert "undated_counterevidence" not in d[cid].computed


def test_same_side_undated_value_adds_no_inconsistent_values() -> None:
    d = decide(BASE + [_bmi("36.4"), _undated(_bmi, "52.8")])
    assert d["bmi_path_a"].flags == () and d["bmi_path_a"].rule_id == "bmi_path_a:7"


def test_undated_evidence_stays_excluded_and_the_crossing_value_is_recorded() -> None:
    d = decide(BASE + [_bmi("36.4"), _undated(_bmi, "26.1")])["bmi_path_a"]
    # evidence ids follow the row order: 0 start, 1 document date, 2 BMI at initiation, 3 undated
    assert [(x.evidence_id, x.reason) for x in d.excluded_evidence] == [(3, "timing_unknown")]
    assert 3 not in d.used_evidence and 2 in d.used_evidence
    assert d.computed["bmi_raw"] == "36.4"
    assert d.computed["undated_counterevidence"] == [
        {"value": "26.1", "origin": "stated", "evidence": [3]}
    ]


def test_case_b_the_undated_weight_keeps_the_height_the_code_pairs_it_with() -> None:
    """At initiation 105 kg with the 170 cm of the same note (36.3). The undated 88 kg stands
    with its own 160 cm in the other document, so the undated candidate is 88 / 1.6² = 34.375;
    with the 170 cm it would be 30.4."""
    rows = BASE + [
        _height("170"),
        _weight("105"),
        _undated(_height, "160"),
        _undated(_weight, "88"),
    ]
    d = decide(rows)
    assert _statuses(d) == {
        "bmi_path_a": ("review", True),
        "bmi_path_b.bmi": ("supported", False),
        "bmi_path_c.bmi": ("supported", False),
    }
    found = d["bmi_path_a"].computed["undated_counterevidence"]
    assert [(c["origin"], Decimal(c["value"])) for c in found] == [("computed", Decimal("34.375"))]
    assert d["bmi_path_a"].computed["bmi_raw"].startswith("36.33")


def test_a_result_that_is_already_review_is_not_touched() -> None:
    d = decide(BASE + [_bmi("36.4", flags=("table_source",)), _undated(_bmi, "26.1")])
    assert d["bmi_path_a"].status == "review" and d["bmi_path_a"].rule_id == "bmi_path_a:8"
    assert FLAG not in d["bmi_path_a"].flags
    integer = decide(BASE + [_bmi("35"), _undated(_bmi, "26.1")])["bmi_path_a"]
    assert integer.rule_id == "bmi_path_a:6" and FLAG not in integer.flags


def test_no_measurement_at_initiation_is_still_insufficient() -> None:
    d = decide(BASE + [_undated(_bmi, "36.4")])
    for cid in BMI_IDS:
        assert d[cid].status == "insufficient" and FLAG not in d[cid].flags


def test_pathways_take_the_review_of_their_bmi_sub_result() -> None:
    d = decide(BASE + [_bmi("36.4"), _undated(_bmi, "26.1")])
    assert d["bmi_path_b"].status == "review" and d["bmi_path_c"].status == "review"


# --- claim.bmi_bracket ---------------------------------------------------------------------------


def _bracket_claim(rows: list[CheckedEvidence], claimed: str) -> Decision:
    claim = checked(
        "pa_form_claims", claim_id="claim.bmi_bracket", claimed_value=claimed, doc_id="D0"
    )
    d = decide(
        BASE + rows + [claim],
        doc_roles={"D0": "pa_draft", "D1": "clinical", "D2": "clinical"},
        doc_identity={"D0": "match", "D1": "match", "D2": "match"},
    )
    return d["claim.bmi_bracket"]


@pytest.mark.parametrize(
    ("claimed", "undated", "expected"),
    [
        pytest.param("35-39.9", None, "supported", id="agreeing-box-no-undated-value"),
        pytest.param("35-39.9", "32.9", "review", id="agreeing-box-undated-in-another-bracket"),
        pytest.param("35-39.9", "38.7", "supported", id="agreeing-box-undated-in-the-same-bracket"),
        pytest.param("30-34.9", None, "conflict", id="contradicted-box-no-undated-value"),
        pytest.param("30-34.9", "32.9", "review", id="contradicted-box-undated-in-another-bracket"),
        pytest.param("30-34.9", "38.7", "conflict", id="contradicted-box-undated-same-bracket"),
    ],
)
def test_bracket_claim_with_an_undated_value(
    claimed: str, undated: str | None, expected: str
) -> None:
    rows = [_bmi("36.4")] + ([_undated(_bmi, undated)] if undated else [])
    d = _bracket_claim(rows, claimed)
    assert d.status == expected
    assert d.rule_id == ("claim.bmi_bracket:5" if expected == "review" else "claim.bmi_bracket:4")
    if expected == "review":
        assert [x.reason for x in d.excluded_evidence] == ["timing_unknown"]


def test_bracket_claim_ignores_undated_values_that_are_not_candidates() -> None:
    excluded = _undated(_bmi, "32.9", exclusion_reasons=("value_not_in_quote",))
    assert _bracket_claim([_bmi("36.4"), excluded], "35-39.9").status == "supported"
    before = _bmi("32.9", event_date="2025-02-10", relative_llm="before")
    assert _bracket_claim([_bmi("36.4"), before], "35-39.9").status == "supported"


def test_bracket_claim_that_is_already_insufficient_is_not_touched() -> None:
    d = _bracket_claim([_undated(_bmi, "32.9")], "35-39.9")
    assert d.status == "insufficient" and d.rule_id == "claim.bmi_bracket:3"


# --- end to end, shaped like the reported failure ------------------------------------------------

_DOCS = {
    "D0-pa-form-draft": "PRIOR AUTHORIZATION REQUEST - DRAFT\nPatient ID: P-0440\n"
    "Drug requested: Wegovy\nBMI bracket: 35-39.9\n",
    "D1-referral": "Referral for weight management.\n"
    "Patient ID: P-0440. Date of birth 1961-08-09.\n"
    "Semaglutide (Wegovy) was started on 2025-03-15 for weight management.\n"
    "Height 170 cm.\nWeight 95 kg.\nBMI 32.9.\n",
    "D2-clinical": "Clinic visit 2025-03-15.\nPatient ID: P-0440.\nBMI 36.4.\n",
}
_ROLES = {"D0-pa-form-draft": "pa_draft", "D1-referral": "referral", "D2-clinical": "clinical"}
UNDATED_DOC = "D1-referral"


def _fact(doc_id: str, quote: str, relative: str = "unknown", **fields: object) -> dict[str, Any]:
    return {
        "doc_id": doc_id,
        "quote": quote,
        "certainty": "present",
        "subject": "patient",
        "temporality": "current",
        "event_date": "",
        "date_precision": "none",
        "relative_to_glp1_initiation": relative,
        **fields,
    }


def _anthro(doc_id: str, quote: str, kind: str, value: str, unit: str, relative: str) -> Any:
    return _fact(doc_id, quote, relative, kind=kind, raw_value=value, raw_unit=unit)


def _reply() -> dict[str, Any]:
    day = {"event_date": "2025-03-15", "date_precision": "day"}
    extraction = {
        "patient_identity": [
            _fact(
                "D1-referral",
                "Patient ID: P-0440. Date of birth 1961-08-09.",
                patient_id="P-0440",
                name="",
                dob="1961-08-09",
                stated_age=None,
            ),
            _fact(
                "D2-clinical",
                "Patient ID: P-0440.",
                patient_id="P-0440",
                name="",
                dob=None,
                stated_age=None,
            ),
        ],
        "doc_dates": [
            _fact(
                "D2-clinical",
                "Clinic visit 2025-03-15.",
                "at",
                target_doc_id="D2-clinical",
                date="2025-03-15",
                **day,
            )
        ],
        "glp1_start": [
            _fact(
                "D1-referral",
                "Semaglutide (Wegovy) was started on 2025-03-15 for weight management.",
                "at",
                drug="Wegovy",
                date="2025-03-15",
                purpose="weight",
                **day,
            )
        ],
        "anthropometrics": [
            _anthro("D2-clinical", "BMI 36.4.", "bmi", "36.4", "", "at"),
            _anthro(UNDATED_DOC, "Height 170 cm.", "height", "170", "cm", "unknown"),
            _anthro(UNDATED_DOC, "Weight 95 kg.", "weight", "95", "kg", "unknown"),
            _anthro(UNDATED_DOC, "BMI 32.9.", "bmi", "32.9", "", "unknown"),
        ],
        "pa_form_claims": [
            _fact(
                "D0-pa-form-draft",
                "BMI bracket: 35-39.9",
                claim_id="claim.bmi_bracket",
                claimed_value="35-39.9",
            )
        ],
    }
    template = json.loads(
        (FIXTURES / "rules" / "bmi-integer-30" / "fake-reply.json").read_text(encoding="utf-8")
    )
    block = next(b for b in template["content"] if b["type"] == "tool_use")
    block["input"] = {**{k: [] for k in block["input"]}, **extraction}
    return template  # type: ignore[no-any-return]


def _write_case(root: Path) -> Path:
    case = root / "undated-case"
    (case / "docs").mkdir(parents=True)
    for doc_id, text in _DOCS.items():
        (case / "docs" / f"{doc_id}.txt").write_text(text, encoding="utf-8")
    documents = "\n".join(f"  - {{doc_id: {d}, role: {r}}}" for d, r in _ROLES.items())
    (case / "input.yaml").write_text(
        "# Synthetic case: a BMI above 35 at initiation, undated values below 35 elsewhere.\n"
        "variant_id: undated-case\n"
        "assessment_date: 2026-10-15\n"
        "target_course: {drug: Wegovy, start: 2025-03-15}\n"
        'primary_patient: {patient_id: P-0440, name: "Synthetic Patient", dob: 1961-08-09}\n'
        f"documents:\n{documents}\n",
        encoding="utf-8",
    )
    (case / "fake-reply.json").write_text(json.dumps(_reply()), encoding="utf-8")
    return case


def test_end_to_end_undated_document_on_the_other_side_of_35(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BRIDGE_FAKE_CLIENT", "1")
    case = _write_case(tmp_path)
    db = str(tmp_path / "x.db")
    code = main(["check", str(case), "--db", db, "--json", "--explain"])
    report = json.loads(capsys.readouterr().out)
    assert code == EXIT_OK and report["status"] == "completed", report["dead_letters"]
    # every fact was located and none was excluded: the undated ones are verified evidence
    assert {(e["position_status"], tuple(e["exclusion_reasons"])) for e in report["evidence"]} == {
        ("verbatim", ())
    }
    by_id = {d["condition"]: d for d in report["decisions"]}
    path_a = by_id["bmi_path_a"]
    assert (path_a["status"], path_a["rule_id"]) == ("review", "bmi_path_a:9")
    assert path_a["flags"] == [FLAG]
    undated = [x for x in path_a["excluded_evidence"] if x["reason"] == "timing_unknown"]
    assert len(undated) == 3 and all(x["ref"].startswith(f"{UNDATED_DOC}[") for x in undated)
    # the reason names the triggering evidence by reference only
    assert all(x["ref"] in path_a["reason"] for x in undated)
    assert by_id["bmi_path_b.bmi"]["status"] == "supported"  # 32.9 does not cross 30
    assert by_id["bmi_path_b.bmi"]["flags"] == []
    assert by_id["claim.bmi_bracket"]["status"] == "review"
    assert by_id["claim.bmi_bracket"]["rule_id"] == "claim.bmi_bracket:5"

    code = main(["check", str(case), "--db", db, "--explain"])
    text = capsys.readouterr().out
    assert code == EXIT_OK
    assert f"bmi_path_a: review [bmi_path_a:9] flags={FLAG}" in text
    assert all(f"{x['ref']}(timing_unknown)" in text for x in undated)
    for sentence in ("Referral for weight", "Height 170 cm", "Weight 95 kg", "Synthetic"):
        assert sentence not in text


# --- invariant over the committed dev replays and the synthetic fixtures -------------------------


@pytest.fixture
def bmi_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[list[tuple[RuleInput, Decimal, Decision]]]:
    """Every `decide_bmi` call made while the test runs: its input, threshold and decision."""
    calls: list[tuple[RuleInput, Decimal, Decision]] = []
    original = rules_module.decide_bmi

    def recording(ri: RuleInput, condition: str, threshold: Decimal) -> Decision:
        decision = original(ri, condition, threshold)
        calls.append((ri, threshold, decision))
        return decision

    monkeypatch.setattr(rules_module, "decide_bmi", recording)
    yield calls


def _assert_no_conclusion_against_undated_values(
    calls: list[tuple[RuleInput, Decimal, Decision]],
) -> None:
    for ri, threshold, decision in calls:
        if decision.status not in ("supported", "not_supported"):
            continue
        used_side = Decimal(decision.computed["bmi_raw"]) >= threshold
        timing_unknown = {
            x.evidence_id for x in decision.excluded_evidence if x.reason == "timing_unknown"
        }
        for cand in ri.facts.bmi_candidates:
            if cand.tp.relative == "unknown" and timing_unknown.issuperset(cand.evidence_ids):
                assert (cand.value >= threshold) == used_side, (
                    f"{decision.condition} {decision.status} against undated evidence "
                    f"{list(cand.evidence_ids)}"
                )


def test_no_dev_replay_concludes_against_an_undated_value(
    bmi_calls: list[tuple[RuleInput, Decimal, Decision]],
) -> None:
    if not mtsamples_files():
        pytest.skip("MTSamples documents not fetched (scripts/fetch_mtsamples.py)")
    with tempfile.TemporaryDirectory() as out:
        code, report, _ = run_eval(EvalOptions(offline=True, out=Path(out), baseline_ref=None))
    assert code == 0 and bmi_calls
    assert len(bmi_calls) == 3 * len(report["score"]["cases"])
    _assert_no_conclusion_against_undated_values(bmi_calls)


def test_no_synthetic_fixture_concludes_against_an_undated_value(
    bmi_calls: list[tuple[RuleInput, Decimal, Decision]],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BRIDGE_FAKE_CLIENT", "1")
    fixtures = sorted(p for p in (FIXTURES / "rules").iterdir() if p.is_dir())
    fixtures.append(_write_case(tmp_path))
    for i, fixture in enumerate(fixtures):
        assert main(["check", str(fixture), "--db", str(tmp_path / f"{i}.db"), "--json"]) == EXIT_OK
        capsys.readouterr()
    assert len(bmi_calls) == 3 * len(fixtures)
    _assert_no_conclusion_against_undated_values(bmi_calls)
