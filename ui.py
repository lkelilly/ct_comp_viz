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

_NCT_LINK_CLICK_JS = """
document.addEventListener('click', function(e) {
    var link = e.target.closest('.nct-link');
    if (!link) return;
    e.preventDefault();
    Shiny.setInputValue('selected_nct', link.dataset.nct, {priority: 'event'});
});
"""

_TI_NCT_LINK_CLICK_JS = """
document.addEventListener('click', function(e) {
    var link = e.target.closest('.ti-nct-link');
    if (!link) return;
    e.preventDefault();
    Shiny.setInputValue('ti_edit_nct', link.dataset.nct, {priority: 'event'});
});
"""

app_ui = ui.page_bootstrap(
    ui.head_content(
        ui.tags.script(src="https://cdn.plot.ly/plotly-3.0.1.min.js"),
        ui.busy_indicators.use(pulse=True),
        ui.tags.style(TRUNC_TOOLTIP_CSS),
        ui.tags.script(ui.HTML(TRUNC_TOOLTIP_JS)),
        ui.tags.script(ui.HTML(_CTRL_CLICK_JS)),
        ui.tags.script(ui.HTML(_NCT_LINK_CLICK_JS)),
        ui.tags.script(ui.HTML(_TI_NCT_LINK_CLICK_JS)),
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
        ui.tags.style("""
          .shiny-input-container:has(#query_intr_land),
          .shiny-input-container:has(#query_locn_land),
          .shiny-input-container:has(#include_other_id_land) {
            margin-bottom: 0 !important;
          }
          .shiny-input-container:has(#filter_status) {
            margin-top: 0 !important;
            margin-bottom: 0 !important;
          }
          .shiny-input-container:has(#upload_file) {
            margin-bottom: 0 !important;
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