"""Run the eval questions through one model and score every answer.

For each question: run the gold SQL on the frozen snapshot, get the model's
reply (from the cache if it was asked before), check and run the model's SQL
the same way app.py does, and compare the two results.

With --retry, a query that the guardrail or DuckDB refuses is sent back to
the model once with the error message, and the second reply is the one scored.

Stopping and restarting is safe. Replies are cached, so a second run asks the
model only for what is missing and scores everything again.

Output: results/raw/real/<run name>/run.json with the configuration, and one
        <question id>.json per question. These files hold values from the
        real data and are gitignored. The screen shows verdicts only.
        At the end the run is summarized by summarize.py, which writes the
        aggregate metrics to results/processed/summaries/<run name>.json.

Usage:
    python eval/run_eval.py [--model TAG] [--examples YAML] [--retry] [--ids q001 q002 ...] [--name NAME]
"""

import argparse
import hashlib
import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import duckdb

from app import run_query
from cache import DEFAULT_CACHE_DIR, cached_call
from generate_sql import BASE_URL, MODEL, build_request, build_retry_request, extract_sql, is_decline, send
from guardrails import check_sql
from load_questions import DEFAULT_QUESTIONS, load_questions
from prompt import RETRY_TEMPLATE, load_examples
from score import ABS_TOLERANCE, compare_results
from summarize import write_summary

SNAPSHOT_MANIFEST = Path("eval/snapshot.json")
OUT_ROOT = Path("results/raw/real")
# Far above any gold result; a model result that reaches it counts as wrong.
MAX_ROWS = 1000
TIMEOUT_S = 10

CORRECT_VERDICTS = {"correct", "declined_correctly"}
# The failures that come with an error message the model can act on.
RETRY_VERDICTS = {"rejected", "sql_error"}
TIMING_FIELDS = ["prompt_tokens", "completion_tokens", "ttft_s", "latency_s"]


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def evaluate(question, reply, db_path, max_rows=MAX_ROWS, timeout_s=TIMEOUT_S):
    """Score one model reply. Returns the verdict and everything it rests on.

    Verdicts: correct, wrong_result, declined_correctly, declined_wrongly,
    answered_unanswerable, rejected (by the guardrail), sql_error, timeout.
    """
    sql = extract_sql(reply)
    result = {
        "sql": sql,
        "declined": is_decline(sql),
        "ran": False,
        "verdict": None,
        "detail": "",
        # The full error text, for the retry. It can quote values from the data.
        "error": None,
        "gold_rows": None,
        "model_rows": None,
    }
    if question["answerable"]:
        _, result["gold_rows"], _ = run_query(question["gold_sql"], db_path, max_rows, timeout_s)

    if result["declined"]:
        result["verdict"] = "declined_wrongly" if question["answerable"] else "declined_correctly"
        return result

    allowed, reason = check_sql(sql)
    if not allowed:
        result["verdict"], result["detail"], result["error"] = "rejected", reason, reason
        return result
    try:
        _, result["model_rows"], truncated = run_query(sql, db_path, max_rows, timeout_s)
    except duckdb.Error as error:
        result["verdict"], result["detail"] = "sql_error", str(error).splitlines()[0]
        result["error"] = str(error)
        return result
    except TimeoutError as error:
        result["verdict"], result["detail"] = "timeout", str(error)
        return result
    result["ran"] = True

    if not question["answerable"]:
        result["verdict"] = "answered_unanswerable"
    elif truncated:
        result["verdict"], result["detail"] = "wrong_result", f"more than {max_rows} rows"
    else:
        match, reason = compare_results(result["gold_rows"], result["model_rows"], question["ordered"])
        result["verdict"], result["detail"] = ("correct" if match else "wrong_result"), reason
    return result


def ollama_info(base_url, model):
    """Return (Ollama version, model digest), or (None, None) if not an Ollama server."""
    host = base_url.removesuffix("/v1")
    try:
        with urllib.request.urlopen(f"{host}/api/version", timeout=5) as response:
            version = json.load(response)["version"]
        with urllib.request.urlopen(f"{host}/api/tags", timeout=5) as response:
            models = json.load(response)["models"]
    except (OSError, ValueError, KeyError):
        return None, None
    digest = next((entry["digest"] for entry in models if entry["name"] == model), None)
    return version, digest


def git_state():
    """Return (commit hash, True if there are uncommitted changes)."""
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    changes = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout
    return commit or None, bool(changes.strip())


