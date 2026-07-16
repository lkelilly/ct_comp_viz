"""
modules/archive.py
──────────────────
Archive browser UI and server logic.

Session-saved records are stored in-memory via session_archive reactiveVal.

Also owns Check Updates: diff computation, the Checking tab DataTable,
and Save to Session with name modal.
"""

import re
import html as _html
import json as _json
from pathlib import Path
from datetime import date
import math

import pandas as pd
from itables import to_html_datatable, JavascriptFunction
from shiny import reactive, render, ui

from core.utils import (
    read_uploaded_csv, filter_by_selections, input_exists,
    make_filter_ui, filter_sort_sidebar, dismissible_alert, COL_LABELS,
    _pad_month_only,
)
from core.ct_api import fetch_studies, CTGovAPIError, CTGovNetworkError
from core.utils import _extract_study


_COMPARE_FIELDS = [
    "study_status",
    "enrollment",
    "primary_completion_date",
    "completion_date",
    "study_results",
    "primary_outcome_measures",
    "secondary_outcome_measures",
    "inclusion_criteria",
    "exclusion_criteria",
    "interventions",
    "conditions",
    "start_date",
]

# Derived fields editable in diff view
_DERIVED_FIELDS = {
    "compound":   "interventions",
    "indication": "conditions",
    "acronym":    None,
}

_COL_LABELS = {
    **COL_LABELS,
    "primary_outcome_measures":   "Primary Outcomes",
    "secondary_outcome_measures": "Secondary Outcomes",
}

_TRUNCATE_COLS = {
    "primary_outcome_measures", "secondary_outcome_measures",
    "inclusion_criteria", "exclusion_criteria", "conditions", "interventions",
}
_TRUNCATE_LEN = 200

def _norm(val, field):
    """Normalize a field value for comparison."""
    if field == "enrollment":
        try:
            v = float(val)
            return None if math.isnan(v) else int(v)
        except (TypeError, ValueError):
            return None
    if field in ("primary_completion_date", "completion_date", "start_date"):
        raw = str(val).strip() if val is not None else ""
        if raw in ("", "NaT", "nan"):
            return None
        try:
            return pd.to_datetime(raw, dayfirst=False, errors="raise").strftime("%Y-%m-%d")
        except Exception:
            return raw.replace("/", "-")
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    s = str(val).strip().lower()
    s = re.sub(r'\s*\|\s*', '|', s)
    return s or None


_NO_RAW_FIELDS = {
    "conditions", "interventions", "study_status", "study_results",
    "primary_outcome_measures", "secondary_outcome_measures",
    "inclusion_criteria", "exclusion_criteria",
}


def compare_trial_fields(archived: dict, fresh: dict) -> list:
    """Return list of {field, archived_value, current_value} for changed fields."""
    diffs = []
    for field in _COMPARE_FIELDS:
        raw_field = field + "_raw"
        if field in _NO_RAW_FIELDS:
            arch_val = archived.get(field)
            fresh_val = fresh.get(field)
        else:
            arch_val = archived.get(raw_field) or archived.get(field)
            fresh_val = fresh.get(raw_field) or fresh.get(field)
        arch_norm = _norm(arch_val, field)
        fresh_norm = _norm(fresh_val, field)
        if arch_norm != fresh_norm:
            diffs.append({
                "field": field,
                "archived_value": arch_val,
                "current_value": fresh_val,
            })
    return diffs


def _e(val):
    return _html.escape(str(val) if val is not None else "")


def _trunc_span(val, field):
    """Escaped HTML for a value; wraps in a hoverable span with the full
    text in data-full when the value is actually truncated."""
    s = str(val) if val is not None else ""
    if field in _TRUNCATE_COLS and len(s) > _TRUNCATE_LEN:
        short = s[:_TRUNCATE_LEN] + "…"
        return f'<span class="trunc" data-full="{_e(s)}">{_e(short)}</span>'
    return _e(s)


