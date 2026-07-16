"""
modules/query.py
────────────────
Search/upload form UI and server logic.

Owns:
  UI:     query_page_ui()  — full-screen stacked-row page: upload row + two-column query section
                             (used in source-selection view)
          edit_query_ui()  — same two-column query section without title/upload row
                             (used in the edit-query slide panel)
  Server: query_server()
"""

import asyncio

from shiny import reactive, render, ui

from core.utils import build_filter_kwargs


# ── Query field columns ───────────────────────────────────────────────────────

def _left_col_fields():
    """
    Owns:
      - Primary fields (condition/intervention | other terms/location)
      - alt compound checkbox + conditional
      - Study Status radio
      - Age min/max
      - Sex + Healthy volunteers
      - Start date from/to
      - Enrollment size min/max
    """
    return ui.div(
        # Primary query fields
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
                              placeholder="City, state, zip code, country, etc."),
            ),
            col_widths=[6, 6],
        ),
        # Alt compound
        ui.layout_columns(
            ui.div(
                ui.input_checkbox("include_other_id_land",
                                  "Include alternative compound name", value=False),
                class_="d-flex align-items-center",
            ),
            ui.panel_conditional(
                "input.include_other_id_land",
                ui.input_text("query_other_id_land", None,
                              placeholder="e.g. LY3819469"),
            ),
            col_widths=[6, 6],
        ),
        # Study status
        ui.input_radio_buttons(
            "filter_status", "Study Status",
            choices={
                "": "All studies",
                "RECRUITING|NOT_YET_RECRUITING|ENROLLING_BY_INVITATION":
                    "Recruiting and not yet recruiting studies",
            },
            selected="",
            inline=True,
        ),
        ui.hr(class_="my-2"),
        ui.p("Eligibility Criteria", class_="fw-semibold fs-5 mt-2 mb-1"),
        # Age
        ui.p("Age", class_="fw-semibold fs-6 mb-1"),
        ui.layout_columns(
            ui.input_numeric("filter_age_min", "Minimum age (years)", value=None, min=0, max=120),
            ui.input_numeric("filter_age_max", "Maximum age (years)", value=None, min=0, max=120),
            col_widths=[6, 6],
        ),
        # Sex + Healthy volunteers
        ui.input_select(
            "filter_sex", "Sex",
            choices={"All": "All", "FEMALE": "Female", "MALE": "Male"},
            selected="All",
        ),
        ui.div(
            ui.input_checkbox("filter_healthy", "Accepts healthy volunteers", value=False),
            class_="mt-1",
        ),
        ui.hr(class_="my-2"),
        ui.p("Date Range", class_="fw-semibold fs-5 mt-2 mb-1"),
        # Start date
        ui.p("Start date", class_="fw-semibold fs-6 mb-1"),
        ui.layout_columns(
            ui.input_text("filter_start_from", "From", placeholder="YYYY-MM-DD"),
            ui.input_text("filter_start_to",   "To",   placeholder="YYYY-MM-DD"),
            col_widths=[6, 6],
        ),
        # Primary completion date
        ui.p("Primary completion date", class_="fw-semibold fs-6 mb-1"),
        ui.layout_columns(
            ui.input_text("filter_completion_from", "From", placeholder="YYYY-MM-DD"),
            ui.input_text("filter_completion_to",   "To",   placeholder="YYYY-MM-DD"),
            col_widths=[6, 6],
        ),
        class_="pe-4",
    )


