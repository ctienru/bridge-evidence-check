# Synthetic fixtures

Hand-written synthetic inputs for unit tests. Every sentence here was written for the tests;
nothing is copied from MTSamples, from a published case report, or from any case document.
These files are never used by `eval` and are not recorded model responses.

- `blind_draft_valid.json`, `adjudication_valid.jsonl`, `expected_valid.json` — valid examples
  of the three gold-side files (`scripts/validate_gold.py`).
- `drafting/spec.yaml` and `drafting/response_*.json` — a route 1 spec and model responses,
  one passing and one per failing deterministic check (`bridge_check.drafting`).
