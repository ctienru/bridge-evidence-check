# Machine contract

> Fourth edition, 2026-11-23. **Program-level names and rules are defined by this page**: condition IDs, status codes, decisions and aggregation, conflicts, initiation timepoint, enums, input and extraction schema, data flow, gold format and matching, thresholds, execution and CI. The reasons behind the project policies are not written up in this repository yet; this page only writes the policies in the form the program uses. When another document and this page disagree, this page wins and the other document is corrected.

## 1. Status codes, run status, exit codes

| Machine code | Display | When to use |
|---|---|---|
| `supported` | Supported | Evidence with a verbatim or normalized hit, and patient, assertion and timepoint all match |
| `not_supported` | Explicitly not supported | Positive counter-evidence or evidence of absence (denies diabetes, an explicitly complete single-drug list, BMI 26) |
| `insufficient` | Insufficient data | Not mentioned, or only data that cannot support a conclusion |
| `conflict` | Conflict | Contradictory values for the same fact that would change the result (§4) |
| `review` | Needs human review | Evidence exists, but a human must judge (exclusion evidence, policy grey zone, unclear precision) |

- DB, YAML, JSON and CLI always use the machine codes; display strings appear only in reports and `--explain`. **There is no sixth status.**
- When aggregating, the "how much a human needs to look" order is: `conflict` > `review` > `insufficient`. `supported` and `not_supported` are conclusions and are not in this ordering.

**Run status** `case_runs.status` ∈ `running` / `completed` / `failed` (`partial` is reserved, not used in P1); on failure add `failed_stage` ∈ `input` / `extract` / `parse` / `verify` / `compute` / `rules` / `store` / `interrupted`.

- `completed`: all processing completed; it does not mean any condition is supported. Missing data in a document, or a value that cannot be parsed (evidence excluded with `unparseable_value`), are data problems and still `completed`.
- **P1: an unexpected program exception in verify / compute → the whole run is `failed`, no decisions are published.** Skipping the failing item could drop exactly the negation, wrong-patient or date evidence, and the remaining data would become a false support. If `partial` is really needed later, error propagation ("which conditions depend on this evidence") has to come first.
- Leftover `running`: only **after acquiring the run lock** (§11) is every `running` row in the database, of any case, changed to `failed` + `interrupted`. The lock is one per database, so holding it means no other run is in flight and a leftover `running` can only be a real crash.
- `case_runs.stopped_after` ∈ `extract` / `verify`: set when a run is stopped at that stage boundary (the test-only `--stop-after` option). It may be non-NULL only when the status is `completed`.
- Store schema version: `PRAGMA user_version` holds `SCHEMA_VERSION` (currently 2). A database that carries another version is refused before anything is written to it; there are no migrations.
- Rules writing decisions and changing `case_runs.status` to `completed` happen in **one transaction**; there is no intermediate state "decisions written, status not updated".

**CLI** (entry point `bridge`): `check <case> [--explain] [--json]`, `eval --split dev|holdout [--data-root <path>] [--ladder <case>]`, `excerpts`, `history <case>`.

| Command | Exit code |
|---|---|
| `check` | 0 = `completed`; 3 = `failed`; 4 = another run holds the lock. **The exit code only expresses execution**; "how many top-level rows need a human" goes in the report and `--json` |
| `eval` | 0 = no regression; 1 = regression (§11); 3 = execution failure; 4 = lock |

## 2. Condition and sub-result IDs

| ID | Display | Kind (`decisions.kind`) | Top level |
|---|---|---|---|
| `age_18` | Age 18 or older (at initiation) | `condition` | ✔ |
| `bmi_path_a` | Pathway A: BMI ≥ 35 | `path` | ✔ |
| `bmi_path_b` | Pathway B | `path` | ✔ |
| `bmi_path_b.bmi`, `.hfpef`, `.htn`, `.ckd` | B's BMI ≥ 30, HFpEF, uncontrolled hypertension, CKD 3a+ | `sub` | |
| `bmi_path_c` | Pathway C | `path` | ✔ |
| `bmi_path_c.bmi`, `.prediabetes`, `.mi`, `.stroke`, `.pad` | C's BMI ≥ 27, prediabetes, prior MI, prior stroke, symptomatic PAD | `sub` | |
| `exclusion.t2dm`, `.osa`, `.mash`, `.part_d_glp1` | Exclusions: T2DM, moderate-to-severe OSA, non-cirrhotic MASH F2–F3, GLP-1 received under Part D in 2026 | `exclusion` | ✔ |
| `patient_identity` | Patient identity consistent | `condition` | ✔ |
| `lifestyle.nutrition`, `.activity` | Nutrition program, physical activity | `lifestyle` | (reported separately) |
| `claim.<id>` | PA draft claim check | `claim` | (reported separately) |

- Everything is scored. Pathway A has no sub-results. No single "overall eligible" decision is output.
- When a pathway is already established, the other sub-results are still decided and scored as usual; they just do not affect the pathway (this is what `required_for_pathway: false` meant in older documents).
- **Case-level flag** `mace_purpose` is stored in `case_runs.case_flags` and in gold `case_flags`; it is not a status.
- **Claims**: one ID per checkbox field on the PA form, named after what it is checked against (`claim.age_18`, `claim.drug`, `claim.bmi_bracket`, `claim.bmi_path_b.hfpef`, `claim.exclusion.t2dm`, …). P1 only builds the ones used by cases 01 and 15; the full list is added batch by batch. Status: chart supports → `supported`; not mentioned → `insufficient`; contradicted → `conflict`; chart mentions it but as suspected (HFpEF ticked, chart says r/o HFpEF) → `review`. A claim is decided on its own question, so its status may differ from the sub-result's. When the sub-result is `insufficient` but the chart holds material related to the claim that cannot answer it, the claim is `review`: a written diagnosis of the patient that the claim builds on while the claim's further requirements are not shown (uncontrolled hypertension ticked, the chart names hypertension and has no reading at initiation), or a lab inside the range that defines the claimed diagnosis with no diagnosis statement. With nothing related the claim is `insufficient`; a lab outside that range is not related material, and a source or format flag on the sub-result (`table_source`, `unrecognized`, `imprecise_source`) does not by itself make the claim `review` (guide K-03). Claims never change a condition's status.
- **Rule functions**: `rules.py` uses an explicit registry `RULES: dict[str, RuleFn]`, keyed by the IDs in the table above (no function-name conversion).

## 3. Decision rules

Every table is **evaluated top to bottom; the first matching row is the result**. Step 0 is the same for all tables: first filter out evidence whose `exclusion_reasons` is non-empty (wrong patient, PA draft, value not in quote, …).

### 3.1 BMI sub-result: `decide_bmi(cands, threshold, policy) -> Decision`

1. Height: take the nearest record from any timepoint (adult height is treated as stable; add `height_from_other_date`); weight and stated BMI are taken only from `at` (§5).
2. No `at` weight or BMI: only `before` → `review`; otherwise `insufficient`.
3. Compute candidate values: height and weight present → computed value; stated BMI values are also candidates.
4. Candidate values fall on **both sides of this threshold** (regardless of the gap; 29.9 vs 30.1 counts) → `conflict`, stop.
5. Candidate values differ by more than the tolerance (§4) but on the same side → continue, add `inconsistent_values`. `bmi_raw` uses the computed value (the stated value only when there is no height and weight).
6. Only an integer BMI, **and** no height and weight, **and** ⌊x⌋ ≤ threshold < x+0.5 → `review` + `imprecise_source`.
7. `bmi_raw ≥ threshold` → `supported`; otherwise `not_supported`.
8. Result is `supported` but the evidence used carries `table_source` / `timing_disagreement` / `unrecognized` → change to `review`.

