# Holdout evaluation: cases 11, 14, 16 (2026-11-10) and cases 09, 10, 12, 18 (2026-11-23)

This page reports two holdout batches that were run on different configurations: cases 11, 14 and 16 on 2026-11-10 (prompt `extract-v4`), from the next paragraph down to "After this run", and cases 09, 10, 12 and 18 on 2026-11-23 (prompt `extract-v5`), under "Second holdout batch". The two batches are reported separately and are never summed. The last section, "Regression runs after the resolver fix (2026-11-23)", reports regression runs made on 2026-11-23 after a code change: the replay of the second batch has two false supports, and regression runs do not replace the results above.

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
- **Nothing was changed in response to this result** as of the publication of these results; see 'After this run' below. From now on these four cases are used cases: any later run on them is a regression run.

### After this run

Added 2026-11-23. After this run, and using the failure class it reported (note A: a start fact whose drug is written as a brand name followed by the ingredient in parentheses), one thing was changed: the GLP-1 name resolver (`glp1_canonical`, contract §5). A name of the form `outer (inner)` now resolves only when one part is a listed brand and the other part is exactly that brand's ingredient, in either order; every other name with a parenthesis stays unresolved, as before the change (a brand with another ingredient, a name next to a dose or any other word, a drug outside the list next to an ingredient). The change was designed from the description of the failure class and tested on strings written for the tests; the stored strings and the documents of the four cases were not read for it. Cases 09, 10, 12 and 18 were already used cases when the change was made and remain so. None of the seven holdout cases was run again and no rerun is reported here: the results above are those of the run before the change, and a later run on any of the seven cases is a regression run. Nothing above this section was changed.

Added later on 2026-11-23: the regression replay of this batch with that change is reported under "Regression runs" below; it has two false supports.

## Regression runs after the resolver fix (2026-11-23)

**The regression replay of the second batch (R2 below) has two false supports, both in case-09.** `bmi_path_a` is `supported` where gold is `conflict`, and `claim.bmi_bracket` is `supported` where gold is `review`. The published run of 2026-11-23 had both rows at `insufficient` and had no false support. What the run records show: with the resolver change the initiation date of case-09 is verified, so the BMI rows are now decided. The gold `doc_dates` fact that dates the transcription was not returned by the extractor, so the transcription's height, weight and BMI carry no date and are excluded as `timing_unknown`. The only BMI value counted is the one stated in the referral, which is dated at initiation. Gold counts the values of both documents, which disagree (`inconsistent_values`); the system saw one value, did not see the disagreement between the documents, and returned `supported`. Before the change the same missing date was hidden behind the unresolved drug name: the rows stopped at "no verified GLP-1 initiation date". Not fixed.

| Case | Row | Kind | Gold | Published 2026-11-23 | R2 regression |
|---|---|---|---|---|---|
| case-09 | bmi_path_a | condition | con | ins | **sup** |
| case-09 | claim.bmi_bracket | claim | rev | ins | **sup** |

Related, not false supports by the definition used here (gold status is `supported`): `bmi_path_b.bmi` and `bmi_path_c.bmi` of case-09 are `supported` without the `inconsistent_values` flag gold carries, for the same reason; they are counted wrong.

The regression run of the first batch (R1 below) has no false support: no row has the system at `supported` where gold is not `supported`.

**These are regression runs on used cases. The published results stand** and are not replaced by anything in this section: conditions 27/60 and claims 4/19 for cases 11, 14 and 16 (2026-11-10), conditions 60/80 and claims 9/26 for cases 09, 10, 12 and 18 (2026-11-23). All seven cases had already been run and read before the code changed, so no number in this section is a holdout measurement. Published and regression numbers are shown in separate, labelled columns and are never summed; the two regression runs are never summed either. Nothing above this section was changed for it, except the sentence added under the page title and the sentence added at the end of the second batch's "After this run".

In the tables of this section: `sup` supported, `not` not_supported, `ins` insufficient, `con` conflict, `rev` review, `–` no decision; flags follow the status.

