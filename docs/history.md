# History

One line per merged PR, in merge order. "Why" is the question the PR answered. Dates are US Eastern.

| PR | Date | What | Why |
|---|---|---|---|
| #2 | 11-08 | Repo skeleton: uv, ruff, mypy strict, pre-commit, CI | CI is green before any code exists |
| #4 | 11-08 | Rules table v1 schema and manifest checker | Policy values live in a versioned YAML table; CI fails on a missing rule id |
| #6 | 11-08 | Contract and annotation guide draft | The machine contract and the labeling rules are written before the code that follows them |
| #8 | 11-08 | Guide clauses reviewed for the two smoke cases | Gold may use only reviewed clauses |
| #10 | 11-08 | Data-side tools: drafting, candidates, keyword scan, validators, MTSamples fetch | Gold needs its own tools, kept apart from the extractor under test |
| #12 | 11-09 | Extraction, run state and SQLite store | Every API attempt is recorded before anything is computed from it |
| #14 | 11-09 | Gold for smoke case 01; hashes for case-15-L0 | The first gold case and the first hash-only row |
| #16 | 11-09 | Quote verification: position, value and assertion checks | An extracted fact counts only when its quote is found in the document |
| #18 | 11-09 | Annotation guide revision 01 (guide version 1) | Labeling questions from the first two gold cases became clauses |
| #21 | 11-09 | Guide clauses reviewed for the next gold cases | Gold may use only reviewed clauses |
| #23 | 11-09 | Compute and rules: decisions, pathways, claims | Decisions come from deterministic code, not from the model |
| #24 | 11-09 | Drug table v2 | The next cases name drugs the first table did not have |
| #26 | 11-09 | Global limits and cost ceilings | Attempts, time and cost are bounded before the first live call; that call was blocked by schema size |
| #28 | 11-09 | Extraction through non-strict tool use with local validation; first live run | The way past the schema-size limit |
| #29 | 11-09 | Dev gold for cases 02, 03, 04, 07, 07b and 17 | A dev set to measure against |
| #31 | 11-09 | Checkpoint A: first real-extractor run over the 7 dev variants | The first number on real extractions, and the root causes of its misses |
| #36 | 11-09 | Initiation anchored on dated event facts regardless of temporality | The main root cause found at checkpoint A |
| #38 | 11-09 | Model timepoint `unknown` is not a disagreement; identity values inside their quote | Second round of fixes after checkpoint A |
| #39 | 11-09 | Guide revision 02; gold version 2 for cases 01, 03, 17 | The guide items the holdout cases will hit were settled first; the dev gold they changed moved to version 2 with a change list |
| #42 | 11-09 | `freeze_splits` accepts hash-only rows | Holdout cases appear in this repository only as hashes |
| #43 | 11-09 | Scoring and `bridge eval`: two-level scoring, coverage matrix, regression check, CI job | One command scores the dev split and CI fails on a regression |
| #46 | 11-10 | Failure recovery: three fixed scenarios and rerun on a cached extraction | What happens when a run stops midway |
| #49 | 11-10 | `age_18` is `conflict` when verified intervals fall on opposite sides of 18 | Contradictory ages were not reported as a conflict |
| #48 | 11-10 | README, full version | What the tool checks, how, and with what limits |
| #51 | 11-10 | Holdout hashes for cases 14, 16, 11; eval skips hash-only dev rows | The holdout is frozen before the pipeline runs on it |
| #53 | 11-10 | Holdout evaluation: one run of the frozen configuration | The number on cases the pipeline was not tuned on |
| #54 | 11-22 | Annotator described as not a physician | Who wrote the gold |
| #56 | 11-23 | Docstrings for rules, compute and store; in-repo references only | The code can be read without documents outside the repository |
| #57 | 11-23 | Contract, fourth edition | Rules decided after the holdout run, and a list of known gaps between contract and code |
| #59 | 11-23 | Rules follow the contract in five known gaps | Close the gaps that need no new extraction |
| #61 | 11-23 | Guide version 3; lifestyle applicability; claim rule; relative time expressions | The remaining gaps that can be checked offline |
| #63 | 11-23 | Parse retry, prompt `extract-v5`, date binding; dev replays recorded again | The extraction weaknesses the holdout run showed |
