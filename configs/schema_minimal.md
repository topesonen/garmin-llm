# Schema

DuckDB database. Query only the `activities` table.

```sql
CREATE TABLE activities (
    activity_id INTEGER,
    start_time_local TIMESTAMP,
    activity_type VARCHAR,  -- e.g. 'Running', 'Trail Running', 'Track Running', 'Strength Training', 'Cycling', 'Indoor Cycling', 'Cardio', 'Indoor Rowing', 'Hiking'
    sport_group VARCHAR,  -- 'running', 'cycling', 'strength', 'cardio', 'rowing', 'hiking', 'skiing', 'other'
    workout_label VARCHAR,
    distance_km DOUBLE,
    elapsed_time_s DOUBLE,
    timer_time_s DOUBLE,
    moving_time_s DOUBLE,
    avg_pace_s_per_km DOUBLE,
    best_pace_s_per_km DOUBLE,
    avg_gap_s_per_km DOUBLE,
    avg_speed_kmh DOUBLE,
    best_speed_kmh DOUBLE,
    calories_kcal DOUBLE,
    avg_hr_bpm DOUBLE,
    max_hr_bpm DOUBLE,
    aerobic_te DOUBLE,
    avg_run_cadence_spm DOUBLE,
    max_run_cadence_spm DOUBLE,
    total_ascent_m DOUBLE,
    total_descent_m DOUBLE,
    min_elevation_m DOUBLE,
    max_elevation_m DOUBLE,
    avg_stride_length_m DOUBLE,
    avg_vertical_ratio_pct DOUBLE,
    avg_vertical_oscillation_cm DOUBLE,
    avg_ground_contact_time_ms DOUBLE,
    avg_power_w DOUBLE,
    max_power_w DOUBLE,
    normalized_power_w DOUBLE,
    avg_resp_brpm DOUBLE,
    min_resp_brpm DOUBLE,
    max_resp_brpm DOUBLE,
    body_battery_drain DOUBLE,
    steps DOUBLE,
    total_strokes DOUBLE,
    total_reps DOUBLE,
    total_sets DOUBLE,
    number_of_laps DOUBLE,
    best_lap_time_s DOUBLE
);
```

"Runs" means `sport_group = 'running'` unless a specific running type is asked for.
