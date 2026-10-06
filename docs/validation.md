# Manual validation of the ingest

Six activities compared field by field between the `activities` table and Garmin Connect, to catch errors that aggregate checks cannot (a shifted start time, a wrong unit).

This file records pass or fail only. The compared values are kept in `data/private/validation_values.md`, which is not committed, so no individual activity is published.

Status: passed. All 36 fields pass or are not applicable.

- Checked by: Topias
- Date: 2026-10-06
- Export used: `Activities.csv` with the manual corrections described in `docs/data_notes.md`

## Result

Mark each cell `pass`, `fail` or `n/a` (field not recorded for that activity).

| Activity kind          | Date and start time | Distance | Timer time | Average HR | Elevation gain | Average power |
| ---------------------- | ------------------- | -------- | ---------- | ---------- | -------------- | ------------- |
| Race                   | pass                | pass     | pass       | pass       | pass           | pass          |
| Long run               | pass                | pass     | pass       | pass       | pass           | pass          |
| Interval session       | pass                | pass     | pass       | pass       | pass           | pass          |
| Track run              | pass                | pass     | pass       | pass       | pass (note 1)  | pass          |
| Strength training      | pass                | n/a      | pass       | pass       | n/a            | n/a           |
| Non-running activity   | pass                | pass     | pass       | pass       | pass           | n/a           |

A field passes when the database value equals the Garmin Connect value after unit conversion and display rounding.

## Questions this check answers

| Question from `docs/data_notes.md` | Answer |
|---|---|
| Is `start_time_local` the local start time? | Yes. All six start times match Garmin Connect to the second. |
| Are HR, elevation and power in the units given in `docs/schema.md`? | Yes, on every activity that records them. |

Not covered by this check: respiration rate and ground contact time units.

## Notes

1. Track run, elevation gain: Garmin Connect shows 0 and the table has NULL. The export writes `--` in that field, and the ingest stores `--` as NULL, so the ingest matches the file. Across the whole export, no activity has an elevation gain of 0 and 223 have `--`. Recorded as a pass because the difference is between Garmin's page and Garmin's export; see `docs/data_notes.md`.
2. Track run, distance: Garmin Connect shows metres and the table stores km. The values agree after conversion, which confirms the metres rule in the ingest.

## Failures

None.