### What each run is and is not

- **R2: cases 09, 10, 12, 18, replayed from the stored responses of 2026-11-23. No API call.** Same prompt, schema and inputs, so the extraction cache key is unchanged; the current code re-ran verify, compute and rules on the same model output. The only code difference from the published run is the resolver change (one file, `compute.py`), so R2 isolates its effect. It is not a new measurement of the extractor and not a holdout result.
- **R1: cases 11, 14, 16, one live pass, three calls, under the current configuration.** Their stored responses were recorded under `extract-v4` and cannot be replayed under `extract-v5`. R1 shows the current configuration on the first batch's cases; it mixes the effect of the prompt, the retry budget, the date binding, the rule changes and the resolver, and a new model response, and cannot attribute a change to any one of them. It is not a holdout result: the configuration was changed after these cases were read.
- Nothing was changed in response to what the runs showed: no gold, document, rule, prompt or code edit.
- Single annotator, one run, one model; counts, not rates. Not a validation on real records.

### Configuration

Extractor `claude-sonnet-5-5` (model returned `claude-sonnet-5-5` in R1; R2 reuses the responses of 2026-11-23, model returned `claude-sonnet-5-5`), prompt `extract-v5`, schema `v2`, rules `bridge-v1`, drugs `drugs-v2`, verify terms `verify-terms-v1`, splitter `sentences-v1`. Public code main `3b8f0fc7336ab5ac7c23baea952bfea03a5c1dc4`, clean tree before and after each command, nothing written into it. Private data at its main `13bbba0` (gold version 1 for cases 10, 11, 14, 16 and 18, version 2 for cases 09 and 12).

The published runs they are compared with: 2026-11-23 on public `a62edc72ccdcaed9815b7bf0f6227c2cf03400d5`, `extract-v5`; 2026-11-10 on public `395173651c75a560286bab6abd1d030120ed41aa`, `extract-v4`.

**Staged manifests.** Each run read a staged manifest: the public `splits.yaml` at `3b8f0fc` with the other batch's holdout rows removed and nothing else changed, next to real copies of the case directories (no links).

| Manifest | sha256 |
|---|---|
| public `splits.yaml` at `3b8f0fc` (unchanged since `a62edc7`) | `449ee7a0df62c170ef1b60defb05110d352ddf85064ec3ec76304a6023dc1c65` |
| R2 staged (rows of cases 11, 14, 16 removed; byte-identical to the 2026-11-23 one) | `a86345f6a025beb79b7be6dd1926c48a42fcc8a991302aa75652cc8219076191` |
| R1 staged (rows of cases 09, 10, 12, 18 removed) | `405a69992bf891ec15283416236a6334879083657718093128b2d3df6e512066` |

Each report's `manifest_sha256` is its staged value. Before each run the frozen files were verified: the private manifest check passed (8 variants: 1 dev, 7 holdout); R2, 45 of 45 files against the private manifest and 21 of 21 against the public rows (19 plain sha256 values, the two MTSamples documents by salted hash); R1, 33 of 33 and 15 of 15 (all plain).

Commands (each run once, from the public checkout):

```
# R2, with the API key absent from the environment of the process
bridge eval --split holdout --data-root <private>/.stage/eval --db <scratch>/r2.db --out <scratch>/r2 --json
# R1, with the key present, fresh database
bridge eval --split holdout --data-root <private>/.stage/eval --db <scratch>/r1.db --out <scratch>/r1 --json
```

Exit code 0 for both.

The report files are `reports/eval-holdout-round2-regression.json` and `reports/eval-holdout-round2-regression.md` (R2) and `reports/eval-holdout-regression.json` and `reports/eval-holdout-regression.md` (R1): each run wrote them as `eval-holdout.json` and `eval-holdout.md`, and they are stored here under the new names, byte for byte. The header of each file is the one the command writes for every `--split holdout` evaluation (it says "holdout" and "frozen before the run"); the files are the reports of regression runs. The four report files of the published runs (`reports/eval-holdout.json`, `reports/eval-holdout.md`, `reports/eval-holdout-round2.json`, `reports/eval-holdout-round2.md`) are unchanged. No document text, quote or patient name appears here or in the report files.

