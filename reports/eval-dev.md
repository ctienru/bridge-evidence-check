# Eval report, split=dev, mode=offline

prompt extract-v4 · schema v2 · rules bridge-v1 · splitter sentences-v1 · model returned claude-sonnet-5-5 · code 90ae6089be091c08bfefa47557fe03d65c861853-dirty

One run of one model on 7 dev variants. Not a holdout result; not a validation on real records. Scoring rules: docs/eval.md. Every number is a count.

## Totals (micro, all sections pooled)

| Measure | Count |
|---|---|
| Input variants (case families) | 7 (6) |
| Runs failed (kept in every denominator) | 0 |
| Conditions correct (status and flags) | 133/140 |
| Claims correct (status) | 36/39 |
| Missed exclusion evidence / gold review exclusion rows | 0/2 |
| Exclusion evidence found | 2 |
| Human workload (top-level review + conflict + insufficient) | 47 |
| Packets with at least one human item | 7/7 |

False supports next to their denominators (target 0; the columns are not combined):

| Rows | False supports | Gold non-supported | System supported | Correctly automated |
|---|---|---|---|---|
| conditions | 0 | 112 | 24 | 16/18 |
| claims | 0 | 19 | 19 | – |

First upstream error of every miss: compute_timepoint 2 · extraction_wrong_value 7 · rules 1.

## Regression against the baseline

No baseline to compare against (bootstrap): report only.

## Sections by text origin

False supports are reported per section and never summed across sections.

### Real text: MTSamples transcriptions (limited test on external text)

Variants: `case-01`, `case-03`

| Measure | Count |
|---|---|
| Input variants (case families) | 2 (2) |
| Runs failed (kept in every denominator) | 0 |
| Conditions correct (status and flags) | 36/40 |
| Claims correct (status) | 12/15 |
| Missed exclusion evidence / gold review exclusion rows | 0/1 |
| Exclusion evidence found | 1 |
| Human workload (top-level review + conflict + insufficient) | 15 |
| Packets with at least one human item | 2/2 |

False supports next to their denominators (target 0; the columns are not combined):

| Rows | False supports | Gold non-supported | System supported | Correctly automated |
|---|---|---|---|---|
| conditions | 0 | 33 | 5 | 3/4 |
| claims | 0 | 8 | 6 | – |

First upstream error of every miss: extraction_wrong_value 7.

### Real text: published case reports (limited test on external text)

Variants: `case-17`

| Measure | Count |
|---|---|
| Input variants (case families) | 1 (1) |
| Runs failed (kept in every denominator) | 0 |
| Conditions correct (status and flags) | 20/20 |
| Claims correct (status) | 6/6 |
| Missed exclusion evidence / gold review exclusion rows | – |
| Exclusion evidence found | 0 |
| Human workload (top-level review + conflict + insufficient) | 8 |
| Packets with at least one human item | 1/1 |

False supports next to their denominators (target 0; the columns are not combined):

| Rows | False supports | Gold non-supported | System supported | Correctly automated |
|---|---|---|---|---|
| conditions | 0 | 18 | 2 | 1/1 |
| claims | 0 | 3 | 3 | – |

First upstream error of every miss: none.

### Authored cases (does each specified scenario and policy branch hold; not a measure of accuracy)

Variants: `case-02`, `case-04`, `case-07`, `case-07b`

| Measure | Count |
|---|---|
| Input variants (case families) | 4 (3) |
| Runs failed (kept in every denominator) | 0 |
| Conditions correct (status and flags) | 77/80 |
| Claims correct (status) | 18/18 |
| Missed exclusion evidence / gold review exclusion rows | 0/1 |
| Exclusion evidence found | 1 |
| Human workload (top-level review + conflict + insufficient) | 24 |
| Packets with at least one human item | 4/4 |

False supports next to their denominators (target 0; the columns are not combined):

| Rows | False supports | Gold non-supported | System supported | Correctly automated |
|---|---|---|---|---|
| conditions | 0 | 61 | 17 | 12/13 |
| claims | 0 | 8 | 10 | – |

