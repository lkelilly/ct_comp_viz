"""
modules/landing.py
──────────────────
Landing page — UI and all landing-specific server logic.

Owns:
  UI:     landing_page layout, widget factory functions
  Server: active_view switcher, loading overlay, _on_run, _on_back,
          upload_status, api_error_msg, safe input helpers, _query_kwargs,
          filter snapshot/restore
"""

import asyncio
from datetime import datetime

from shiny import reactive, render, ui

from utils import _valid_date


# ── Widget factories (used by both landing and ui.py sidebar) ─────────────────

def primary_boxes(suffix=""):
    s = suffix
    return [
        ui.input_text(f"query_cond{s}", "Condition/disease",      placeholder="e.g. Type 2 Diabetes"),
        ui.input_text(f"query_term{s}", "Other terms",            placeholder="NCT Number, Drug Name, etc."),
        ui.input_text(f"query_intr{s}", "Intervention/treatment", placeholder="e.g. Tirzepatide"),
        ui.input_text(f"query_other_id{s}", "Alternative compound name",
                      placeholder="e.g. LY3819469"),
        ui.input_text(f"query_locn{s}", "Location",
                      placeholder="Address, city, state, zip code, or country"),
    ]


def study_status_widget(inline=False):
    return ui.input_radio_buttons(
        "filter_status", "Study Status",
        choices={
            "": "All studies",
            "RECRUITING|NOT_YET_RECRUITING|ENROLLING_BY_INVITATION":
                "Recruiting and not yet recruiting studies",
        },
        selected="",
        inline=inline,
    )


def more_filters_widgets():
    return [
        ui.p("Age", style="font-weight:600; font-size: 0.9rem; margin-bottom:.25rem;"),
        ui.layout_columns(
            ui.input_numeric("filter_age_min", "Minimum age (years)", value=None, min=0, max=120),
            ui.input_numeric("filter_age_max", "Maximum age (years)", value=None, min=0, max=120),
            col_widths=[6, 6],
        ),
        ui.hr(style="margin:.5rem 0;"),
        ui.input_select(
            "filter_sex", "Sex",
            choices={"All": "All", "FEMALE": "Female", "MALE": "Male"},
            selected="All",
        ),
        ui.input_checkbox("filter_healthy", "Accepts healthy volunteers", value=False),
        ui.hr(style="margin:.5rem 0;"),
        ui.input_checkbox_group(
            "filter_phase", "Phase",
            choices={
                "EARLY_PHASE1": "Early Phase 1", "PHASE1": "Phase 1",
                "PHASE2": "Phase 2",             "PHASE3": "Phase 3",
                "PHASE4": "Phase 4",             "NA":     "Not applicable",
            },
            selected=[],
        ),
        ui.hr(style="margin:.5rem 0;"),
        ui.input_checkbox_group(
            "filter_study_type", "Study Type",
            choices={
                "INTERVENTIONAL": "Interventional", "OBSERVATIONAL": "Observational",
                "EXPANDED_ACCESS": "Expanded access",
            },
            selected=[],
        ),
        ui.hr(style="margin:.5rem 0;"),
        ui.input_checkbox_group(
            "filter_funder", "Funder Type",
            choices={"NIH": "NIH", "FED": "Other federal",
                     "INDUSTRY": "Industry", "OTHER": "Other"},
            selected=[],
        ),
        ui.hr(style="margin:.5rem 0;"),
        ui.input_radio_buttons(
            "filter_results", "Study Results",
            choices=["Any", "With results", "Without results"],
            selected="Any", inline=True,
        ),
        ui.hr(style="margin:.5rem 0;"),
        ui.p("Start date", style="font-weight:600; margin-bottom:.25rem;"),
        ui.layout_columns(
            ui.input_text("filter_start_from", "From", placeholder="YYYY-MM-DD"),
            ui.input_text("filter_start_to",   "To",   placeholder="YYYY-MM-DD"),
            col_widths=[6, 6],
        ),
        ui.p("Primary completion date",
             style="font-weight:600; font-size: 0.9rem; margin:.5rem 0 .25rem;"),
        ui.layout_columns(
            ui.input_text("filter_completion_from", "From", placeholder="YYYY-MM-DD"),
            ui.input_text("filter_completion_to",   "To",   placeholder="YYYY-MM-DD"),
            col_widths=[6, 6],
        ),
        ui.hr(style="margin:.5rem 0;"),
        ui.p("Enrollment size", style="font-weight:600; font-size: 0.9rem; margin-bottom:.25rem;"),
        ui.layout_columns(
            ui.input_numeric("filter_enroll_min", "Min", value=None, min=0),
            ui.input_numeric("filter_enroll_max", "Max", value=None, min=0),
            col_widths=[6, 6],
        ),
        ui.hr(style="margin:.5rem 0;"),
        ui.p("Additional search fields",
             style="font-weight:600; font-size: 0.9rem; margin-bottom:.25rem;"),
        ui.input_text("query_spons",  "Sponsor/collaborator", placeholder="e.g. Eli Lilly and Company"),
        ui.input_text("query_titles", "Title/acronym",        placeholder="e.g. SURMOUNT"),
        ui.input_text("query_id",     "NCT/study ID",         placeholder="e.g. NCT04184622"),
        ui.input_text("query_outc",   "Outcome measure",      placeholder="e.g. HbA1c"),
        ui.hr(style="margin:.5rem 0;"),
        ui.p("Sorting", style="font-weight:600; font-size: 0.9rem; margin-bottom:.25rem;"),
        ui.input_select(
            "sort_order", "Sort by",
            choices={
                "LastUpdatePostDate:desc": "Last updated (newest)",
                "LastUpdatePostDate:asc":  "Last updated (oldest)",
                "StartDate:desc":          "Start date (newest)",
                "StartDate:asc":           "Start date (oldest)",
                "EnrollmentCount:desc":    "Enrollment (largest)",
            },
            selected="LastUpdatePostDate:desc",
        ),
        ui.input_numeric("max_results", "Max results", value=500, min=10, max=10000, step=100),
    ]