### 3.2 Comorbidity sub-results

**`bmi_path_b.htn`**:

1. No `at` BP at all → `insufficient`.
2. No reading with `sbp > 140 or dbp > 90` → `insufficient` (exactly 140 or 90 adds `boundary_value`). **Readings first, then drugs.**
3. There is an above-threshold reading; look up `distinct_antihypertensives_overlapping(date)` for that day (deduplicated by `drug_canonical`; `class` is only used to recognize whether a drug is an antihypertensive):
   - ≥ 2 drugs from different products → `supported`
   - ≥ 2 drugs but all from one combination pill → `review` + `combination_pill`
   - 2 drugs reached only by counting a `class_ambiguous` drug → `review` + `class_ambiguous`
4. < 2 drugs and the list has `complete=true` → `not_supported` (`htn_not_supported_by_complete_list`).
5. Everything else (period unknown, list incomplete) → `insufficient`.

**Several readings above the threshold**: each such reading is judged on its own day by rows 3–5. The sub-result is `supported` if any reading is `supported`; otherwise `review` if any reading gives a `review` outcome (`combination_pill`, `class_ambiguous`); otherwise `insufficient` if any reading cannot be judged; `not_supported` only when every reading above the threshold is refuted by a complete medication list. `insufficient` outranks `not_supported`.

Tests: `test_htn_boundary_reading_with_ambiguous_diuretics_is_insufficient` (case 15), `test_htn_combination_pill_alone_is_review` (case 04 before the added drug).

**`bmi_path_c.prediabetes`**:

1. The patient has a prediabetes diagnosis (present / historical) → `supported`.
2. The diagnosis is uncertain → `review`.
3. No diagnosis, A1c 5.7–6.4% or fasting glucose 100–125 mg/dL, with or without a denial → `review` (`a1c_prediabetes_range_without_dx`).
4. No diagnosis, A1c ≥ 6.5% or fasting glucose ≥ 126, with or without a denial → this item `insufficient`; `exclusion.t2dm` is decided per §3.3 as `review` (`lab_in_diabetes_range_without_dx: review`).
5. Explicit negation of prediabetes → `not_supported`.
6. Everything else (including A1c below the range, no diagnosis) → `insufficient`. Below the range is not positive counter-evidence.

**Denial together with a lab in range** (this table and `exclusion.t2dm` in §3.3): "No diagnosis" includes an explicit denial. A lab in range outranks a denial. `exclusion.t2dm`: a denial of type 2 diabetes together with an A1c of 6.5% or more, or a fasting glucose of 126 mg/dL or more → `review`. `bmi_path_c.prediabetes`: a denial of prediabetes together with an A1c of 5.7–6.4% or a fasting glucose of 100–125 mg/dL → `review`; a denial together with a diabetes-range lab → `insufficient` for this sub-result, and `exclusion.t2dm` is `review`. Example: a note that reads "denies prediabetes" and reports an A1c of 6.1% on the same visit gives `review`, not `not_supported`.

**`bmi_path_b.hfpef`**: HFpEF diagnosis present / historical → `supported`; uncertain (r/o) → `review`; explicit negation → `not_supported`; only a test finding such as diastolic dysfunction, no diagnosis → `insufficient`; everything else → `insufficient`.

**`bmi_path_b.ckd`**: CKD diagnosis with stage ≥ 3a → `supported`; CKD diagnosis with no stage written → `review`, whether or not an eGFR is recorded (all eGFR values are listed; `ckd_dx_egfr_only`); explicit stage 1–2 → `not_supported`; only eGFR, no diagnosis → `insufficient`.

**`bmi_path_c.mi`, `.stroke`**: the patient's own present / historical diagnosis → `supported`; a denial together with imaging or history evidence → `conflict` (§4); an uncertain mention → `review`; explicit denial → `not_supported`; TIA, demand ischemia, appearing only in a surgical-risk discussion (`hypothetical`), only troponin → `insufficient`.

**`bmi_path_c.pad`**: PAD diagnosis with `symptomatic=true` (claudication etc.) → `supported`; PAD diagnosis but symptoms unclear → `review`; PAD explicitly asymptomatic → `not_supported`; with several timepoints take the one closest to the initiation date (E04).

### 3.3 Exclusion sub-results (decided individually, not aggregated)

