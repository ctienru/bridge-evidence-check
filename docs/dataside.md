# Data-side tools

How gold for a case is produced with the data-side tools (planning 05 §5.2; annotation
guide P-04, §8–§10; contract §7–§8). The data side uses `gpt-6.1-sol`; its output never
enters gold without Terri's verification. The extractor under test (`claude-sonnet-5-5`)
is never involved here.

## Route 1 — authored documents (referral letter, PA draft)

1. **Terri writes, or reviews and approves, the spec** (private repo; a draft may be proposed by
   the coding agent and is kept under `records/<case>/drafts/`): `case_id`, the documents (`doc_id`, `role`,
   instructions) and the facts each must contain (value, unit, three axes, `event_date`,
   `must_use` dirty wordings).
2. **`scripts/draft_authored.py`** `--spec` `--prompt` `--out-docs` `--out-record` `--raw-out`:
   calls the model, archives every raw reply (`--raw-out`, private), parses it, requires the
   document and fact id sets to equal the spec, and runs the four deterministic checks per
   fact (quote verbatim and unique; value inside the quote; assertion cue in the same
   sentence; `must_use` present). All pass → documents to `--out-docs`, drafting record
   (`drafted_by`, `drafted_at`, `quote_map`, `checks`) to `--out-record` (private).
3. **Terri reads the final documents** both ways: every spec fact is written, no clinical fact
   beyond the spec. She copies `drafted_by` into `case.yaml` `documents[].drafted_by`.
4. **Terri writes the gold facts** for these documents from the spec and the quote map
   (`origin: spec`), with one adjudication line each (L-02).

## Route 2 — real text (MTSamples transcript, case-report passage)

1. **`scripts/fetch_mtsamples.py`** downloads the mirror, verifies the whole-file sha256,
   selects the transcription by `sample_name` + per-text hash and writes
   `cases/<id>/docs/D2-mtsamples-<row>.txt` (git-ignored, never committed).
2. **Terri blind-labels** every condition status and fills the inventory table
   (`blind_draft.json`, B-01–B-03) before seeing any model output. Never edited afterwards.
3. **`scripts/propose_candidates.py`** `--case` (or `--doc` + `--doc-id`) `--guide` `--prompt`
   `--out` `--raw-out`: archives the raw reply first (private), then writes candidates with
   verbatim-located quotes (`start`, `end`, `sha8`) in the adjudication `candidate` shape:
   L-01 allow-list keys with controlled values plus `location`. No quote text in `--out`.
4. **`scripts/keyword_scan.py`** `--case` (or `--doc` + `--doc-id`) `--candidates` `--out`:
   W-01 terms plus every drug name; lists sentences no `located` candidate covers
   (`doc_id`, `start`, `end`, `sha8`, `term`).
5. **Terri verifies every scored fact** one by one: candidates, uncovered hits, inventory
   rows without a candidate; decides every condition status by hand; writes `reason`.
6. **Terri writes `adjudication.jsonl`** (one line per item, L-01–L-03) and `expected.json`.
7. **`scripts/validate_gold.py`** `--blind` `--adjudication` `--gold` validates the three files;
   then `scripts/freeze_splits.py --check` after the hashes are added to `splits.yaml`.

## Where files live

| File | Public repo | Private repo |
|---|---|---|
| `case.yaml`, `input.yaml`, authored `docs/*.txt`, `blind_draft.json`, `adjudication.jsonl`, `expected.json` (dev cases) | yes | — |
| `docs/D2-mtsamples-*.txt` | downloaded at run time, git-ignored | — |
| Drafting spec, prompts (`--prompt`), drafting record (`--out-record`) | — | yes |
| Raw model replies (`--raw-out`) | — | yes (never inside the public checkout; the tools refuse such paths) |
| `rules/cues-v1.yaml`, `rules/scan-terms-v1.yaml`, `fixtures/synthetic/` | yes | — |
| Holdout cases, case-15 ladder levels | hashes only in `splits.yaml` | files |

The tools never read a holdout variant (checked on the path as written and as resolved),
never write an annotator-owned file (`expected.json`, `blind_draft.json`,
`adjudication.jsonl`, `input.yaml`, `case.yaml`) or `splits.yaml`, and never print
document text, quotes or patient names.

## Import boundary

`src/bridge_check/dataside/` (drafting, candidates, OpenAI wrapper) is used only by the scripts above. The pipeline (`cli`, `extract`, `verify`,
`compute`, `rules`, `store`) never imports it; `tests/test_import_boundary.py` fails if it
does. Shared modules (`enums`, `gold_schema`, `manifest`, `text`, `rules_schema`, `cues`,
`sentences`) may be used by both sides; the verifier uses the same cue table and splitter as
the drafting checks.

Two frozen tables feed the verifier: `rules/cues-v1.yaml` (the cue words of guide §3.2) and
`rules/verify-terms-v1.yaml`, a matching lexicon (concept aliases, value labels, event words,
identifier labels, lifestyle cues). Both are fixed-pattern lookups, not semantic
understanding: an unlisted wording is not recognised and the fact goes to review. A change
to either file is a change to the verifier and bumps its `version`.
