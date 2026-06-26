"""
modules/landing.py
──────────────────
Landing page — and all landing-specific server logic.

Owns:
  UI:     landing_page layout, widget factory functions
  Server: landing_view switcher, loading overlay, _on_run, _on_back,
          upload_status, api_error_msg, safe input helpers, _query_kwargs,
          filter snapshot/restore
"""

import asyncio

from shiny import reactive, render, ui

from core.utils import build_filter_kwargs


# ── Widget factories ──────────────────────────────────────────────────────────

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
        ui.p("Age", class_="fw-semibold fs-6 mb-1"),
        ui.layout_columns(
            ui.input_numeric("filter_age_min", "Minimum age (years)", value=None, min=0, max=120),
            ui.input_numeric("filter_age_max", "Maximum age (years)", value=None, min=0, max=120),
            col_widths=[6, 6],
        ),
        ui.hr(class_="my-2"),
        ui.input_select(
            "filter_sex", "Sex",
            choices={"All": "All", "FEMALE": "Female", "MALE": "Male"},
            selected="All",
        ),
        ui.input_checkbox("filter_healthy", "Accepts healthy volunteers", value=False),
        ui.hr(class_="my-2"),
        ui.input_checkbox_group(
            "filter_phase", "Phase",
            choices={
                "EARLY_PHASE1": "Early Phase 1", "PHASE1": "Phase 1",
                "PHASE2": "Phase 2",             "PHASE3": "Phase 3",
                "PHASE4": "Phase 4",             "NA":     "Not applicable",
            },
            selected=[],
        ),
        ui.hr(class_="my-2"),
        ui.input_checkbox_group(
            "filter_study_type", "Study Type",
            choices={
                "INTERVENTIONAL": "Interventional", "OBSERVATIONAL": "Observational",
                "EXPANDED_ACCESS": "Expanded access",
            },
            selected=[],
        ),
        ui.hr(class_="my-2"),
        ui.input_checkbox_group(
            "filter_funder", "Funder Type",
            choices={"NIH": "NIH", "FED": "Other federal",
                     "INDUSTRY": "Industry", "OTHER": "Other"},
            selected=[],
        ),
        ui.hr(class_="my-2"),
        ui.input_radio_buttons(
            "filter_results", "Study Results",
            choices=["Any", "With results", "Without results"],
            selected="Any", inline=True,
        ),
        ui.hr(class_="my-2"),
        ui.p("Start date", class_="fw-semibold fs-6 mb-1"),
        ui.layout_columns(
            ui.input_text("filter_start_from", "From", placeholder="YYYY-MM-DD"),
            ui.input_text("filter_start_to",   "To",   placeholder="YYYY-MM-DD"),
            col_widths=[6, 6],
        ),
        ui.p("Primary completion date",
             class_="fw-semibold mt-2 mb-1 fs-6 mb-1"),
        ui.layout_columns(
            ui.input_text("filter_completion_from", "From", placeholder="YYYY-MM-DD"),
            ui.input_text("filter_completion_to",   "To",   placeholder="YYYY-MM-DD"),
            col_widths=[6, 6],
        ),
        ui.hr(class_="my-2"),
        ui.p("Enrollment size", class_="fw-semibold fs-6 mb-1"),
        ui.layout_columns(
            ui.input_numeric("filter_enroll_min", "Min", value=None, min=0),
            ui.input_numeric("filter_enroll_max", "Max", value=None, min=0),
            col_widths=[6, 6],
        ),
        ui.hr(class_="my-2"),
        ui.p("Additional search fields", class_="fw-semibold fs-6 mb-1"),
        ui.input_text("query_spons",  "Sponsor/collaborator", placeholder="e.g. Eli Lilly and Company"),
        ui.input_text("query_titles", "Title/acronym",        placeholder="e.g. SURMOUNT"),
        ui.input_text("query_id",     "NCT/study ID",         placeholder="e.g. NCT04184622"),
        ui.input_text("query_outc",   "Outcome measure",      placeholder="e.g. HbA1c"),
        ui.hr(class_="my-2"),
        ui.p("Sorting", class_="fw-semibold fs-6 mb-1"),
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
            ui.h2("Dashboard Testing", class_="fw-bold mb-1"),
            ui.p("Testing version of a dashboard that can connect ClinicalTrail.gov and" \
            " PubMed to help summarize trial information, provide details, and render timelines.", 
                 class_="fs-6 fw-normal text-start text-muted mb-2"),

            ui.h6("Option 1. Upload Data to Proces", class_="fw-bold mt-1 mb-1"),
            ui.div(
                ui.input_file("upload_file", None, accept=".csv",
                              button_label="Choose CSV", multiple=False),
                ui.div(ui.output_text("upload_status"),
                       class_="text-muted small mt-1"),
                class_="text-center pt-1 mb-1",
            ),

            ui.hr(class_="my-1"),
            ui.h6("Option 2. Query ClinicalTrial.gov", class_="fw-bold mt-3 mb-2"),
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
                            class_="d-flex align-items-center",
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
                    class_="d-flex flex-column gap-0",
                ),
                class_="border border-secondary rounded-1",
                style="padding:1.25rem 1.25rem 0 1.25rem;",
            ),

            ui.tags.style("""
              /* Override rules */
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
            ui.div(
                ui.div(
                    ui.div(
                        ui.div(
                            ui.tags.button(
                                ui.tags.span("More Filters", class_="fs-6"),
                                class_="accordion-button", type="button",
                                data_bs_toggle="collapse", data_bs_target="#CollapseMorefilters",
                                aria_expanded="true", aria_controls="collapseMorefilters",
                            ),
                            class_="fw-normal fs-5",
                        ),
                        class_="accordion-header",
                    ),
                    ui.hr(class_="my-0 py-0"),
                    ui.div(
                        ui.div(
                            ui.layout_columns(
                                ui.div(*more_filters_widgets()[:28]),
                                ui.div(*more_filters_widgets()[28:]),
                                col_widths=[6, 6],
                            ),
                        ),
                        class_="accordion-body accordion-collapse collapse",
                        id="CollapseMorefilters",
                    ),
                    class_="accordion-item",
                ),
                class_="accordion border border-secondary rounded-1 mt-3",
            ),

            ui.hr(class_="my-4"),
            ui.div(
                ui.output_text("api_error_msg"),
                ui.input_action_button(
                    "btn_run", "Run Query",
                    class_="btn btn-dark",
                ),
                class_="d-grid col-4 mx-auto text-center",
            ),

            class_="card p-5 w-100",
            style="max-width:860px; border-radius:12px; box-shadow:0 4px 32px rgba(0,0,0,.08);",
        ),
        id="landing_page",
        class_="min-vh-100 d-flex align-items-center justify-content-center p-4",
        style="background:#f5f5f7;",
    )


def _loading_overlay(fetched, total):
    pct       = int((fetched / total) * 100) if total > 0 else None
    bar_width = f"{pct}%" if pct is not None else "100%"
    return ui.div(
        landing_page_ui(),
        ui.div(
            ui.div(
                ui.div(
                    ui.h5("Fetching from ClinicalTrials.gov…",
                          class_="mb-2 text-muted"),
                    ui.p(
                        f"Retrieved {fetched:,} of {total:,} studies" if total > 0
                        else "Connecting…",
                        class_="fs-6 text-muted mb-3",
                    ),
                    ui.div(
                        ui.div(
                            f"{pct}%",
                            class_="progress-bar",
                            role="progressbar",
                            style=f"width:{bar_width};",
                            **{
                                "aria-valuenow": str(pct or 0),
                                "aria-valuemin": "0",
                                "aria-valuemax": "100",
                            },
                        ),
                        class_="progress",
                    ),
                    class_="bg-white rounded-3 p-5 shadow text-center",
                ),
                class_="d-flex align-items-center justify-content-center w-100 h-100",
            ),
            class_="position-fixed",
            style=(
                "inset:0; background:rgba(245,245,247,.85);"
                " z-index:999; backdrop-filter:blur(3px);"
            ),
        ),
    )


# ── Server logic ──────────────────────────────────────────────────────────────

def landing_server(input, output, session,
                   show_main, is_loading, load_progress,
                   api_data, upload_data, api_error,
                   log_fn, run_fetch_fn, read_uploaded_csv_fn,
                   process_fn, fetch_pubs_fn):

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
            **build_filter_kwargs(input),
        )

    # ── View switcher ─────────────────────────────────────────────────────────

    @output
    @render.ui
    def landing_view():
        if show_main.get():
            return None
        if is_loading.get():
            fetched, total = load_progress.get()
            return _loading_overlay(fetched, total)
        return landing_page_ui()

    # ── Run Query ─────────────────────────────────────────────────────────────

    @reactive.effect
    @reactive.event(input.btn_run)
    async def _on_run():
        success = await run_fetch_fn(_query_kwargs_from_land())
        await asyncio.sleep(0)
        if success:
            show_main.set(True)

    # ── Back button ───────────────────────────────────────────────────────────

    @reactive.effect
    @reactive.event(input.btn_back)
    def _on_back():
        ui.update_text("query_cond_land", value="")
        ui.update_text("query_intr_land", value="")
        ui.update_text("query_term_land", value="")
        ui.update_text("query_locn_land", value="")
        ui.update_checkbox_group("viz_compound",   selected=[])
        ui.update_checkbox_group("viz_indication", selected=[])
        ui.update_checkbox_group("viz_phase",      selected=[])
        ui.update_checkbox_group("ti_compound",    selected=[])
        ui.update_checkbox_group("ti_indication",  selected=[])
        ui.update_checkbox_group("ti_phase",       selected=[])
        log_fn("Returned to search page.")
        api_data.set(None)
        upload_data.set(None)
        show_main.set(False)

    # ── Upload feedback ───────────────────────────────────────────────────────

    _upload_msg = reactive.Value("")

    @output
    @render.text
    def upload_status():
        return _upload_msg.get()

    @reactive.effect
    @reactive.event(input.upload_file)
    async def _on_upload():
        f = input.upload_file()
        if f is None:
            return
        name = f[0]["name"]
        path = f[0]["datapath"]
        is_loading.set(True)
        load_progress.set((0, 0))
        try:
            df = read_uploaded_csv_fn(path)
            df = process_fn(df)
            with ui.Progress(min=0, max=3) as p:
                p.set(0, message="Processing upload", detail="Processing data...")
                await asyncio.sleep(0)
                p.set(1, message="Processing upload", detail="Fetching publications from PubMed...")
                df = await asyncio.to_thread(fetch_pubs_fn, df)
                p.set(3, message="Processing upload", detail="Done")
                await asyncio.sleep(0)
            api_data.set(None)
            upload_data.set(df)
            log_fn(f"Uploaded {name}: {len(df)} rows x {len(df.columns)} columns", level="ok")
            _upload_msg.set(f"Just uploaded:  {name}  ({len(df):,} rows)")
            show_main.set(True)
        except Exception as e:
            log_fn(f"Error reading {name}: {e}", level="error")
            _upload_msg.set(f"Error:  Could not read {name}")
        finally:
            is_loading.set(False)
            load_progress.set((0, 0))

    # ── Error display ─────────────────────────────────────────────────────────

    @output
    @render.text
    def api_error_msg():
        err = api_error.get()
        return f"⚠ {err}" if err else ""