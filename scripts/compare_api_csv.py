"""Compare the Personal API's activities with the CSV-built activities table.

Before the API replaces the CSV export, this checks that each API field,
converted with the planned unit conversion, gives the same values as the
column the CSV ingest produced. Activities are matched on local start time.
Only aggregates are printed and written: match counts, per-column agreement,
the median API/CSV ratio (a unit error shows as a ratio like 100 or 0.01),
and a count table of API type keys against CSV activity types.

Output: results/raw/real/api_vs_csv_<date>.json (gitignored)

Usage:
    python scripts/compare_api_csv.py [--db PATH] [--places PATH]
"""

import argparse
import json
import statistics
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import garmin_api  # noqa: E402
from ingest_csv import DEFAULT_DB, DEFAULT_PLACES, load_places, workout_label  # noqa: E402

OUT_DIR = Path("results/raw/real")


def speed_to_pace(v):
    return 1000.0 / v if v else None


def ms_to_kmh(v):
    return v * 3.6 if v is not None else None


# Our column: (API field, conversion to our unit, tolerance in our unit).
# A value agrees when |api - csv| <= max(tolerance, 1% of |csv|); the CSV
# holds rounded display values, so exact equality is not expected.
COLUMNS = {
    "distance_km": ("distance", lambda v: v / 1000.0 if v else None, 0.01),
    "elapsed_time_s": ("elapsedDuration", None, 1),
    "timer_time_s": ("duration", None, 1),
    "moving_time_s": ("movingDuration", None, 1),
    "avg_pace_s_per_km": ("averageSpeed", speed_to_pace, 1),
    "best_pace_s_per_km": ("maxSpeed", speed_to_pace, 1),
    "avg_gap_s_per_km": ("avgGradeAdjustedSpeed", speed_to_pace, 1),
    "avg_speed_kmh": ("averageSpeed", ms_to_kmh, 0.1),
    "best_speed_kmh": ("maxSpeed", ms_to_kmh, 0.1),
    "calories_kcal": ("calories", None, 1),
    "avg_hr_bpm": ("averageHR", None, 1),
    "max_hr_bpm": ("maxHR", None, 1),
    "aerobic_te": ("aerobicTrainingEffect", None, 0.1),
    "avg_run_cadence_spm": ("averageRunningCadenceInStepsPerMinute", None, 1),
    "max_run_cadence_spm": ("maxRunningCadenceInStepsPerMinute", None, 1),
    "total_ascent_m": ("elevationGain", None, 1),
    "total_descent_m": ("elevationLoss", None, 1),
    "min_elevation_m": ("minElevation", None, 1),
    "max_elevation_m": ("maxElevation", None, 1),
    "avg_stride_length_m": ("avgStrideLength", None, 0.01),
    "avg_vertical_ratio_pct": ("avgVerticalRatio", None, 0.1),
    "avg_vertical_oscillation_cm": ("avgVerticalOscillation", None, 0.1),
    "avg_ground_contact_time_ms": ("avgGroundContactTime", None, 1),
    "avg_power_w": ("avgPower", None, 1),
    "max_power_w": ("maxPower", None, 1),
    "normalized_power_w": ("normPower", None, 1),
    "avg_resp_brpm": ("avgRespirationRate", None, 1),
    "min_resp_brpm": ("minRespirationRate", None, 1),
    "max_resp_brpm": ("maxRespirationRate", None, 1),
    "body_battery_drain": ("differenceBodyBattery", None, 1),
    "steps": ("steps", None, 0),
    "total_strokes": ("strokes", None, 0),
    "total_reps": ("totalReps", None, 0),
    "total_sets": ("totalSets", None, 0),
    "number_of_laps": ("lapCount", None, 0),
    "best_lap_time_s": ("minActivityLapDuration", None, 1),
}


def compare_column(pairs, tol):
    """pairs: (csv value, api value) for every matched activity."""
    both = [(c, a) for c, a in pairs if c is not None and a is not None]
    agree = [abs(a - c) <= max(tol, 0.01 * abs(c)) for c, a in both]
    ratios = [a / c for c, a in both if c != 0]
    return {
        "both": len(both),
        "agree": sum(agree),
        "csv_only": sum(1 for c, a in pairs if c is not None and a is None),
        "api_only": sum(1 for c, a in pairs if c is None and a is not None),
        "median_ratio": round(statistics.median(ratios), 4) if ratios else None,
        "max_abs_diff": round(max(abs(a - c) for c, a in both), 3) if both else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--places", type=Path, default=DEFAULT_PLACES)
    args = ap.parse_args()

    con = duckdb.connect(str(args.db), read_only=True)
    cur = con.execute("SELECT * FROM activities")
    names = [d[0] for d in cur.description]
    csv_rows = {str(r[names.index("start_time_local")]): dict(zip(names, r)) for r in cur.fetchall()}
    con.close()

    token = garmin_api.get_token(garmin_api.read_key())
    api_rows = {a["startTimeLocal"]: a for a in garmin_api.fetch_activities(token, "2000-01-01")}

    matched = sorted(set(csv_rows) & set(api_rows))
    places = load_places(args.places)
    result = {
        "date": date.today().isoformat(),
        "csv_activities": len(csv_rows),
        "api_activities": len(api_rows),
        "matched": len(matched),
        "csv_unmatched": len(set(csv_rows) - set(api_rows)),
        "api_unmatched_by_type": dict(Counter(
            api_rows[k]["activityType"]["typeKey"] for k in set(api_rows) - set(csv_rows)
        )),
        "type_pairs": {
            f"{t} -> {c}": n for (t, c), n in sorted(Counter(
                (api_rows[k]["activityType"]["typeKey"], csv_rows[k]["activity_type"])
                for k in matched
            ).items())
        },
        "workout_label_equal": sum(
            workout_label(api_rows[k].get("activityName") or "", csv_rows[k]["activity_type"], places)
            == csv_rows[k]["workout_label"]
            for k in matched
        ),
        "columns": {},
    }
    for col, (field, convert, tol) in COLUMNS.items():
        pairs = []
        for k in matched:
            a = api_rows[k].get(field)
            if a is not None and convert is not None:
                a = convert(a)
            pairs.append((csv_rows[k][col], a))
        result["columns"][col] = {"api_field": field, **compare_column(pairs, tol)}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"api_vs_csv_{result['date']}.json"
    out.write_text(json.dumps(result, indent=2) + "\n")

    print({k: v for k, v in result.items() if k not in ("columns", "type_pairs")})
    for pair, n in result["type_pairs"].items():
        print(f"  {pair}: {n}")
    print(f"{'column':30s} {'both':>5s} {'agree':>5s} {'csv_only':>8s} {'api_only':>8s} {'ratio':>8s} {'max_diff':>9s}")
    for col, r in result["columns"].items():
        print(f"{col:30s} {r['both']:5d} {r['agree']:5d} {r['csv_only']:8d} {r['api_only']:8d} "
              f"{str(r['median_ratio']):>8s} {str(r['max_abs_diff']):>9s}")
    print(f"written: {out}")


if __name__ == "__main__":
    main()
