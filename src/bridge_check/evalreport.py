"""Markdown rendering of the public evaluation report (`reports/eval-dev.md`).

Input is the dictionary `export_public_report()` returned: ids, enum values and counts.
Every number is a count (`n/of` or a plain integer); there is no percentage anywhere.
Sections follow planning section 3 in this order: header, totals, regression, sections by
text origin, per-condition grid, per case, facts and citations, traps, coverage matrix,
gold origin, policy sources, out of scope.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from bridge_check.casemeta import SECTIONS

ABBREVIATIONS: dict[str, str] = {
    "supported": "sup",
    "not_supported": "not",
    "insufficient": "ins",
    "conflict": "con",
    "review": "rev",
}


def _c(counts: Mapping[str, Any]) -> str:
    return "–" if counts["of"] == 0 else f"{counts['n']}/{counts['of']}"


def _table(header: Sequence[str], rows: Iterable[Sequence[Any]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return lines


def _hist(d: Mapping[str, int]) -> str:
    items = [f"{k} {v}" for k, v in d.items() if v]
    return " · ".join(items) if items else "none"


def _false_support_rows(label: str, fs: Mapping[str, Any]) -> list[Any]:
    return [
        label,
        fs["count"],
        fs["gold_non_supported"],
        fs["system_supported"],
        _c(fs["correctly_automated"]),
    ]


def _totals(micro: Mapping[str, Any]) -> list[str]:
    lines = _table(
        ["Measure", "Count"],
        [
            ["Input variants (case families)", f"{micro['variants']} ({micro['case_families']})"],
            ["Runs failed (kept in every denominator)", micro["runs_failed"]],
            ["Conditions correct (status and flags)", _c(micro["conditions_correct"])],
            ["Claims correct (status)", _c(micro["claims_correct"])],
            [
                "Missed exclusion evidence / gold review exclusion rows",
                _c(micro["missed_exclusions"]),
            ],
            ["Exclusion evidence found", micro["exclusion_evidence_found"]],
            [
                "Human workload (top-level review + conflict + insufficient)",
                micro["human_workload"],
            ],
            ["Packets with at least one human item", _c(micro["packets_needing_human"])],
        ],
    )
    lines += [
        "",
        "False supports next to their denominators (target 0; the columns are not combined):",
        "",
        *_table(
            [
                "Rows",
                "False supports",
                "Gold non-supported",
                "System supported",
                "Correctly automated",
            ],
            [
                _false_support_rows("conditions", micro["false_supports"]),
                _false_support_rows("claims", micro["claims_false_supports"]),
            ],
        ),
        "",
        f"First upstream error of every miss: {_hist(micro['first_errors'])}.",
    ]
    return lines


def _facts(micro: Mapping[str, Any]) -> list[str]:
    f, c, p = micro["facts"], micro["citations"], micro["positions"]
    lines = _table(
        [
            "Gold facts",
            "Matched",
            "Matched, excluded by verify",
            "Wrong value (timing only)",
            "Missed",
            "False positives",
            "Expected-absent correct",
            "Expected-absent FP",
        ],
        [
            [
                f["gold_facts"],
                f["matched"],
                f["matched_but_excluded"],
                f"{f['wrong_value']} ({f['wrong_value_timing_only']})",
                f["missed"],
                f["false_positives"],
                f["absent_correct"],
                f["absent_false_positive"],
            ]
        ],
    )
    lines += [
        "",
        *_table(
            ["Citation measure", "Count"],
            [
                ["Quote located (verbatim or normalized) / evidence rows", _c(c["quotes_located"])],
                ["Fact semantically correct (every key) / gold facts", _c(c["facts_correct"])],
                [
                    "Gold evidence recalled (span overlapped by a located row) / gold facts",
                    _c(c["gold_evidence_recalled"]),
                ],
            ],
        ),
        "",
        f"Position status: verbatim {p['verbatim']} · normalized {p['normalized']} · "
        f"candidate {p['candidate']} · not_found {p['not_found']}.",
        f"Exclusion reasons: {_hist(micro['exclusion_reasons'])}.",
    ]
    return lines


def _grid(cases: Mapping[str, Any], group: str, rows: Sequence[Mapping[str, Any]]) -> list[str]:
    vids = list(cases)
    out = []
    for r in rows:
        cells = []
        for vid in vids:
            row = cases[vid][group].get(r["id"])
            if row is None:
                cells.append("")
                continue
            live = ABBREVIATIONS.get(row["status"] or "", "–")
            cells.append(
                live
                if row["correct"]
                else f"**{live}** (gold {ABBREVIATIONS.get(row['gold_status'], '?')})"
            )
        out.append(
            [
                f"`{r['id']}`",
                *cells,
                _c(r["correct"]),
                r["false_supports"],
                r["policy_source"] or "",
            ]
        )
    return _table(["Row", *vids, "Correct", "False sup.", "Source"], out)


def render_eval_markdown(report: Mapping[str, Any]) -> str:
    score = report["score"]
    micro = score["micro"]
    g = report["generated_from"]
    lines = [
        f"# Eval report, split={report['split']}, mode={report['mode']}",
        "",
        f"prompt {g['prompt_version']} · schema {g['schema_version']} · rules "
        f"{g['rules_version']} · splitter {g['splitter_version']} · model returned "
        f"{g['model_returned']} · code {g['code_sha']}",
        "",
        (
            f"One run of one model on {micro['variants']} dev variants. Not a holdout result; "
            "not a validation on real records."
            if report["split"] == "dev"
            else f"One run of one model on {micro['variants']} holdout variants, frozen before "
            "the run; not a validation on real records."
        )
        + " Scoring rules: docs/eval.md. Every number is a count.",
        "",
    ]
    if report["skipped"]:
        lines += ["Skipped variants (never read, never scored):", ""]
        lines += [f"- `{s['variant_id']}`: {s['reason']}" for s in report["skipped"]]
        lines.append("")
    if report["incomplete"]:
        lines += [
            "**Incomplete**: MTSamples documents were unavailable for at least one "
            "variant; those variants are missing from every count below.",
            "",
        ]
    lines += ["## Totals (micro, all sections pooled)", "", *_totals(micro), ""]

    b, reg = report["baseline"], report["regression"]
    lines += ["## Regression against the baseline", ""]
    if not b["found"]:
        lines += ["No baseline to compare against (bootstrap): report only.", ""]
    else:
        lines.append(
            f"Baseline `{b['ref']}` (sha256 `{b['sha256']}`). "
            + (
                "Gold changed for: " + ", ".join(f"`{v}`" for v in b["gold_changed"]) + ". "
                if b["gold_changed"]
                else ""
            )
            + ("**Regression detected.**" if reg["detected"] else "No regression.")
        )
        lines.append("")
        if reg["items"]:
            lines += _table(
                ["Variant", "Row", "Kind", "Before", "After"],
                [
                    [
                        i["variant_id"],
                        f"`{i['row']}`",
                        i["kind"],
                        f"{i['before_status']} {' '.join(i['before_flags'])}".strip(),
                        f"{i['after_status']} {' '.join(i['after_flags'])}".strip(),
                    ]
                    for i in reg["items"]
                ],
            )
            lines.append("")

    lines += [
        "## Sections by text origin",
        "",
        "False supports are reported per section and never summed across sections.",
        "",
    ]
    for name in SECTIONS:
        sec = score["sections"][name]
        m = sec["micro"]
        label = {
            "mtsamples": "Real text: MTSamples transcriptions (limited test on external text)",
            "case_report": "Real text: published case reports (limited test on external text)",
            "authored": "Authored cases (does each specified scenario and policy branch hold; "
            "not a measure of accuracy)",
            "dirty": "Dirty-ladder variants (public final levels; none yet)",
        }[name]
        lines.append(f"### {label}")
        lines.append("")
        if not sec["variants"]:
            lines += ["No variants in this section.", ""]
            continue
        lines.append("Variants: " + ", ".join(f"`{v}`" for v in sec["variants"]))
        lines.append("")
        lines += _totals(m)
        lines.append("")

    cases = score["cases"]
    lines += [
        "## Per condition (macro)",
        "",
        "Live status per variant; a bold cell differs from gold and names the gold status.",
        "",
        *_grid(cases, "conditions", score["macro"]["conditions"]),
        "",
        "### Claims",
        "",
        *_grid(cases, "claims", score["macro"]["claims"]),
        "",
    ]

    lines += [
        "## Per case",
        "",
        *_table(
            [
                "Variant",
                "Section",
                "Run",
                "Conditions",
                "Claims",
                "False sup.",
                "Workload",
                "First errors",
                "Cost USD",
            ],
            [
                [
                    f"`{vid}`",
                    c["section"],
                    c["run_status"] + (f" ({c['failed_stage']})" if c["failed_stage"] else ""),
                    _c(c["conditions_correct"]),
                    _c(c["claims_correct"]),
                    c["false_supports"]["count"] + c["claims_false_supports"]["count"],
                    "–" if c["human_workload"] is None else c["human_workload"],
                    _hist(c["first_errors"]),
                    "–" if c["cost_usd"] is None else f"{c['cost_usd']:.4f}",
                ]
                for vid, c in cases.items()
            ],
        ),
        "",
    ]

    lines += ["## Facts and citations (micro)", "", *_facts(micro), ""]

    lines += [
        "## Traps",
        "",
        "A trap passes in a variant when the run completed and every id under that "
        "variant's `tests:` is correct; the first upstream error is tagged once per "
        "(trap, variant). Traps of one variant share a verdict (docs/eval.md).",
        "",
    ]
    if score["traps"]:
        lines += _table(
            ["Trap", "Passed", "Results", "First errors"],
            [
                [
                    f"`{t['trap_id']}`",
                    f"{t['passed']}/{t['opportunities']}",
                    ", ".join(
                        f"{r['variant_id']} {'pass' if r['passed'] else 'fail'}"
                        + (f" ({r['first_error']}/{r['stage']})" if r["first_error"] else "")
                        for r in t["results"]
                    ),
                    _hist(t["first_errors"]),
                ]
                for t in score["traps"]
            ],
        )
    else:
        lines.append("No variant lists traps.")
    lines.append("")

    cov = score["coverage"]
    lines += [
        "## Coverage matrix (trap × test type)",
        "",
        f"Filled cells {_c(cov['filled'])}; empty cells are listed under Not covered.",
        "",
    ]
    if cov["traps"]:
        lines += _table(
            ["Trap", *cov["test_types"]],
            [
                [f"`{t}`", *(", ".join(cov["cells"][t][tt]) or "–" for tt in cov["test_types"])]
                for t in cov["traps"]
            ],
        )
        lines += ["", "### Not covered", ""]
        by_trap: dict[str, list[str]] = {}
        for nc in cov["not_covered"]:
            by_trap.setdefault(nc["trap_id"], []).append(nc["test_type"])
        lines += [f"- `{t}`: {', '.join(tts)}" for t, tts in by_trap.items()]
    else:
        lines.append("No traps listed.")
    lines.append("")

    lines += [
        "## Gold origin",
        "",
        f"Facts by `origin`: {_hist(score['gold_origin'])}. Facts carrying a guideline "
        f"clause: {_c(score['gold_with_clause'])}. Every scored gold fact was checked "
        "by the annotator; none was reviewed by a physician.",
        "",
    ]

    lines += [
        "## Policy sources",
        "",
        f"Rules table `{score['rules_version']}`. Condition → source id: "
        + ", ".join(f"`{k}` {v}" for k, v in score["condition_sources"].items())
        + ".",
        "",
        *_table(
            ["Source id", "Last modified"],
            [[s["id"], s["last_modified"] or "–"] for s in score["policy_sources"]],
        ),
        "",
    ]

    lines += ["## Out of scope in this report", "", *[f"- {x}" for x in score["out_of_scope"]], ""]
    return "\n".join(lines)
