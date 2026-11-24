# Eval report, split=holdout, mode=online

prompt extract-v5 · schema v2 · rules bridge-v1 · splitter sentences-v1 · model returned claude-sonnet-5-5 · code dc69ba5b9b56f49182d579b15f9fbba6d2553175

One run of one model on 4 holdout variants, frozen before the run; not a validation on real records. Scoring rules: docs/eval.md. Every number is a count.

Skipped variants (never read, never scored):

- `case-01`: other_split
- `case-07`: other_split
- `case-07b`: other_split
- `case-02`: other_split
- `case-04`: other_split
- `case-03`: other_split
- `case-17`: other_split
- `case-15-L0`: other_split

## Totals (micro, all sections pooled)

| Measure | Count |
|---|---|
| Input variants (case families) | 4 (4) |
| Runs failed (kept in every denominator) | 0 |
| Conditions correct (status and flags) | 64/80 |
| Claims correct (status) | 18/26 |
| Missed exclusion evidence / gold review exclusion rows | 0/3 |
| Exclusion evidence found | 3 |
| Human workload (top-level review + conflict + insufficient) | 29 |
| Packets with at least one human item | 4/4 |

False supports next to their denominators (target 0; the columns are not combined):

| Rows | False supports | Gold non-supported | System supported | Correctly automated |
|---|---|---|---|---|
| conditions | 0 | 64 | 9 | 7/11 |
| claims | 0 | 13 | 10 | – |

First upstream error of every miss: compute_timepoint 6 · extraction_missed 4 · extraction_wrong_value 14.

## Regression against the baseline

No baseline to compare against (bootstrap): report only.

## Sections by text origin

False supports are reported per section and never summed across sections.

### Real text: MTSamples transcriptions (limited test on external text)

Variants: `case-09`, `case-12`

| Measure | Count |
|---|---|
| Input variants (case families) | 2 (2) |
| Runs failed (kept in every denominator) | 0 |
| Conditions correct (status and flags) | 31/40 |
| Claims correct (status) | 12/15 |
| Missed exclusion evidence / gold review exclusion rows | 0/2 |
| Exclusion evidence found | 2 |
| Human workload (top-level review + conflict + insufficient) | 16 |
| Packets with at least one human item | 2/2 |

False supports next to their denominators (target 0; the columns are not combined):

| Rows | False supports | Gold non-supported | System supported | Correctly automated |
|---|---|---|---|---|
| conditions | 0 | 31 | 4 | 2/4 |
| claims | 0 | 8 | 5 | – |

First upstream error of every miss: compute_timepoint 2 · extraction_missed 4 · extraction_wrong_value 6.

### Real text: published case reports (limited test on external text)

Variants: `case-18`

| Measure | Count |
|---|---|
| Input variants (case families) | 1 (1) |
| Runs failed (kept in every denominator) | 0 |
| Conditions correct (status and flags) | 17/20 |
| Claims correct (status) | 4/5 |
| Missed exclusion evidence / gold review exclusion rows | – |
| Exclusion evidence found | 0 |
| Human workload (top-level review + conflict + insufficient) | 7 |
| Packets with at least one human item | 1/1 |

False supports next to their denominators (target 0; the columns are not combined):

| Rows | False supports | Gold non-supported | System supported | Correctly automated |
|---|---|---|---|---|
| conditions | 0 | 17 | 1 | 2/3 |
| claims | 0 | 1 | 3 | – |

First upstream error of every miss: extraction_wrong_value 4.

### Authored cases (does each specified scenario and policy branch hold; not a measure of accuracy)

Variants: `case-10`

| Measure | Count |
|---|---|
| Input variants (case families) | 1 (1) |
| Runs failed (kept in every denominator) | 0 |
| Conditions correct (status and flags) | 16/20 |
| Claims correct (status) | 2/6 |
| Missed exclusion evidence / gold review exclusion rows | 0/1 |
| Exclusion evidence found | 1 |
| Human workload (top-level review + conflict + insufficient) | 6 |
| Packets with at least one human item | 1/1 |

False supports next to their denominators (target 0; the columns are not combined):

| Rows | False supports | Gold non-supported | System supported | Correctly automated |
|---|---|---|---|---|
| conditions | 0 | 16 | 4 | 3/4 |
| claims | 0 | 4 | 2 | – |

First upstream error of every miss: compute_timepoint 4 · extraction_wrong_value 4.

### Dirty-ladder variants (public final levels; none yet)

No variants in this section.

## Per condition (macro)

Live status per variant; a bold cell differs from gold and names the gold status.

