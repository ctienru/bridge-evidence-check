# Synthetic fixtures

Hand-written synthetic inputs for unit tests. Every sentence here was written for the tests;
nothing is copied from MTSamples, from a published case report, or from any case document.
These files are never used by `eval` and are not recorded model responses.

- `blind_draft_valid.json`, `adjudication_valid.jsonl`, `expected_valid.json` — valid examples
  of the three gold-side files (`scripts/validate_gold.py`).
- `drafting/spec.yaml` and `drafting/response_*.json` — a route 1 spec and model responses,
  one passing and one per failing deterministic check (`bridge_check.drafting`).
- `case-smoke/` — a synthetic case (`input.yaml` and three short documents) for the
  pipeline tests and the offline `bridge check`.
- `extract/response_*.json` — raw `Message` replies for `bridge_check.fake_client`: a valid
  extraction of `case-smoke` (every quote verbatim), invalid JSON, a schema violation,
  a truncated reply (`max_tokens`) and a refusal. Timeouts and HTTP errors are raised as
  SDK exceptions by the fake client, not stored as files.
- `verify/<name>/` — negative fixtures for quote verification: `input.yaml`, `docs/` and one
  scripted extraction reply (`fake-reply.json`) each. With `BRIDGE_FAKE_CLIENT=1`, `bridge
  check fixtures/synthetic/verify/<name> --json --stop-after verify` uses that reply and shows
  one verifier behaviour: a fabricated quote, a paraphrased quote, a changed value, negation
  scope, family history (guide A-10), repeated quotes, a table line, a wrong-patient
  document, a PA-draft-only fact, a CRLF document and an NFKC document. The first line of
  each `input.yaml` says what it demonstrates. `verify/crlf/docs/` is kept byte-exact by
  `.gitattributes`.
