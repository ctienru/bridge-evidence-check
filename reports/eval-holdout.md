# Eval report, split=holdout, mode=online

prompt extract-v4 · schema v2 · rules bridge-v1 · splitter sentences-v1 · model returned claude-sonnet-5-5 · code 395173651c75a560286bab6abd1d030120ed41aa

One run of one model on 3 holdout variants, frozen before the run; not a validation on real records. Scoring rules: docs/eval.md. Every number is a count.

Skipped variants (never read, never scored):

- `case-15-L0`: other_split

## Totals (micro, all sections pooled)

| Measure | Count |
|---|---|
| Input variants (case families) | 3 (3) |
| Runs failed (kept in every denominator) | 1 |
| Conditions correct (status and flags) | 27/60 |
| Claims correct (status) | 4/19 |
| Missed exclusion evidence / gold review exclusion rows | 3/3 |
| Exclusion evidence found | 0 |
| Human workload (top-level review + conflict + insufficient) | 16 |
| Packets with at least one human item | 3/3 |

False supports next to their denominators (target 0; the columns are not combined):

| Rows | False supports | Gold non-supported | System supported | Correctly automated |
|---|---|---|---|---|
| conditions | 0 | 51 | 2 | 2/7 |
| claims | 0 | 10 | 2 | – |

First upstream error of every miss: extraction_missed 9 · extraction_wrong_value 12 · run_failed 27.

## Regression against the baseline

No baseline to compare against (bootstrap): report only.

## Sections by text origin

False supports are reported per section and never summed across sections.

### Real text: MTSamples transcriptions (limited test on external text)

No variants in this section.

### Real text: published case reports (limited test on external text)

Variants: `case-11`, `case-14`, `case-16`

| Measure | Count |
|---|---|
| Input variants (case families) | 3 (3) |
| Runs failed (kept in every denominator) | 1 |
| Conditions correct (status and flags) | 27/60 |
| Claims correct (status) | 4/19 |
| Missed exclusion evidence / gold review exclusion rows | 3/3 |
| Exclusion evidence found | 0 |
| Human workload (top-level review + conflict + insufficient) | 16 |
| Packets with at least one human item | 3/3 |

False supports next to their denominators (target 0; the columns are not combined):

| Rows | False supports | Gold non-supported | System supported | Correctly automated |
|---|---|---|---|---|
| conditions | 0 | 51 | 2 | 2/7 |
| claims | 0 | 10 | 2 | – |

First upstream error of every miss: extraction_missed 9 · extraction_wrong_value 12 · run_failed 27.

### Authored cases (does each specified scenario and policy branch hold; not a measure of accuracy)

No variants in this section.

### Dirty-ladder variants (public final levels; none yet)

No variants in this section.

## Per condition (macro)

Live status per variant; a bold cell differs from gold and names the gold status.

| Row | case-11 | case-14 | case-16 | Correct | False sup. | Source |
|---|---|---|---|---|---|---|
| `age_18` | **–** (gold not) | sup | sup | 2/3 | 0 | faq |
| `bmi_path_a` | **–** (gold ins) | **ins** (gold sup) | **ins** (gold sup) | 0/3 | 0 | faq |
| `bmi_path_b` | **–** (gold ins) | ins | ins | 2/3 | 0 | faq |
| `bmi_path_b.bmi` | **–** (gold ins) | **ins** (gold sup) | **ins** (gold sup) | 0/3 | 0 | faq |
| `bmi_path_b.ckd` | **–** (gold ins) | ins | ins | 2/3 | 0 | faq |
| `bmi_path_b.hfpef` | **–** (gold ins) | ins | ins | 2/3 | 0 | faq |
| `bmi_path_b.htn` | **–** (gold ins) | ins | ins | 2/3 | 0 | factsheet |
| `bmi_path_c` | **–** (gold ins) | **ins** (gold rev) | **ins** (gold rev) | 0/3 | 0 | faq |
| `bmi_path_c.bmi` | **–** (gold ins) | **ins** (gold sup) | **ins** (gold sup) | 0/3 | 0 | faq |
| `bmi_path_c.mi` | **–** (gold ins) | ins | ins | 2/3 | 0 | faq |
| `bmi_path_c.pad` | **–** (gold ins) | ins | ins | 2/3 | 0 | faq |
| `bmi_path_c.prediabetes` | **–** (gold sup) | **ins** (gold rev) | **ins** (gold rev) | 0/3 | 0 | faq |
| `bmi_path_c.stroke` | **–** (gold ins) | ins | ins | 2/3 | 0 | faq |
| `exclusion.mash` | **–** (gold ins) | **ins** (gold rev) | ins | 1/3 | 0 | form |
| `exclusion.osa` | **–** (gold rev) | ins | **ins** (gold rev) | 1/3 | 0 | form |
| `exclusion.part_d_glp1` | **–** (gold not) | ins | ins | 2/3 | 0 | partd |
| `exclusion.t2dm` | **–** (gold ins) | **ins** (gold not) | ins | 1/3 | 0 | form |
| `lifestyle.activity` | **–** (gold ins) | ins | ins | 2/3 | 0 |  |
| `lifestyle.nutrition` | **–** (gold ins) | ins | ins | 2/3 | 0 |  |
| `patient_identity` | **–** (gold rev) | rev | rev | 2/3 | 0 | form |

