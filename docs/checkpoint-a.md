# Checkpoint A: first real-extractor run over the dev set

Date 2026-11-09. Extractor `claude-sonnet-5-5` (returned `claude-sonnet-5-5` on every call),
prompt `extract-v2`, schema `v2`, rules `bridge-v1`, splitter `sentences-v1`, code `f0bb792`.
Dev variants from `splits.yaml`: case-01, 02, 03, 04, 07, 07b, 17.

**One run of one model on seven dev cases; not a holdout result; not an evaluation yet.**

No document text, quote or patient name appears on this page. Evidence is cited as
`doc_id[start:end] sha8`. The per-case comparison files are `reports/checkpoint-a/<variant>.json`
and `reports/checkpoint-a/compare.md`; the regression baseline is `reports/baseline-dev.json`;
the recorded extractions are `replays/<variant>/<input_hash>-extract-v2-v2.json`.

## Calls

One fresh database outside the checkout; each case checked twice. Prices $2.00 / $10.00
per million input / output tokens (ADR 0001).

| Case | Input tokens | Output tokens | Latency | Cost | Attempts (pass 1) | Parse | Pass 2 | Evidence rows |
|---|---:|---:|---:|---:|---|---|---|---:|
| case-01 | 14 345 | 5 757 | 25.6 s | $0.0863 | 1 `parsed` | ok | cache hit, no attempt | 38 |
| case-02 | 12 598 | 3 644 | 18.1 s | $0.0616 | 1 `parsed` | ok | cache hit, no attempt | 27 |
| case-03 | 13 424 | 3 661 | 16.8 s | $0.0635 | 1 `parsed` | ok | cache hit, no attempt | 26 |
| case-04 | 12 819 | 5 101 | 22.4 s | $0.0766 | 1 `parsed` | ok | cache hit, no attempt | 37 |
| case-07 | 12 603 | 3 380 | 15.6 s | $0.0590 | 1 `parsed` | ok | cache hit, no attempt | 24 |
| case-07b | 12 722 | 4 239 | 19.6 s | $0.0678 | 1 `parsed` | ok | cache hit, no attempt | 31 |
| case-17 | 13 237 | 3 132 | 14.6 s | $0.0578 | 1 `parsed` | ok | cache hit, no attempt | 22 |
| **Total** | **91 748** | **28 914** | **132.7 s** | **$0.4726** | 7 calls, 0 retries | 7 of 7 | 7 of 7 | 205 |

Plus the opt-in live test on the synthetic smoke case (`pytest -m live`): 12 339 input and
2 411 output tokens, 11.1 s, $0.0488. **Spend for this checkpoint: $0.5214.** No run came
near a ceiling ($1.00 per run, $5.00 per eval). Mean latency per call 19.0 s; maximum 25.6 s.

Every quote the model returned was found verbatim in its document (205 of 205). Each replay,
restored from offsets and hashes and re-run offline through verify, compute and rules,
reproduces every decision of its live run (7 of 7 cases, 179 of 179 decisions).

## Conditions

Cells show the live status; a bold cell differs from gold and names the gold status.
`⚑` marks a matching row that also carries matching flags. Abbreviations: sup = supported,
not = not_supported, ins = insufficient, con = conflict, rev = review.

