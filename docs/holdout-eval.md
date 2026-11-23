# Holdout evaluation: cases 11, 14, 16 (2026-11-10) and cases 09, 10, 12, 18 (2026-11-23)

This page reports two holdout batches that were run on different configurations: cases 11, 14 and 16 on 2026-11-10 (prompt `extract-v4`), from the next paragraph down to "After this run", and cases 09, 10, 12 and 18 on 2026-11-23 (prompt `extract-v5`), under "Second holdout batch". The two batches are reported separately and are never summed.

Date: 2026-11-10 (live pass 08:45 to 08:46 UTC). Extractor `claude-sonnet-5-5` (model returned `claude-sonnet-5-5`), prompt `extract-v4`, schema `v2`, rules `bridge-v1`, drugs `drugs-v2`, verify terms as on main, splitter `sentences-v1`. Public code `395173651c75a560286bab6abd1d030120ed41aa` (the commit that wired `--split holdout` on top of main `f82c1463d595658c1a956ec936bd841abd75812d`, with no prompt, schema, rule or gold change). Private data at its main `1e92867`, gold version 1 for all three variants, frozen hashes re-verified before the run.

**One run of one model on three holdout variants. Single annotator, one run, one model; counts, not rates. Not a validation on real records.** Design-time known scenarios; the configuration was not adjusted on these inputs' results. The three variants were frozen (hash-only rows in `splits.yaml`) before the pipeline first ran on them.

No document text, quote or patient name appears here. Evidence is cited as `doc_id[start:end] sha8` in the report files only. The report files of this batch are `reports/eval-holdout.json` and `reports/eval-holdout.md` (the live pass); the private repository holds the raw responses, the redacted requests, the attempt rows, both passes' reports, the per-case gold comparisons and the run database.

## Gold disclosure

Before this run the annotator did not complete the final read of the three holdout golds or the line-by-line check of the excerpts against the articles; any later gold correction will be recorded in `changes` with a higher `gold_version` and disclosed here, and the corrected case is then reported as a regression case. Gold facts: 64, of which 36 from the spec and 28 from model candidates, all human-verified; all 64 carry a guideline clause; none was reviewed by a physician.

## Calls

Prices: $2.00 per million input tokens, $10.00 per million output tokens. Ceilings: $1.00 per run, $5.00 per evaluation, 4 attempts per run of which 1 parse-class, 300 s wall clock.

| Case | Input tokens | Output tokens | Latency | Cost | Attempts | Outcome |
|---|---|---|---|---|---|---|
| case-14 | 14,158 | 3,167 | 16.2 s | $0.0600 | 1 | parsed, run completed |
| case-16 | 13,275 | 2,170 | 10.5 s | $0.0483 | 1 | parsed, run completed |
| case-11 | 13,531 | 4,493 | 21.0 s | $0.0720 | 1 | parse failed, run failed |
| **Live pass** | 40,964 | 9,830 | | **$0.1802** | 3 | 2 completed, 1 failed |

**Case 11 failed at the parse stage.** The response was saved and then rejected by local schema validation: one `value_error` at `doc_dates[2].date`, whose validator accepts only `YYYY`, `YYYY-MM` or `YYYY-MM-DD` (the extractor wrote a document date in another shape). The run's single parse-class attempt was spent, so the run ended `failed` at stage `parse`. Under the scoring rules (`docs/eval.md`) it stays in every denominator with all 20 condition rows and all 7 claim rows counted wrong, first upstream error `run_failed`. It was not rerun.

**Cache pass and an unintended second call.** A second `bridge eval --split holdout` on the same database was meant to confirm determinism without an API call. Cases 14 and 16 were served from cache and reproduced every row, flag and count of the live pass exactly. Case 11 was not: a parse-failed attempt is final (only an interrupted `response_saved` attempt is replayed, `docs/recovery.md`), so the second pass made a new live call for case 11 (13,531 input tokens, 6,452 output tokens, 34.5 s, $0.0916), which parsed and completed. That call was not planned and is not part of the measurement: the configuration promised one call per case, so its scores are recorded in the private repository only and are not reported here. Total spent on the two passes: $0.2718.

## Totals (live pass; conditions and claims pooled where stated)