def _build_diff_datatable(df, diffs_by_nct, pending):
    """Build an itables DataTable HTML string for the Checking tab."""
    show_cols = (
        ["nct_number", "study_title"]
        + _COMPARE_FIELDS
        + list(_DERIVED_FIELDS.keys())
    )
    show_cols = [c for c in show_cols if c in df.columns]

    rows = df.to_dict("records")
    changed_ncts = set(diffs_by_nct.keys())

    def _sort_key(r):
        return (0 if r["nct_number"] in changed_ncts else 1,
                -len(diffs_by_nct.get(r["nct_number"], [])))

    rows = sorted(rows, key=_sort_key)

    display_rows = []
    for row in rows:
        nct = row.get("nct_number", "")
        row_diffs = {d["field"]: d for d in diffs_by_nct.get(nct, [])}
        is_changed = nct in changed_ncts
        has_pending = bool(pending.get(nct))
        out = {"_sort": "0" if is_changed else "1"}

        # Build NCT cell explicitly for hightlighted color
        nct_safe = _e(nct)
        nct_link = (
            f'<a href="#" class="nct-link" style="font-weight:500" data-nct="{nct_safe}">{nct_safe}</a>'
        )
        if is_changed and has_pending:
            out["nct_number"] = (
                f'<div style="border-left:3px solid #198754;padding-left:5px;background:#d1e7dd">'
                f'{nct_link}'
                f'</div>'
            )
        elif is_changed:
            out["nct_number"] = nct_link
        else:
            out["nct_number"] = nct_safe

        for col in show_cols:
            if col == "nct_number":
                continue  # already handled above
            raw_key = col + "_raw"
            arch_val = row.get(raw_key, row.get(col, ""))
            if arch_val is None or (isinstance(arch_val, float) and math.isnan(arch_val)):
                arch_val = ""

            if col in _DERIVED_FIELDS:
                # Read-only — show pending edit value if available, else archived value
                display_val = (pending.get(nct) or {}).get(col, arch_val)
                out[col] = _e(str(display_val) if display_val else "")
            elif col in row_diffs and is_changed:
                diff = row_diffs[col]
                old_html = _trunc_span(arch_val, col)
                new_html = _trunc_span(diff["current_value"] or "", col)
                out[col] = (
                    f'<div style="border-left:3px solid #f0c040;padding-left:5px;background:#fffde7">'
                    f'<span style="color:#aaa;font-size:.82em;display:block">{old_html}</span>'
                    f'<span style="font-weight:500;display:block">{new_html}</span>'
                    f'</div>'
                )
            else:
                out[col] = _trunc_span(arch_val, col)

        display_rows.append(out)

    if not display_rows:
        return "<p class='text-muted p-3'>No data.</p>"

    display_df = pd.DataFrame(display_rows, columns=["_sort"] + show_cols)
    display_df = display_df.rename(columns=_COL_LABELS)

    html_render = JavascriptFunction(
        "function(data, type, row) {"
        "  if (type === 'display') return data != null ? data : '';"
        "  return (data != null ? String(data) : '').replace(/<[^>]+>/g, '');"
        "}"
    )
    col_defs = [
        {"targets": [0], "visible": False, "searchable": False},
        {"targets": "_all", "render": html_render},
    ]

    table_html = to_html_datatable(
        display_df,
        showIndex=False,
        allow_html=True,
        columnDefs=col_defs,
        scrollX=True,
        lengthMenu=[10, 25, 50],
        pageLength=25,
        classes="display compact",
        order=[[0, "asc"]],
    )
    return table_html


# ── Archive date normalization ─────────────────────────────────────────────────

_DATE_COLS = ("start_date", "primary_completion_date", "completion_date", "last_update_date")


