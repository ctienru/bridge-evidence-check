# Failure recovery

A `bridge check` can stop part way: the process is killed, the API times out, or a stage
raises. This page lists the three failure scenarios the pipeline recovers from, what a
rerun does in each, what `bridge history` shows, and how to reproduce each one offline.
The rules behind it are in `docs/contracts.md` §1 (run status, `failed_stage`) and §11
(attempt state machine, lookup order, run lock, recovery).

## Commit boundaries

| Step | Committed | When |
|---|---|---|
| Start | Run lock taken; leftover `running` runs become `failed` + `interrupted`, leftover `started` attempts become `unknown_outcome`; a new `case_runs` row (`running`) | at once |
| API call | `attempts` row `started` before the request; raw `response_json` and `response_saved` as soon as the full reply arrives | each on its own, before parsing |
| Parse | `parsed` and the `extractions` row | one transaction |
| Verify, compute | `evidence`, `doc_facts`, `med_periods` | one transaction per stage |
| Rules | every `decisions` row and `status = completed` | one transaction |

Every `check` looks for the extraction in this order: the `extractions` row for the cache
key (`cache`), else the latest `response_saved` attempt for that key, parsed again
(`replay`), else a new API call (`api`). Verify, compute and rules always run again with the
current code; only the extraction is cached.

## The three scenarios

| Scenario | State left behind | What the rerun does | Table changes on rerun |
|---|---|---|---|
| (a) Full raw response saved, parse interrupted | attempt `response_saved`, no `extractions` row | replays the parse; no API call | `case_runs` +1, `attempts` +0, `extractions` +1 |
| (b) No full response: timeout, or killed between `started` and `response_saved` | attempt `unknown_outcome` (cost NULL) | calls the API again, as a new attempt | `case_runs` +1, `attempts` +1, `extractions` +1 |
| (c) Extraction stored, rules failed or rolled back | `extractions` row; no decisions | cache hit; no API call; verify, compute and rules run again | `case_runs` +1, `attempts` +0, `extractions` +0 |

In every case the earlier run stays in the database and in `bridge history`: `failed` at the
stage that failed, or `failed` + `interrupted` when the process died with the run still
`running`.

## At-least-once, not exactly-once

Scenario (b) may call the API again and pay again. A timeout does not mean the server did
not run the request: the reply may have been produced and billed and never reached disk.
Such an attempt is recorded as `unknown_outcome` with cost NULL (unknown, not zero), and the
cost ceilings charge it at the full reservation of one call (`docs/adr/0001-global-limits.md`).
Only scenario (a) avoids a second call, because the complete reply is already on disk.

## What the user sees

`bridge history <case>` lists every run. It shows ids, statuses, counts and timestamps only,
never document text:

```
runs for case-smoke
run  status     failed_stage  extraction  source      src_attempt  attempts  unknown_outcome  started_at
1    failed     interrupted   -           -           -            1         1                2026-…
2    completed  -             1           fresh call  2            1         0                2026-…
3    completed  -             1           cache hit   2            0         0                2026-…
```

- `source` is where the run's extraction came from: `fresh call` (api), `replay`, or
  `cache hit`; `-` when the run never got one.
- `src_attempt` is the attempt whose reply the extraction was parsed from.
- `attempts` counts the attempts this run made; `unknown_outcome` counts those of them whose
  result is unknown and may have been billed.
- `--json` gives the same rows with `extraction_source` and `unknown_outcomes`.

## Reproduce with the fake client

No key and no cost. `BRIDGE_FAKE_FAULT` stops the run at a named boundary as a killed
process would leave it: the run stays `running`, `bridge check` prints
`injected fault at <boundary>` on stderr and exits 3. The variable is honoured only together
with `BRIDGE_FAKE_CLIENT`; otherwise it is ignored. The boundaries are
`before_response_saved`, `after_response_saved` and `in_rules`. Start each scenario from a
fresh database:

```
rm -f recovery.db recovery.db-wal recovery.db-shm recovery.db.lock
```

(a) Full raw response saved, parse interrupted:

```
BRIDGE_FAKE_CLIENT=1 BRIDGE_FAKE_FAULT=after_response_saved uv run bridge check fixtures/synthetic/case-smoke --db recovery.db   # exit 3
BRIDGE_FAKE_CLIENT=1 uv run bridge check fixtures/synthetic/case-smoke --db recovery.db   # "extraction 1 from replay (source attempt 1 …)", "attempts this run: 0"
uv run bridge history fixtures/synthetic/case-smoke --db recovery.db
```

(b) No full response, killed after the request left:

```
BRIDGE_FAKE_CLIENT=1 BRIDGE_FAKE_FAULT=before_response_saved uv run bridge check fixtures/synthetic/case-smoke --db recovery.db   # exit 3
BRIDGE_FAKE_CLIENT=1 uv run bridge check fixtures/synthetic/case-smoke --db recovery.db   # "from api (source attempt 2 …)"; run 1 shows unknown_outcome 1
uv run bridge history fixtures/synthetic/case-smoke --db recovery.db
```

(b) No full response, timeout (four attempts with backoff, about 7 seconds):

```
BRIDGE_FAKE_CLIENT=timeout uv run bridge check fixtures/synthetic/case-smoke --db recovery.db   # exit 3, failed at extract, unknown_outcome=4
BRIDGE_FAKE_CLIENT=1 uv run bridge check fixtures/synthetic/case-smoke --db recovery.db   # "from api (source attempt 5 …)"
uv run bridge history fixtures/synthetic/case-smoke --db recovery.db
```

(c) Extraction stored, rules rolled back:

```
BRIDGE_FAKE_CLIENT=1 BRIDGE_FAKE_FAULT=in_rules uv run bridge check fixtures/synthetic/case-smoke --db recovery.db   # exit 3
BRIDGE_FAKE_CLIENT=1 uv run bridge check fixtures/synthetic/case-smoke --db recovery.db   # "from cache", "attempts this run: 0", 23 decisions
uv run bridge history fixtures/synthetic/case-smoke --db recovery.db
```

The first row of each history is the leftover `running` run, which the next check turned
into `failed` + `interrupted`. `*.db` files are git-ignored. The same scenarios run as
tests, with exact table counts before and after:

```
uv run pytest -q tests/test_recovery.py
```
