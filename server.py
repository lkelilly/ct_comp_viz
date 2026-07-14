"""
server.py
─────────
Shared state, core fetch logic, renderUI functions, and module wiring.

Owns:
  - All shared reactive values
  - _log helper and _summarize_kwargs
  - _run_fetch (async, used by landing._on_run)
  - Navbar, context bar, slide panel, and main content renderUI
  - Mode selector and context bar button handlers
  - console_log + btn_clear_log
  - Module wiring
"""

import asyncio
import time
from datetime import datetime

from shiny import reactive, render, ui

from core.ct_api     import fetch_studies, CTGovAPIError, CTGovNetworkError
from core.utils      import (
    studies_to_dataframe, read_uploaded_csv, process_raw_ctgov,
)
from core.pubmed_api import add_publications

from modules.query          import query_server, query_page_ui, edit_query_ui
from modules.trial_info     import trial_info_server, trial_info_ui
from modules.trial_summary  import trial_summary_server, trial_summary_ui
from modules.viz            import viz_server, viz_ui
from modules.archive        import archive_server, archive_ui


# ── Inner tab set ─────────────────────────────────────────────────────────────

def _tab_console():
    return ui.nav_panel(
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


def _inner_tabs(right_controls=None):
    nav_items = [viz_ui(), trial_info_ui(), trial_summary_ui(), _tab_console()]
    if right_controls is not None:
        nav_items.append(ui.nav_spacer())
        nav_items.append(ui.nav_control(right_controls))
    return ui.navset_underline(*nav_items, id="inner_tabs",
                               header=ui.output_ui("slide_panel_ui"))


def server(input, output, session):

    # ── Shared reactive state ─────────────────────────────────────────────────

    current_mode    = reactive.Value("none")   # "none" | "fetch" | "archive"
    app_state       = reactive.Value("empty")  # "empty" | "source_selection" | "loaded"
    query_params    = reactive.Value({})
    upload_info     = reactive.Value(None)     # {"filename": str, "count": int}
    data_source     = reactive.Value(None)     # "fetch" | "upload"
    edit_panel_open = reactive.Value(False)
    session_archive = reactive.Value([])

    is_loading      = reactive.Value(False)
    load_progress   = reactive.Value((0, 0))

    api_data        = reactive.Value(None)
    upload_data     = reactive.Value(None)
    api_error       = reactive.Value(None)
    log_entries     = reactive.Value([])

    # Set by archive_server when diffs are found or applied; read by context_bar_ui
    # Shape: {"diffs": dict|None, "applied": int|None}
    archive_update_status = reactive.Value({})

    @reactive.calc
    def active_data():
        if api_data.get() is not None:
            return api_data.get()
        if upload_data.get() is not None:
            return upload_data.get()
        return None

    # ── Logging ───────────────────────────────────────────────────────────────

    def _log(msg, level="info"):
        ts = datetime.now().strftime("%H:%M:%S")
        entries = log_entries.get().copy()
        entries.append((ts, level, msg))
        log_entries.set(entries)

    def _summarize_kwargs(kwargs):
        parts = []
        label_map = {
            "query_cond": "condition", "query_intr": "intervention",
            "query_term": "terms",     "query_spons": "sponsor",
            "query_titles": "title",   "query_locn": "location",
            "query_id": "id",          "query_outc": "outcome",
        }
        for key, label in label_map.items():
            v = kwargs.get(key)
            if v:
                parts.append(f'{label}="{v}"')
        phases   = [p for p in (kwargs.get("filter_phase")  or []) if p]
        statuses = [s for s in (kwargs.get("filter_status") or []) if s]
        if phases:
            parts.append(f"phase={','.join(phases)}")
        if statuses:
            parts.append(f"status={','.join(statuses)}")
        return "  ".join(parts) if parts else "(no query params)"

    # ── Core async fetch ──────────────────────────────────────────────────────

    async def _run_fetch(kwargs):
        api_error.set(None)
        is_loading.set(True)
        load_progress.set((0, 0))

        _log(f"Query: {_summarize_kwargs(kwargs)}")
        _log(f"Fetching from ClinicalTrials.gov  (max {kwargs.get('max_results', 500)} results)…")

        t0 = time.time()

        async def _on_progress(fetched, total):
            load_progress.set((fetched, total))
            await asyncio.sleep(0)

        try:
            studies, total = await fetch_studies(**kwargs, progress_callback=_on_progress)
            elapsed = round(time.time() - t0, 1)
            fetched = len(studies)
            capped  = fetched < total
            _log(
                f"Retrieved {fetched:,} studies"
                + (f" (of {total:,} total — capped by max_results)" if capped
                   else f" of {total:,} total")
                + f"  [{elapsed}s]",
                level="ok",
            )
            df = studies_to_dataframe(studies)
            _log(f"Processed into DataFrame: {len(df)} rows x {len(df.columns)} columns")

            with ui.Progress(min=0, max=5) as p:
                p.set(0, message="Processing data", detail="Standardizing dates...")
                await asyncio.sleep(0)
                p.set(1, message="Processing data", detail="Mapping indications...")
                await asyncio.sleep(0)
                p.set(2, message="Processing data", detail="Adding compound information...")
                df = await asyncio.to_thread(
                    process_raw_ctgov, df,
                    query_intr=kwargs.get("query_intr") or "",
                    query_other_id=kwargs.get("query_other_id") or "",
                )
                p.set(3, message="Processing data", detail="Fetching publications from PubMed...")
                await asyncio.sleep(0)
                df = await asyncio.to_thread(add_publications, df)
                p.set(5, message="Processing data", detail="Done")
                await asyncio.sleep(0)

            _log(f"Processed DataFrame: indication + compound columns added", level="ok")
            _log(f"Publication adding complete", level="ok")

            api_data.set(df)
            upload_data.set(None)
            return True
        except CTGovAPIError as e:
            _log(f"API error: {e}", level="error")
            api_error.set(str(e))
        except CTGovNetworkError as e:
            _log(f"Network error: {e}", level="error")
            api_error.set(str(e))
        except Exception as e:
            _log(f"Unexpected error: {e}", level="error")
            api_error.set(str(e))
        finally:
            is_loading.set(False)
            load_progress.set((0, 0))

        return False

    # ── Mode selector handlers ────────────────────────────────────────────────

    @reactive.effect
    @reactive.event(input.btn_mode_fetch)
    def _on_mode_fetch():
        current_mode.set("fetch")
        edit_panel_open.set(False)
        if data_source.get() in ("fetch", "upload") and (
            api_data.get() is not None or upload_data.get() is not None
        ):
            app_state.set("loaded")
        else:
            app_state.set("source_selection")

    @reactive.effect
    @reactive.event(input.btn_mode_archive)
    def _on_mode_archive():
        current_mode.set("archive")
        edit_panel_open.set(False)
        if data_source.get() is None and upload_data.get() is not None:
            app_state.set("loaded")
        else:
            app_state.set("source_selection")

    # ── Empty-state CTA handlers ──────────────────────────────────────────────

    @reactive.effect
    @reactive.event(input.btn_cta_fetch)
    def _on_cta_fetch():
        current_mode.set("fetch")
        app_state.set("source_selection")

    @reactive.effect
    @reactive.event(input.btn_cta_archive)
    def _on_cta_archive():
        current_mode.set("archive")
        app_state.set("source_selection")

    # ── Context bar button handlers ───────────────────────────────────────────

    @reactive.effect
    @reactive.event(input.btn_toggle_edit)
    def _on_toggle_edit():
        edit_panel_open.set(not edit_panel_open.get())

    @reactive.effect
    @reactive.event(input.btn_archive_select)
    def _on_archive_select():
        edit_panel_open.set(not edit_panel_open.get())

    @reactive.effect
    @reactive.event(input.btn_back_to_page)
    def _on_back_to_query():
        edit_panel_open.set(False)
        app_state.set("source_selection")

    @output
    @render.ui
    def check_updates_btn_ui():
        status  = archive_update_status.get()
        if status.get("checking"):
            return ui.div()
        if status.get("diffs"):
            return ui.input_action_button(
                "btn_save_to_session", "Save to Session",
                class_="btn btn-sm btn-success me-2 mt-1",
            )
        return ui.input_action_button(
            "btn_check_updates", "Check Updates",
            class_="btn btn-sm btn-success me-2 mt-1",
        )

    # ── Download ──────────────────────────────────────────────────────────────

    @render.download(filename=lambda: f"ct_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
    def btn_download():
        df = active_data()
        if df is None:
            return
        import io
        date_cols = [c for c in ("start_date", "primary_completion_date", "completion_date", "last_update_date")
                     if c in df.columns]
        out = df.copy()
        for col in date_cols:
            raw_col = col + "_raw"
            if raw_col in out.columns:
                out[col] = out[raw_col]
                out = out.drop(columns=[raw_col])
            else:
                out[col] = out[col].dt.strftime("%Y-%m-%d").fillna("")
        # Replace embedded newlines in all string columns so Excel doesn't split rows
        for col in out.select_dtypes(include="object").columns:
            out[col] = out[col].astype(str).str.replace(r"\r\n|\r|\n", " ", regex=True)
        # Use BytesIO + utf-8-sig so Excel auto-detects encoding (fixes â¥ â„¢ Â² etc.)
        buf = io.BytesIO()
        out.to_csv(buf, index=False, encoding="utf-8-sig")
        yield buf.getvalue()

    @render.download(filename=lambda: f"ct_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
    def btn_download_xlsx():
        df = active_data()
        if df is None:
            return
        import io
        date_cols = [c for c in ("start_date", "primary_completion_date", "completion_date", "last_update_date")
                     if c in df.columns]
        out = df.copy()
        for col in date_cols:
            raw_col = col + "_raw"
            if raw_col in out.columns:
                out[col] = out[raw_col]
                out = out.drop(columns=[raw_col])
            else:
                out[col] = out[col].dt.strftime("%Y-%m-%d").fillna("")
        # Excel handles multi-line cells natively — no newline stripping needed
        # Pre-truncate to Excel's hard 32,767 char-per-cell limit to suppress openpyxl warnings
        EXCEL_MAX = 32_767
        for col in out.select_dtypes(include="object").columns:
            out[col] = out[col].astype(str).str[:EXCEL_MAX]
        buf = io.BytesIO()
        out.to_excel(buf, index=False, engine="openpyxl")
        yield buf.getvalue()

    # ── Auto-select Visualization tab when data loads ─────────────────────────

    @reactive.effect
    def _auto_select_viz():
        if app_state.get() == "loaded":
            ui.update_navset("inner_tabs", selected="Visualization")

    @reactive.effect
    def _reset_check_state_on_load():
        if app_state.get() == "loaded":
            archive_update_status.set({})

    # ── Navbar renderUI ───────────────────────────────────────────────────────

    @output
    @render.ui
    def app_navbar():
        mode = current_mode.get()

        def _nav_link(input_id, label, this_mode):
            active_cls = " active" if mode == this_mode else ""
            return ui.tags.li(
                ui.tags.a(
                    label,
                    class_=f"nav-link fw-bold px-3 py-1{active_cls}",
                    href="#",
                    onclick=f"Shiny.setInputValue('{input_id}', Math.random()); return false;",
                ),
                class_="nav-item",
            )

        return ui.tags.nav(
            ui.div(
                ui.tags.span("DEMO", class_="navbar-brand mb-0 h1 text-white fw-bold"),
                ui.tags.ul(
                    _nav_link("btn_mode_fetch",   "Fetch / Upload", "fetch"),
                    ui.tags.li(
                        ui.tags.span("||", class_="nav-link mx-1 px-2 text-white-50 pe-none"),
                        class_="nav-item",
                    ),
                    _nav_link("btn_mode_archive", "Archive", "archive"),
                    class_="navbar-nav nav-pills justify-content-center",
                ),
                class_="container-fluid",
            ),
            class_="navbar navbar-dark bg-dark",
            data_bs_theme="dark",
        )

    # ── Context bar renderUI ──────────────────────────────────────────────────

    @output
    @render.ui
    def context_bar_ui():
        if app_state.get() != "loaded":
            return ui.div()

        mode   = current_mode.get()
        source = data_source.get()
        df     = active_data()
        count  = len(df) if df is not None else 0

        parts = []
        if source == "fetch":
            params = query_params.get()
            text_fields = [
                ("query_cond",     "Condition"),
                ("query_intr",     "Intervention"),
                ("query_term",     "Terms"),
                ("query_spons",    "Sponsor"),
                ("query_other_id", "ID"),
                ("query_locn",     "Location"),
                ("query_titles",   "Title"),
                ("query_id",       "NCT ID"),
                ("query_outc",     "Outcome"),
            ]
            for field, label in text_fields:
                val = params.get(field, "")
                if val:
                    parts.append(f"{label}: {val}")

            for field, label in [
                ("filter_phase",      "Phase"),
                ("filter_status",     "Status"),
                ("filter_study_type", "Type"),
                ("filter_funder",     "Funder"),
            ]:
                vals = params.get(field) or []
                if vals:
                    parts.append(f"{label}: {', '.join(vals)}")

            sex = params.get("filter_sex", "")
            if sex and sex.lower() not in ("", "all"):
                parts.append(f"Sex: {sex}")
            if params.get("filter_healthy"):
                parts.append("Healthy volunteers")
            results = params.get("filter_results", "Any")
            if results and results != "Any":
                parts.append(f"Results: {results}")

            age_min = params.get("filter_age_min")
            age_max = params.get("filter_age_max")
            if age_min or age_max:
                parts.append(f"Age: {age_min or ''}-{age_max or ''}")

            for from_f, to_f, label in [
                ("filter_start_from",      "filter_start_to",      "Start"),
                ("filter_completion_from", "filter_completion_to", "Completion"),
            ]:
                f, t = params.get(from_f), params.get(to_f)
                if f or t:
                    parts.append(f"{label}: {f or ''} - {t or ''}")
        elif source == "upload":
            info = upload_info.get()
            if info:
                parts.append(f"Dataset: {info['filename']}")
        elif mode == "archive":
            parts.append("Archive dataset")

        parts.append(f"{count:,} trials")
        callout_text = " • ".join(parts)

        label_map = {"fetch": "Fetched", "upload": "Uploaded", "archive": "Archive"}
        badge_label = label_map.get(source or mode, "")

        main_info = ui.div(
            ui.span(badge_label, class_="btn btn-sm btn-info me-2 align-middle pe-none"),
            ui.span(callout_text, class_="small"),
        )

        status = archive_update_status.get()
        upd_diffs   = status.get("diffs")
        upd_applied = status.get("applied")

        update_info = None
        if upd_applied is not None:
            update_info = ui.div(
                ui.span("Updates Applied",
                        class_="btn btn-sm btn-success me-2 align-middle pe-none"),
                ui.span(f"{upd_applied} trial(s) updated", class_="small"),
            )
        elif upd_diffs:
            n_trials = len(upd_diffs)
            n_fields = sum(len(v) for v in upd_diffs.values())
            update_info = ui.div(
                ui.span("Updates",
                        class_="btn btn-sm btn-warning me-2 align-middle pe-none"),
                ui.span(f"{n_trials} of {count} trial(s) have changes • {n_fields} field(s) total",
                        class_="small"),
            )

        row_children = [main_info] + ([update_info] if update_info is not None else [])

        return ui.div(
            ui.div(*row_children, class_="d-flex justify-content-between align-items-center"),
            class_="bd-callout bd-callout-info container-fluid m-1 py-2",
        )

    # ── Slide panel renderUI ──────────────────────────────────────────────────

    @output
    @render.ui
    def slide_panel_ui():
        if not edit_panel_open.get():
            return ui.div()
        mode = current_mode.get()
        if mode == "fetch" or data_source.get() == "fetch":
            return ui.div(
                edit_query_ui(),
            )
        if mode == "archive":
            return ui.div(
                archive_ui(),
            )
        return ui.div()

    # ── Main content renderUI ─────────────────────────────────────────────────

    @output
    @render.ui
    def main_content_ui():
        state = app_state.get()
        mode  = current_mode.get()

        if state == "empty":
            return ui.div(
                ui.div(
                    ui.h3("Get Started", class_="fw-bold mb-3"),
                    ui.p("Welcome! This dashboard supports three workflows:", class_="text-muted text-start mb-1"),
                    ui.tags.ol(
                        ui.tags.li(
                            ui.tags.strong("Fetch"), " — query ClinicalTrials.gov directly and process results for " \
                            "timeline visualization, publication links, and standardized trial information. You can also" \
                            "get the compound's CLUWE path if it's a Lilly compound;",
                            class_="mb-1",
                        ),
                        ui.tags.li(
                            ui.tags.strong("Upload"), " — bring your own CT.gov-alike data and run the same processing;",
                            class_="mb-1",
                        ),
                        ui.tags.li(
                            ui.tags.strong("Archive"), " — (Initial demo, developing) browse curated datasets and compare " \
                            "them against the latest data from CT.gov. Edit and save your own version per session.",
                            class_="mb-1",
                        ),
                        class_="text-muted text-start mb-1 ps-3",
                    ),
                    ui.p("Thanks for testing with the current version!", class_="text-muted mb-4"),
                    ui.div(
                        ui.input_action_button(
                            "btn_cta_fetch", "Fetch / Upload",
                            class_="btn btn-dark me-3",
                        ),
                        ui.input_action_button(
                            "btn_cta_archive", "Browse archive",
                            class_="btn btn-outline-dark",
                        ),
                    ),
                    class_="card p-5 text-center",
                    style="max-width:560px; border-radius:12px; box-shadow:0 4px 32px rgba(0,0,0,.08);",
                ),
                class_="min-vh-100 d-flex align-items-center justify-content-center p-4",
                style="background:#f5f5f7;",
            )

        if state == "source_selection":
            if mode == "fetch":
                return query_page_ui()
            if mode == "archive":
                return ui.div(
                    archive_ui(),
                    class_="min-vh-100 p-4",
                    style="background:#f5f5f7;",
                )
            return ui.div()

        # state == "loaded"
        source = data_source.get()


        right_btns = [
            ui.tags.div(
                ui.tags.button(
                    "Download Processed Data",
                    ui.tags.span(class_="caret"),
                    class_="btn btn-sm btn-primary dropdown-toggle me-0",
                    **{"data-bs-toggle": "dropdown", "aria-expanded": "false", "type": "button"},
                ),
                ui.tags.ul(
                    ui.tags.li(
                        ui.download_button("btn_download", "CSV (.csv)",
                                           class_="dropdown-item"),
                    ),
                    ui.tags.li(
                        ui.download_button("btn_download_xlsx", "Excel (.xlsx)",
                                           class_="dropdown-item"),
                    ),
                    class_="dropdown-menu",
                ),
                class_="btn-group me-2 mt-1",
            ),
        ]
        if source == "fetch":
            toggle_label = "Hide Query" if edit_panel_open.get() else "Edit Query"
            right_btns.append(
                ui.input_action_button("btn_toggle_edit", toggle_label,
                                       class_="btn btn-sm btn-secondary me-2 mt-1")
            )
        elif source == "upload":
            right_btns.append(
                ui.tags.button(
                    "Upload New Data",
                    class_="btn btn-sm btn-secondary me-2 mt-1",
                    onclick="document.getElementById('upload_file_new').click();",
                    type="button",
                )
            )
        if mode == "archive":
            right_btns.append(ui.output_ui("check_updates_btn_ui"))
        back_label = "Select Other Archive Data" if mode == "archive" else "Back to Upload/Query"
        right_btns.append(
            ui.input_action_button("btn_back_to_page", back_label,
                                   class_="btn btn-sm btn-dark me-2 mt-1")
        )
        right_controls = ui.div(*right_btns, class_="d-flex align-items-center")

        return ui.div(
            _inner_tabs(right_controls=right_controls),
            class_="flex-grow-1 mx-1",
        )

    # ── Console log ───────────────────────────────────────────────────────────

    @output(suspend_when_hidden=False)
    @render.ui
    def console_log():
        entries = log_entries.get()
        if not entries:
            return ui.p("No log entries yet. Run a query to see output.",
                        class_="text-muted fst-italic")
        colors = {"info": "#aaa", "ok": "#4ec94e", "warn": "#f0c040", "error": "#f04040"}
        icons  = {"info": ">", "ok": "success: ", "warn": "warning: ", "error": "error: "}
        lines  = []
        for ts, level, msg in entries:
            color = colors.get(level, "#aaa")
            icon  = icons.get(level, ">")
            lines.append(
                ui.div(
                    ui.span(f"[{ts}]", style="color:#555; margin-right:.5rem;"),
                    ui.span(icon,      style=f"color:{color}; margin-right:.4rem;"),
                    ui.span(msg,       style=f"color:{color};"),
                    style="margin:.15rem 0; line-height:1.5;",
                )
            )
        return ui.div(*lines)

    @reactive.effect
    @reactive.event(input.btn_clear_log)
    def _on_clear_log():
        log_entries.set([])

    # ── Wire modules ──────────────────────────────────────────────────────────

    query_server(
        input, output, session,
        current_mode=current_mode,
        app_state=app_state,
        is_loading=is_loading,
        load_progress=load_progress,
        api_data=api_data,
        upload_data=upload_data,
        query_params=query_params,
        upload_info=upload_info,
        data_source=data_source,
        edit_panel_open=edit_panel_open,
        api_error=api_error,
        log_fn=_log,
        run_fetch_fn=_run_fetch,
        read_uploaded_csv_fn=read_uploaded_csv,
        process_fn=process_raw_ctgov,
        fetch_pubs_fn=add_publications,
    )

    trial_info_server(input, output, session, active_data=active_data)
    trial_summary_server(input, output, session, active_data=active_data)
    viz_server(input, output, session, active_data=active_data)
    archive_server(
        input, output, session,
        session_archive=session_archive,
        app_state=app_state,
        current_mode=current_mode,
        data_source=data_source,
        api_data=api_data,
        upload_data=upload_data,
        archive_update_status=archive_update_status,
        log_fn=_log,
    )
