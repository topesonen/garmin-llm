"""Read activities from the Garmin Connect Personal API.

The Personal API is Garmin's official access to one's own data. A personal
API key, created in Garmin Connect (Settings > Personal API Key), is
exchanged for an access token valid for 24 hours; there are no refresh
tokens, so each run asks for a new one.

Findings not in Garmin's documentation (checked 2026-10-22):
- The token endpoint returns the token as plain text (a JWT), not JSON.
- Resource calls take the token as "Authorization: Bearer <token>".
- The activity list is the same JSON as Garmin Connect's web app, including
  start and end coordinates and the owner's name, so callers must keep only
  the fields they need.
- Large pages fail with HTTP 500, although the documented default page size
  is 99. The limit looks like the size of the reply, not the number of
  activities: a page of 50 at about 157 kB loaded, while pages near 190 kB
  failed, and every activity loads on its own. So pages are 20 activities,
  like the web app, and a failing page is retried in halves.

The key is read from GARMIN_API_KEY, or from a KEY=value file
(default ~/.config/garmin-llm/garmin.env).
"""

import os
from pathlib import Path

import requests

BASE_URL = "https://personal.connectapi.garmin.com"
TOKEN_PATH = "/personalapitoken-service/personal-api/personal-api-key/token"
ACTIVITIES_PATH = "/activitylist-service/activities/search/activities"
DEFAULT_KEY_FILE = Path("~/.config/garmin-llm/garmin.env")
PAGE_SIZE = 20
TIMEOUT_S = 30


def read_key(key_file=DEFAULT_KEY_FILE):
    if os.environ.get("GARMIN_API_KEY"):
        return os.environ["GARMIN_API_KEY"]
    for line in Path(key_file).expanduser().read_text().splitlines():
        name, _, value = line.strip().partition("=")
        if name == "GARMIN_API_KEY":
            return value
    raise SystemExit(f"No GARMIN_API_KEY in the environment or in {key_file}")


def get_token(key):
    r = requests.post(
        BASE_URL + TOKEN_PATH,
        headers={"Authorization": f"ApiKey {key}"},
        timeout=TIMEOUT_S,
    )
    r.raise_for_status()
    return r.text.strip()


def fetch_activities(token, start_date, end_date=None):
    """All activities with a local start date from start_date (YYYY-MM-DD)
    on, oldest first, as returned by the API."""
    params = {"startDate": start_date, "sortOrder": "asc", "limit": PAGE_SIZE}
    if end_date:
        params["endDate"] = end_date
    activities = []
    size = PAGE_SIZE
    while True:
        r = requests.get(
            BASE_URL + ACTIVITIES_PATH,
            params={**params, "limit": size, "start": len(activities)},
            headers={"Authorization": f"Bearer {token}"},
            timeout=TIMEOUT_S,
        )
        if r.status_code == 500 and size > 1:
            size //= 2
            continue
        r.raise_for_status()
        page = r.json()
        activities.extend(page)
        if len(page) < size:
            return activities
        size = PAGE_SIZE
