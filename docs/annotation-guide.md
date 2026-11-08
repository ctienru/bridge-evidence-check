# Annotation guide

Status: DRAFT by the coding agent. A clause counts only after Terri marks it `Reviewed: yes`.

Guideline version: 0 (draft). Machine-level names (condition IDs, status codes, enums, gold format) are defined in [`contracts.md`](./contracts.md); when this guide and the contract disagree, the contract wins and this guide is corrected.

This guide is followed by everyone who writes gold: the human annotator and the candidate-proposing model (a non-Claude model). The extractor (Claude) does not read it and its output never enters gold.

Clause IDs: `P` principles, `S` statuses, `A` assertion, `T` timepoints, `C` per-condition rules, `K` claims, `G` clinical judgement, `W` keyword scan and cue words, `B` blind draft, `L` adjudication log, `U` uncertainty reasons, `R` reliability checks and guide revision. Every clause ends with a `Reviewed:` marker. Clinical judgement clauses (`G-xx`) also carry a `Source:` line; gold facts decided by one of them record its ID in `guideline_clause`.

All examples in this guide are synthetic sentences written for the guide. None is quoted from MTSamples, from a published case report, or from any case document.

## 1. Scope and principles

- **P-01** Label only what the system can see: the text of the files under `cases/<variant_id>/docs/` plus `input.yaml`. Nothing in `case.yaml`, in the case story, or in the annotator's head produces a gold fact. If a fact is needed for a definite gold (for example "this measurement is the initiation baseline"), it must be written into a visible document marked `doc_origin: authored`. `Reviewed: no`
- **P-02** Extractor output never becomes gold. The candidate-proposing model is a different vendor's model, called through the API and recorded at snapshot-level model ID; its candidates are suggestions to verify, not gold. The same model drafts authored documents (route 1). Its snapshot-level model ID is recorded in `case.yaml` as `documents[].drafted_by` for every `doc_origin: authored` document, and in `adjudication.jsonl` (`drafted_by`, §10) for every candidate; a rewrite in the dirty ladder records the rewriting model the same way in that level's `case.yaml`. `Reviewed: no`
- **P-03** One human makes the final judgement on every scored gold fact and every condition status (`review: human_verified`). There is no "two models agree" shortcut and no sampling-based sign-off. `Reviewed: no`
- **P-04** Gold is produced by two routes (contract §8, §9). Route 1, authored documents: a spec (`case.yaml` fact list) is written first; a non-Claude model drafts the documents and returns a fact_id → verbatim quote map; deterministic checks confirm every quote exists verbatim, the value is inside the quote, the assertion cue is in the quote's sentence, and the requested dirty wording appears; Terri reads the final documents and checks both directions (every spec fact is written; no clinical fact beyond the spec). Route 2, real text: Terri blind-labels statuses and inventories facts first (§9), one non-Claude model proposes candidates with quote locations, a deterministic keyword scan (§8) lists uncovered hits, and Terri verifies every scored fact one by one. `Reviewed: no`
- **P-05** Gold is frozen before the pipeline first touches the case (rolling freeze). Later corrections bump `gold_version` and are written to `changes` with date and reason; gold is never silently changed to match model output. `Reviewed: no`
- **P-06** A fact is labelled where it is written. The same fact repeated in two documents is two gold facts (one per `doc_id`); the same fact repeated in one document is one gold fact unless the repetitions describe different events. `Reviewed: no`
- **P-07** Gold for MTSamples documents stores `start`, `end` and `quote_sha256` only, never the quote text. The same rule applies to `blind_draft.json` and `adjudication.jsonl`: refer to text by `doc_id`, offsets and hash, not by copying it. `Reviewed: no`
- **P-08** Condition statuses in gold are decided by the annotator from the facts, by hand, without running the production rule engine. A disagreement between the blind status and the status implied by the facts is investigated and its cause recorded (§10). `Reviewed: no`
- **P-09** Expected absence (`expected_absent[]`) is asserted only after both the inventory (§9) and the keyword scan (§8) have been checked for that field; "the model did not list it" is never enough. `Reviewed: no`
- **P-10** The annotator's clinical background (pharmacy, nutrition; not a physician) is disclosed in the report. Clinical judgement clauses (§7) exist so that such judgements are explicit, sourced and countable, not so that they are presumed correct. `Reviewed: no`

## 2. Statuses

The five codes are defined in contract §1. This section says when an annotator picks each one. One synthetic example each; the status is for the named condition only.

