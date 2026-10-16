"""Answer one question about the training data: question in, SQL and result out.

Steps: build the prompt, ask the model for SQL, check it with the guardrails,
run it on a locked-down connection, print the SQL and the result.

The model is claude-haiku-5-5, chosen by the eval. Set LLM_MODEL or pass
--model to use another, for example qwen2.5-coder:1.5b on the local Ollama
server for offline tests. The eval keeps its own default in generate_sql.py.

Usage:
    python src/app.py "How many runs did I do in 2025?" [--model NAME]
                      [--db PATH] [--max-rows N] [--timeout SECONDS]
"""

import argparse
import os
import threading
from pathlib import Path

import duckdb
import pandas as pd

from generate_sql import generate_sql
from guardrails import check_sql

MODEL = os.environ.get("LLM_MODEL", "claude-haiku-5-5")
DEFAULT_DB = Path("data/warehouse/garmin.duckdb")
DEFAULT_MAX_ROWS = 50
DEFAULT_TIMEOUT_S = 10


def run_query(sql, db_path=DEFAULT_DB, max_rows=DEFAULT_MAX_ROWS, timeout_s=DEFAULT_TIMEOUT_S):
    """Run a query read-only. Returns (column names, rows, truncated)."""
    # Second guardrail layer: the connection cannot write to the database
    # and cannot read other files or the network.
    con = duckdb.connect(
        str(db_path), read_only=True, config={"enable_external_access": False}
    )
    # DuckDB has no query timeout setting, so a timer interrupts the query.
    timer = threading.Timer(timeout_s, con.interrupt)
    timer.start()
    try:
        cursor = con.execute(sql)
        columns = [column[0] for column in cursor.description]
        # One row more than the limit shows whether the result was cut off.
        rows = cursor.fetchmany(max_rows + 1)
    except duckdb.InterruptException:
        raise TimeoutError(f"query stopped after {timeout_s} s") from None
    finally:
        timer.cancel()
        con.close()
    truncated = len(rows) > max_rows
    return columns, rows[:max_rows], truncated


def answer(
    question, db_path=DEFAULT_DB, max_rows=DEFAULT_MAX_ROWS, timeout_s=DEFAULT_TIMEOUT_S, model=MODEL
):
    """Run the whole pipeline for one question and return the outcome, without printing.

    "status" is one of: "declined" (the model says the data cannot answer it),
    "rejected" (the guardrail refused the SQL), "failed" (DuckDB error or
    timeout), "ok". "error" holds the reason for "rejected" and "failed".
    """
    generated = generate_sql(question, model)
    result = {
        "model": generated["model"],
        "latency_s": generated["latency_s"],
        "sql": generated["sql"],
        "error": None,
        "columns": None,
        "rows": None,
        "truncated": False,
    }
    if generated["declined"]:
        return {**result, "status": "declined"}

    ok, reason = check_sql(generated["sql"])
    if not ok:
        return {**result, "status": "rejected", "error": reason}

    try:
        columns, rows, truncated = run_query(generated["sql"], db_path, max_rows, timeout_s)
    except (duckdb.Error, TimeoutError) as error:
        return {**result, "status": "failed", "error": str(error).splitlines()[0]}
    return {**result, "status": "ok", "columns": columns, "rows": rows, "truncated": truncated}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("question")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--max-rows", type=int, default=DEFAULT_MAX_ROWS)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    args = parser.parse_args()

    result = answer(args.question, args.db, args.max_rows, args.timeout, args.model)
    if result["status"] == "declined":
        print(f"The model says this cannot be answered from the data ({result['model']}).")
        return 0
    print(f"SQL ({result['model']}, {result['latency_s']:.1f} s):")
    print(result["sql"])
    print()

    if result["status"] == "rejected":
        print(f"Not run, {result['error']}")
        return 1
    if result["status"] == "failed":
        print(f"Query failed: {result['error']}")
        return 1

    print("Result:")
    print(pd.DataFrame(result["rows"], columns=result["columns"]).to_string(index=False))
    if result["truncated"]:
        print(f"(first {args.max_rows} rows shown)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
