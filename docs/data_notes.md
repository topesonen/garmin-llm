# Data Notes: Garmin Activities CSV

Findings from loading `Activities.csv` (Garmin Connect > Activities > Export CSV). Not part of the model's schema context.

## Source

- 548 rows, 48 columns, activities from 2024-02-28 to 2026-10-01.
- Full Garmin history

## Quirks handled in `src/ingest_csv.py`

| Quirk | Handling |
|---|---|
| Missing values written as `--`, `--:--:--` | Converted to NULL |
| Thousands separators (`1,182`, `3,260`) | Removed before parsing |
| Leading apostrophe on negatives (`'-5`), an Excel guard | Stripped |
| **Track Running distance is in metres**, all other types in km | Divided by 1000 for Track Running |
| `Avg Pace` / `Best Pace` hold min/km for foot sports and km/h for cycling and some others | Split into `*_pace_s_per_km` and `*_speed_kmh` by format |
| Durations as `hh:mm:ss`, `hh:mm:ss.f` and `mm:ss.f` | All parsed to seconds |
| `Moving Time` is `00:00:00` for non-GPS activities | Set to NULL |
| Distance `0.00` for activities without distance | Set to NULL |
| Titles contain place names (city prefixes) | `Title` dropped from both tables; `workout_label` keeps the title with a leading place name removed, using `data/private/place_names.txt` |
| 2 rows of type `Assistance Requested` | Excluded |

## Dropped columns

All empty, constant or near-empty in this export: Favorite (always False), Training Stress Score (always 0.0), Decompression (always No), Total Routes, Climb Time, Total Rest, Stress Change, Stress Start, Stress End, Avg Stress, Max Stress (1 to 6 values each).

## Unit checks done from the data itself

| Check | Result |
|---|---|
| Garmin `Avg Pace` vs timer time / distance (foot sports) | Max difference 7.5 s/km: distance is km, pace is based on timer time, not moving time |
| Track Running pace vs distance/1000 | Matches: confirms metres |
| Cadence x stride length vs speed from pace | Median difference 0.07 km/h: stride in metres, cadence in steps/min |
| Vertical oscillation / stride vs vertical ratio | Median difference 0.07 points: oscillation in cm, ratio in percent |

Not checkable from the data alone: HR, power, elevation, respiration, ground contact time units follow Garmin's display conventions. HR, power and elevation were confirmed in the manual check in `docs/validation.md` (2026-10-06); respiration and ground contact time were not part of it.

## Manual corrections to the raw CSV

The export is not used exactly as downloaded. On 2026-10-03 Topias corrected four activities by hand in `data/raw/Activities.csv`; the untouched export is kept next to it as `Activities.original.csv`.

- What was wrong: four `Running` activities in 2026 had timer and elapsed times of 34 to 57 hours for 6.2 to 8.8 km, with calories of 24,072 to 40,356. They have no HR and no pace, and timer time equal to elapsed time, which is the pattern of a manually entered activity. The raw text was a normal `hh:mm:ss` value, so this was in the source data, not a parsing error.
- What was changed: `Time` and `Elapsed Time` on those four rows, now 34 to 57 minutes, and their `Calories`.
- After the correction: no activity has a timer time over 8 hours (longest 4.48 h), the highest calorie value is 3730, and 4 activities have no calorie value (1 of the four corrected runs, 3 others).
- There is no ingest rule for this. A fresh export from Garmin Connect will bring the four values back, and the same check (timer time over 8 hours) will find them.

## Things to know for eval questions

- 6 activities have elapsed time more than 1.5 x timer time (long pauses); 2 of them have an elapsed time over 8 hours. 1 activity has elapsed time shorter than timer time. Questions about duration should use `timer_time_s`.
- Some activities are very short (seconds) and look accidental. Not removed; decide whether eval questions should exclude them.
- `workout_label` is mixed English and Finnish and inconsistent (e.g. several spellings for stroller runs). Good test material for the model, but gold SQL for label-based questions must list the exact labels.
- Race names in `workout_label` still contain city names inside the event name (e.g. a Helsinki marathon). Fine locally; never publish label values.
- Timestamps are local start time, confirmed in the manual validation (2026-10-06).
- NULL in `total_ascent_m` and `total_descent_m` can mean zero as well as not recorded. The export never writes 0 for elevation gain (223 rows have `--`, none has 0), and the manual validation found a track run where Garmin Connect shows 0 and the export has `--`. Sums are unaffected; averages skip those activities.
