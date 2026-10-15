# garmin-llm

A local assistant that answers questions about my Garmin training data. A small language model running on a laptop turns a question into SQL, the SQL is checked and run against a DuckDB database, and the result is printed. No data leaves the machine.

```
$ python src/app.py "How many runs did I do in 2025?"
SQL (qwen2.5-coder:1.5b, 16.4 s):
SELECT COUNT(*) FROM activities WHERE start_time_local >= '2025-01-01' AND start_time_local < '2026-01-01' AND sport_group = 'running'

Result:
 count_star()
           81
```

The output above is from a test database with invented activities.

## Status

Work in progress. The plan and the session log are in [PROJECT.md](PROJECT.md).

| Part | State |
|---|---|
| Ingest of the Garmin Connect CSV export into DuckDB | Done |
| Environment check and first speed measurement | Done |
| Baseline assistant (question to SQL to result) | Done |
| Manual validation of the ingest | Done |
| Evaluation set (34 questions with gold SQL, plus 16 held-out) and harness | Done |
| Model and prompt experiments | Results table, schema-detail and plan-before-SQL experiments done |
| Synthetic data, so others can run it | Not started |

## Results

The evaluation set has 34 questions: 27 that the table can answer and 7 that it cannot, where the right reply is to decline. A generated query counts as correct when it returns the same result as the gold query on a frozen copy of the database. All runs are on my real data, so only aggregate metrics are published. Every run is at temperature 0 on the same 34 questions. A separate set of 16 held-out questions, written after these runs, checks which of the results carry over to new questions; see [Held-out check](#held-out-check).

Configurations, in the order they were run. "Examples v1" is three worked SQL examples in the prompt ([configs/fewshot_v1.yaml](configs/fewshot_v1.yaml)); "examples v2" adds one example of declining ([configs/fewshot_v2.yaml](configs/fewshot_v2.yaml)). "Retry" sends a query that failed back to the model once, with the error message. "Minimal schema" replaces the schema description [docs/schema.md](docs/schema.md) with [configs/schema_minimal.md](configs/schema_minimal.md): a `CREATE TABLE` statement with column names and types, the allowed values of `activity_type` and `sport_group`, and the rule for what "runs" means, but no units, column descriptions or notes on writing queries. "Plan" asks the model to write a short plan as SQL comments, one line per step, before the query (`--plan`), with "examples v3" ([configs/fewshot_v3.yaml](configs/fewshot_v3.yaml)): the v2 examples with such a plan before each query.

| # | Model | Prompt | Retry | Run |
|---|---|---|---|---|
| 1 | `qwen2.5-coder:1.5b` | zero-shot | no | `qwen2.5-coder_1.5b-e5e0a51f` |
| 2 | `qwen2.5-coder:7b` | zero-shot | no | `qwen2.5-coder_7b-a08b236d` |
| 3 | `qwen2.5-coder:7b` | examples v1 | no | `qwen2.5-coder_7b-00b15b66` |
| 4 | `qwen2.5-coder:7b` | examples v2 | no | `qwen2.5-coder_7b-669c9542` |
| 5 | `qwen2.5-coder:7b` | examples v2 | yes, first message | `qwen2.5-coder_7b-abc924b9` |
| 6 | `qwen2.5-coder:7b` | examples v2 | yes | `qwen2.5-coder_7b-3ff49b60` |
| 7 | `ministral-3:8b` | examples v2 | yes | `ministral-3_8b-22cea93a` |
| 8 | `qwen2.5-coder:7b` | examples v2, minimal schema | yes | `qwen2.5-coder_7b-37256498` |
| 9 | `qwen2.5-coder:7b` | examples v3, plan | yes | `qwen2.5-coder_7b-1df20b74` |

### Accuracy

| # | Correct overall | Execution accuracy | Valid SQL | Unanswerable declined | Answerable declined | Simple | Date logic | Window | Multi-step |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 10 of 34 | 10 of 27 | 27 of 34 | 0 of 7 | 0 of 27 | 6 of 9 | 4 of 7 | 0 of 5 | 0 of 6 |
| 2 | 17 of 34 | 12 of 27 | 26 of 29 | 5 of 7 | 0 of 27 | 8 of 9 | 3 of 7 | 0 of 5 | 1 of 6 |
| 3 | 17 of 34 | 17 of 27 | 28 of 34 | 0 of 7 | 0 of 27 | 9 of 9 | 6 of 7 | 0 of 5 | 2 of 6 |
| 4 | 21 of 34 | 15 of 27 | 22 of 28 | 6 of 7 | 0 of 27 | 8 of 9 | 5 of 7 | 0 of 5 | 2 of 6 |
| 5 | 23 of 34 | 17 of 27 | 25 of 25 | 6 of 7 | 3 of 27 | 8 of 9 | 6 of 7 | 1 of 5 | 2 of 6 |
| 6 | 23 of 34 | 17 of 27 | 26 of 28 | 6 of 7 | 0 of 27 | 8 of 9 | 6 of 7 | 1 of 5 | 2 of 6 |
| 7 | 21 of 34 | 17 of 27 | 27 of 30 | 4 of 7 | 0 of 27 | 9 of 9 | 6 of 7 | 0 of 5 | 2 of 6 |
| 8 | 22 of 34 | 17 of 27 | 27 of 29 | 5 of 7 | 0 of 27 | 9 of 9 | 5 of 7 | 1 of 5 | 2 of 6 |
| 9 | 22 of 34 | 16 of 27 | 27 of 28 | 6 of 7 | 0 of 27 | 9 of 9 | 4 of 7 | 1 of 5 | 2 of 6 |

Execution accuracy counts the 27 answerable questions. Valid SQL counts the replies that were queries rather than declines, and how many of them passed the guardrail and ran. With retry, the second reply is the one scored.

| # | Correct on the first try | Retried | Fixed by the retry | Ran after the retry |
|---|---|---|---|---|
| 5 | 21 of 34 | 6 | 2 | 3 |
| 6 | 21 of 34 | 6 | 2 | 4 |
| 7 | 19 of 34 | 6 | 2 | 3 |
| 8 | 21 of 34 | 3 | 1 | 1 |
| 9 | 20 of 34 | 6 | 2 | 5 |

### Speed

Medians per question, CPU-only (hardware below).

| # | Time to first token | Latency | Generated tokens/s | Prompt tokens | Generated tokens |
|---|---|---|---|---|---|
| 1 | 0.66 s | 4.06 s | 17.56 | 1082.5 | 52.0 |
| 2 | 2.77 s | 12.49 s | 4.76 | 1082.5 | 44.5 |
| 3 | 3.28 s | 21.29 s | 3.99 | 1356.5 | 63.5 |
| 4 | 2.85 s | 17.77 s | 4.48 | 1382.5 | 57.0 |
| 5, 6 | not comparable | not comparable | not comparable | 1382.5 | 61.0 |
| 7 | 3.60 s | 31.86 s | 3.22 | 1437.5 | 79.5 |
| 8 | 2.68 s | 18.42 s | 4.32 | 791.5 | 57.5 |
| 9 | 3.05 s | 31.58 s | 3.98 | 1503.0 | 103.0 |

Runs 5 and 6 reuse the cached first replies of run 4, with their old timings, so their speed does not describe live use. Run 7 generated its replies live, except four first replies cached from a smoke test, including its slowest request (136 s to the first token, a cold start). Runs 8 and 9 generated all their replies live, because the changed prompt gives every request a new cache key. The fairest speed comparison between the two models is generated tokens per second: about 4.5 for `qwen2.5-coder:7b` and 3.2 for `ministral-3:8b`.

### What the runs show

These are results on the main set, which the prompt was tuned on. The held-out check below shows that the gain from the examples and the retry does not carry over.

- The larger qwen model declines unanswerable questions that the small one always answered, but writes only slightly better SQL without examples.
- Three worked examples in the prompt improved the SQL and stopped the model from declining, because every example answered with SQL. One added example of declining brought that back.
- The retry fixed 2 of the 6 failed first replies in each retry run. In run 5 the retry message offered declining as a way out, and on 3 questions the model gave up on a question it could have answered. With that option removed (run 6) it no longer declined them, but it did not fix them either.
- A second model family, `ministral-3:8b` with the best configuration, matches qwen on answerable questions (17 of 27 each) and is behind on unanswerable ones (4 of 7 declined against 6). It generates about 30% fewer tokens per second. The examples and the retry message were written after reading qwen's failures, which may favour qwen.
- The column descriptions do not help. With only names, types and category values (run 8) the best configuration scores 17 of 27 on answerable questions, the same as with the full description (run 6), on a prompt about 43% shorter (791.5 against 1382.5 median prompt tokens). Six questions changed verdict between the two runs, in both directions. The failure labels pointed this way: wrong columns and wrong units are rare in every labelled run.
- A plan before the query (run 9) did not help either: 16 of 27 answerable questions against 17, with window and multi-step questions unchanged at 1 of 5 and 2 of 6. The model did write the plans (28 of 34 first replies start with one; the other 6 are declines), and generated about 70% more tokens per answer (103 against 61 median). Eight questions changed verdict, in both directions.
- Window-function questions are the weak spot of every configuration: 1 of 5 at best. Multi-step questions are at most 2 of 6.
- Between runs 3 and 4, two answerable questions flipped from correct to wrong for reasons unrelated to the added example. With 27 answerable questions, a difference of about two questions is noise.

`duckdb-nsql:7b`, a model trained for DuckDB SQL, was tried first as the second family: it got none of four questions right in a smoke test, with or without the examples, so it was not run on the full set.

The examples and the retry message were written after reading failures on these same 34 questions, and runs 1 to 7 are scored on them, so the later rows are likely to flatter the method.

### Held-out check

To test that, 16 new questions ([eval/questions_heldout.yaml](eval/questions_heldout.yaml)) were written after the runs above, with a similar mix: 3 simple, 3 date logic, 4 window, 3 multi-step and 3 unanswerable. They were verified on the real data like the main set, and no prompt change may be based on the model's failures on them. The two ends of the tuning were run on them with `qwen2.5-coder:7b`, the best configuration with `ministral-3:8b`, and the best configuration with the minimal schema and with a plan:

|                                        | qwen 7b, zero-shot (as run 2) | qwen 7b, examples v2 and retry (as run 6) | ministral 8b, examples v2 and retry (as run 7) | qwen 7b, minimal schema (as run 8) | qwen 7b, plan (as run 9) |
| -------------------------------------- | ----------------------------- | ----------------------------------------- | ---------------------------------------------- | ---------------------------------- | ------------------------ |
| Correct overall                        | 7 of 16                       | 7 of 16                                   | 7 of 16                                        | 8 of 16                            | 6 of 16                  |
| Execution accuracy                     | 6 of 13                       | 6 of 13                                   | 7 of 13                                        | 7 of 13                            | 5 of 13                  |
| Valid SQL                              | 10 of 15                      | 13 of 15                                  | 15 of 16                                       | 14 of 15                           | 13 of 15                 |
| Unanswerable declined                  | 1 of 3                        | 1 of 3                                    | 0 of 3                                         | 1 of 3                             | 1 of 3                   |
| Fixed by the retry                     |                               | 0 of 4                                    | 1 of 3                                         | 0 of 3                             | 0 of 3                   |
| Simple, date logic, window, multi-step | 3/3, 2/3, 0/4, 1/3            | 3/3, 1/3, 1/4, 1/3                        | 3/3, 2/3, 1/4, 1/3                             | 3/3, 1/3, 1/4, 2/3                 | 3/3, 1/3, 0/4, 1/3       |
| Median latency                         | 17.16 s                       | 28.26 s                                   | 36.32 s                                        | 20.74 s                            | 34.7 s                   |
| Run                                    | `qwen2.5-coder_7b-e61d0f58`   | `qwen2.5-coder_7b-dc128d9a`               | `ministral-3_8b-b0bb4e2c`                      | `qwen2.5-coder_7b-2dc2c765`        | `qwen2.5-coder_7b-1ce29e57` |

On the main set the same two configurations score 17 and 23 of 34. On the held-out questions they score the same. The examples make more queries run, but the extra queries are wrong, and the decline example does not raise the declines. The six-question gain on the main set is therefore best read as fitted to those questions, not as a general improvement. Sixteen questions is a small set and does not prove that the effect is zero, but zero-shot scores about the same share on both sets (44% and 50%), so the held-out questions are not simply harder.

The model comparison holds on the held-out set: `ministral-3:8b` is level with qwen on answerable questions (7 of 13 against 6 of 13, within noise) and declines none of the three unanswerable ones, against one for qwen. It was the slowest of the three runs.

The minimal schema holds on the held-out set too: 7 of 13 answerable questions against 6 of 13 with the full description, a difference of one question. The schema description was written before any of the runs, so this comparison is not affected by tuning on the main set.

The plan does not help on the held-out set: 5 of 13 answerable questions against 6 of 13, and none of the 4 window questions. Neither more context about the table nor a written plan moves the window and multi-step questions with this model.

### Reference: a hosted model

To check whether the questions themselves are hard, both sets were run once on a hosted model, `claude-haiku-5-5` (Claude Haiku 5.5) through the Anthropic API, zero-shot and without retry. The assistant itself stays local; this run is a reference point only. Only the prompt leaves the machine: instructions, schema and question, all of which are public in this repository. The queries run locally, and the retry is refused for hosted models because DuckDB error messages can quote values from the data. Haiku 5.5 accepts no temperature or seed, so its replies cannot be reproduced exactly; the stored replies make the scoring reproducible. Thinking was turned off, so it answers directly like the local models.

|                                        | qwen 7b, zero-shot (run 2)    | qwen 7b, best (run 6)         | Haiku 5.5, zero-shot          |
| -------------------------------------- | ----------------------------- | ----------------------------- | ----------------------------- |
| Main set, correct overall              | 17 of 34                      | 23 of 34                      | 31 of 34                      |
| Main set, execution accuracy           | 12 of 27                      | 17 of 27                      | 24 of 27                      |
| Main set, unanswerable declined        | 5 of 7                        | 6 of 7                        | 7 of 7                        |
| Main set, simple, date, window, multi  | 8/9, 3/7, 0/5, 1/6            | 8/9, 6/7, 1/5, 2/6            | 8/9, 6/7, 5/5, 5/6            |
| Held-out, correct overall              | 7 of 16                       | 7 of 16                       | 16 of 16                      |
| Held-out, execution accuracy           | 6 of 13                       | 6 of 13                       | 13 of 13                      |
| Held-out, window                       | 0 of 4                        | 1 of 4                        | 4 of 4                        |
| Runs (main, held-out)                  | `a08b236d`, `e61d0f58`        | `3ff49b60`, `dc128d9a`        | `995023bf`, `c34994c1`        |

Run names are shortened; the full names are `qwen2.5-coder_7b-...` and `claude-haiku-5-5-...`. The two runs used 96,421 input and 5,902 output tokens, about $0.013 at the listed price of $0.10 and $0.50 per million. The median latency was 1.17 s per question on the main set, against 12 to 30 s on the laptop; network and data-centre hardware make that a context figure, not a comparison.

None of Haiku's three main-set failures is a wrong approach. Two return the right answer with extra columns; with them dropped, both match the gold query. The third puts a sentence before an otherwise well-formed query, so the guardrail refuses it. That query uses the `avg_pace_s_per_km` column, which [docs/schema.md](docs/schema.md) describes as timer time divided by distance, where the question asks for that division. In the data the two differ slightly (median 0.25 s per km over 302 runs, more than 1 s for 6 of them), enough to miss the 0.005 tolerance. So the schema description is slightly wrong there, and a model that trusts it is misled.

A capable model answers every held-out question and all nine window questions. The questions and gold queries hold up, and the failures of the local models come from the models, not from ambiguous questions. That agrees with the two prompt experiments above: neither more schema detail nor a written plan moved the window and multi-step questions with the 7b model.

### Why the queries fail

Failures on answerable questions were labelled by hand for five runs, by reading the model's SQL next to the gold SQL:

| Category              | 1: 1.5b zero-shot | 2: 7b zero-shot | 6: 7b, examples and retry | 7: ministral, examples and retry | 9: 7b, plan |
| --------------------- | ----------------- | --------------- | ------------------------- | -------------------------------- | ----------- |
| Missing step          | 6                 | 5               | 5                         | 4                                | 3           |
| Wrong aggregation     | 5                 | 4               | 0                         | 1                                | 1           |
| Wrong date logic      | 3                 | 4               | 2                         | 3                                | 2           |
| Wrong column or table | 1                 | 1               | 1                         | 1                                | 0           |
| Wrong units           | 0                 | 0               | 1                         | 0                                | 0           |
| Other                 | 2                 | 1               | 1                         | 1                                | 5           |
| Failures              | 17                | 15              | 10                        | 10                               | 11          |

"Missing step" means the query answers a simpler question than the one asked, for example monthly totals where a running total was asked. The examples and the retry removed most aggregation mistakes; the missing steps stayed, in both model families, and most of them are on window-function questions. The labels are in [eval/labels/](eval/labels/).

The labels of run 9 also judge the plan the model wrote before each failed query. In 6 of the 11 failures the plan was right and the query did not follow it: for one question the plan asks for a cumulative sum per month and the query sums each month without accumulating. In 3 the plan only restated the hard part of the question ("find the longest run", "identify consecutive days") without a way to do it; these are the hardest window questions. In 2 the plan itself was wrong and the query followed it. Two of the questions that broke with the plan return a correct answer plus an extra column, the total the plan mentions; with that column dropped both match the gold query. These are labelled "other". So the 7b model can often break a question into the right steps, but its SQL does not follow them, and on the hardest questions it cannot break them down. Only main-set failures were read, by the held-out rule.

The numbers come from the files in [results/processed/summaries/](results/processed/summaries/), one per run. Numbers count as equal when they differ by at most 0.005, so an answer rounded to two decimals is accepted. The tolerance was 0.001 until run 7, where one query was right except for rounding; every failure of runs 1 to 6 was re-checked at 0.005 and none changes, so their summary files still record 0.001.

## How it works

1. `src/prompt.py` builds the prompt: instructions, the table schema from [docs/schema.md](docs/schema.md), then the question.
2. `src/generate_sql.py` sends it to the model through an OpenAI-compatible endpoint and extracts the SQL from the reply.
3. `src/guardrails.py` allows only a single `SELECT` that reads the `activities` table, using DuckDB's own parser.
4. `src/app.py` runs the query on a read-only connection with no file or network access, a timeout and a row limit.

The model is reached only through the OpenAI-compatible API, so a different server can be used by setting `LLM_BASE_URL` and `LLM_MODEL`.

For the hosted reference run only, `eval/run_eval.py` sends models whose name starts with `claude-` through the Anthropic Python SDK (`src/send_anthropic.py`), with the same prompt text.

## How it is evaluated

- [eval/questions.yaml](eval/questions.yaml) holds the questions and a gold SQL query for each. Expected answers are computed by running the gold query, never typed by hand.
- [eval/questions_heldout.yaml](eval/questions_heldout.yaml) holds 16 held-out questions in the same format, run with `--questions eval/questions_heldout.yaml`. Their runs get their own run names.
- `eval/run_eval.py` runs every question through one configuration and compares result sets with `eval/score.py`: numbers may differ by at most 0.005, column names are ignored, and row order counts only where the question asks for it.
- Every model reply is cached on disk, keyed by the full request, so an interrupted run continues where it stopped.
- `--examples` adds the worked examples in a file such as [configs/fewshot_v2.yaml](configs/fewshot_v2.yaml) to the prompt. The examples are not eval questions.
- `--retry` sends a failed query back to the model once, with the error message.
- `--plan` asks for a short plan as SQL comments before the query. The comments keep the reply a single valid query, so the guardrail and DuckDB need no change; a decline after comment lines still counts as a decline.
- `--schema` replaces the schema description in the prompt, for example with [configs/schema_minimal.md](configs/schema_minimal.md). The schema is part of the system prompt, whose hash is in the run name.
- `eval/summarize.py` writes the aggregate metrics for a run.

## Hardware and speed

Everything so far runs CPU-only on a ThinkPad T490 (Intel i7-8665U, 32 GB RAM) with [Ollama](https://ollama.com). With `qwen2.5-coder:1.5b` it generates about 15 tokens per second in the benchmark; in the eval runs the median was 17.56 tokens per second for the 1.5b model, 4.76 for `qwen2.5-coder:7b` and 3.22 for `ministral-3:8b`. In the benchmark, a cold request took 21.8 seconds, of which 15.1 seconds went to reading the 1039-token schema prompt. The schema sits at the start of every prompt so that the server's cache covers it on later questions.

Details and the raw measurements are in [docs/environment.md](docs/environment.md) and `results/raw/environment/`.

## Running it

The repository does not include data. It needs your own Garmin export until the synthetic dataset exists.

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

ollama pull qwen2.5-coder:1.5b
```

1. In Garmin Connect, open Activities and use Export CSV. Save the file as `data/raw/Activities.csv`.
2. Create `data/private/place_names.txt` with one place name per line. These are stripped from the start of activity titles. The file may be empty.
3. Load the data: `python src/ingest_csv.py`
4. Ask a question: `python src/app.py "What was my longest run?"`

The eval needs a frozen copy of the database (`python scripts/freeze_snapshot.py`) and then runs with, for example:

```
ollama pull qwen2.5-coder:7b
python eval/run_eval.py --model qwen2.5-coder:7b --examples configs/fewshot_v2.yaml
```

The hosted reference run needs an Anthropic API key in `ANTHROPIC_API_KEY` and runs with `python eval/run_eval.py --model claude-haiku-5-5`.

The gold queries in `eval/questions.yaml` were verified against my data. On another export they still run, but nobody has checked that their answers are right for it.

## Privacy

- The raw export, the database and anything derived from individual activities are gitignored.
- Activity titles are not loaded as they are; leading place names are removed, and the table has no location columns.
- Aggregate figures about the real data (row counts, date range, ranges) appear in the docs on purpose. Individual activities are not published.
- The hosted reference run sends only the prompt (instructions, schema, examples, question) to the Anthropic API. Queries run locally, and the retry, whose message can quote values from the data, is refused for hosted models.

The rules are in the Privacy section of [PROJECT.md](PROJECT.md).

## Documents

- [PROJECT.md](PROJECT.md): plan, decisions, session log
- [docs/schema.md](docs/schema.md): the `activities` table, also used as the model's schema context
- [docs/data_notes.md](docs/data_notes.md): quirks of the export and how the ingest handles them
- [docs/environment.md](docs/environment.md): machine, versions, model digest, measurements
- [docs/validation.md](docs/validation.md): manual check of the ingest
- [eval/questions.yaml](eval/questions.yaml): the evaluation questions and gold SQL
- [eval/questions_heldout.yaml](eval/questions_heldout.yaml): the held-out questions
- [results/processed/summaries/](results/processed/summaries/): aggregate metrics per eval run
- [eval/labels/](eval/labels/): hand-made error labels for the failures of four runs
