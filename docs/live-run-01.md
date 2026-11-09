# Live run 01: the API rejects the compiled schema

Date 2026-11-09. Extractor `claude-sonnet-5-5`, prompt `extract-v1`, schema `v1`
(`src/bridge_check/schema.py`, 13 of 16 union parameters, `event_date` fallback), code at
`7e12adc` plus this branch. This page records one attempt of one model on the frozen smoke
cases; it is a measurement, not an evaluation.

## Result

The API rejected the request before generating anything. `bridge check` sends
`output_config.format = {"type": "json_schema", "schema": extraction_json_schema()}`
(contract §7.2); the server compiles that schema into a grammar and refused it:

```
HTTP 400 invalid_request_error
The compiled grammar is too large, which would cause performance issues.
Simplify your tool schemas or reduce the number of strict tools.
request_id: req_011CgsrJsMNQTmbTtcTAmxdg
```

Same error on the synthetic smoke case (`uv run pytest -q -m live`) and on every variant
below; the frozen cases were not sent because they use the same schema. The attempt row
is `api_error` (`BadRequestError status=400`), not retried, cost 0. Per the issue the
schema was **not** changed; the decision is recorded for a human.

| Scope item | Status |
|---|---|
| `cases/case-01` live run (`source: api`, then `source: cache`) | not run: same schema, would get the same 400 |
| `case-15-L0` live run | not run |
| Schema accepted by the API | **no**, error above |
| Tokens, latency, cost, verification summary, `human_workload`, live-vs-gold table | no data; the run never reached a response |
| Raw responses in the private checkout | nothing to save |

## Diagnostics

Scratch calls with the smoke documents, `max_tokens: 1` and no `thinking`, so a schema
that compiles costs only its input tokens (a 400 costs nothing). The union count is not
the binding constraint; the compiled grammar size is. Only the schema was varied.

| Variant (`extraction_json_schema()` with …) | JSON bytes | Compiled | Input tokens |
|---|---:|---|---:|
| as committed (with and without `thinking`) | 22 488 | no | – |
| `description` removed everywhere | 17 154 | no | – |
| every `enum` replaced by `string` | 18 902 | no | – |
| only `patient_identity` (1 array, 1 definition) | 2 167 | **yes** | 3 179 |
| first 3 arrays (`patient_identity`, `doc_dates`, `glp1_start`) | 5 304 | **yes** | 4 948 |
| first 6 arrays (adds `prior_glp1`, `anthropometrics`, `bp_readings`) | 10 337 | no | – |
| first 9 arrays (adds `labs`, `medications`, `medication_lists`) | 16 217 | no | – |

The schema has no `pattern` constraints. Sizes of the 12 item definitions: 1.4–2.5 KB each
(`Medication` 2 461, `Diagnosis` 2 253, `Lifestyle` 2 251 bytes); the eight shared fields
(`doc_id`, `quote`, the three assertion axes, `event_date`, `date_precision`,
`relative_to_glp1_initiation`) are repeated in every definition, with 74 enums and 274 enum
values in all. The threshold lies between 5.3 KB (3 definitions) and 10.3 KB (6); the
committed schema is about four times the size that compiled.

Cost of the diagnostics: 2 compiled calls, 8 127 input tokens and 2 output tokens,
$0.0163 at $2.00 / $10.00 per million; the 400 responses were free.

The two compiled calls also give the only measured input size so far: the schema is
counted as input at roughly 565 tokens per KB, so the committed request would be about
14 600 input tokens for the smoke documents (planning 06 §2.3 assumed about 6 000 per case).

## What is not decided here

Options for the human decision, in the order of least change to the contract:
factor the eight shared fields into one `$ref` and shorten enums (may not reach a
four-fold reduction); split the extraction into several calls with smaller schemas
(changes the cache key, attempt budget and replay semantics of contract §11); or send
the schema in the prompt only and keep the local Pydantic validation as the sole check
(gives up the server-side guarantee that `parse_failed` is rare). None was tried.
`docs/adr/0001-global-limits.md` therefore records provisional limits derived from the
planning estimate and from the two compiled calls, to be re-derived after the first
accepted live call.
