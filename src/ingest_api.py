"""Load all activities from the Garmin Connect Personal API into DuckDB.

Replaces the CSV export as the data source (M4). Each run fetches the full
history and rebuilds both tables, so edits and deletions made in Garmin
Connect are picked up. The mapping reproduces the CSV-built table; it was
checked column by column in scripts/compare_api_csv.py (2026-10-22).

Output: data/warehouse/garmin.duckdb with tables
        raw_activities  the API fields used below, in API units, plus
                        garmin_activity_id; no name, location or owner fields
        activities      cleaned, typed, units documented in docs/schema.md

The database is written to a temporary file and moved into place, so the app
never reads a half-written file.

Usage:
    python src/ingest_api.py [--db PATH] [--places PATH]
"""

import argparse
import os
from pathlib import Path

import duckdb
import pandas as pd

import garmin_api
from ingest_csv import DEFAULT_DB, DEFAULT_PLACES, SPORT_GROUPS, load_places, workout_label

# API type key -> activity type name as in the CSV export.
ACTIVITY_TYPES = {
    "bouldering": "Bouldering",
    "cross_country_skiing_ws": "Cross Country Classic Skiing",
    "cycling": "Cycling",
    "hiking": "Hiking",
    "indoor_cardio": "Cardio",
    "indoor_cycling": "Indoor Cycling",
    "indoor_rowing": "Indoor Rowing",
    "multi_sport": "Multisport",
    "other": "Other",
    "running": "Running",
    "soccer": "Soccer/Football",
    "street_running": "Street Running",
    "strength_training": "Strength Training",
    "track_running": "Track Running",
    "trail_running": "Trail Running",
    "volleyball": "Volleyball",
    "yoga": "Yoga",
}

# Safety events, not workouts (the CSV's "Assistance Requested").
EXCLUDED_TYPE_KEYS = {"assistance"}

# Types that get pace (s/km); all others get speed (km/h), as in the CSV.
PACE_TYPES = {
    "Running", "Trail Running", "Street Running", "Track Running",
    "Treadmill Running", "Indoor Running", "Hiking", "Walking",
}

# Our column -> (API field, factor to our unit). Pace and speed are derived below.
NUMERIC = {
    "distance_km": ("distance", 0.001),
    "elapsed_time_s": ("elapsedDuration", 1),
    "timer_time_s": ("duration", 1),
    "moving_time_s": ("movingDuration", 1),
    "calories_kcal": ("calories", 1),
    "avg_hr_bpm": ("averageHR", 1),
    "max_hr_bpm": ("maxHR", 1),
    "aerobic_te": ("aerobicTrainingEffect", 1),
    "avg_run_cadence_spm": ("averageRunningCadenceInStepsPerMinute", 1),
    "max_run_cadence_spm": ("maxRunningCadenceInStepsPerMinute", 1),
    "total_ascent_m": ("elevationGain", 1),
    "total_descent_m": ("elevationLoss", 1),
    "min_elevation_m": ("minElevation", 1),
    "max_elevation_m": ("maxElevation", 1),
    "avg_stride_length_m": ("avgStrideLength", 0.01),  # API gives cm
    "avg_vertical_ratio_pct": ("avgVerticalRatio", 1),
    "avg_vertical_oscillation_cm": ("avgVerticalOscillation", 1),
    "avg_ground_contact_time_ms": ("avgGroundContactTime", 1),
    "avg_power_w": ("avgPower", 1),
    "max_power_w": ("maxPower", 1),
    "normalized_power_w": ("normPower", 1),
    "avg_resp_brpm": ("avgRespirationRate", 1),
    "min_resp_brpm": ("minRespirationRate", 1),
    "max_resp_brpm": ("maxRespirationRate", 1),
    "body_battery_drain": ("differenceBodyBattery", 1),
    "steps": ("steps", 1),
    "total_strokes": ("strokes", 1),
    "total_reps": ("totalReps", 1),
    "total_sets": ("totalSets", 1),
    "number_of_laps": ("lapCount", 1),
    "best_lap_time_s": ("minActivityLapDuration", 1),
}

# Columns where 0 is a real value. Everywhere else the API's 0 means "not
# recorded" and becomes NULL, as in the CSV export, which wrote "--" there.
# Open question: keep zeros instead (PROJECT.md, open decisions).
ZERO_IS_VALUE = {"aerobic_te", "min_elevation_m", "max_elevation_m"}

SPEED_FIELDS = ["averageSpeed", "maxSpeed", "avgGradeAdjustedSpeed"]
RAW_FIELDS = (
    ["activityId", "startTimeLocal", "manualActivity"]
    + [f for f, _ in NUMERIC.values()]
    + SPEED_FIELDS
)