| Condition | case-01 | case-02 | case-03 | case-04 | case-07 | case-07b | case-17 |
|---|---|---|---|---|---|---|---|
| `age_18` | sup ⚑ | sup | sup | sup | sup | sup | sup |
| `patient_identity` | rev ⚑ | sup | rev ⚑ | sup | con | con | rev ⚑ |
| `bmi_path_a` | **ins** (gold sup) | **ins** (gold not) | **ins** (gold not) | **ins** (gold not) | ins | sup | ins |
| `bmi_path_b` | ins | **ins** (gold sup) | ins | **ins** (gold sup) | ins | ins | ins |
| `bmi_path_b.bmi` | **ins** (gold sup) | **ins** (gold sup) | **ins** (gold sup) | **ins** (gold sup) | ins | sup | ins |
| `bmi_path_b.hfpef` | ins | sup | ins | ins | ins | ins | ins |
| `bmi_path_b.htn` | ins | ins | ins | **ins** (gold sup) | not ⚑ | not ⚑ | ins |
| `bmi_path_b.ckd` | ins | ins | ins | ins | ins | ins | ins |
| `bmi_path_c` | ins | ins | ins | **ins** (gold sup) | ins | ins | ins |
| `bmi_path_c.bmi` | **ins** (gold sup) | **ins** (gold sup) | **ins** (gold sup) | **ins** (gold sup) | ins | sup | ins |
| `bmi_path_c.prediabetes` | ins | ins | ins | sup | ins | ins | ins |
| `bmi_path_c.mi` | ins | ins | ins | ins | ins | ins | sup |
| `bmi_path_c.stroke` | not | ins | ins | ins | ins | ins | ins |
| `bmi_path_c.pad` | ins | ins | ins | ins | ins | ins | ins |
| `exclusion.t2dm` | ins | ins | ins | ins | ins | ins | ins |
| `exclusion.osa` | ins | ins | rev | not | ins | ins | ins |
| `exclusion.mash` | ins | ins | ins | ins | ins | ins | ins |
| `exclusion.part_d_glp1` | ins | rev | ins | ins | ins | ins | ins |
| `lifestyle.nutrition` | **rev** (gold ins) | ins | ins | ins | ins | ins | ins |
| `lifestyle.activity` | ins | ins | ins | **not** (gold rev) | ins | ins | ins |
| **correct** | **16/20** | **16/20** | **17/20** | **13/20** | **20/20** | **20/20** | **20/20** |

## Claims

| Claim | case-01 | case-02 | case-03 | case-04 | case-07 | case-07b | case-17 |
|---|---|---|---|---|---|---|---|
| `claim.age_18` | sup | sup | sup | sup | sup | sup | sup |
| `claim.bmi_bracket` | **ins** (gold sup) | **ins** (gold sup) | **ins** (gold sup) | **ins** (gold sup) | ins | con | ins |
| `claim.bmi_path_b.hfpef` | ins | con | | | | | ins |
| `claim.bmi_path_b.htn` | | | **ins** (gold rev) | | con | con | ins |
| `claim.bmi_path_c.mi` | | | | | | | sup |
| `claim.bmi_path_c.stroke` | sup | | | | | | |
| `claim.drug` | **ins** (gold sup) | **ins** (gold sup) | **ins** (gold sup) | **ins** (gold sup) | sup | sup | **ins** (gold sup) |
| `claim.exclusion.osa` | | | rev | con | | | |
| `claim.exclusion.part_d_glp1` | ins | | | | | | |
| `claim.exclusion.t2dm` | ins | | | | | | |
| `claim.lifestyle.activity` | ins | | | | | | |
| `claim.lifestyle.nutrition` | **rev** (gold ins) | | ins | | ins | ins | |
| **correct** | **6/9** | **2/4** | **3/6** | **2/4** | **5/5** | **5/5** | **5/6** |

## Totals

| Measure | Count |
|---|---:|
| Conditions matching gold (status and flags) | 122 / 140 |
| Claims matching gold (status) | 28 / 39 |
| False supports (gold not `supported`, live `supported`), conditions | 0 (of 112 gold non-supported rows) |
| False supports, claims | 0 |
| Missed exclusions (gold `review`, live `insufficient` / `not_supported`) | 0 (of 2 gold `review` exclusion rows) |
| Live `supported` condition rows / gold `supported` rows | 15 / 28 |

The denominators are counted from the seven gold files: 20 conditions in each case, and
claims as listed in each `claims[]` (9, 4, 6, 4, 5, 5, 6). The six cases added with the dev
gold alone give 120 conditions.

Facts (contract §8 keys, one-to-one; a match whose evidence carries an exclusion reason is
not counted as matched):

