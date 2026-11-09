# Live run 01: first accepted extraction on the frozen smoke cases

Date 2026-11-09. Extractor `claude-sonnet-5-5`, prompt `extract-v2`, schema `v2`
(`src/bridge_check/schema.py`), output mode "single non-strict tool"
(`docs/adr/0002-extraction-output-mode.md`), code at `6f02410` (main) plus this branch.
This page records a handful of calls of one model on the two frozen smoke cases; it is a
measurement, not an evaluation. No document text, quote or patient name appears here.

## Why a second page section exists

The first attempt of the day (`output_config.format` with the compiled schema) was rejected
before generating anything (`HTTP 400 The compiled grammar is too large`, 22.5 KB against
roughly 5 KB usable; see ADR 0002 for the diagnostics). The request shape was changed to a
single tool `record_extraction` whose `input_schema` is the full schema, not strict, with
`tool_choice: auto` (the model rejects forced tool use: `tool_choice: type "tool" and "any"
are not supported for this model.`, `req_011CgswgEgggb5KgexcDtNSc`, free) and
`disable_parallel_tool_use: true`; the prompt requires the call. Everything below is with
that shape.

## Calls made

Prices $2.00 / $10.00 per million input / output tokens (list, 2026-11-08). "Round 1" is
the first prompt draft; the two parse failures led to two sentences being added to the
prompt (no other key than the twelve arrays; the allowed `claimed_value` tokens), and
"round 2" is the committed prompt. Every call below is one attempt; none was retried.

| # | Case | Prompt state | Request bytes | Input tokens | Output tokens | Latency | Cost | Attempt status |
|---|---|---|---:|---:|---:|---:|---:|---|
| 0 | case-smoke (probe, forced `tool_choice`) | round 1 | 27 986 | – | – | – | $0 | HTTP 400, see above |
| 1 | case-smoke (probe, `auto`) | round 1 | 28 095 | 11 736 | 2 292 | 11.1 s | $0.0464 | tool called; `claim_id` outside the enum (schema gap, fixed in v2) |
| 2 | case-01 | round 1 | 32 465 | 14 205 | 7 731 | 39.0 s | $0.1057 | `parsed`, run completed |
| 3 | case-smoke (`bridge check`) | round 1 | – | 12 199 | 2 535 | 12.0 s | $0.0497 | `parse_failed` `ValidationError` at `pa_form_claims.3` (`claimed_value` not a token) |
| 4 | case-15-L0 | round 1 | 31 985 | 13 942 | 4 173 | 19.9 s | $0.0696 | `parse_failed` `ValidationError` (`extra_forbidden`: one extra top-level key) |
| 5 | case-smoke (`pytest -m live`) | round 2 | – | 12 339 | 2 401 | 11.7 s | $0.0487 | `parsed` |
| 6 | case-01 | round 2 | 32 840 | 14 345 | 5 863 | 26.1 s | $0.0873 | `parsed`, run completed |
| 7 | case-15-L0 | round 2 | 32 360 | 14 082 | 4 401 | 20.0 s | $0.0722 | `parsed`, run completed |

Total 7 billed calls, 92 848 input and 29 396 output tokens, $0.480. Every billed call
returned exactly one `tool_use` block named `record_extraction` with a JSON object as
input and `stop_reason: tool_use`; no reply had a text block or a refusal.

Measured ratios: 2.29–2.30 request bytes per billed input token on the real cases, 2.39 on
the smoke probe; the billed input stayed far below the reservation bound (request bytes
plus 2 000 tokens, ADR 0001). The model returned by the API was `claude-sonnet-5-5` on every
call.

## Runs (round 2, fresh database, then the second run)

| Scope item | case-01 | case-15-L0 (private checkout) |
|---|---|---|
| First `bridge check --json` | run 1, `completed`, extraction 1 `source: api`, attempt 1 `parsed` | run 3, `completed`, extraction 2 `source: api`, attempt 2 `parsed` |
| Second `bridge check --json` | run 2, `completed`, extraction 1 `source: cache`, no attempt row | run 4, `completed`, extraction 2 `source: cache`, no attempt row |
| Decisions | 29 (2 conditions, 3 paths, 9 sub-results, 4 exclusions, 2 lifestyle, 9 claims) | 28 (same, 8 claims) |
| `human_workload` (top-level rows for a human) | 8 | 8 |
| Facts returned | 6 identity, 3 doc dates, 1 GLP-1 start, 3 anthropometrics, 8 medications, 1 list, 4 diagnoses, 3 lifestyle, 10 claims; 0 BP, 0 labs, 0 prior GLP-1 | 5 identity, 3 doc dates, 1 GLP-1 start, 1 anthropometric, 1 BP, 1 lab, 3 medications, 4 diagnoses, 8 claims; 0 lists, 0 lifestyle, 0 prior GLP-1 |
| Evidence rows / position status | 39, all `verbatim` | 27, all `verbatim` |
| Assertion check | 29 matched, 9 mismatch, 1 unrecognized | 21 matched, 6 unrecognized |
| Exclusion reasons | assertion_mismatch 9, claim_document 4, value_not_in_quote 2, unparseable_value 1 | claim_document 4 |
| Flags | unrecognized 5, ambiguous_match 1, id_missing 1 | unrecognized 8, id_missing 1 |
| Document identity | D0 match, D1 match, D2 missing | D0 match, D1 match, D2 missing |
| Dead letters | none | none |