### R2: cases 09, 10, 12, 18 (replay, no API call)

`<scratch>/r2.db` was a copy of the archived run database of 2026-11-23 (same sha256 as the archive before the run). Proof that no request was sent: the API key was absent from the environment of the command (checked in the same environment before the run); the event log has one `extract_cache_hit` per case and no `attempt_started`; the database still holds exactly the 4 attempt rows of 2026-11-23 (newest attempt timestamp 21:57 UTC, before this run) next to 4 new run rows (ids 5 to 8) with `extraction_source: cache`, each pointing at the extraction of the published run; the report's cost is 0.

#### Totals (R2): published and regression side by side, never summed

| Measure | Published 2026-11-23 (live, `a62edc7`) | R2 regression (replay, `3b8f0fc`) |
|---|---|---|
| Conditions correct (status and flags) | 60/80 | 64/80 |
| Claims correct (status) | 9/26 | 18/26 |
| False supports, conditions (target 0) | 0 of 64 gold non-supported rows; system supported 1 | 1 of 64 gold non-supported rows; system supported 10 |
| False supports, claims | 0 of 13 gold non-supported rows; system supported 2 | 1 of 13 gold non-supported rows; system supported 11 |
| Missed exclusion evidence (gold `review` exclusion rows) | 0 of 3 | 0 of 3 |
| Human workload (top-level `review` + `conflict` + `insufficient`) | 33 | 27 |
| Packets with at least one human item | 4/4 | 4/4 |
| Correctly automated among gold-automatable | 3/11 | 7/11 |
| Gold facts matched / wrong value / missed | 37 / 55 / 5 of 106 (9 more matched but excluded by the verifier; 11 of the wrong values differ on timing only) | 46 / 46 / 5 of 106 (9 more matched but excluded by the verifier; 7 of the wrong values differ on timing only) |
| Quotes located | 130/130 | 130/130 |
| Runs failed | 0 | 0 |
| First upstream error of the wrong rows | compute_timepoint 2 · extraction_missed 6 · extraction_wrong_value 29 | compute_timepoint 5 · extraction_missed 4 · extraction_wrong_value 15 |
| Cost (USD) | $0.336016 (4 calls) | 0 (no call) |

| Case | Conditions, published | Conditions, regression | Claims, published | Claims, regression |
|---|---|---|---|---|
| case-09 | 13/20 | 14/20 | 3/7 | 5/7 |
| case-10 | 15/20 | 16/20 | 0/6 | 3/6 |
| case-12 | 16/20 | 17/20 | 4/8 | 6/8 |
| case-18 | 16/20 | 17/20 | 2/5 | 4/5 |


#### Rows that changed (R2)

| Change | All rows | Conditions | Claims |
|---|---|---|---|
| wrong → right | 13 | 4 | 9 |
| right → wrong | 0 | 0 | 0 |
| wrong → still wrong | 24 | 16 | 8 |
| – of which (different wrong status) | 7 | 6 | 1 |
| – of which (same status) | 17 | 10 | 7 |
| right → right | 69 | 60 | 9 |

Wrong → right (13): `age_18`, `claim.age_18` and `claim.drug` in all four cases, and `claim.bmi_bracket` in case-10.

| Case | Row | Gold | Published | Regression | First upstream error (regression) |
|---|---|---|---|---|---|
| case-09 | age_18 | sup | ins | sup |  |
| case-09 | claim.age_18 | sup | ins | sup |  |
| case-09 | claim.drug | sup | ins | sup |  |
| case-10 | age_18 | sup | ins | sup |  |
| case-10 | claim.age_18 | sup | ins | sup |  |
| case-10 | claim.bmi_bracket | con | ins | con |  |
| case-10 | claim.drug | sup | ins | sup |  |
| case-12 | age_18 | sup | ins | sup |  |
| case-12 | claim.age_18 | sup | ins | sup |  |
| case-12 | claim.drug | sup | ins | sup |  |
| case-18 | age_18 | sup | ins | sup |  |
| case-18 | claim.age_18 | sup | ins | sup |  |
| case-18 | claim.drug | sup | ins | sup |  |