| Case | Gold facts | Matched | Matched, excluded by verify | Wrong value (timing only) | Missed | False positives | Expected-absent correct |
|---|---:|---:|---:|---:|---:|---:|---:|
| case-01 | 31 | 4 | 0 | 23 (13) | 4 | 2 | 10 / 11 |
| case-02 | 19 | 11 | 2 | 6 (2) | 0 | 6 | 16 / 16 |
| case-03 | 23 | 14 | 2 | 7 (2) | 0 | 3 | 14 / 14 |
| case-04 | 29 | 13 | 2 | 14 (2) | 0 | 6 | 12 / 12 |
| case-07 | 18 | 12 | 5 | 1 (0) | 0 | 2 | 15 / 15 |
| case-07b | 22 | 16 | 5 | 1 (0) | 0 | 4 | 13 / 13 |
| case-17 | 16 | 10 | 3 | 3 (1) | 0 | 4 | 18 / 18 |
| **Total** | **158** | **80** | **19** | **55 (20)** | **4** | **27** | **98 / 99** |

"Timing only" means the only differing keys are the event date and the timepoint relative
to initiation, the extractor's own values for them were right, and compute derived the
difference. Most of the 19 "matched, excluded by verify" are identity facts on the PA draft
(`claim_document`, by design) and on the other patient's note in 07 and 07b
(`wrong_patient`, by design). Most false positives are document dates and identity facts
that gold does not inventory.

## Error classification

Each mismatching row is assigned the first upstream error (`scripts/compare_gold.py`): gold
question, then a dependent gold fact missed, a dependent fact with a wrong extracted value,
a dependent fact excluded by verify, a timing difference compute derived, otherwise rules.

| First upstream error | Conditions | Claims |
|---|---:|---:|
| `extraction_missed` | 0 | 0 |
| `extraction_wrong_value` | 17 | 11 |
| `verify_excluded` | 0 | 0 |
| `compute_timepoint` | 1 | 0 |
| `rules` | 0 | 0 |
| `gold_question` | 0 | 0 |

The gold questions found are fact-level and change no row (list below).

## Top ten misses

1. **GLP-1 start labelled `historical`** (case-01, 02, 03, 04, 17). The model marks the start
   sentence `historical` because it carries a past date; the guide says a date is not a cue
   (A-03, C-08) and gold says `current`. The verifier finds no historical cue in the sentence,
   flags it `unrecognized`, and compute does not anchor an initiation date on it (contract §5).
   With no initiation every BMI row is `insufficient` (C-22). Directly behind 24 of the 29
   mismatching rows: every pathway and BMI sub-result miss except `bmi_path_b.htn`, every
   `claim.drug` miss and every `claim.bmi_bracket` miss. In 07 and 07b the model said `current` and both cases match 20/20.
2. **Measurements and fills labelled `historical`** (case-04: six anthropometric facts and
   five BP readings; 07 and 07b: one BP reading each; case-02: three prior GLP-1 fills). Same
   A-03 cue question; in case-04 it would block the BMI and blood-pressure rows even with an
   initiation date. case-02's `exclusion.part_d_glp1` still matches gold.
3. **`bmi_path_b.htn`, case-04** (gold `supported`). No BP reading can be at initiation without
   one (item 1); the antihypertensive periods of the form "started on X, still on at Y" are not
   counted as certainly in use (known gap, contract §3.2).
4. **`lifestyle.activity`, case-04** (gold `review`, live `not_supported`). The record names a
   limitation and no program; `program_type` has no value for that, the model writes
   `none_stated`, and the rule reads it as "no program at all" (known gap, contract §6,
   guide C-18). Classified `compute_timepoint` by the first-difference rule (a timing-only
   difference on the fact); the decisive difference is the enum gap.
5. **`lifestyle.nutrition` and its claim, case-01** (gold `insufficient`, live `review`). The
   nutrition records differ from gold in `end_kind` and temporality, and the rule reads one as
   a commercial program with unknown attendance (C-18).
6. **Unparseable height** (case-03, written in feet and inches; case-01's height is also
   `unparseable_value`). No BMI is computed from it (known gap, C-02, contract §4).
7. **`claim.bmi_path_b.htn`, case-03** (gold `review`, live `insufficient`). Gold follows the
   K-03 reading (a ticked box the chart mentions only as suspected); the engine has no BP at
   initiation (item 1) and does not reproduce the K-03 row (recorded with the gold).