- **S-01** `supported`: at least one verifiable quote from the right patient, with assertion present / patient and the required timepoint, establishes the condition. Example: "Weight 128 kg, height 170 cm, BMI 44.3 at the start of semaglutide on 2025-03-15." → `bmi_path_a` `supported`. `Reviewed: no`
- **S-02** `not_supported`: positive counter-evidence or evidence of absence. Negation of the concept, an explicitly complete list that lacks the required item, or a value below the threshold. Example: "Denies diabetes or prediabetes; A1c 5.2% last month." → `bmi_path_c.prediabetes` `not_supported`. `Reviewed: no`
- **S-03** `insufficient`: nothing is said, or what is said cannot carry a conclusion either way (wrong timepoint, no diagnosis behind a lab, only advice given, payer unknown). Example: "Patient was encouraged to eat more vegetables." → `lifestyle.nutrition` `insufficient`. `Reviewed: no`
- **S-04** `conflict`: two verified values for the same fact (contract §4) sit on opposite sides of the threshold the condition uses, or a diagnosis is both asserted and negated at the same timepoint. Example: a clinic note "BMI 29.6 at initiation" and the referral letter "BMI 30.4 when Wegovy was started" → `bmi_path_b.bmi` `conflict`; `bmi_path_c.bmi` is not in conflict (both values ≥ 27). `Reviewed: no`
- **S-05** `review`: evidence exists and a human must judge it: positive exclusion evidence, an uncertain diagnosis, a policy grey zone, an imprecise source, a table, a combination pill, an unrecognized wording. Example: "Sleep study years ago showed OSA; has not used CPAP since tonsillectomy." → `exclusion.osa` `review` (severity unspecified, post-surgical status unknown). `Reviewed: no`
- **S-06** Never invent a sixth status, and never encode "needs a look" as `insufficient` to lower the review count: the human-workload metric counts `review` + `conflict` + `insufficient` together, so the choice must follow the definitions above, not the count. `Reviewed: no`
- **S-07** The condition `reason` field is a short English sentence that names the deciding evidence by `doc_id` and, for MTSamples documents, offsets or `sha8`; it never pastes the quote. `Reviewed: no`

## 3. Assertion: three axes

Every fact carries `certainty`, `subject` and `temporality` (contract §6). The axes are labelled independently and may combine freely (for example uncertain + family + historical).

### 3.1 Definitions

- **A-01** `certainty`: `present` — the text asserts the fact; `negated` — the text denies it; `uncertain` — the text proposes, suspects, questions, or leaves it pending. `Reviewed: no`
- **A-02** `subject`: `patient` — the person the document is about; `family` — a relative; `other` — anyone else (a spouse, a donor, a population statement). `Reviewed: no`
- **A-03** `temporality`: `current` — holds at the time the sentence describes; `historical` — happened in the past and the text does not say it has ended ("history of", "prior", "s/p"); `resolved` — the text itself says it has ended, remitted or been cured; `hypothetical` — mentioned as a risk, a possibility, a condition, or a counselling point, not as something the patient has. `Reviewed: no`
- **A-04** Treated is not resolved. "s/p", "post", "after surgery", "on CPAP", "controlled on medication" describe treatment and keep `temporality` at `current` or `historical`; only an explicit statement of remission, resolution or cure earns `resolved`. `Reviewed: no`
- **A-05** Default values are present / patient / current. A mention outside the scope of every cue takes the defaults. The annotator does not infer a non-default value from world knowledge; a non-default value needs a cue in the sentence. `Reviewed: no`

### 3.2 Cue words per axis

Draft list; the deterministic `check_assertion` uses a frozen copy of this table, so additions here are additions to the verifier (contract §6).

| Axis | Value | Cue words and patterns (draft) |
|---|---|---|
| certainty | `negated` | no, not, denies, denied, denying, negative for, without, free of, absent, none, never had, ruled out, r/o'd, excluded |
| certainty | `uncertain` | r/o, rule out, possible, possibly, probable, probably, likely, suspected, suspicion of, questionable, ?, vs, versus, differential includes, consider, cannot exclude, pending, to be evaluated, working diagnosis |
| subject | `family` | mother, father, mom, dad, brother, sister, sibling, son, daughter, aunt, uncle, grandmother, grandfather, maternal, paternal, family history, FH, FHx, runs in the family |
| subject | `other` | wife, husband, spouse, partner, donor, roommate, patients with (population statement) |
| temporality | `historical` | history of, hx, h/o, hx of, prior, previous, previously, remote, in the past, years ago, s/p, status post, former |
| temporality | `resolved` | resolved, in remission, remission, cured, no longer has, no longer meets criteria, off all medication with normal values (only when the sentence says the condition itself ended) |
| temporality | `hypothetical` | risk of, at risk for, if, should she develop, may develop, could, counseled regarding, risks include, complications include, in the event of, would |

