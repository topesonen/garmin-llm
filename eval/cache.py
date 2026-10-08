"""Store each model reply on disk so that no request is ever sent twice.

A request is everything that determines the reply: the model, the messages
and the generation settings. Its SHA-256 hash is the file name, so the same
request always finds the same file, and any change to the prompt, the model
or a setting gives a new file. This is what lets an interrupted eval run
continue where it stopped.

One JSON file per request: <cache dir>/<hash>.json, holding the request and
the response.
"""

import hashlib
import json
import os
from pathlib import Path

DEFAULT_CACHE_DIR = Path("results/cache")


def cache_key(request):
    """Return the hash that identifies a request."""
    # Sorted keys and fixed separators: the same request always gives the same text.
    text = json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load(request, cache_dir=DEFAULT_CACHE_DIR):
    """Return the stored response for a request, or None if there is none."""
    path = Path(cache_dir) / f"{cache_key(request)}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())["response"]


def save(request, response, cache_dir=DEFAULT_CACHE_DIR):
    """Store a response. The file appears complete or not at all."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{cache_key(request)}.json"
    # Write to a temporary name and rename: a crash in the middle of writing
    # leaves no half-written file under the real name.
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"request": request, "response": response}, indent=2, ensure_ascii=False)
    )
    os.replace(temporary, path)


def cached_call(request, call, cache_dir=DEFAULT_CACHE_DIR):
    """Return (response, from_cache). Runs call(request) only if nothing is stored.

    If call raises, nothing is stored, so a failed request is tried again next time.
    """
    response = load(request, cache_dir)
    if response is not None:
        return response, True
    response = call(request)
    save(request, response, cache_dir)
    return response, False