def write_json(path, data):
    # default=str turns dates and decimals into text; the files are a record, not an input.
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--examples", type=Path, help="YAML file of worked examples to put in the prompt")
    parser.add_argument("--retry", action="store_true", help="send a failed query back to the model once, with the error")
    parser.add_argument("--ids", nargs="+", help="run only these question ids")
    parser.add_argument("--name", help="run name; default is the model plus a hash of the configuration")
    args = parser.parse_args()

    questions = load_questions(args.questions)
    unverified = [q["id"] for q in questions if not q["verified"]]
    if unverified:
        raise SystemExit(f"not verified: {', '.join(unverified)}")
    if args.ids:
        unknown = set(args.ids) - {q["id"] for q in questions}
        if unknown:
            raise SystemExit(f"unknown ids: {', '.join(sorted(unknown))}")
        questions = [q for q in questions if q["id"] in args.ids]

    snapshot = json.loads(SNAPSHOT_MANIFEST.read_text())
    actual_hash = hashlib.sha256(Path(snapshot["snapshot"]).read_bytes()).hexdigest()
    if actual_hash != snapshot["sha256"]:
        raise SystemExit(f"{snapshot['snapshot']} does not match the hash in {SNAPSHOT_MANIFEST}")

    examples = load_examples(args.examples) if args.examples else ()
    overlap = {text for text, _ in examples} & {q["question"].strip() for q in load_questions(args.questions)}
    if overlap:
        raise SystemExit(f"{args.examples} repeats an eval question: {sorted(overlap)[0]}")

    ollama_version, model_digest = ollama_info(args.base_url, args.model)
    example = build_request("", args.model)
    system_prompt = example["messages"][0]["content"]
    # Everything that defines this configuration. A change to any of it gives a new run folder.
    config = {
        "model": args.model,
        "model_digest": model_digest,
        "temperature": example["temperature"],
        "seed": example["seed"],
        "system_prompt_sha256": sha256_text(system_prompt),
        "snapshot_sha256": snapshot["sha256"],
    }
    # Added only when examples are used, so runs without them keep their name.
    if args.examples:
        config["examples_sha256"] = sha256_text(json.dumps(examples))
    if args.retry:
        config["retry_prompt_sha256"] = sha256_text(RETRY_TEMPLATE)
    name = args.name or f"{args.model.replace(':', '_').replace('/', '_')}-{sha256_text(json.dumps(config, sort_keys=True))[:8]}"
    out_dir = OUT_ROOT / name
    out_dir.mkdir(parents=True, exist_ok=True)

    commit, dirty = git_state()
    run = {
        "name": name,
        "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "finished": None,
        **config,
        "base_url": args.base_url,
        "ollama_version": ollama_version,
        "system_prompt": system_prompt,
        "examples_file": str(args.examples) if args.examples else None,
        "examples": [{"question": text, "sql": sql} for text, sql in examples],
        "retry": args.retry,
        "retry_prompt": RETRY_TEMPLATE if args.retry else None,
        "snapshot": snapshot["snapshot"],
        "questions_file": str(args.questions),
        "questions_sha256": sha256_text(args.questions.read_text()),
        "question_ids": [q["id"] for q in questions],
        "abs_tolerance": ABS_TOLERANCE,
        "max_rows": MAX_ROWS,
        "timeout_s": TIMEOUT_S,
        "duckdb_version": duckdb.__version__,
        "git_commit": commit,
        "git_uncommitted_changes": dirty,
    }
    write_json(out_dir / "run.json", run)
    print(f"run {name}: {len(questions)} questions, results in {out_dir}")

    for question in questions:
        request = build_request(question["question"], args.model, examples)
        # The digest is part of the key: the same tag can point to a new model version.
        key = {"request": request, "model_digest": model_digest}
        response, from_cache = cached_call(
            key, lambda key: send(key["request"], args.base_url), DEFAULT_CACHE_DIR
        )
        scored = evaluate(question, response["reply"], snapshot["snapshot"])
        calls, first_attempt = [response], None
        if args.retry and scored["verdict"] in RETRY_VERDICTS:
            first_attempt = {field: scored[field] for field in ("sql", "verdict", "detail", "error")}
            first_attempt["reply"] = response["reply"]
            # The second request holds the first reply and its error, so it has its own cache entry.
            key = {
                "request": build_retry_request(request, response["reply"], scored["error"]),
                "model_digest": model_digest,
            }
            response, retry_from_cache = cached_call(
                key, lambda key: send(key["request"], args.base_url), DEFAULT_CACHE_DIR
            )
            from_cache = from_cache and retry_from_cache
            calls.append(response)
            scored = evaluate(question, response["reply"], snapshot["snapshot"])
        record = {
            "id": question["id"],
            "category": question["category"],
            "question": question["question"],
            "answerable": question["answerable"],
            "ordered": question["ordered"],
            "gold_sql": question["gold_sql"],
            "correct": scored["verdict"] in CORRECT_VERDICTS,
            **scored,
            "from_cache": from_cache,
            **response,
            # With a retry: the reply and SQL are the second attempt's, the time
            # to first token is the first call's, tokens and latency are totals.
            "ttft_s": calls[0]["ttft_s"],
            "latency_s": sum(call["latency_s"] for call in calls),
            "prompt_tokens": sum(call["prompt_tokens"] or 0 for call in calls),
            "completion_tokens": sum(call["completion_tokens"] or 0 for call in calls),
            "first_attempt": first_attempt,
            "calls": [{field: call[field] for field in TIMING_FIELDS} for call in calls],
        }
        write_json(out_dir / f"{question['id']}.json", record)
        # An error message can quote a value from the data, so only its type is shown.
        shown = scored["detail"].split(":")[0] if scored["verdict"] == "sql_error" else scored["detail"]
        source = "cache" if from_cache else "model"
        print(
            f"{question['id']}  {scored['verdict']:<22} {record['latency_s']:6.1f} s  {source}"
            f"{'  ' + shown if shown else ''}"
            f"{'  (retry after ' + first_attempt['verdict'] + ')' if first_attempt else ''}"
        )

    run["finished"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write_json(out_dir / "run.json", run)
    print()
    # The summary covers every result file in the run folder, also from earlier partial runs.
    write_summary(out_dir)


if __name__ == "__main__":
    main()
