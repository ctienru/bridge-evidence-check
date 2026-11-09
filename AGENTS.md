# Project rules (for coding agents)

## Language
All repo communication is in English: code, comments, README, docs, commit messages, PRs, issues, review replies.

## What this project is
A pre-attestation chart evidence checker for the Medicare GLP-1 Bridge.
The LLM only extracts fields and verbatim quotes. Quote verification, computation, rules, and evaluation are deterministic code.
The system outputs evidence statuses per condition. It never outputs "eligible" or "not eligible".

Machine-level names and rules (condition IDs, status codes, decision tables, schema, gold format, CI) are defined in `docs/contracts.md`. If code and that document disagree, stop and ask.

## Never do
- Do not create or edit `cases/*/expected.json` (gold is written by a human).
- Do not read or run variants marked `holdout` in `splits.yaml`.
- Do not print full document text, quotes, or patient names in logs, exceptions, or test output. Logs refer to evidence by `evidence_id` only (no MTSamples offsets). Public reports refer to evidence as `doc_id[start:end] sha8`.
- Do not put patient data in schema property names or enums.
- Do not enable SDK automatic retries (`max_retries=0`). Retries live only in `extract.py`, with a per-run budget: at most 4 API attempts per case run (including the first, at most 1 of them for parse/refusal/truncation) and at most 5 minutes in total.
- Do not mark a quote as verified using fuzzy similarity.
- Do not call `messages.parse()`. Save the raw response first, then validate.
- Do not add Streamlit, RAG, an agent framework, or PostgreSQL.
- Do not add a LICENSE file.
- Do not import `bridge_check.dataside` from the pipeline (`cli`, `extract`, `verify`, `compute`, `rules`, `store`).

## Models
- Extractor under test: `claude-sonnet-5-5` (Anthropic). Its output is verified, computed on and scored; it never becomes gold.
- Data side (`src/bridge_check/dataside/`, `scripts/draft_authored.py`, `scripts/propose_candidates.py`): `gpt-6.1-sol` (OpenAI). It has no dated snapshot ID, so every call records the response `model` field and a UTC timestamp in the raw archive (`--raw-out`, private repo) and in `drafted_by`.
- Neither model's output enters gold without human verification (annotation guide P-02, P-03).

## Invariants (tests must hold these)
- Without a verified GLP-1 start date, BMI sub-results and pathways A/B/C are never `supported`.
- Evidence whose position status is not `verbatim` or `normalized` never supports `supported` or `not_supported`.
- Evidence from a wrong-patient document is excluded from every condition.
- Evidence from the PA draft (`role: pa_draft`) never supports a clinical condition.
- If an extraction already exists for a cache key, do not call the API; still re-run verify, compute, and rules with current code.
- Exclusion sub-results are never `supported`; positive exclusion evidence returns `review`.
- Threshold comparisons use the unrounded BMI.
- The raw API response is committed to `attempts` before parsing.
- An unexpected exception in verify or compute fails the whole run (`failed`); no decisions are published.

## Work order
Read `rules/*.yaml` and `tests/` first; make existing tests pass. Do not change expected values in tests.
For new behavior, write a failing test first, then implement.
One issue → one branch → one PR. Keep PRs small.

## How to run (run these yourself and paste the output in the PR)
- Tests: `uv run pytest -x -q -m "not live"`; one file: `uv run pytest tests/test_rules.py -x`
- Lint and types: `uv run ruff check . && uv run ruff format --check . && uv run mypy --strict src` (required; pre-commit and CI also run mypy on `tests/` and `scripts/`)
- Evaluation: `uv run bridge eval --split dev --offline` (from item 7)
- Manifest check: `uv run python scripts/freeze_splits.py --check`

## Review checklist
See `docs/review-checklist.md` (to be added).

## Code review rules (for automated reviewers)
- Report only P0/P1: anything that can cause a false `supported`, duplicate API calls, an unrecorded attempt, a changed gold or holdout file, or document text in logs or public outputs.
- No style comments. Do not suggest new abstraction layers.
- Any change that turns a condition from non-supported to `supported` must point to the test that covers it.
- The extraction cache key must not include verifier versions; verification results must not enter the extraction cache.
- Threshold comparisons must not use rounded values.

Changes to this file go through a PR, like code. If an agent makes the same mistake twice, update this file.