- **A-06** A cue acts only inside its scope: to its right, until the next scope terminator. Terminators: `but`, `however`, `except`, `;`, the end of the sentence, and a list-item boundary (a line break that starts a new bullet, number or table row). Candidate terminators not yet adopted: `although`, `whereas`, `while`, `:`. `Reviewed: no`
- **A-07** A cue to the left of the mention within the same scope applies; a cue to the right ("… was ruled out") applies only when the pattern is in the table as a right-hand pattern (`ruled out`, `excluded`, `resolved`, `in remission`, `pending`). When the annotator cannot tell whether a cue reaches the mention, the fact is labelled with the defaults and the condition is `review` with reason `unrecognized`. `Reviewed: no`
- **A-08** `?` counts as `uncertain` only when attached to a concept ("?HFpEF", "HFpEF?"); a question mark ending a question sentence is not a cue. `Reviewed: no`
- **A-09** Negation of a treatment is not negation of the condition. "Not on insulin" leaves diabetes unlabelled; "no CPAP" leaves OSA unlabelled. `Reviewed: no`
- **A-10** Family cue scope: "Family history: mother with diabetes, father with stroke; patient denies either" → diabetes: family; stroke: family; both are also negated for the patient after the `;` terminator, as separate facts with subject `patient`. `Reviewed: no`

### 3.3 Minimal pairs

| Text (synthetic) | certainty | subject | temporality | Note |
|---|---|---|---|---|
| r/o HFpEF | uncertain | patient | current | `bmi_path_b.hfpef` → `review` |
| HFpEF ruled out | negated | patient | current | `bmi_path_b.hfpef` → `not_supported` |
| HFpEF | present | patient | current | `bmi_path_b.hfpef` → `supported` |
| Mother had suspected HFpEF | uncertain | family | historical | not patient evidence; `expected_absent` is still wrong because the mention exists — label it with subject `family` |
| OSA s/p surgery | present | patient | historical | treated ≠ resolved; `osa_severity: unspecified`; `exclusion.osa` → `review` |
| OSA, resolved after surgery per repeat sleep study | present | patient | resolved | still `exclusion.osa` → `review` (contract §3.3 step 4) |
| Denies diabetes | negated | patient | current | `exclusion.t2dm` → `not_supported` |
| T2DM, in remission after bariatric surgery | present | patient | resolved | `exclusion.t2dm` → `review` |
| History of MI in 2019 | present | patient | historical | `bmi_path_c.mi` → `supported` |
| Surgical risks discussed, including MI and stroke | present | patient | hypothetical | `bmi_path_c.mi`, `.stroke` → `insufficient` |
| No history of stroke, but TIA last year | negated (stroke) / present (TIA, concept `other`) | patient | historical | `bmi_path_c.stroke` → `not_supported`; TIA is not stroke (G-06) |
| Possible prediabetes, A1c pending | uncertain | patient | current | `bmi_path_c.prediabetes` → `review` |

- **A-11** The rows above are the reference set for the "common-sense completion" risk: a treated condition, a suspected condition and a relative's condition each get their own three-axis label; none of them becomes `present / patient / current` by inference. `Reviewed: no`

## 4. Timepoints

- **T-01** `relative_to_glp1_initiation` ∈ `at` / `before` / `after` / `unknown` is labelled on every fact. The annotator labels what the text supports; the program recomputes it from dates (`relative_computed`) and scoring uses the program's value, so a gold date must be right before a gold timepoint matters (contract §5). `Reviewed: no`
- **T-02** `at`: the fact's date interval is the single day of the initiation date, or the quote itself names the fact as the initiation baseline ("at initiation", "baseline", "before starting <drug>" in the sense of the pre-treatment measurement). Any other undated fact is `unknown`, not `at`. `Reviewed: no`
- **T-03** `before` / `after`: the fact's whole date interval lies before / after the initiation date. A month-precision date in the same month as initiation overlaps and is `unknown`. `Reviewed: no`
- **T-04** `event_date` is written at the precision the text gives: `2024-01-15` (`day`), `2024-01` (`month`), `2024` (`year`). Never complete a month to its first day. A date the text does not contain is `null`; the timepoint is then `unknown` unless the quote itself carries the explicit baseline wording of T-02, in which case it is `at` with `event_date: null`. `Reviewed: no`
- **T-05** `doc_dates[]`: an undated main document (MTSamples) gets its date only from a sentence in another visible document that states it ("the attached consult note from 2025-03-14"). That sentence is a gold fact of field `doc_dates` with `target_doc_id` and `date`; facts in the target document then take that date. Without such a sentence, the target document's facts stay `unknown`, except facts whose own quote carries the explicit baseline wording of T-02 (those are `at` without a date). `Reviewed: no`
- **T-06** A BMI `at` label on an undated document therefore needs either explicit baseline wording inside the BMI quote (T-02), or two gold facts: the anthropometric fact and the `doc_dates` fact that dates the document to the initiation day. `Reviewed: no`
- **T-07** `assessment_date` (in `input.yaml`) is the reference date for "current and ongoing" (lifestyle) and for nothing else; it is never the run date and never the initiation date. `Reviewed: no`
- **T-08** The initiation date itself is a gold fact (`glp1_start`) and must be found in the visible text; `target_course` in `input.yaml` only says which course is assessed. If the text does not contain it, every BMI sub-result is `insufficient` regardless of what the annotator knows. `Reviewed: no`
- **T-09** Medication periods: `start`, `end` and `end_kind` are labelled at the text's precision. An undated list labelled as current medications in the same document as a BP reading is in use on that document's date (`same_note_list`). Whether the list is explicitly complete (`medication_lists[].complete`) is labelled from wording such as "complete medication list" or "no other medications"; a section header alone is not completeness. `Reviewed: no`
- **T-10** Exclusion evidence after initiation is still labelled and still counts (`post_initiation_exclusion` → `review`); the "after initiation is not used" rule applies to BMI and pathway facts only. `Reviewed: no`

