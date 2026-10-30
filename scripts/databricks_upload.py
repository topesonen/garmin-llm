"""Load the frozen eval snapshot into Unity Catalog for the Genie comparison.

Exports `activities` from the snapshot to Parquet, uploads it to a volume and
creates `garmin.eval_snapshot.activities` with the table and column comments
from docs/schema.md. Reads DATABRICKS_HOST and DATABRICKS_TOKEN from the
environment. Prints counts only.

    python scripts/databricks_upload.py --parquet /path/to/scratch/activities.parquet
"""

import argparse
import json
import re
from pathlib import Path

import duckdb
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = json.loads((ROOT / "eval" / "snapshot.json").read_text())["snapshot"]
SCHEMA_DOC = ROOT / "docs" / "schema.md"

CATALOG = "garmin"
SCHEMA = "eval_snapshot"
VOLUME = "staging"
TABLE = f"{CATALOG}.{SCHEMA}.activities"


def sql_string(text):
    """Quote text as a Databricks SQL string literal."""
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def schema_comments():
    """Return the table comment and {column: comment} from docs/schema.md."""
    text = SCHEMA_DOC.read_text()
    section = text.split("## Table: activities", 1)[1]
    table_comment = section.strip().split("\n\n", 1)[0].strip()
    columns = {}
    for line in section.splitlines():
        match = re.match(r"\|\s*(\w+)\s*\|\s*\w+\s*\|([^|]*)\|([^|]*)\|", line)
        if not match or match.group(1) == "Column":
            continue
        name, unit, description = match.group(1), match.group(2).strip(), match.group(3).strip()
        columns[name] = f"{description}. Unit: {unit}" if unit else description
    return table_comment, columns


def export_parquet(path):
    con = duckdb.connect(str(ROOT / SNAPSHOT), read_only=True)
    names = [row[0] for row in con.execute("DESCRIBE activities").fetchall()]
    # The timestamp goes as text so no time zone conversion can touch it.
    select = ", ".join(
        "strftime(start_time_local, '%Y-%m-%d %H:%M:%S') AS start_time_local"
        if name == "start_time_local" else name
        for name in names
    )
    con.execute(f"COPY (SELECT {select} FROM activities) TO '{path}' (FORMAT parquet)")
    rows = con.execute("SELECT count(*) FROM activities").fetchone()[0]
    return names, rows


def run(w, warehouse_id, statement):
    response = w.statement_execution.execute_statement(
        warehouse_id=warehouse_id, statement=statement, wait_timeout="50s"
    )
    while response.status.state in (StatementState.PENDING, StatementState.RUNNING):
        response = w.statement_execution.get_statement(response.statement_id)
    if response.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"{response.status.state}: {response.status.error}")
    return response.result.data_array if response.result else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", required=True, help="local path for the exported file")
    args = parser.parse_args()

    names, rows = export_parquet(args.parquet)
    table_comment, comments = schema_comments()
    missing = [name for name in names if name not in comments]
    if missing:
        raise SystemExit(f"no description in docs/schema.md for: {missing}")
    print(f"exported {rows} rows, {len(names)} columns")

    w = WorkspaceClient()
    warehouse_id = next(iter(w.warehouses.list())).id

    run(w, warehouse_id, f"CREATE CATALOG IF NOT EXISTS {CATALOG}")
    run(w, warehouse_id, f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")
    run(w, warehouse_id, f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{SCHEMA}.{VOLUME}")

    remote = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME}/activities.parquet"
    with open(args.parquet, "rb") as f:
        w.files.upload(remote, f, overwrite=True)

    select = ", ".join(
        "to_timestamp_ntz(start_time_local) AS start_time_local"
        if name == "start_time_local" else name
        for name in names
    )
    run(w, warehouse_id, f"CREATE OR REPLACE TABLE {TABLE} AS SELECT {select} FROM parquet.`{remote}`")
    run(w, warehouse_id, f"COMMENT ON TABLE {TABLE} IS {sql_string(table_comment)}")
    for name in names:
        run(w, warehouse_id, f"ALTER TABLE {TABLE} ALTER COLUMN {name} COMMENT {sql_string(comments[name])}")

    count = run(w, warehouse_id, f"SELECT count(*) FROM {TABLE}")[0][0]
    print(f"{TABLE}: {count} rows, {len(names)} column comments")


if __name__ == "__main__":
    main()
