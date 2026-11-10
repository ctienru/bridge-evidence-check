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