First upstream error of every miss: compute_timepoint 2 · rules 1.

### Dirty-ladder variants (public final levels; none yet)

No variants in this section.

## Per condition (macro)

Live status per variant; a bold cell differs from gold and names the gold status.

| Row | case-01 | case-02 | case-03 | case-04 | case-07 | case-07b | case-17 | Correct | False sup. | Source |
|---|---|---|---|---|---|---|---|---|---|---|
| `age_18` | sup | sup | sup | sup | sup | sup | sup | 7/7 | 0 | faq |
| `bmi_path_a` | sup | not | **ins** (gold not) | not | ins | sup | ins | 6/7 | 0 | faq |
| `bmi_path_b` | ins | sup | ins | **ins** (gold sup) | ins | ins | ins | 6/7 | 0 | faq |
| `bmi_path_b.bmi` | sup | sup | **ins** (gold sup) | sup | ins | sup | ins | 6/7 | 0 | faq |
| `bmi_path_b.ckd` | ins | ins | ins | ins | ins | ins | ins | 7/7 | 0 | faq |
| `bmi_path_b.hfpef` | ins | sup | ins | ins | ins | ins | ins | 7/7 | 0 | faq |
| `bmi_path_b.htn` | ins | ins | ins | **ins** (gold sup) | not | not | ins | 6/7 | 0 | factsheet |
| `bmi_path_c` | ins | ins | ins | sup | ins | ins | ins | 7/7 | 0 | faq |
| `bmi_path_c.bmi` | sup | sup | **ins** (gold sup) | sup | ins | sup | ins | 6/7 | 0 | faq |
| `bmi_path_c.mi` | ins | ins | ins | ins | ins | ins | sup | 7/7 | 0 | faq |
| `bmi_path_c.pad` | ins | ins | ins | ins | ins | ins | ins | 7/7 | 0 | faq |
| `bmi_path_c.prediabetes` | ins | ins | ins | sup | ins | ins | ins | 7/7 | 0 | faq |
| `bmi_path_c.stroke` | not | ins | ins | ins | ins | ins | ins | 7/7 | 0 | faq |
| `exclusion.mash` | ins | ins | ins | ins | ins | ins | ins | 7/7 | 0 | form |
| `exclusion.osa` | ins | ins | rev | not | ins | ins | ins | 7/7 | 0 | form |
| `exclusion.part_d_glp1` | ins | rev | ins | ins | ins | ins | ins | 7/7 | 0 | partd |
| `exclusion.t2dm` | ins | ins | ins | ins | ins | ins | ins | 7/7 | 0 | form |
| `lifestyle.activity` | ins | ins | ins | **not** (gold rev) | ins | ins | ins | 6/7 | 0 |  |
| `lifestyle.nutrition` | **rev** (gold ins) | ins | ins | ins | ins | ins | ins | 6/7 | 0 |  |
| `patient_identity` | rev | sup | rev | sup | con | con | rev | 7/7 | 0 | form |

### Claims

| Row | case-01 | case-02 | case-03 | case-04 | case-07 | case-07b | case-17 | Correct | False sup. | Source |
|---|---|---|---|---|---|---|---|---|---|---|
| `claim.age_18` | sup | sup | sup | sup | sup | sup | sup | 7/7 | 0 |  |
| `claim.bmi_bracket` | sup | sup | **ins** (gold sup) | sup | ins | con | ins | 6/7 | 0 |  |
| `claim.bmi_path_b.hfpef` | ins | con |  |  |  |  | ins | 3/3 | 0 |  |
| `claim.bmi_path_b.htn` |  |  | **ins** (gold rev) |  | con | con | ins | 3/4 | 0 |  |
| `claim.bmi_path_c.mi` |  |  |  |  |  |  | sup | 1/1 | 0 |  |
| `claim.bmi_path_c.stroke` | sup |  |  |  |  |  |  | 1/1 | 0 |  |
| `claim.drug` | sup | sup | sup | sup | sup | sup | sup | 7/7 | 0 |  |
| `claim.exclusion.osa` |  |  | rev | con |  |  |  | 2/2 | 0 |  |
| `claim.exclusion.part_d_glp1` | ins |  |  |  |  |  |  | 1/1 | 0 |  |
| `claim.exclusion.t2dm` | ins |  |  |  |  |  |  | 1/1 | 0 |  |
| `claim.lifestyle.activity` | ins |  |  |  |  |  |  | 1/1 | 0 |  |
| `claim.lifestyle.nutrition` | **rev** (gold ins) |  | ins |  | ins | ins |  | 3/4 | 0 |  |