## 5. Per-condition labelling rules

Each subsection points to the decision table in the contract and lists the traps that most often produce a wrong label (drawn from the review checklist). Facts are labelled first; the condition status follows from the facts and the contract table.

### 5.1 `age_18` (contract §3.5)

- **C-01** Label `dob` and `stated_age` from `patient_identity[]` with the document date; a stated age is an interval `[a, a+1)` on that day. Trap: taking an age stated years after initiation as the age at initiation without the interval shift. `Reviewed: no`

### 5.2 `bmi_path_a` and `*.bmi` (contract §3.1)

- **C-02** Label every height, weight and stated BMI as an `anthropometrics` fact with `raw_value`, `raw_unit` and `norm_value` (`cm`, `kg`, `kg/m2`). Units are normalized in `norm_value` only; `raw_*` keep the text. Traps: lb read as kg, in as cm; a current BMI used as the initiation BMI; a measurement before bariatric surgery used as the initiation value; any pre-initiation measurement treated as `at`. `Reviewed: no`
- **C-03** A pediatric expression (a percentage of a percentile, a z-score) is `kind: bmi_percentile` and never a kg/m² value. `Reviewed: no`
- **C-04** Two BMI values in one document are two facts; if they straddle a threshold the sub-result using that threshold is `conflict`, otherwise the status is decided as usual with `inconsistent_values`. Never keep only one of them. `Reviewed: no`
- **C-05** An integer stated BMI with no height and weight whose rounding could cross the threshold (contract §3.1 step 6) gives `review` + `imprecise_source`; two candidates both clearly above the threshold give `supported`, not `insufficient`. `Reviewed: no`
- **C-06** Without a verified initiation date no BMI sub-result and no pathway is `supported`; this is an invariant, not a judgement. `Reviewed: no`

### 5.3 `bmi_path_b.htn` (contract §3.2)

- **C-07** Label each BP reading (`sbp`, `dbp`) with its date; label each medication with `name`, `dose`, `indication` if stated, `start` / `end` / `end_kind`, `list_id`; label each list's `complete`. Traps: exactly 140 or 90 read as "greater than"; a "controlled" statement overriding an above-threshold reading; one antihypertensive seen and the list assumed to be the whole list; a drug with another plausible indication (an alpha-blocker for urinary symptoms, a diuretic for heart failure) counted as an antihypertensive without the `class_ambiguous` route; a combination pill counted as two drugs without `combination_pill`; narrative "on medication" with no list entry, or a list entry with no narrative, not recorded as separate facts; a diagnosis word alone ("HTN") taken as uncontrolled hypertension. `Reviewed: no`

### 5.4 `bmi_path_b.hfpef` (contract §3.2)

- **C-08** Only an explicit diagnosis concept `hfpef` is labelled as such; "diastolic dysfunction", "preserved EF", "EF 60%" are findings and are not `hfpef` facts (G-07). Traps: r/o HFpEF labelled present; a relative's HFpEF labelled subject `patient`. `Reviewed: no`

### 5.5 `bmi_path_b.ckd` (contract §3.2)

- **C-09** Label the diagnosis with `ckd_stage` when written; label each eGFR as a `labs` fact with its date. Traps: a stage inferred from eGFR by the annotator (G-09); "CKD 2" matched as CKD 3a; a transient eGFR drop during an acute illness read as a stage. `Reviewed: no`

### 5.6 `bmi_path_c.prediabetes` (contract §3.2)

- **C-10** Label the diagnosis and every A1c and fasting glucose separately. Traps: a lab in the prediabetes range labelled as a diagnosis (G-08); metformin or an SGLT2 inhibitor read as diabetes (G-02); A1c below the range labelled as negation of prediabetes; unusual units (g/L) converted at extraction instead of kept raw and normalized separately. `Reviewed: no`

### 5.7 `bmi_path_c.mi`, `.stroke` (contract §3.2)

- **C-11** Label every infarction or stroke mention as `concept: mi` / `stroke` with its three axes; a relative's MI or stroke is a gold fact with `subject: family` and never supports the patient's condition (the status is decided from `subject: patient` facts only). Traps: a family-history MI dropped instead of labelled `family`, or labelled `patient`; "ischemic heart disease", "CAD", "angina", "demand ischemia", "troponin elevation" labelled as `mi` (G-01); TIA labelled as `stroke` (G-06); a disease mentioned in a surgical-risk discussion labelled `current` instead of `hypothetical`; "no hx of stroke" labelled present. `Reviewed: no`

