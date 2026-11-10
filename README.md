# bridge-evidence-check

A pre-attestation chart evidence checker for the Medicare GLP-1 Bridge.

Before a prescriber signs the Bridge attestation, someone has to check the patient's documents for each eligibility condition: BMI at the start of GLP-1 therapy, the qualifying comorbidities, and the exclusions. This tool reads a document packet and reports, for each condition, whether the documents support it, contradict it, conflict, lack the information, or need a human to decide — with verbatim evidence for every claim. An LLM (Claude) only extracts fields and quotes. Deterministic code verifies every quote against the source text, applies the CMS rules, and runs the evaluation.

## Current state

`bridge check` runs end to end on the seven dev variants of `splits.yaml`: one extraction call, quote verification, compute and rules, with every attempt stored. The first real-extractor run (`docs/checkpoint-a.md`) gave:

| Measure | Result |
|---|---|
| Conditions matching gold | 122 / 140 |
| PA-claim checks matching gold | 28 / 39 |
| False supports | 0 |
| Missed exclusions | 0 of 2 |
| Cost, 7 calls | $0.47 |

This is one run of one model on seven dev cases. It is not a holdout result and not an evaluation yet. Most misses come from one cause: the model labels the GLP-1 start `historical`, so no initiation date is anchored.

Reproduce offline, without a key:

```
BRIDGE_FAKE_CLIENT=1 uv run bridge check fixtures/synthetic/case-smoke --db /tmp/bridge.db
uv run python scripts/compare_gold.py --db /tmp/bridge.db --case fixtures/synthetic/case-smoke \
    --gold fixtures/synthetic/compare_gold/case-smoke-gold.json --out /tmp/compare.json
uv run pytest -q tests/test_public_outputs.py tests/test_baseline.py
```

The recorded dev extractions are in `replays/` (MTSamples quotes as offset and hash only); `reports/baseline-dev.json` is the regression baseline and `reports/checkpoint-a/` holds the per-case comparisons. `bridge eval --split dev --offline`, which will re-run the replays, is not implemented yet.

Run live (needs `ANTHROPIC_API_KEY` in `.env`; keep the database outside the checkout):

```
uv run python scripts/fetch_mtsamples.py
BRIDGE_DB=/path/outside/checkout/live.db uv run --env-file .env bridge check cases/case-07 --json
uv run python scripts/compare_gold.py --db /path/outside/checkout/live.db --case case-07 --out compare.json
uv run python scripts/export_replay.py --db /path/outside/checkout/live.db --case case-07
uv run python scripts/build_baseline.py --db /path/outside/checkout/live.db
```

A run stops before any call that would pass $1.00 per run or $5.00 per evaluation (ADR 0001).

## Data sources