## Per case

| Variant | Section | Run | Conditions | Claims | False sup. | Workload | First errors | Cost USD |
|---|---|---|---|---|---|---|---|---|
| `case-01` | mtsamples | completed | 19/20 | 8/9 | 0 | 7 | extraction_wrong_value 2 | 0.0000 |
| `case-02` | authored | completed | 20/20 | 4/4 | 0 | 5 | none | 0.0000 |
| `case-03` | mtsamples | completed | 17/20 | 4/6 | 0 | 8 | extraction_wrong_value 5 | 0.0000 |
| `case-04` | authored | completed | 17/20 | 4/4 | 0 | 4 | compute_timepoint 2 · rules 1 | 0.0000 |
| `case-07` | authored | completed | 20/20 | 5/5 | 0 | 8 | none | 0.0000 |
| `case-07b` | authored | completed | 20/20 | 5/5 | 0 | 7 | none | 0.0000 |
| `case-17` | case_report | completed | 20/20 | 6/6 | 0 | 8 | none | 0.0000 |

## Facts and citations (micro)

| Gold facts | Matched | Matched, excluded by verify | Wrong value (timing only) | Missed | False positives | Expected-absent correct | Expected-absent FP |
|---|---|---|---|---|---|---|---|
| 158 | 116 | 21 | 17 (6) | 4 | 26 | 99 | 0 |

| Citation measure | Count |
|---|---|
| Quote located (verbatim or normalized) / evidence rows | 204/204 |
| Fact semantically correct (every key) / gold facts | 116/158 |
| Gold evidence recalled (span overlapped by a located row) / gold facts | 152/158 |

Position status: verbatim 204 · normalized 0 · candidate 0 · not_found 0.
Exclusion reasons: assertion_mismatch 10 · claim_document 27 · unparseable_value 2 · value_not_in_quote 3 · wrong_patient 10.

## Traps

A trap passes in a variant when the run completed and every id under that variant's `tests:` is correct; the first upstream error is tagged once per (trap, variant). Traps of one variant share a verdict (docs/eval.md).

| Trap | Passed | Results | First errors |
|---|---|---|---|
| `T-activity-medical-limitation` | 0/1 | case-04 fail (compute_timepoint/compute) | compute_timepoint 1 |
| `T-activity-not-documented` | 2/2 | case-07 pass, case-07b pass | none |
| `T-acute-bp-no-antihypertensives` | 1/1 | case-17 pass | none |
| `T-advice-only-lifestyle` | 0/1 | case-03 fail (extraction_wrong_value/extract) | extraction_wrong_value 1 |
| `T-antihypertensive-class-ambiguous` | 0/1 | case-03 fail (extraction_wrong_value/extract) | extraction_wrong_value 1 |
| `T-bmi-current-only-no-baseline` | 2/2 | case-07 pass, case-07b pass | none |
| `T-bmi-exact-threshold` | 1/1 | case-02 pass | none |
| `T-bmi-from-lb-in` | 0/1 | case-03 fail (extraction_wrong_value/extract) | extraction_wrong_value 1 |
| `T-combination-pill` | 0/1 | case-04 fail (compute_timepoint/compute) | compute_timepoint 1 |
| `T-hfpef-dx-authored` | 1/1 | case-02 pass | none |
| `T-hfref-finding-not-hfpef` | 1/1 | case-17 pass | none |
| `T-historical-mi-plus-acute-event` | 1/1 | case-17 pass | none |
| `T-osa-probable-uncertain` | 0/1 | case-03 fail (extraction_wrong_value/extract) | extraction_wrong_value 1 |
| `T-osa-sleep-study-negative` | 0/1 | case-04 fail (compute_timepoint/compute) | compute_timepoint 1 |
| `T-pa-claim-contradicts-record` | 3/4 | case-02 pass, case-04 fail (compute_timepoint/compute), case-07 pass, case-07b pass | compute_timepoint 1 |
| `T-part-d-2026` | 1/1 | case-02 pass | none |
| `T-pathway-overlap-b-and-c` | 0/1 | case-04 fail (compute_timepoint/compute) | compute_timepoint 1 |
| `T-post-initiation-measurements` | 0/1 | case-04 fail (compute_timepoint/compute) | compute_timepoint 1 |
| `T-wrong-patient-same-dob` | 2/2 | case-07 pass, case-07b pass | none |