Every quote the model returned was found verbatim in its document (position status), on
both cases. The D2 document of each case carries no patient identifier, hence `missing`
and the `id_missing` flag that gold also expects.

## Live vs gold, case-01 (public gold `cases/case-01/expected.json`)

Condition rows: 16 of 20 statuses match gold; flags match on every matching row.

| Condition | Gold | Gold flags | Live | Live flags | Match |
|---|---|---|---|---|---|
| `age_18` | supported | inconsistent_values | supported | inconsistent_values | yes |
| `bmi_path_a` | supported | – | insufficient | – | no |
| `bmi_path_b` | insufficient | – | insufficient | – | yes |
| `bmi_path_b.bmi` | supported | – | insufficient | – | no |
| `bmi_path_b.hfpef` | insufficient | – | insufficient | – | yes |
| `bmi_path_b.htn` | insufficient | – | insufficient | – | yes |
| `bmi_path_b.ckd` | insufficient | – | insufficient | – | yes |
| `bmi_path_c` | insufficient | – | insufficient | – | yes |
| `bmi_path_c.bmi` | supported | – | insufficient | – | no |
| `bmi_path_c.prediabetes` | insufficient | – | insufficient | – | yes |
| `bmi_path_c.mi` | insufficient | – | insufficient | – | yes |
| `bmi_path_c.stroke` | not_supported | – | not_supported | – | yes |
| `bmi_path_c.pad` | insufficient | – | insufficient | – | yes |
| `exclusion.t2dm` | insufficient | – | insufficient | – | yes |
| `exclusion.osa` | insufficient | – | insufficient | – | yes |
| `exclusion.mash` | insufficient | – | insufficient | – | yes |
| `exclusion.part_d_glp1` | insufficient | – | insufficient | – | yes |
| `patient_identity` | review | id_missing | review | id_missing | yes |
| `lifestyle.nutrition` | insufficient | – | review | – | no |
| `lifestyle.activity` | insufficient | – | insufficient | – | yes |

Claims: 6 of 9 match (`claim.drug` and `claim.bmi_bracket` are `insufficient` live against
`supported` in gold; `claim.lifestyle.nutrition` is `review` against `insufficient`).

The three BMI rows are the one real gap: gold has a supported BMI at initiation, the live
run has none, and the verification counts show where it went (one anthropometric value
rejected as `unparseable_value`, two as `value_not_in_quote`, nine assertion mismatches).
Whether that is the extractor's quote choice or the verifier's lexicon is a question for the
evaluation item, not for this measurement.

## Live vs gold, case-15-L0 (private gold)

Condition rows: 19 of 20 statuses match gold. The one difference is a comorbidity
sub-result that gold marks `supported` and the live run sends to `review` with the
`unrecognized` flag (a wording the verifier's lexicon does not know); one matching row
lacks a `boundary_value` flag that gold carries. Claims: 5 of 8 match. The row-level table
and every raw response are in the private checkout under `records/live/case-15-L0/2026-11-09/`.

## Private records

For each case and date the private checkout holds the `--json` report of every run, the
request kwargs of every attempt with the document text replaced by its sha256 and length,
the attempt row (status, tokens, latency, cost), and the raw response. Raw responses whose
quotes carry MTSamples text (case-01) are kept under `replays-full/mtsamples/case-01/live/`,
which is git-ignored there; everything else is under `records/live/<case>/<date>/`. The
public repository holds this page only.

## What this changes

- `docs/adr/0001-global-limits.md` is revised from these numbers: request timeout 120 s,
  per-eval ceiling $5.00; the other limits stay.
- The lost grammar guarantee is real: of the 4 accepted calls under the first prompt
  draft (calls 1–4), 3 failed local validation (2 of 3 if the probe, which failed on the
  schema gap, is left out); the rejected forced probe (call 0) never reached validation.
  The contract allows one parse-class attempt per run. With the tightened prompt 3 of 3
  passed. This is a count of 7 billed calls, not a rate; ADR 0002 records the consequence.