def _right_col_fields():
    """
    Owns:
      - Study Results radio
      - Primary completion date from/to
      - Phase checkbox group
      - Study Type checkbox group
      - Funder Type checkbox group
      - Sponsor/Title + NCT ID/Outcome
      - Sort by + Max results inline
    """
    return ui.div(
        # Phase
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
        # Study type
        ui.input_checkbox_group(
            "filter_study_type", "Study Type",
            choices={
                "INTERVENTIONAL": "Interventional", "OBSERVATIONAL": "Observational",
                "EXPANDED_ACCESS": "Expanded access",
            },
            selected=[],
        ),
        ui.hr(class_="my-2"),
        # Study results
        ui.input_radio_buttons(
            "filter_results", "Study Results",
            choices=["Any", "With results", "Without results"],
            selected="Any", inline=True,
        ),
        ui.hr(class_="my-2"),
        # Funder type
        ui.input_checkbox_group(
            "filter_funder", "Funder Type",
            choices={"NIH": "NIH", "FED": "Other federal",
                     "INDUSTRY": "Industry", "OTHER": "Other"},
            selected=[],
        ),
        ui.hr(class_="my-2"),
        ui.p("More Ways to Search", class_="fw-semibold fs-5 mt-2 mb-1"),
        # Sponsor + Title; NCT ID + Outcome
        ui.layout_columns(
            ui.input_text("query_spons",  "Sponsor/collaborator", placeholder="e.g. Eli Lilly and Company"),
            ui.input_text("query_titles", "Title/acronym",        placeholder="e.g. SURMOUNT"),
            col_widths=[6, 6],
        ),
        ui.layout_columns(
            ui.input_text("query_id",   "NCT/study ID",    placeholder="e.g. NCT04184622"),
            ui.input_text("query_outc", "Outcome measure", placeholder="e.g. HbA1c"),
            col_widths=[6, 6],
        ),
        ui.hr(class_="my-2"),
        # Sort by + Max results
        ui.layout_columns(
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
            col_widths=[6, 6],
        ),
        class_="ps-4 border-start",
    )


def _query_section_header(title="Option 2. Query ClinicalTrials.gov"):
    """Heading + Run Query button on the same row, button right-aligned."""
    return ui.div(
        ui.h6(title, class_="fw-bold mb-0"),
        ui.div(
            ui.output_text("api_error_msg"),
            ui.input_action_button("btn_run", "Run Query", class_="btn btn-dark"),
            class_="d-flex align-items-center gap-2",
        ),
        class_="d-flex justify-content-between align-items-center mb-3",
    )


# ── Full-screen query page ────────────────────────────────────────────────────

def query_page_ui():
    """
    Full-screen stacked-row page.
    Row 1: title + description
    Row 2: upload (two-column: label left, file widget right)
    Row 3: two-column query fields with Run Query button inline with heading
    Used in source-selection view.
    """
    return ui.div(
        # Title
        ui.h2("Dashboard Testing", class_="fw-bold mb-1"),
        ui.p(
            "Testing version of a dashboard that can connect ClinicalTrials.gov and"
            " PubMed to help summarize trial information, provide details, and render timelines.",
            class_="fs-6 fw-normal text-muted mb-0",
        ),
        ui.hr(class_="my-4"),
        # Upload row
        ui.div(
            ui.div(
                ui.h6("Option 1. Upload Data to Process", class_="fw-bold mb-0"),
                class_="col-6 d-flex align-items-center",
            ),
            ui.div(
                ui.input_file("upload_file", None, accept=".csv",
                              button_label="Choose CSV", multiple=False),
                ui.div(ui.output_text("upload_status"), class_="text-muted small"),
                class_="col-6 d-flex align-items-end flex-column",
            ),
            class_="row align-items-center g-0",
        ),
        ui.hr(class_="my-4"),
        _query_section_header(),
        ui.div(
            ui.div(_left_col_fields(),  class_="col-6"),
            ui.div(_right_col_fields(), class_="col-6"),
            class_="row g-0",
        ),
        class_="container-fluid min-vh-100 py-5 px-5",
        style="background:#f5f5f7;",
    )


# ── Edit-query slide panel ────────────────────────────────────────────────────

def edit_query_ui():
    """
    Query-only form (no title, description, or upload row).
    Used in the edit-query slide panel.
    """
    return ui.div(
        _query_section_header(title="Edit Last Query"),
        ui.div(
            ui.div(_left_col_fields(),  class_="col-6"),
            ui.div(_right_col_fields(), class_="col-6"),
            class_="row g-0",
        ),
        class_="container-fluid py-4 px-5",
    )


# ── Server logic ──────────────────────────────────────────────────────────────

