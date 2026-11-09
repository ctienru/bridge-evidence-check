# Machine contract

> 2026-11-08 (third edition, incorporating the ninth review). **Program-level names and rules are defined by this page**: condition IDs, status codes, decisions and aggregation, conflicts, initiation timepoint, enums, input and extraction schema, data flow, gold format and matching, thresholds, execution and CI. The policy content (why a decision is made this way) lives in `docs/adr/0001-project-policies.md` (to be added); this page only writes it in the form the program uses. When another document and this page disagree, this page wins and the other document is corrected.
>
> To be reviewed and signed off by Terri (plan item 1b); finalized before the schema smoke test.

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
- Leftover `running`: only **after acquiring the run lock** (§11) are old `running` rows of the same case changed to `failed` + `interrupted`. With the lock in place, a leftover `running` can only be a real crash.
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
- **Claims**: one ID per checkbox field on the PA form, named after what it is checked against (`claim.age_18`, `claim.drug`, `claim.bmi_bracket`, `claim.bmi_path_b.hfpef`, `claim.exclusion.t2dm`, …). P1 only builds the ones used by cases 01 and 15; the full list is added batch by batch. Status: chart supports → `supported`; not mentioned → `insufficient`; contradicted → `conflict`; chart mentions it but as suspected (HFpEF ticked, chart says r/o HFpEF) → `review`. Claims never change a condition's status.
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

Tests: `test_htn_boundary_reading_with_ambiguous_diuretics_is_insufficient` (case 15), `test_htn_combination_pill_alone_is_review` (case 04 before the added drug).

**`bmi_path_c.prediabetes`**:

1. The patient has a prediabetes diagnosis (present / historical) → `supported`.
2. The diagnosis is uncertain → `review`.
3. No diagnosis, A1c 5.7–6.4% or fasting glucose 100–125 mg/dL → `review` (`a1c_prediabetes_range_without_dx`).
4. No diagnosis, A1c ≥ 6.5% or fasting glucose ≥ 126 → this item `insufficient`; `exclusion.t2dm` is decided per §3.3 as `review` (`lab_in_diabetes_range_without_dx: review`).
5. Explicit negation of prediabetes → `not_supported`.
6. Everything else (including A1c below the range, no diagnosis) → `insufficient`. Below the range is not positive counter-evidence.

**`bmi_path_b.hfpef`**: HFpEF diagnosis present / historical → `supported`; uncertain (r/o) → `review`; explicit negation → `not_supported`; only a test finding such as diastolic dysfunction, no diagnosis → `insufficient`; everything else → `insufficient`.

**`bmi_path_b.ckd`**: CKD diagnosis with stage ≥ 3a → `supported`; CKD diagnosis, no stage written, only eGFR → `review` (list all eGFR values; `ckd_dx_egfr_only`); explicit stage 1–2 → `not_supported`; only eGFR, no diagnosis → `insufficient`.

**`bmi_path_c.mi`, `.stroke`**: the patient's own present / historical diagnosis → `supported`; a denial together with imaging or history evidence → `conflict` (§4); explicit denial → `not_supported`; TIA, demand ischemia, appearing only in a surgical-risk discussion (`hypothetical`), only troponin → `insufficient`.

**`bmi_path_c.pad`**: PAD diagnosis with `symptomatic=true` (claudication etc.) → `supported`; PAD diagnosis but symptoms unclear → `review`; PAD explicitly asymptomatic → `not_supported`; with several timepoints take the one closest to the initiation date (E04).

### 3.3 Exclusion sub-results (decided individually, not aggregated)