1. A positive diagnosis and an explicit negation at the same timepoint → `conflict`.
2. Special staging: MASH explicitly F0–F1 or cirrhosis (F4), OSA explicitly mild (mild or AHI < 15) → `not_supported` (not this exclusion).
3. Appears only after initiation → `review` + `post_initiation_exclusion` (evidence from before and after is kept; the pathways' "not used after initiation" rule does not apply).
4. The patient has positive or suspected evidence (present, historical, resolved, uncertain; OSA severity unknown, post-surgical status unknown) → `review`. `exclusion.osa` and `exclusion.mash`: a hypothetical mention with certainty `present` counts as positive evidence and returns `review`; an exclusion errs toward a human look. `exclusion.t2dm` only: an A1c ≥ 6.5% or a fasting glucose ≥ 126 mg/dL without a diagnosis, with or without a denial → `review` (§3.2, denial together with a lab in range).
5. Explicit negation, and for `exclusion.t2dm` no lab in the diabetes range → `not_supported`.
6. Not mentioned → `insufficient`.

**`exclusion.part_d_glp1`**: the document says it was paid by Part D in 2026, or names a Part D fill with no date → `review`; a Part D fill in 2025 or earlier, Medicaid, self-pay, or explicitly Bridge → `not_supported`; not mentioned, payer unknown (only an amount, or compounded without a payer), or a `commercial` payer → `insufficient`.

- Exclusion sub-results are never `supported`; `max_status: review` in the rules table means "positive exclusion evidence returns `review`".
- The Part D `not_supported` is a **deliberate exception**: 2025, Medicaid and self-pay are not positive evidence of "none received in 2026"; they only mean "the instance the document mentions does not trigger". It is kept so that false triggers stay visible; the report notes this.
- The Part D sub-result is always scored; "not found does not mean none; 2026 Part D is checked by CMS against claims" is a fixed footnote in the report and is not scored.

### 3.4 Pathway aggregation

**Pathways B and C**:

1. All comorbidity sub-results are `not_supported` → `not_supported`.
2. The BMI sub-result is `not_supported` → `not_supported`.
3. The BMI sub-result is `insufficient` / `conflict` / `review` → the pathway equals the BMI sub-result.
4. The BMI sub-result is `supported`: any comorbidity `supported` → `supported`; otherwise take the highest-ranked comorbidity (`conflict` > `review` > `insufficient`).

**Pathway A** equals the BMI ≥ 35 decision.

**Downgrade** (applied last; only turns `supported` into `review`): `mace_purpose` present → `supported` on all three pathways becomes `review`; pathway C established only through `mi` / `stroke` / `pad` (no `prediabetes`) → the pathway becomes `review` + `cv_history_only`, the sub-results stay `supported`.

**No GLP-1 initiation date**: the BMI sub-result is `insufficient`; aggregation proceeds as above (when all comorbidities are `not_supported` the pathway is still `not_supported`).

**Worked checks** (parametrized tests in `test_rules.py`):

| Situation | BMI sub-result | Comorbidities | Pathway |
|---|---|---|---|
| 07 pathway B | insufficient | hfpef insufficient, htn not_supported, ckd insufficient | insufficient |
| 15 pathway B | insufficient | hfpef supported, htn insufficient, ckd review | insufficient |
| 13 pathway C | supported | prediabetes supported | supported |
| 05 pathway C | supported | stroke, pad supported | review (`cv_history_only`) |
| 17 pathway C | insufficient | mi supported | insufficient |
| E11 | not_supported (26) | — | all three not_supported |
| hypothetical | supported | one review, two insufficient | review |
| hypothetical | review | all not_supported | not_supported |

### 3.5 Age, identity, lifestyle

**Age** `age_18`: a stated age `a` (document date `d`) means the age on that day is in `[a, a+1)`; shift it to the initiation date `s` to get the age interval at initiation. With a date of birth, compute the exact value directly.

- Whole interval ≥ 18 → `supported`; whole interval < 18 → `not_supported`; interval straddles 18 → `review`.
- With an initiation date, one verified interval wholly below 18 and another wholly at or above 18 → `conflict` (§4, threshold first), with both intervals in `used_evidence`; the rules above, including `review` for a straddling interval and `inconsistent_values`, apply only when no such pair exists. Test: `test_age_conflict_when_verified_intervals_fall_on_opposite_sides`.
- Neither date of birth nor age → `insufficient`.
- No verified initiation date: initiation is not later than `assessment_date`, so only an upper bound on the age at initiation is known. Convert the date of birth or the stated age to `assessment_date`. If the whole interval is below 18 → `not_supported`. Otherwise → `insufficient`. `age_18` is never `supported` without a verified initiation date. A stated age with no document date → `insufficient`.
- Examples: age 85 written three years after initiation → ≥ 81 at initiation → `supported`; age 19 written three years after initiation (day-precision document date) → 16 at initiation → `not_supported`; the same sentence with a year-precision document date → the interval straddles 18 → `review`; age 13 written ten years before initiation → about 23 at initiation → `supported`.
- Test: `test_age_stated_after_initiation_uses_interval`.

**Identity** `patient_identity` (the primary patient identifier comes from the input, §7.1): **compare IDs only; compare date of birth only when the document has no ID; never compare names**.

- Only an affirmed identifier counts: the cues read it as the patient's own (`subject: patient`), `certainty: present`, and not `hypothetical`. An uncertain, family or hypothetical identifier neither matches nor triggers `wrong_patient`; a negated identifier never matches.
- Only identifiers of the same type are compared. A label decides the type; the primary patient's type follows from the shape of its identifier. The date of birth decides only when no identifier of the same type was compared.
- A labelled identifier is read in full from the document text at every located occurrence, so a quote that clips it is still screened on the whole identifier. A labelled identifier that cannot be parsed never matches: the document is `missing` and its identity evidence carries `id_missing`.

1. A document's ID differs from the primary patient (or no comparable ID and the date of birth differs) → `conflict`; all located evidence from that document is excluded (`wrong_patient`).
2. No document has any comparable identifier → `insufficient`.
3. Some documents have neither a comparable ID nor a date of birth and the rest are consistent → `review` + `id_missing`; the evidence of those documents is still usable.
4. Every document is consistent → `supported`.

**Lifestyle** `lifestyle.*`: A lifestyle record applies only if a verified date or period places it on `assessment_date`: its end is on or after that day, or the record is dated on that day, or its date is before that day and `end_kind` is `ongoing`. A record dated before that day with `end_kind: unknown`, and any record with `end_kind: ended`, does not apply. When no record applies → `insufficient`. A program that starts later, and an undated record, do not apply.

1. Several applicable records → the one closest to `assessment_date` decides; the rows below read that record.
2. The document explicitly states there is no diet plan at all (or no activity at all) → `not_supported`.
3. Only advice, a referral not yet attended, "will consider", or declined → `insufficient`.
4. A commercial program (Weight Watchers, Noom), irregular attendance, or activity with a medical limitation or exception → `review`.
5. Otherwise, a structured nutrition or activity program that applies on `assessment_date` → `supported`.

**Human workload**: per case, the number of top-level rows that are `review` + `conflict` + `insufficient`; sub-results are not double-counted; lifestyle and claims are reported separately.

## 4. Conflicts and tolerances

**Same fact**: same patient, same kind of measurement or same diagnosis concept, same timepoint (both `at`; or overlapping `event_date` intervals; or both undated, describing the same visit in the same document). `at` and `after` do not conflict.

**Tolerances** (within tolerance and not crossing a threshold is treated as the same value): BMI ±0.2; weight 1% relative; height ±1 cm; BP has no tolerance; age derived from date of birth vs stated age within 1 year; labs have no tolerance.

- **Threshold first, then tolerance**: two values on either side of a threshold → the sub-results that use that threshold are `conflict`, whether or not they are within tolerance. BMI thresholds 27, 30 and 35 are each judged separately (34.6 vs 36 → only `bmi_path_a` conflicts).
- Same side, beyond tolerance → decide as usual, add `inconsistent_values`. Age 58 vs 55 → `age_18` `supported` + `inconsistent_values`; but a contradiction in date of birth or ID is handled by the identity table and does not disappear because the ages are on the same side.
- **Labs**: Labs follow the BMI rule: thresholds first. Two values of the same lab kind at the same timepoint that fall on opposite sides of a threshold (A1c 5.7 and 6.5; fasting glucose 100 and 126) → `conflict` for the sub-result that uses that threshold. Two different values on the same side → decide as usual and add `inconsistent_values`. `bmi_path_b.ckd` decides from the diagnosis and its stage; differing eGFR values at the same timepoint add `inconsistent_values`. When a diagnosis decides a sub-result, its lab values are not compared with the thresholds. Labs have no tolerance; values are compared as `Decimal`.
- A `conflict` cannot be rescued by another piece of evidence.
- **Diagnoses**: same concept, overlapping timepoints, one present / historical and one negated → `conflict` (E15). Different timepoints: for "prior" questions (MI, stroke) any valid present / historical record counts; for "current" questions (symptomatic PAD, OSA severity) take the one closest to the initiation date.

## 5. Initiation timepoint and dates

**The course under assessment**: `target_course` in `input.yaml` (drug + start date) specifies which initiation is assessed; the start date must still be found in the documents and pass quote verification, otherwise there is no initiation date. Resuming after a pause is not a new initiation; if the documents do not show which course it is → the affected BMI sub-results are `review`.

**The course's drug**: a `glp1_start` row names the course when its drug resolves to the same ingredient as `target_course.drug` (`glp1_canonical`; the same resolver gives `drug_canonical` for `prior_glp1` and for gold matching in §8). A bare name resolves when it is one of the ingredients `semaglutide`, `tirzepatide`, `liraglutide` or one of their listed brands, ignoring case and whitespace. A name of the form `outer (inner)` resolves only when one part is a listed brand and the other part is exactly that brand's ingredient, in either order ("Wegovy (semaglutide)", "semaglutide (Wegovy)"). Every other name with a parenthesis stays unresolved and names no course: a brand with another ingredient, two brands, two ingredients, a brand or an ingredient next to a dose, a route, a formulation word or any other word (so a drug outside the list next to an ingredient never resolves), words after the parenthetical, more than one parenthetical, an unbalanced parenthesis, an empty part. There is no fuzzy or prefix match. For `claim.drug`, a start written as a brand with its ingredient names that brand.

`relative_to_glp1_initiation` ∈ `at` / `before` / `after` / `unknown`, **present on every kind of fact**; the DB stores two columns: `relative_llm` (filled by the LLM) and `relative_computed` (computed by the program; scoring uses this column).

1. Both the fact's `event_date` and the initiation date exist → the program compares **date intervals**: the identical single day → `at`; entirely before or after → `before` / `after`; overlapping but undecidable (for example the same month at month precision) → `unknown`. The LLM's `unknown` means "not stated" and is not a claim; `timing_disagreement` is raised only when the LLM's `at` / `before` / `after` contradicts `relative_computed`. Scoring and every decision use `relative_computed`.
2. No date → only a quote that explicitly states a baseline at initiation (at initiation, baseline, before starting tirzepatide) is `at`; otherwise `unknown`.
3. The main MTSamples document has no date: `doc_dates[]` records "the date of document D2 is X, source is this sentence in D1". **`doc_dates[]` must also pass quote verification**; if it fails → D2's facts have timepoint `unknown`. `evidence.event_date_source` ∈ `llm` / `doc_dates:<evidence_id>` / `none`; a BMI `at` can only attach to verified date evidence, and `used_evidence` lists both the BMI sentence and the date sentence. The verifier records what the quote itself says in `evidence.attributes.quote_date` (`{"date", "precision"}`, the date bound to the fact's mention at the text's precision; absent when the quote names no date) and sets `event_date_source` to `llm` (the model's `event_date` equals a date bound in the quote), `none` (the model gave a date but the quote has none bound) or NULL (not checked: quote not found, or no `event_date` given); compute writes `doc_dates:<evidence_id>` only onto a fact whose quote carries no date. The two cases of guide T-05 are fixed: a measurement whose quote carries its own date ("measured 2025-03-16") never inherits the document date; one whose quote has no date ("today") inherits the document's verified date. A fact whose mention carries a relative time expression ("last year", "two months before the visit") and no date of its own does not inherit the document date: its `event_date` is null and its timepoint is `unknown` (guide T-05). This applies to point-in-time facts. In a `medications` or `lifestyle` entry a relative time expression states when the period began; the entry is still placed by the verified document date. A `doc_dates` fact whose quote names no document, or whose role word fits two documents, is `unrecognized` and dates no document.