### 5.8 `bmi_path_c.pad` (contract §3.2)

- **C-12** Label `symptomatic` from the text: `yes` with claudication, rest pain or ulceration stated; `no` when asymptomatic is stated; `unknown` otherwise. Trap: a reduced ankle-brachial index alone labelled as PAD with `symptomatic: yes`. `Reviewed: no`

### 5.9 `exclusion.t2dm` (contract §3.3)

- **C-13** Label every mention, including negated, resolved and uncertain ones. Traps: a drug implying the diagnosis (G-02); "insulin-dependent" read as type 1 or type 2 (G-04); "T2DM, in remission" labelled as absent or as current; an A1c ≥ 6.5% without a diagnosis labelled as T2DM (G-08). `Reviewed: no`

### 5.10 `exclusion.osa` (contract §3.3)

- **C-14** Label `osa_severity` (`mild` / `moderate` / `severe` / `unspecified`) and `ahi` when written. Traps: "on CPAP" read as moderate-to-severe; "s/p tonsillectomy" read as resolved (A-04); "mild" or AHI < 15 not labelled, so the `not_supported` row is missed. `Reviewed: no`

### 5.11 `exclusion.mash` (contract §3.3)

- **C-15** Label `concept: mash` only when MASH (or NASH) is written; label `fibrosis_stage` and `cirrhosis` when written, with the method noted in `reason`. Traps: fatty liver, steatosis, MASLD or raised ALT labelled as `mash` (G-03); a kPa value converted to a stage by the annotator (G-05); a biopsy SAF stage misread (G-05); F0–F1 or cirrhosis not labelled, so the `not_supported` row is missed. `Reviewed: no`

### 5.12 `exclusion.part_d_glp1` (contract §3.3)

- **C-16** Label every prior GLP-1 mention as `prior_glp1` with `drug`, `date`, `payer`, `compounded`. `payer` is `bridge` only when the text names Bridge; an amount alone is `unknown`. Traps: any prior GLP-1 use labelled as Part D; a 2025 fill or a Medicaid fill labelled as a 2026 Part D fill; "not found" turned into `not_supported` (it is `insufficient`). `Reviewed: no`

### 5.13 `patient_identity` (contract §3.5)

- **C-17** Label `patient_id`, `dob` and `name` per document as written. Status compares IDs; date of birth only when a document has no ID; names never (a changed surname is not a mismatch). Trap: using a document before checking its identifiers. `Reviewed: no`

### 5.14 `lifestyle.nutrition`, `.activity` (contract §3.5)

- **C-18** Label `program_type`, `attendance`, `start` / `end` / `end_kind`, `limitation`. Traps: advice or a pending referral labelled as a program; a declined single dietitian visit labelled as "no diet plan at all"; a commercial program labelled `structured_clinical`; a program that starts after `assessment_date` counted as current. `Reviewed: no`

### 5.15 Pathways `bmi_path_a`, `bmi_path_b`, `bmi_path_c` and downgrades (contract §3.4)

- **C-19** The pathway status is derived by hand from its sub-results with the contract §3.4 table: all comorbidities `not_supported` → `not_supported`; BMI `not_supported` → `not_supported`; BMI `insufficient` / `conflict` / `review` → the pathway equals the BMI sub-result; BMI `supported` with any comorbidity `supported` → `supported`, otherwise the highest-ranked comorbidity (`conflict` > `review` > `insufficient`). Pathway A equals the BMI ≥ 35 sub-result. Sub-results keep their own status whatever the pathway. `Reviewed: no`
- **C-20** `mace_purpose` is a case flag, not a status: label it in `case_flags` only when a verified, non-excluded `glp1_start` fact for the primary patient that refers to the course named in `target_course` has `purpose: mace` (the text states that this course is for cardiovascular risk reduction). A `mace` purpose on another course, on a prior GLP-1, or in an excluded document (wrong patient, PA draft) does not set the flag. With the flag set, every pathway that would be `supported` is `review`; the sub-results stay as they are. `Reviewed: no`
- **C-21** Pathway C established only through `mi` / `stroke` / `pad` with `prediabetes` not `supported` is `review` with flag `cv_history_only`; the sub-results stay `supported`. Pathway flags are part of gold and are matched, so the annotator writes them. `Reviewed: no`
- **C-22** Without a verified initiation date the BMI sub-result is `insufficient` and aggregation still runs (all comorbidities `not_supported` still gives `not_supported`). `Reviewed: no`

## 6. PA draft claims

