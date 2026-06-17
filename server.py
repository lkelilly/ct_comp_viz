"""
server.py
─────────
Shared state, core fetch logic, and module wiring.

Owns:
  - All shared reactive values
  - _log helper and _summarise_kwargs
  - _run_fetch (async, used by landing._on_run and _on_rerun here)
  - _on_rerun handler (sidebar Re-run Query button)
  - compare_upload_status
  - console_log + btn_clear_log
  - Calls landing_server and trial_info_server
"""

import asyncio
import time
from datetime import datetime

import pandas as pd
from itables import to_html_datatable

from shiny import reactive, render, ui

from ct_api import fetch_studies, CTGovAPIError, CTGovNetworkError
from utils  import studies_to_dataframe, read_uploaded_csv, process_raw_ctgov, filter_upload_data, _valid_date
from ui     import main_layout

from modules.landing        import landing_server
from modules.trial_info     import trial_info_server
from modules.trial_summary  import trial_summary_server
from modules.compare        import compare_server
from modules.viz            import viz_server


def server(input, output, session):

    # ── Shared reactive state ─────────────────────────────────────────────────
    show_main       = reactive.Value(False)
    is_loading      = reactive.Value(False)
    load_progress   = reactive.Value((0, 0))

    api_data        = reactive.Value(None)
    upload_data     = reactive.Value(None)
    upload_data_raw = reactive.Value(None)   # original upload; no overwritten after set
    compare_data    = reactive.Value(None)
    api_error       = reactive.Value(None)
    filter_snapshot = reactive.Value({})
    log_entries     = reactive.Value([])

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

    def _summarise_kwargs(kwargs):
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

    # ── Core async fetch (shared by landing._on_run and _on_rerun) ────────────

    async def _run_fetch(kwargs):
        api_error.set(None)
        is_loading.set(True)
        load_progress.set((0, 0))

        _log(f"Query: {_summarise_kwargs(kwargs)}")
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

            with ui.Progress(min=0, max=4) as p:
                p.set(0, message="Processing data", detail="Standardizing dates...")
                await asyncio.sleep(0)
                p.set(1, message="Processing data", detail="Mapping indications...")
                await asyncio.sleep(0)
                p.set(2, message="Processing data", detail="Adding compound information...")
                df = process_raw_ctgov(df, query_intr=kwargs.get("query_intr") or "")
                p.set(4, message="Processing data", detail="Done")
                await asyncio.sleep(0)

            _log(f"Processed DataFrame: indication + compound columns added", level="ok")

            api_data.set(df)
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

    # ── Re-run from sidebar ───────────────────────────────────────────────────

    @reactive.effect
    @reactive.event(input.btn_rerun)
    async def _on_rerun():
        kwargs = dict(
            query_cond=input.query_cond(),
            query_intr=input.query_intr(),
            query_other_id=input.query_other_id() or "",
            query_term=input.query_term(),
            query_locn=input.query_locn(),
            query_titles=input.query_titles(),
            query_spons=input.query_spons(),
            query_id=input.query_id(),
            query_outc=input.query_outc(),
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

        if api_data.get() is not None:
            _log("Re-running query with updated filters…")
            await _run_fetch(kwargs)
        else:
            raw = upload_data_raw.get()
            if raw is None:
                _log("No uploaded data to filter.", level="warn")
                return
            _log(f"Applying filters to uploaded data…")
            try:
                filtered = filter_upload_data(raw, kwargs)
                upload_data.set(filtered)
                _log(
                    f"Filters applied: {len(filtered):,} of {len(raw):,} rows shown.",
                    level="ok",
                )
            except Exception as e:
                _log(f"Error applying filters: {e}", level="error")

    @reactive.effect
    def _update_rerun_label():
        if api_data.get() is not None:
            ui.update_action_button("btn_rerun", label="Re-run Query")
        elif upload_data.get() is not None:
            ui.update_action_button("btn_rerun", label="Apply Filters")

    @reactive.effect
    def _toggle_sidebar_for_viz():
        tab = input.main_navbar()
        ui.update_sidebar("main_sidebar", show=(tab != "Visualization"))

    # ── Console log ───────────────────────────────────────────────────────────

    @output
    @render.ui
    def console_log():
        entries = log_entries.get()
        if not entries:
            return ui.p("No log entries yet. Run a query to see output.",
                        style="color:#555; font-style:italic;")
        colors = {"info": "#aaa", "ok": "#4ec94e", "warn": "#f0c040", "error": "#f04040"}
        icons  = {"info": ">",   "ok": "✓",        "warn": "⚠",       "error": "✗"}
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

    landing_server(
        input, output, session,
        show_main=show_main,
        is_loading=is_loading,
        load_progress=load_progress,
        api_data=api_data,
        upload_data=upload_data,
        upload_data_raw=upload_data_raw,
        api_error=api_error,
        filter_snapshot=filter_snapshot,
        log_entries=log_entries,
        main_layout=main_layout,
        run_fetch_fn=_run_fetch,
        read_uploaded_csv_fn=read_uploaded_csv,
        process_fn=process_raw_ctgov,
    )

    trial_info_server(input, output, session, active_data=active_data)
    trial_summary_server(input, output, session, active_data=active_data)
    compare_server(input, output, session, active_data=active_data, compare_data=compare_data, log_fn=_log)
    viz_server(input, output, session, active_data=active_data)