**Dated event facts and the temporality axis**: `glp1_start`, `prior_glp1` and `doc_dates` are dated events. For these three fields anchoring the initiation date, anchoring a document date, passing a prior fill to the rules (`exclusion.part_d_glp1`) and using the fact's own date ignore the temporality axis. All three use the same gate. They still require a `verbatim` or `normalized` position, `certainty: present` and `subject: patient` (claimed and confirmed by the cues), no `unrecognized` flag, and the date bound inside the quote (otherwise `value_not_in_quote`). When the cues read the temporality axis as `current`, `historical` or `resolved`, the verifier derives `assertion_check` for these fields from the certainty and subject axes alone; the temporality outcome stays in `evidence.attributes.per_axis.temporality`, and when it is not `matched` the evidence carries the flag `temporality_unverified`. An explicit hypothetical cue in scope, or a temporality scope that cannot be decided, still decides as for any other field (`assertion_mismatch` or `unrecognized`): a conditional date or fill is not an event. A row that fails the gate stays stored as evidence with its exclusion reason or `unrecognized` flag, but never reaches the rules. That flag is not an exclusion, does not block anchoring and does not cap a decision (it is not one of the step-8 flags). A row the model itself labels `hypothetical` is still not a patient fact and anchors nothing. A date inside the sentence is never a temporality cue (guide A-03, C-08).

**Reference date**: `assessment_date` in `input.yaml`; "current and ongoing" is judged against it, not against the run date.

**Date precision** `date_precision` ∈ `day` / `month` / `year`: `2024-01` is the interval of the whole of January and is not filled in as the 1st. A medication period counts as overlapping only when the overlap is certain; otherwise `period_unknown`.

**Undated medication lists**: a list in the same document as the BP reading, labelled as current medications, is treated as in use on that document's date (`same_note_list`; case 09). Whether it is explicitly complete is a separate matter, `medication_lists[].complete`.

## 6. Enums

**Position status** `position_status`: `verbatim`, `normalized`, `candidate` (fuzzy candidate; cannot support `supported`), `not_found`. The verification order is fixed: on `not_found`, layers 3 and 4 are skipped and `exclusion_reasons` is exactly `quote_not_found`.

**Repeated quotes**: list all positions (verbatim hits and normalization-equivalent hits) and run the sentence-level assertion check on each; all results identical → take the first position, verbatim hits first, record the position status as is, add `ambiguous_match`; results differ → `candidate`.

**Two kinds of `candidate`**: a fuzzy candidate (`attributes.candidate_ratio`) supports nothing and never triggers `wrong_patient`. A repeated quote that became a candidate because its occurrences differ (`attributes.occurrences`) still has a position for each occurrence, and an identifier read there is still screened for `wrong_patient`.

**Sentence-level assertion check** `check_assertion(sentence, mention_span, claimed) -> AssertionCheck`, result ∈ `matched` / `mismatch` / `unrecognized`:

- Cues act only **within scope**: negation words, family words etc. affect only what is to their right and stop at a terminator (`but`, `however`, `except`, `;`, a full stop, a list-item separator). A mention not inside any cue's scope → default values (present / patient / current).
- The LLM gives the default values and there is no cue in scope → `matched`; the LLM says negated / family / resolved etc. and no cue is found in scope → `unrecognized` (cannot support `supported`; the sub-result is `review`); the cue contradicts the LLM → `mismatch` (evidence excluded with `assertion_mismatch`); scope cannot be determined → `unrecognized`.
- Dated event fields (`glp1_start`, `prior_glp1`, `doc_dates`): when the cues read temporality as `current`, `historical` or `resolved`, the result is taken from the certainty and subject axes only, and a temporality outcome other than `matched` adds the flag `temporality_unverified` instead of `unrecognized` or `assertion_mismatch`. A hypothetical cue or an undecidable temporality scope still decides (§5).
- Right-hand patterns: `ruled out`, `excluded`, `resolved` and a `?` attached to a word also apply when they stand to the right of the mention in the same scope. A `?` that ends a question is not a cue.
- Scope on forms: a `Label:` line is a list-item boundary. A heading line that holds only a label and a colon governs the `Label:` entries under it, across full stops; a blank line ends the section.
- A negated treatment is not a negated condition (guide A-09). This does not apply when the treatment word modifies the diagnosis; a negated treatment followed by a conjunction leaves the certainty `unrecognized`.
- In a quote spanning sentences, each mention looks only at the cues in its own sentence; cues do not cross a full stop ("No diabetes. Prior MI." → diabetes: negated; MI: `historical`, from its own cue `Prior`). The terminator list and the cue-word table live together in the annotation guide (`docs/annotation-guide.md`).
- Example: "No diabetes, but mother had MI" → diabetes: negated; MI: family.

**Value binding** (layer 3): the raw value must be a whole token inside the located span and must be bound to the fact it describes. A number binds to its unit and label; a stage or severity to its diagnosis; a date to an event word and then to the drug name; a date of birth to its label; an event date to its own measurement, the nearest one with nothing in between, and for a point-in-time value (`anthropometrics`, `bp_readings`, `labs`) also the only explicit date of the value's clause, on either side of the value and across a value label, unless another number or a treatment term stands between them or the date stands directly on another number of the clause (two or more dates in the clause: the nearest-with-nothing-between rule alone); a `doc_dates` date to the nearest document name; a GLP-1 purpose to a cue (a MACE cue is never overridden); a PAD symptom and a cirrhosis qualifier to the patient's own text in the same clause; each lifestyle value to exactly one cue. A percentile, the end of a range, an upper or lower bound and a signed number are not measurements. A value that follows goal or target wording is not a measurement, for every kind of value. A hypothetical or resumed start, and a start word that governs another drug, are not an initiation. A drug with a stop or an end date in its clause is not ongoing.