Right → wrong: none.

Wrong → still wrong with a different wrong status (7):

| Case | Row | Gold | Published | Regression | First upstream error (regression) |
|---|---|---|---|---|---|
| case-09 | bmi_path_a | con | ins | sup **(false support)** | extraction_missed |
| case-09 | bmi_path_b.bmi | sup `inconsistent_values` | ins | sup | extraction_missed |
| case-09 | bmi_path_c.bmi | sup `inconsistent_values` | ins | sup | extraction_missed |
| case-09 | claim.bmi_bracket | rev | ins | sup **(false support)** | extraction_wrong_value |
| case-10 | bmi_path_a | not `height_from_other_date`, `inconsistent_values` | ins | not `height_from_other_date` | compute_timepoint |
| case-10 | bmi_path_b.bmi | sup `height_from_other_date`, `inconsistent_values` | ins | sup `height_from_other_date` | compute_timepoint |
| case-10 | bmi_path_c.bmi | sup `height_from_other_date`, `inconsistent_values` | ins | sup `height_from_other_date` | compute_timepoint |

The 17 rows that are wrong with the same status as published are in the table of the next section.

#### Wrong rows that remain (R2): first upstream error and expected-gap attribution

The six expected gaps are the six items under "Gaps these cases are expected to meet" above, numbered in that order. The same rule as on 2026-11-23: a row is listed under a gap only if the report's upstream error shows that gap; otherwise "none of the six" or "not attributed". The notes say what the run records hold; they do not change any count.

24 rows are wrong (16 conditions, 8 claims); published: 37 (20 conditions, 17 claims). First upstream error as the report gives it: compute_timepoint 5 · extraction_missed 4 · extraction_wrong_value 15. Attributed to one of the six expected gaps: **0**. "None of the six": 14. "Not attributed": 10. Published: 0 / 27 / 10.

| Case | Row | Gold | Published | Regression | First upstream error (regression) | Expected gap | Note |
|---|---|---|---|---|---|---|---|
| case-09 | bmi_path_a | con | ins | sup **(false support)** | extraction_missed | none of the six | G |
| case-09 | bmi_path_b | sup | ins | ins | extraction_missed | not attributed | C |
| case-09 | bmi_path_b.bmi | sup `inconsistent_values` | ins | sup | extraction_missed | none of the six | G |
| case-09 | bmi_path_b.ckd | sup | ins | ins | compute_timepoint | not attributed | C |
| case-09 | bmi_path_b.htn | rev `class_ambiguous`, `same_note_list` | ins | ins | extraction_wrong_value | not attributed | D |
| case-09 | bmi_path_c.bmi | sup `inconsistent_values` | ins | sup | extraction_missed | none of the six | G |
| case-09 | claim.bmi_bracket | rev | ins | sup **(false support)** | extraction_wrong_value | none of the six | G |
| case-09 | claim.bmi_path_b.ckd | sup | ins | ins | compute_timepoint | not attributed | C |
| case-10 | bmi_path_a | not `height_from_other_date`, `inconsistent_values` | ins | not `height_from_other_date` | compute_timepoint | none of the six | H |
| case-10 | bmi_path_b.bmi | sup `height_from_other_date`, `inconsistent_values` | ins | sup `height_from_other_date` | compute_timepoint | none of the six | H |
| case-10 | bmi_path_b.htn | not `same_note_list` | ins | ins | extraction_wrong_value | none of the six | I |
| case-10 | bmi_path_c.bmi | sup `height_from_other_date`, `inconsistent_values` | ins | sup `height_from_other_date` | compute_timepoint | none of the six | H |
| case-10 | claim.bmi_path_b.htn | con | rev | rev | extraction_wrong_value | none of the six | I |
| case-10 | claim.exclusion.mash | ins | – | – | extraction_wrong_value | none of the six | E |
| case-10 | claim.exclusion.t2dm | con | – | – | extraction_wrong_value | not attributed | E, F |
| case-12 | bmi_path_a | sup | ins | ins | extraction_wrong_value | none of the six | J |
| case-12 | bmi_path_b.bmi | sup | ins | ins | extraction_wrong_value | none of the six | J |
| case-12 | bmi_path_c.bmi | sup | ins | ins | extraction_wrong_value | none of the six | J |
| case-12 | claim.bmi_bracket | sup | ins | ins | extraction_wrong_value | none of the six | J |
| case-12 | claim.bmi_path_b.htn | rev | ins | ins | extraction_wrong_value | not attributed | K |
| case-18 | bmi_path_a | not | ins | ins | extraction_wrong_value | not attributed | B |
| case-18 | bmi_path_b.bmi | sup | ins | ins | extraction_wrong_value | not attributed | B |
| case-18 | bmi_path_c.bmi | sup | ins | ins | extraction_wrong_value | not attributed | B |
| case-18 | claim.bmi_bracket | sup | ins | ins | extraction_wrong_value | not attributed | B |