### Claims

| Row | case-11 | case-14 | case-16 | Correct | False sup. | Source |
|---|---|---|---|---|---|---|
| `claim.age_18` | **–** (gold con) | sup | sup | 2/3 | 0 |  |
| `claim.bmi_bracket` | **–** (gold ins) | **ins** (gold sup) | **ins** (gold sup) | 0/3 | 0 |  |
| `claim.bmi_path_b.htn` | **–** (gold rev) |  |  | 0/1 | 0 |  |
| `claim.bmi_path_c.prediabetes` | **–** (gold sup) | ins | **ins** (gold rev) | 1/3 | 0 |  |
| `claim.drug` | **–** (gold sup) | **ins** (gold sup) | **ins** (gold sup) | 0/3 | 0 |  |
| `claim.exclusion.mash` |  | **–** (gold con) |  | 0/1 | 0 |  |
| `claim.exclusion.osa` | **–** (gold rev) |  | **–** (gold rev) | 0/2 | 0 |  |
| `claim.exclusion.t2dm` | **–** (gold ins) | **ins** (gold sup) | ins | 1/3 | 0 |  |

## Per case

| Variant | Section | Run | Conditions | Claims | False sup. | Workload | First errors | Cost USD |
|---|---|---|---|---|---|---|---|---|
| `case-11` | case_report | failed (parse) | 0/20 | 0/7 | 0 | – | run_failed 27 | 0.0720 |
| `case-14` | case_report | completed | 13/20 | 2/6 | 0 | 8 | extraction_wrong_value 11 | 0.0600 |
| `case-16` | case_report | completed | 14/20 | 2/6 | 0 | 8 | extraction_missed 9 · extraction_wrong_value 1 | 0.0483 |

## Facts and citations (micro)

| Gold facts | Matched | Matched, excluded by verify | Wrong value (timing only) | Missed | False positives | Expected-absent correct | Expected-absent FP |
|---|---|---|---|---|---|---|---|
| 64 | 11 | 7 | 15 (0) | 31 | 2 | 25 | 0 |

| Citation measure | Count |
|---|---|
| Quote located (verbatim or normalized) / evidence rows | 37/37 |
| Fact semantically correct (every key) / gold facts | 11/64 |
| Gold evidence recalled (span overlapped by a located row) / gold facts | 33/64 |

Position status: verbatim 37 · normalized 0 · candidate 0 · not_found 0.
Exclusion reasons: assertion_mismatch 1 · claim_document 8 · value_not_in_quote 5.

## Traps

A trap passes in a variant when the run completed and every id under that variant's `tests:` is correct; the first upstream error is tagged once per (trap, variant). Traps of one variant share a verdict (docs/eval.md).

| Trap | Passed | Results | First errors |
|---|---|---|---|
| `T-a1c-below-range-not-counterevidence` | 0/1 | case-14 fail (extraction_wrong_value/extract) | extraction_wrong_value 1 |
| `T-a1c-range-without-dx` | 0/1 | case-16 fail (extraction_missed/extract) | extraction_missed 1 |
| `T-advice-only-lifestyle` | 0/1 | case-14 fail (extraction_wrong_value/extract) | extraction_wrong_value 1 |
| `T-age-under-18` | 0/1 | case-11 fail (run_failed/parse) | run_failed 1 |
| `T-bmi-percentile` | 0/1 | case-11 fail (run_failed/parse) | run_failed 1 |
| `T-document-missing-patient-id` | 0/3 | case-11 fail (run_failed/parse), case-14 fail (extraction_wrong_value/extract), case-16 fail (extraction_missed/extract) | extraction_missed 1 · extraction_wrong_value 1 · run_failed 1 |
| `T-explicit-baseline-bmi` | 0/1 | case-16 fail (extraction_missed/extract) | extraction_missed 1 |
| `T-glucose-unit-g-per-l` | 0/1 | case-14 fail (extraction_wrong_value/extract) | extraction_wrong_value 1 |
| `T-htn-dx-without-readings` | 0/1 | case-11 fail (run_failed/parse) | run_failed 1 |
| `T-lifestyle-before-start-ongoing-unknown` | 0/1 | case-16 fail (extraction_missed/extract) | extraction_missed 1 |
| `T-mash-biopsy-f2` | 0/1 | case-14 fail (extraction_wrong_value/extract) | extraction_wrong_value 1 |
| `T-osa-on-cpap-unspecified-severity` | 0/1 | case-16 fail (extraction_missed/extract) | extraction_missed 1 |
| `T-osa-post-surgery` | 0/1 | case-11 fail (run_failed/parse) | run_failed 1 |
| `T-pa-claim-contradicts-record` | 0/3 | case-11 fail (run_failed/parse), case-14 fail (extraction_wrong_value/extract), case-16 fail (extraction_missed/extract) | extraction_missed 1 · extraction_wrong_value 1 · run_failed 1 |
| `T-payer-medicaid` | 0/1 | case-11 fail (run_failed/parse) | run_failed 1 |
| `T-post-initiation-measurements` | 0/1 | case-14 fail (extraction_wrong_value/extract) | extraction_wrong_value 1 |
| `T-t2dm-explicitly-negated` | 0/1 | case-14 fail (extraction_wrong_value/extract) | extraction_wrong_value 1 |
| `T-two-baseline-candidates-both-above` | 0/1 | case-16 fail (extraction_missed/extract) | extraction_missed 1 |

