# Evaluation: scoring, `bridge eval`, regression, baseline

> 2026-11-10. How the dev split is scored (`src/bridge_check/scoring.py`), what `bridge
> eval` writes (`reports/eval-dev.json`, `reports/eval-dev.md`), how a regression is decided
> against `reports/baseline-dev.json`, and how that baseline is updated. The rules below are
> the scoring rules of the planning document's evaluation-report section (3.1), named by
> their rows; the machine names are in `docs/contracts.md` §1, §8 and §11.

Every number in a report is a count. There are no percentages and no confidence intervals:
the dev set is a small, deliberately chosen functional test with several variants of one
case, and an interval over it would not describe clinic performance. Nothing here is a
"validation on real records".

## 1. What is scored

**Denominator.** One row per input variant (`case-07` and `case-07b` count separately); the
report also prints the number of case families (distinct `case_id`). A run that did not
complete (`failed`, or stopped at a stage boundary) stays in every denominator and counts
every condition and claim as wrong, tagged `run_failed`; it earns nothing, not even the
expected-absent rows.

**Fact matching.** Gold facts and evidence rows are matched one-to-one on the contract §8
keys: `field`, the kind or concept, the three assertion axes (certainty, subject,
temporality), `doc_id`, the normalized value within the §4 tolerances, the event date and
the computed timepoint. A stroke extracted as present where gold says negated is a false
positive plus a miss, never a match; a relative's MI extracted as the patient's is wrong.
Repeated quotes of one event are one record. Four conventions, all in
`src/bridge_check/compare.py`: a value gold does not state (`unknown`, `none_stated`,
`unspecified`) is compared as unwritten; medication `list_id`s are labels each side invents,
so gold lists are aligned to system lists before medications are compared; a gold fact with
no match is reported `wrong_value` against the closest row of the same field, selector and
document, with the differing keys named; a difference only in the event date or timepoint
that compute derived (not the extractor's own value) is a `compute_timepoint` error, not an
extraction error. The tests the contract names for this (`test_family_bp_is_not_patient_tp`,
`test_wrong_med_period_is_not_tp`, `test_ckd2_is_not_ckd3a_tp`,
`test_missing_gold_date_is_not_tp`) are in `tests/test_scoring.py`.

**Not found.** The system's "not found" is an empty array. An `expected_absent` entry the
system did not extract is `absent_correct`; one it extracted is `absent_false_positive`. A
gold fact without any row is `missed`.

**Conditions.** A condition is correct only when its status equals gold and its sorted flags
equal gold's flags; a claim only needs the status. A **false support** is a row the system
marks `supported` where gold does not. It is counted on its own and printed next to three
denominators that are never combined: the rows gold does not support (the opportunities),
the rows the system supports, and the gold-automatable top-level rows (gold `supported` or
`not_supported` on a condition, pathway or exclusion) the system settled correctly. The
target is zero false supports; the report prints whatever the count is.

**Position status and exclusion reasons.** Evidence rows are counted by the four position
statuses only (`verbatim`, `normalized`, `candidate`, `not_found`); evidence-level exclusion
reasons are a separate histogram.

**Policy source.** Every condition row carries the `source.id` of its rule in
`rules/bridge-v1.yaml`; the report ends with the rules-table version and the source list
(id and last-modified date). The source quotes stay in the rules table.

**Micro and macro.** Micro totals pool every row of the split; macro rows list each
condition and claim id with its correct count over the variants that score it and its live
status per variant, so a rare condition (PAD, HFpEF) stays visible.

**Three citation measures.** Quote located: evidence rows whose quote the verifier found
`verbatim` or `normalized`, over all evidence rows. Fact semantically correct: gold facts
matched on every key, over all gold facts. Gold evidence recall: gold facts whose span a
located system row of the same document overlaps, whatever that row's value, over all gold
facts. These are not ALCE's citation precision and recall; the definitions differ.

**Exclusion evidence.** For the four `exclusion.*` rows, besides the status comparison the
report counts the gold `review` rows (exclusion evidence exists) the system also marked
`review` (found) and those it marked `insufficient` or `not_supported` (missed).

**Human workload and correctly automated.** Human workload is the number of top-level rows
(conditions, pathways, exclusions) that are `review`, `conflict` or `insufficient`, the same
count `bridge check` prints; the report also counts packets with at least one such row. Next
to it stands "correctly automated among gold-automatable", so that sending everything to a
human cannot look safe.

**Two levels, first upstream error.** The case level is the condition rows above. The trap
level is diagnostic: every `trap_id` a variant lists in its hidden `case.yaml` passes when
the run completed and every id under that file's `tests:` is correct; otherwise it fails
with the most upstream error among the failing rows, in the order `gold_question`,
`extraction_missed`, `extraction_wrong_value`, `verify_excluded`, `compute_timepoint`,
`extraction_extra`, `rules`, mapped to the stage (gold, extract, verify, compute, rules).
One verdict per (trap, variant): the rows a miss drags down (a pathway after its BMI
sub-result) are not counted again. Limitation: the traps of one variant share a verdict,
because `case.yaml` lists traps and tested ids without saying which trap a given row
exercises. The coverage matrix says which isolated test covers each trap.

**Coverage matrix.** Rows are the trap ids of the public `case.yaml` files and of the rule
fixtures' `meta.yaml` (`fixtures/synthetic/rules/<name>/meta.yaml`, `trap_ids:` only);
columns are the five test types (isolated real text, isolated minimal pair, rules fixture,
integrated case, ladder level). A cell lists the variants or fixtures that fill it; the
"Not covered" list is every empty cell. Only the rules-fixture and integrated-case columns
can be filled today.

**Gold origin.** The report prints the count of gold facts per `origin` (`spec`,
`model_candidate`, `keyword_scan`, `human_inventory`) and the count carrying a
`guideline_clause`. Every scored gold fact was checked by the annotator; no physician
reviewed any of them.

**Sections.** Variants are grouped by the origin of their documents: real text from
MTSamples, real text from a published case report, authored cases, and dirty-ladder levels
(empty until a final ladder level is public). Each section carries its own totals and its own
false-support count; sections are never summed into one number. Dev and holdout are never in
one report: `bridge eval` accepts `--split dev` only, and every manifest row whose split is
not `dev` is skipped before its directory is named (`holdout_never_read`). A dev row whose
`cases/<variant_id>/` directory is absent from the data root is a hash-only row (its files
are kept in the private repo, contract §11): it is skipped with reason `hash_only`, listed
under `skipped`, never opened and never scored, and it does not make the report
incomplete; against a data root that holds the directory (`--data-root`) it is evaluated
like any other dev row, and the baseline records it by id under `hash_only` with no case
entry. A dev row whose directory, any path
beneath it, or its replay resolves into a holdout variant (a link) is refused before any
read (`holdout_path_refused`) and the evaluation exits 3; the exact path of every file
(`input.yaml`, each document, `expected.json`, `case.yaml`, the replay) is checked again
right before it is opened, so a link reached through a linked directory is refused too,
and a holdout directory is recognised by file-system identity, not only by its spelling.
The report, baseline, database and lock destinations are checked against the checkout and
the selected data root before anything is created; a report or baseline destination that is
a symbolic link or shares its inode with another name (a hard link) is refused, and every
write is an atomic replacement of the directory entry, so no existing file is ever
truncated in place. `input.yaml` is guarded inside the shared loader, so the case-id lookup
that precedes a run opens nothing in a holdout variant either. The baseline title guard
refuses a linked head file before reading it, with or without the marker. A case input,
document, gold file, `case.yaml` or replay with more than one hard link is refused before
it is opened (a hard link shares an inode, which no path check can see); no committed file
has more than one link. The link count is taken on the file a path resolves to, so a symbolic link
to a file that shares its inode with a holdout file is refused as well. The SQLite sidecars
(`-wal`, `-shm`, `-journal`), which SQLite writes and truncates by name, are checked like
any other destination: against both roots, and refused when they are links, before any
connection is opened (`bridge check`, `bridge eval` and the baseline script alike). SQLite
derives those names from the resolved database path, so the sidecars are checked next to
the path as given and next to the file it resolves to.
`scripts/build_baseline.py` writes through the same link-refusing, atomic writer as
`bridge eval`.

**Out of scope here.** The verifier ablation (with and without each verifier layer on the
same recorded extractions) and the rules-only unit-test table are listed under "Out of
scope" in every report until they exist.

## 2. How to read `eval-dev.md`

1. The header names the prompt, schema, rules, splitter and model versions, the code sha,
   skipped variants with their reasons (`holdout_never_read`, `hash_only`,
   `mtsamples_unavailable`, `holdout_path_refused`), and whether the report is incomplete
   (an MTSamples document could not be fetched, so that variant is missing from every
   count; a hash-only skip does not make it incomplete).
2. Totals: the micro counts above, with the false-support table.
3. Regression against the baseline: the ref, its sha256, and the items (section 3).
4. Sections by text origin, each with the same totals.
5. Per condition: live status per variant; a bold cell differs from gold and names the gold
   status; the last columns are the correct count, false supports and the policy source.
6. Per case: run status, counts, workload, first-error histogram, cost.
7. Facts and citations: fact outcomes, the three measures, position statuses, exclusion
   reasons.
8. Traps, then the coverage matrix and "Not covered".
9. Gold origin, policy sources, out of scope.

The JSON (`eval-dev.json`) holds the same content with every count as `{n, of}`; it is
sorted-key, has no timestamps, and two runs on one checkout produce identical bytes.
Everything in both files passed `export_public_report()`: every key and string is an id, an
enum value, a version, a hash, a date or an evidence reference `doc_id[start:end] sha8`.
Free text cannot pass.

## 3. How a regression is decided

`bridge eval --baseline-from <git ref>` reads `reports/baseline-dev.json` at that ref (CI
passes the PR base sha). Rows are compared by variant and condition or claim id against
the baseline rows (`status`, `flags`, `gold_status`, `gold_flags`, `correct`):

| Kind | Fires when |
|---|---|
| `false_support` | the row is now `supported` with gold not `supported`, and the baseline row was not |
| `status` | the baseline row was correct and the status now differs from gold |
| `flags` | the baseline row was correct, the status still matches, the flags no longer do (conditions and the case flags) |
| `exclusion_downgrade` | an `exclusion.*` row was `review` in the baseline and is now `insufficient` or `not_supported`, whatever gold says |
| `run_failed`, `case_missing` | a baseline variant whose run did not complete, or that the evaluation did not score |

Skipped variants are never compared. A variant whose gold hash differs from the baseline's
is named under `gold_changed`; the rules above still apply to it. Rows that exist on one side
only are ignored. A wrong row that stays wrong, a wrong row that becomes correct and an
unchanged `review` are not regressions.

Exit codes: 0 no regression, 1 regression, 3 a run failed, a dev variant was refused, or the
requested comparison could not run, 4 another run holds the lock. A failed run takes
precedence over a regression. Bootstrap, where the report is written without a comparison
and the exit code is 0 or 3, is only: no `--baseline-from`, the zero sha (a first push), or a
ref that resolves to a commit without the file. A ref that does not resolve, or a baseline
that does not validate, exits 3 after writing the report; the title guard fails the same way.

A new false support is a regression even in a row or variant the baseline does not have
(its prior false support is "none"); every current row is checked, not only the baseline's.

## 4. How to update the baseline

`reports/baseline-dev.json` is produced by the same code path as the evaluation
(`bridge_check.baseline.build`, also behind `scripts/build_baseline.py`). To refresh it from
the committed replays:

```
uv run bridge eval --split dev --offline --write-baseline
```

The file is written only when every dev run completed and no dev variant was refused or
left out for a missing MTSamples document; the write goes through the same output guard as
every other tool (a holdout path, an annotator-owned name or a link that resolves to one is
refused). A pull
request may change it only when its title carries `[update baseline]`; the CI step
`Baseline change guard` (`scripts/check_baseline_title.py`) fails otherwise, and always fails
when the base has the file and the head deleted it. The eval job then still prints the
regression items against the old baseline in the report. Ordinary pull requests leave the
file alone; an eval that finds a regression against it exits 1.

## 5. Offline mechanics

`--offline` seeds each run with the committed replay for the current input hash, prompt and
schema version (`replays/<variant_id>/<input_hash>-<prompt>-<schema>.json`): the
extraction is restored from offsets and hashes, written as a saved response under the run's
own attempt (`attempt_no = 0`, `response_saved`, cost null) and parsed through the ordinary
replay branch of the extractor, so the run's source is `replay` and no API request exists.
`bridge history` shows these attempts with number 0. The replay is required every time: a
live extraction a previous `check` cached for the same request is never used offline, and
replay-derived extractions sit under their own cache key (request key plus replay hash), so a
second offline run in one database reuses only its own seeded replay (`cache`). Without a
matching replay the run fails at `extract` and counts as wrong, whatever the database holds. `fixtures/synthetic/` is never a replay source. The
database is a fresh temporary file unless `--db` is given. A `case.yaml`, `meta.yaml` or
`splits.yaml` that does not parse stops the evaluation with exit 3 and a message that names
the file only, never a line of it.

Online evaluation (no `--offline`) uses the real client with the cache and saved responses
first; the per-evaluation cost ceiling is enforced by passing what earlier runs spent to
each extraction.

## 6. Version note

`compare_version` 2 splits the former `extraction_wrong_value` class into
`extraction_wrong_value` (a dependent gold fact with a wrong value) and `extraction_extra`
(a dependent fact gold does not hold, or an expected-absent hit). The per-case files under
`reports/checkpoint-a/` are version 1 and are kept as they were written.