COLUMN_ORDER = [
    "activity_id", "start_time_local", "activity_type", "sport_group", "workout_label",
    "distance_km", "elapsed_time_s", "timer_time_s", "moving_time_s",
    "avg_pace_s_per_km", "avg_speed_kmh", "best_pace_s_per_km", "best_speed_kmh",
    "avg_gap_s_per_km",
] + [c for c in NUMERIC if c not in (
    "distance_km", "elapsed_time_s", "timer_time_s", "moving_time_s")]


def raw_row(a):
    """The API fields kept in raw_activities. activityName is left out: it
    holds place names, like the CSV's Title."""
    row = {f: a.get(f) for f in RAW_FIELDS}
    row["garmin_activity_id"] = row.pop("activityId")
    row["typeKey"] = a["activityType"]["typeKey"]
    return row


def to_pace(speed_ms):
    return 1000.0 / speed_ms if speed_ms else None


def to_kmh(speed_ms):
    return speed_ms * 3.6 if speed_ms else None


def clean_row(a, places, unknown_types):
    key = a["activityType"]["typeKey"]
    if key not in ACTIVITY_TYPES:
        unknown_types.add(key)
    activity_type = ACTIVITY_TYPES.get(key, key.replace("_", " ").title())

    out = {
        "start_time_local": pd.Timestamp(a["startTimeLocal"]),
        "activity_type": activity_type,
        "sport_group": SPORT_GROUPS.get(activity_type, "other"),
        "workout_label": workout_label(a.get("activityName") or "", activity_type, places),
    }
    for col, (field, factor) in NUMERIC.items():
        v = a.get(field)
        if v is None or (v == 0 and col not in ZERO_IS_VALUE):
            out[col] = None
        else:
            out[col] = float(v) * factor

    pace = activity_type in PACE_TYPES
    out["avg_pace_s_per_km"] = to_pace(a.get("averageSpeed")) if pace else None
    out["best_pace_s_per_km"] = to_pace(a.get("maxSpeed")) if pace else None
    out["avg_speed_kmh"] = None if pace else to_kmh(a.get("averageSpeed"))
    out["best_speed_kmh"] = None if pace else to_kmh(a.get("maxSpeed"))
    # Grade-adjusted pace exists for running only; the API leaves it out elsewhere.
    out["avg_gap_s_per_km"] = to_pace(a.get("avgGradeAdjustedSpeed"))
    return out


def fix_manual(df, manual):
    """A manually entered activity has no recording, so its only meaningful
    duration is the timer time. Garmin keeps an elapsed time it cannot edit
    (four runs of 34 to 57 hours, see docs/data_notes.md); cap elapsed time and
    best lap at the timer time. Returns the number of rows changed."""
    bad = manual & (df["elapsed_time_s"] > df["timer_time_s"])
    df.loc[bad, "elapsed_time_s"] = df.loc[bad, "timer_time_s"]
    df.loc[bad, "best_lap_time_s"] = df.loc[bad, ["best_lap_time_s", "timer_time_s"]].min(axis=1)
    return int(bad.sum())


def build(api_activities, places):
    kept = [a for a in api_activities if a["activityType"]["typeKey"] not in EXCLUDED_TYPE_KEYS]
    kept.sort(key=lambda a: a["startTimeLocal"])
    unknown_types = set()
    df = pd.DataFrame([clean_row(a, places, unknown_types) for a in kept])
    manual = pd.Series([bool(a.get("manualActivity")) for a in kept])
    fixed = fix_manual(df, manual)
    df.insert(0, "activity_id", range(1, len(df) + 1))
    raw = pd.DataFrame([raw_row(a) for a in api_activities])
    return raw, df[COLUMN_ORDER], fixed, unknown_types


def write_db(path, raw, activities):
    """Write both tables to a temporary file, then move it over the database."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    con = duckdb.connect(str(tmp))
    con.register("raw_df", raw)
    con.register("act_df", activities)
    con.execute("CREATE TABLE raw_activities AS SELECT * FROM raw_df")
    con.execute("CREATE TABLE activities AS SELECT * FROM act_df")
    con.close()
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--places", type=Path, default=DEFAULT_PLACES)
    args = ap.parse_args()

    places = load_places(args.places)
    token = garmin_api.get_token(garmin_api.read_key())
    api_activities = garmin_api.fetch_activities(token, "2000-01-01")
    raw, activities, fixed, unknown_types = build(api_activities, places)
    write_db(args.db, raw, activities)

    print(f"api activities: {len(raw)}, activities: {len(activities)}, "
          f"excluded: {len(raw) - len(activities)}, manual activities capped: {fixed}")
    print(f"date range: {activities['start_time_local'].min()} "
          f"to {activities['start_time_local'].max()}")
    if unknown_types:
        print(f"unknown type keys, named from the key: {sorted(unknown_types)}")


if __name__ == "__main__":
    main()