- **K-01** The PA draft (`role: pa_draft`) is labelled only as `pa_form_claims[]` (`claim_id`, `claimed_value`). No clinical fact is ever labelled from it; a checked box is a claim, not evidence (`exclusion_reasons: claim_document`). `Reviewed: no`
- **K-02** `claim_id` follows the condition it is checked against: `claim.age_18`, `claim.drug`, `claim.bmi_bracket`, `claim.bmi_path_b.hfpef`, `claim.exclusion.t2dm`, and so on (contract §2). `claimed_value` is the box or bracket as written (`yes`, `no`, `30-34.9`, a drug name). `Reviewed: no`
- **K-03** Claim status in gold `claims[]`: the chart supports the claimed value → `supported`; the chart says nothing → `insufficient`; the chart contradicts it → `conflict`; the chart mentions it only as suspected or with unclear status → `review`. A claim never changes the condition's own status. `Reviewed: no`
- **K-04** `claim.bmi_bracket` is compared against the bracket chosen from the unrounded initiation BMI (`[27,30)`, `[30,35)`, `[35,40)`, `≥40`); a stated BMI of 29.95 is in `[27,30)`. `Reviewed: no`

## 7. Clinical judgement clauses

Each clause names a public source. `Source: TODO(terri)` means the planning documents name no source; Terri fills it in before the clause is reviewed. A gold fact decided by a clause records the clause ID in `guideline_clause`. The report counts facts decided by these clauses and states that no physician reviewed them.

### G-01 Ischemic heart disease is not prior MI

Coronary artery disease, ischemic heart disease, angina, demand ischemia, a positive stress test or an isolated troponin rise are not labelled `concept: mi`. Only an infarction stated as such (MI, myocardial infarction, heart attack, STEMI, NSTEMI) is `mi`.

- Source: TODO(terri)
- Reviewed: no

### G-02 SGLT2 inhibitors, metformin and GLP-1 agonists do not imply diabetes

A medication is labelled as a medication. Metformin (possible PCOS or prediabetes use), SGLT2 inhibitors (possible heart failure or CKD use) and GLP-1 agonists (possible weight indication) never produce a `t2dm` or `prediabetes` diagnosis fact. A diagnosis needs a diagnosis statement.

- Source: TODO(terri) (project policy; see `docs/adr/0001-project-policies.md`, to be added)
- Reviewed: no

### G-03 Hepatic steatosis is not MASH

Fatty liver, hepatic steatosis, MASLD / NAFLD, or an elevated ALT is not labelled `concept: mash`. `mash` requires the text to state MASH (or NASH, steatohepatitis). Fibrosis stage is labelled only when written.

- Source: AASLD practice guidance on MASLD (edition TODO(terri))
- Reviewed: no

### G-04 Insulin-dependent is not type 1

"Insulin-dependent diabetes", "on insulin" or "IDDM" does not fix the diabetes type. Label `concept: t2dm` only when type 2 is stated; label other or unspecified diabetes as `concept: other` with the wording noted in `reason`, and set `exclusion.t2dm` to `review`.

- Source: ADA Standards of Care, classification of diabetes (edition TODO(terri))
- Reviewed: no

### G-05 Reading fibrosis staging (SAF, METAVIR, elastography)

Record the stage exactly as the text writes it (F0–F4; SAF activity and fibrosis components are separate numbers, and only the fibrosis component is `fibrosis_stage`). Never derive a stage from a kPa value, a FIB-4 or a NAFLD fibrosis score; a stiffness value without a written stage leaves `fibrosis_stage` null. Cirrhosis is `cirrhosis: true` only when written.

- Source: AASLD practice guidance on MASLD (edition TODO(terri)); SAF scoring reference TODO(terri)
- Reviewed: no

### G-06 TIA is not stroke

A transient ischemic attack is labelled `concept: other` with the wording noted; it never produces a `stroke` fact and never supports `bmi_path_c.stroke`.

- Source: TODO(terri)
- Reviewed: no

### G-07 A diastolic dysfunction finding is not an HFpEF diagnosis

Echocardiographic findings (diastolic dysfunction grade, preserved or normal ejection fraction, a stated EF percentage, elevated filling pressures) are not labelled `concept: hfpef`. `hfpef` requires a heart-failure diagnosis with preserved ejection fraction stated as a diagnosis (HFpEF, diastolic heart failure, heart failure with preserved EF).

- Source: TODO(terri)
- Reviewed: no

### G-08 Lab values in the prediabetes or diabetes range are labs, not diagnoses

An A1c of 5.7–6.4% or a fasting glucose of 100–125 mg/dL without a diagnosis statement is a `labs` fact and sends `bmi_path_c.prediabetes` to `review`; an A1c ≥ 6.5% or a fasting glucose ≥ 126 mg/dL without a diagnosis is a `labs` fact and sends `exclusion.t2dm` to `review`. The annotator never writes a diagnosis fact from the number.

- Source: ADA Standards of Care, diagnostic criteria (edition TODO(terri)); CMS GLP-1 Bridge FAQ for "prediabetes per ADA"
- Reviewed: no

