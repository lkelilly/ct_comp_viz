"""
ui.py
─────
Assembles the sidebar, remaining tabs, main_layout, and app_ui.
Landing page UI lives in modules/landing.py.
Trial Information UI lives in modules/trial_info.py.
Trail Summary UI lives in modules/trail_summary.py.
Compare page UI lives in modules/compare.py.
"""

from shiny import ui

from modules.landing       import primary_boxes, study_status_widget, more_filters_widgets
from modules.trial_info    import trial_info_ui
from modules.trial_summary import trial_summary_ui
from modules.compare       import compare_ui
from modules.viz           import viz_ui


# ── Sidebar ───────────────────────────────────────────────────────────────────

filter_sidebar = ui.sidebar(
    ui.h6("SEARCH & FILTERS",
          style="letter-spacing:.08em; color:#888; margin-bottom:.75rem; font-size:.75rem;"),

    *primary_boxes(suffix=""),
    study_status_widget(),

    ui.accordion(
        ui.accordion_panel("More Filters", *more_filters_widgets()),
        open=[], id="sidebar_accordion",
    ),

    ui.hr(),
    ui.input_action_button(
        "btn_rerun", "Re-run Query",
        style="width:100%; background:#1a1a2e; color:#fff; border:none; "
              "padding:.6rem; border-radius:4px;",
    ),
    ui.input_action_button(
        "btn_back", "← Back to Search",
        style="width:100%; margin-top:.5rem; background:transparent; color:#555; "
              "border:1px solid #ccc; padding:.6rem; border-radius:4px;",
    ),

    width="320px",
    id="main_sidebar",
)


# ── Tabs that haven't been moved to modules yet ───────────────────────────────

tab_console = ui.nav_panel(
    "Console",
    ui.div(
        ui.div(
            ui.span("Query log", style="font-weight:600; font-size:.85rem; color:#ccc;"),
            ui.input_action_button(
                "btn_clear_log", "Clear",
                style=(
                    "background:transparent; border:1px solid #444; color:#aaa;"
                    " padding:.2rem .75rem; font-size:.75rem; border-radius:3px; cursor:pointer;"
                ),
            ),
            style="display:flex; justify-content:space-between; align-items:center; margin-bottom:.5rem;",
        ),
        ui.output_ui("console_log"),
        style=(
            "background:#1a1a1a; border-radius:8px; padding:1rem; margin:1rem;"
            " font-family:'Courier New', monospace; font-size:.8rem;"
            " min-height:300px; max-height:60vh; overflow-y:auto;"
        ),
    ),
)


# ── Main layout ───────────────────────────────────────────────────────────────

main_layout = ui.page_navbar(
    viz_ui(),
    trial_info_ui(),
    trial_summary_ui(),
    compare_ui(),
    tab_console,
    title="DEMO",
    sidebar=filter_sidebar,
    id="main_navbar",
)


# ── Root app UI ───────────────────────────────────────────────────────────────

app_ui = ui.page_fluid(
    ui.head_content(
        ui.tags.style("""
            body { font-family: 'Inter', sans-serif; margin: 0; }
            body:has(#viz_sidebar) #viz_sidebar ~ .main { overflow: hidden !important; }
            .bslib-sidebar-layout { height: 100vh; }
            /* Only disable scroll on the outermost bslib layout */
            .bslib-sidebar-layout:not(.bslib-sidebar-layout .bslib-sidebar-layout) {
                overflow: hidden !important;
            }
            .accordion-button { font-size: .85rem; }
            .shiny-input-checkboxgroup,
            .shiny-input-radiogroup { margin-bottom: .25rem; }
            .shiny-input-checkboxgroup .shiny-options-group,
            .shiny-input-radiogroup .shiny-options-group {
                padding-top: .25rem; margin-top: .5rem; margin-bottom: .5rem;
            }
            .shiny-input-checkboxgroup label,
            .shiny-input-radiogroup label {
                display: flex; align-items: center; gap: .4rem;
                padding: .3rem 0; margin-bottom: 0; line-height: 1.3;
            }
            .shiny-input-checkboxgroup .checkbox,
            .shiny-input-radiogroup .radio { margin: 0; padding-left: 0; }
            @media (max-width: 1519px) {
                #viz_plot .ytick text { display: none; }
            }
        """)
    ),
    ui.output_ui("active_view"),
)