- `value_not_in_quote`: the raw value is not a whole token, inside the located span, bound to the fact.
- `unrecognized`: the text neither supports nor refutes a non-default value (no cue, conflicting cues, or a binding that cannot be resolved). The flag is set independently of `assertion_check`, and it reaches only the sub-results that use the flagged fact. A fact that carries the flag supports neither `supported` nor `not_supported`: a sub-result that would reach either status through such a fact is `review`. An `insufficient` result is unchanged.
- A start date or a document date that is excluded or flagged `unrecognized` anchors nothing: facts that depend on it stay undated, and the BMI sub-results are `insufficient` (or `review` when only a measurement before initiation exists, §3.1).
- PA form checkboxes: the value binds only on a `pa_draft` document, on a single line of the form `label: options` with a marked (`[X]`) or empty box, and only when the label is a registered label of that claim. A field that offers choices needs exactly one mark, on the claimed value.
- Verifier attributes in `evidence.attributes`: `quote_date` (§5), `normalizations` (the normalization steps of a `normalized` position), `candidate_ratio` and `occurrences` (the two kinds of `candidate` above).

**Table detection** (`table_source`): the line containing the quote has `|`, or 2 or more tabs, or fields separated by 3 or more consecutive spaces. P1 does not parse tables; sub-results that use them are `review`.

**Evidence-level exclusion reasons** `evidence.exclusion_reasons` (array): `quote_not_found`, `value_not_in_quote`, `assertion_mismatch`, `wrong_patient`, `unparseable_value`, `claim_document`.

**Condition-level exclusion reasons** `decisions.excluded_evidence[].reason`: `after_initiation`, `before_initiation`, `timing_unknown`, `period_unknown`, `candidate_only`, `superseded_by_at`.

**Flags** `flags`: `id_missing`, `inconsistent_values`, `imprecise_source`, `table_source`, `timing_disagreement`, `combination_pill`, `class_ambiguous`, `cv_history_only`, `boundary_value`, `unrecognized` (an unrecognized concept or wording; counted separately in the report and automatically added to the trap pool's pending list), `ambiguous_match`, `post_initiation_exclusion`, `same_note_list`, `height_from_other_date`, `uncovered_keyword` (optional), `temporality_unverified` (evidence only: an event fact's temporality label the cues, which read an actual event, do not confirm, §5; never on a decision).

**Attempt status** `attempts.status`: `started` (written before sending) → `response_saved` (the complete response is on disk) → `parsed` | `parse_failed` | `refused` | `truncated`; or `api_error`, `unknown_outcome` (timeout, or interrupted before the response reached disk; cost recorded as NULL, not 0).

**Assertion, three axes**: `certainty` ∈ `present` / `negated` / `uncertain`; `subject` ∈ `patient` / `family` / `other`; `temporality` ∈ `current` / `historical` / `resolved` / `hypothetical`.

**Other**:

| Field | Values |
|---|---|
| `payer` | `part_d`, `medicaid`, `self_pay`, `bridge`, `commercial`, `unknown` |
| `purpose` | `weight`, `mace`, `other`, `unknown` |
| `end_kind` | `ongoing`, `ended`, `unknown` |
| `osa_severity` | `mild`, `moderate`, `severe`, `unspecified` |
| `symptomatic` | `yes`, `no`, `unknown` |
| `lifestyle.program_type` | `structured_clinical`, `commercial`, `advice_only`, `referral_pending`, `declined`, `none_stated` |
| `lifestyle.attendance` | `regular`, `irregular`, `unknown` |
| `doc_role` | `clinical`, `referral`, `pa_draft` |
| `doc_origin` | `mtsamples`, `case_report`, `authored` |
| gold `origin` | `spec`, `model_candidate`, `keyword_scan`, `human_inventory` |
| gold `review` | `human_verified` |

The string `"unknown"` is valid only in the enum fields of the table above; numeric or date fields receiving `"unknown"`, `"N/A"` or `""` are always rejected.

## 7. Input, extraction and data flow

### 7.1 Input visible to the system: `cases/<variant_id>/input.yaml` + `docs/`

```yaml
variant_id: case-01            # ladder versions carry the level: case-15-L0 … case-15-L5
assessment_date: 2026-10-15
target_course: {drug: Wegovy, start: 2025-03-15}
primary_patient: {patient_id: P-1042, name: "…", dob: 1961-04-02}
documents:
  - {doc_id: D0-pa-form-draft, role: pa_draft}
  - {doc_id: D1-referral, role: referral}
  - {doc_id: D2-mtsamples-4985, role: clinical}
```

- Sent to the model: the full text of each document, with its `doc_id` and `role`. **Not sent**: `primary_patient`, `assessment_date`, `target_course` (identity and timepoints are compared by the program).
- `case.yaml` is hidden configuration (story, traps, sources, `doc_origin`, ladder record); the system does not see it.
- Reading files: `open(path, encoding="utf-8", newline="")`, no newline conversion; offsets refer to this string. Tests cover position mapping for CRLF, NFKC expansion, combining characters and emoji.

### 7.2 Extraction output

Not found means an empty array. Every fact shares: `doc_id`, `quote`, `certainty`, `subject`, `temporality`, `event_date`, `date_precision`, `relative_to_glp1_initiation`.

| Array | Specific fields |
|---|---|
| `patient_identity[]` | `patient_id`, `name`, `dob`, `stated_age` |
| `doc_dates[]` | `target_doc_id`, `date` |
| `glp1_start[]` | `drug`, `date`, `purpose` |
| `prior_glp1[]` | `drug`, `date`, `payer`, `compounded` |
| `anthropometrics[]` | `kind` ∈ `height` / `weight` / `bmi` / `bmi_percentile`, `raw_value`, `raw_unit` |
| `bp_readings[]` | `sbp`, `dbp` |
| `labs[]` | `kind` ∈ `a1c` / `fpg` / `egfr`, `raw_value`, `raw_unit` |
| `medications[]` | `name`, `dose`, `indication`, `start`, `end` (each with precision), `end_kind`, `list_id` |
| `medication_lists[]` | `list_id`, `complete`, `section_title` |
| `diagnoses[]` | `concept`, `osa_severity`, `ahi`, `fibrosis_stage`, `cirrhosis`, `ckd_stage`, `symptomatic` |
| `lifestyle[]` | `kind`, `program_type`, `attendance`, `start`, `end`, `end_kind`, `limitation`, `description` |
| `pa_form_claims[]` | `claim_id`, `claimed_value` |

- `concept` ∈ `t2dm`, `prediabetes`, `osa`, `mash`, `hfpef`, `ckd`, `mi`, `stroke`, `pad`, `hypertension`, `other`. `bmi_percentile` is never treated as kg/m². NASH (the older name) maps to `mash`; the original spelling stays in the quote.
- The `MEDICATIONS:` section of an MTSamples document does not count as explicitly complete. `complete=true` with no antihypertensive in the list → can express "complete, but no antihypertensives".
- Output mode (`docs/adr/0002-extraction-output-mode.md`): the schema is sent as the `input_schema` of a single tool, `record_extraction`, that is **not** `strict`, with `tool_choice: {type: auto, disable_parallel_tool_use: true}`; the system prompt requires exactly one call. The reply's `tool_use.input` is the extraction. The local Pydantic model keeps the full constraints and is the only validation: a reply without the call, with a non-object input, or with a validation error is `parse_failed` (§11). `transform_schema()` is not in the request path; it remains a local test that the schema compiles.
  Why: the compiled grammar of this schema (22.5 KB) exceeds the API's limit (about 5 KB), so neither `output_config.format` nor a strict tool is accepted; a non-strict tool compiles no grammar and has no size limit, and the model rejects forced `tool_choice`. The server-side guarantee that the output matches the schema is given up; the attempt budget and the dead letters cover a schema-violating reply, and nothing downstream reads an unvalidated extraction.
