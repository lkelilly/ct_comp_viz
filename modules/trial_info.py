"""
modules/trial_info.py
─────────────────────
Trial Information tab — UI and server logic.
"""

from itables import to_html_datatable, JavascriptFunction
from shiny import render, ui

from core.utils import filter_by_selections, input_exists, make_filter_ui, filter_sort_sidebar, COL_LABELS


def _insert_after(d, after_key, extra):
    """Return a copy of dict `d` with `extra`'s items inserted right after
    `after_key`. Preserves key order, which trial_table below relies on to
    determine displayed column order."""
    out = {}
    for k, v in d.items():
        out[k] = v
        if k == after_key:
            out.update(extra)
    return out


TRIAL_TABLE_LABELS = _insert_after(COL_LABELS, "brief_summary", {
    "primary_outcome_measures":   "Primary Outcome Measures",
    "secondary_outcome_measures": "Secondary Outcome Measures",
})

TRUNCATE_COLS = [
    "brief_summary",
    "primary_outcome_measures",
    "secondary_outcome_measures",
    "simplified_primary_outcome",
    "simplified_secondary_outcome",
    "conditions",
    "interventions",
    "inclusion_criteria",
    "exclusion_criteria",
]

TRUNCATE_LENGTH = 200


def trial_info_ui():
    sidebar = filter_sort_sidebar("ti")

    return ui.nav_panel(
        "Trial Information",
        ui.layout_sidebar(
            sidebar,
            ui.div(
                ui.output_ui("trial_table"),
            ),
        ),
    )


def trial_info_server(input, output, session, active_data):

    @output(suspend_when_hidden=False)
    @render.ui
    def ti_compound_ui():
        return make_filter_ui(active_data, "compound", "ti_compound", "Compound:")

    @output(suspend_when_hidden=False)
    @render.ui
    def ti_indication_ui():
        return make_filter_ui(active_data, "indication", "ti_indication", "Indication:")

    @output(suspend_when_hidden=False)
    @render.ui
    def ti_phase_ui():
        return make_filter_ui(active_data, "phases", "ti_phase", "Phase:")

    @output(suspend_when_hidden=False)
    @render.ui
    def trial_table():
        df = active_data()
        if df is None or df.empty:
            return ui.p("Returned 0 studies. Check your query message.",
                        class_="text-muted p-4 text-center")

        df = filter_by_selections(df, input, [
            ("compound",   "ti_compound"),
            ("indication", "ti_indication"),
            ("phases",     "ti_phase"),
        ])

        sort_col = input.ti_sort_by() if input_exists(input, "ti_sort_by") else "start_date"
        if sort_col in df.columns:
            df = df.sort_values(sort_col, na_position="last")

        df_display = df.rename(columns=TRIAL_TABLE_LABELS)
        display_cols = [TRIAL_TABLE_LABELS[c] for c in TRIAL_TABLE_LABELS if c in df.columns]
        df_display = df_display[display_cols]

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
                    "      return '<a href=\"' + part + '\" target=\"_blank\" class=\"d-block\">' + part + '</a>';"
                    "    }"
                    "    return part;"
                    "  }).join('');"
                    "}"
                ),
            })

        cluwe_label = TRIAL_TABLE_LABELS.get("cluwe_path", "CLUWE Path")
        if cluwe_label in display_cols:
            cluwe_idx = display_cols.index(cluwe_label)
            col_defs.append({
                "targets": [cluwe_idx],
                "render": JavascriptFunction(
                    "function(data, type, row) {"
                    "  if (type !== 'display' || !data || data === 'NA') return data;"
                    "  return data.split(' | ').map(function(part) {"
                    "    return '<span class=\"d-block\">' + part.trim() + '</span>';"
                    "  }).join('');"
                    "}"
                ),
            })

        truncate_labels = [TRIAL_TABLE_LABELS.get(c, c) for c in TRUNCATE_COLS]
        truncate_idxs = [display_cols.index(lbl) for lbl in truncate_labels if lbl in display_cols]
        if truncate_idxs:
            col_defs.append({
                "targets": truncate_idxs,
                "render": JavascriptFunction(
                    "function(data, type, row) {"
                    "  if (type !== 'display' || data == null) return data;"
                    "  var s = String(data);"
                    f"  if (s.length <= {TRUNCATE_LENGTH}) return s;"
                    f"  var shortText = s.slice(0, {TRUNCATE_LENGTH}) + '…';"
                    "  var fullAttr = s.replace(/\"/g, '&quot;');"
                    "  return '<span class=\"trunc\" data-full=\"' + fullAttr + '\">' + shortText + '</span>';"
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