def query_server(input, output, session,
                 app_state,
                 api_data, upload_data, query_params, upload_info, data_source,
                 edit_panel_open, api_error, log_fn,
                 run_fetch_fn, read_uploaded_csv_fn, process_fn, fetch_pubs_fn,
                 loaded_session_index=None):

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

    # ── Run Query / Re-run Query ──────────────────────────────────────────────

    @reactive.effect
    @reactive.event(input.btn_run)
    async def _on_run():
        kwargs = _query_kwargs_from_land()
        success = await run_fetch_fn(kwargs)
        if success:
            query_params.set(kwargs)
            data_source.set("fetch")
            app_state.set("loaded")
            edit_panel_open.set(False)
            if loaded_session_index is not None:
                loaded_session_index.set(None)

    # ── Upload ────────────────────────────────────────────────────────────────

    _upload_msg = reactive.Value("")

    @output
    @render.text
    def upload_status():
        return _upload_msg.get()

    async def _do_upload(name, path):
        try:
            df = read_uploaded_csv_fn(path)
            df = process_fn(
                df,
                query_intr=input.query_intr_land() or "",
                query_other_id=(input.query_other_id_land() if input.include_other_id_land() else ""),
            )
            with ui.Progress(min=0, max=3) as p:
                p.set(0, message="Processing upload", detail="Processing data...")
                await asyncio.sleep(0)
                p.set(1, message="Processing upload", detail="Fetching publications from PubMed...")
                df = await asyncio.to_thread(fetch_pubs_fn, df)
                p.set(3, message="Processing upload", detail="Done")
                await asyncio.sleep(0)
            api_data.set(None)
            upload_data.set(df)
            upload_info.set({"filename": name, "count": len(df)})
            data_source.set("upload")
            app_state.set("loaded")
            if loaded_session_index is not None:
                loaded_session_index.set(None)
            log_fn(f"Uploaded {name}: {len(df)} rows x {len(df.columns)} columns", level="ok")
            _upload_msg.set(f"Just uploaded:  {name}  ({len(df):,} rows)")
        except Exception as e:
            log_fn(f"Error reading {name}: {e}", level="error")
            _upload_msg.set(f"Error:  Could not read {name}")

    @reactive.effect
    @reactive.event(input.upload_file)
    async def _on_upload():
        f = input.upload_file()
        if f is None:
            return
        await _do_upload(f[0]["name"], f[0]["datapath"])

    @reactive.effect
    @reactive.event(input.upload_file_new)
    async def _on_upload_new():
        f = input.upload_file_new()
        if f is None:
            return
        await _do_upload(f[0]["name"], f[0]["datapath"])

    # ── Error display ─────────────────────────────────────────────────────────

    @output
    @render.text
    def api_error_msg():
        err = api_error.get()
        return f"⚠ {err}" if err else ""

    # ── Pre-fill form when edit panel opens ───────────────────────────────────

    @reactive.effect
    def _prefill_on_edit_open():
        if not edit_panel_open.get():
            return
        if data_source.get() != "fetch":
            return
        params = query_params.get()
        ui.update_text("query_cond_land",     value=params.get("query_cond",  ""))
        ui.update_text("query_intr_land",     value=params.get("query_intr",  ""))
        ui.update_text("query_term_land",     value=params.get("query_term",  ""))
        ui.update_text("query_locn_land",     value=params.get("query_locn",  ""))
        ui.update_text("query_spons",         value=params.get("query_spons", ""))
        ui.update_text("query_titles",        value=params.get("query_titles",""))
        ui.update_text("query_id",            value=params.get("query_id",    ""))
        ui.update_text("query_outc",          value=params.get("query_outc",  ""))
        other_id = params.get("query_other_id", "")
        if other_id:
            ui.update_checkbox("include_other_id_land", value=True)
            ui.update_text("query_other_id_land", value=other_id)
        ui.update_action_button("btn_run", label="Re-run Query")

    @reactive.effect
    def _reset_run_label():
        if not edit_panel_open.get():
            ui.update_action_button("btn_run", label="Run Query")
