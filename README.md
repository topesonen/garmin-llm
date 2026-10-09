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
| Evaluation set (34 questions with gold SQL) and harness | Done |
| Model and prompt experiments | In progress |
| Synthetic data, so others can run it | Not started |

## Results so far

The evaluation set has 34 questions: 27 that the table can answer and 7 that it cannot, where the right reply is to decline. A generated query counts as correct when it returns the same result as the gold query on a frozen copy of the database. All runs are on my real data, so only aggregate metrics are published.

| Configuration | Correct overall | Execution accuracy (answerable) | Unanswerable declined | Median latency |
|---|---|---|---|---|
| `qwen2.5-coder:1.5b`, zero-shot | 10 of 34 | 10 of 27 | 0 of 7 | 4.06 s |
| `qwen2.5-coder:7b`, zero-shot | 17 of 34 | 12 of 27 | 5 of 7 | 12.49 s |
| `qwen2.5-coder:7b`, 3 SQL examples | 17 of 34 | 17 of 27 | 0 of 7 | 21.29 s |
| `qwen2.5-coder:7b`, 3 SQL examples and 1 example of declining | 21 of 34 | 15 of 27 | 6 of 7 | 17.77 s |
| The same, with one retry after a failed query | 23 of 34 | 17 of 27 | 6 of 7 | not comparable |

The retry run reuses the cached first replies of the row above it, so its latency does not describe live use. The retry row is the second of two retry runs; the first had the same three scores and is described below.

What the runs show:

- The larger model declines unanswerable questions that the small one always answered, but writes only slightly better SQL without examples.
- Three worked examples in the prompt improved the SQL and stopped the model from declining, because every example answered with SQL. One added example of declining brought that back.
- Without a retry, no configuration has answered any of the 5 window-function questions correctly.
- Between the last two rows, two answerable questions flipped from correct to wrong for reasons unrelated to the added example. With 27 answerable questions, a difference of about two is noise.

- The retry sends a query that failed back to the model once, with the error message. 6 of the 34 first replies failed; the retry fixed 2 of them, among them the first correct window-function answer. In a first version the retry message offered declining as a way out, and on 3 of the 6 the model gave up on a question it could have answered. With that option removed it no longer declined them, but it did not fix them either: twice it repeated the same failing query, once it wrote a query that ran and was wrong.

By category, the best run (last row) got 8 of 9 simple questions, 6 of 7 date-logic, 1 of 5 window, 2 of 6 multi-step and 6 of 7 unanswerable.

The first retry run is the only one in which an answerable question was declined (3 of 27).

The examples and the retry message were written after reading failures on these same 34 questions, and every run is scored on them, so the later rows are likely to flatter the method. There is no held-out set yet.

### Why the queries fail

Failures on answerable questions were labelled by hand for three runs, by reading the model's SQL next to the gold SQL:

| Category | 1.5b zero-shot | 7b zero-shot | 7b, examples and retry |
|---|---|---|---|
| Missing step | 6 | 5 | 5 |
| Wrong aggregation | 5 | 4 | 0 |
| Wrong date logic | 3 | 4 | 2 |
| Wrong column or table | 1 | 1 | 1 |
| Wrong units | 0 | 0 | 1 |
| Other | 2 | 1 | 1 |
| Failures | 17 | 15 | 10 |

"Missing step" means the query answers a simpler question than the one asked, for example monthly totals where a running total was asked. The examples and the retry removed the aggregation mistakes; the missing steps stayed, and four of the five in the last column are window-function questions. The labels are in [eval/labels/](eval/labels/).

The numbers come from the files in [results/processed/summaries/](results/processed/summaries/), one per run.

## How it works

1. `src/prompt.py` builds the prompt: instructions, the table schema from [docs/schema.md](docs/schema.md), then the question.
2. `src/generate_sql.py` sends it to the model through an OpenAI-compatible endpoint and extracts the SQL from the reply.
3. `src/guardrails.py` allows only a single `SELECT` that reads the `activities` table, using DuckDB's own parser.
4. `src/app.py` runs the query on a read-only connection with no file or network access, a timeout and a row limit.

The model is reached only through the OpenAI-compatible API, so a different server can be used by setting `LLM_BASE_URL` and `LLM_MODEL`.

## How it is evaluated

- [eval/questions.yaml](eval/questions.yaml) holds the questions and a gold SQL query for each. Expected answers are computed by running the gold query, never typed by hand.
- `eval/run_eval.py` runs every question through one configuration and compares result sets with `eval/score.py`: numbers may differ by at most 0.001, column names are ignored, and row order counts only where the question asks for it.
- Every model reply is cached on disk, keyed by the full request, so an interrupted run continues where it stopped.
- `--examples` adds the worked examples in a file such as [configs/fewshot_v2.yaml](configs/fewshot_v2.yaml) to the prompt. The examples are not eval questions.
- `--retry` sends a failed query back to the model once, with the error message.
- `eval/summarize.py` writes the aggregate metrics for a run.

## Hardware and speed

Everything so far runs CPU-only on a ThinkPad T490 (Intel i7-8665U, 32 GB RAM) with [Ollama](https://ollama.com). With `qwen2.5-coder:1.5b` it generates about 15 tokens per second in the benchmark; in the eval runs the median was 17.56 tokens per second for the 1.5b model and 4.76 for `qwen2.5-coder:7b`. In the benchmark, a cold request took 21.8 seconds, of which 15.1 seconds went to reading the 1039-token schema prompt. The schema sits at the start of every prompt so that the server's cache covers it on later questions.

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

The gold queries in `eval/questions.yaml` were verified against my data. On another export they still run, but nobody has checked that their answers are right for it.

## Privacy

- The raw export, the database and anything derived from individual activities are gitignored.
- Activity titles are not loaded as they are; leading place names are removed, and the table has no location columns.
- Aggregate figures about the real data (row counts, date range, ranges) appear in the docs on purpose. Individual activities are not published.

The rules are in the Privacy section of [PROJECT.md](PROJECT.md).

## Documents

- [PROJECT.md](PROJECT.md): plan, decisions, session log
- [docs/schema.md](docs/schema.md): the `activities` table, also used as the model's schema context
- [docs/data_notes.md](docs/data_notes.md): quirks of the export and how the ingest handles them
- [docs/environment.md](docs/environment.md): machine, versions, model digest, measurements
- [docs/validation.md](docs/validation.md): manual check of the ingest
- [eval/questions.yaml](eval/questions.yaml): the evaluation questions and gold SQL
- [results/processed/summaries/](results/processed/summaries/): aggregate metrics per eval run
- [eval/labels/](eval/labels/): hand-made error labels for the failures of three runs