# ── Landing page UI ───────────────────────────────────────────────────────────

def landing_page_ui():
    return ui.div(
        ui.div(
            ui.h2("Test", style="letter-spacing:.15em; margin-bottom:.25rem; font-size:1.75rem; font-weight:700;"),
            ui.p("hello",
                 style="color:#888; margin-bottom:2rem; font-size:.95rem;"),

            ui.h6("UPLOAD YOUR OWN DATA",
                  style="letter-spacing:.08em; color:#333; font-size:.85rem; font-weight:700; margin-bottom:.6rem;"),
            ui.div(
                ui.input_file("upload_file", None, accept=".csv",
                              button_label="Choose CSV", multiple=False),
                ui.div(ui.output_text("upload_status"),
                       style="font-size:.8rem; color:#888; margin-top:.35rem; min-height:1.1rem;"),
                style="padding-top: .2rem; text-align:center; margin-bottom:.2rem;",
            ),

            ui.h6("QUERY CLINICALTRIALS.GOV",
                  style="letter-spacing:.08em; color:#333; font-size:.85rem; font-weight:700; margin-bottom:.6rem;"),
            ui.div(
                ui.div(
                    ui.layout_columns(
                        ui.div(
                            ui.input_text("query_cond_land", "Condition/disease",
                                          placeholder="e.g. Type 2 Diabetes"),
                            ui.input_text("query_intr_land", "Intervention/treatment",
                                          placeholder="e.g. Tirzepatide"),
                        ),
                        ui.div(
                            ui.input_text("query_term_land", "Other terms",
                                          placeholder="NCT number, Drug Name, etc."),
                            ui.input_text("query_locn_land", "Location",
                                          placeholder="Address, city, state, zip code, or country"),
                        ),
                        col_widths=[6, 6],
                    ),
                    ui.layout_columns(
                        ui.div(
                            ui.input_checkbox("include_other_id_land", "Include alternative compound name", value=False),
                            style="display:flex; align-items:center;",
                        ),
                        ui.panel_conditional(
                            "input.include_other_id_land",
                            ui.input_text(
                                "query_other_id_land", None,
                                placeholder="e.g. LY3819469",
                            ),
                        ),
                        col_widths=[6, 6],
                    ),
                    ui.layout_columns(
                        study_status_widget(inline=True),
                        col_widths=[12],
                    ),
                    style="display:flex; flex-direction:column; gap:0;",
                ),
                style="border:2px solid #e8e8e8; border-radius:8px; padding:1.25rem 1.25rem 0 1.25rem;",
            ),

            ui.tags.style("""
              #landing_accordion .accordion-button {
                font-size: 1rem;
                font-weight: 600;
              }
              .shiny-input-container:has(#query_intr_land),
              .shiny-input-container:has(#query_locn_land),
              .shiny-input-container:has(#include_other_id_land) {
                margin-bottom: 0 !important;
              }
              .shiny-input-container:has(#filter_status) {
                margin-top: 0 !important;
                margin-bottom: 0 !important;
              }
            """),
            ui.div(
                ui.accordion(
                    ui.accordion_panel(
                        "More Filters",
                        ui.layout_columns(
                            ui.div(*more_filters_widgets()[:28]),
                            ui.div(*more_filters_widgets()[28:]),
                            col_widths=[6, 6],
                        ),
                    ),
                    open=[], id="landing_accordion",
                ),
                style=(
                    "border:2px solid #e8e8e8; border-radius:8px; overflow:hidden;"
                    " margin-top:.75rem;"
                ),
            ),

            ui.hr(style="margin:1.75rem 0;"),
            ui.div(
                ui.output_text("api_error_msg"),
                ui.input_action_button(
                    "btn_run", "Run Query",
                    style=(
                        "background:#1a1a2e; color:#fff; border:none;"
                        " padding:.75rem 3rem; font-size:1rem; border-radius:6px;"
                        " cursor:pointer; letter-spacing:.05em;"
                    ),
                ),
                style="text-align:center;",
            ),

            style=(
                "background:#fff; border-radius:12px; padding:3rem;"
                " box-shadow:0 4px 32px rgba(0,0,0,.08); width:100%; max-width:860px;"
            ),
        ),
        id="landing_page",
        style=(
            "min-height:100vh; display:flex; align-items:center; justify-content:center;"
            " background:#f5f5f7; padding:2rem;"
        ),
    )


