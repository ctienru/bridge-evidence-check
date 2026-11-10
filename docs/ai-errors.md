# What the AI got wrong

Errors made by the two kinds of AI in this project, what caught them, and the fix. The
extractor is the model under test (`claude-sonnet-5-5`); the coding agent writes code under
prompts and stops before commit. Sources: `docs/checkpoint-a.md`, `docs/live-run-01.md` and
the review rounds of the pull requests. Every row was caught by a test, a gold comparison or
a review before it reached `main`.

## Extractor

| What was wrong | Caught by | Fix |
|---|---|---|
| The GLP-1 start sentence was labelled `historical` because it carries a past date, so no initiation date was anchored and every BMI row fell to `insufficient`. Behind 24 of the 29 mismatching rows of the first checkpoint. | Gold comparison at checkpoint A | Compute anchors the initiation on dated event facts regardless of the temporality label |
| BMI facts carried `relative_to_glp1_initiation: unknown`, which raised `timing_disagreement` and capped 11 rows at `review`. | Checkpoint comparison after the anchoring fix | Contract change: an unknown model timepoint is not a disagreement |
| Identity facts named a date of birth that was not inside the quote (4 rows excluded as `value_not_in_quote`). | The value-in-quote verifier layer | Prompt `extract-v4` requires identity values inside their quote |
| A relative's diabetes was extracted as the patient's `t2dm`, and a relative's hypertension as the patient's. | Gold comparison; the assertion layer excluded the evidence (`wrong_patient`, `assertion_mismatch`) | No code change needed; the rows stayed correct because the verifier blocked the evidence |
| A commercial nutrition program was given `end_kind: unknown` instead of `ended`. | Gold comparison | Left as a sampled extraction error; the result erred toward `review` |

## Coding agent

| What was wrong | Caught by | Fix |
|---|---|---|
| The first live request put a `claim_id` outside the schema enum. | The first live call | Schema version 2 |
| The regression check only walked baseline rows, so a false support on a new row or a new variant was never detected. | Colleague review of the scoring pull request | The check walks every current row |
| A cache hit bypassed the replay path, so an offline evaluation could score a stale extraction. | Colleague review of the scoring pull request | Replays always run, with a replay-specific cache key |
| A symlink inside a dev case directory could point into a holdout directory, and a YAML parse error echoed file content. | Colleague review of the scoring pull request | Every path is resolved and checked before opening; YAML errors report the file name only |
| An early design cached decisions by extraction id, rules version and git SHA, so uncommitted verifier changes would have reused old decisions. | Design review before implementation | Only the extraction is cached; verify, compute and rules always run again |
