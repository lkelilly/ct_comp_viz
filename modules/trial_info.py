"""
modules/trial_info.py
─────────────────────
Trial Information tab — UI and server logic.
"""

import pandas as pd
from itables import to_html_datatable
from shiny import render, ui

from config import TRIAL_TABLE_LABELS, TRUNCATE_COLS, TRUNCATE_LENGTH


def trial_info_ui():
    return ui.nav_panel(
        "Trial Information",
        ui.div(
            ui.output_ui("trial_table"),
            style="margin:1rem; overflow-x:auto;",
        ),
    )


def trial_info_server(input, output, session, active_data):

    @output
    @render.ui
    def trial_table():
        df = active_data()
        if df is None or (isinstance(df, pd.DataFrame) and df.empty):
            return ui.p("No data loaded. Run a query first.",
                        style="color:#aaa; padding:2rem;")

        df_display = df.rename(columns=TRIAL_TABLE_LABELS)
        display_cols = [TRIAL_TABLE_LABELS[c] for c in TRIAL_TABLE_LABELS if c in df.columns]
        df_display = df_display[display_cols]

        truncate_labels = [TRIAL_TABLE_LABELS.get(c, c) for c in TRUNCATE_COLS]
        for col in truncate_labels:
            if col in df_display.columns:
                df_display[col] = df_display[col].apply(
                    lambda x: (str(x)[:TRUNCATE_LENGTH] + "…")
                    if isinstance(x, str) and len(x) > TRUNCATE_LENGTH
                    else x
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