def _loading_overlay(fetched, total):
    pct       = int((fetched / total) * 100) if total > 0 else None
    bar_width = f"{pct}%" if pct is not None else "100%"
    animated  = "progress-bar-animated progress-bar-striped" if pct is None else ""
    return ui.div(
        landing_page_ui(),
        ui.div(
            ui.div(
                ui.div(
                    ui.h5("Fetching from ClinicalTrials.gov…",
                          style="margin-bottom:.5rem; color:#1a1a2e;"),
                    ui.p(
                        f"Retrieved {fetched:,} of {total:,} studies" if total > 0
                        else "Connecting…",
                        style="color:#888; font-size:.85rem; margin-bottom:1rem;",
                    ),
                    ui.div(
                        ui.div(
                            class_=f"progress-bar {animated}", role="progressbar",
                            style=(
                                f"width:{bar_width}; background:#1a1a2e;"
                                " transition:width .4s ease;"
                            ),
                            **{"aria-valuenow": str(pct or 0),
                               "aria-valuemin": "0", "aria-valuemax": "100"},
                        ),
                        class_="progress",
                        style="height:6px; border-radius:3px; background:#e0e0e0;",
                    ),
                    style=(
                        "background:#fff; border-radius:12px; padding:2.5rem 3rem;"
                        " box-shadow:0 8px 40px rgba(0,0,0,.15);"
                        " text-align:center; min-width:360px;"
                    ),
                ),
                style="display:flex; align-items:center; justify-content:center; width:100%; height:100%;",
            ),
            style=(
                "position:fixed; inset:0; background:rgba(245,245,247,.85);"
                " z-index:9999; backdrop-filter:blur(3px);"
            ),
        ),
    )


