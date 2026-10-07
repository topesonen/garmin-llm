"""Decide whether a generated query may be run.

Allowed: exactly one SELECT statement that reads the activities table and no
other table. The check uses DuckDB's own parser on an empty in-memory
database, so it never touches the real data. The query is only parsed, not
resolved against a schema, so a wrong column name is not caught here.

This is the first of two layers. The second is the connection the query runs
on (read-only, no file or network access), set up where the query is executed.

Usage:
    python src/guardrails.py "SELECT count(*) FROM activities"
"""

import json
import sys

import duckdb

ALLOWED_TABLES = {"activities"}
# Table functions that only produce rows from their arguments. Any other
# table function (read_csv, duckdb_settings, ...) is rejected.
ALLOWED_TABLE_FUNCTIONS = {"generate_series", "range", "unnest"}


def _collect(node, tables, functions, cte_names):
    """Walk the parsed query and record every table, table function and CTE name."""
    if isinstance(node, list):
        for item in node:
            _collect(item, tables, functions, cte_names)
        return
    if not isinstance(node, dict):
        return
    if node.get("type") == "BASE_TABLE":
        name = node["table_name"].lower()
        schema = (node.get("schema_name") or "").lower()
        if node.get("catalog_name") or schema not in ("", "main"):
            name = ".".join(part for part in (node.get("catalog_name"), schema, name) if part)
        tables.add(name)
    elif node.get("type") == "TABLE_FUNCTION":
        functions.add(node["function"]["function_name"].lower())
    for key, value in node.items():
        if key == "cte_map":
            cte_names.update(entry["key"].lower() for entry in value["map"])
        _collect(value, tables, functions, cte_names)


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

    # json_serialize_sql returns the parsed query as a tree without resolving
    # names or types. con.get_table_names was used here before, but it rejects
    # valid queries: it treats every column as untyped, so a window frame such
    # as RANGE BETWEEN INTERVAL 6 DAY PRECEDING fails to bind.
    con = duckdb.connect(config={"enable_external_access": False})
    try:
        tree = json.loads(con.execute("SELECT json_serialize_sql(?)", [sql]).fetchone()[0])
    except duckdb.Error as error:
        return False, f"rejected by DuckDB: {str(error).splitlines()[0]}"
    finally:
        con.close()
    if tree.get("error"):
        return False, f"rejected by DuckDB: {tree.get('error_message', 'unknown error')}"

    tables, functions, cte_names = set(), set(), set()
    _collect(tree, tables, functions, cte_names)

    not_allowed = functions - ALLOWED_TABLE_FUNCTIONS
    if not_allowed:
        return False, f"table function not allowed: {', '.join(sorted(not_allowed))}"
    # A name defined in a WITH clause is not a table of its own.
    other = tables - ALLOWED_TABLES - cte_names
    if other or not tables & ALLOWED_TABLES:
        found = ", ".join(sorted(other)) or "none"
        return False, f"must read only the activities table, found: {found}"
    return True, ""


if __name__ == "__main__":
    ok, reason = check_sql(sys.argv[1])
    print("allowed" if ok else f"rejected: {reason}")