| Row | case-09 | case-10 | case-12 | case-18 | Correct | False sup. | Source |
|---|---|---|---|---|---|---|---|
| `age_18` | sup | sup | sup | sup | 4/4 | 0 | faq |
| `bmi_path_a` | **rev** (gold con) | **rev** (gold not) | **ins** (gold sup) | **ins** (gold not) | 0/4 | 0 | faq |
| `bmi_path_b` | **ins** (gold sup) | ins | ins | ins | 3/4 | 0 | faq |
| `bmi_path_b.bmi` | **sup** (gold sup) | **sup** (gold sup) | **ins** (gold sup) | **ins** (gold sup) | 0/4 | 0 | faq |
| `bmi_path_b.ckd` | **ins** (gold sup) | ins | ins | ins | 3/4 | 0 | faq |
| `bmi_path_b.hfpef` | ins | ins | ins | ins | 4/4 | 0 | faq |
| `bmi_path_b.htn` | **ins** (gold rev) | **ins** (gold not) | ins | ins | 2/4 | 0 | factsheet |
| `bmi_path_c` | ins | ins | ins | ins | 4/4 | 0 | faq |
| `bmi_path_c.bmi` | **sup** (gold sup) | **sup** (gold sup) | **ins** (gold sup) | **ins** (gold sup) | 0/4 | 0 | faq |
| `bmi_path_c.mi` | ins | ins | not | ins | 4/4 | 0 | faq |
| `bmi_path_c.pad` | ins | ins | ins | ins | 4/4 | 0 | faq |
| `bmi_path_c.prediabetes` | ins | ins | ins | ins | 4/4 | 0 | faq |
| `bmi_path_c.stroke` | ins | ins | not | ins | 4/4 | 0 | faq |
| `exclusion.mash` | ins | ins | ins | ins | 4/4 | 0 | form |
| `exclusion.osa` | ins | ins | ins | ins | 4/4 | 0 | form |
| `exclusion.part_d_glp1` | ins | not | ins | ins | 4/4 | 0 | partd |
| `exclusion.t2dm` | rev | rev | rev | not | 4/4 | 0 | form |
| `lifestyle.activity` | ins | ins | ins | ins | 4/4 | 0 |  |
| `lifestyle.nutrition` | ins | ins | ins | ins | 4/4 | 0 |  |
| `patient_identity` | rev | sup | rev | rev | 4/4 | 0 | form |

### Claims

| Row | case-09 | case-10 | case-12 | case-18 | Correct | False sup. | Source |
|---|---|---|---|---|---|---|---|
| `claim.age_18` | sup | sup | sup | sup | 4/4 | 0 |  |
| `claim.bmi_bracket` | rev | **rev** (gold con) | **ins** (gold sup) | **ins** (gold sup) | 1/4 | 0 |  |
| `claim.bmi_path_b.ckd` | **ins** (gold sup) |  |  |  | 0/1 | 0 |  |
| `claim.bmi_path_b.htn` | rev | **rev** (gold con) | **ins** (gold rev) |  | 1/3 | 0 |  |
| `claim.bmi_path_c.mi` | ins |  | sup |  | 2/2 | 0 |  |
| `claim.bmi_path_c.prediabetes` |  |  | ins | ins | 2/2 | 0 |  |
| `claim.drug` | sup | sup | sup | sup | 4/4 | 0 |  |
| `claim.exclusion.mash` |  | **–** (gold ins) |  |  | 0/1 | 0 |  |
| `claim.exclusion.osa` |  |  | ins |  | 1/1 | 0 |  |
| `claim.exclusion.t2dm` | rev | **–** (gold con) | rev | sup | 3/4 | 0 |  |

## Per case

| Variant | Section | Run | Conditions | Claims | False sup. | Workload | First errors | Cost USD |
|---|---|---|---|---|---|---|---|---|
| `case-09` | mtsamples | completed | 14/20 | 6/7 | 0 | 8 | compute_timepoint 2 · extraction_missed 4 · extraction_wrong_value 1 | 0.0000 |
| `case-10` | authored | completed | 16/20 | 2/6 | 0 | 6 | compute_timepoint 4 · extraction_wrong_value 4 | 0.0000 |
| `case-12` | mtsamples | completed | 17/20 | 6/8 | 0 | 8 | extraction_wrong_value 5 | 0.0000 |
| `case-18` | case_report | completed | 17/20 | 4/5 | 0 | 7 | extraction_wrong_value 4 | 0.0000 |

## Facts and citations (micro)

| Gold facts | Matched | Matched, excluded by verify | Wrong value (timing only) | Missed | False positives | Expected-absent correct | Expected-absent FP |
|---|---|---|---|---|---|---|---|
| 106 | 46 | 9 | 46 (7) | 5 | 19 | 46 | 0 |

