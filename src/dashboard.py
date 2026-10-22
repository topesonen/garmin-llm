"""Fixed queries for the Stats tab: no model, one function per block.

Each function takes an open read-only connection and the date to count from,
and returns a DataFrame, so the queries can be checked without Streamlit and
with any date in place of today.
"""

import calendar
import datetime as dt

import duckdb

from app import DEFAULT_DB

# Garmin's primary-benefit labels, from easiest to hardest. NONE stands for
# activities Garmin gave no label (training_effect_label is NULL).
LABEL_ORDER = [
    "RECOVERY", "AEROBIC_BASE", "TEMPO", "LACTATE_THRESHOLD",
    "VO2MAX", "ANAEROBIC_CAPACITY", "SPEED", "NONE",
]

# The three intensity groups of Garmin's training load focus. Garmin splits
# each activity's load across the groups; here a whole activity goes to the
# group of its primary benefit, so the shares are close to Garmin's, not equal.
LABEL_GROUP = {
    "RECOVERY": "Low aerobic",
    "AEROBIC_BASE": "Low aerobic",
    "TEMPO": "High aerobic",
    "LACTATE_THRESHOLD": "High aerobic",
    "VO2MAX": "High aerobic",
    "ANAEROBIC_CAPACITY": "Anaerobic",
    "SPEED": "Anaerobic",
    "NONE": "No label",
}
GROUP_ORDER = ["Low aerobic", "High aerobic", "Anaerobic", "No label"]


def connect(db_path=DEFAULT_DB):
    return duckdb.connect(
        str(db_path), read_only=True, config={"enable_external_access": False}
    )


def week_start(today):
    """Monday of the week that holds today."""
    return today - dt.timedelta(days=today.weekday())


def month_start(today, months_back=0):
    """First day of the month that holds today, or of a month before it."""
    index = today.year * 12 + today.month - 1 - months_back
    return dt.date(index // 12, index % 12 + 1, 1)


def months_ago(today, months):
    """The same day the given number of calendar months earlier, or the last
    day of that month when it is shorter (31 Aug, 2 months -> 30 Jun)."""
    first = month_start(today, months)
    return first.replace(day=min(today.day, calendar.monthrange(first.year, first.month)[1]))


def first_activity_date(con):
    return con.execute("SELECT min(start_time_local)::DATE FROM activities").fetchone()[0]


def totals(con, start, end):
    """Activities, hours, running km and training load from start up to, not
    including, end. One row."""
    return con.execute(
        """
        SELECT count(*) AS activities,
               coalesce(sum(timer_time_s), 0) / 3600 AS hours,
               coalesce(sum(distance_km) FILTER (WHERE sport_group = 'running'), 0) AS running_km,
               coalesce(sum(training_load), 0) AS training_load
        FROM activities
        WHERE start_time_local >= $start AND start_time_local < $end
        """,
        {"start": start, "end": end},
    ).df()


def training_effect_by_month(con, today, months=12):
    """Activities and training load per primary-benefit label for each
    calendar month. The current month is included, so it is partial."""
    return con.execute(
        """
        SELECT date_trunc('month', start_time_local)::DATE AS month,
               coalesce(training_effect_label, 'NONE') AS label,
               count(*) AS activities,
               coalesce(sum(training_load), 0) AS training_load
        FROM activities
        WHERE start_time_local >= $start AND start_time_local < $end
        GROUP BY ALL
        ORDER BY month, label
        """,
        {"start": month_start(today, months - 1), "end": today + dt.timedelta(days=1)},
    ).df()


def training_effect_between(con, start, end):
    """Activities and training load per primary-benefit label from start up
    to, not including, end."""
    return con.execute(
        """
        SELECT coalesce(training_effect_label, 'NONE') AS label,
               count(*) AS activities,
               coalesce(sum(training_load), 0) AS training_load
        FROM activities
        WHERE start_time_local >= $start AND start_time_local < $end
        GROUP BY ALL
        ORDER BY label
        """,
        {"start": start, "end": end},
    ).df()


def types_between(con, start, end):
    """Activities and training load per activity group from start up to, not
    including, end. The groups are the sport groups, with trail running taken
    out of running as its own group."""
    return con.execute(
        """
        SELECT CASE WHEN activity_type = 'Trail Running' THEN 'trail_running'
                    ELSE sport_group END AS activity_group,
               count(*) AS activities,
               coalesce(sum(training_load), 0) AS training_load
        FROM activities
        WHERE start_time_local >= $start AND start_time_local < $end
        GROUP BY ALL
        ORDER BY activity_group
        """,
        {"start": start, "end": end},
    ).df()