## Coverage matrix (trap × test type)

Filled cells 24/95; empty cells are listed under Not covered.

| Trap | isolated_real | isolated_minimal_pair | rules_fixture | integrated_case | ladder_level |
|---|---|---|---|---|---|
| `T-activity-medical-limitation` | – | – | – | case-04 | – |
| `T-activity-not-documented` | – | – | – | case-07, case-07b | – |
| `T-acute-bp-no-antihypertensives` | – | – | – | case-17 | – |
| `T-advice-only-lifestyle` | – | – | – | case-03 | – |
| `T-antihypertensive-class-ambiguous` | – | – | htn-combination-pill | case-03 | – |
| `T-bmi-current-only-no-baseline` | – | – | – | case-07, case-07b | – |
| `T-bmi-exact-threshold` | – | – | bmi-29.9-vs-30.1 | case-02 | – |
| `T-bmi-from-lb-in` | – | – | – | case-03 | – |
| `T-combination-pill` | – | – | htn-combination-pill | case-04 | – |
| `T-hfpef-dx-authored` | – | – | – | case-02 | – |
| `T-hfref-finding-not-hfpef` | – | – | – | case-17 | – |
| `T-historical-mi-plus-acute-event` | – | – | – | case-17 | – |
| `T-osa-probable-uncertain` | – | – | – | case-03 | – |
| `T-osa-sleep-study-negative` | – | – | – | case-04 | – |
| `T-pa-claim-contradicts-record` | – | – | – | case-02, case-04, case-07, case-07b | – |
| `T-part-d-2026` | – | – | part-d-2025 | case-02 | – |
| `T-pathway-overlap-b-and-c` | – | – | – | case-04 | – |
| `T-post-initiation-measurements` | – | – | – | case-04 | – |
| `T-wrong-patient-same-dob` | – | – | identity-mismatch | case-07, case-07b | – |

### Not covered

- `T-activity-medical-limitation`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-activity-not-documented`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-acute-bp-no-antihypertensives`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-advice-only-lifestyle`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-antihypertensive-class-ambiguous`: isolated_real, isolated_minimal_pair, ladder_level
- `T-bmi-current-only-no-baseline`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-bmi-exact-threshold`: isolated_real, isolated_minimal_pair, ladder_level
- `T-bmi-from-lb-in`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-combination-pill`: isolated_real, isolated_minimal_pair, ladder_level
- `T-hfpef-dx-authored`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-hfref-finding-not-hfpef`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-historical-mi-plus-acute-event`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-osa-probable-uncertain`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-osa-sleep-study-negative`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-pa-claim-contradicts-record`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-part-d-2026`: isolated_real, isolated_minimal_pair, ladder_level
- `T-pathway-overlap-b-and-c`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-post-initiation-measurements`: isolated_real, isolated_minimal_pair, rules_fixture, ladder_level
- `T-wrong-patient-same-dob`: isolated_real, isolated_minimal_pair, ladder_level

## Gold origin

Facts by `origin`: model_candidate 31 · spec 127. Facts carrying a guideline clause: 158/158. Every scored gold fact was checked by the annotator; none was reviewed by a physician.

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
