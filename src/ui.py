"""Web page for the assistant: fixed stats, and the same pipeline as app.py.

Usage:
    streamlit run src/ui.py
"""

import datetime as dt

import altair as alt
import pandas as pd
import streamlit as st

import dashboard
from app import DEFAULT_MAX_ROWS, answer

# Display names for Garmin's primary-benefit labels, in dashboard.LABEL_ORDER.
LABEL_NAMES = {
    "RECOVERY": "Recovery",
    "AEROBIC_BASE": "Base",
    "TEMPO": "Tempo",
    "LACTATE_THRESHOLD": "Threshold",
    "VO2MAX": "VO2 max",
    "ANAEROBIC_CAPACITY": "Anaerobic",
    "SPEED": "Speed",
    "NONE": "No label",
}

# One colour per group in dashboard.GROUP_ORDER, after Garmin's training load
# focus: light blue, orange, purple, and grey for "No label". Each mode has its
# own steps, checked with the dataviz skill's palette validator (all pairs pass
# colour-blind separation; light blue is under 3:1 contrast on white, so
# every bar has a tooltip and the charts a legend).
GROUP_COLOURS = {
    "light": ["#3fa0e0", "#eb6834", "#6250d6", "#898781"],
    "dark": ["#2f9ad8", "#d95926", "#8a5ee0", "#898781"],
}
# Page background, drawn as a gap between stacked labels of the same group.
SURFACE = {"light": "#ffffff", "dark": "#0e1117"}
# One neutral colour for charts whose bars are told apart by their axis labels,
# so they do not borrow the meaning of the intensity group colours.
NEUTRAL = {"light": "#52514e", "dark": "#c3c2b7"}

SPORT_NAMES = {
    "running": "Running", "strength": "Strength", "cardio": "Cardio", "cycling": "Cycling",
    "rowing": "Rowing", "hiking": "Hiking", "skiing": "Skiing", "other": "Other",
}

MEASURES = {"Activities": "activities", "Training load": "training_load"}
CUSTOM = "Custom range..."
PERIODS = [
    "This week", "This month", "Past 7 days", "Past 30 days",
    "Past 3 months", "Past 6 months", "This year", CUSTOM,
]


def theme():
    return "dark" if st.context.theme.type == "dark" else "light"


def show_totals(df, previous=None):
    """Four numbers in a row; with previous, each shows the change from it."""
    row = df.iloc[0]
    before = previous.iloc[0] if previous is not None else None
    fields = [
        ("Activities", "activities", "{:.0f}"),
        ("Hours", "hours", "{:.1f}"),
        ("Running km", "running_km", "{:.1f}"),
        ("Training load", "training_load", "{:.0f}"),
    ]
    for column, (title, field, fmt) in zip(st.columns(4), fields):
        delta = None if before is None else fmt.format(row[field] - before[field])
        column.metric(title, fmt.format(row[field]), delta)


def period_dates(period, today, con):
    """First and last day of the chosen period, both included. None while a
    custom range has only its start date picked."""
    if period == CUSTOM:
        first = dashboard.first_activity_date(con)
        picked = st.date_input(
            "Dates",
            value=(max(first, today - dt.timedelta(days=29)), today),
            min_value=first,
            max_value=today,
            format="DD.MM.YYYY",
            key="te_dates",
        )
        return tuple(picked) if len(picked) == 2 else None
    start = {
        "This week": dashboard.week_start(today),
        "This month": dashboard.month_start(today),
        "Past 7 days": today - dt.timedelta(days=6),
        "Past 30 days": today - dt.timedelta(days=29),
        "Past 3 months": dashboard.months_ago(today, 3),
        "Past 6 months": dashboard.months_ago(today, 6),
        "This year": today.replace(month=1, day=1),
    }[period]
    return start, today


def format_range(start, end):
    """22 Jul - 22 Oct 2026, with the first year left out when it is the same."""
    first = f"{start.day} {start:%b}" + ("" if start.year == end.year else f" {start.year}")
    return f"{first} - {end.day} {end:%b %Y}"


def measure_axis(measure):
    """Counts get whole-number ticks only."""
    return alt.Axis(format="d", tickMinStep=1) if measure == "activities" else alt.Axis()


def label_chart(df, x, measure, title):
    """Bars per primary-benefit label, coloured by Garmin's intensity group."""
    names = [LABEL_NAMES[label] for label in dashboard.LABEL_ORDER]
    df = df.assign(
        benefit=df["label"].map(LABEL_NAMES),
        group=df["label"].map(dashboard.LABEL_GROUP),
        order=df["label"].map(dashboard.LABEL_ORDER.index),
    )
    colour = alt.Color(
        "group:N",
        scale=alt.Scale(domain=dashboard.GROUP_ORDER, range=GROUP_COLOURS[theme()]),
        legend=alt.Legend(title=None, orient="bottom"),
    )
    axis = measure_axis(measure)
    tooltip = [
        alt.Tooltip("benefit:N", title="Benefit"),
        alt.Tooltip("group:N", title="Group"),
        alt.Tooltip(f"{measure}:Q", title=title, format=".0f"),
    ]
    bars = alt.Chart(df).mark_bar(stroke=SURFACE[theme()], strokeWidth=2)
    if x == "month":
        chart = bars.encode(
            x=alt.X("yearmonth(month):O", title=None, axis=alt.Axis(format="%b", labelAngle=0)),
            y=alt.Y(f"{measure}:Q", title=title, axis=axis),
            color=colour,
            order=alt.Order("order:Q"),
            tooltip=[alt.Tooltip("yearmonth(month):O", title="Month", format="%b %Y")] + tooltip,
        )
    else:
        chart = bars.encode(
            y=alt.Y("benefit:N", title=None, sort=names),
            x=alt.X(f"{measure}:Q", title=title, axis=axis),
            color=colour,
            tooltip=tooltip,
        )
    st.altair_chart(chart, width="stretch")