- Versions: `prompt_version` is `extract-v5` and `schema_version` is `v2`. `claim_id` carries its allowed values as an `enum` in the schema.

### 7.3 Data flow

```python
def extract(inp: CaseInput, client: Client, store: Store) -> Extraction: ...
def verify(ext: Extraction, docs: Docs) -> list[CheckedEvidence]: ...
def compute(evidence: Sequence[CheckedEvidence], ctx: CaseContext) -> ComputedFacts: ...
def evaluate_rules(facts: ComputedFacts, policy: Policy) -> list[Decision]: ...
```

- Rules read only `ComputedFacts`; `ComputedFacts` come only from `CheckedEvidence`. **No layer reads back the untrusted `parsed_json`.**
- The type-specific fields of `CheckedEvidence` are stored in `evidence.attributes` (JSON); each `field` has its own Pydantic model for validation.

| Extraction | Derived by compute | Rule `requires` |
|---|---|---|
| `patient_identity[]`, input `primary_patient` | `doc_facts.identity_status`, `wrong_patient` | `patient_identity`; pre-filter for all conditions |
| `glp1_start[]`, input `target_course` | `initiation_date`, `initiation_purpose` | all pathways, `mace_purpose` |
| `doc_dates[]` | `doc_facts.doc_date` | timepoint computation |
| `patient_identity[].dob`, `stated_age` | `age_interval_at_initiation` | `age_18` |
| `anthropometrics[]` | `bmi_candidates[]` | `bmi_path_a`, `*.bmi` |
| `bp_readings[]` | `bp_at_initiation[]` | `bmi_path_b.htn` |
| `medications[]`, `medication_lists[]` | `med_periods[]`, `distinct_antihypertensives_overlapping(date)` | `bmi_path_b.htn` |
| `labs[]` | `a1c`, `fpg_mg_dl`, `egfr[]` | `prediabetes`, `ckd`, `exclusion.t2dm` |
| `diagnoses[]` | `dx[]` | comorbidity and exclusion sub-results |
| `prior_glp1[]` | `prior_glp1[]` | `exclusion.part_d_glp1` |
| `lifestyle[]`, input `assessment_date` | `lifestyle_applicable[]` | `lifestyle.*` |
| `pa_form_claims[]` | `bmi_bracket` | `claim.*` |

**Tests for rules and policy**: `set(yaml_ids) == set(RULES)`; every `requires` ⊆ the names in the middle column above; boolean policies are tested with both values; enum policies are tested only with the **implemented** values, and `Policy.model_validate` raises `UnsupportedPolicyValue` on an unimplemented value (`test_policy_rejects_unimplemented_values`). Safety conditions (for example "no support without an initiation date") are written as invariants, not as switches.

## 8. Gold format and matching

```json
{
  "variant_id": "case-01",
  "guideline_version": 1,
  "facts": [
    {"field": "anthropometrics", "kind": "bmi", "norm_value": 46.0, "norm_unit": "kg/m2",
     "doc_id": "D2-mtsamples-4985", "start": 812, "end": 833, "quote_sha256": "…",
     "certainty": "present", "subject": "patient", "temporality": "current",
     "event_date": "2025-03-14", "relative_to_glp1_initiation": "at",
     "origin": "human_inventory", "review": "human_verified", "guideline_clause": null}
  ],
  "expected_absent": [
    {"field": "lifestyle", "kind": "activity"},
    {"field": "diagnoses", "concept": "mash"}
  ],
  "conditions": [
    {"id": "bmi_path_a", "status": "supported", "flags": [], "reason": "…"}
  ],
  "case_flags": [],
  "claims": [{"id": "claim.bmi_bracket", "status": "supported"}],
  "gold_version": 1,
  "changes": []
}
```

- `norm_value` units are fixed: `cm`, `kg`, `kg/m2`, `mmHg`, A1c `%`, glucose `mg/dL` (g/L ×100, mmol/L ×18.016), eGFR `mL/min/1.73m2`.
- `start` / `end`: Python string indices, 0-based, `end` exclusive. MTSamples cases store only `quote_sha256`; others store `quote`. `freeze_splits.py` checks this.
- `expected_absent[]`: facts the system must not extract (`field` plus `kind` or `concept`). Not extracted → "not_found correct"; extracted → FP.
- `sentence_id` is not in gold and not scored. `flags` and `case_flags` are matched. Clinical judgement items add `guideline_clause`.
- Excerpt gold uses the same format with `conditions` replaced by `sub_results`; only the items under test are listed.
- Blind draft `blind_draft.json`: `conditions` (`id`, `status`) + inventory table (`field`, `kind` / `concept`, `present` / `absent` / `unsure`, approximate location); never changed afterwards. A case may instead carry `assisted_review.json` in the same format, whose inventory was proposed with AI assistance and confirmed by the annotator; such a case has no blind draft and no blind agreement count, and a case has one file or the other.

**Matching**: one-to-one; only repeated quotes of the same event are merged into one record. **All three axes are matched for every kind of fact**; when gold has an `event_date` the system must have one and it must be identical (a gold date is not a wildcard).

| `field` | Additional keys that must match |
|---|---|
| `anthropometrics`, `labs` | `kind`, `doc_id`, `norm_value` (BMI / weight / height per the §4 tolerances; labs compared exactly as Decimal), `relative_to_glp1_initiation` |
| `bp_readings` | `doc_id`, `sbp`, `dbp`, `relative_to_glp1_initiation` |
| `diagnoses` | `concept`, `doc_id`, and when present `osa_severity` / `ahi` / `fibrosis_stage` / `cirrhosis` / `ckd_stage` / `symptomatic` |
| `medications` | normalized drug name, `doc_id`, `period_start`, `period_end`, `end_kind`, `list_id` (a label: the gold label is first aligned to the system label of the matched `medication_lists` fact) |
| `medication_lists` | `doc_id`, `complete` |
| `glp1_start` | drug name, `date`, `doc_id`; no `payer` (the extraction has none for this field) |
| `prior_glp1` | drug name, `date`, `payer`, `doc_id` |
| `doc_dates` | `target_doc_id`, `date` |
| `patient_identity` | `doc_id`, `patient_id`, `dob`; no date is compared: gold carries `event_date: null` on these facts (guide T-04) |
| `lifestyle` | `kind`, `program_type`, `attendance`, `end_kind`, `doc_id` |
| `pa_form_claims` | `claim_id`, `claimed_value`; no date is compared: gold carries `event_date: null` on these facts |

- **Not stated**: the enum values `unknown`, `none_stated` and `unspecified` count as "the document does not say" on both sides; gold leaves those keys out and they never count as a mismatch.
- **Excluded evidence**: an evidence row with a non-empty `exclusion_reasons` (for example `claim_document` or `wrong_patient`) is never a false positive. When it is the only row that matches a gold fact, the fact is `matched_but_excluded`, not a true positive.
- **Wrong value**: a gold fact with no match is paired with the closest unmatched row of the same `field`, `kind` / `concept` and `doc_id` (fewest differing keys, then lowest evidence id) and reported with the names of the differing keys.
- **Most upstream error** of a wrong condition or claim, first hit wins: `gold_question`, `extraction_missed`, `extraction_wrong_value`, `verify_excluded`, `compute_timepoint` (the only differences are a date or timepoint that compute derived), `extraction_extra` (a dependent fact the system extracted that gold does not hold), otherwise `rules`.

