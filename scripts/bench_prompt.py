"""Measure generation speed of one Ollama model on one fixed text-to-SQL prompt.

The prompt is the schema in docs/schema.md plus a made-up question. No real
data is read or sent. The model is unloaded first, so run 1 is a cold start.

Output: one JSON file per run in results/raw/environment/<timestamp>_<model>/,
        each holding the request, the config and Ollama's untouched response.

Usage:
    python scripts/bench_prompt.py [--model TAG] [--runs N] [--host URL]
"""

import argparse
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_MODEL = "qwen2.5-coder:1.5b"
DEFAULT_HOST = "http://localhost:11434"
SCHEMA_PATH = Path("docs/schema.md")
OUT_ROOT = Path("results/raw/environment")

QUESTION = "How many running activities were longer than 10 km in 2025?"

# Fixed sampling settings, so every run asks for the same output.
# num_ctx is left at Ollama's default on purpose; the response shows
# how many prompt tokens were actually evaluated.
OPTIONS = {"seed": 0, "temperature": 0}


def call(host, path, payload=None):
    """GET when payload is None, otherwise POST it as JSON."""
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        host + path, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.loads(resp.read())


def build_prompt():
    schema = SCHEMA_PATH.read_text()
    return (
        "You write DuckDB SQL.\n\n"
        f"{schema}\n\n"
        "Answer the question with one SQL SELECT query and nothing else.\n\n"
        f"Question: {QUESTION}\n"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--host", default=DEFAULT_HOST)
    args = parser.parse_args()

    version = call(args.host, "/api/version")["version"]
    tags = call(args.host, "/api/tags")["models"]
    digest = next(m["digest"] for m in tags if m["name"] == args.model)

    prompt = build_prompt()
    request = {
        "model": args.model,
        "prompt": prompt,
        "stream": False,
        "options": OPTIONS,
    }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = OUT_ROOT / f"{stamp}_{args.model.replace(':', '_')}"
    out_dir.mkdir(parents=True)

    # keep_alive 0 with no prompt unloads the model from memory.
    call(args.host, "/api/generate", {"model": args.model, "keep_alive": 0})

    print(f"ollama {version}, {args.model}, digest {digest[:12]}")
    print("run  load_s  prompt_tok  prompt_tok_s  gen_tok  gen_tok_s  total_s")
    for run in range(1, args.runs + 1):
        response = call(args.host, "/api/generate", request)
        record = {
            "run": run,
            "cold_start": run == 1,
            "ollama_version": version,
            "model": args.model,
            "model_digest": digest,
            "request": request,
            "response": response,
        }
        (out_dir / f"run_{run:02d}.json").write_text(json.dumps(record, indent=2))

        # Ollama reports durations in nanoseconds. prompt_eval_duration can be
        # near zero when the prompt is already cached from the previous run.
        prompt_s = response.get("prompt_eval_duration", 0) / 1e9
        gen_s = response["eval_duration"] / 1e9
        prompt_tok = response.get("prompt_eval_count", 0)
        prompt_rate = prompt_tok / prompt_s if prompt_s > 0 else float("nan")
        print(
            f"{run:>3}  {response['load_duration'] / 1e9:6.2f}  {prompt_tok:10d}"
            f"  {prompt_rate:12.1f}  {response['eval_count']:7d}"
            f"  {response['eval_count'] / gen_s:9.1f}"
            f"  {response['total_duration'] / 1e9:7.2f}"
        )
    print(f"raw responses: {out_dir}")


if __name__ == "__main__":
    main()
