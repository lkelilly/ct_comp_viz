"""
modules/trial_info.py
─────────────────────
Trial Information tab — UI and server logic.
"""

from itables import to_html_datatable, JavascriptFunction
from shiny import render, ui

from core.utils import filter_by_selections, input_exists


TRIAL_TABLE_LABELS = {
    "nct_number":                 "NCT Number",
    "acronym":                    "Acronym",
    "study_title":                "Study Title",
    "indication":                 "Indication",
    "compound":                   "Compound",
    "relevant_publication":       "Relevant Publication",
    "publication_source":         "Publication Source",
    "interventions":              "Interventions",
    "conditions":                 "Conditions",
    "enrollment":                 "Enrollment",
    "start_date":                 "Start Date",
    "primary_completion_date":    "Primary Completion",
    "completion_date":            "Completion Date",
    "phases":                     "Phase",
    "study_status":               "Status",
    "study_type":                 "Study Type",
    "study_results":              "Results",
    "brief_summary":              "Brief Summary",
    "primary_outcome_measures":          "Primary Outcome Measures",
    "secondary_outcome_measures":        "Secondary Outcome Measures",
    "simplified_primary_outcome":        "Simplified Primary Outcome",
    "simplified_secondary_outcome":      "Simplified Secondary Outcome",
    "inclusion_criteria":                "Inclusion Criteria",
    "exclusion_criteria":                "Exclusion Criteria",
    "sponsor":                    "Sponsor",
    "cluwe_path":                 "CLUWE Path",
}

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

_CTRL_CLICK_JS = """
document.addEventListener('click', function(e) {
    if (!e.ctrlKey) return;
    var cb = e.target;
    if (cb.tagName !== 'INPUT' || cb.type !== 'checkbox') return;
    var group = cb.closest('.shiny-input-checkboxgroup');
    if (!group) return;
    e.preventDefault();
    var all = group.querySelectorAll('input[type=checkbox]');
    all.forEach(function(c) { c.checked = false; });
    cb.checked = true;
    Shiny.setInputValue(group.id, [cb.value]);
}, true);
"""


def trial_info_ui():
    sidebar = ui.sidebar(
        ui.div(
            ui.h6("TRIAL FILTERS", class_="fs-6 fw-bold"),
            ui.tags.small("Ctrl+Click to select only one item.",
                          class_="d-block m-0 text-muted"),
        ),
        ui.output_ui("ti_compound_ui"),
        ui.output_ui("ti_indication_ui"),
        ui.output_ui("ti_phase_ui"),

        ui.hr(class_="my-1"),
        ui.h6("SORT", class_="fs-6 fw-bold"),
        ui.input_select(
            "ti_sort_by", "Sort rows by:",
            choices={
                "start_date":              "Start Date",
                "primary_completion_date": "Primary Completion Date",
                "completion_date":         "Completion Date",
                "phases":                  "Phase",
            },
            selected="start_date",
        ),

        ui.tags.script(ui.HTML(_CTRL_CLICK_JS)),
        width="280px",
        id="ti_sidebar",
    )

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
        df = active_data()
        if df is None or df.empty:
            return ui.div()
        choices = sorted(df["compound"].dropna().unique().tolist())
        return ui.input_checkbox_group("ti_compound", "Compound:", choices=choices, selected=choices)

    @output(suspend_when_hidden=False)
    @render.ui
    def ti_indication_ui():
        df = active_data()
        if df is None or df.empty:
            return ui.div()
        choices = sorted(df["indication"].dropna().unique().tolist())
        return ui.input_checkbox_group("ti_indication", "Indication:", choices=choices, selected=choices)

    @output(suspend_when_hidden=False)
    @render.ui
    def ti_phase_ui():
        df = active_data()
        if df is None or df.empty:
            return ui.div()
        choices = sorted(df["phases"].dropna().unique().tolist())
        return ui.input_checkbox_group("ti_phase", "Phase:", choices=choices, selected=choices)

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
