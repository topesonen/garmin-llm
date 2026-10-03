# Schema

DuckDB database: `data/warehouse/garmin.duckdb`. Query only the `activities` table. `raw_activities` is the untouched text import and is not for querying.

## Table: activities

One row per recorded workout from Garmin Connect. NULL means the value was not recorded for that activity (for example, no distance for strength training, no cadence for cycling).

| Column | Type | Unit | Description |
|---|---|---|---|
| activity_id | INTEGER | | Sequential id, ordered by start time |
| start_time_local | TIMESTAMP | local time | When the activity started |
| activity_type | VARCHAR | | Garmin activity type, e.g. 'Running', 'Trail Running', 'Track Running', 'Strength Training', 'Cycling', 'Indoor Cycling', 'Cardio', 'Indoor Rowing', 'Hiking' |
| sport_group | VARCHAR | | Coarse grouping: 'running' (all running types), 'cycling', 'strength', 'cardio', 'rowing', 'hiking', 'skiing', 'other' |
| workout_label | VARCHAR | | Free-text label from the activity title, e.g. 'Threshold', 'Easy Run', 'HYROX', 'norjalainen 4x4', race names. Mixed English and Finnish. NULL when the title was only Garmin's default |
| distance_km | DOUBLE | km | Distance. NULL when not recorded |
| elapsed_time_s | DOUBLE | seconds | Wall-clock time from start to end, including pauses |
| timer_time_s | DOUBLE | seconds | Timer time, excluding pauses. Use this for duration and pace |
| moving_time_s | DOUBLE | seconds | Time spent moving. NULL for activities without GPS |
| avg_pace_s_per_km | DOUBLE | seconds per km | Average pace (timer time / distance). Foot sports only |
| best_pace_s_per_km | DOUBLE | seconds per km | Best pace. Foot sports only |
| avg_gap_s_per_km | DOUBLE | seconds per km | Grade-adjusted pace. Running only |
| avg_speed_kmh | DOUBLE | km/h | Average speed. Cycling and some other sports only |
| best_speed_kmh | DOUBLE | km/h | Best speed. Cycling and some other sports only |
| calories_kcal | DOUBLE | kcal | Energy expenditure |
| avg_hr_bpm | DOUBLE | beats per minute | Average heart rate |
| max_hr_bpm | DOUBLE | beats per minute | Maximum heart rate |
| aerobic_te | DOUBLE | 0 to 5 scale | Garmin aerobic training effect |
| avg_run_cadence_spm | DOUBLE | steps per minute | Average running cadence |
| max_run_cadence_spm | DOUBLE | steps per minute | Maximum running cadence |
| total_ascent_m | DOUBLE | metres | Elevation gain |
| total_descent_m | DOUBLE | metres | Elevation loss |
| min_elevation_m | DOUBLE | metres | Lowest elevation |
| max_elevation_m | DOUBLE | metres | Highest elevation |
| avg_stride_length_m | DOUBLE | metres | Average stride length |
| avg_vertical_ratio_pct | DOUBLE | percent | Vertical oscillation divided by stride length |
| avg_vertical_oscillation_cm | DOUBLE | centimetres | Average vertical bounce |
| avg_ground_contact_time_ms | DOUBLE | milliseconds | Average ground contact time |
| avg_power_w | DOUBLE | watts | Average running power |
| max_power_w | DOUBLE | watts | Maximum running power |
| normalized_power_w | DOUBLE | watts | Normalized running power |
| avg_resp_brpm | DOUBLE | breaths per minute | Average respiration rate |
| min_resp_brpm | DOUBLE | breaths per minute | Minimum respiration rate |
| max_resp_brpm | DOUBLE | breaths per minute | Maximum respiration rate |
| body_battery_drain | DOUBLE | points | Garmin Body Battery change during the activity (negative = drained) |
| steps | DOUBLE | count | Steps during the activity |
| total_strokes | DOUBLE | count | Strokes (rowing) |
| total_reps | DOUBLE | count | Repetitions (strength training) |
| total_sets | DOUBLE | count | Sets (strength training) |
| number_of_laps | DOUBLE | count | Laps recorded |
| best_lap_time_s | DOUBLE | seconds | Fastest lap time |

## Notes for writing queries

- Pace in min:sec per km: `avg_pace_s_per_km / 60` gives decimal minutes.
- Weekly totals: `date_trunc('week', start_time_local)` (weeks start on Monday).
- "Runs" means `sport_group = 'running'` unless a specific running type is asked for.