**Holdout**: A holdout variant is evaluated once, with the frozen configuration. A later change to its gold raises `gold_version`, adds a `changes` entry, is disclosed in the evaluation report, and the case is reported as a regression case from then on.

Required tests: `test_family_bp_is_not_patient_tp`, `test_wrong_med_period_is_not_tp`, `test_ckd2_is_not_ckd3a_tp`, `test_missing_gold_date_is_not_tp`.

## 9. Version identity of the dirty ladder

- Each level is an **immutable input version**; `variant_id` carries the level (`case-15-L0` … `case-15-L5`); `splits.yaml` is keyed by `(case_id, variant_id)` and records the hashes of `input.yaml`, `docs/`, gold and replay for each version.
- Each level first **materializes** the inherited `input.yaml` and `docs/` as complete files, then freezes them; nothing is assembled at run time.
- **Gold inherits the semantic facts** (`kind` / `concept`, `norm_value`, the three axes, timepoint, `doc_id`); `quote`, `start`, `end` and `raw_*` are rebuilt from the fact_id → quote map returned by the rewriting model and then pass the deterministic checks (`docs/annotation-guide.md` §1, route 1 step 3). Only M4 leaves the words unchanged.
- **M2 (convert to tables)** hits the "tables are always `review`" rule: this is a delta in the level's expected status, recorded in the change log, and not an extraction regression (`test_m2_table_policy_changes_expected_status`).
- P1: `case-15-L0` is private only; the public `splits.yaml` holds only hashes; the first version published in P2 is the final one (in the public repo, `case-15` has `alias_of: case-15-L5` in `case.yaml`).
- Test: `test_ladder_gold_matches_current_variant`.

## 10. Thresholds and policy

| Item | Value | Source |
|---|---|---|
| BMI | 27, 30, 35 (`≥`, unrounded value) | CMS FAQ |
| Age | 18 | CMS FAQ |
| Uncontrolled hypertension | systolic > 140 or diastolic > 90, with at least two antihypertensives at the same time | CMS fact sheet |
| Prediabetes range | A1c 5.7–6.4%; fasting glucose 100–125 mg/dL | ADA |
| Diabetes range | A1c ≥ 6.5%; fasting glucose ≥ 126 mg/dL | ADA |
| CKD 3a or higher | eGFR < 60 | KDIGO |
| Moderate-to-severe OSA | AHI ≥ 15, or explicitly moderate / severe | AASM |

