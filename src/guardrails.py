"""Decide whether a generated query may be run.

Allowed: exactly one SELECT statement that reads the activities table and no
other table. The check uses DuckDB's own parser on an empty in-memory
database, so it never touches the real data.

This is the first of two layers. The second is the connection the query runs
on (read-only, no file or network access), set up where the query is executed.

Usage:
    python src/guardrails.py "SELECT count(*) FROM activities"
"""

import sys

import duckdb

ALLOWED_TABLES = {"activities"}


def check_sql(sql):
    """Return (True, "") if the query may run, else (False, reason)."""
    try:
        statements = duckdb.extract_statements(sql)
    except duckdb.Error as error:
        return False, f"does not parse: {str(error).splitlines()[0]}"

    if len(statements) != 1:
        return False, f"expected one statement, found {len(statements)}"
    if statements[0].type != duckdb.StatementType.SELECT:
        return False, f"not a SELECT: {statements[0].type.name}"

    # Looking up table names can make DuckDB open files named in the query
    # (e.g. read_csv), so file and network access is switched off first.
    con = duckdb.connect(config={"enable_external_access": False})
    try:
        tables = {name.lower() for name in con.get_table_names(sql)}
    except duckdb.Error as error:
        return False, f"rejected by DuckDB: {str(error).splitlines()[0]}"
    finally:
        con.close()

    if tables != ALLOWED_TABLES:
        found = ", ".join(sorted(tables)) or "none"
        return False, f"must read only the activities table, found: {found}"
    return True, ""


if __name__ == "__main__":
    ok, reason = check_sql(sys.argv[1])
    print("allowed" if ok else f"rejected: {reason}")
