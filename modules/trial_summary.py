"""
modules/trial_summary.py
────────────────────────
Trial Summary tab — one row per compound with aggregated statistics.
"""

import pandas as pd
from itables import to_html_datatable
from shiny import render, ui

def _build_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate df by compound into one summary row per compound."""
    df = df.copy()

    base = df.groupby("compound", sort=False).apply(
        lambda g: pd.Series({
            "Number of Studies": g["nct_number"].nunique(),
            "Indications": ", ".join(sorted(g["indication"].dropna().unique())),
        })
    ).reset_index()

    # Phase 3 stats — group the Phase 3 subset once
    ph3 = df[df["phases"] == "PHASE3"]

    def _ph3_group_stats(sub):
        pcd = sub["primary_completion_date"]
        if pcd.notna().any():
            idx         = pcd.idxmin()
            first_study = sub.loc[idx, "acronym"]
            first_date  = sub.loc[idx, "primary_completion_date"]
        else:
            first_study = None
            first_date  = None
        return pd.Series({
            "Number of Ph3 Studies": sub["nct_number"].nunique(),
            "First Ph3 Study": first_study,
            "First Ph3 Completion Date": first_date,
        })

    if not ph3.empty:
        ph3_stats = (
            ph3.groupby("compound", sort=False)
            .apply(_ph3_group_stats)
            .reset_index()
        )
    else:
        ph3_stats = pd.DataFrame(columns=[
            "compound", "Number of Ph3 Studies",
            "First Ph3 Study", "First Ph3 Completion Date",
        ])

    summary = base.merge(ph3_stats, on="compound", how="left")
    # Compounds with no Phase 3 studies will be 0
    summary["Number of Ph3 Studies"] = (
        summary["Number of Ph3 Studies"].fillna(0).astype(int)
    )
    summary = summary.rename(columns={"compound": "Compound"})
    return summary[
        [
            "Compound",
            "Number of Studies",
            "Indications",
            "Number of Ph3 Studies",
            "First Ph3 Study",
            "First Ph3 Completion Date",
        ]
    ]


def trial_summary_ui():
    return ui.nav_panel(
        "Trial Summary",
        ui.div(
            ui.output_ui("trial_summary_table"),
            class_="m-3",
        ),
    )


def trial_summary_server(input, output, session, active_data):

    @output(suspend_when_hidden=False)
    @render.ui
    def trial_summary_table():
        df = active_data()
        if df is None or df.empty:
            return ui.p("No data loaded. Run a query first.",
                        class_="text-muted p-4 text-center")

        summary = _build_summary(df)

        table_html = to_html_datatable(
            summary,
            showIndex=False,
            lengthMenu=[10, 25, 50, 100],
            pageLength=10,
            style="width:100%",
            classes="display compact",
            scrollX=True,
        )
        return ui.HTML(table_html)