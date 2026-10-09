"""Turn the result files of one eval run into aggregate metrics.

Reads results/raw/real/<run name>/ and counts; it never asks the model and
never opens the database. The output holds verdicts, counts and timings only,
no values from the real data, so it can be committed.

Output: results/processed/summaries/<run name>.json, and the same numbers on screen.

run_eval.py calls this at the end of every run. Run it on its own to rebuild
a summary without running the eval.

Usage:
    python eval/summarize.py [RUN_DIR]      default: the most recently changed run
"""

import json
import statistics
import sys
from collections import Counter
from pathlib import Path

import yaml

from load_questions import load_questions

RAW_ROOT = Path("results/raw/real")
OUT_ROOT = Path("results/processed/summaries")
LABEL_ROOT = Path("eval/labels")
# The categories from the project brief, for failures on answerable questions.
# missing_step was added by Topias on 2026-10-08: the query answers a simpler
# question than the one asked and leaves out a step the question needs.
ERROR_CATEGORIES = [
    "wrong_column_or_table", "wrong_date_logic", "wrong_aggregation",
    "wrong_units", "wrong_label_matching", "missing_step", "other",
]  # fmt: skip
CONFIG_FIELDS = [
    "name", "started", "finished", "model", "model_digest", "ollama_version",
    "temperature", "seed", "system_prompt_sha256", "examples_file", "examples_sha256", "retry", "retry_prompt_sha256",
    "snapshot_sha256",
    "questions_sha256", "abs_tolerance", "git_commit", "git_uncommitted_changes",
]  # fmt: skip


def share(part, whole):
    """Return a count, its total and the fraction, or None when there is nothing to count."""
    return {"count": part, "of": whole, "share": round(part / whole, 4) if whole else None}


def spread(values):
    """Return median, minimum and maximum of a list of numbers."""
    values = [value for value in values if value is not None]
    if not values:
        return None
    return {
        "median": round(statistics.median(values), 2),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
    }


def error_categories(run_dir, records):
    """Count the hand-made labels in eval/labels/<run name>.yaml, if the file exists."""
    path = LABEL_ROOT / f"{run_dir.name}.yaml"
    if not path.exists():
        return None
    labels = {entry["id"]: entry for entry in yaml.safe_load(path.read_text()) or []}
    counts = {category: 0 for category in ERROR_CATEGORIES}
    unlabelled = []
    for record in records:
        if record["correct"] or not record["answerable"]:
            continue
        label = labels.get(record["id"], {})
        category = label.get("category")
        # A label made for other SQL than the model's current reply no longer applies.
        current = (label.get("model_sql") or "").strip() == record["sql"].strip()
        if category is None or not current:
            unlabelled.append(record["id"])
        elif category not in counts:
            raise SystemExit(f"{path}: {record['id']} has unknown category {category!r}")
        else:
            counts[category] += 1
    return {"counts": counts, "unlabelled": unlabelled}


