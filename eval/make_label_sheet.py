"""Create the sheet in which the failures of one eval run are labelled by hand.

One entry per answerable question the model got wrong, showing the question,
the gold SQL and the model's SQL side by side, with an empty category to fill
in. Unanswerable questions are left out: their failure is always the same,
the model did not decline.

The sheet holds questions and SQL only, no values from the data, so it can be
committed. Running this again keeps the labels already filled in, as long as
the model's SQL for that question has not changed.

Output: eval/labels/<run name>.yaml

Usage:
    python eval/make_label_sheet.py [RUN_DIR]     default: the most recently changed run
"""

import json
import sys
from pathlib import Path

import yaml

from summarize import ERROR_CATEGORIES, LABEL_ROOT, RAW_ROOT


def block(text, indent="    "):
    """Lay text out as the indented lines of a YAML block."""
    return "\n".join(indent + line for line in text.strip().splitlines())


def main():
    if len(sys.argv) > 1:
        run_dir = Path(sys.argv[1])
    else:
        runs = [path for path in RAW_ROOT.iterdir() if (path / "run.json").exists()]
        run_dir = max(runs, key=lambda path: (path / "run.json").stat().st_mtime)

    path = LABEL_ROOT / f"{run_dir.name}.yaml"
    earlier = {}
    if path.exists():
        earlier = {entry["id"]: entry for entry in yaml.safe_load(path.read_text()) or []}

    parts = [
        f"# Error labels for run {run_dir.name}. Filled in by hand.\n"
        f"# category is one of: {', '.join(ERROR_CATEGORIES)}\n"
        "# With several mistakes, pick the most specific category that fits and put the rest\n"
        "# in note. Use other only when no single fix would make the query right.\n"
    ]
    kept = entries = 0
    for record_path in sorted(run_dir.glob("q*.json")):
        record = json.loads(record_path.read_text())
        if record["correct"] or not record["answerable"]:
            continue
        entries += 1
        old = earlier.get(record["id"], {})
        same_sql = (old.get("model_sql") or "").strip() == record["sql"].strip()
        category = old.get("category") if same_sql else None
        note = old.get("note") if same_sql else None
        kept += category is not None
        # For an SQL error only the error type is kept: the full message can quote the data.
        detail = record["detail"].split(":")[0] if record["verdict"] == "sql_error" else record["detail"]
        parts.append(
            f"- id: {record['id']}\n"
            f"  verdict: {record['verdict']}\n"
            f"  detail: {json.dumps(detail)}\n"
            f"  question: >-\n{block(record['question'])}\n"
            f"  gold_sql: |\n{block(record['gold_sql'])}\n"
            f"  model_sql: |\n{block(record['sql'])}\n"
            f"  category: {category or ''}\n"
            f"  note: {json.dumps(note or '')}\n"
        )
    LABEL_ROOT.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts))
    print(f"{path}: {entries} failures to label, {kept} labels kept from before")


if __name__ == "__main__":
    main()