### G-09 CKD stage is read, not computed

`ckd_stage` is labelled only when the text writes a stage (3a, 3b, "stage 3", …). An eGFR value is a `labs` fact; the annotator does not assign a stage from it. With a CKD diagnosis and eGFR values only, `bmi_path_b.ckd` is `review` and the reason lists every eGFR with its date.

- Source: KDIGO CKD guideline, GFR categories (edition TODO(terri))
- Reviewed: no

### G-10 OSA severity is read, not inferred

`osa_severity` is `moderate` / `severe` when the text writes it or when an AHI ≥ 15 is written; `mild` when written or AHI < 15; otherwise `unspecified`. CPAP use, a sleep study without a result, or a referral does not set severity.

- Source: AASM scoring manual / clinical guideline for OSA severity by AHI (edition TODO(terri))
- Reviewed: no

### G-11 Treated, controlled or operated is not resolved

CMS asks the prescriber to distinguish "no longer applies" from "well controlled". The annotator makes no such distinction: a treated or controlled exclusion diagnosis is labelled `present` and the exclusion is `review`; only a textual statement of remission or resolution is `resolved`, and the exclusion is still `review`.

- Source: CMS Medicare GLP-1 Bridge provider FAQ / prescriber instructions (URL TODO(terri))
- Reviewed: no

### G-12 Payer is read from the text

`payer` is `part_d` only when Part D (or a Part D plan name) is written; `medicaid`, `self_pay`, `commercial` likewise; `bridge` only when Bridge is written. A copay amount alone is `unknown`.

- Source: CMS, Information for Part D plans (Medicare GLP-1 Bridge) (URL TODO(terri))
- Reviewed: no

### G-13 MASH outside F2–F3 is not this exclusion

MASH with a written stage F0–F1, or MASH with cirrhosis (F4) written, is labelled with `fibrosis_stage` / `cirrhosis` as written and `exclusion.mash` is `not_supported` with the reason stating the stage. The gold still contains the `mash` fact.

- Source: CMS GLP-1 Bridge PA form, Q3 wording ("non-cirrhotic MASH with moderate to advanced fibrosis") (URL TODO(terri))
- Reviewed: no

## 8. Keyword scan and cue words

The keyword scan is deterministic (no LLM). Every sentence containing a term below that is not covered by any candidate quote is listed as an uncovered hit and must be verified by the annotator (§1 P-04).

- **W-01** Scan terms (draft; case-insensitive, word-boundary where meaningful). From the planning documents: diabetes, A1c, OSA, CPAP, steatosis, MASH, fibrosis, BMI, kg, lb, mmHg, semaglutide, Wegovy, tirzepatide, Part D, Medicaid, dietitian, exercise. Proposed additions: DM, T2DM, prediabetes, HbA1c, glucose, metformin, insulin, HFpEF, heart failure, ejection fraction, EF, CKD, eGFR, creatinine, MI, infarction, stroke, CVA, TIA, PAD, claudication, hypertension, HTN, BP, blood pressure, apnea, AHI, sleep study, NASH, steatohepatitis, biopsy, FibroScan, kPa, cirrhosis, height, weight, lbs, cm, inches, Zepbound, Ozempic, Mounjaro, Saxenda, liraglutide, Foundayo, GLP-1, Bridge, copay, nutrition, diet, Noom, Weight Watchers, walking, gym, physical therapy, DOB, MRN. `Reviewed: no`
- **W-02** The cue-word table in §3.2 is the single cue list; the verifier's `check_assertion` and the keyword scan both load it from the frozen copy that ships with the code, and a change here is a guideline version bump. `Reviewed: no`
- **W-03** A scan hit is recorded in `adjudication.jsonl` by `doc_id`, `start`, `end` and `sha8` of the sentence, never by its text. `Reviewed: no`

## 9. Blind draft and inventory table

Written before any AI output is seen; saved as `cases/<variant_id>/blind_draft.json` and never edited afterwards (contract §8). Corrections go in gold `changes`.

- **B-01** `conditions`: one entry per top-level condition and sub-result ID of contract §2 with `id` and `status`. `Reviewed: no`
- **B-02** `inventory`: one row per extraction field in the inventory list (BMI / height / weight, GLP-1 drug and date, payer, T2DM, OSA, MASH / fibrosis, prediabetes, HFpEF, CKD, BP, antihypertensives, MI / stroke / PAD, nutrition, activity, age, identity) with `field`, `kind` or `concept`, `presence` ∈ `present` / `absent` / `unsure`, and `location` (a `doc_id` plus a section name or approximate offset; no quoted text). Contradictory values and discontinuation information are noted in `notes` by location. `Reviewed: no`
- **B-03** Format (draft field names):