def type_chart(df, measure, title):
    """One bar per sport group, largest first."""
    df = df.assign(sport=df["sport_group"].map(SPORT_NAMES).fillna(df["sport_group"]))
    chart = (
        alt.Chart(df)
        .mark_bar(color=NEUTRAL[theme()])
        .encode(
            y=alt.Y("sport:N", title=None, sort="-x"),
            x=alt.X(f"{measure}:Q", title=title, axis=measure_axis(measure)),
            tooltip=[
                alt.Tooltip("sport:N", title="Type"),
                alt.Tooltip(f"{measure}:Q", title=title, format=".0f"),
            ],
        )
    )
    st.altair_chart(chart, width="stretch")


def group_months(df, group, measure, title, today, months=12):
    """One small bar chart per label of a group, all in the group's colour and
    on one scale, so labels of the same colour are compared by position."""
    labels = [label for label in dashboard.LABEL_ORDER if dashboard.LABEL_GROUP[label] == group]
    # Every month for every label, with 0 where there was none, so all the
    # small charts have the same months on the x axis.
    grid = pd.MultiIndex.from_product(
        [pd.date_range(dashboard.month_start(today, months - 1), periods=months, freq="MS"), labels],
        names=["month", "label"],
    )
    df = (
        df.assign(month=pd.to_datetime(df["month"]))
        .set_index(["month", "label"])[[measure]]
        .reindex(grid, fill_value=0)
        .reset_index()
    )
    top = max(df[measure].max(), 1)
    colour = GROUP_COLOURS[theme()][dashboard.GROUP_ORDER.index(group)]
    for label in labels:
        st.caption(LABEL_NAMES[label])
        chart = (
            alt.Chart(df[df["label"] == label])
            .mark_bar(color=colour)
            .encode(
                x=alt.X("yearmonth(month):O", title=None, axis=alt.Axis(format="%b", labelAngle=0)),
                y=alt.Y(f"{measure}:Q", title=None, scale=alt.Scale(domain=[0, top]), axis=measure_axis(measure)),
                tooltip=[
                    alt.Tooltip("yearmonth(month):O", title="Month", format="%b %Y"),
                    alt.Tooltip(f"{measure}:Q", title=title, format=".0f"),
                ],
            )
            .properties(height=110)
        )
        st.altair_chart(chart, width="stretch")


def show_stats(today):
    with dashboard.connect() as con:
        st.subheader("This week")
        show_totals(dashboard.totals(con, dashboard.week_start(today), today + dt.timedelta(days=1)))

        # Month to date against the same number of days of last month.
        this_month = dashboard.month_start(today)
        last_month = dashboard.month_start(today, 1)
        days = (today - this_month).days + 1
        st.subheader("This month")
        show_totals(
            dashboard.totals(con, this_month, today + dt.timedelta(days=1)),
            dashboard.totals(con, last_month, min(last_month + dt.timedelta(days=days), this_month)),
        )
        st.caption(f"Change against the first {days} days of last month.")

        st.subheader("Breakdown")
        choice = st.segmented_control("Show", list(MEASURES), default="Activities", key="te_measure")
        measure = MEASURES[choice or "Activities"]
        title = choice or "Activities"
        period = st.selectbox("Period", PERIODS, index=PERIODS.index("Past 30 days"), key="te_period")
        dates = period_dates(period, today, con)
        if dates is None:
            st.caption("Pick the end date.")
        else:
            start, end = dates
            by_label = dashboard.training_effect_between(con, start, end + dt.timedelta(days=1))
            st.caption(f"{format_range(start, end)}, {by_label['activities'].sum()} activities")
            st.markdown("**Training effect**")
            label_chart(by_label, "label", measure, title)
            st.markdown("**Activity types**")
            type_chart(dashboard.types_between(con, start, end + dt.timedelta(days=1)), measure, title)

        st.subheader("Training effect by month")
        groups = ["All"] + dashboard.GROUP_ORDER[:3]
        detail = st.segmented_control("Detail", groups, default="All", key="te_detail") or "All"
        monthly = dashboard.training_effect_by_month(con, today)
        if detail == "All":
            label_chart(monthly, "month", measure, title)
        else:
            group_months(monthly, detail, measure, title, today)


def show_ask():
    # A form sends the question only on submit, not on every keystroke.
    with st.form("ask"):
        question = st.text_input("Question", placeholder="How many runs did I do last month?")
        submitted = st.form_submit_button("Ask")

    if submitted and question.strip():
        with st.spinner("Writing and running the query..."):
            result = answer(question.strip())

        if result["status"] == "declined":
            st.info(f"The model says this cannot be answered from the data ({result['model']}).")
            if result["interpretation"]:
                st.caption(result["interpretation"])
        else:
            if result["interpretation"]:
                st.markdown(f"**Read as:** {result['interpretation']}")
            st.caption(f"{result['model']}, {result['latency_s']:.1f} s")
            st.code(result["sql"], language="sql")
            if result["status"] == "rejected":
                st.error(f"Not run, {result['error']}")
            elif result["status"] == "failed":
                st.error(f"Query failed: {result['error']}")
            else:
                st.dataframe(
                    pd.DataFrame(result["rows"], columns=result["columns"]), hide_index=True
                )
                if result["truncated"]:
                    st.caption(f"First {DEFAULT_MAX_ROWS} rows shown.")


st.set_page_config(page_title="Garmin training data", layout="centered")
st.title("Training")

stats_tab, ask_tab = st.tabs(["Stats", "Ask"])
with stats_tab:
    show_stats(dt.date.today())
with ask_tab:
    show_ask()