# ── Server logic ──────────────────────────────────────────────────────────────

def landing_server(input, output, session,
                   show_main, is_loading, load_progress,
                   api_data, upload_data, upload_data_raw, api_error,
                   filter_snapshot, log_entries,
                   main_layout, run_fetch_fn, read_uploaded_csv_fn,
                   process_fn):

    # ── Safe helpers ──────────────────────────────────────────────────────────

    def _query_kwargs_from_land():
        return dict(
            query_cond=input.query_cond_land(),
            query_intr=input.query_intr_land(),
            query_other_id=(input.query_other_id_land()
                            if input.include_other_id_land() else ""),
            query_term=input.query_term_land(),
            query_locn=input.query_locn_land(),
            query_titles=input.query_titles() or "",
            query_spons=input.query_spons() or "",
            query_id=input.query_id() or "",
            query_outc=input.query_outc() or "",
            filter_phase=list(input.filter_phase()) if input.filter_phase() else [],
            filter_status=(
                input.filter_status().split("|")
                if input.filter_status() else []
            ),
            filter_study_type=list(input.filter_study_type()) if input.filter_study_type() else [],
            filter_funder=list(input.filter_funder()) if input.filter_funder() else [],
            filter_sex=input.filter_sex(),
            filter_healthy=input.filter_healthy(),
            filter_results=input.filter_results(),
            filter_age_min=input.filter_age_min(),
            filter_age_max=input.filter_age_max(),
            filter_enroll_min=input.filter_enroll_min(),
            filter_enroll_max=input.filter_enroll_max(),
            filter_start_from=_valid_date(input.filter_start_from()),
            filter_start_to=_valid_date(input.filter_start_to()),
            filter_completion_from=_valid_date(input.filter_completion_from()),
            filter_completion_to=_valid_date(input.filter_completion_to()),
            sort_order=input.sort_order(),
            max_results=int(input.max_results() or 500),
        )

    # ── View switcher ─────────────────────────────────────────────────────────

    @output
    @render.ui
    def active_view():
        if show_main.get():
            return main_layout
        if is_loading.get():
            fetched, total = load_progress.get()
            return _loading_overlay(fetched, total)
        return landing_page_ui()

    # ── Run Query ─────────────────────────────────────────────────────────────

    @reactive.effect
    @reactive.event(input.btn_run)
    async def _on_run():
        filter_snapshot.set({
            "filter_phase":           list(input.filter_phase()) if input.filter_phase() else [],
            "filter_status":          input.filter_status(),
            "filter_study_type":      list(input.filter_study_type()) if input.filter_study_type() else [],
            "filter_funder":          list(input.filter_funder()) if input.filter_funder() else [],
            "filter_sex":             input.filter_sex(),
            "filter_healthy":         input.filter_healthy(),
            "filter_results":         input.filter_results(),
            "filter_age_min":         input.filter_age_min(),
            "filter_age_max":         input.filter_age_max(),
            "filter_enroll_min":      input.filter_enroll_min(),
            "filter_enroll_max":      input.filter_enroll_max(),
            "filter_start_from":      _valid_date(input.filter_start_from()),
            "filter_start_to":        _valid_date(input.filter_start_to()),
            "filter_completion_from": _valid_date(input.filter_completion_from()),
            "filter_completion_to":   _valid_date(input.filter_completion_to()),
            "sort_order":             input.sort_order(),
            "max_results":            input.max_results(),
        })

        is_loading.set(True)
        load_progress.set((0, 0))
        success = await run_fetch_fn(_query_kwargs_from_land())
        await asyncio.sleep(0)
        if success:
            show_main.set(True)
            snap = filter_snapshot.get()
            if snap.get("filter_phase"):
                ui.update_checkbox_group("filter_phase",      selected=snap["filter_phase"])
            if snap.get("filter_status") is not None:
                ui.update_radio_buttons("filter_status",      selected=snap["filter_status"])
            if snap.get("filter_study_type"):
                ui.update_checkbox_group("filter_study_type", selected=snap["filter_study_type"])
            if snap.get("filter_funder"):
                ui.update_checkbox_group("filter_funder",     selected=snap["filter_funder"])
            if snap.get("filter_sex"):
                ui.update_select("filter_sex",                selected=snap["filter_sex"])
            if snap.get("filter_results"):
                ui.update_radio_buttons("filter_results",     selected=snap["filter_results"])
            if snap.get("filter_age_min") is not None:
                ui.update_numeric("filter_age_min",           value=snap["filter_age_min"])
            if snap.get("filter_age_max") is not None:
                ui.update_numeric("filter_age_max",           value=snap["filter_age_max"])
            if snap.get("filter_enroll_min") is not None:
                ui.update_numeric("filter_enroll_min",        value=snap["filter_enroll_min"])
            if snap.get("filter_enroll_max") is not None:
                ui.update_numeric("filter_enroll_max",        value=snap["filter_enroll_max"])
            if snap.get("filter_start_from"):
                ui.update_text("filter_start_from",           value=snap["filter_start_from"])
            if snap.get("filter_start_to"):
                ui.update_text("filter_start_to",             value=snap["filter_start_to"])
            if snap.get("filter_completion_from"):
                ui.update_text("filter_completion_from",      value=snap["filter_completion_from"])
            if snap.get("filter_completion_to"):
                ui.update_text("filter_completion_to",        value=snap["filter_completion_to"])
            if snap.get("sort_order"):
                ui.update_select("sort_order",                selected=snap["sort_order"])
            if snap.get("max_results") is not None:
                ui.update_numeric("max_results",              value=snap["max_results"])
            ui.update_text("query_cond",     value=input.query_cond_land())
            ui.update_text("query_intr",     value=input.query_intr_land())
            ui.update_text("query_other_id", value=input.query_other_id_land()
                           if input.include_other_id_land() else "")
            ui.update_text("query_term",     value=input.query_term_land())
            ui.update_text("query_locn",   value=input.query_locn_land())
            ui.update_text("query_spons",  value=input.query_spons()  or "")
            ui.update_text("query_titles", value=input.query_titles() or "")
            ui.update_text("query_id",     value=input.query_id()     or "")
            ui.update_text("query_outc",   value=input.query_outc()   or "")

    # ── Back button ───────────────────────────────────────────────────────────

    @reactive.effect
    @reactive.event(input.btn_back)
    def _on_back():
        ui.update_text("query_cond_land", value="")
        ui.update_text("query_intr_land", value="")
        ui.update_text("query_term_land", value="")
        ui.update_text("query_locn_land", value="")
        log_entries.set(log_entries.get() + [
            (datetime.now().strftime("%H:%M:%S"), "info", "Returned to search page.")
        ])
        show_main.set(False)

    # ── Upload feedback ───────────────────────────────────────────────────────

    _upload_msg = reactive.Value("")

    @output
    @render.text
    def upload_status():
        return _upload_msg.get()

    @reactive.effect
    @reactive.event(input.upload_file)
    def _on_upload():
        f = input.upload_file()
        if f is None:
            return
        name = f[0]["name"]
        path = f[0]["datapath"]
        try:
            df = read_uploaded_csv_fn(path)
            df = process_fn(df)
            api_data.set(None)
            upload_data.set(df)
            upload_data_raw.set(df)
            log_entries.set(log_entries.get() + [(
                datetime.now().strftime("%H:%M:%S"), "ok",
                f"Uploaded {name}: {len(df)} rows x {len(df.columns)} columns"
            )])
            _upload_msg.set(f"✓  {name}  ({len(df):,} rows)")
            show_main.set(True)
        except Exception as e:
            log_entries.set(log_entries.get() + [(
                datetime.now().strftime("%H:%M:%S"), "error",
                f"Error reading {name}: {e}"
            )])
            _upload_msg.set(f"⚠  Could not read {name}")

    # ── Error display ─────────────────────────────────────────────────────────

    @output
    @render.text
    def api_error_msg():
        err = api_error.get()
        return f"⚠ {err}" if err else ""