"""Ask the model for SQL and pull the query out of its reply.

Talks to any OpenAI-compatible chat endpoint. The defaults point at the local
Ollama server; set LLM_BASE_URL, LLM_MODEL and LLM_API_KEY to use another one.

Usage:
    python src/generate_sql.py "How many runs did I do in 2025?"
"""

import os
import re
import sys
import time

from openai import OpenAI

from prompt import build_messages

BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1")
MODEL = os.environ.get("LLM_MODEL", "qwen2.5-coder:1.5b")
# Ollama ignores the key, but the client requires one to be set.
API_KEY = os.environ.get("LLM_API_KEY", "ollama")

# First Markdown code fence in a reply, with an optional language tag.
FENCE = re.compile(r"```[a-zA-Z]*\s*\n(.*?)```", re.DOTALL)


def extract_sql(reply):
    """Return the SQL in a model reply: the first fenced block, else all of it."""
    match = FENCE.search(reply)
    sql = match.group(1) if match else reply
    return sql.strip()


def generate_sql(question, model=MODEL, base_url=BASE_URL):
    """Send one question to the model. Returns the raw reply, the SQL and timing."""
    client = OpenAI(base_url=base_url, api_key=API_KEY)
    started = time.perf_counter()
    completion = client.chat.completions.create(
        model=model,
        messages=build_messages(question),
        temperature=0,
        seed=0,
    )
    latency_s = time.perf_counter() - started
    reply = completion.choices[0].message.content
    return {
        "model": model,
        "reply": reply,
        "sql": extract_sql(reply),
        "finish_reason": completion.choices[0].finish_reason,
        "prompt_tokens": completion.usage.prompt_tokens,
        "completion_tokens": completion.usage.completion_tokens,
        "latency_s": latency_s,
    }


if __name__ == "__main__":
    result = generate_sql(sys.argv[1])
    print("--- raw reply")
    print(result["reply"])
    print("--- extracted sql")
    print(result["sql"])
    print(
        f"--- {result['model']}, {result['prompt_tokens']} prompt tokens, "
        f"{result['completion_tokens']} completion tokens, "
        f"{result['latency_s']:.1f} s, finish: {result['finish_reason']}"
    )