1. Positive evidence and explicit negation at the same timepoint → `conflict`.
2. Special staging: MASH explicitly F0–F1 or cirrhosis (F4), OSA explicitly mild (mild or AHI < 15) → `not_supported` (not this exclusion).
3. Appears only after initiation → `review` + `post_initiation_exclusion` (evidence from before and after is kept; the pathways' "not used after initiation" rule does not apply).
4. The patient has positive or suspected evidence (present, historical, resolved, uncertain; OSA severity unknown, post-surgical status unknown; A1c ≥ 6.5 without a diagnosis) → `review`.
5. Explicit negation → `not_supported`.
6. Not mentioned → `insufficient`.

**`exclusion.part_d_glp1`**: the document says it was paid by Part D in 2026 → `review`; 2025 or earlier, Medicaid, self-pay, or explicitly Bridge → `not_supported`; not mentioned, or payer unknown (only an amount, or compounded without a payer) → `insufficient`.

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
- Neither date of birth nor age, or no initiation date and the interval straddles 18 → `insufficient`.
- Examples: age 85 written three years after initiation → ≥ 81 at initiation → `supported`; age 19 written three years after initiation (day-precision document date) → 16 at initiation → `not_supported`; the same sentence with a year-precision document date → the interval straddles 18 → `review`; age 13 written ten years before initiation → about 23 at initiation → `supported`.
- Test: `test_age_stated_after_initiation_uses_interval`.

**Identity** `patient_identity` (the primary patient identifier comes from the input, §7.1): **compare IDs only; compare date of birth only when the document has no ID; never compare names**.

1. A document's ID differs from the primary patient (or no ID and the date of birth differs) → `conflict`; all evidence from that document is excluded (`wrong_patient`).
2. A document has neither ID nor date of birth → `review`; its evidence is still usable, add `id_missing`.
3. Every document is consistent → `supported`.
4. No document has any comparable identifier → `insufficient`.

**Lifestyle** `lifestyle.*`: use only data that proves applicability on `assessment_date` (the period covers that day, or the date is before that day with no end recorded); a program that starts later does not count.

1. A structured nutrition or activity program, still ongoing on `assessment_date` → `supported`.
2. The document explicitly states there is no diet plan at all (or no activity at all) → `not_supported`.
3. A commercial program (Weight Watchers, Noom), irregular attendance, or activity with a medical limitation or exception → `review`.
4. Only advice, a referral not yet attended, "will consider", or declined → `insufficient`.
5. Several applicable records → take the one closest to `assessment_date`.

**Human workload**: per case, the number of top-level rows that are `review` + `conflict` + `insufficient`; sub-results are not double-counted; lifestyle and claims are reported separately.

## 4. Conflicts and tolerances

**Same fact**: same patient, same kind of measurement or same diagnosis concept, same timepoint (both `at`; or overlapping `event_date` intervals; or both undated, describing the same visit in the same document). `at` and `after` do not conflict.

**Tolerances** (within tolerance and not crossing a threshold is treated as the same value): BMI ±0.2; weight 1% relative; height ±1 cm; BP has no tolerance; age derived from date of birth vs stated age within 1 year; labs compared exactly as normalized `Decimal`.

- **Threshold first, then tolerance**: two values on either side of a threshold → the sub-results that use that threshold are `conflict`, whether or not they are within tolerance. BMI thresholds 27, 30 and 35 are each judged separately (34.6 vs 36 → only `bmi_path_a` conflicts).
- Same side, beyond tolerance → decide as usual, add `inconsistent_values`. Age 58 vs 55 → `age_18` `supported` + `inconsistent_values`; but a contradiction in date of birth or ID is handled by the identity table and does not disappear because the ages are on the same side.
- A `conflict` cannot be rescued by another piece of evidence.
- **Diagnoses**: same concept, overlapping timepoints, one present / historical and one negated → `conflict` (E15). Different timepoints: for "prior" questions (MI, stroke) any valid present / historical record counts; for "current" questions (symptomatic PAD, OSA severity) take the one closest to the initiation date.

## 5. Initiation timepoint and dates

**The course under assessment**: `target_course` in `input.yaml` (drug + start date) specifies which initiation is assessed; the start date must still be found in the documents and pass quote verification, otherwise there is no initiation date. Resuming after a pause is not a new initiation; if the documents do not show which course it is → the affected BMI sub-results are `review`.

`relative_to_glp1_initiation` ∈ `at` / `before` / `after` / `unknown`, **present on every kind of fact**; the DB stores two columns: `relative_llm` (filled by the LLM) and `relative_computed` (computed by the program; scoring uses this column).

1. Both the fact's `event_date` and the initiation date exist → the program compares **date intervals**: the identical single day → `at`; entirely before or after → `before` / `after`; overlapping but undecidable (for example the same month at month precision) → `unknown`. Disagreement with the LLM's value → `timing_disagreement`.
2. No date → only a quote that explicitly states a baseline at initiation (at initiation, baseline, before starting tirzepatide) is `at`; otherwise `unknown`.
3. The main MTSamples document has no date: `doc_dates[]` records "the date of document D2 is X, source is this sentence in D1". **`doc_dates[]` must also pass quote verification**; if it fails → D2's facts have timepoint `unknown`. `evidence.event_date_source` ∈ `llm` / `doc_dates:<evidence_id>` / `none`; a BMI `at` can only attach to verified date evidence, and `used_evidence` lists both the BMI sentence and the date sentence. The verifier records what the quote itself says in `evidence.attributes.quote_date` (`{"date", "precision"}`, the date bound to the fact's mention at the text's precision; absent when the quote names no date) and sets `event_date_source` to `llm` (the model's `event_date` equals a date bound in the quote), `none` (the model gave a date but the quote has none bound) or NULL (not checked: quote not found, or no `event_date` given); compute writes `doc_dates:<evidence_id>` only onto a fact whose quote carries no date.

