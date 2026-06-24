"""
modules/trial_info.py
─────────────────────
Trial Information tab — UI and server logic.
"""

from itables import to_html_datatable, JavascriptFunction
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
        if df is None or df.empty:
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

        pub_label = TRIAL_TABLE_LABELS.get("relevant_publication", "Relevant Publication")
        col_defs = []
        if pub_label in display_cols:
            pub_idx = display_cols.index(pub_label)
            col_defs.append({
                "targets": [pub_idx],
                "render": JavascriptFunction(
                    "function(data, type, row) {"
                    "  if (type !== 'display' || !data || data === 'NA') return data;"
                    "  return data.split(' | ').map(function(part) {"
                    "    part = part.trim();"
                    "    if (part.indexOf('http://') === 0 || part.indexOf('https://') === 0) {"
                    "      return '<a href=\"' + part + '\" target=\"_blank\">' + part + '</a>';"
                    "    }"
                    "    return part;"
                    "  }).join(' | ');"
                    "}"
                ),
            })

        dt_kwargs = dict(
            showIndex=False,
            lengthMenu=[10, 25, 50, 100],
            pageLength=10,
            style="width:100%",
            classes="display compact",
            scrollX=True,
        )
        if col_defs:
            dt_kwargs["columnDefs"] = col_defs

        table_html = to_html_datatable(df_display, **dt_kwargs)
        return ui.HTML(table_html)