"""Ask the model for SQL and pull the query out of its reply.

Talks to any OpenAI-compatible chat endpoint. The defaults point at the local
Ollama server; set LLM_BASE_URL, LLM_MODEL and LLM_API_KEY to use another one.
A model whose name starts with claude- goes through the Anthropic API instead
(send_anthropic.py). generate_sql() asks it for structured output: JSON with
the interpretation, a decline flag and the SQL. Local models reply in text.

Usage:
    python src/generate_sql.py "How many runs did I do in 2025?"
"""

import json
import os
import re
import sys
import time

from openai import OpenAI

from prompt import DECLINE_TOKEN, DEFAULT_SCHEMA, REPLY_SCHEMA, build_messages, build_retry_messages
from send_anthropic import is_hosted, send_anthropic, to_anthropic_request

BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1")
MODEL = os.environ.get("LLM_MODEL", "qwen2.5-coder:1.5b")
# Ollama ignores the key, but the client requires one to be set.
API_KEY = os.environ.get("LLM_API_KEY", "ollama")

# First Markdown code fence in a reply, with an optional language tag.
FENCE = re.compile(r"```[a-zA-Z]*\s*\n(.*?)```", re.DOTALL)
# First line that starts a query: SELECT, WITH, or a comment (a plan before the query).
QUERY_START = re.compile(r"^[ \t]*(SELECT\b|WITH\b|--)", re.IGNORECASE | re.MULTILINE)


def extract_sql(reply):
    """Return the SQL in a model reply.

    The first fenced block if there is one. Otherwise the reply from the first
    line that starts a query, so a sentence the model wrote before the query
    is dropped. A reply with no such line is returned whole, which keeps a
    decline intact; the guardrail checks whatever comes back.
    """
    match = FENCE.search(reply)
    if match:
        return match.group(1).strip()
    start = QUERY_START.search(reply)
    return reply[start.start():].strip() if start else reply.strip()


def is_decline(sql):
    """True if the extracted reply is the decline token and not a query.

    Comment lines before the token are skipped: with a plan in the prompt,
    the model may explain in comments why it declines.
    """
    lines = [line.strip() for line in sql.splitlines()]
    code = [line for line in lines if line and not line.startswith("--")]
    return bool(code) and code[0].upper().startswith(DECLINE_TOKEN)


def build_request(
    question, model=MODEL, examples=(), schema_path=DEFAULT_SCHEMA, plan=False, structured=False
):
    """Return everything that determines the reply; also the key for caching it.

    structured=True asks for a JSON reply matching REPLY_SCHEMA; only the
    Anthropic sender supports it. Without it the request is unchanged, so
    earlier cache keys and run names stay valid.
    """
    request = {
        "model": model,
        "messages": build_messages(
            question, schema_path=schema_path, examples=examples, plan=plan, structured=structured
        ),
        "temperature": 0,
        "seed": 0,
    }
    if structured:
        request["output_schema"] = REPLY_SCHEMA
    return request


def parse_structured(reply):
    """Return (interpretation, sql, declined) from a structured reply.

    A reply that is not valid JSON (cut off, or a refusal) gives empty SQL,
    which the guardrail then refuses.
    """
    try:
        fields = json.loads(reply)
    except json.JSONDecodeError:
        return None, "", False
    return fields["interpretation"].strip(), fields["sql"].strip(), bool(fields["cannot_answer"])


def build_retry_request(request, reply, error):
    """Return the request that asks again after a failed query."""
    return {**request, "messages": build_retry_messages(request["messages"], reply, error)}


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
    if is_hosted(model):
        response = send_anthropic(to_anthropic_request(build_request(question, model, structured=True)))
        interpretation, sql, declined = parse_structured(response["reply"])
    else:
        response = send(build_request(question, model), base_url)
        sql = extract_sql(response["reply"])
        interpretation, declined = None, is_decline(sql)
    return {
        "model": model,
        **response,
        "sql": sql,
        "declined": declined,
        "interpretation": interpretation,
    }


if __name__ == "__main__":
    result = generate_sql(sys.argv[1])
    print("--- raw reply")
    print(result["reply"])
    if result["interpretation"]:
        print(f"--- interpretation: {result['interpretation']}")
    print("--- declined" if result["declined"] else "--- extracted sql")
    print(result["sql"])
    print(
        f"--- {result['model']}, {result['prompt_tokens']} prompt tokens, "
        f"{result['completion_tokens']} completion tokens, "
        f"first token after {result['ttft_s']:.1f} s, total {result['latency_s']:.1f} s, "
        f"finish: {result['finish_reason']}"
    )