## Coverage matrix (trap × test type)

Filled cells 23/115; empty cells are listed under Not covered.

| Trap | isolated_real | isolated_minimal_pair | rules_fixture | integrated_case | ladder_level |
|---|---|---|---|---|---|
| `T-a1c-below-range-not-counterevidence` | – | – | – | case-14 | – |
| `T-a1c-range-without-dx` | – | – | – | case-16 | – |
| `T-advice-only-lifestyle` | – | – | – | case-14 | – |
| `T-age-under-18` | – | – | – | case-11 | – |
| `T-antihypertensive-class-ambiguous` | – | – | htn-combination-pill | – | – |
| `T-bmi-exact-threshold` | – | – | bmi-29.9-vs-30.1 | – | – |
| `T-bmi-percentile` | – | – | – | case-11 | – |
| `T-combination-pill` | – | – | htn-combination-pill | – | – |
| `T-document-missing-patient-id` | – | – | – | case-11, case-14, case-16 | – |
| `T-explicit-baseline-bmi` | – | – | – | case-16 | – |
| `T-glucose-unit-g-per-l` | – | – | – | case-14 | – |
| `T-htn-dx-without-readings` | – | – | – | case-11 | – |
| `T-lifestyle-before-start-ongoing-unknown` | – | – | – | case-16 | – |
| `T-mash-biopsy-f2` | – | – | – | case-14 | – |
| `T-osa-on-cpap-unspecified-severity` | – | – | – | case-16 | – |
| `T-osa-post-surgery` | – | – | – | case-11 | – |
| `T-pa-claim-contradicts-record` | – | – | – | case-11, case-14, case-16 | – |
| `T-part-d-2026` | – | – | part-d-2025 | – | – |
| `T-payer-medicaid` | – | – | – | case-11 | – |
| `T-post-initiation-measurements` | – | – | – | case-14 | – |
| `T-t2dm-explicitly-negated` | – | – | – | case-14 | – |
| `T-two-baseline-candidates-both-above` | – | – | – | case-16 | – |
| `T-wrong-patient-same-dob` | – | – | identity-mismatch | – | – |

### Not covered

- `T-a1c-below-range-not-counterevidence`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-a1c-range-without-dx`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-advice-only-lifestyle`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-age-under-18`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-antihypertensive-class-ambiguous`: isolated_real, isolated_minimal_pair, integrated_case, ladder_level
- `T-bmi-exact-threshold`: isolated_real, isolated_minimal_pair, integrated_case, ladder_level
- `T-bmi-percentile`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-combination-pill`: isolated_real, isolated_minimal_pair, integrated_case, ladder_level
- `T-document-missing-patient-id`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-explicit-baseline-bmi`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-glucose-unit-g-per-l`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-htn-dx-without-readings`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-lifestyle-before-start-ongoing-unknown`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-mash-biopsy-f2`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-osa-on-cpap-unspecified-severity`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-osa-post-surgery`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-pa-claim-contradicts-record`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-part-d-2026`: isolated_real, isolated_minimal_pair, integrated_case, ladder_level
- `T-payer-medicaid`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-post-initiation-measurements`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-t2dm-explicitly-negated`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-two-baseline-candidates-both-above`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-wrong-patient-same-dob`: isolated_real, isolated_minimal_pair, integrated_case, ladder_level

## Gold origin

Facts by `origin`: model_candidate 28 · spec 36. Facts carrying a guideline clause: 64/64. Every scored gold fact was checked by the annotator; none was reviewed by a physician.

## Policy sources

Rules table `bridge-v1`. Condition → source id: `age_18` faq, `bmi_path_a` faq, `bmi_path_b` faq, `bmi_path_b.bmi` faq, `bmi_path_b.ckd` faq, `bmi_path_b.hfpef` faq, `bmi_path_b.htn` factsheet, `bmi_path_c` faq, `bmi_path_c.bmi` faq, `bmi_path_c.mi` faq, `bmi_path_c.pad` faq, `bmi_path_c.prediabetes` faq, `bmi_path_c.stroke` faq, `exclusion.mash` form, `exclusion.osa` form, `exclusion.part_d_glp1` partd, `exclusion.t2dm` form, `patient_identity` form.

| Source id | Last modified |
|---|---|
| faq | 2026-08-06 |
| factsheet | – |
| form | – |
| partd | 2026-08-06 |

## Out of scope in this report

- verifier_ablation
- rules_only_unit_tests
