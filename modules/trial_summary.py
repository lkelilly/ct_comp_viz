"""
modules/trial_summary.py
────────────────────────
Trial Summary tab — minimal table showing study_title, phases, and indication.

Indication is derived from the `conditions` column via indication_mapping.py.
"""

import pandas as pd
from itables import to_html_datatable
from shiny import render, ui

from indication_mapping import map_indication


# Column to display → DataFrame column name
_DISPLAY_COLS = {
    "Acronym":     "acronym",
    "Compound":    "compound",
    "Study Title": "study_title",
    "Phase":       "phases",
    "Indication":  "indication",
}


def trial_summary_ui():
    return ui.nav_panel(
        "Trial Summary",
        ui.div(
            ui.output_ui("trial_summary_table"),
            style="margin:1rem; overflow-x:auto;",
        ),
    )


def trial_summary_server(input, output, session, active_data):

    @output
    @render.ui
    def trial_summary_table():
        df = active_data()
        if df is None or (isinstance(df, pd.DataFrame) and df.empty):
            return ui.p("No data loaded. Run a query first.",
                        style="color:#aaa; padding:2rem;")

        # indication is already derived by process_raw_ctgov; add fallback for safety
        df = df.copy()
        if "indication" not in df.columns:
            if "conditions" in df.columns:
                df["indication"] = df["conditions"].apply(map_indication)
            else:
                df["indication"] = "Other"

        # Keep only the three display columns that exist
        cols_to_keep = [
            col for col in _DISPLAY_COLS.values()
            if col in df.columns
        ]
        df_display = df[cols_to_keep].rename(
            columns={v: k for k, v in _DISPLAY_COLS.items()}
        )

        table_html = to_html_datatable(
            df_display,
            showIndex=False,
            lengthMenu=[10, 25, 50, 100],
            pageLength=10,
            style="width:100%",
            classes="display compact",
            scrollX=True,
        )
        return ui.HTML(table_html)