8. **A relative's diabetes extracted as `t2dm`** (case-01, subject `family`). Gold labels it
   `other` (G-04) and lists `t2dm` as expected-absent; no row changes because the fact is a
   relative's (A-10).
9. **A relative's hypertension extracted as the patient's** (case-03, subject axis; A-02, A-10).
   No row changes in this case.
10. **Family diagnoses missed** (case-01: two hypertension and two `other` facts with subject
    `family`). The only missed gold facts of the run; no row depends on them.

## Known gaps carried from the gold PR

- Height in feet and inches is not parsed (`unparseable_value`): case-03.
- Medication periods of the form "started on X, still on at Y" are not counted as certainly
  in use on Y: case-04 `bmi_path_b.htn`.
- Cue scope across paragraphs: a cue in one paragraph does not reach a mention in the next.
  Not isolated in this run; item 1 is a different cause (no cue at all).
- `program_type` has no value for a limitation-only record: case-04 `lifestyle.activity`.

## Gold questions for guide revision 02

Listed in `reports/gold-questions-dev.json`; gold is unchanged.

- Identity facts carry an `event_date` in case-01 (five), case-03 (one) and case-17 (one) and
  none elsewhere; claim facts carry one in case-01 (all nine) and none elsewhere. They account
  for 14 of the 20 timing-only differences. Decide whether identity and claim facts are dated
  (T-04).
- case-01's `glp1_start` fact has `payer: unknown`, while the extraction schema has no payer on
  `glp1_start` and contract §8 matches `glp1_start` on payer.
- The OSA facts of case-03 and case-04 have no `osa_severity` (C-14, G-10).
- Self-paid GLP-1 use in case-07 and case-07b is not labelled as `prior_glp1` (C-16, G-12).

## What this changes

- The comparison, the replay export and the baseline exist and are deterministic; the
  baseline is the reference the eval job will compare against.
- The single largest cause is one labelling rule (item 1). It is a prompt and verifier
  question, not a rules question; fixing it is out of scope here.

## Tag proposal

After this PR is merged:

```
git switch main && git pull
git tag -a v0.1.0 -m "v0.1.0: checkpoint A - first real-extractor run over the 7 dev variants (122/140 conditions, 28/39 claims, 0 false supports; one run, not an evaluation)"
git push origin v0.1.0
```

## After the anchoring fix

Date 2026-11-09. Same extractor (returned `claude-sonnet-5-5` on every call), prompt
`extract-v3`, schema `v2`, rules `bridge-v1`, splitter `sentences-v1`, code `68b1c86` plus the
working tree of this change. Same seven dev variants; gold unchanged.

**Still one run of one model on seven dev cases; not a holdout result; not an evaluation.**

What changed (contract §5, "Dated event facts and the temporality axis"):

- Prompt `extract-v3` adds two sentences to `extract-v2`. A date inside a sentence is never a
  temporality cue. `glp1_start`, `prior_glp1` and `doc_dates` are dated events and are
  `current` unless an explicit cue precedes the mention. New prompt text means new cache keys.
- For those three fields, verify takes `assertion_check` from certainty and subject only. A
  temporality outcome other than `matched` adds the evidence flag `temporality_unverified`. It
  is no longer `unrecognized` or `assertion_mismatch`. The flag does not block anchoring and
  does not cap a decision. This holds only while the cues read an actual event: an explicit
  hypothetical cue still excludes the row, and an undecidable temporality scope still flags it
  `unrecognized`, so a conditional document date or fill neither anchors nor triggers an
  exclusion. A prior fill reaches the Part D rule only through the same gate as the start and
  the document dates; a fill that fails it stays stored as evidence for review. Anchoring still needs a located quote, present, patient, no
  `unrecognized` flag and the start day inside the quote.

The per-case files under `reports/checkpoint-a/`, `compare.md` and `reports/baseline-dev.json`
now hold this run. The checkpoint-A versions are at tag `v0.1.0`. The `extract-v2` replays stay
next to the new `extract-v3` replays.

