"""Build the chat messages sent to the model for one question.

The system message holds the instructions and the schema in docs/schema.md.
It is identical for every question, so the model server can reuse its cached
evaluation of it. Worked examples, if any, follow as earlier turns of the
conversation. The question goes last, in the user message.

Usage:
    python src/prompt.py "How many runs did I do in 2025?" [EXAMPLES_YAML]
"""

import sys
from pathlib import Path

import yaml

DEFAULT_SCHEMA = Path("docs/schema.md")

# What the model replies in place of SQL when the table cannot answer the question.
DECLINE_TOKEN = "CANNOT_ANSWER"

INSTRUCTIONS = (
    "You translate questions about a person's training activities into SQL "
    "for DuckDB.\n"
    "Reply with exactly one SELECT query and nothing else: no explanation, "
    "no Markdown.\n"
    "Use only the table and columns described below.\n"
    "If the question cannot be answered from that table, reply with exactly "
    f"{DECLINE_TOKEN} and nothing else."
)

# Sent after a query that the guardrail or DuckDB refused, for one more attempt.
# The first version also offered the decline token here. The model then gave
# up on 3 of 6 retried questions, all answerable (run qwen2.5-coder_7b-abc924b9).
RETRY_TEMPLATE = (
    "That query failed with this error:\n{error}\n"
    "Fix the query. Reply with the corrected query and nothing else."
)


def load_examples(path):
    """Return the worked examples in a YAML file as a list of (question, sql)."""
    entries = yaml.safe_load(Path(path).read_text())
    return [(entry["question"].strip(), entry["sql"].strip()) for entry in entries]


def build_messages(question, schema_path=DEFAULT_SCHEMA, examples=()):
    """Return the messages list for the OpenAI-compatible chat endpoint."""
    schema = Path(schema_path).read_text().strip()
    messages = [{"role": "system", "content": f"{INSTRUCTIONS}\n\n{schema}"}]
    # Each example looks like a question the model already answered correctly.
    for example_question, example_sql in examples:
        messages.append({"role": "user", "content": example_question})
        messages.append({"role": "assistant", "content": example_sql})
    messages.append({"role": "user", "content": question.strip()})
    return messages


def build_retry_messages(messages, reply, error):
    """Return the conversation continued with the failed reply and its error."""
    return messages + [
        {"role": "assistant", "content": reply},
        {"role": "user", "content": RETRY_TEMPLATE.format(error=error)},
    ]


if __name__ == "__main__":
    examples = load_examples(sys.argv[2]) if len(sys.argv) > 2 else ()
    for message in build_messages(sys.argv[1], examples=examples):
        print(f"--- {message['role']} ({len(message['content'])} chars)")
        print(message["content"])
