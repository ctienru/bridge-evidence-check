# ADR 0001: global limits for a case run

Status: accepted, numbers measured (2026-11-09). First proposed the same day with
provisional numbers, when the live run was rejected by the API; revised from the first
accepted live calls (`docs/live-run-01.md`: 7 billed calls on the two frozen smoke cases
and the synthetic smoke case). To be re-derived again after `eval` runs the 18 cases.

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
| Request timeout | 120 s | `client.with_options(timeout=min(120, remaining))`; not in the cache key | measured, below |
| `max_tokens` | 16 000 | request kwarg; **in the cache key** | kept, below |
| Per-run cost ceiling | $1.00 | before each send, against spent plus a reservation for the next call | measured, below |
| Per-eval cost ceiling | $5.00 | same, plus what the eval already spent | measured, below |

**Measurements (2026-11-09, `claude-sonnet-5-5`, prompt `extract-v2`).** Four calls on
the two real smoke cases and three on the synthetic smoke case, every one a single attempt:

| | Real cases (4 calls) | Synthetic smoke (3 calls) |
|---|---|---|
| Request bytes (canonical JSON) | 31 985 – 32 840 | about 28 100 |
| Billed input tokens | 13 942 – 14 345 | 11 736 – 12 339 |
| Bytes per input token | 2.29 – 2.30 | 2.3 – 2.4 |
| Output tokens (thinking included) | 4 173 – 7 731 (mean 5 542) | 2 292 – 2 535 |
| Latency | 19.9 – 39.0 s | 11.1 – 12.0 s |
| Cost at list prices | $0.070 – $0.106 (mean $0.084) | $0.046 – $0.050 |

**Request timeout, 120 s.** The rule set when nothing was measured: three times the
measured maximum latency, rounded up to a minute. 3 × 39.0 s = 117 s → 120 s. A reply
that used the whole `max_tokens` at the observed rate (7 731 output tokens in 39 s, about
200 per second) would take about 80 s, inside the timeout. 120 s leaves room for two
full-length attempts inside the 300 s wall clock. The earlier provisional value was 180 s.

**`max_tokens`, 16 000.** Kept. The largest reply used 7 731 tokens, under half; the
smallest 2 292. Lowering it changes the cache key, so it moves only when the evaluation
shows the margin is never needed.

**Cost model.** List prices (2026-11-08): $2.00 per million input tokens, $10.00 per
million output tokens; cache reads are not used and not modelled. A real case bills about
14 300 input tokens (the schema inside the tool definition is most of it; the documents
add a few hundred) and 4 000 – 8 000 output tokens, 6 000 for the estimate.

- Expected cost of one call: 14 300 × $2.00 / 10⁶ + 6 000 × $10.00 / 10⁶ = $0.029 + $0.060 = **$0.089** (measured mean $0.084).
- Worst case of one call: 14 300 × $2.00 / 10⁶ + 16 000 × $10.00 / 10⁶ = $0.029 + $0.160 = **$0.189**.

**Reservation.** Before every send the program reserves `reserved_cost(request)`, an
upper bound rather than an estimate: one input token per UTF-8 byte of the canonical
request JSON (every token of the tokenizer spans at least one byte; the live calls billed
2.3 bytes per input token), plus 2 000 tokens for whatever the server wraps around the
tool definition (the API bills a tool-use system prompt; its size is not documented, so the
allowance is an assumption; the live test asserts `input_tokens ≤ bytes + 2 000` on every
accepted call, and the measured input was less than half the bound), plus the whole
`max_tokens` as output (the API never returns more), at list prices. For the largest real
request (32 840 bytes) that is
34 840 × $2.00 / 10⁶ + 16 000 × $10.00 / 10⁶ = $0.070 + $0.160 = **$0.230 per call**.

**Per-run ceiling, $1.00.** The contract allows 4 attempts; 4 × $0.230 = $0.92 must fit,
otherwise the ceiling would silently cut the attempt budget; rounded up to $1.00
(unchanged from the provisional value, which used $0.216 for the smoke request). The
ceiling does not bite at today's request size; it bites as soon as the reservation grows
(a larger `max_tokens`, a larger schema or document packet, a price change): at
`max_tokens` 64 000 the reservation is $0.71 and a second attempt is refused. The expected
cost of a run is about $0.09 (one call) to $0.36 (four).

**Per-eval ceiling, $5.00.** 18 cases × $0.089 = $1.60 for one call each; × 3 safety (one
retry for every case plus the error of the estimate) = $4.81, rounded to $5.00. The
provisional value was $3.50, from an estimated $0.06 per call that did not count the
output tokens the real cases produce. The last case of an eval needs $5.00 − spent ≥ $0.230
to be sent at all.

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
- A parse-class outcome also ends the run (one allowed), and under the tool-use output mode
  (ADR 0002) it is a measured quantity rather than a rarity: 3 of 4 accepted first-draft calls on
  2026-11-09 (2 of 3 without the probe), 0 of 3 after the prompt was tightened. The cost of such a run is one call.
- The ceilings live in code, not in `rules/bridge-v1.yaml`: they are operational limits,
  not policy, and the rules table's `IMPLEMENTED` allow-list stays about CMS policy.
- Tests use the fake client with monkeypatched prices (`tests/test_extract.py`,
  `tests/test_cli.py`); `uv run pytest -q -m live` is the one opt-in call that checks the
  request shape against the API.
- The numbers come from 7 calls on 3 cases; this ADR is revised, not superseded, when the
  18-case evaluation exists.
