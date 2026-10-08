# Local Text-to-SQL Assistant: Project Brief

Shared brief for Topias and the coding agent (Claude Code). Read this file, `docs/schema.md` and `docs/data_notes.md` before starting any work.

Two phases:
- **Phase A (now):** a local assistant on Ollama that answers natural-language questions about personal Garmin training data by generating and running SQL against DuckDB, with an execution-based evaluation harness. Runs on a laptop with no usable GPU.
- **Phase B (later):** run the same assistant against vLLM on a rented GPU and benchmark serving cost, latency and throughput under concurrent load.

The application talks to the model only through the OpenAI-compatible API, so switching from Ollama to vLLM is a config change, not a rewrite.

## Current status (2026-10-08)

Done:
- Data source: Garmin Connect activities CSV export (`Activities.csv`), stored in `data/raw/` (gitignored).
- `src/ingest_csv.py` loads it into `data/warehouse/garmin.duckdb` as `raw_activities` (text, Title column removed) and `activities` (typed, cleaned).
- `docs/schema.md`: column-level schema with units, written to double as the model's schema context.
- `docs/data_notes.md`: export quirks, how each was handled, unit checks done from the data, and notes for eval questions.
- `.gitignore` covering raw data, private config, the DuckDB file, CSVs and real-data results.
- Repo is on GitHub as `garmin-llm` (public). Python venv with pinned dependencies.
- Topias confirmed on 2026-10-05 that the CSV covers the full Garmin history.
- Four activities with wrong durations corrected by hand in the raw CSV; see `docs/data_notes.md`.
- A0: Ollama 0.35.1 installed, `qwen2.5-coder:1.5b` pulled as the smoke-test model, generation speed measured with `scripts/bench_prompt.py` (about 15 tokens/s, CPU-only). Recorded in `docs/environment.md`, raw runs in `results/raw/environment/`.
- A1 complete: manual validation of six activities against Garmin Connect passed on 2026-10-06 (`docs/validation.md`). Finding: the export writes no value where Garmin Connect shows an elevation gain of 0, so NULL ascent can mean zero.
- A2 complete: `python src/app.py "question"` prints the generated SQL and the result. Modules: `prompt.py`, `generate_sql.py` (OpenAI client, SQL extraction), `guardrails.py` (single SELECT on `activities`, checked with DuckDB's parser), `app.py` (read-only connection, no external access, timeout, row limit). Tested by the agent on a throwaway database with invented rows, and by Topias on the real data.
- `README.md`: brief version, to be replaced by the full write-up in A8.
- A3 complete for now: `eval/questions.yaml` (committed, public) holds 34 questions, all verified by Topias (33 on 2026-10-07, q034 on 2026-10-08): 9 simple, 7 date logic, 5 window, 6 multi-step, 7 unanswerable. Candidates were drafted by the agent and tested on invented rows; Topias checked each against the real database. More questions can be added up to the 50 limit.

Open:
- Everything from A4 onwards.
- The decline token is decided (see A4) but not built: the prompt in `src/prompt.py` still asks for exactly one SELECT and nothing else.
- `guardrails.py` was changed on 2026-10-07 and has no automated tests yet. It now reads table names from the parsed query (`json_serialize_sql`) in place of `get_table_names`, which rejected valid queries with a `RANGE BETWEEN INTERVAL ... PRECEDING` window frame. The same change closed the earlier gap: system catalogs and table functions other than `generate_series`, `range` and `unnest` are now rejected. Checked by hand on 22 allow and reject cases and the 15 gold queries.
- A2 has no cache for model calls yet; required from A4.

Next: A4 step 4, the cache for model replies. A7 (synthetic data) can be built alongside.

## Why this project

- Evidence for AI engineer / applied ML roles built on a data engineering background: LLM over structured data ("chat with the data warehouse").
- Clean evaluation: every question has a gold SQL query, and correctness is judged by comparing result sets, not by an LLM judge.
- The local AI story: private health-adjacent data never leaves the machine at inference time, no API costs, ordinary hardware.
- Phase B connects to the MSc thesis theme (cost-performance tradeoffs). The README may point out this connection; it must not describe the thesis as being about inference or text-to-SQL.

## Hardware (Phase A)

| Component | Value |
|---|---|
| Machine | Lenovo ThinkPad T490 |
| OS | Ubuntu 24.04.4 LTS |
| CPU | Intel i7-8665U, 4 cores / 8 threads |
| RAM | 32 GB |
| GPU | NVIDIA GeForce MX250 (low VRAM, no driver installed) + Intel UHD 620 |

Implications:
- Inference is CPU-only, decided 2026-10-03. No NVIDIA driver is installed, so Ollama does not see the MX250. The Ollama install script installs one without asking; see `docs/environment.md` before upgrading Ollama.
- Models in the 1B to 4B range are the default. 7B to 8B fit in RAM but expect slow generation; use them for comparison runs.
- Eval runs are slow. Scripts must be resumable and cache every model output.
- Measured tokens/s on this laptop is a result to report, not a number to assume. First measurement is in `docs/environment.md`.

## Open decisions (Topias decides, agent does not)

| Decision | Options | Status |
|---|---|---|
| Generator models (2 to 3) | Small models from the Ollama library, including at least one code/SQL-oriented model if available, plus one 7B/8B for comparison. Verify availability and licence at decision time. | TBD |
| Exclude accidental short activities in eval questions | Yes / no, and threshold | TBD |
| Full Garmin account export later (FIT files, sleep, VO2max) | See `GARMIN_SETUP.md`. Not needed for v1. | Deferred |
| Interface | CLI only, or a minimal web UI (e.g. Streamlit or Gradio) | TBD |
| Repo name and visibility | | Decided 2026-10-03: `garmin-llm`, public |
| GPU use in Phase A | CPU-only, or install the NVIDIA driver and test offload to the MX250 | Decided 2026-10-03: CPU-only |
| How `docs/validation.md` stays private | Gitignore the file, or record only pass/fail per field with no values. `docs/` is committed and the repo is public. | Decided 2026-10-05: pass/fail per field only in `docs/validation.md`; the compared values go in `data/private/validation_values.md` (gitignored) |

## Stack

- Python, pinned dependencies in `requirements.txt` (currently duckdb, openai, pandas, PyYAML).
- DuckDB as the warehouse (`data/warehouse/garmin.duckdb`).
- Ollama for generation, accessed through the OpenAI Python client and the Ollama OpenAI-compatible endpoint. Check the current Ollama docs for supported endpoints before relying on them.

## Pipeline

1. Question in.
2. Prompt = schema context from `docs/schema.md` + optional few-shot examples + question.
3. Model returns one SQL query.
4. Guardrails: read-only DuckDB connection, single SELECT statement only, only the `activities` table, query timeout, row limit.
5. Execute; on error, optionally feed the error back to the model for one retry (an experiment, not the baseline).
6. Return the result table and, optionally, a short natural-language answer generated from it.
7. If the question cannot be answered from the schema, the model should say so instead of guessing.

## Phase A steps

### A0. Environment check
Install Ollama, pull one small model, confirm GPU behaviour, record CPU-only vs offload tokens/s for one fixed prompt.
Done when: `docs/environment.md` records versions, GPU behaviour and measured numbers.
Status: done 2026-10-05, CPU-only numbers only. The offload comparison was not run because no NVIDIA driver is installed, by decision.

### A1. Data (done 2026-10-06)
- [x] Ingest CSV into DuckDB (`src/ingest_csv.py`)
- [x] Schema doc (`docs/schema.md`) and data notes (`docs/data_notes.md`)
- [x] Topias: confirm the CSV covers the full history (confirmed 2026-10-05)
- [x] Topias: check 5 activities (a race, a long run, an interval session, a track or treadmill run, a non-running activity) against Garmin Connect: date and start time, distance, timer time, average HR, elevation gain, power if present. Record pass/fail per field in `docs/validation.md`, and the compared values in `data/private/validation_values.md` (gitignored), so no individual row is published. Done 2026-10-06 with six activities, all passed.
Done when: `docs/validation.md` shows the check passed. Do not write eval questions before that.

### A2. Baseline assistant
Pipeline steps 1 to 4 and 6 with one model, zero-shot.
Done when: one command answers a question and prints the SQL and the result.
Status: done 2026-10-06 (`src/app.py`).

### A3. Evaluation set
30 to 50 questions, each with a gold SQL query written or verified by Topias. Spread across difficulty: simple filters and aggregates, date logic (weekly/monthly volume, comparisons between periods), window functions, and multi-step questions. Include 5 to 10 questions the schema cannot answer. Label-based questions using `workout_label` were dropped (Topias, 2026-10-07): labels are rarely used in the data.
Gold answers are computed by running the gold SQL on a frozen snapshot of the database, so expected results are never typed by hand.
The agent may draft candidate questions and SQL from the schema; only Topias marks them verified.
Done when: `eval/questions.yaml` exists and every question is verified.
Status: done for now 2026-10-07 with 33 verified questions. Each row has `id`, `category`, `question`, `answerable`, `gold_sql`, `ordered`, `verified` and `notes`. Pace answers are in decimal minutes per km (see `docs/data_notes.md`).

### A4. Evaluation harness
Metrics:
- **Execution accuracy:** generated SQL returns the same result set as the gold SQL (order-insensitive unless the question requires ordering; numeric tolerance documented).
- **Valid SQL rate:** share of queries that parse and run.
- **Error categories:** wrong column/table, wrong date logic, wrong aggregation, wrong units, wrong label matching, other. Labelled manually for failures.
- **Unanswerable handling:** share of unanswerable questions correctly declined.
- **Performance:** time to first token, total latency, tokens/s per model.
Done when: one command runs the full eval for one configuration, writes raw results, and resumes after interruption.
Decisions (Topias, 2026-10-08):
- Declining: the model replies with the fixed token `CANNOT_ANSWER` in place of SQL. The harness also counts declines on answerable questions.
- Numeric tolerance: two numbers are equal when they agree to a few decimal places. The rule in `eval/score.py`: they differ by at most 0.001.
- Column names and column order are ignored; only the values are compared. The number of columns must match: an extra column fails the question, and the reason is recorded so its frequency can be seen. Row order counts only when the question has `ordered: true`.
- Time to first token is measured in A4 by streaming the reply, because cached replies cannot be timed again later.
Build order: question loader (done 2026-10-08, `eval/load_questions.py`), frozen database snapshot (done 2026-10-08, `scripts/freeze_snapshot.py`; snapshot `data/warehouse/garmin_eval_2026-10-08.duckdb`, hash and counts in `eval/snapshot.json`), result comparison (done 2026-10-08, `eval/score.py`), reply cache, run loop (`eval/run_eval.py`), metrics summary.

### A5. Experiments
Vary one thing at a time against the baseline: model, schema description detail, number of few-shot examples, error-feedback retry on/off.
Done when: a results table compares configurations on all metrics, with raw results stored (aggregates only for real data, see privacy).

### A6. Interface (optional)
Minimal UI for demos.

### A7. Synthetic data and public eval
`scripts/make_synthetic.py` generates a fake `activities` table with the same schema and realistic distributions (including the quirks in `docs/data_notes.md`), plus a synthetic eval set, so the project runs for anyone without the real data.

### A8. Write-up
README: use case, architecture, guardrails, eval method, results, failure analysis, limitations, hardware.
Done when: Topias has checked every number against `results/raw/`.

## Engineering backlog (to do at some point)

Added 2026-10-06 by Topias. These make the project show the engineering side of AI engineer work: wrapping a model in an API, tracking cost and latency per call, evaluating output, handling failures and retries, and structuring Python as a package. Not scheduled yet; Topias decides when each one happens.

| Item | What it means here | Relation to the plan |
|---|---|---|
| API endpoint | Serve the assistant over HTTP with FastAPI: a question in, SQL and result out | New. Could replace or sit under the A6 interface |
| Per-request logging | Record prompt tokens, completion tokens, latency and cost for every model call | New. Token counts and latency are already returned by `generate_sql.py` but not stored. Cost is zero on local hardware and becomes real in Phase B |
| Eval set with measured accuracy | 20 to 30 questions with known correct SQL, accuracy measured | Already planned as A3 and A4 (30 to 50 questions) |
| Failures and retries | Handle a model server that is down or slow, a reply with no usable SQL, and a query that errors | Partly planned: pipeline step 5 (error feedback retry) is an A5 experiment. Retries and timeouts on the model call itself are new |
| Tests | Automated tests for extraction, guardrails and query execution, runnable without the real data | New. The checks done by hand in A2 are the starting point |
| Package layout | Installable package with a `pyproject.toml` in place of loose scripts in `src/` | New. Changes the repo layout below |

## Phase B: vLLM serving benchmark (after Phase A)

Run the assistant against vLLM on a rented GPU. Measure TTFT, inter-token latency, end-to-end latency (p50/p95/p99), output tokens/s, requests/s and cost per 1M output tokens across concurrency levels (e.g. 1, 4, 16, 64) and quantization settings (BF16, AWQ, GPTQ, FP8 where supported). Re-run the synthetic eval set on each setting to check execution accuracy does not degrade.

Phase B decisions (model, GPU provider, GPU type, spend cap) are made by Topias before it starts. Never start a paid instance without Topias confirming in the session; terminate instances at the end of every session and log hours and cost in `costs.md`. Check the vLLM CLI and benchmarking tool against the docs for the installed version.

## Privacy

- `data/raw/`, `data/private/`, the real DuckDB file, CSVs and real-data results are gitignored and never committed.
- The `Title` column is not loaded into the database. `workout_label` strips leading place names using `data/private/place_names.txt`; race names can still contain a city inside the event name, so label values are never published.
- No latitude, longitude or location columns in any table.
- Real-data results are published only as aggregate metrics. Query outputs, gold answers, sample rows and label values stay private.
- **`eval/questions.yaml` is public** (Topias, 2026-10-07). It holds question text and gold SQL only, and gold answers are computed at run time, so it contains no value from the real data. It was private while label-based questions were planned; those were dropped. Questions and notes must not contain label values, race names, places or query results.
- **Aggregates of the real data in this public repo are there on purpose** (Topias, 2026-10-05). `docs/data_notes.md` and this file contain row counts, the date range, counts per check, and minimum, maximum and range values computed from the real activities. The handful of example labels in `docs/schema.md` were also approved for publication (2026-10-03); other label values stay private. Individual rows are not published.
- **Claude Code is a cloud model.** Anything it reads or prints goes to Anthropic. During development, the agent works against the schema and synthetic data; it does not open `data/raw/`, does not print real rows, and checks real-data logic with aggregate queries (counts, null rates, min/max) unless Topias explicitly asks otherwise in the session.

## Repo layout

```
garmin-llm/
  README.md
  PROJECT.md
  CLAUDE.md               points Claude Code to this file
  GARMIN_SETUP.md         full account export, for later
  requirements.txt
  .gitignore
  configs/                one YAML per experiment configuration
  data/raw/               gitignored: Activities.csv
  data/private/           gitignored: place_names.txt, validation_values.md
  data/warehouse/         gitignored real DB; synthetic DB may be committed
  data/synthetic/         synthetic CSV/DB, committed
  src/
    ingest_csv.py         done
    prompt.py             done
    generate_sql.py       done
    guardrails.py         done
    app.py                done
  eval/
    questions.yaml        done; questions and gold SQL only, no answers
    questions_synthetic.yaml
    load_questions.py     done
    snapshot.json         done; hash and counts of the frozen database
    run_eval.py
    score.py              done
  scripts/
    bench_prompt.py       done
    freeze_snapshot.py    done
    make_synthetic.py
  results/raw/
    environment/          A0 benchmark runs, committed
  results/processed/
  docs/
    schema.md             done
    data_notes.md         done
    environment.md        done
    validation.md         done; pass/fail only, no values
  scratch/                gitignored: ad hoc queries against the real data
  costs.md                Phase B only
```

## Rules for the agent

- Never fabricate, estimate or fill in results. Every number in the README must trace to a file in `results/raw/`.
- If a run fails or looks wrong, record and report it; do not silently rerun and drop it.
- Ask before changing models, metrics, eval questions or the schema. If the schema changes, update `docs/schema.md` and `docs/data_notes.md` in the same change.
- Follow the privacy section, including the Claude Code rule.
- Cache all model calls keyed by configuration and input, so interrupted runs resume.
- Record Ollama version, model name and tag/digest, and all config values in every result file.
- Secrets in environment variables only, never in the repo.
- No emojis in code or comments.
- Update "Current status" and the session log at the end of each session.

## Output for the CV (later, after results exist)

One line describing what was built and measured, with real numbers from `results/processed/`. Written by Topias after the write-up, not before.

## Session log

| Date | Phase | What was done | Next step |
|---|---|---|---|
| 2026-10-03 | A1 | CSV export profiled; `ingest_csv.py`, `schema.md`, `data_notes.md`, `.gitignore` written; quirks found: Track Running distance in metres, pace/speed mixed in one column, place names in titles | Topias: confirm full history, run manual validation. Agent: A0 environment check |
| 2026-10-03 | Setup, A1, A0 | venv and git set up, repo pushed as `garmin-llm` (public); CSV re-ingested (548 raw rows, 546 activities); four runs with durations of 34 to 57 hours found by aggregate checks and corrected by hand in the CSV; Ollama 0.35.1 installed; its install script added an NVIDIA driver, which was removed | Agent: pull the model and benchmark |
| 2026-10-05 | A0 | `qwen2.5-coder:1.5b` pulled and digest recorded; `scripts/bench_prompt.py` written and run 5 times (about 15 generated tokens/s, 21.8 s cold request); OpenAI-compatible endpoint confirmed; `docs/environment.md` written. Found: output text differs between cold and cached runs at temperature 0, and the model adds a code fence or prose around the SQL | Topias: run manual validation (pass/fail public, values private), decide on adding `openai`. Agent: A2 baseline assistant |
| 2026-10-06 | A1, A2 | Baseline assistant written (`prompt.py`, `generate_sql.py`, `guardrails.py`, `app.py`), `openai` 3.24.0 added; manual validation of six activities passed, with the elevation-gain NULL finding added to `data_notes.md` and `schema.md`; brief `README.md`; `scratch/` gitignored for ad hoc queries | Agent: draft candidate eval questions (A3), or start the harness (A4). Topias: verify questions and gold SQL |
| 2026-10-07 | A3 | Eval set written and verified: 33 questions in `eval/questions.yaml` (format changed from JSONL to YAML); label-based questions dropped; pace questions use minutes per km; `guardrails.py` rewritten to read table names from the parsed query after it rejected a valid `RANGE BETWEEN INTERVAL` window, which also closed the system-catalog gap; `eval/questions.yaml` made public by Topias' decision | Topias: decide how the model declines, and the numeric tolerance. Agent: A4 harness, add PyYAML, freeze a database snapshot |