Notes (letters A to F are those of the 2026-11-23 record; A no longer applies to any row):

- **B.** Not attributed. The report charges these rows to extraction: the first error is `extraction_wrong_value`, and the three gold facts (baseline weight, height and BMI) differ on `relative_to_glp1_initiation` only. So the report does not show gap 1, and the rows are not listed under it. What the run records hold: the rows are now decided at the step where gap 1 acts (the initiation date is verified; the stored decision is "no weight or BMI at initiation"), and the stored evidence is consistent with gap 1: gold has the three values as `at` with no date, on the baseline wording; in the run they are located verbatim, pass the assertion check, are undated, have a computed timepoint of `unknown` and are excluded as `timing_unknown`. The extractor labelled the values `before`, not `at`.
- **C.** Unchanged from 2026-11-23. Report class `compute_timepoint` (`extraction_missed` for the parent row). Gold dates the diagnosis by a document date stated in the referral for the transcription; the extractor did not return that document-date fact, and the diagnosis row was also excluded by the verifier (`value_not_in_quote`). Not one of the six as far as the report shows.
- **D.** Gold flags `same_note_list` and `class_ambiguous` (the area of gaps 3 and 4). The stored decision is still "no blood pressure reading at initiation", now with a verified initiation date: the reading was excluded by the verifier (`assertion_mismatch`) and carries no date. The row stops before antihypertensives are counted. Neither gap was reached.
- **E.** Unchanged. The form's box was returned with `certainty: negated` where gold has `present`, and the verifier excluded it (`assertion_mismatch`); no claim decision was produced for the row.
- **F.** Unchanged. Expected gap 5 (the claim rule against a chart that documents type 2 diabetes in remission) is the rule for this row; because of E the rule did not run.
- **G.** The false supports and their two sibling rows; see the first paragraph of this section. First error `extraction_missed` (`extraction_wrong_value` for the claim): the document-date fact for the transcription was not returned, so its values are undated and excluded as `timing_unknown`, and only the referral's stated BMI was counted. Gold dates these values by the document date, not by baseline wording, so this is not gap 1; none of the six.
- **H.** Status now equals gold; the `inconsistent_values` flag is missing (`height_from_other_date` is present). Report class `compute_timepoint`: the BMI stated in the visit note was returned with the right date and labelled `at`, but its date was not bound and its computed timepoint is `unknown` (the gold fact differs on timing only), so it was excluded and only the computed BMI was counted. Gold dates the value explicitly, so this is not gap 1; none of the six.
- **I.** The row now reaches the antihypertensive count: a reading at initiation above the threshold is found, and 0 antihypertensives are counted as certainly in use. The note's medication is in the drug table (not gap 3) and its list was read as a current list (not the unknown heading of gap 4), but the list fact was excluded by the verifier (`value_not_in_quote`), which leaves the medication's period unknown. First error `extraction_wrong_value`. None of the six. The claim row follows the condition.
- **J.** Stored decision "no weight or BMI at initiation" ("no BMI at initiation" for the claim), with a verified initiation date. The transcription's weight and height were excluded by the verifier (`value_not_in_quote`, `unparseable_value`) and differ from gold on value and date. Gold dates them by the document date. None of the six.
- **K.** Unchanged status and class. The stored decision is "chart holds nothing related"; the hypertension diagnosis was excluded by the verifier (`assertion_mismatch`).

