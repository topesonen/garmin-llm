"""Load the eval questions and check that every entry is well formed.

The check stops an eval run before it starts if the file has a typo, such as
a misspelt true/false or a duplicated id, so a slow run is not wasted on it.

Usage:
    python eval/load_questions.py [PATH]
"""

import sys
from collections import Counter
from pathlib import Path

import yaml

DEFAULT_QUESTIONS = Path("eval/questions.yaml")
FIELDS = ["id", "category", "question", "answerable", "gold_sql", "ordered", "verified", "notes"]


def check_question(entry):
    """Return a list of problems with one entry; empty if it is fine."""
    if not isinstance(entry, dict):
        return ["entry is not a mapping of fields"]
    problems = []
    if list(entry) != FIELDS:
        problems.append(f"fields must be {FIELDS}, found {list(entry)}")
        return problems
    for field in ("id", "category", "question"):
        if not isinstance(entry[field], str) or not entry[field].strip():
            problems.append(f"{field} must be non-empty text")
    for field in ("answerable", "ordered", "verified"):
        if not isinstance(entry[field], bool):
            problems.append(f"{field} must be true or false, found {entry[field]!r}")
    has_sql = isinstance(entry["gold_sql"], str) and bool(entry["gold_sql"].strip())
    if entry["answerable"] is True and not has_sql:
        problems.append("answerable question needs gold_sql")
    if entry["answerable"] is False and entry["gold_sql"] is not None:
        problems.append("unanswerable question must have gold_sql: null")
    return problems


def load_questions(path=DEFAULT_QUESTIONS):
    """Return the questions as a list of dicts. Raises ValueError on any problem."""
    entries = yaml.safe_load(Path(path).read_text())
    if not isinstance(entries, list):
        raise ValueError(f"{path}: expected a list of questions")
    problems = []
    for number, entry in enumerate(entries, start=1):
        name = entry.get("id", f"entry {number}") if isinstance(entry, dict) else f"entry {number}"
        problems += [f"{name}: {problem}" for problem in check_question(entry)]
    ids = Counter(entry["id"] for entry in entries if isinstance(entry, dict) and "id" in entry)
    problems += [f"{name}: id used {count} times" for name, count in ids.items() if count > 1]
    if problems:
        raise ValueError(f"{path}:\n  " + "\n  ".join(problems))
    return entries


if __name__ == "__main__":
    questions = load_questions(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_QUESTIONS)
    print(f"{len(questions)} questions, {sum(q['verified'] for q in questions)} verified")
    for category, count in Counter(q["category"] for q in questions).items():
        print(f"  {category}: {count}")
