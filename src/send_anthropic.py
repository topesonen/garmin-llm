"""Send a request to a hosted Claude model through the Anthropic API.

Used by the eval as a reference point next to the local models; the assistant
itself (app.py) stays local. The request is built by generate_sql.build_request
in the OpenAI chat format and converted here, so the prompt is the same text
for every model.

Differences from the local models:
- No temperature and no seed: Claude Haiku 5.5 rejects non-default sampling
  settings, so a hosted reply cannot be reproduced exactly. The reply cache
  makes a rerun of the eval reproducible.
- Thinking is turned off, so the model answers directly like the local ones.

The client reads the key from ANTHROPIC_API_KEY.
"""

import time

import anthropic

# Far above any SQL reply; a reply that reaches it ends with stop_reason max_tokens.
MAX_TOKENS = 4096


def is_hosted(model):
    """True for a model served by the Anthropic API rather than the local server."""
    return model.startswith("claude-")


def to_anthropic_request(request):
    """Convert an OpenAI-format request into the arguments of messages.stream.

    The system message moves to the separate system field. Temperature and seed
    are dropped, because the model does not accept them.
    """
    system = [m["content"] for m in request["messages"] if m["role"] == "system"]
    return {
        "model": request["model"],
        "max_tokens": MAX_TOKENS,
        "thinking": {"type": "disabled"},
        "system": "\n\n".join(system),
        "messages": [m for m in request["messages"] if m["role"] != "system"],
    }


def send_anthropic(request):
    """Send a converted request and return the reply with token counts and timing.

    Returns the same fields as generate_sql.send, plus the model id the API
    reports.
    """
    client = anthropic.Anthropic()
    started = time.perf_counter()
    ttft_s = None
    pieces = []
    with client.messages.stream(**request) as stream:
        for text in stream.text_stream:
            if ttft_s is None:
                ttft_s = time.perf_counter() - started
            pieces.append(text)
        message = stream.get_final_message()
    latency_s = time.perf_counter() - started
    return {
        "reply": "".join(pieces),
        "finish_reason": message.stop_reason,
        "prompt_tokens": message.usage.input_tokens,
        "completion_tokens": message.usage.output_tokens,
        "ttft_s": ttft_s,
        "latency_s": latency_s,
        "served_model": message.model,
    }