**Reference date**: `assessment_date` in `input.yaml`; "current and ongoing" is judged against it, not against the run date.

**Date precision** `date_precision` ∈ `day` / `month` / `year`: `2024-01` is the interval of the whole of January and is not filled in as the 1st. A medication period counts as overlapping only when the overlap is certain; otherwise `period_unknown`.

**Undated medication lists**: a list in the same document as the BP reading, labelled as current medications, is treated as in use on that document's date (`same_note_list`; case 09). Whether it is explicitly complete is a separate matter, `medication_lists[].complete`.

## 6. Enums

**Position status** `position_status`: `verbatim`, `normalized`, `candidate` (fuzzy candidate; cannot support `supported`), `not_found`. The verification order is fixed: on `not_found`, layers 3 and 4 are skipped and `exclusion_reasons` is exactly `quote_not_found`.

**Repeated quotes**: list all positions and run the sentence-level assertion check on each; all results identical → take the first position, record the position status as is, add `ambiguous_match`; results differ → `candidate`.

**Sentence-level assertion check** `check_assertion(sentence, mention_span, claimed) -> AssertionCheck`, result ∈ `matched` / `mismatch` / `unrecognized`:

- Cues act only **within scope**: negation words, family words etc. affect only what is to their right and stop at a terminator (`but`, `however`, `except`, `;`, a full stop, a list-item separator). A mention not inside any cue's scope → default values (present / patient / current).
- The LLM gives the default values and there is no cue in scope → `matched`; the LLM says negated / family / resolved etc. and no cue is found in scope → `unrecognized` (cannot support `supported`; the sub-result is `review`); the cue contradicts the LLM → `mismatch` (evidence excluded with `assertion_mismatch`); scope cannot be determined → `unrecognized`.
- In a quote spanning sentences, each mention looks only at the cues in its own sentence; cues do not cross a full stop ("No diabetes. Prior MI." → diabetes: negated; MI: defaults). The terminator list and the cue-word table live together in the annotation guide (`docs/annotation-guide.md`).
- Example: "No diabetes, but mother had MI" → diabetes: negated; MI: family.

