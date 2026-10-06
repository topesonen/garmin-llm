"""Build the chat messages sent to the model for one question.

The system message holds the instructions and the schema in docs/schema.md.
It is identical for every question, so the model server can reuse its cached
evaluation of it. The question goes last, in the user message.

Usage:
    python src/prompt.py "How many runs did I do in 2025?"
"""

import sys
from pathlib import Path

DEFAULT_SCHEMA = Path("docs/schema.md")

INSTRUCTIONS = (
    "You translate questions about a person's training activities into SQL "
    "for DuckDB.\n"
    "Reply with exactly one SELECT query and nothing else: no explanation, "
    "no Markdown.\n"
    "Use only the table and columns described below."
)


def build_messages(question, schema_path=DEFAULT_SCHEMA):
    """Return the messages list for the OpenAI-compatible chat endpoint."""
    schema = Path(schema_path).read_text().strip()
    return [
        {"role": "system", "content": f"{INSTRUCTIONS}\n\n{schema}"},
        {"role": "user", "content": question.strip()},
    ]


if __name__ == "__main__":
    for message in build_messages(sys.argv[1]):
        print(f"--- {message['role']} ({len(message['content'])} chars)")
        print(message["content"])