def summarize(run_dir):
    run = json.loads((run_dir / "run.json").read_text())
    records = [json.loads(path.read_text()) for path in sorted(run_dir.glob("q*.json"))]
    expected = {question["id"] for question in load_questions(run["questions_file"])}
    found = {record["id"] for record in records}

    answerable = [record for record in records if record["answerable"]]
    unanswerable = [record for record in records if not record["answerable"]]
    wrote_sql = [record for record in records if not record["declined"]]

    by_category = {}
    for record in records:
        counts = by_category.setdefault(record["category"], Counter())
        counts["of"] += 1
        counts["count"] += record["correct"]

    # Tokens per second while generating: the time before the first token is left out.
    # A question with a retry has two model calls, each measured on its own.
    calls = [call for record in records for call in record.get("calls") or [record]]
    speeds = [
        call["completion_tokens"] / (call["latency_s"] - call["ttft_s"])
        for call in calls
        if call["completion_tokens"] and call["ttft_s"] is not None
        and call["latency_s"] > call["ttft_s"]
    ]  # fmt: skip
    retried = [record for record in records if record.get("first_attempt")]

    return {
        "config": {field: run.get(field) for field in CONFIG_FIELDS},
        "complete": found == expected,
        "missing_questions": sorted(expected - found),
        "questions": len(records),
        "correct_overall": share(sum(r["correct"] for r in records), len(records)),
        # Answerable questions whose result matches the gold result.
        "execution_accuracy": share(sum(r["correct"] for r in answerable), len(answerable)),
        # Replies containing SQL that passed the guardrail and ran without error.
        "valid_sql_rate": share(sum(r["ran"] for r in wrote_sql), len(wrote_sql)),
        "unanswerable_declined": share(sum(r["correct"] for r in unanswerable), len(unanswerable)),
        # The harmful case: a query ran and returned something for an unanswerable question.
        "unanswerable_answered": share(
            sum(r["verdict"] == "answered_unanswerable" for r in unanswerable), len(unanswerable)
        ),
        "answerable_declined": share(sum(r["declined"] for r in answerable), len(answerable)),
        # Only for runs with the error-feedback retry. All other metrics describe
        # the final attempt; these show what the retry changed.
        "retry": {
            "correct_first_try": share(
                sum(r["correct"] and not r.get("first_attempt") for r in records), len(records)
            ),
            "retried": share(len(retried), len(records)),
            "fixed_by_retry": share(sum(r["correct"] for r in retried), len(retried)),
            "ran_after_retry": share(sum(r["ran"] for r in retried), len(retried)),
        } if run.get("retry") else None,
        "by_category": {
            category: share(counts["count"], counts["of"]) for category, counts in by_category.items()
        },
        "verdicts": dict(Counter(record["verdict"] for record in records).most_common()),
        "error_categories": error_categories(run_dir, records),
        "performance": {
            "ttft_s": spread([record["ttft_s"] for record in records]),
            "latency_s": spread([record["latency_s"] for record in records]),
            "generation_tokens_per_s": spread(speeds),
            "prompt_tokens": spread([record["prompt_tokens"] for record in records]),
            "completion_tokens": spread([record["completion_tokens"] for record in records]),
        },
        "per_question": {record["id"]: record["verdict"] for record in records},
    }


def show(label, value):
    if value["share"] is None:
        print(f"  {label:<28} none")
    else:
        print(f"  {label:<28} {value['count']:>2} of {value['of']:<2}  {value['share']:.1%}")


def write_summary(run_dir):
    """Summarize one run, write the summary file and print the numbers."""
    run_dir = Path(run_dir)
    summary = summarize(run_dir)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    out_path = OUT_ROOT / f"{run_dir.name}.json"
    out_path.write_text(json.dumps(summary, indent=2) + "\n")

    print(f"{run_dir.name}  ({summary['config']['model']})")
    if not summary["complete"]:
        print(f"  INCOMPLETE, missing: {', '.join(summary['missing_questions'])}")
    show("correct overall", summary["correct_overall"])
    show("execution accuracy", summary["execution_accuracy"])
    show("valid SQL rate", summary["valid_sql_rate"])
    show("unanswerable declined", summary["unanswerable_declined"])
    show("unanswerable answered", summary["unanswerable_answered"])
    show("answerable declined", summary["answerable_declined"])
    if summary["retry"]:
        print("retry")
        for label, value in summary["retry"].items():
            show(label.replace("_", " "), value)
    print("by category")
    for category, value in summary["by_category"].items():
        show(category, value)
    print("verdicts")
    for verdict, count in summary["verdicts"].items():
        print(f"  {verdict:<28} {count:>2}")
    labels = summary["error_categories"]
    if labels:
        print("error categories (failures on answerable questions, labelled by hand)")
        for category, count in labels["counts"].items():
            print(f"  {category:<28} {count:>2}")
        if labels["unlabelled"]:
            print(f"  {'not labelled yet':<28} {len(labels['unlabelled']):>2}")
    print("performance (median, min to max)")
    for name, value in summary["performance"].items():
        if value:
            print(f"  {name:<28} {value['median']:>8}  ({value['min']} to {value['max']})")
    print(f"written to {out_path}")


def main():
    if len(sys.argv) > 1:
        run_dir = Path(sys.argv[1])
    else:
        runs = [path for path in RAW_ROOT.iterdir() if (path / "run.json").exists()]
        if not runs:
            raise SystemExit(f"no runs in {RAW_ROOT}")
        run_dir = max(runs, key=lambda path: (path / "run.json").stat().st_mtime)
    write_summary(run_dir)


if __name__ == "__main__":
    main()