### Calls

One fresh database outside the checkout; each case checked twice.

| Case | Input tokens | Output tokens | Latency | Cost | Attempts (pass 1) | Pass 2 | Evidence rows |
|---|---:|---:|---:|---:|---|---|---:|
| case-01 | 14 489 | 5 353 | 23.7 s | $0.0825 | 1 `parsed` | cache hit, no attempt | 36 |
| case-02 | 12 742 | 3 646 | 16.9 s | $0.0619 | 1 `parsed` | cache hit, no attempt | 27 |
| case-03 | 13 568 | 3 891 | 18.0 s | $0.0660 | 1 `parsed` | cache hit, no attempt | 28 |
| case-04 | 12 963 | 4 213 | 19.3 s | $0.0681 | 1 `parsed` | cache hit, no attempt | 29 |
| case-07 | 12 747 | 3 501 | 16.2 s | $0.0605 | 1 `parsed` | cache hit, no attempt | 25 |
| case-07b | 12 866 | 3 213 | 15.0 s | $0.0579 | 1 `parsed` | cache hit, no attempt | 22 |
| case-17 | 13 381 | 3 128 | 14.6 s | $0.0580 | 1 `parsed` | cache hit, no attempt | 22 |
| **Total** | **92 756** | **26 945** | **123.6 s** | **$0.4550** | 7 calls, 0 retries | 7 of 7 | 189 |

Plus `pytest -m live` on the synthetic smoke case: 12 483 input and 2 369 output tokens,
11.5 s, $0.0487. **Spend for this change: $0.5037.** No run came near a ceiling.

The decisions reported below come from re-running the stored extractions with the final code (cache
hits, no attempt); status, rule, reason and flags equal those of the first live runs for all
179 decisions. Every quote was found verbatim in its document (189 of 189). Each `extract-v3` replay, restored
and re-run offline, gives the same status, flags, rule and reason for every decision of its
live run (179 of 179); only evidence ids inside `computed` differ.

### Totals

| Measure | Checkpoint A | Contract fix only (v2 replays) | This run (v3, live) |
|---|---:|---:|---:|
| Conditions matching gold | 122 / 140 | 125 / 140 | 123 / 140 |
| Claims matching gold | 28 / 39 | 34 / 39 | 33 / 39 |
| False supports, conditions and claims | 0 | 0 | 0 |
| Missed exclusions | 0 | 0 | 0 |
| Mismatching rows | 29 | 20 | 23 |

The middle column re-runs the committed `extract-v2` replays offline through the new verify and
compute. It needs no API call and isolates the contract fix from the prompt change.

| Case | Conditions, A → now | Claims, A → now |
|---|---|---|
| case-01 | 16 → 15 | 6 → 8 |
| case-02 | 16 → 16 | 2 → 3 |
| case-03 | 17 → 17 | 3 → 4 |
| case-04 | 13 → 16 | 2 → 3 |
| case-07 | 20 → 20 | 5 → 5 |
| case-07b | 20 → 19 | 5 → 4 |
| case-17 | 20 → 20 | 5 → 6 |

Facts: 94 of 158 gold facts matched (80 before), 12 matched but excluded by verify (19), 48
wrong value (55), 4 missed (4), 22 false positives (27), expected-absent 99 / 99 (98 / 99).

Labels: the `extract-v2` replays carry 28 non-`current` temporality labels across seven fields,
including 5 of 7 GLP-1 starts. The `extract-v3` replays carry 2, both on diagnoses; all 7 starts
are `current`. No evidence row of this run carries `temporality_unverified`.

### What the fix changed

- An initiation date is now anchored in all seven cases (two before: case-07 and case-07b).
- `claim.drug` matches gold in all seven cases (two before).
- case-04: `bmi_path_a`, both BMI sub-results, `bmi_path_c` and `claim.bmi_bracket` now match
  gold. The anthropometric and blood-pressure labels that blocked them are now `current`.
- case-02: `bmi_path_a` now matches gold (`not_supported`).
- case-01: `lifestyle.nutrition` and its claim now match gold. The nutrition records no longer
  carry a `historical` label.

