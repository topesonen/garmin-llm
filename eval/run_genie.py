"""Run the eval questions through a Databricks Genie space and score the answers.

Genie gets each question in a new conversation and writes and runs its own
Databricks SQL on garmin.eval_snapshot.activities, a copy of the frozen
snapshot (scripts/databricks_upload.py). The result rows it returns are
compared with the gold SQL run locally on the snapshot, with the same
eval/score.py functions as the other runs, so the summary is comparable.

Scoring rules for Genie (Topias, 2026-10-29):
- A reply with no query (a text answer, a clarifying question) is a decline.
- When Genie writes several queries, the last one is scored.
- There is no guardrail check: the SQL is Databricks SQL, which DuckDB's
  parser cannot read, and it ran on Databricks, not here.
- A message that ends in FAILED or CANCELLED is genie_failed, and is not
  cached, so the next run asks again.

Before the first question, the live space is compared with
configs/genie_space.yaml; the run stops if they differ. Replies are cached
(results/cache/), so a stopped run continues where it stopped. At the end the
warehouse is stopped, because Free Edition does not allow lowering its
auto-stop time and idle minutes count against the daily limit.

Output: results/raw/real/<run name>/ as run_eval.py, and the summary in
        results/processed/summaries/<run name>.json. The screen shows verdicts only.
        Needs DATABRICKS_HOST and DATABRICKS_TOKEN in the environment.

Usage:
    python eval/run_genie.py [--questions YAML] [--ids q001 ...] [--name NAME] [--keep-warehouse]
"""

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import duckdb
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.dashboards import MessageStatus

from app import run_query
from cache import DEFAULT_CACHE_DIR, cached_call
from genie import (
    DEFAULT_SPACE_CONFIG, column_types, load_space_config, rows_from_statement, serialized_space,
    space_differences,
)
from load_questions import DEFAULT_QUESTIONS, load_questions
from run_eval import CORRECT_VERDICTS, MAX_ROWS, OUT_ROOT, SNAPSHOT_MANIFEST, TIMEOUT_S, git_state, sha256_text, write_json
from score import ABS_TOLERANCE, compare_results, matches_with_extra_columns
from summarize import write_summary

MODEL = "databricks-genie"
# The Genie API limits questions per minute; a pause between live questions stays under it.
MIN_INTERVAL_S = 12


class GenieFailed(Exception):
    """A message that did not complete. Raised so that cached_call stores nothing."""

    def __init__(self, reply):
        super().__init__(reply["status"])
        self.reply = reply


def ask(w, space_id, question):
    """Ask one question in a new conversation. Returns a reply that can be stored as JSON."""
    started = time.monotonic()
    message = w.genie.start_conversation_and_wait(space_id, question)
    queries, text = [], None
    for attachment in message.attachments or []:
        if attachment.text and attachment.text.content:
            text = attachment.text.content
        if not attachment.query:
            continue
        query = {
            "attachment_id": attachment.attachment_id,
            "sql": attachment.query.query,
            "description": attachment.query.description,
            "state": None, "error": None, "column_types": None, "data": None,
            "truncated": None, "chunks": None,
        }  # fmt: skip
        statement = w.genie.get_message_attachment_query_result(
            space_id, message.conversation_id, message.message_id, attachment.attachment_id
        ).statement_response
        query["state"] = statement.status.state.value
        if statement.status.error:
            query["error"] = statement.status.error.message
        if statement.manifest:
            query["column_types"] = column_types(statement.manifest)
            query["truncated"] = statement.manifest.truncated
            query["chunks"] = statement.manifest.total_chunk_count
            # Values stay text here, so the cache is exactly what the API sent.
            query["data"] = statement.result.data_array if statement.result else []
        queries.append(query)
    reply = {
        "status": message.status.value,
        "error": message.error.error if message.error else None,
        "conversation_id": message.conversation_id,
        "message_id": message.message_id,
        "queries": queries,
        # Genie's answer in words. It can quote values from the data.
        "text": text,
        "latency_s": round(time.monotonic() - started, 2),
    }
    if message.status != MessageStatus.COMPLETED:
        raise GenieFailed(reply)
    return reply


def evaluate(question, reply, db_path):
    """Score one Genie reply. Same verdicts and fields as run_eval.evaluate, plus genie_failed."""
    query = reply["queries"][-1] if reply["queries"] else None
    result = {
        "sql": query["sql"] if query else "",
        "interpretation": query["description"] if query else None,
        "declined": reply["status"] == "COMPLETED" and query is None,
        "ran": False, "verdict": None, "detail": "", "error": None,
        "extra_columns_match": None, "gold_rows": None, "model_rows": None,
    }  # fmt: skip
    if question["answerable"]:
        _, result["gold_rows"], _ = run_query(question["gold_sql"], db_path, MAX_ROWS, TIMEOUT_S)

    if reply["status"] != "COMPLETED":
        result["verdict"], result["detail"] = "genie_failed", reply["status"]
        return result
    if result["declined"]:
        result["verdict"] = "declined_wrongly" if question["answerable"] else "declined_correctly"
        return result
    if query["state"] != "SUCCEEDED":
        result["verdict"], result["detail"], result["error"] = "sql_error", query["state"], query["error"]
        return result
    result["ran"] = True
    result["model_rows"] = rows_from_statement(query["column_types"], query["data"])

    if not question["answerable"]:
        result["verdict"] = "answered_unanswerable"
    elif query["truncated"] or (query["chunks"] or 1) > 1 or len(result["model_rows"]) > MAX_ROWS:
        result["verdict"], result["detail"] = "wrong_result", "result truncated"
    else:
        match, reason = compare_results(result["gold_rows"], result["model_rows"], question["ordered"])
        result["verdict"], result["detail"] = ("correct" if match else "wrong_result"), reason
        result["extra_columns_match"] = not match and matches_with_extra_columns(
            result["gold_rows"], result["model_rows"], question["ordered"]
        )
    return result


