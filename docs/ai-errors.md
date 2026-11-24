# What the AI got wrong

Errors made by the two kinds of AI in this project, what caught them, and the fix. The
extractor is the model under test (`claude-sonnet-5-5`); the coding agent writes code under
prompts and stops before commit. Sources: `docs/checkpoint-a.md`, `docs/live-run-01.md` and
the review rounds of the pull requests. Every row but the last one of the extractor table was
caught by a test, a gold comparison or a review before it reached `main`; that last row is on
`main` and is not fixed.

## Extractor

| What was wrong | Caught by | Fix |
|---|---|---|
| The GLP-1 start sentence was labelled `historical` because it carries a past date, so no initiation date was anchored and every BMI row fell to `insufficient`. Behind 24 of the 29 mismatching rows of the first checkpoint. | Gold comparison at checkpoint A | Compute anchors the initiation on dated event facts regardless of the temporality label |
| BMI facts carried `relative_to_glp1_initiation: unknown`, which raised `timing_disagreement` and capped 11 rows at `review`. | Checkpoint comparison after the anchoring fix | Contract change: an unknown model timepoint is not a disagreement |
| Identity facts named a date of birth that was not inside the quote (4 rows excluded as `value_not_in_quote`). | The value-in-quote verifier layer | Prompt `extract-v4` requires identity values inside their quote |
| A relative's diabetes was extracted as the patient's `t2dm`, and a relative's hypertension as the patient's. | Gold comparison; the assertion layer excluded the evidence (`wrong_patient`, `assertion_mismatch`) | No code change needed; the rows stayed correct because the verifier blocked the evidence |
| A commercial nutrition program was given `end_kind: unknown` instead of `ended`. | Gold comparison | Left as a sampled extraction error; the result erred toward `review` |
| On the holdout cases one document date was written in a shape the schema rejects and failed the whole run; baseline values carried a wrong `event_date` or none bound to them; exclusion evidence was returned with a wrong assertion or not at all. | The holdout evaluation of 2026-11-10 (`docs/holdout-eval.md`): local schema validation, then the gold comparison | One more attempt after a failed validation; prompt `extract-v5` (date shapes, `event_date` only from the quote, document dates, every exclusion mention); the verifier binds the only date of a clause to its value across a label. The three holdout cases are no longer untouched |
| On the second holdout batch the drug of the GLP-1 start was returned as a brand name followed by the ingredient in parentheses. The name resolver, which mapped only a bare brand or a bare ingredient, did not resolve that form, so no initiation date was verified. Behind 30 of the 37 wrong rows of that run. | The holdout evaluation of 2026-11-23 (`docs/holdout-eval.md`): the gold comparison, then a call of the resolver on the stored strings | The resolver accepts a brand written with exactly its own ingredient in parentheses, in either order, and leaves every other parenthetical name unresolved (contract §5). The holdout cases were not run again |
| Evidence excluded for unknown timing is ignored when it contradicts the counted evidence. In one case of the second holdout batch the document-date fact for one document was not returned, so that document's height, weight and BMI carried no date and were excluded as `timing_unknown`; only the BMI stated in another document was counted, the disagreement between the two documents was not seen, and two rows are `supported` where gold has `conflict` and `review`: two false supports. | The regression replay of holdout batch 2 made on 2026-11-23 after the resolver fix (`docs/holdout-eval.md`): the gold comparison | Not fixed |

## Coding agent

| What was wrong | Caught by | Fix |
|---|---|---|
| The first live request put a `claim_id` outside the schema enum. | The first live call | Schema version 2 |
| The regression check only walked baseline rows, so a false support on a new row or a new variant was never detected. | Colleague review of the scoring pull request | The check walks every current row |
| A cache hit bypassed the replay path, so an offline evaluation could score a stale extraction. | Colleague review of the scoring pull request | Replays always run, with a replay-specific cache key |
| A symlink inside a dev case directory could point into a holdout directory, and a YAML parse error echoed file content. | Colleague review of the scoring pull request | Every path is resolved and checked before opening; YAML errors report the file name only |
| An early design cached decisions by extraction id, rules version and git SHA, so uncommitted verifier changes would have reused old decisions. | Design review before implementation | Only the extraction is cached; verify, compute and rules always run again |
