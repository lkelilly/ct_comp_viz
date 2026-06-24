"""
ui.py
─────
Assembles the sidebar, remaining tabs, main_layout, and app_ui.
Landing page UI lives in modules/landing.py.
Trial Information UI lives in modules/trial_info.py.
Trail Summary UI lives in modules/trail_summary.py.
Compare page UI lives in modules/compare.py.
Viz page UI lives in modules/viz.py.
"""

from shiny import ui

from modules.trial_info    import trial_info_ui
from modules.trial_summary import trial_summary_ui
from modules.compare       import compare_ui
from modules.viz           import viz_ui


# ── Tabs that haven't been moved to modules yet ───────────────────────────────

tab_console = ui.nav_panel(
    "Console",
    ui.div(
        ui.div(
            ui.span("Query log", class_="fw-semibold", style="font-size:.85rem; color:#ccc;"),
            ui.input_action_button(
                "btn_clear_log", "Clear",
                class_="btn btn-outline-secondary btn-sm",
            ),
            class_="d-flex justify-content-between align-items-center mb-2",
        ),
        ui.output_ui("console_log"),
        class_="m-3 p-3 font-monospace overflow-y-auto",
        style=(
            "background:#1a1a1a; border-radius:8px; font-size:.8rem;"
            " min-height:300px; max-height:60vh;"
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
    ui.nav_spacer(),
    ui.nav_control(
        ui.input_action_button(
            "btn_back", "Back to Search/Upload",
            class_="btn btn-dark btn-sm mx-2 my-1",
        )
    ),
    title="DEMO",
    id="main_navbar",
)


# ── Root app UI ───────────────────────────────────────────────────────────────

app_ui = ui.page_bootstrap(
    ui.head_content(
        ui.tags.script(src="https://cdn.plot.ly/plotly-3.0.1.min.js"),
        ui.tags.style("""
            body { font-family: system-ui, Avenir, Helvetica, Arial, sans-serif; margin: 0; }
            .bslib-sidebar-layout { height: 100vh; }
            /* Only disable scroll on the outermost bslib layout */
            .bslib-sidebar-layout:not(.bslib-sidebar-layout .bslib-sidebar-layout) {
                overflow: hidden !important;
            }
            .accordion-button { font-size: .85rem; }

            /* Shared section/sidebar header */
            .section-header {
                letter-spacing: .08em;
                color: #333;
                font-size: .85rem;
                font-weight: 700;
            }

            /* Selection group styling */
            .shiny-input-checkboxgroup label ~ .shiny-options-group,
            .shiny-input-radiogroup label ~ .shiny-options-group {
                margin-top: 0;
            }
            @media (max-width: 1519px) {
                #viz_plot .ytick text { display: none; }
            }
        """)
    ),
    ui.div(ui.input_checkbox("show_main_flag", "", value=False),
           style="display:none;"),
    ui.panel_conditional("!input.show_main_flag", ui.output_ui("landing_view")),
    ui.panel_conditional("input.show_main_flag", main_layout),
)