```json
{
  "variant_id": "case-01",
  "drafted_at": "2026-11-20",
  "conditions": [
    {"id": "age_18", "status": "supported"},
    {"id": "bmi_path_b.htn", "status": "insufficient"}
  ],
  "inventory": [
    {"field": "anthropometrics", "kind": "bmi", "presence": "present", "location": "D2-mtsamples-4985 / vitals paragraph"},
    {"field": "diagnoses", "concept": "mash", "presence": "absent", "location": null},
    {"field": "medications", "kind": "antihypertensive", "presence": "unsure", "location": "D1-referral / medication list"}
  ],
  "notes": ["two weights in D2, different paragraphs"]
}
```

`Reviewed: no`

- **B-04** The blind draft is compared with the final gold statuses in the report (agreement count per condition); a disagreement is written up in the adjudication log with its cause. `Reviewed: no`

## 10. Adjudication log

One line per adjudicated item in `cases/<variant_id>/adjudication.jsonl` (n2c2-style). Lines are appended, never rewritten.

- **L-01** Fields (draft): `variant_id`; `item` (`fact` or `condition`); `field` and `kind` / `concept`, or `condition_id`; `candidate` — the proposing model's candidate as an object (`doc_id`, `start`, `end`, `sha8`, `norm_value`, the three axes, `event_date`) or `null` when none; `scan_hit` — the uncovered keyword hit as (`doc_id`, `start`, `end`, `sha8`, `term`) or `null`; `inventory` — the blind-draft presence for this field or `null`; `decision` ∈ `accept` / `modify` / `reject` / `add` / `absent`; `final` — the gold entry as written, or `null`; `guideline_clause` — the clause ID relied on (`G-xx`, or `A-xx` / `T-xx` for assertion and timepoint decisions) or `null`; `guideline_version`; `drafted_by` — snapshot-level model ID of the candidate-proposing model, or `null` (for authored documents the drafting model is recorded in `case.yaml` `documents[].drafted_by`, P-02); `second_opinion` — model ID when a different vendor's model was asked for a counter-view, or `null`; `decided_at`; `note` — free text with no document text. `Reviewed: no`
- **L-02** Every scored gold fact has at least one adjudication line, whatever its `origin` (`spec`, `model_candidate`, `keyword_scan`, `human_inventory`); every `expected_absent` entry has a line with `decision: absent` and the inventory and scan results it rests on. `Reviewed: no`
- **L-03** A second-opinion model's answer is reference only and never a decision; the line records that it was asked and what was decided, not its text. `Reviewed: no`

## 11. Writing uncertainty reasons

The `reason` field of a `review`, `conflict` or `insufficient` condition tells the reviewer what to look at.

- **U-01** One sentence, English, in the form "<what is missing or unclear>; see <doc_id>[start:end] sha8". Name the policy or clause when one applies (`G-xx`, `boundary_value`, `imprecise_source`). `Reviewed: no`
- **U-02** For `conflict`, name both values with their `doc_id` locations and the threshold they straddle. `Reviewed: no`
- **U-03** For `review` on an exclusion, state the three-axis label and what a human has to decide (severity, stage, current status, payer year). `Reviewed: no`
- **U-04** For `insufficient`, say which kind of evidence would have been needed (a dated measurement at initiation, a diagnosis statement, a payer). Do not write "not mentioned" alone when something related was mentioned. `Reviewed: no`
- **U-05** Never paste document text into `reason`; never name the patient; never include MTSamples offsets in public reports except in the `doc_id[start:end] sha8` form. `Reviewed: no`

## 12. Reliability checks and guide revision

- **R-01** Revision cadence: after the 2 smoke-test cases are labelled, the guide is revised once before the remaining cases; later revisions are batched. Every revision bumps the guideline version and lists (a) the clauses changed and (b) the frozen gold items that could be affected; only those items are re-examined, and any change to them is written to that gold's `changes` with the clause ID. `Reviewed: no`
- **R-02** Self-retest: two real-text dev cases are relabelled about a week after the first pass, with the earlier labels and the candidates hidden. The report gives, per case, agreeing conditions / total conditions, plus the differences in three-axis labels, timepoints and missed evidence. Agreement is not correctness and is reported as agreement. `Reviewed: no`
- **R-03** Independent blind set: 3–5 cases are chosen and labelled by a colleague following this guide, unseen by Terri until evaluation; for 1–2 of them both annotators label conditions and facts independently before seeing any output, both sets are saved before adjudication, and condition-level agreement is reported separately. This checks whether the guide is clear; it is not a full inter-annotator agreement study and is not described as one. `Reviewed: no`
- **R-04** Optional seeded errors: 5–8 known-wrong candidates (fixed seed) are mixed into the verification queue and revealed afterwards; the report states how many were caught. `Reviewed: no`
- **R-05** Disclosure: the report lists the share of gold by `origin`, the number of facts found only by human inventory, the number decided by `G-xx` clauses, and that no physician reviewed the clinical judgement clauses. `Reviewed: no`
