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
| Manual validation of the ingest | In progress |
| Evaluation set and harness | Not started |
| Model and prompt experiments | Not started |
| Synthetic data, so others can run it | Not started |

There are no accuracy results yet. The assistant runs, but how often its SQL is correct has not been measured.

## How it works

1. `src/prompt.py` builds the prompt: instructions, the table schema from [docs/schema.md](docs/schema.md), then the question.
2. `src/generate_sql.py` sends it to the model through an OpenAI-compatible endpoint and extracts the SQL from the reply.
3. `src/guardrails.py` allows only a single `SELECT` that reads the `activities` table, using DuckDB's own parser.
4. `src/app.py` runs the query on a read-only connection with no file or network access, a timeout and a row limit.

The model is reached only through the OpenAI-compatible API, so a different server can be used by setting `LLM_BASE_URL` and `LLM_MODEL`.

## Hardware and speed

Everything so far runs CPU-only on a ThinkPad T490 (Intel i7-8665U, 32 GB RAM) with [Ollama](https://ollama.com). With `qwen2.5-coder:1.5b` it generates about 15 tokens per second. In the benchmark, a cold request took 21.8 seconds, of which 15.1 seconds went to reading the 1039-token schema prompt. The schema sits at the start of every prompt so that the server's cache covers it on later questions.

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
