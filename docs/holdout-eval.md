# Holdout evaluation: one run on cases 11, 14 and 16

Date: 2026-11-10 (live pass 08:45 to 08:46 UTC). Extractor `claude-sonnet-5-5` (model returned `claude-sonnet-5-5`), prompt `extract-v4`, schema `v2`, rules `bridge-v1`, drugs `drugs-v2`, verify terms as on main, splitter `sentences-v1`. Public code `395173651c75a560286bab6abd1d030120ed41aa` (the commit that wired `--split holdout` on top of main `f82c1463d595658c1a956ec936bd841abd75812d`, with no prompt, schema, rule or gold change). Private data at its main `1e92867`, gold version 1 for all three variants, frozen hashes re-verified before the run.

**One run of one model on three holdout variants. Single annotator, one run, one model; counts, not rates. Not a validation on real records.** Design-time known scenarios; the configuration was not adjusted on these inputs' results. The three variants were frozen (hash-only rows in `splits.yaml`) before the pipeline first ran on them.

No document text, quote or patient name appears here. Evidence is cited as `doc_id[start:end] sha8` in the report files only. The report files are `reports/eval-holdout.json` and `reports/eval-holdout.md` (the live pass); the private repository holds the raw responses, the redacted requests, the attempt rows, both passes' reports, the per-case gold comparisons and the run database.

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

Added 2026-11-23. After this run, and using the failure classes reported above (`run_failed` on one badly shaped date, `extraction_wrong_value` on the dates and timepoints of baseline values, `extraction_missed` and the missed exclusion evidence), three things were changed: the retry budget (one more parse-class attempt per run, contract §11), the extraction prompt (`extract-v5`) and the binding of a date to its value in the verifier (contract §6). Cases 11, 14 and 16 are therefore no longer untouched test cases for any later configuration: a later result on them is a result on cases that informed the configuration. Nothing above this section was changed, and none of the three cases was run again for these changes.

## Second holdout batch: frozen 2026-11-23, not yet run

Four more holdout cases were frozen on 2026-11-23 under guide version 3, after the changes merged that day and before any pipeline run on them: cases 09, 10, 12 and 18. They are hash-only rows in `splits.yaml`. The batch will be run once; this section will then be followed by its results. Nothing in this section is a result.

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