def _normalize_archive_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize date columns in a CSV-loaded archive DataFrame to YYYY-MM-DD strings.

    Month-only values (YYYY-MM) are padded to the first of the month, matching
    process_raw_ctgov()'s handling so downstream date parsing (e.g. the
    Visualization tab) treats them the same as fetched/uploaded data.
    Unparseable values are left unchanged. Non-string values (e.g.
    already-parsed Timestamps) are skipped.
    """
    df = df.copy()
    for col in _DATE_COLS:
        if col not in df.columns:
            continue

        def _to_iso(v):
            if not isinstance(v, str):
                return v
            v = v.strip()
            if not v or v in ("NaT", "nan"):
                return v
            v = _pad_month_only(v)
            try:
                return pd.to_datetime(v, dayfirst=False).strftime("%Y-%m-%d")
            except Exception:
                return v

        df[col] = df[col].apply(_to_iso)
    return df


# ── Curated data ──────────────────────────────────────────────────────────────

_CURATED_STUBS = _json.loads(
    (Path(__file__).parent.parent / "data" / "curated_datasets.json").read_text(encoding="utf-8")
)


# ── UI ────────────────────────────────────────────────────────────────────────

def archive_ui():
    return ui.div(
        ui.div(
            ui.input_text(
                "archive_filter", None,
                placeholder="Search by compound",
            ),
            class_="mb-3",
        ),
        ui.h6("Curated datasets", class_="fw-semibold mb-3"),
        ui.div(
            *[
                ui.div(
                    ui.div(
                        ui.div(
                            ui.span(stub["compound"], class_="fw-semibold d-block"),
                            ui.span(stub["indication"], class_="text-muted small"),
                            class_="mb-2",
                        ),
                        ui.p(stub.get("description", ""), class_="small text-muted mb-3"),
                        ui.div(
                            ui.span(f"Updated: {stub['save_date']}", class_="text-muted small"),
                            ui.input_action_button(
                                f"btn_load_curated_{i}", "Load",
                                class_="btn btn-sm btn-outline-dark",
                            ),
                            class_="d-flex justify-content-between align-items-center",
                        ),
                        class_="card p-3 h-100",
                    ),
                    class_="col",
                )
                for i, stub in enumerate(_CURATED_STUBS)
            ],
            class_="row row-cols-1 row-cols-md-2 g-3 mb-3",
        ),
        ui.hr(class_="my-3"),
        ui.h6("Saved in this session", class_="fw-semibold mb-2"),
        ui.output_ui("session_archive_cards"),
        class_="p-3",
    )


# ── Server ────────────────────────────────────────────────────────────────────

def archive_server(input, output, session,
                   session_archive, app_state, data_source,
                   api_data, upload_data, archive_update_status, active_data,
                   log_fn=None):

    # Diff state owned entirely here
    _update_diffs:  reactive.Value = reactive.Value(None)
    _update_fresh:  reactive.Value = reactive.Value(None)
    _pending_edits: reactive.Value = reactive.Value({})
    _source_label   = reactive.Value("")

    # ── Check Updates handler ────────────────────────────────────────────────

    @reactive.effect
    @reactive.event(input.btn_check_updates)
    async def _on_check_updates():
        df = active_data()
        if df is None:
            return
        archive_update_status.set({"checking": True})
        nct_ids = df["nct_number"].dropna().tolist()
        diffs_by_nct = {}
        try:
            with ui.Progress(min=0, max=2) as p:
                p.set(0, message="Fetching latest data from ClinicalTrials.gov…")
                studies, _ = await fetch_studies(
                    query_id=" OR ".join(nct_ids), max_results=len(nct_ids)
                )
                fresh_by_nct = {
                    row["nct_number"]: row
                    for row in [_extract_study(s) for s in studies]
                }
                p.set(1, message="Comparing fields…")
                for _, archived in df.iterrows():
                    nct = archived["nct_number"]
                    fresh = fresh_by_nct.get(nct)
                    if fresh is None:
                        continue
                    field_diffs = compare_trial_fields(dict(archived), fresh)
                    if field_diffs:
                        diffs_by_nct[nct] = field_diffs
                p.set(2)
        except CTGovAPIError as e:
            archive_update_status.set({})
            if log_fn:
                log_fn(f"Archive check: API error: {e}", level="error")
            ui.notification_show(f"API error: {e}", type="error", duration=6)
            return
        except CTGovNetworkError as e:
            archive_update_status.set({})
            if log_fn:
                log_fn(f"Archive check: network error: {e}", level="error")
            ui.notification_show(f"Network error: {e}", type="error", duration=6)
            return
        except Exception as e:
            archive_update_status.set({})
            if log_fn:
                log_fn(f"Archive check: unexpected error: {e}", level="error")
            ui.notification_show(f"Could not check updates: {e}", type="error", duration=6)
            return

        if log_fn:
            log_fn(f"Archive check: {len(nct_ids)} trial(s) queried from ClinicalTrials.gov")

        if not diffs_by_nct:
            archive_update_status.set({})
            if log_fn:
                log_fn(f"Archive check: all {len(nct_ids)} trial(s) up to date", level="ok")
            ui.notification_show("All trials are up to date.", type="message", duration=4)
            return

        if log_fn:
            log_fn(f"Archive check: {len(diffs_by_nct)} trial(s) with changed fields", level="ok")
        _update_diffs.set(diffs_by_nct)
        _update_fresh.set(fresh_by_nct)
        _pending_edits.set({})
        archive_update_status.set({"diffs": diffs_by_nct})
        ui.insert_nav_panel(
            "inner_tabs",
            ui.nav_panel(
                "Checking",
                ui.layout_sidebar(
                    filter_sort_sidebar("chk"),
                    ui.div(
                        dismissible_alert(
                            "Click an NCT number to review and edit derived fields (Compound, Indication, Acronym) for that trial.",
                            level="primary",
                        ),
                        ui.output_ui("checking_table"),
                    ),
                ),
            ),
            target="Trial Information",
            position="after",
            select=True,
        )

    # ── NCT-click review modal ───────────────────────────────────────────────

    @reactive.effect
    @reactive.event(input.selected_nct)
    def _show_nct_modal():
        nct = input.selected_nct()
        if not nct:
            return
        ui.modal_remove()   # clear any existing modal before showing a new one
        diffs = _update_diffs.get() or {}
        row_diffs = diffs.get(nct, [])
        df = active_data()
        archived_row = {}
        if df is not None:
            rows = df[df["nct_number"] == nct]
            if not rows.empty:
                archived_row = rows.iloc[0].to_dict()

        pending_nct = (_pending_edits.get() or {}).get(nct, {})
        changed_fields = {d["field"] for d in row_diffs}

        body_items = []

        title = archived_row.get("study_title", "")
        if title:
            body_items.append(ui.p(title, class_="fw-semibold mb-3"))

        if row_diffs:
            diff_rows = []
            for d in row_diffs:
                field = d["field"]
                label = _COL_LABELS.get(field, field)
                old_v = str(d["archived_value"] or "—")
                new_v = str(d["current_value"] or "—")
                diff_rows.append(
                    ui.div(
                        ui.div(ui.tags.small(label, class_="fw-semibold"), class_="col-3"),
                        ui.div(ui.tags.small(old_v, class_="text-muted fst-italic"), class_="col"),
                        ui.div(ui.tags.small(new_v, class_="fw-semibold text-success"), class_="col"),
                        class_="row g-1 mb-1 pb-1 border-bottom",
                    )
                )
            body_items += [
                ui.h6("Field Changes", class_="text-muted mb-1 small text-uppercase"),
                ui.div(
                    ui.div(
                        ui.div(ui.tags.small("Field", class_="fw-semibold text-muted"), class_="col-3"),
                        ui.div(ui.tags.small("Current", class_="fw-semibold text-muted"), class_="col"),
                        ui.div(ui.tags.small("Incoming", class_="fw-semibold text-success"), class_="col"),
                        class_="row g-1 mb-1",
                    ),
                    *diff_rows,
                    class_="mb-3",
                ),
            ]

        body_items.append(
            ui.h6("Derived Fields", class_="text-muted mb-2 small text-uppercase mt-2")
        )
        for field, source_field in _DERIVED_FIELDS.items():
            if field not in archived_row:
                continue
            label = _COL_LABELS.get(field, field)
            current_val = pending_nct.get(field, archived_row.get(field, ""))
            stale = source_field is not None and source_field in changed_fields
            stale_badge = (
                ui.span("source changed — review",
                        class_="badge bg-warning text-dark ms-2 small")
                if stale else ui.span()
            )
            body_items.append(
                ui.div(
                    ui.div(
                        ui.span(label, class_="fw-semibold"),
                        stale_badge,
                        class_="mb-1",
                    ),
                    ui.input_text(
                        f"modal_{nct}_{field}", None,
                        value=str(current_val or ""),
                        width="100%",
                    ),
                    class_="mb-3",
                )
            )

        ui.modal_show(
            ui.modal(
                *body_items,
                title=f"Review — {nct}",
                footer=ui.div(
                    ui.input_action_button(
                        "btn_nct_modal_save", "Save",
                        class_="btn btn-primary me-2",
                    ),
                    ui.modal_button("Cancel"),
                ),
                size="xl",
                easy_close=True,
            )
        )

    @reactive.effect
    @reactive.event(input.btn_nct_modal_save)
    def _on_nct_modal_save():
        nct = input.selected_nct()
        if not nct:
            ui.modal_remove()
            return
        edits = _pending_edits.get().copy()
        if nct not in edits:
            edits[nct] = {}
        df = active_data()
        if df is not None:
            for field in _DERIVED_FIELDS:
                if field in df.columns:
                    input_id = f"modal_{nct}_{field}"
                    try:
                        val = getattr(input, input_id)()
                        if val is not None:
                            edits[nct][field] = val
                    except Exception:
                        pass
        _pending_edits.set(edits)
        if log_fn:
            log_fn(f"Pending edit saved for {nct}")
        ui.modal_remove()

    # ── Save to Session button ───────────────────────────────────────────────

    @reactive.effect
    @reactive.event(input.btn_save_to_session)
    def _on_save_to_session_click():
        ui.modal_show(
            ui.modal(
                ui.input_text(
                    "save_session_name", "Dataset name",
                    value=_source_label.get() or "Updated dataset",
                ),
                title="Save to session",
                footer=ui.div(
                    ui.input_action_button(
                        "btn_modal_save", "Save",
                        class_="btn btn-primary me-2",
                    ),
                    ui.modal_button("Cancel"),
                ),
                easy_close=True,
            )
        )

    @reactive.effect
    @reactive.event(input.btn_modal_save)
    def _on_modal_save():
        ui.modal_remove()
        df = active_data()
        if df is None:
            if log_fn:
                log_fn("Save to session: no active data to save", level="error")
            ui.notification_show("No active data to save.", type="error", duration=5)
            return
        try:
            df = df.copy()
            diffs  = _update_diffs.get() or {}
            fresh  = _update_fresh.get() or {}
            edits  = _pending_edits.get()

            # Columns that are entirely NaN get inferred as float64 by pandas;
            # writing text into them later raises "Invalid value ... for dtype
            # 'float64'". Widen to object dtype for any field we're about to write.
            written_fields = set()
            for field_map in edits.values():
                written_fields.update(field_map.keys())
            for field_diffs in diffs.values():
                written_fields.update(d["field"] for d in field_diffs)
            for field in written_fields:
                if field in df.columns and df[field].dtype != object:
                    df[field] = df[field].astype(object)

            # Apply user edits to derived fields
            for nct, field_map in edits.items():
                mask = df["nct_number"] == nct
                for field, value in field_map.items():
                    if field in df.columns:
                        df.loc[mask, field] = value

            # Apply fresh values for all other changed raw fields
            for nct, field_diffs in diffs.items():
                mask = df["nct_number"] == nct
                fresh_row = fresh.get(nct, {})
                nct_edits = edits.get(nct) or {}
                for diff in field_diffs:
                    field = diff["field"]
                    if field in df.columns and field not in nct_edits:
                        df.loc[mask, field] = fresh_row.get(field, diff["current_value"])

            # Set as active data
            if api_data.get() is not None:
                api_data.set(df)
            else:
                upload_data.set(df)

            # Save to session archive
            name = (input.save_session_name() or "").strip() or "Updated dataset"
            src  = _source_label.get() or "archive"
            n_updated = len(diffs)
            records = session_archive.get().copy()
            records.append({
                "label":       name,
                "save_date":   date.today().strftime("%Y-%m-%d"),
                "description": f"Updated from '{src}' — {n_updated} trial(s) updated.",
                "df":          df,
            })
            session_archive.set(records)
            if log_fn:
                log_fn(f"Saved to session: '{name}' — {n_updated} trial(s) updated", level="ok")

            _update_diffs.set(None)
            _update_fresh.set(None)
            _pending_edits.set({})
            archive_update_status.set({"applied": n_updated})
            ui.update_navset("inner_tabs", selected="Trial Information")
            ui.remove_nav_panel("inner_tabs", "Checking")
        except Exception as e:
            if log_fn:
                log_fn(f"Save to session: unexpected error: {e}", level="error")
            ui.notification_show(f"Could not save to session: {e}", type="error", duration=6)

    # ── Checking tab filters ─────────────────────────────────────────────────

    @output(suspend_when_hidden=False)
    @render.ui
    def chk_compound_ui():
        return make_filter_ui(active_data, "compound", "chk_compound", "Compound:")

    @output(suspend_when_hidden=False)
    @render.ui
    def chk_indication_ui():
        return make_filter_ui(active_data, "indication", "chk_indication", "Indication:")

    @output(suspend_when_hidden=False)
    @render.ui
    def chk_phase_ui():
        return make_filter_ui(active_data, "phases", "chk_phase", "Phase:")

    # ── Checking tab output ──────────────────────────────────────────────────

    @output(suspend_when_hidden=False)
    @render.ui
    def checking_table():
        diffs = _update_diffs.get()
        if diffs is None:
            return ui.p("No updates to review.", class_="text-muted p-4 text-center")
        df = active_data()
        if df is None:
            return ui.div()

        df = filter_by_selections(df, input, [
            ("compound",   "chk_compound"),
            ("indication", "chk_indication"),
            ("phases",     "chk_phase"),
        ])
        sort_col = input.chk_sort_by() if input_exists(input, "chk_sort_by") else "start_date"
        if sort_col in df.columns:
            df = df.sort_values(sort_col, na_position="last")

        pending = _pending_edits.get()
        return ui.HTML(_build_diff_datatable(df, diffs, pending))

    # ── Session archive cards ────────────────────────────────────────────────

    @output
    @render.ui
    def session_archive_cards():
        records = session_archive.get()
        if not records:
            return ui.p(
                "No records saved yet. After loading data, use 'Save to session' to store it here.",
                class_="text-muted small fst-italic",
            )
        cards = []
        for i, rec in enumerate(records):
            cards.append(
                ui.div(
                    ui.div(
                        ui.div(
                            ui.span(rec.get("label", f"Record {i+1}"), class_="fw-semibold"),
                        ),
                        ui.div(
                            ui.span(f"Saved: {rec.get('save_date', '')}", class_="text-muted small me-3"),
                            ui.input_action_button(
                                f"btn_load_session_{i}", "Load",
                                class_="btn btn-sm btn-outline-dark",
                            ),
                            class_="d-flex align-items-center",
                        ),
                        class_="d-flex justify-content-between align-items-center",
                    ),
                    class_="card p-3 mb-2",
                )
            )
        return ui.div(*cards)

    # ── Session archive load handlers ────────────────────────────────────────

    @reactive.effect
    def _load_session_handlers():
        records = session_archive.get()
        for i, rec in enumerate(records):
            def _make_handler(idx):
                @reactive.effect
                @reactive.event(input[f"btn_load_session_{idx}"])
                def _handler():
                    r = session_archive.get()[idx]
                    df = r.get("df")
                    if df is not None:
                        api_data.set(None)
                        upload_data.set(df)
                        data_source.set(None)
                        _source_label.set(r.get("label", ""))
                        archive_update_status.set({})
                        app_state.set("loaded")
                        if log_fn:
                            label = r.get("label", "")
                            log_fn(f"Loaded session record: '{label}' ({len(df)} rows)", level="ok")
            _make_handler(i)

    # ── Curated card load handlers ───────────────────────────────────────────

    for i in range(len(_CURATED_STUBS)):
        def _make_curated_handler(idx):
            stub = _CURATED_STUBS[idx]
            csv_path = Path(__file__).parent.parent / stub["path"]

            @reactive.effect
            @reactive.event(input[f"btn_load_curated_{idx}"])
            def _handler():
                try:
                    df = read_uploaded_csv(str(csv_path))
                    df = _normalize_archive_dates(df)
                    api_data.set(None)
                    upload_data.set(df)
                    data_source.set(None)
                    _source_label.set(stub.get("compound", "curated"))
                    archive_update_status.set({})
                    app_state.set("loaded")
                    if log_fn:
                        compound = stub.get("compound", "curated")
                        log_fn(f"Loaded curated dataset: {compound} ({len(df)} rows)", level="ok")
                except Exception as e:
                    ui.notification_show(
                        f"Could not load dataset: {e}",
                        type="error",
                        duration=5,
                    )
        _make_curated_handler(i)
