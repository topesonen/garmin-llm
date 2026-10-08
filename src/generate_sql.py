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

from prompt import DECLINE_TOKEN, build_messages

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


def is_decline(sql):
    """True if the extracted reply is the decline token and not a query."""
    return sql.upper().startswith(DECLINE_TOKEN)


def build_request(question, model=MODEL):
    """Return everything that determines the reply; also the key for caching it."""
    return {
        "model": model,
        "messages": build_messages(question),
        "temperature": 0,
        "seed": 0,
    }


def send(request, base_url=BASE_URL):
    """Send a request and return the raw reply with token counts and timing."""
    client = OpenAI(base_url=base_url, api_key=API_KEY)
    started = time.perf_counter()
    # Streaming delivers the reply piece by piece, which is the only way to
    # see when the first piece arrived. The token counts come in a last chunk.
    stream = client.chat.completions.create(
        **request, stream=True, stream_options={"include_usage": True}
    )
    pieces = []
    ttft_s = finish_reason = usage = None
    for chunk in stream:
        if chunk.usage is not None:
            usage = chunk.usage
        if not chunk.choices:
            continue
        choice = chunk.choices[0]
        if choice.delta.content:
            if ttft_s is None:
                ttft_s = time.perf_counter() - started
            pieces.append(choice.delta.content)
        if choice.finish_reason:
            finish_reason = choice.finish_reason
    latency_s = time.perf_counter() - started
    return {
        "reply": "".join(pieces),
        "finish_reason": finish_reason,
        "prompt_tokens": usage.prompt_tokens if usage else None,
        "completion_tokens": usage.completion_tokens if usage else None,
        "ttft_s": ttft_s,
        "latency_s": latency_s,
    }


def generate_sql(question, model=MODEL, base_url=BASE_URL):
    """Send one question to the model. Returns the raw reply, the SQL and timing."""
    response = send(build_request(question, model), base_url)
    sql = extract_sql(response["reply"])
    return {"model": model, **response, "sql": sql, "declined": is_decline(sql)}


if __name__ == "__main__":
    result = generate_sql(sys.argv[1])
    print("--- raw reply")
    print(result["reply"])
    print("--- declined" if result["declined"] else "--- extracted sql")
    print(result["sql"])
    print(
        f"--- {result['model']}, {result['prompt_tokens']} prompt tokens, "
        f"{result['completion_tokens']} completion tokens, "
        f"first token after {result['ttft_s']:.1f} s, total {result['latency_s']:.1f} s, "
        f"finish: {result['finish_reason']}"
    )
