"""Answer one question about the training data: question in, SQL and result out.

Steps: build the prompt, ask the model for SQL, check it with the guardrails,
run it on a locked-down connection, print the SQL and the result.

Usage:
    python src/app.py "How many runs did I do in 2025?" [--db PATH]
                      [--max-rows N] [--timeout SECONDS]
"""

import argparse
import threading
from pathlib import Path

import duckdb
import pandas as pd

from generate_sql import generate_sql
from guardrails import check_sql

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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("question")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--max-rows", type=int, default=DEFAULT_MAX_ROWS)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    args = parser.parse_args()

    generated = generate_sql(args.question)
    if generated["declined"]:
        print(f"The model says this cannot be answered from the data ({generated['model']}).")
        return 0
    print(f"SQL ({generated['model']}, {generated['latency_s']:.1f} s):")
    print(generated["sql"])
    print()

    ok, reason = check_sql(generated["sql"])
    if not ok:
        print(f"Not run, {reason}")
        return 1

    try:
        columns, rows, truncated = run_query(generated["sql"], args.db, args.max_rows, args.timeout)
    except (duckdb.Error, TimeoutError) as error:
        print(f"Query failed: {str(error).splitlines()[0]}")
        return 1

    print("Result:")
    print(pd.DataFrame(rows, columns=columns).to_string(index=False))
    if truncated:
        print(f"(first {args.max_rows} rows shown)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
