# bridge-evidence-check

A pre-attestation chart evidence checker for the Medicare GLP-1 Bridge.

Before a prescriber signs the Bridge attestation, someone has to check the patient's documents for each eligibility condition: BMI at the start of GLP-1 therapy, the qualifying comorbidities, and the exclusions. This tool reads a document packet and reports, for each condition, whether the documents support it, contradict it, conflict, lack the information, or need a human to decide — with verbatim evidence for every claim. An LLM (Claude) only extracts fields and quotes. Deterministic code verifies every quote against the source text, applies the CMS rules, and runs the evaluation.

## Status

In progress. Nothing here is usable yet.

## Data sources

- There is no real patient data from any EHR in this repository.
- MTSamples transcripts are downloaded at runtime by a script and are not committed.
- Excerpts from published case reports are used under CC BY, with attribution.
- All other documents (referral letters, PA form drafts, authored cases) are synthetic.

## License

This repository is not yet licensed. Third-party materials are used under their own licenses; see NOTICE (to be added).