**Table detection** (`table_source`): the line containing the quote has `|`, or 2 or more tabs, or fields separated by 3 or more consecutive spaces. P1 does not parse tables; sub-results that use them are `review`.

**Evidence-level exclusion reasons** `evidence.exclusion_reasons` (array): `quote_not_found`, `value_not_in_quote`, `assertion_mismatch`, `wrong_patient`, `unparseable_value`, `claim_document`.

**Condition-level exclusion reasons** `decisions.excluded_evidence[].reason`: `after_initiation`, `before_initiation`, `timing_unknown`, `period_unknown`, `candidate_only`, `superseded_by_at`.

**Flags** `flags`: `id_missing`, `inconsistent_values`, `imprecise_source`, `table_source`, `timing_disagreement`, `combination_pill`, `class_ambiguous`, `cv_history_only`, `boundary_value`, `unrecognized` (an unrecognized concept or wording; counted separately in the report and automatically added to the trap pool's pending list), `ambiguous_match`, `post_initiation_exclusion`, `same_note_list`, `height_from_other_date`, `uncovered_keyword` (optional).

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
- Convert with the SDK's `transform_schema()` before sending to the API; the local Pydantic model keeps the full constraints.
- **Fallback for the union limit** (used only if the schema smoke test exceeds the limit): make `event_date` a non-null string, add `none` to `date_precision`, and have a `model_validator` require `precision=none ⇔ event_date==""` — this is the only exception to "reject empty strings".

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
- Blind draft `blind_draft.json`: `conditions` (`id`, `status`) + inventory table (`field`, `kind` / `concept`, `present` / `absent` / `unsure`, approximate location); never changed afterwards.

**Matching**: one-to-one; only repeated quotes of the same event are merged into one record. **All three axes are matched for every kind of fact**; when gold has an `event_date` the system must have one and it must be identical (a gold date is not a wildcard).

| `field` | Additional keys that must match |
|---|---|
| `anthropometrics`, `labs` | `kind`, `doc_id`, `norm_value` (BMI / weight / height per the §4 tolerances; labs compared exactly as Decimal), `relative_to_glp1_initiation` |
| `bp_readings` | `doc_id`, `sbp`, `dbp`, `relative_to_glp1_initiation` |
| `diagnoses` | `concept`, `doc_id`, and when present `osa_severity` / `ahi` / `fibrosis_stage` / `cirrhosis` / `ckd_stage` / `symptomatic` |
| `medications` | normalized drug name, `doc_id`, `start`, `end`, `end_kind`, `list_id` |
| `medication_lists` | `doc_id`, `complete` |
| `glp1_start`, `prior_glp1` | drug name, `date`, `payer`, `doc_id` |
| `doc_dates` | `target_doc_id`, `date` |
| `patient_identity` | `doc_id`, `patient_id`, `dob` |
| `lifestyle` | `kind`, `program_type`, `attendance`, `end_kind`, `doc_id` |
| `pa_form_claims` | `claim_id`, `claimed_value` |

Required tests: `test_family_bp_is_not_patient_tp`, `test_wrong_med_period_is_not_tp`, `test_ckd2_is_not_ckd3a_tp`, `test_missing_gold_date_is_not_tp`.

## 9. Version identity of the dirty ladder

- Each level is an **immutable input version**; `variant_id` carries the level (`case-15-L0` … `case-15-L5`); `splits.yaml` is keyed by `(case_id, variant_id)` and records the hashes of `input.yaml`, `docs/`, gold and replay for each version.
- Each level first **materializes** the inherited `input.yaml` and `docs/` as complete files, then freezes them; nothing is assembled at run time.
- **Gold inherits the semantic facts** (`kind` / `concept`, `norm_value`, the three axes, timepoint, `doc_id`); `quote`, `start`, `end` and `raw_*` are rebuilt from the fact_id → quote map returned by the rewriting model and then pass the deterministic checks (`docs/annotation-guide.md` §1, route 1 step 3). Only M4 leaves the words unchanged.
- **M2 (convert to tables)** hits the "tables are always `review`" rule: this is a delta in the level's expected status, recorded in the change log, and not an extraction regression (`test_m2_table_policy_changes_expected_status`).
- P1: `case-15-L0` is private only; the public `splits.yaml` holds only hashes; the first version published in P2 is the final one (in the public repo, `case-15` has `alias_of: case-15-L5` in `case.yaml`).
- Test: `test_ladder_gold_matches_current_variant`.

## 10. Thresholds and policy

| Item | Value | Source (verified against the source text in plan item 1) |
|---|---|---|
| BMI | 27, 30, 35 (`≥`, unrounded value) | CMS FAQ |
| Age | 18 | CMS FAQ |
| Uncontrolled hypertension | systolic > 140 or diastolic > 90, with at least two antihypertensives at the same time | CMS fact sheet |
| Prediabetes range | A1c 5.7–6.4%; fasting glucose 100–125 mg/dL | ADA |
| Diabetes range | A1c ≥ 6.5%; fasting glucose ≥ 126 mg/dL | ADA |
| CKD 3a or higher | eGFR < 60 | KDIGO |
| Moderate-to-severe OSA | AHI ≥ 15, or explicitly moderate / severe | AASM |

- **BMI display bracket** (`bmi_bucket_from_raw: true`): the unrounded value selects a half-open bracket `[27,30)`, `[30,35)`, `[35,40)`, `≥40`; formatting never re-selects the bracket.
- Hypertension: `htn_not_supported_by_complete_list: true`; `htn_not_supported_by_readings: false`.
- `lab_in_diabetes_range_without_dx: review`; `path_c_cv_history_requires_review: true`.
- **Antihypertensives** `rules/drugs-v1.yaml`: drug name (including brand names and combinations) → `drug_canonical`, `class`; uncertain ones are marked `class_ambiguous`. P1 only includes the drugs of cases 01 and 15; the rest are added batch by batch.
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

Terminal states such as `parse_failed` are not replayed. **The retry budget is per case run**: total attempts ≤ 4 (including the first), of which parse-type ≤ 1, total time 5 minutes.

**Extraction cache key** = `sha256(canonical_json(request_kwargs))`: `request_kwargs` is what is actually passed to `messages.create` — `model`, `system`, `messages` (including the documents and the `doc_id` / `role` wrapping), `output_config`, `max_tokens`, `thinking`; `canonical_json = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))`. Excludes timeout, retry settings and metadata. Tests: changing a role or the prompt content changes the key; dict order does not.

**Cache scope**: only the extraction cache; verify, compute and rules are recomputed every time.

**Storage constraints**: every SQLite table is `STRICT`; every enum column (the status codes and run status of §1, each enum of §6, `decisions.kind`) has a `CHECK`, with the value list generated by the program from the single enum definition, never written twice by hand; `foreign_keys=ON` on every connection; SQL uses only Postgres-compatible syntax and is centralized in `store.py`. Tests: `test_db_rejects_unknown_enum_value`, `test_db_rejects_wrong_type`, `test_foreign_keys_enforced`.

**Per-document run conclusions** are stored in `doc_facts(case_run_id, doc_id, doc_date, doc_date_evidence_id, identity_status, identity_evidence_id)`; the `documents` table stores only the input source (`doc_id`, `case_id`, `sha256`, `role`).

**Structured logs**: standard-library `logging`, one JSON object per line: `ts`, `level`, `run_id`, `case_id` (or `variant_id`), `attempt_no`, `stage`, `event`, `duration_ms`, `error_type`; **no document content and no quotes** (MTSamples offsets are not written either). `--json` output has the same structure as the report.

**Error records** `dead_letters`: `case_run_id`, `attempt_id`, `stage`, `error_type`, `fact_path` or `evidence_id`, sanitized message (no source text). `bridge history` shows each run's source attempt, cache hit or recovery source, and `unknown_outcome`.

**Sentence splitting**: a rule-based splitter at a fixed version (with a clinical abbreviation list); the version is recorded in `case_runs`.

**CI** (GitHub Actions; job names are fixed and branch protection points to them):

| job | Content | Starts at |
|---|---|---|
| `quality` | `ruff check`, `ruff format --check`, `mypy --strict` (must pass from plan item 1 on); `pip-audit` (never blocking) | plan item 1 |
| `data-integrity` | `fetch_mtsamples.py` → source hash → `freeze_splits.py --check` → public-output leak scan | plan item 1 (fetch is required as soon as the manifest includes MTSamples) |
| `tests` | `pytest -m "not live"` | plan item 3 |
| `eval` | `bridge eval --split dev --offline` plus regression comparison; report uploaded with `if: always()`, only the sanitized directory | plan item 7 |

- Triggers: `push: {branches: [main]}` and `pull_request`, so PR branches do not run twice. Checkout with `fetch-depth: 0`.
- MTSamples mirror unreachable → the 6 cases are marked `skipped: mtsamples unavailable`, the report is marked "incomplete", other jobs are not blocked.
- Private CI checks out the public code at a **specified `code_sha`** (not defaulting to main) and runs `bridge eval --data-root <private data>`; `splits.yaml` can be merged (public holdout rows hold only hashes, the private side supplies the files).

**Freeze check**: `freeze_splits.py --check` reads `splits.yaml` from the PR's base SHA and compares. New batches can only add; changing existing gold must bump `gold_version` and write `changes`; changing a split always fails. Each has its own test (first bootstrap, appended batch, legitimate correction, forbidden split change).

**Regression baseline**: `reports/baseline-dev.json` stores the manifest / gold / replay hashes, the status and flags of every condition in every case, correctness, false-support count, and missed-exclusion count. CI reads the baseline from the **PR base SHA**; present in base but deleted in head → fail; ordinary PRs may not change this file; only PRs labelled "update baseline" may, and CI still prints the diff against the old baseline. Before plan item 7, when base has no baseline → report only, exit code 0.

**Definition of regression**: more false supports, any condition going from correct to wrong, flags going from correct to wrong, an exclusion sub-result dropping from `review` to `insufficient` / `not_supported`.

**Replay files**:

- Path `replays/<variant_id>/<input_hash>-<prompt_version>-<schema_version>.json`.
- Each quote records `replay_fidelity`: `exact` (non-MTSamples text stored directly; or an MTSamples verbatim hit that can be restored losslessly from the offset) or `lossy` (an MTSamples normalized hit, or unlocatable). Unlocatable `lossy` quotes store `sha256` plus the placeholder string `"\x00UNLOCATABLE:" + sha8`.
- Public replays guarantee consistency for two classes only: `locatable` (verbatim ∪ normalized) vs `not_locatable`. The four-valued position status and the quote-verification ablation exist only in the private full report; the public report lists the number of `lossy` quotes and keeps them out of those metrics' denominators.
- The private side compares, record by record, the `position_status`, `assertion_check`, exclusion reasons and decisions of the complete recording against the restored public version.
- `fixtures/synthetic/`: hand-written synthetic responses and failure fixtures for unit tests; not called recorded responses and never used in `eval`.

**Public outputs**: every public artifact (report, replay, CI artifact) goes through `export_public_run()`, which exports with an **allow-list of fields**; MTSamples free-text fields (`description`, `indication`, `section_title`, quotes) are always externalized as offset + hash or omitted; reports cite evidence only as `doc_id[start:end] sha8`. Test `test_public_outputs_contain_no_mtsamples_text`: cut the 6 documents into 40-character sliding windows and scan `reports/`, `replays/`, `cases/**/expected.json` and failure outputs; additionally plant a unique long string and confirm no public artifact contains it. pytest assertion messages use `evidence_id`, never a quote.
