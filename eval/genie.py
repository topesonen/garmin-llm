"""Helpers for the Genie comparison: the space definition and result rows.

The Genie and Statement Execution APIs return every value as text, with the
column types in a manifest. rows_from_statement() turns them back into Python
values of the kind DuckDB returns, so eval/score.py compares them the same way.
"""

import datetime
import hashlib
import json
from decimal import Decimal
from pathlib import Path

import yaml

DEFAULT_SPACE_CONFIG = Path("configs/genie_space.yaml")


def load_space_config(path=DEFAULT_SPACE_CONFIG):
    return yaml.safe_load(Path(path).read_text())


def stable_id(text):
    """A 32-character hex id derived from the content, so rebuilds are identical."""
    return hashlib.md5(text.encode()).hexdigest()


def serialized_space(config):
    """Return the serialized_space JSON for the create and update calls."""
    instructions = config["instructions"].strip()
    examples = [
        {
            "id": stable_id(example["question"]),
            "question": [example["question"].strip()],
            "sql": [line + "\n" for line in example["sql"].strip().splitlines()],
        }
        for example in config["examples"]
    ]
    space = {
        "version": 1,
        "data_sources": {"tables": [{"identifier": config["table"]}]},
        "instructions": {
            "text_instructions": [{"id": stable_id(instructions), "content": [instructions]}],
            "example_question_sqls": sorted(examples, key=lambda e: e["id"]),
        },
    }
    return json.dumps(space)


def convert(value, type_name):
    """Turn one text value from the API into a Python value."""
    if value is None:
        return None
    type_name = type_name.upper()
    if type_name in ("BYTE", "SHORT", "INT", "LONG"):
        return int(value)
    if type_name in ("FLOAT", "DOUBLE"):
        return float(value)
    if type_name == "DECIMAL":
        return Decimal(value)
    if type_name == "BOOLEAN":
        return value.lower() == "true"
    if type_name == "DATE":
        return datetime.date.fromisoformat(value)
    if type_name in ("TIMESTAMP", "TIMESTAMP_NTZ"):
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    return value


def column_types(manifest):
    return [column.type_name.value for column in manifest.schema.columns]


def rows_from_statement(types, data_array):
    """Return a result as a list of tuples of Python values."""
    return [tuple(convert(v, t) for v, t in zip(row, types)) for row in data_array or []]


def space_differences(live_serialized, config):
    """Return how the live space differs from the config file; empty if it matches."""
    live = json.loads(live_serialized)
    wanted = json.loads(serialized_space(config))
    differences = []
    tables = lambda space: [t["identifier"] for t in space["data_sources"]["tables"]]
    if tables(live) != tables(wanted):
        differences.append(f"tables: {tables(live)}")
    text = lambda space: ["".join(t["content"]).strip() for t in space["instructions"].get("text_instructions", [])]
    if text(live) != text(wanted):
        differences.append("text instructions")
    examples = lambda space: sorted(
        ("".join(e["question"]).strip(), "".join(e["sql"]).strip())
        for e in space["instructions"].get("example_question_sqls", [])
    )
    if examples(live) != examples(wanted):
        differences.append("example queries")
    return differences