def stop_warehouse(w, warehouse_id):
    try:
        w.warehouses.stop(warehouse_id)
        print(f"warehouse {warehouse_id} stopping")
    except Exception as error:
        print(f"could not stop warehouse {warehouse_id}: {error}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--space-config", type=Path, default=DEFAULT_SPACE_CONFIG)
    parser.add_argument("--ids", nargs="+", help="run only these question ids")
    parser.add_argument("--name", help="run name; default is databricks-genie plus a hash of the configuration")
    parser.add_argument("--keep-warehouse", action="store_true", help="do not stop the warehouse at the end")
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

    space_config = load_space_config(args.space_config)
    space_id = space_config["space_id"]
    w = WorkspaceClient()
    space = w.genie.get_space(space_id, include_serialized_space=True)
    differences = space_differences(space.serialized_space, space_config)
    if differences:
        raise SystemExit(f"space {space_id} differs from {args.space_config}: {', '.join(differences)}")
    overlap = {e["question"].strip() for e in space_config["examples"]} & {
        q["question"].strip() for q in load_questions(args.questions)
    }
    if overlap:
        raise SystemExit(f"{args.space_config} repeats an eval question: {sorted(overlap)[0]}")

    config = {
        "model": MODEL,
        "space_id": space_id,
        "space_sha256": sha256_text(serialized_space(space_config)),
        "snapshot_sha256": snapshot["sha256"],
    }
    if args.questions.resolve() != DEFAULT_QUESTIONS.resolve():
        config["questions_sha256"] = sha256_text(args.questions.read_text())
    name = args.name or f"{MODEL}-{sha256_text(json.dumps(config, sort_keys=True))[:8]}"
    out_dir = OUT_ROOT / name
    out_dir.mkdir(parents=True, exist_ok=True)

    commit, dirty = git_state()
    run = {
        "name": name,
        "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "finished": None,
        **config,
        "model_digest": None,
        "temperature": None,
        "seed": None,
        "warehouse_id": space.warehouse_id,
        "table": space_config["table"],
        # The space plays the part of the prompt and the examples.
        "examples_file": str(args.space_config),
        "examples_sha256": config["space_sha256"],
        "space": json.loads(serialized_space(space_config)),
        "retry": False,
        "snapshot": snapshot["snapshot"],
        "questions_file": str(args.questions),
        "questions_sha256": sha256_text(args.questions.read_text()),
        "question_ids": [q["id"] for q in questions],
        "abs_tolerance": ABS_TOLERANCE,
        "max_rows": MAX_ROWS,
        "duckdb_version": duckdb.__version__,
        "git_commit": commit,
        "git_uncommitted_changes": dirty,
    }
    write_json(out_dir / "run.json", run)
    print(f"run {name}: {len(questions)} questions, results in {out_dir}")

    last_live = 0.0

    def live_call(key):
        nonlocal last_live
        time.sleep(max(0.0, MIN_INTERVAL_S - (time.monotonic() - last_live)))
        last_live = time.monotonic()
        return ask(w, key["space_id"], key["question"])

    try:
        for question in questions:
            key = {
                "provider": MODEL,
                "space_id": space_id,
                "space_sha256": config["space_sha256"],
                "snapshot_sha256": snapshot["sha256"],
                "question": question["question"].strip(),
            }
            try:
                reply, from_cache = cached_call(key, live_call, DEFAULT_CACHE_DIR)
            except GenieFailed as failure:
                reply, from_cache = failure.reply, False
            scored = evaluate(question, reply, snapshot["snapshot"])
            record = {
                "id": question["id"],
                "category": question["category"],
                "question": question["question"],
                "answerable": question["answerable"],
                "ordered": question["ordered"],
                "gold_sql": question["gold_sql"],
                "correct": scored["verdict"] in CORRECT_VERDICTS,
                "correct_lenient": scored["verdict"] in CORRECT_VERDICTS or bool(scored["extra_columns_match"]),
                **scored,
                "from_cache": from_cache,
                "genie": reply,
                "queries_written": len(reply["queries"]),
                # Genie reports no tokens and no time to first token.
                "ttft_s": None,
                "latency_s": reply["latency_s"],
                "prompt_tokens": None,
                "completion_tokens": None,
                "first_attempt": None,
                "calls": [{"prompt_tokens": None, "completion_tokens": None, "ttft_s": None, "latency_s": reply["latency_s"]}],
            }
            write_json(out_dir / f"{question['id']}.json", record)
            # An error message can quote a value from the data, so only the state is shown.
            source = "cache" if from_cache else "genie"
            print(
                f"{question['id']}  {scored['verdict']:<22} {reply['latency_s']:6.1f} s  {source}"
                f"{'  ' + scored['detail'] if scored['detail'] else ''}"
                f"{'  (' + str(len(reply['queries'])) + ' queries)' if len(reply['queries']) > 1 else ''}"
            )
    finally:
        if not args.keep_warehouse:
            stop_warehouse(w, space.warehouse_id)

    run["finished"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write_json(out_dir / "run.json", run)
    print()
    write_summary(out_dir)


if __name__ == "__main__":
    main()
