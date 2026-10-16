"""Web page for the assistant: the same pipeline as app.py, in a browser.

Usage:
    streamlit run src/ui.py
"""

import pandas as pd
import streamlit as st

from app import DEFAULT_MAX_ROWS, answer

st.set_page_config(page_title="Garmin training data", layout="centered")
st.title("Ask about your training")

# A form sends the question only on submit, not on every keystroke.
with st.form("ask"):
    question = st.text_input("Question", placeholder="How many runs did I do last month?")
    submitted = st.form_submit_button("Ask")

if submitted and question.strip():
    with st.spinner("Writing and running the query..."):
        result = answer(question.strip())

    if result["status"] == "declined":
        st.info(f"The model says this cannot be answered from the data ({result['model']}).")
    else:
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
