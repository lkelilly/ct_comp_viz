"""
ui.py
─────
Root app UI. Single page, no landing-page toggle.

Layout:
  - app_navbar       (reactive navbar, mode selector)
  - context_bar_ui   (visible only when data is loaded)
  - slide_panel_ui   (edit-query or archive-select slide-down)
  - main_content_ui  (empty state | source form | inner display tabs)

All renderUI logic lives in server.py.
"""

from shiny import ui

from core.utils import TRUNC_TOOLTIP_CSS, TRUNC_TOOLTIP_JS

app_ui = ui.page_bootstrap(
    ui.head_content(
        ui.tags.script(src="https://cdn.plot.ly/plotly-3.0.1.min.js"),
        ui.busy_indicators.use(pulse=True),
        ui.tags.style(TRUNC_TOOLTIP_CSS),
        ui.tags.script(ui.HTML(TRUNC_TOOLTIP_JS)),
        ui.tags.style("""
            body { font-family: system-ui, Avenir, Helvetica, Arial, sans-serif; margin: 0; }
            .bslib-sidebar-layout { height: calc(100vh - 56px); }

            .bslib-sidebar-layout > .main {
                padding-left: 15px !important;
                padding-right: 0 !important;
            }
            .tab-content > .tab-pane {
                margin-top: 0 !important;
            }

            .hint-text { font-size: .75rem; color: #888; }

            .shiny-input-checkboxgroup label ~ .shiny-options-group,
            .shiny-input-radiogroup label ~ .shiny-options-group {
                margin-top: 0;
            }

            /* Top navbar */
            .navbar .nav-pills .nav-link.active {
                background-color: #fff !important;
                color: #000 !important;
            }

            /* Inner tabs */
            #inner_tabs {
                background: #f8f9fa;
            }

            #inner_tabs .nav-link {
                font-weight: 600;
                margin-left: 0.5rem;
            }

             #inner_tabs .nav-link.active {
                font-weight: 700;
            }


            /* Bootstrap-style callout */
            .bd-callout {
                padding: .6rem 1.25rem;
                border-left: .25rem solid #dee2e6;
                border-radius: .25rem;
                background-color: #fff;
            }
            .bd-callout-info {
                border-left-color: #0dcaf0;
                background-color: #f0fbfd;
                color: #055160;
            }

        """),
    ),
    ui.output_ui("app_navbar"),
    ui.output_ui("context_bar_ui"),
    ui.output_ui("main_content_ui"),
    ui.div(
        ui.input_file("upload_file_new", None, accept=".csv", multiple=False),
        style="display:none;",
    ),
)