### Remaining mismatches

23 rows: 17 conditions and 6 claims. Each is listed with the first upstream error from
`scripts/compare_gold.py` and the cause found in the evidence.

| Case | Row | Gold | Live | First error | Cause |
|---|---|---|---|---|---|
| case-01 | `bmi_path_a`, `bmi_path_b.bmi`, `bmi_path_c.bmi`, `claim.bmi_bracket` | sup | rev `timing_disagreement` | `extraction_wrong_value` | A |
| case-01 | `bmi_path_b`, `bmi_path_c` | ins | rev | `extraction_wrong_value` | A |
| case-02 | `bmi_path_b.bmi`, `bmi_path_c.bmi` | sup | rev `timing_disagreement` | `extraction_wrong_value` | A |
| case-02 | `claim.bmi_bracket` | sup | rev `timing_disagreement` | `rules` | A |
| case-02 | `bmi_path_b` | sup | rev | `extraction_wrong_value` | A |
| case-02 | `bmi_path_c` | ins | rev | `extraction_wrong_value` | A |
| case-03 | `bmi_path_a`, `bmi_path_b.bmi`, `bmi_path_c.bmi`, `claim.bmi_bracket` | not / sup | ins | `extraction_wrong_value` | B |
| case-03 | `claim.bmi_path_b.htn` | rev | ins | `extraction_wrong_value` | C |
| case-04 | `bmi_path_b.htn`, `bmi_path_b` | sup | ins | `compute_timepoint` | D |
| case-04 | `lifestyle.activity` | rev | not | `rules` | E |
| case-04 | `age_18`, `claim.age_18` | sup | ins | `extraction_wrong_value` | F |
| case-07b | `age_18`, `claim.age_18` | sup | ins | `extraction_wrong_value` | F |

- **A. Timing disagreement on the BMI facts (11 rows: 6 in case-01, 5 in case-02).** The model writes
  `relative_to_glp1_initiation: unknown` on the height, weight and BMI. Compute derives `at` from
  the anchored start and the document date, and the disagreement caps every BMI decision at
  `review` (§3.1 step 8). In case-01 both extractions say `unknown`; the cap only appears now that
  the start anchors. In case-02 the `extract-v2` extraction said `at` and the `extract-v3` one says
  `unknown`. The prompt asks for `at` only when the document places the fact at the start, so
  `unknown` follows the prompt. Whether a model `unknown` against a computed `at` should count as
  a disagreement is a contract question (§5 item 1), not changed here. case-02's `doc_dates` rows
  also carry an off-default subject without a cue and anchor nothing; the measurements carry
  their own date, so this changes no row.
- **B. Unparseable height (4 rows).** case-03's height is in feet and inches
  (`unparseable_value`) and its weight has no date, so no BMI is computed. Known gap (C-02,
  contract §4).
- **C. K-03 reading (1 row).** case-03 `claim.bmi_path_b.htn`, unchanged from checkpoint A item 7.
- **D. Medication period "started on X, still on at Y" (2 rows).** case-04; known gap
  (contract §3.2). Classified `compute_timepoint`.
- **E. `program_type` has no value for a limitation-only record (1 row).** case-04; known gap
  (contract §6, guide C-18).
- **F. Identity facts with a date of birth outside the quote (4 rows).** In case-04 and case-07b
  every identity fact names a date of birth that its quote does not contain. Verify excludes
  each with `value_not_in_quote`, so no age is verified. This is new in this sample; the prompt
  wording for identity facts is unchanged.

### What this changes

- The labelling rule behind checkpoint A item 1 no longer blocks anchoring. The contract fix
  alone, on the old extractions, removes 9 of the 29 mismatching rows with no new false support.
- The largest remaining cause is A: the timepoint label on measurements, which now caps BMI
  rows at `review` instead of leaving them `insufficient`. Both are safe directions.
- Live totals move less than the offline column because a new sample brings its own errors
  (A in case-02, F). One run per prompt cannot separate prompt effect from sampling variation.