- There is no real patient data from any EHR in this repository.
- MTSamples transcripts are downloaded at runtime by a script and are not committed.
- Excerpts from published case reports are used under CC BY, with attribution.
  Case 17 reproduces the Case 1 heading and narrative prose from Abhinav Karan,
  Julien Feghaly, Anamarys Blanco, and Calvin Choi, *Dual Culprit ST-Elevation
  Myocardial Infarction: A Rare but Complex Clinical Entity*, Cureus, 2025, 17(8), e90478.
  The excerpt preserves the wording and omits figures, videos, and captions.
  [DOI 10.7759/cureus.90478](https://doi.org/10.7759/cureus.90478) ·
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
- All other documents (referral letters, PA form drafts, authored cases) are synthetic.

## Running a check

`bridge check <case>` reads `<case>/input.yaml` and `docs/`, runs the extraction (`claude-sonnet-5-5`, prompt `prompts/extract-v3.md`, schema `src/bridge_check/schema.py`) and stores every attempt, raw response and extraction in SQLite (`./bridge.db`, or `--db` / `BRIDGE_DB`). It then verifies every extracted quote (`src/bridge_check/verify.py`: position, value-in-quote, sentence-level assertion check, PA-draft and wrong-patient exclusions) and stores one evidence row per fact. `compute.py` turns the verified evidence into facts (initiation date, document dates and timepoints, BMI candidates, age intervals, medication periods, normalized labs) and `rules.py` applies the decision tables of `docs/contracts.md` §3 with the thresholds and policies of `rules/bridge-v1.yaml`; the decisions and `status = completed` are written in one transaction, and a failure in compute or rules records `failed` at that stage and publishes no decision. `--json` carries `decisions[]`, `case_flags` and `human_workload`; `--explain` lists every decision with the rule step that fired, the evidence it used or excluded (as `doc_id[start:end] sha8` with reasons) and the computed values, as machine codes only. The verifier matches fixed patterns from two frozen tables, `rules/cues-v1.yaml` (cue words) and `rules/verify-terms-v1.yaml` (a matching lexicon: concept aliases, value labels, event and identifier words); it does not understand text, and a wording it does not know sends the fact to review. The SQLite file carries a store schema version (`PRAGMA user_version`); a `bridge.db` created by an older version is refused with exit 3 and must be deleted or replaced (`--db` / `BRIDGE_DB`), there are no migrations. `bridge history <case>` lists every run with its extraction and whether it came from the cache, a replay of a saved response, or a fresh API call.

```
BRIDGE_FAKE_CLIENT=1 uv run bridge check fixtures/synthetic/case-smoke --json   # offline, synthetic reply
uv run bridge history fixtures/synthetic/case-smoke
```

`BRIDGE_FAKE_CLIENT` selects a hand-written reply from `fixtures/synthetic/extract/` (`1`/`valid`, `no_tool_call`, `truncated`, `refusal`, `timeout`, `server_error`, `bad_request`); without it the real API is called and `ANTHROPIC_API_KEY` is needed (`uv run --env-file .env bridge check …` reads it from the git-ignored `.env`). Exit codes: 0 completed, 3 failed, 4 another run holds the lock. Logs are JSON lines on stderr and never contain document text.

Every run is bounded by the limits in `docs/adr/0001-global-limits.md` (`Limits` in `src/bridge_check/extract.py`): at most 4 API attempts, 1 of them parse-class, 5 minutes of wall clock, a request timeout, `max_tokens`, and two cost ceilings (per run and per eval) checked before each API call against the cost already spent plus a reservation for the next call; a call that would exceed a ceiling is refused with a message on stderr and exit 3, and nothing downstream runs. The extraction schema travels as the `input_schema` of a single non-strict tool, `record_extraction`, and the reply's tool input is validated locally (`docs/adr/0002-extraction-output-mode.md`). `uv run pytest -q -m live` makes one real call on the synthetic smoke case to check that the API accepts the request and the reply parses (needs the key; excluded from CI). The first live runs are recorded in `docs/live-run-01.md`.

## Data-line tools

Scripts the annotator uses to prepare and check gold (contract §7–§8, annotation guide §8–§10). None of them writes gold; `expected.json` is always written by a human.

- `scripts/fetch_mtsamples.py` — downloads the MTSamples mirror named in `cases/<id>/case.yaml`, verifies the whole-file sha256, selects the transcription by `sample_name` and per-transcription hash, and writes `cases/<id>/docs/D2-mtsamples-<row>.txt` byte-exact. Network only, no key. The downloaded text is git-ignored and never committed.
- `scripts/draft_authored.py` — route 1: a drafting spec (kept in the private repo) → the data-line model → authored documents plus a fact → quote map, then four deterministic checks (quote verbatim and unique, value inside the quote, assertion cue in the same sentence, requested wording present). Every raw reply is saved to the required `--raw-out` (a private path) before it is parsed. Needs `OPENAI_API_KEY`.
- `scripts/propose_candidates.py` — route 2: real documents → candidate facts with located quotes, written in the adjudication `candidate` shape (allow-list keys with controlled values only; the quote text stays in the raw reply, which the required `--raw-out` saves to a private path before parsing). Needs `OPENAI_API_KEY`.
- `scripts/keyword_scan.py` — deterministic scan of the W-01 terms (`rules/scan-terms-v1.yaml`) and every drug name in `rules/drugs-v2.yaml`; lists sentences not covered by any candidate quote as `doc_id`, offsets, `sha8` and term; a candidate covers a sentence only if it is `located` and its `sha8` still matches the text. With `--doc` every file needs an explicit de-identified `--doc-id` (file names are never used). No key.
- `scripts/validate_gold.py` — validates `blind_draft.json`, `adjudication.jsonl` and `expected.json` against the contract and guide shapes; prints field paths and error types only. No key.

Holdout variants listed in `splits.yaml` are never read by these tools, private outputs (`--raw-out`, `--out-record`) are refused inside the public checkout, and no tool writes an annotator-owned file (`expected.json`, `blind_draft.json`, `adjudication.jsonl`, `input.yaml`, `case.yaml`). Keys go in `.env` (see `.env.example`), which is git-ignored. Prompts, drafting specs, drafting records and raw model responses live in the private companion repo; the public repo holds only the tools, the frozen cue and scan-term tables, and the sanitized outputs. Install the extra dependency with `uv sync --group dev --group data`.

## License

This repository is not yet licensed. Third-party materials are used under their own licenses; see NOTICE (to be added).