| Citation measure | Count |
|---|---|
| Quote located (verbatim or normalized) / evidence rows | 130/130 |
| Fact semantically correct (every key) / gold facts | 46/106 |
| Gold evidence recalled (span overlapped by a located row) / gold facts | 96/106 |

Position status: verbatim 130 · normalized 0 · candidate 0 · not_found 0.
Exclusion reasons: assertion_mismatch 14 · claim_document 20 · unparseable_value 1 · value_not_in_quote 8.

## Traps

A trap passes in a variant when the run completed and every id under that variant's `tests:` is correct; the first upstream error is tagged once per (trap, variant). Traps of one variant share a verdict (docs/eval.md).

| Trap | Passed | Results | First errors |
|---|---|---|---|
| `T-a1c-below-range-not-counterevidence` | 0/1 | case-18 fail (extraction_wrong_value/extract) | extraction_wrong_value 1 |
| `T-bmi-from-lb-in` | 0/1 | case-12 fail (extraction_wrong_value/extract) | extraction_wrong_value 1 |
| `T-borderline-diabetes-with-labs` | 0/1 | case-12 fail (extraction_wrong_value/extract) | extraction_wrong_value 1 |
| `T-ckd-stage-iv-stated` | 0/1 | case-09 fail (extraction_missed/extract) | extraction_missed 1 |
| `T-controlled-statement-vs-reading` | 0/1 | case-12 fail (extraction_wrong_value/extract) | extraction_wrong_value 1 |
| `T-cross-doc-bmi-conflict-across-threshold` | 0/1 | case-09 fail (extraction_missed/extract) | extraction_missed 1 |
| `T-diabetes-type-unspecified` | 0/1 | case-09 fail (extraction_missed/extract) | extraction_missed 1 |
| `T-disability-not-activity-exception` | 0/1 | case-18 fail (extraction_wrong_value/extract) | extraction_wrong_value 1 |
| `T-document-missing-patient-id` | 0/3 | case-09 fail (extraction_missed/extract), case-12 fail (extraction_wrong_value/extract), case-18 fail (extraction_wrong_value/extract) | extraction_missed 1 · extraction_wrong_value 2 |
| `T-explicit-baseline-bmi` | 0/1 | case-18 fail (extraction_wrong_value/extract) | extraction_wrong_value 1 |
| `T-htn-two-distinct-drugs-above-threshold` | 0/1 | case-09 fail (extraction_missed/extract) | extraction_missed 1 |
| `T-ischemic-heart-disease-not-mi` | 0/1 | case-09 fail (extraction_missed/extract) | extraction_missed 1 |
| `T-metric-and-imperial-side-by-side` | 0/1 | case-18 fail (extraction_wrong_value/extract) | extraction_wrong_value 1 |
| `T-negated-history-statements` | 0/1 | case-12 fail (extraction_wrong_value/extract) | extraction_wrong_value 1 |
| `T-nutrition-structured-strong` | 0/1 | case-18 fail (extraction_wrong_value/extract) | extraction_wrong_value 1 |
| `T-osa-probable-uncertain` | 0/1 | case-12 fail (extraction_wrong_value/extract) | extraction_wrong_value 1 |
| `T-pa-claim-contradicts-record` | 0/4 | case-09 fail (extraction_missed/extract), case-10 fail (extraction_wrong_value/extract), case-12 fail (extraction_wrong_value/extract), case-18 fail (extraction_wrong_value/extract) | extraction_missed 1 · extraction_wrong_value 3 |
| `T-pause-and-resume-not-new-start` | 0/1 | case-18 fail (extraction_wrong_value/extract) | extraction_wrong_value 1 |
| `T-post-initiation-measurements` | 0/1 | case-18 fail (extraction_wrong_value/extract) | extraction_wrong_value 1 |
| `T-presurgical-bmi-as-baseline` | 0/1 | case-10 fail (extraction_wrong_value/extract) | extraction_wrong_value 1 |
| `T-prior-glp1-self-pay` | 0/1 | case-10 fail (extraction_wrong_value/extract) | extraction_wrong_value 1 |
| `T-same-note-med-list-date` | 0/1 | case-09 fail (extraction_missed/extract) | extraction_missed 1 |
| `T-sedentary-explicit` | 0/1 | case-10 fail (extraction_wrong_value/extract) | extraction_wrong_value 1 |
| `T-stated-vs-computed-bmi-mismatch` | 0/1 | case-10 fail (extraction_wrong_value/extract) | extraction_wrong_value 1 |
| `T-steatosis-not-mash` | 0/1 | case-10 fail (extraction_wrong_value/extract) | extraction_wrong_value 1 |
| `T-t2dm-explicitly-negated` | 0/1 | case-18 fail (extraction_wrong_value/extract) | extraction_wrong_value 1 |
| `T-t2dm-in-remission` | 0/1 | case-10 fail (extraction_wrong_value/extract) | extraction_wrong_value 1 |

