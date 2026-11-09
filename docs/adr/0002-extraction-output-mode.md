# ADR 0002: extraction output mode

Status: accepted (2026-11-09). Supersedes the "sent with `transform_schema()`" wording of
contract §7.2 and the output-mode part of planning section 2.1 of the technology notes.

## Context

The extraction reply is one JSON object with twelve arrays of facts, each fact carrying
eight shared fields and two to nine specific ones, 74 enum fields with 274 values in all.
The contract's design sent the Pydantic schema, passed through the SDK's
`transform_schema()`, as `output_config.format` (structured outputs), so the server would
constrain decoding to the schema and `parse_failed` would be rare.

On the first live call (2026-11-09) the API rejected every variant of that request:

```
HTTP 400 invalid_request_error
The compiled grammar is too large, which would cause performance issues.
Simplify your tool schemas or reduce the number of strict tools.
```

Diagnostics with `max_tokens: 1` and the smoke documents (a 400 is free; 2 compiled calls
cost $0.0163):

| Variant (`extraction_json_schema()` with …) | JSON bytes | Compiled |
|---|---:|---|
| as committed (with and without `thinking`) | 22 488 | no |
| `description` removed everywhere | 17 154 | no |
| every `enum` replaced by `string` | 18 902 | no |
| only `patient_identity` (1 array, 1 definition) | 2 167 | yes |
| first 3 arrays | 5 304 | yes |
| first 6 arrays | 10 337 | no |
| first 9 arrays | 16 217 | no |

The union count (13 of the 16 allowed) is not the binding constraint; the compiled grammar
size is, with a threshold between 5.3 and 10.3 KB of schema. The committed schema is about
four times the largest size that compiled.

## Options

1. **Shrink the schema** to about a quarter: factor the eight shared fields into one
   `$ref`, shorten or drop enums and descriptions. Dropping every description or every
   enum each removed only about a fifth; a four-fold cut would remove the constraints the
   schema exists to express, and it is not clear it would reach the threshold.
2. **Split the extraction into several calls** with smaller schemas (three or four calls of
   three arrays each). Three to four times the input cost per case, and the cache key,
   attempt budget, replay semantics and `attempts` table of contract §11 are all defined
   for one call per case.
3. **Keep one call and the full schema, drop the server-side grammar**: send the schema as
   the `input_schema` of one tool that is not `strict` (only strict tools and
   `output_config.format` are compiled), and rely on the local Pydantic validation that the
   contract already requires (§7.2) and that verify already assumes.

## Decision

Option 3. The request carries exactly one tool, `record_extraction`, whose `input_schema`
is `pydantic_json_schema()` (the full local schema; `transform_schema()` is no longer in the
request path and is kept only as a local check that the schema still compiles under the
structured-output rules), and `tool_choice = {"type": "auto", "disable_parallel_tool_use":
true}`. The system prompt (`prompts/extract-v2.md`) requires the call: exactly once, with
the twelve arrays and nothing else.

`auto` rather than a forced call: the first probe used
`tool_choice = {"type": "tool", "name": "record_extraction"}` and the model rejected it,

```
HTTP 400 invalid_request_error
tool_choice: type "tool" and "any" are not supported for this model.
```

(`req_011CgswgEgggb5KgexcDtNSc`). This is a restriction of `claude-sonnet-5-5` itself, not
of the schema, and the API documents `auto` plus a prompt instruction as the replacement.
The second probe with `auto` was accepted (11 736 input tokens, $0.046) and returned the
tool call. `prompt_version` is `extract-v2` and `schema_version` is `v2`, so stored runs
and cache keys of the two designs never mix; `request_kwargs`, and with it the cache key,
now contain `tools` and `tool_choice` instead of `output_config` (contract §11).

Schema v2 differs from v1 in one field: `claim_id` carries its allowed values as an `enum`
in the JSON schema. The Python validator already enforced them, but the schema sent to the
model said only `string`, and the probe returned `bmi_bracket` for `claim.bmi_bracket`.
Structured outputs would have had the same gap.

## What is lost, and how it is covered

With a compiled grammar the reply could not have an unknown key, a wrong enum value or a
non-object input; it never guaranteed cross-field rules (a `claimed_value` fitting its
`claim_id`, a date matching its precision), which were always local. Without the grammar
the reply's `tool_use.input` is still always a JSON object (the API parses it), but any of
those can happen. The local validation is the only check, and it is reached exactly as
before: the raw response is committed as `response_saved` first, then classified. A reply
with no `record_extraction` call, or whose input is not an object, is `parse_failed`
(`NoToolUse`, `BadToolInput`); a Pydantic error is `parse_failed` with the field path in the
dead letter; `refused` and `truncated` are unchanged.

The cover is the retry budget of contract §11: a parse-class outcome ends the run
(`failed_stage=parse`) because at most one parse-class attempt is allowed per run, and the
next check of the same case replays nothing (terminal states are not replayed) and makes a
fresh call. Nothing downstream ever sees an invalid extraction, so the safety invariants
hold; what is lost is attempts and money, not correctness.

Measured on 2026-11-09 (`docs/live-run-01.md`): under the first draft of the v2 prompt, 3 of
the 4 accepted calls failed validation (the probe on the `claim_id` schema gap, then one on
a free-text `claimed_value` that was an identifier, one on an extra top-level key); the
rejected forced probe never reached validation. The prompt was given two sentences on exactly
those points and 3 of 3 calls then passed. Seven calls say nothing about the rate; the
evaluation item will. If the rate turns out high, the options are, in order: tighten the
prompt or the schema descriptions further; make the top-level object tolerant of unknown
keys (a contract change, since §7.2 rejects them); raise the parse-class budget (a contract
change). Returning to structured outputs is possible only if the grammar limit is raised;
the local check `test_schema_compiles_with_transform_schema` keeps the schema ready for it.

## Consequences

- One call per case, full schema, no size limit on the schema; the input cost of a call is
  the schema plus the documents (about 14 000 tokens on the smoke cases) either way.
- `parse_failed` is no longer rare by construction; it is a measured quantity reported
  per run and per eval, and every occurrence leaves a raw response to inspect.
- The live test (`uv run pytest -q -m live`) checks the tool-use request shape against the
  API on the smoke case; it is where a prompt, schema or SDK change that breaks the call
  is noticed.
- Hand-written replies (`fixtures/synthetic/**`, the private `fake-reply.json`) use the
  `tool_use` shape; a text-only reply is the `no_tool_call` fixture.
