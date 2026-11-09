# ADR 0001: global limits for a case run

Status: proposed, numbers provisional (2026-11-09). The live run that was to measure
them was rejected by the API (`docs/live-run-01.md`); every value below comes from the
contract, the planning estimate, or the two compiled diagnostic calls, and is to be
re-derived from the first accepted live call before `eval` runs the 18 cases.

## Context

A case run makes at most a few API calls, but each one is paid for and nothing stops a
misconfigured loop, a raised `max_tokens`, or a price change from multiplying the bill
across an evaluation. The contract fixes the attempt and time budgets (§11); this ADR
adds the request timeout, `max_tokens`, and two cost ceilings, and puts all of them in one
place: `Limits` in `src/bridge_check/extract.py` (`LIMITS` is the committed instance).

## Decision

| Limit | Value | Where enforced | Source |
|---|---|---|---|
| API attempts per run | ≤ 4, including the first | `extract._call_api` | contract §11, AGENTS.md |
| Parse-class attempts (`parse_failed`, `refused`, `truncated`) | ≤ 1 | same | contract §11 |
| Wall clock per run | 300 s | checked before each send, bounds each timeout, checked again before `parsed` | contract §11 |
| Request timeout | 180 s | `client.with_options(timeout=min(180, remaining))`; not in the cache key | see below |
| `max_tokens` | 16 000 | request kwarg; **in the cache key** | see below |
| Per-run cost ceiling | $1.00 | before each send, against spent plus a reservation for the next call | see below |
| Per-eval cost ceiling | $3.50 | same, plus what the eval already spent | see below |

**Request timeout, 180 s.** No latency was measured. A reply that uses the whole
`max_tokens` at about 100 output tokens per second (thinking included) takes about 160 s;
the planning value of 60 s would turn every long reply into `unknown_outcome`, which is
paid for and repeated. 180 s leaves room for one full-length attempt plus a shorter retry
inside the 300 s wall clock. To be replaced by three times the measured maximum latency,
rounded up to a minute, once a reply exists.

**`max_tokens`, 16 000.** Kept from planning 06 §2.1: the reply is twelve arrays of facts
with verbatim quotes plus adaptive thinking, and the estimate of about 1 500 content tokens
has not been measured. Lowering it changes the cache key, so it moves only with a
measurement.

**Cost model.** List prices of 06 §2.3 (2026-11-08): $2.00 per million input tokens,
$10.00 per million output tokens; cache reads are not used and not modelled. The only
measured input size is from the two compiled diagnostic calls: about 565 tokens per KB of
schema, so the committed request is about 14 600 input tokens for the smoke documents and
somewhat more for a real case (the documents add about 1 500 tokens). Expected output
including thinking: about 3 000 tokens.

- Expected cost of one call: 15 000 × $2.00 / 10⁶ + 3 000 × $10.00 / 10⁶ = $0.03 + $0.03 = $0.06.
- Worst case of one call: 15 000 × $2.00 / 10⁶ + 16 000 × $10.00 / 10⁶ = $0.03 + $0.16 = $0.19.

**Reservation.** Before every send the program reserves `reserved_cost(request)`, an
upper bound rather than an estimate: one input token per UTF-8 byte of the canonical
request JSON (every token of the tokenizer spans at least one byte; the two compiled
probes billed 2.1–2.3 bytes per input token), plus 2 000 tokens for whatever the server
wraps around a structured-output request (the API documents that this overhead is billed
but not its maximum, so the allowance is an assumption; the live test asserts
`input_tokens ≤ bytes + 2 000` on every accepted call, which is where it gets checked),
plus the whole `max_tokens` as output (the API never returns more), at list prices. For the smoke request (26 157 bytes) that is
28 157 × $2.00 / 10⁶ + 16 000 × $10.00 / 10⁶ = $0.056 + $0.160 = **$0.216 per call**; a
real case adds a few hundred bytes of documents.

**Per-run ceiling, $1.00.** The contract allows 4 attempts; 4 × $0.216 = $0.87 must fit,
otherwise the ceiling would silently cut the attempt budget; rounded up to $1.00. The
ceiling therefore does not bite at today's request size; it bites as soon as the
reservation grows (a larger `max_tokens`, a larger schema or document packet, a price
change): at `max_tokens` 64 000 the reservation is $0.70 and a second attempt is refused.
The expected cost of a run is still about $0.06 (one call) to $0.24 (four).

**Per-eval ceiling, $3.50.** 18 cases × $0.06 = $1.08 for one call each; × 3 safety
(one retry for every case plus the error of the estimate) = $3.24, rounded to $3.50. For
comparison the planning estimate was $0.49 for 18 cases; the difference is the schema's
input tokens, which the estimate did not count. The last case of an eval needs
$3.50 − spent ≥ $0.216 to be sent at all.

**Semantics of the ceilings.** Before every send, `spent` = the cost recorded on this
run's attempts (`attempts.cost_usd`), with every `unknown_outcome` attempt counted at the
reservation. `unknown_outcome` covers a client-side timeout, an interrupt, a transport
failure (`APIConnectionError`: the SDK raises the same class for a refused connection and
for a response lost after the server ran the request) and a server-side processing
timeout (HTTP 504, or an error body of type `timeout_error`, which the API documents can
also arrive as HTTP 500). In all of these the cost is unknown and stays reserved. Only
another status error, where the server answered without running the request (400, 429,
500 `api_error`, 529 `overloaded_error`), is a free `api_error`.
The send is refused when `spent + reservation > run ceiling`, or when
`eval_spent_usd + spent + reservation > eval ceiling` (`eval_spent_usd` is what the
enclosing eval already spent, passed by the caller). A refusal writes a dead letter
(`RunCostCeiling` / `EvalCostCeiling`, message with the amounts, no document text), no
attempt row exists for it, the run ends `failed` at `extract`, `bridge check` prints the
message on stderr and exits 3, and verify, compute and rules do not run. Because the
reservation is an upper bound on the next call, a recorded charge never exceeds a
ceiling. Cache hits and replays make no API call and are never refused. `check` runs one
case and passes `eval_spent_usd=0.0`; `eval` (not implemented yet) will pass the running
total of the cases already run, computed with the same unknown-outcome rule.

**Caps are caps.** `Limits` validates its values: `max_attempts` ≤ 4,
`max_parse_class_attempts` ≤ 1 and `wall_clock_s` ≤ 300 can be lowered by a caller but
never raised; a larger value raises `ValueError` before any call.

## Consequences

- A reply that is cut by `max_tokens` is `truncated` (parse-class) and ends the run; the
  ceilings never cut a reply themselves.
- The ceilings live in code, not in `rules/bridge-v1.yaml`: they are operational limits,
  not policy, and the rules table's `IMPLEMENTED` allow-list stays about CMS policy.
- Tests use the fake client with monkeypatched prices (`tests/test_extract.py`,
  `tests/test_cli.py`); `uv run pytest -q -m live` is the one opt-in call that checks the
  schema against the API.
- Until the schema compiles, every number here is an estimate; this ADR is revised, not
  superseded, when the measurement exists.
