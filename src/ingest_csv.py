"""Load the Garmin Connect activities CSV export into DuckDB.

Input:  data/raw/Activities.csv (Garmin Connect > Activities > Export CSV)
Output: data/warehouse/garmin.duckdb with tables
        raw_activities  all CSV columns except Title, as text
        activities      cleaned, typed, units documented in docs/schema.md

Usage:
    python src/ingest_csv.py [--csv PATH] [--db PATH] [--places PATH]
"""

import argparse
import re
from pathlib import Path

import duckdb
import pandas as pd

DEFAULT_CSV = Path("data/raw/Activities.csv")
DEFAULT_DB = Path("data/warehouse/garmin.duckdb")
DEFAULT_PLACES = Path("data/private/place_names.txt")

# Activity types excluded from the cleaned table.
# "Assistance Requested" entries are safety events, not workouts.
EXCLUDED_TYPES = {"Assistance Requested"}

# Activity types whose Distance column is exported in metres instead of km.
# Confirmed by checking elapsed time / distance against Garmin's Avg Pace.
DISTANCE_IN_METRES = {"Track Running"}

SPORT_GROUPS = {
    "Running": "running",
    "Trail Running": "running",
    "Track Running": "running",
    "Street Running": "running",
    "Cycling": "cycling",
    "Indoor Cycling": "cycling",
    "Strength Training": "strength",
    "Cardio": "cardio",
    "Indoor Rowing": "rowing",
    "Hiking": "hiking",
    "Cross Country Classic Skiing": "skiing",
}


def parse_missing(value):
    """Return None for Garmin placeholders, otherwise the stripped string."""
    if value is None or pd.isna(value):
        return None
    s = str(value).strip().lstrip("'")
    if s in {"", "--", "--:--:--", "--:--"}:
        return None
    return s


def parse_number(value):
    s = parse_missing(value)
    if s is None:
        return None
    return float(s.replace(",", ""))


def parse_duration_s(value):
    """Parse h:mm:ss, mm:ss or either with fractional seconds into seconds."""
    s = parse_missing(value)
    if s is None:
        return None
    seconds = 0.0
    for part in s.split(":"):
        seconds = seconds * 60 + float(part)
    return seconds


def parse_pace_or_speed(value):
    """Garmin puts min/km pace ("7:45") for foot sports and km/h ("20.4")
    for cycling and some others in the same column. Return (pace_s_per_km, speed_kmh)."""
    s = parse_missing(value)
    if s is None:
        return None, None
    if ":" in s:
        return parse_duration_s(s), None
    return None, float(s)


def load_places(path):
    if not path.exists():
        raise SystemExit(
            f"Missing {path}. Create it with one place name per line "
            "(see docs/schema.md, workout_label)."
        )
    names = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            names.append(line)
    # Longest first so multi-word names match before their prefixes.
    return sorted(names, key=len, reverse=True)


def workout_label(title, activity_type, places):
    """Strip a leading place name from the title. Return None when what is left
    is only Garmin's automatic title (the activity type itself)."""
    s = parse_missing(title)
    if s is None:
        return None
    for place in places:
        pattern = rf"^{re.escape(place)}(\s+-\s+|\s+)"
        if re.match(pattern, s, flags=re.IGNORECASE):
            s = re.sub(pattern, "", s, count=1, flags=re.IGNORECASE)
            break
    s = s.strip()
    if not s or s.lower() == str(activity_type).lower():
        return None
    return s


def clean(raw, places):
    df = raw[~raw["Activity Type"].isin(EXCLUDED_TYPES)].copy()
    df = df.sort_values("Date").reset_index(drop=True)

    out = pd.DataFrame()
    out["activity_id"] = range(1, len(df) + 1)
    out["start_time_local"] = pd.to_datetime(df["Date"])
    out["activity_type"] = df["Activity Type"].values
    out["sport_group"] = df["Activity Type"].map(SPORT_GROUPS).fillna("other").values
    out["workout_label"] = [
        workout_label(t, a, places) for t, a in zip(df["Title"], df["Activity Type"])
    ]

    distance = df["Distance"].map(parse_number)
    in_metres = df["Activity Type"].isin(DISTANCE_IN_METRES)
    distance = distance.where(~in_metres, distance / 1000.0)
    # 0.00 km is how Garmin records activities without distance.
    out["distance_km"] = distance.where(distance > 0).values

    out["elapsed_time_s"] = df["Elapsed Time"].map(parse_duration_s).values
    out["timer_time_s"] = df["Time"].map(parse_duration_s).values
    moving = df["Moving Time"].map(parse_duration_s)
    # 00:00:00 means Garmin did not compute moving time (no GPS).
    out["moving_time_s"] = moving.where(moving > 0).values

    avg = df["Avg Pace"].map(parse_pace_or_speed)
    best = df["Best Pace"].map(parse_pace_or_speed)
    out["avg_pace_s_per_km"] = [p for p, _ in avg]
    out["avg_speed_kmh"] = [v for _, v in avg]
    out["best_pace_s_per_km"] = [p for p, _ in best]
    out["best_speed_kmh"] = [v for _, v in best]
    out["avg_gap_s_per_km"] = df["Avg GAP"].map(parse_duration_s).values

    numeric = {
        "calories_kcal": "Calories",
        "avg_hr_bpm": "Avg HR",
        "max_hr_bpm": "Max HR",
        "aerobic_te": "Aerobic TE",
        "avg_run_cadence_spm": "Avg Run Cadence",
        "max_run_cadence_spm": "Max Run Cadence",
        "total_ascent_m": "Total Ascent",
        "total_descent_m": "Total Descent",
        "min_elevation_m": "Min Elevation",
        "max_elevation_m": "Max Elevation",
        "avg_stride_length_m": "Avg Stride Length",
        "avg_vertical_ratio_pct": "Avg Vertical Ratio",
        "avg_vertical_oscillation_cm": "Avg Vertical Oscillation",
        "avg_ground_contact_time_ms": "Avg Ground Contact Time",
        "avg_power_w": "Avg Power",
        "max_power_w": "Max Power",
        "normalized_power_w": "Normalized Power® (NP®)",
        "avg_resp_brpm": "Avg Resp",
        "min_resp_brpm": "Min Resp",
        "max_resp_brpm": "Max Resp",
        "body_battery_drain": "Body Battery Drain",
        "steps": "Steps",
        "total_strokes": "Total Strokes",
        "total_reps": "Total Reps",
        "total_sets": "Total Sets",
        "number_of_laps": "Number of Laps",
    }
    for col, src in numeric.items():
        out[col] = df[src].map(parse_number).values

    out["best_lap_time_s"] = df["Best Lap Time"].map(parse_duration_s).values
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--places", type=Path, default=DEFAULT_PLACES)
    args = ap.parse_args()

    raw = pd.read_csv(args.csv, dtype=str, keep_default_na=False)
    places = load_places(args.places)
    activities = clean(raw, places)

    args.db.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(args.db))
    # Title holds place names, so it is kept out of the database entirely.
    con.register("raw_df", raw.drop(columns=["Title"]))
    con.register("act_df", activities)
    con.execute("CREATE OR REPLACE TABLE raw_activities AS SELECT * FROM raw_df")
    con.execute("CREATE OR REPLACE TABLE activities AS SELECT * FROM act_df")
    con.close()

    excluded = len(raw) - len(activities)
    print(f"raw rows: {len(raw)}, activities: {len(activities)}, excluded: {excluded}")
    print(
        f"date range: {activities['start_time_local'].min()} "
        f"to {activities['start_time_local'].max()}"
    )


if __name__ == "__main__":
    main()
