# Environment (Phase A)

Recorded 2026-10-05. The measurements and versions below come from files in `results/raw/environment/20261005T180300Z_qwen2.5-coder_1.5b/`. The laptop model, installed RAM, licence and the driver incident are from the session, not from those files.

- `system_info.txt`: OS, CPU, memory, versions, GPU state, `ollama ps`, `ollama show`
- `run_01.json` to `run_05.json`: the benchmark runs, with Ollama's untouched responses
- `openai_endpoint_check.txt`: one request to the OpenAI-compatible endpoint

`system_info.txt` was collected 14 minutes after the benchmark, in the same session.

## Machine

| Component | Value |
|---|---|
| Laptop | ThinkPad T490 |
| OS | Ubuntu 24.04.4 LTS, kernel 7.0.0-31-generic |
| CPU | Intel Core i7-8665U, 4 cores, 8 threads, AVX2 |
| RAM | 30 GiB usable (32 GB installed) |
| Integrated GPU | Intel UHD Graphics 620, drives the display |
| Discrete GPU | NVIDIA GeForce MX250 (GP108M), no driver loaded |

## Software

| Component | Version |
|---|---|
| Python | 3.12.3 |
| duckdb | 1.5.6 |
| pandas | 3.0.5 |
| numpy | 2.5.3 (installed as a pandas dependency) |
| Ollama | 0.35.1, systemd service on `127.0.0.1:11434` |

## Model

| Field | Value |
|---|---|
| Tag | `qwen2.5-coder:1.5b` |
| Digest | `d7372fd828518a4d38b1eb196c673c31a85f2ed302b3d1e406c4c2d1b64a0668` |
| Format, quantization | GGUF, Q4_K_M |
| Parameters | 1.5B |
| Size on disk | 986 MB |
| Size in memory | 1.2 GB |
| Context length | 32768 supported; Ollama loads it with 4096 by default |
| Licence | Apache 2.0 |

This is the smoke-test model for A0. It is not a decision on the generator models.

## GPU behaviour

Inference is CPU-only, by decision (Topias, 2026-10-03). `ollama ps` reports `100% CPU`.

- No NVIDIA or nouveau kernel module is loaded, so Ollama cannot see the MX250. It also skips the integrated GPU by default.
- The CPU-only versus offload comparison named in the A0 task was not run. The MX250 has 2 GB of memory and needs a driver install that was ruled out.
- Side effect of the Ollama install script: it detects an NVIDIA GPU and installs the `cuda-drivers` package without asking. Here that installed the NVIDIA 615.71.09 open driver, whose module then failed to load (`could not insert 'nvidia': No such device`). The driver was removed again by hand. Re-running the install script to upgrade Ollama will install it again.

## Benchmark

`scripts/bench_prompt.py`: one fixed prompt (the schema in `docs/schema.md` plus a made-up question), native `/api/generate`, `seed` 0, `temperature` 0, default context of 4096. The model is unloaded first, so run 1 is a cold start. 5 runs on 2026-10-05.

| Run | Load (s) | Prompt tokens | Prompt eval (s) | Generated tokens | Generation (s) | Generated tokens/s | Total (s) |
|---|---|---|---|---|---|---|---|
| 1 (cold) | 2.06 | 1039 | 15.10 | 66 | 4.64 | 14.2 | 21.81 |
| 2 | 0.00 | 1039 | 0.06 | 60 | 4.03 | 14.9 | 4.12 |
| 3 | 0.00 | 1039 | 0.07 | 60 | 4.10 | 14.6 | 4.18 |
| 4 | 0.00 | 1039 | 0.07 | 60 | 3.96 | 15.1 | 4.05 |
| 5 | 0.00 | 1039 | 0.07 | 60 | 4.00 | 15.0 | 4.08 |

Generated tokens/s is `eval_count / eval_duration` from the response.

- Generation speed: 14.2 tokens/s cold, 14.6 to 15.1 tokens/s on runs 2 to 5 (mean 14.9).
- Prompt evaluation: 68.8 tokens/s on the cold run (1039 tokens in 15.10 s). Runs 2 to 5 reuse Ollama's cache of the identical prompt, so their prompt eval time does not measure reading speed.
- The 1039-token prompt fits in the 4096 default context.

## Observations that affect later phases

- **Output is not identical across runs at temperature 0.** Run 1 and runs 2 to 5 returned the same query with different whitespace: a line break before each `AND` in run 1 (66 tokens), one line in the others (60 tokens). The cause was not investigated; the cold run evaluated the prompt fresh and the others used the cache. Scoring must compare query results, not SQL text.
- **The model adds text it was told to leave out.** All five benchmark replies wrap the SQL in a Markdown code fence, and the endpoint check reply adds explanatory sentences around it. The pipeline needs a SQL extraction step.
- **Prompt evaluation dominates a cold request** (15.10 s of 21.81 s). Keeping the schema at the start of every prompt lets the cache cover it.
- **The OpenAI-compatible endpoint works** (`/v1/chat/completions`, HTTP 200). It returns token counts but no durations, so the pipeline must time requests itself.
- These are single-session numbers on a laptop with other programs running. They show the order of magnitude, not a tuned benchmark.