**Gaps 1, 3 and 4, which were not reached on 2026-11-23:**

- **Gap 1:** the run now reaches the step where gap 1 acts; the report does not attribute the rows to it. Case-18, four rows (`bmi_path_a`, `bmi_path_b.bmi`, `bmi_path_c.bmi`, `claim.bmi_bracket`), note B.
- **Gap 3: not reached.** Case-09 `bmi_path_b.htn`, whose gold carries `class_ambiguous`, still stops at the blood pressure reading, before any drug is counted (note D). In case-10 the count ran, and the medication there is in the table. No remaining wrong row's error shows a drug outside the table.
- **Gap 4: not reached.** Same row, same stop (note D). The stored evidence of case-09 does hold the transcription's medication list with status `unknown`, which is the condition gap 4 describes, but no decision used it. In case-10 the same-note step ran and failed for another reason (note I).

#### What got worse (R2)

- False supports: conditions 0 → 1, claims 0 → 1 (case-09, first paragraph of this section). The target is 0. This is the one way R2 is worse than the published run, and it is the most serious kind of error the report counts.
- No row went from right to wrong.
- Human workload went 33 → 27; with a false support among the rows no longer sent to a human, that drop is not simply an improvement.
- The other differences between the two columns: conditions 60/80 → 64/80, claims 9/26 → 18/26, correctly automated 3/11 → 7/11, gold facts matched 37 → 46 of 106, wrong rows 37 → 24.

### R1: cases 11, 14, 16 (one live pass, three calls)

Live pass 23:29 to 23:30 UTC, fresh database. Prices: $2.00 per million input tokens, $10.00 per million output tokens. Ceilings: $1.00 per run, $5.00 per evaluation.

| Case | Input tokens | Output tokens | Latency | Cost | Attempts | Outcome |
|---|---|---|---|---|---|---|
| case-14 | 14,594 | 4,689 | 24.9 s | $0.0761 | 1 | parsed, run completed |
| case-16 | 13,711 | 4,208 | 19.5 s | $0.0695 | 1 | parsed, run completed |
| case-11 | 13,967 | 4,593 | 22.5 s | $0.0739 | 1 | parsed, run completed |
| **Live pass** | 42,272 | 13,490 | | **$0.2194** | 3 | 3 completed, 0 failed |

All three responses parsed on the first attempt; no retry, no second pass, no rerun. Cost $0.219444, inside the expected 0.2 to 0.3 USD and under both ceilings.

#### Totals (R1): published and regression side by side, never summed