- **BMI display bracket** (`bmi_bucket_from_raw: true`): the unrounded value selects a half-open bracket `[0,27)`, `[27,30)`, `[30,35)`, `[35,40)`, `≥40` (the PA form's "less than 27" box is `claimed_value: <27`); formatting never re-selects the bracket.
- Hypertension: `htn_not_supported_by_complete_list: true`; `htn_not_supported_by_readings: false`.
- `lab_in_diabetes_range_without_dx: review`; `path_c_cv_history_requires_review: true`.
- **Antihypertensives** `rules/drugs-v2.yaml`: drug name (including brand names and combinations) → `drug_canonical`, `class`; uncertain ones are marked `class_ambiguous`. Version 2 includes the drugs of cases 01, 15, 03 and 04 plus chlorthalidone and spironolactone; `class_ambiguous` is allowed only on the five classes listed in the table's header (`thiazide_diuretic`, `loop_diuretic`, `potassium_sparing_diuretic`, `mineralocorticoid_receptor_antagonist`, `alpha_blocker`), and every combination component also has a standalone entry with the same class; the rest are added batch by batch. GLP-1 names are not in this table (`bridge_check.enums.GLP1_NAMES`; how a GLP-1 name resolves to its ingredient is in §5).
- The rules table's `source.quote` holds one short quotation (no more than one sentence).

## 11. Execution, storage, CI

**Run lock**: on entry the CLI takes `fcntl.flock(LOCK_EX | LOCK_NB)` on the lock file corresponding to the DB path; if it cannot → print "another run in progress", exit code 4, do not touch the DB. The lock covers the whole run (including waiting for the API), but **no SQL write transaction is held while waiting for the API**.

```python
with exclusive_run_lock(db_path, blocking=False):
    recover_orphaned_runs(conn)  # turn leftover running rows into failed+interrupted
    return check_case(...)
```

Tests: two processes run at once, the second exits with code 4 and does not change the first one's status; after a kill the lock is released and the next run can recover.

**API calls and recovery**:

1. Before sending, write `attempts` (`started`) and commit.
2. On receiving the complete response, immediately write `response_json`, change to `response_saved`, commit, and only then parse.
3. After parsing, change to `parsed` (in the same transaction write `extractions` with `INSERT … ON CONFLICT(cache_key) DO NOTHING`, then read back) or to `parse_failed` / `refused` / `truncated`.
4. Timeout or interruption before reaching disk → `unknown_outcome`, cost NULL; this is the acknowledged at-least-once limitation.

**Lookup order for every `check`**: find `extractions` by cache key → otherwise find the latest attempt with `status='response_saved'` and replay the parse (no API call) → only if neither exists, call the API.

```sql
SELECT id, response_json FROM attempts
WHERE cache_key = ? AND status = 'response_saved'
ORDER BY id DESC LIMIT 1;
CREATE INDEX idx_attempts_cache_key ON attempts(cache_key);
```

Terminal states such as `parse_failed` are not replayed. **The retry budget is per case run**: total attempts ≤ 4 (including the first), of which parse-type (`parse_failed`, `refused`, `truncated`) ≤ 2, total time 5 minutes. After a first `parse_failed` the same request is sent once more, as a new attempt with its own row and its own saved response; `refused` and `truncated` are not retried and end the run at once. The cost of every attempt counts toward the cost ceilings.

**Extraction cache key** = `sha256(canonical_json(request_kwargs))`: `request_kwargs` is what is actually passed to `messages.create` — `model`, `system`, `messages` (including the documents and the `doc_id` / `role` wrapping), `tools`, `tool_choice`, `max_tokens`, `thinking`; `canonical_json = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))`. Excludes timeout, retry settings and metadata. Tests: changing a role or the prompt content changes the key; dict order does not.

**Cost check before sending**: every API call is checked against the per-run and per-eval cost ceilings before its attempt row is written: the cost already recorded plus a reservation for the call about to be sent must fit under the ceiling, otherwise the call is not made. An `unknown_outcome` attempt has no recorded cost (NULL) and is counted at its reservation against both ceilings. The ceilings, the request timeout and `max_tokens` are set in `docs/adr/0001-global-limits.md`.

**Cache scope**: only the extraction cache; verify, compute and rules are recomputed every time.

**Storage constraints**: every SQLite table is `STRICT`; every enum column (the status codes and run status of §1, each enum of §6, `decisions.kind`) has a `CHECK`, with the value list generated by the program from the single enum definition, never written twice by hand; `foreign_keys=ON` on every connection; SQL uses only Postgres-compatible syntax and is centralized in `store.py`. Tests: `test_db_rejects_unknown_enum_value`, `test_db_rejects_wrong_type`, `test_foreign_keys_enforced`.

**Database file**: a database file with more than one hard link is refused before SQLite opens it. A symbolic link to the database is resolved first, so both spellings share one run lock. The sidecar files (`-wal`, `-shm`, `-journal`) are checked next to the given path and next to the resolved path: one that is a symbolic link or has more than one hard link is refused. Tests: `test_db_with_more_than_one_link_is_refused`, `test_a_symlink_to_the_same_db_shares_the_lock`, `test_open_store_refuses_linked_sidecars`, `test_open_store_checks_sidecars_at_the_resolved_path`.

**Per-document run conclusions** are stored in `doc_facts(case_run_id, doc_id, doc_date, doc_date_evidence_id, identity_status, identity_evidence_id)`; the `documents` table stores only the input source (`doc_id`, `case_id`, `sha256`, `role`).

**Structured logs**: standard-library `logging`, one JSON object per line: `ts`, `level`, `run_id`, `case_id` (or `variant_id`), `attempt_no`, `stage`, `event`, `duration_ms`, `error_type`; **no document content and no quotes** (MTSamples offsets are not written either). `--json` output has the same structure as the report. SDK and HTTP client loggers (`anthropic`, `httpx`, `httpcore`) are capped at `WARNING`, so a debug setting cannot write request bodies to the log. A case whose `input.yaml` cannot be read is recorded as `unresolved-<sha8 of the case path>`; input error messages use only fixed file names, field names and indices.

**Error records** `dead_letters`: `case_run_id`, `attempt_id`, `stage`, `error_type`, `fact_path` or `evidence_id`, sanitized message (no source text). `bridge history` shows each run's source attempt, cache hit or recovery source, and `unknown_outcome`.

**Sentence splitting**: a rule-based splitter at a fixed version (with a clinical abbreviation list); the version is recorded in `case_runs`.

**Rules version**: `rules_version` names the rules table (`rules/bridge-v1.yaml`). Rule code has no version of its own; the commit in the report header identifies it.

**CI** (GitHub Actions; job names are fixed and branch protection points to them):

| job | Runs | Fetches MTSamples |
|---|---|---|
| `quality` | `ruff check`, `ruff format --check`, `mypy --strict`, `pytest -m "not live"`, then `pip-audit` (never blocking) | no |
| `tests` | `pytest -m "not live"` | yes |
| `data-integrity` | `freeze_splits.py --check` against the base SHA, then `check_rules.py` | yes |
| `eval` | on pull requests the baseline change guard (`check_baseline_title.py`); `bridge eval --split dev --offline` against the baseline of the base SHA; `pytest tests/eval`; the public report directory is uploaded with `if: always()` | yes |

- Triggers: `push: {branches: [main]}` and `pull_request`, so PR branches do not run twice. `data-integrity` and `eval` check out with `fetch-depth: 0`, because both read the base SHA.
- Fetch step (`fetch_mtsamples.py`): exit code 2 means the MTSamples mirror is unreachable; the job writes a summary line and continues (the eval report is then incomplete). Any other non-zero exit code fails the job.
- Private CI checks out the public code at a **specified `code_sha`** (not defaulting to main) and runs `bridge eval --data-root <private data>`; `splits.yaml` can be merged (public holdout rows hold only hashes, the private side supplies the files).

**Freeze check**: `freeze_splits.py --check` reads `splits.yaml` from the PR's base SHA and compares. New batches can only add; changing existing gold must bump `gold_version` and write `changes`; changing a split always fails. Each has its own test (first bootstrap, appended batch, legitimate correction, forbidden split change). A row whose `cases/<variant_id>/` directory is absent from the checkout is a **hash-only row** (its files are kept in the private repo): the check verifies its shape (`files` lists `input.yaml` and `expected.json` with sha256 hashes; `split`, `gold_version`, `frozen_at`) and treats it as frozen without looking for the files; the base comparison applies to it unchanged, so its file list is fixed, only `expected.json` may change and only with a higher `gold_version`, and its split never changes. A hash-only row may carry a salted sha256 for a document whose plain hash would identify a public source text; such an entry is marked by a comment in `splits.yaml`. If the directory exists, every listed file must exist and match its hash. Hash-only rows may be `dev` or `holdout`; the eval path skips variants without a directory and logs the skip with reason `hash_only`.

**Regression baseline**: `reports/baseline-dev.json` stores the manifest / gold / replay hashes, the status and flags of every condition in every case, correctness, false-support count, and missed-exclusion count. CI reads the baseline from the **PR base SHA**; present in base but deleted in head → fail; ordinary PRs may not change this file; only PRs whose title contains `[update baseline]` may, and CI still prints the diff against the old baseline. When the base has no baseline yet → report only, exit code 0.

**Holdout isolation**: holdout variants never run in CI and have no baseline (`eval --split holdout` refuses the baseline options). `eval --split holdout` requires a `--data-root` outside the public checkout; the case directory must be the real `<data-root>/cases/<variant_id>` with every file resolving inside it, and the replay must resolve under its own replay directory, so a symbolic link is refused before any file is opened. The database, its lock and its sidecars may not lie inside the public checkout, including a default temporary location. The whole batch is checked first: one refused row means no attempt is made for any row and the exit code is 3. In a dev eval, a path that resolves into a holdout variant is refused (exit code 3). `check` and `history` refuse a case whose resolved location is a holdout variant, compared by file-system identity, so a differently cased spelling or a link is refused too.

**Definition of regression**: more false supports, any condition going from correct to wrong, flags going from correct to wrong, an exclusion sub-result dropping from `review` to `insufficient` / `not_supported`.

**Replay files**:

- Path `replays/<variant_id>/<input_hash>-<prompt_version>-<schema_version>.json`.
- Each quote records `replay_fidelity`: `exact` (non-MTSamples text stored directly; or an MTSamples verbatim hit that can be restored losslessly from the offset) or `lossy` (an MTSamples normalized hit, or unlocatable). Unlocatable `lossy` quotes store `sha256` plus the placeholder string `"\x00UNLOCATABLE:" + sha8`.
- Public replays guarantee consistency for two classes only: `locatable` (verbatim ∪ normalized) vs `not_locatable`. The four-valued position status and the quote-verification ablation exist only in the private full report; the public report lists the number of `lossy` quotes and keeps them out of those metrics' denominators.
- The private side compares, record by record, the `position_status`, `assertion_check`, exclusion reasons and decisions of the complete recording against the restored public version.
- `fixtures/synthetic/`: hand-written synthetic responses and failure fixtures for unit tests; not called recorded responses and never used in `eval`.

**Public outputs**: every public artifact (report, replay, CI artifact) goes through `export_public_run()`, which exports with an **allow-list of fields**; MTSamples free-text fields (`description`, `indication`, `section_title`, quotes) are always externalized as offset + hash or omitted; reports cite evidence only as `doc_id[start:end] sha8`. Test `test_public_outputs_contain_no_mtsamples_text`: cut the 6 documents into 40-character sliding windows and scan `reports/`, `replays/`, `cases/**/expected.json` and failure outputs; additionally plant a unique long string and confirm no public artifact contains it. pytest assertion messages use `evidence_id`, never a quote.

### Known gaps between this contract and the code

- §5, baseline wording: no code implements "an undated quote that states a baseline at initiation is `at`"; such a fact stays `unknown`.
- §6, target values: the code rejects only a blood pressure after goal or target wording; a BMI, weight or lab is accepted as a measurement.
- §11, cost of `unknown_outcome`: counted at the reservation only within its own run; it counts as $0 toward the evaluation ceiling across runs.