## Coverage matrix (trap × test type)

Filled cells 32/160; empty cells are listed under Not covered.

| Trap | isolated_real | isolated_minimal_pair | rules_fixture | integrated_case | ladder_level |
|---|---|---|---|---|---|
| `T-a1c-below-range-not-counterevidence` | – | – | – | case-18 | – |
| `T-antihypertensive-class-ambiguous` | – | – | htn-combination-pill | – | – |
| `T-bmi-exact-threshold` | – | – | bmi-29.9-vs-30.1 | – | – |
| `T-bmi-from-lb-in` | – | – | – | case-12 | – |
| `T-borderline-diabetes-with-labs` | – | – | – | case-12 | – |
| `T-ckd-stage-iv-stated` | – | – | – | case-09 | – |
| `T-combination-pill` | – | – | htn-combination-pill | – | – |
| `T-controlled-statement-vs-reading` | – | – | – | case-12 | – |
| `T-cross-doc-bmi-conflict-across-threshold` | – | – | – | case-09 | – |
| `T-diabetes-type-unspecified` | – | – | – | case-09 | – |
| `T-disability-not-activity-exception` | – | – | – | case-18 | – |
| `T-document-missing-patient-id` | – | – | – | case-09, case-12, case-18 | – |
| `T-explicit-baseline-bmi` | – | – | – | case-18 | – |
| `T-htn-two-distinct-drugs-above-threshold` | – | – | – | case-09 | – |
| `T-ischemic-heart-disease-not-mi` | – | – | – | case-09 | – |
| `T-metric-and-imperial-side-by-side` | – | – | – | case-18 | – |
| `T-negated-history-statements` | – | – | – | case-12 | – |
| `T-nutrition-structured-strong` | – | – | – | case-18 | – |
| `T-osa-probable-uncertain` | – | – | – | case-12 | – |
| `T-pa-claim-contradicts-record` | – | – | – | case-09, case-10, case-12, case-18 | – |
| `T-part-d-2026` | – | – | part-d-2025 | – | – |
| `T-pause-and-resume-not-new-start` | – | – | – | case-18 | – |
| `T-post-initiation-measurements` | – | – | – | case-18 | – |
| `T-presurgical-bmi-as-baseline` | – | – | – | case-10 | – |
| `T-prior-glp1-self-pay` | – | – | – | case-10 | – |
| `T-same-note-med-list-date` | – | – | – | case-09 | – |
| `T-sedentary-explicit` | – | – | – | case-10 | – |
| `T-stated-vs-computed-bmi-mismatch` | – | – | – | case-10 | – |
| `T-steatosis-not-mash` | – | – | – | case-10 | – |
| `T-t2dm-explicitly-negated` | – | – | – | case-18 | – |
| `T-t2dm-in-remission` | – | – | – | case-10 | – |
| `T-wrong-patient-same-dob` | – | – | identity-mismatch | – | – |

### Not covered

- `T-a1c-below-range-not-counterevidence`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-antihypertensive-class-ambiguous`: isolated_real, isolated_minimal_pair, integrated_case, ladder_level
- `T-bmi-exact-threshold`: isolated_real, isolated_minimal_pair, integrated_case, ladder_level
- `T-bmi-from-lb-in`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-borderline-diabetes-with-labs`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-ckd-stage-iv-stated`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-combination-pill`: isolated_real, isolated_minimal_pair, integrated_case, ladder_level
- `T-controlled-statement-vs-reading`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-cross-doc-bmi-conflict-across-threshold`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-diabetes-type-unspecified`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-disability-not-activity-exception`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-document-missing-patient-id`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-explicit-baseline-bmi`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-htn-two-distinct-drugs-above-threshold`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-ischemic-heart-disease-not-mi`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-metric-and-imperial-side-by-side`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-negated-history-statements`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-nutrition-structured-strong`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-osa-probable-uncertain`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-pa-claim-contradicts-record`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-part-d-2026`: isolated_real, isolated_minimal_pair, integrated_case, ladder_level
- `T-pause-and-resume-not-new-start`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-post-initiation-measurements`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-presurgical-bmi-as-baseline`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-prior-glp1-self-pay`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-same-note-med-list-date`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-sedentary-explicit`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-stated-vs-computed-bmi-mismatch`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-steatosis-not-mash`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-t2dm-explicitly-negated`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-t2dm-in-remission`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-wrong-patient-same-dob`: isolated_real, isolated_minimal_pair, integrated_case, ladder_level

## Gold origin

Facts by `origin`: model_candidate 39 · spec 67. Facts carrying a guideline clause: 106/106. Every scored gold fact was checked by the annotator; none was reviewed by a physician.

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