| Measure | Published 2026-11-10 (live, `3951736`, `extract-v4`) | R1 regression (live, `3b8f0fc`, `extract-v5`) |
|---|---|---|
| Conditions correct (status and flags) | 27/60 | 47/60 |
| Claims correct (status) | 4/19 | 10/19 |
| False supports, conditions (target 0) | 0 of 51 gold non-supported rows; system supported 2 | 0 of 51 gold non-supported rows; system supported 2 |
| False supports, claims | 0 of 10 gold non-supported rows; system supported 2 | 0 of 10 gold non-supported rows; system supported 5 |
| Missed exclusion evidence (gold `review` exclusion rows) | 3 of 3 | 0 of 3 |
| Human workload (top-level `review` + `conflict` + `insufficient`) | 16 | 23 |
| Packets with at least one human item | 3/3 | 3/3 |
| Correctly automated among gold-automatable | 2/7 | 4/7 |
| Gold facts matched / wrong value / missed | 11 / 15 / 31 of 64 (7 more matched but excluded by the verifier; 0 of the wrong values differ on timing only) | 26 / 24 / 2 of 64 (12 more matched but excluded by the verifier; 1 of the wrong values differ on timing only) |
| Quotes located | 37/37 | 82/82 |
| Runs failed | 1 | 0 |
| First upstream error of the wrong rows | extraction_missed 9 · extraction_wrong_value 12 · run_failed 27 | compute_timepoint 1 · extraction_extra 1 · extraction_missed 4 · extraction_wrong_value 12 · verify_excluded 4 |
| Cost (USD) | $0.180228 (3 calls, pass 1) | $0.219444 (3 calls) |

| Case | Conditions, published | Conditions, regression | Claims, published | Claims, regression |
|---|---|---|---|---|
| case-11 | 0/20 (run failed) | 19/20 | 0/7 (run failed) | 4/7 |
| case-14 | 13/20 | 13/20 | 2/6 | 3/6 |
| case-16 | 14/20 | 15/20 | 2/6 | 3/6 |

The published run of case-11 failed at parsing, so all of its 27 rows are wrong by rule in the published column; in R1 the response parsed and the run completed.

#### False supports (R1)

None. No row has the system at `supported` where gold is not `supported`.

#### Rows that changed (R1)

| Change | All rows | Conditions | Claims |
|---|---|---|---|
| wrong → right | 26 | 20 | 6 |
| right → wrong | 0 | 0 | 0 |
| wrong → still wrong | 22 | 13 | 9 |
| – of which (different wrong status) | 1 | 1 | 0 |
| – of which (published run failed) | 4 | 1 | 3 |
| – of which (same status) | 17 | 11 | 6 |
| right → right | 31 | 27 | 4 |

Wrong → right (26): 23 rows of case-11, whose published rows are wrong by rule because the run failed (the table says "run failed" instead of comparing statuses), and 3 rows of cases 14 and 16.

| Case | Row | Gold | Published | Regression | First upstream error (regression) |
|---|---|---|---|---|---|
| case-11 | age_18 | not | run failed | not |  |
| case-11 | bmi_path_a | ins | run failed | ins |  |
| case-11 | bmi_path_b | ins | run failed | ins |  |
| case-11 | bmi_path_b.bmi | ins | run failed | ins |  |
| case-11 | bmi_path_b.ckd | ins | run failed | ins |  |
| case-11 | bmi_path_b.hfpef | ins | run failed | ins |  |
| case-11 | bmi_path_b.htn | ins | run failed | ins |  |
| case-11 | bmi_path_c | ins | run failed | ins |  |
| case-11 | bmi_path_c.bmi | ins | run failed | ins |  |
| case-11 | bmi_path_c.mi | ins | run failed | ins |  |
| case-11 | bmi_path_c.pad | ins | run failed | ins |  |
| case-11 | bmi_path_c.stroke | ins | run failed | ins |  |
| case-11 | exclusion.mash | ins | run failed | ins |  |
| case-11 | exclusion.osa | rev | run failed | rev |  |
| case-11 | exclusion.part_d_glp1 | not | run failed | not |  |
| case-11 | exclusion.t2dm | ins | run failed | ins |  |
| case-11 | lifestyle.activity | ins | run failed | ins |  |
| case-11 | lifestyle.nutrition | ins | run failed | ins |  |
| case-11 | patient_identity | rev `id_missing` | run failed | rev `id_missing` |  |
| case-11 | claim.age_18 | con | run failed | con |  |
| case-11 | claim.bmi_bracket | ins | run failed | ins |  |
| case-11 | claim.drug | sup | run failed | sup |  |
| case-11 | claim.exclusion.t2dm | ins | run failed | ins |  |
| case-14 | claim.drug | sup | ins | sup |  |
| case-16 | exclusion.osa | rev | ins | rev |  |
| case-16 | claim.drug | sup | ins | sup |  |