| Measure | Holdout (3 variants, 1 run failed) |
|---|---|
| Conditions correct (status and flags) | 27/60 |
| Claims correct (status) | 4/19 |
| False supports, conditions (target 0) | 0 of 51 gold non-supported rows; system supported 2 |
| False supports, claims | 0 of 10 gold non-supported rows; system supported 2 |
| Missed exclusion evidence | 3 of 3 gold `review` exclusion rows (one per case; case 11's by the failed run) |
| Human workload (top-level `review` + `conflict` + `insufficient`) | 16 (8 + 8 on cases 14 and 16; the failed run published no decisions) |
| Packets with at least one human item | 3/3 |
| Correctly automated among gold-automatable | 2/7 |
| Gold facts matched / wrong value / missed | 11 / 15 / 31 of 64 (7 matched but excluded by the verifier) |
| Quotes located | 37/37 |
| Cost of the live pass (USD, 3 calls) | $0.18 |

All three variants are in the `case_report` section (real text from a published case report plus authored referral and PA draft); the MTSamples, authored and dirty sections are empty in this report. Sections are never summed with the dev report.

## Per-case conditions (live status vs gold)

`sup` supported, `not` not_supported, `ins` insufficient, `con` conflict, `rev` review, `failed` no decision (run failed). A cell `live (gold)` is a miss.

| Condition | case-11 | case-14 | case-16 |
|---|---|---|---|
| age_18 | failed (not) | sup | sup |
| bmi_path_a | failed (ins) | ins (sup) | ins (sup) |
| bmi_path_b | failed (ins) | ins | ins |
| bmi_path_b.bmi | failed (ins) | ins (sup) | ins (sup) |
| bmi_path_b.ckd | failed (ins) | ins | ins |
| bmi_path_b.hfpef | failed (ins) | ins | ins |
| bmi_path_b.htn | failed (ins) | ins | ins |
| bmi_path_c | failed (ins) | ins (rev) | ins (rev) |
| bmi_path_c.bmi | failed (ins) | ins (sup) | ins (sup) |
| bmi_path_c.mi | failed (ins) | ins | ins |
| bmi_path_c.pad | failed (ins) | ins | ins |
| bmi_path_c.prediabetes | failed (sup) | ins (rev, gold flag `table_source`) | ins (rev, gold flag `table_source`) |
| bmi_path_c.stroke | failed (ins) | ins | ins |
| exclusion.mash | failed (ins) | ins (rev) | ins |
| exclusion.osa | failed (rev) | ins | ins (rev) |
| exclusion.part_d_glp1 | failed (not) | ins | ins |
| exclusion.t2dm | failed (ins) | ins (not) | ins |
| lifestyle.activity | failed (ins) | ins | ins |
| lifestyle.nutrition | failed (ins) | ins | ins |
| patient_identity | failed (rev, `id_missing`) | rev `id_missing` | rev `id_missing` |
| **Correct** | **0/20** | **13/20** | **14/20** |

Claims: case-14 2/6 (`claim.age_18`, `claim.bmi_path_c.prediabetes` correct; `claim.bmi_bracket`, `claim.drug`, `claim.exclusion.t2dm` insufficient where gold is supported; `claim.exclusion.mash` no decision where gold is conflict), case-16 2/6 (`claim.age_18`, `claim.exclusion.t2dm` correct; `claim.bmi_bracket`, `claim.drug` insufficient where gold is supported; `claim.bmi_path_c.prediabetes` insufficient where gold is review; `claim.exclusion.osa` no decision where gold is review), case-11 0/7 (run failed).

No condition and no claim was a false support. The two `supported` conditions the system produced (age_18 on cases 14 and 16) match gold.

## First upstream error of every miss (condition and claim rows pooled)

| Class | Rows |
|---|---|
| run_failed | 27 (case 11: 20 conditions, 7 claims) |
| extraction_wrong_value | 12 (case 14: 7 conditions, 4 claims; case 16: 1 claim) |
| extraction_missed | 9 (case 16: 6 conditions, 3 claims) |
| gold_question, verify_excluded, compute_timepoint, extraction_extra, rules | 0 |

Every miss on the two completed runs is charged to extraction. On case 14 the extractor located the baseline BMI, weight, fasting glucose and A1c with the right number but a wrong `event_date` and `relative_to_glp1_initiation` (so no fact sat at the GLP-1 start), gave the diagnoses a wrong `certainty` or `subject`, and the MASH diagnosis a wrong `certainty` and date; on case 16 it did not return the baseline weight, height and BMI, the A1c, the OSA diagnosis or the two lifestyle facts at all (9 gold facts missed), and misread the identity facts and the GLP-1 drug name. Every quote the extractor did return was located verbatim (37 of 37). The verifier, compute and rules stages produced no first error; the verifier excluded 7 returned facts that matched gold (identity facts quoted from the PA draft, `claim_document`; three facts whose value was not inside the quote, `value_not_in_quote`). The gold `review` exclusion evidence was extracted with a wrong assertion and then excluded on case 14, and not extracted on case 16. Trap pass rate is 0 of 22 trap ids listed by the three variants, because a trap passes only when the run completed and every row it covers is correct.

## What this run does not show

- One run and one model: the parse failure on case 11 may or may not recur; no rerun was made to find out.
- Three variants of one text origin; nothing here is clinic performance.
- The verifier ablation and the rules-only table are out of scope in this report, as in the dev report.
- The holdout golds have not had the annotator's final read (see the gold disclosure above).

## After this run

Added 2026-11-23. After this run, and using the failure classes reported above (`run_failed` on one badly shaped date, `extraction_wrong_value` on the dates and timepoints of baseline values, `extraction_missed` and the missed exclusion evidence), three things were changed: the retry budget (one more parse-class attempt per run, contract §11), the extraction prompt (`extract-v5`) and the binding of a date to its value in the verifier (contract §6). Cases 11, 14 and 16 are therefore no longer untouched test cases for any later configuration: a later result on them is a result on cases that informed the configuration. Nothing above this section was changed for these changes (the page title and the two sentences under it were written later, with the results of the second batch), and none of the three cases was run again for these changes.

## Second holdout batch: frozen and run once on 2026-11-23

The part down to 'Results' was written before the run (PR #67); only the sentences that said the batch had not been run were changed.

Four more holdout cases were frozen on 2026-11-23 under guide version 3, after the changes merged that day and before any pipeline run on them: cases 09, 10, 12 and 18. They are hash-only rows in `splits.yaml`. The batch was run once, on 2026-11-23; its results are under "Results" below. Nothing between this heading and "Results" is a result.

| Case | Main document | Gold version | Gold facts (from spec, from model candidates) |
|---|---|---|---|
| case-09 | MTSamples transcription | 2 | 25 (14, 11) |
| case-10 | authored documents only | 1 | 29 (29, 0) |
| case-12 | MTSamples transcription | 2 | 26 (14, 12) |
| case-18 | passage of a published case report (CC BY 4.0) | 1 | 26 (10, 16) |

Cases 09 and 12 are at gold version 2 because their main document was given a neutral document id on the day of the freeze, before any run and before the manifest listed them; no fact, position, value or status changed.

**Salted hashes.** For the two MTSamples main documents the manifest carries a salted sha256 (sha256 over a private 32-byte salt followed by the file bytes) instead of the plain hash, because the plain hash of a public transcription would identify it. The salt is kept in the private repository and can be disclosed to verify the commitment. Which transcriptions they are is not stated in this repository. Every other hash in the four rows is a plain sha256 of the file.

### How the gold was made, and how that differs from cases 11, 14 and 16

- **No blind draft.** Cases 11, 14 and 16 followed the route in `docs/dataside.md`, in which the annotator blind-labels the statuses and the inventory before seeing any model output. These four cases did not. The inventory of each case was proposed with AI assistance (Codex, `gpt-6.2-sol`) and confirmed by the annotator; it is stored privately as `assisted_review.json`, which has the format of `blind_draft.json`. No blind agreement count is reported for these four cases.
- **Statuses.** The 20 condition statuses were carried over from an expected-status table the annotator wrote before the documents were drafted, with one status, in one of the four cases, changed after reading the final documents.
- **Candidates.** Candidate facts were proposed by `gpt-6.1-sol`. It and the model that assisted the inventory are both OpenAI models; the extractor's model family was not involved.
- **Whose decisions.** Every verdict on a candidate, every gold fact and every status is the annotator's.
- **Read before the freeze.** The annotator read the real-text facts against the documents before the freeze. For cases 11, 14 and 16 the final read had not been completed before their run (gold disclosure above).

### Gaps these cases are expected to meet

Written down before the run. Each is a place where the contract and the code are known to differ, or where a table does not yet cover what the documents say:

- An undated baseline value named as the pre-treatment baseline is `at` in gold and stays `unknown` in the code (Known gaps, baseline wording).
- Diabetes written without a type has no rule yet.
- Two antihypertensives named in the documents are outside the drug table.
- Contract §5 ("Undated medication lists", `same_note_list`) treats a list in the same document as the blood-pressure reading, labelled as current medications, as in use on that document's date. Gold applies the same-note rule to a medication section whose heading does not say "current"; the verifier recognises a current list by its heading (`medication_list_status` in `rules/verify-terms-v1.yaml`, where a bare "Medications" heading is `unknown`) and may leave such a list unknown.
- The claim rule against a chart that documents type 2 diabetes in remission.
- The verifier's support terms for a stated absence of activity include "sedentary" and "no exercise", which gold does not read as a statement of no activity at all.

### Results

Date: 2026-11-23 (live pass 21:55 to 21:57 UTC). Extractor `claude-sonnet-5-5` (model returned `claude-sonnet-5-5`), prompt `extract-v5`, schema `v2`, rules `bridge-v1`, drugs `drugs-v2`, verify terms `verify-terms-v1`, splitter `sentences-v1`. Public code main `a62edc72ccdcaed9815b7bf0f6227c2cf03400d5`, clean tree, no local change. Private data at its main `d1d7fa1` (gold version 2 for cases 09 and 12, version 1 for cases 10 and 18), frozen hashes re-verified against the public manifest before the run.

**One live pass: four calls, one per case. No cache pass, no second pass, no rerun of any case.** Single annotator, one run, one model; counts, not rates. Not a validation on real records. The four variants were frozen (hash-only rows in `splits.yaml`) before the pipeline first ran on them, and nothing was changed after the run started.

The evaluation read a staged manifest: the public `splits.yaml` at `a62edc7` (sha256 `449ee7a0df62c170ef1b60defb05110d352ddf85064ec3ec76304a6023dc1c65`) with the rows of case-11, case-14 and case-16 removed and nothing else changed (sha256 `a86345f6a025beb79b7be6dd1926c48a42fcc8a991302aa75652cc8219076191`, the `manifest_sha256` of the report). Those three cases were not run and not staged.

No document text, quote or patient name appears here or in the report files. The report files are `reports/eval-holdout-round2.json` and `reports/eval-holdout-round2.md`: the run wrote them as `eval-holdout.json` and `eval-holdout.md`, and they are stored here under the new names, byte for byte, next to the first batch's `reports/eval-holdout.json` and `reports/eval-holdout.md`.

#### Calls

Prices: $2.00 per million input tokens, $10.00 per million output tokens. Ceilings: $1.00 per run, $5.00 per evaluation.

| Case | Input tokens | Output tokens | Latency | Cost | Attempts | Outcome |
|---|---|---|---|---|---|---|
| case-09 | 15,406 | 6,067 | 31.8 s | $0.0915 | 1 | parsed, run completed |
| case-10 | 13,792 | 4,630 | 22.4 s | $0.0739 | 1 | parsed, run completed |
| case-12 | 14,839 | 7,180 | 37.2 s | $0.1015 | 1 | parsed, run completed |
| case-18 | 14,696 | 3,978 | 20.8 s | $0.0692 | 1 | parsed, run completed |
| **Live pass** | 58,733 | 21,855 | | **$0.3360** | 4 | 4 completed, 0 failed |

All four responses parsed on the first attempt; all four runs completed. Exit code 0.

#### Totals (live pass, the four cases pooled)

| Measure | Holdout batch 2 (4 variants, 0 runs failed) |
|---|---|
| Conditions correct (status and flags) | 60/80 |
| Claims correct (status) | 9/26 |
| False supports, conditions (target 0) | 0 of 64 gold non-supported rows; system supported 1 |
| False supports, claims | 0 of 13 gold non-supported rows; system supported 2 |
| Missed exclusion evidence | 0 of 3 gold `review` exclusion rows |
| Human workload (top-level `review` + `conflict` + `insufficient`) | 33 |
| Packets with at least one human item | 4/4 |
| Correctly automated among gold-automatable | 3/11 |
| Gold facts matched / wrong value / missed | 37 / 55 / 5 of 106 (9 more matched but excluded by the verifier; 11 of the wrong values differ on timing only) |
| Quotes located | 130/130 |
| Cost of the live pass (USD, 4 calls) | $0.34 ($0.336016) |

Sections by text origin (never summed in the report): MTSamples transcriptions (case-09, case-12) conditions 29/40, claims 7/15; published case report (case-18) 16/20, 2/5; authored (case-10) 15/20, 0/6. Trap pass rate 0 of 32 trap opportunities (27 trap ids): a trap passes only when every row of its variant is correct.

#### Per-case conditions (live against gold)

`sup` supported, `not` not_supported, `ins` insufficient, `con` conflict, `rev` review, `–` no decision. A bold cell `live (gold …)` is a miss; flags follow the status.

| Condition | case-09 | case-10 | case-12 | case-18 |
|---|---|---|---|---|
| age_18 | **ins** (gold sup) | **ins** (gold sup) | **ins** (gold sup) | **ins** (gold sup) |
| bmi_path_a | **ins** (gold con) | **ins** (gold not `height_from_other_date`, `inconsistent_values`) | **ins** (gold sup) | **ins** (gold not) |
| bmi_path_b | **ins** (gold sup) | ins | ins | ins |
| bmi_path_b.bmi | **ins** (gold sup `inconsistent_values`) | **ins** (gold sup `height_from_other_date`, `inconsistent_values`) | **ins** (gold sup) | **ins** (gold sup) |
| bmi_path_b.ckd | **ins** (gold sup) | ins | ins | ins |
| bmi_path_b.hfpef | ins | ins | ins | ins |
| bmi_path_b.htn | **ins** (gold rev `class_ambiguous`, `same_note_list`) | **ins** (gold not `same_note_list`) | ins | ins |
| bmi_path_c | ins | ins | ins | ins |
| bmi_path_c.bmi | **ins** (gold sup `inconsistent_values`) | **ins** (gold sup `height_from_other_date`, `inconsistent_values`) | **ins** (gold sup) | **ins** (gold sup) |
| bmi_path_c.mi | ins | ins | not | ins |
| bmi_path_c.pad | ins | ins | ins | ins |
| bmi_path_c.prediabetes | ins | ins | ins | ins |
| bmi_path_c.stroke | ins | ins | not | ins |
| exclusion.mash | ins | ins | ins | ins |
| exclusion.osa | ins | ins | ins | ins |
| exclusion.part_d_glp1 | ins | not | ins | ins |
| exclusion.t2dm | rev | rev | rev | not |
| lifestyle.activity | ins | ins | ins | ins |
| lifestyle.nutrition | ins | ins | ins | ins |
| patient_identity | rev `id_missing` | sup | rev `id_missing` | rev `id_missing` |
| **Correct** | **13/20** | **15/20** | **16/20** | **16/20** |

#### Per-case claims (live against gold)

| Claim | case-09 | case-10 | case-12 | case-18 |
|---|---|---|---|---|
| claim.age_18 | **ins** (gold sup) | **ins** (gold sup) | **ins** (gold sup) | **ins** (gold sup) |
| claim.bmi_bracket | **ins** (gold rev) | **ins** (gold con) | **ins** (gold sup) | **ins** (gold sup) |
| claim.bmi_path_b.ckd | **ins** (gold sup) |  |  |  |
| claim.bmi_path_b.htn | rev | **rev** (gold con) | **ins** (gold rev) |  |
| claim.bmi_path_c.mi | ins |  | sup |  |
| claim.bmi_path_c.prediabetes |  |  | ins | ins |
| claim.drug | **ins** (gold sup) | **ins** (gold sup) | **ins** (gold sup) | **ins** (gold sup) |
| claim.exclusion.mash |  | **–** (gold ins) |  |  |
| claim.exclusion.osa |  |  | ins |  |
| claim.exclusion.t2dm | rev | **–** (gold con) | rev | sup |
| **Correct** | **3/7** | **0/6** | **4/8** | **2/5** |

No condition and no claim was a false support. The system produced `supported` on one condition (`patient_identity`, case-10) and two claims (`claim.bmi_path_c.mi`, case-12; `claim.exclusion.t2dm`, case-18); all three match gold.

#### Wrong rows: first upstream error and expected-gap attribution

The six expected gaps are the six items under "Gaps these cases are expected to meet" above, numbered in that order.

37 rows are wrong (20 conditions, 17 claims). First upstream error as the report gives it: compute_timepoint 2 · extraction_missed 6 · extraction_wrong_value 29. Attributed to one of the six expected gaps: **0**. "None of the six": 27. "Not attributed": 10. A row is listed under a gap only if the report's upstream error shows that gap; the notes say what the run records hold, they do not change any count. That no row is attributed does not show the gaps are absent: with no verified initiation date in any run, the rows where gaps 1, 3 and 4 act stopped earlier.

| Case | Row | Live | Gold | First upstream error (report) | Expected gap | Note |
|---|---|---|---|---|---|---|
| case-09 | age_18 | ins | sup | extraction_missed | none of the six | A |
| case-09 | bmi_path_a | ins | con | extraction_missed | none of the six | A |
| case-09 | bmi_path_b | ins | sup | extraction_missed | not attributed | C |
| case-09 | bmi_path_b.bmi | ins | sup `inconsistent_values` | extraction_missed | none of the six | A |
| case-09 | bmi_path_b.ckd | ins | sup | compute_timepoint | not attributed | C |
| case-09 | bmi_path_b.htn | ins | rev `class_ambiguous`, `same_note_list` | extraction_wrong_value | not attributed | D |
| case-09 | bmi_path_c.bmi | ins | sup `inconsistent_values` | extraction_missed | none of the six | A |
| case-09 | claim.age_18 | ins | sup | extraction_missed | none of the six | A |
| case-09 | claim.bmi_bracket | ins | rev | extraction_wrong_value | none of the six | A |
| case-09 | claim.bmi_path_b.ckd | ins | sup | compute_timepoint | not attributed | C |
| case-09 | claim.drug | ins | sup | extraction_wrong_value | none of the six | A |
| case-10 | age_18 | ins | sup | extraction_wrong_value | none of the six | A |
| case-10 | bmi_path_a | ins | not `height_from_other_date`, `inconsistent_values` | extraction_wrong_value | none of the six | A |
| case-10 | bmi_path_b.bmi | ins | sup `height_from_other_date`, `inconsistent_values` | extraction_wrong_value | none of the six | A |
| case-10 | bmi_path_b.htn | ins | not `same_note_list` | extraction_wrong_value | none of the six | A |
| case-10 | bmi_path_c.bmi | ins | sup `height_from_other_date`, `inconsistent_values` | extraction_wrong_value | none of the six | A |
| case-10 | claim.age_18 | ins | sup | extraction_wrong_value | none of the six | A |
| case-10 | claim.bmi_bracket | ins | con | extraction_wrong_value | none of the six | A |
| case-10 | claim.bmi_path_b.htn | rev | con | extraction_wrong_value | none of the six | A |
| case-10 | claim.drug | ins | sup | extraction_wrong_value | none of the six | A |
| case-10 | claim.exclusion.mash | – | ins | extraction_wrong_value | none of the six | E |
| case-10 | claim.exclusion.t2dm | – | con | extraction_wrong_value | not attributed | E, F |
| case-12 | age_18 | ins | sup | extraction_wrong_value | none of the six | A |
| case-12 | bmi_path_a | ins | sup | extraction_wrong_value | none of the six | A |
| case-12 | bmi_path_b.bmi | ins | sup | extraction_wrong_value | none of the six | A |
| case-12 | bmi_path_c.bmi | ins | sup | extraction_wrong_value | none of the six | A |
| case-12 | claim.age_18 | ins | sup | extraction_wrong_value | none of the six | A |
| case-12 | claim.bmi_bracket | ins | sup | extraction_wrong_value | none of the six | A |
| case-12 | claim.bmi_path_b.htn | ins | rev | extraction_wrong_value | not attributed |  |
| case-12 | claim.drug | ins | sup | extraction_wrong_value | none of the six | A |
| case-18 | age_18 | ins | sup | extraction_wrong_value | none of the six | A |
| case-18 | bmi_path_a | ins | not | extraction_wrong_value | not attributed | A, B |
| case-18 | bmi_path_b.bmi | ins | sup | extraction_wrong_value | not attributed | A, B |
| case-18 | bmi_path_c.bmi | ins | sup | extraction_wrong_value | not attributed | A, B |
| case-18 | claim.age_18 | ins | sup | extraction_wrong_value | none of the six | A |
| case-18 | claim.bmi_bracket | ins | sup | extraction_wrong_value | not attributed | A, B |
| case-18 | claim.drug | ins | sup | extraction_wrong_value | none of the six | A |

Notes:

- **A.** The stored decision is "no verified GLP-1 initiation date" (for the claims: "no verified initiation", "no BMI at initiation", or the condition's `insufficient` carried over; for case-10's hypertension rows: "no blood pressure reading at initiation"). This happened in all four runs. In each case the start fact of the referral was returned with the right date and located verbatim, and it is the gold fact that differs on `drug_canonical`: the extractor wrote the drug as a brand name followed by the ingredient in parentheses, and the GLP-1 name resolver (`glp1_canonical`), which maps a bare brand or a bare ingredient, returns that form unchanged, so no start row named the target course. Checked after the run by calling the resolver on the four stored strings; nothing was changed. The report charges these rows to extraction (`extraction_wrong_value`; `extraction_missed` on case-09). This is none of the six expected gaps.
- **B.** The gold reason of case-18's BMI rows rests on the baseline wording (expected gap 1: an undated baseline value is `at` in gold). The run stopped earlier, at A, and the report's first error is extraction, so gap 1 is not what the report shows.
- **C.** Report class `compute_timepoint` (`extraction_missed` for the parent row). Gold dates the diagnosis by a document date stated in the referral for the transcription; the extractor did not return that document-date fact, and the diagnosis row was also excluded by the verifier (`value_not_in_quote`). Not one of the six as far as the report shows.
- **D.** Gold flags `same_note_list` and `class_ambiguous` (the area of expected gaps 3 and 4). The stored decision is "no blood pressure reading at initiation": the reading was excluded by the verifier (`assertion_mismatch`) and there was no initiation date (A). Neither gap was reached.
- **E.** The form's box was returned with `certainty: negated` where gold has `present`, and the verifier excluded it (`assertion_mismatch`); no claim decision was produced for the row.
- **F.** Expected gap 5 (the claim rule against a chart that documents type 2 diabetes in remission) is the rule for this row; because of E the rule did not run.

#### Facts per case

| Case | Gold facts | Correct (matched) | Matched but excluded by the verifier | Wrong value (timing only) | Missed | False positives |
|---|---|---|---|---|---|---|
| case-09 | 25 | 8 | 2 | 13 (3) | 2 | 8 |
| case-10 | 29 | 14 | 3 | 12 (5) | 0 | 3 |
| case-12 | 26 | 9 | 2 | 13 (3) | 2 | 2 |
| case-18 | 26 | 6 | 2 | 17 (0) | 1 | 6 |
| **All** | 106 | 37 | 9 | 55 (11) | 5 | 19 |

Quotes located: 130/130 verbatim. Verifier exclusion reasons: assertion_mismatch 14, claim_document 20, unparseable_value 1, value_not_in_quote 8.

### What this run shows and does not show

- **False supports: 0.** Conditions: 0 of 64 gold non-supported rows. Claims: 0 of 13 gold non-supported rows. The system produced `supported` on one condition and two claims, and all three match gold.
- **Missed exclusion evidence: 0 of 3** gold `review` exclusion rows. The first batch missed 3 of 3.
- **Parsing.** All four responses parsed on the first attempt, so the second parse-class attempt was again not exercised.
- **37 rows are wrong** (20 conditions, 17 claims). None is attributed to the six gaps written down before the run. 30 of them, in all four cases, carry note A, one cause that was not predicted: the start fact was returned with the drug written as a brand name followed by the ingredient in parentheses, the GLP-1 name resolver does not resolve that form, and no initiation date was verified.
- **The expected gaps were not tested.** Because no initiation date was verified, the rows where expected gaps 1, 3 and 4 act stopped earlier. This run neither confirms nor refutes those gaps.
- **Trap pass rate: 0 of 32 trap opportunities** (27 trap ids). A trap passes in a variant only when the run completed and every row of that variant is correct, so one wrong row fails every trap the variant lists.
- **Scope.** One run, one model, single annotator, and no blind draft for these four cases. The numbers are counts, not rates, and they are not clinic performance.
- **Nothing was changed in response to this result.** From now on these four cases are used cases: any later run on them is a regression run.