Right → wrong: none.

Wrong → still wrong (22): 4 rows of case-11 (published run failed), 17 with the same status as published, 1 with a different wrong status (case-14 `exclusion.mash`: the status now equals gold, with an `unrecognized` flag gold does not carry).

| Case | Row | Gold | Published | Regression | First upstream error (regression) |
|---|---|---|---|---|---|
| case-11 | bmi_path_c.prediabetes | sup | run failed | ins | verify_excluded |
| case-11 | claim.bmi_path_b.htn | rev | run failed | ins | extraction_extra |
| case-11 | claim.bmi_path_c.prediabetes | sup | run failed | ins | verify_excluded |
| case-11 | claim.exclusion.osa | rev | run failed | – | verify_excluded |
| case-14 | bmi_path_a | sup | ins | ins | extraction_missed |
| case-14 | bmi_path_b.bmi | sup | ins | ins | extraction_missed |
| case-14 | bmi_path_c | rev | ins | ins | extraction_missed |
| case-14 | bmi_path_c.bmi | sup | ins | ins | extraction_missed |
| case-14 | bmi_path_c.prediabetes | rev `table_source` | ins | ins | extraction_wrong_value |
| case-14 | exclusion.mash | rev | ins | rev `unrecognized` | compute_timepoint |
| case-14 | exclusion.t2dm | not | ins | ins | extraction_wrong_value |
| case-14 | claim.bmi_bracket | sup | ins | ins | extraction_wrong_value |
| case-14 | claim.exclusion.mash | con | – | – | verify_excluded |
| case-14 | claim.exclusion.t2dm | sup | ins | ins | extraction_wrong_value |
| case-16 | bmi_path_a | sup | ins | ins | extraction_wrong_value |
| case-16 | bmi_path_b.bmi | sup | ins | ins | extraction_wrong_value |
| case-16 | bmi_path_c | rev | ins | ins | extraction_wrong_value |
| case-16 | bmi_path_c.bmi | sup | ins | ins | extraction_wrong_value |
| case-16 | bmi_path_c.prediabetes | rev `table_source` | ins | ins | extraction_wrong_value |
| case-16 | claim.bmi_bracket | sup | ins | ins | extraction_wrong_value |
| case-16 | claim.bmi_path_c.prediabetes | rev | ins | ins | extraction_wrong_value |
| case-16 | claim.exclusion.osa | rev | – | – | extraction_wrong_value |

No expected-gap attribution is made for R1: the six gaps were written down for the second batch.

#### What got worse (R1)

- No row went from right to wrong, and there is no false support.
- Human workload 16 → 23. The published 16 counts two completed runs only (case-11 produced no decisions), so the two numbers are not like for like.
- The other differences between the two columns: conditions 27/60 → 47/60, claims 4/19 → 10/19, missed exclusion evidence 3 of 3 → 0 of 3, runs failed 1 → 0. Most of the row gain is case-11 completing (23 of the 26 rows); on cases 14 and 16 three rows changed to right and 18 stay wrong.

### After these runs

Added 2026-11-23. After these runs, and using the failure R2 reported (verified values of one document carried no date, were excluded as `timing_unknown`, and the BMI rows were decided from the other document's value alone), one rule was added (contract §3.1 step 9). A BMI sub-result that would be `supported` or `not_supported` becomes `review` with the flag `undated_counterevidence` when a verified value of unknown timing lies on the other side of that threshold from the value at initiation; `claim.bmi_bracket` becomes `review` when such a value lies in another bracket. The rule was written from the description of the failure and tested on values and documents invented for the tests. No holdout case was run for it, and no replay with the rule is reported here: the tables above are those of the runs before the rule, and nothing above this subsection was changed.
