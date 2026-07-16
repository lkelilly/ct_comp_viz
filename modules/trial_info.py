"""
modules/trial_info.py
─────────────────────
Trial Information tab — UI and server logic.
"""

import math

import pandas as pd
from itables import to_html_datatable, JavascriptFunction
from shiny import reactive, render, ui

from core.utils import COL_LABELS, dismissible_alert, _pad_month_only
from modules.trial_filters import input_exists, filter_sort_sidebar, register_trial_filters, apply_trial_filters


def _insert_after(d, after_key, extra):
    """Return a copy of dict `d` with `extra`'s items inserted right after
    `after_key`. Preserves key order, which trial_table below relies on to
    determine displayed column order."""
    out = {}
    for k, v in d.items():
        out[k] = v
        if k == after_key:
            out.update(extra)
    return out


TRIAL_TABLE_LABELS = _insert_after(COL_LABELS, "brief_summary", {
    "primary_outcome_measures":   "Primary Outcome Measures",
    "secondary_outcome_measures": "Secondary Outcome Measures",
})

TRUNCATE_COLS = [
    "brief_summary",
    "primary_outcome_measures",
    "secondary_outcome_measures",
    "simplified_primary_outcome",
    "simplified_secondary_outcome",
    "conditions",
    "interventions",
    "inclusion_criteria",
    "exclusion_criteria",
]

TRUNCATE_LENGTH = 200


# ── Edit-mode field classification ──────────────────────────────────────────
# Date fields display/store their original string via the "_raw" companion column
# and are re-parsed into the datetime column on save.
_TI_DATE_FIELDS = {
    "start_date", "primary_completion_date", "completion_date", "last_update_date",
}
# Long free-text fields get a textarea instead of a single-line input.
_TI_LONG_FIELDS = set(TRUNCATE_COLS)
# The NCT number is the row key used for matching, so it is shown read-only.
_TI_READONLY_FIELDS = {"nct_number"}
# Fields computed by this app (derived), plus Brief Summary (manually cleaned-up
# free text) — these are the only ones exposed as editable in the edit modal.
_TI_EDITABLE_FIELDS = {
    "compound", "indication", "acronym",
    "simplified_primary_outcome", "simplified_secondary_outcome",
    "brief_summary",
}
# Fields a reviewer needs for context first, shown at the top of the edit modal.
_TI_PRIORITY_FIELDS = ["study_title", "interventions", "conditions"]


def _editable_fields(df):
    """Columns editable in the trial edit modal, in display order."""
    return [c for c in TRIAL_TABLE_LABELS
            if c in df.columns and c in _TI_EDITABLE_FIELDS]


def _modal_field_order(df):
    """All modal-visible columns, in display order: priority fields first,
    then the remaining TRIAL_TABLE_LABELS fields in their normal order."""
    priority = [c for c in _TI_PRIORITY_FIELDS if c in df.columns]
    rest = [c for c in TRIAL_TABLE_LABELS
            if c in df.columns and c not in _TI_READONLY_FIELDS and c not in priority]
    return priority + rest


def _edit_value(row, field):
    """String value to prefill an edit input for `field` from a trial `row` dict."""
    if field in _TI_DATE_FIELDS:
        raw = row.get(field + "_raw")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        v = row.get(field)
        try:
            if v is not None and pd.notna(v):
                return pd.to_datetime(v).strftime("%Y-%m-%d")
        except Exception:
            pass
        return ""
    v = row.get(field)
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    return str(v)


def trial_info_ui():
    sidebar = filter_sort_sidebar("ti")

    return ui.nav_panel(
        "Trial Information",
        ui.layout_sidebar(
            sidebar,
            ui.div(
                ui.output_ui("ti_edit_controls"),
                ui.output_ui("trial_table"),
            ),
        ),
    )


def trial_info_server(input, output, session, active_data, display_data=None,
                      edit_mode=None, edited_ncts=None,
                      session_archive=None, loaded_session_index=None,
                      api_data=None, upload_data=None, log_fn=None):

    register_trial_filters(output, "ti", active_data)

    display_data = display_data if display_data is not None else active_data

    # Edit mode: when on, NCT numbers become clickable to open the edit modal.
    _ti_edit_mode: reactive.Value = edit_mode if edit_mode is not None else reactive.Value(False)
    # This edit-mode session's own saved edits, patched over display_data() so
    # they show up immediately even while unrelated background changes are held back.
    _own_edits: reactive.Value = reactive.Value({})

    @reactive.effect
    @reactive.event(input.ti_toggle_edit)
    def _toggle_ti_edit():
        turning_on = not _ti_edit_mode.get()
        _ti_edit_mode.set(turning_on)
        if turning_on:
            ui.update_navset("inner_tabs", selected="Trial Information")
        else:
            if (loaded_session_index is not None and session_archive is not None
                    and loaded_session_index.get() is not None):
                idx = loaded_session_index.get()
                records = session_archive.get()
                if 0 <= idx < len(records):
                    df = active_data()
                    if df is not None:
                        new_records = records.copy()
                        new_records[idx] = {**new_records[idx], "df": df.copy()}
                        session_archive.set(new_records)
                        if log_fn:
                            log_fn(f"Updated saved record '{new_records[idx].get('label', '')}' "
                                   f"with {len(df)} row(s) of edits", level="ok")
            _own_edits.set({})

    @output(suspend_when_hidden=False)
    @render.ui
    def ti_edit_btn_ui():
        editing = _ti_edit_mode.get()
        return ui.input_action_button(
            "ti_toggle_edit",
            "Save My Edits" if editing else "Edit Trials",
            class_="btn btn-sm " + ("btn-outline-success" if editing else "btn-success") + " me-2 mt-1",
        )

    @output(suspend_when_hidden=False)
    @render.ui
    def ti_edit_controls():
        if not _ti_edit_mode.get():
            return ui.div()
        return ui.div(
            dismissible_alert(
                ui.span(
                    "1. Click an NCT number in the table to edit that trial.",
                    ui.br(),
                    "2. Click ", ui.tags.code("Save My Edits"), " to re-load visualization.",
                    ui.br(),
                    "3. Click ", ui.tags.code("Save to Archive"), " to save this data set to archive data.",
                ),
                level="primary",
            ),
            class_="mb-1",
        )

    @output(suspend_when_hidden=False)
    @render.ui
    def trial_table():
        df = display_data()
        if df is None or df.empty:
            return ui.p("Returned 0 studies. Check your query message.",
                        class_="text-muted p-4 text-center")

        own = _own_edits.get()
        if own:
            df = df.copy()
            for nct, fields in own.items():
                mask = df["nct_number"] == nct
                for field, val in fields.items():
                    if field in df.columns:
                        df.loc[mask, field] = val

        df = apply_trial_filters(df, input, "ti")

        sort_col = input.ti_sort_by() if input_exists(input, "ti_sort_by") else "start_date"
        if sort_col in df.columns:
            df = df.sort_values(sort_col, na_position="last")

        df_display = df.rename(columns=TRIAL_TABLE_LABELS)
        display_cols = [TRIAL_TABLE_LABELS[c] for c in TRIAL_TABLE_LABELS if c in df.columns]
        df_display = df_display[display_cols]

        pub_label = TRIAL_TABLE_LABELS.get("relevant_publication", "Relevant Publication")
        col_defs = []
        if pub_label in display_cols:
            pub_idx = display_cols.index(pub_label)
            col_defs.append({
                "targets": [pub_idx],
                "render": JavascriptFunction(
                    "function(data, type, row) {"
                    "  if (type !== 'display' || !data || data === 'NA') return data;"
                    "  return data.split(' | ').map(function(part) {"
                    "    part = part.trim();"
                    "    if (part.indexOf('http://') === 0 || part.indexOf('https://') === 0) {"
                    "      return '<a href=\"' + part + '\" target=\"_blank\" class=\"d-block\">' + part + '</a>';"
                    "    }"
                    "    return part;"
                    "  }).join('');"
                    "}"
                ),
            })

        cluwe_label = TRIAL_TABLE_LABELS.get("cluwe_path", "CLUWE Path")
        if cluwe_label in display_cols:
            cluwe_idx = display_cols.index(cluwe_label)
            col_defs.append({
                "targets": [cluwe_idx],
                "render": JavascriptFunction(
                    "function(data, type, row) {"
                    "  if (type !== 'display' || !data || data === 'NA') return data;"
                    "  return data.split(' | ').map(function(part) {"
                    "    return '<span class=\"d-block\">' + part.trim() + '</span>';"
                    "  }).join('');"
                    "}"
                ),
            })

        if _ti_edit_mode.get():
            nct_label = TRIAL_TABLE_LABELS.get("nct_number", "NCT Number")
            if nct_label in display_cols:
                nct_idx = display_cols.index(nct_label)
                col_defs.append({
                    "targets": [nct_idx],
                    "render": JavascriptFunction(
                        "function(data, type, row) {"
                        "  if (type !== 'display' || !data) return data;"
                        "  return '<a href=\"#\" class=\"ti-nct-link\" data-nct=\"' + data + '\">' + data + '</a>';"
                        "}"
                    ),
                })

        truncate_labels = [TRIAL_TABLE_LABELS.get(c, c) for c in TRUNCATE_COLS]
        truncate_idxs = [display_cols.index(lbl) for lbl in truncate_labels if lbl in display_cols]
        if truncate_idxs:
            col_defs.append({
                "targets": truncate_idxs,
                "render": JavascriptFunction(
                    "function(data, type, row) {"
                    "  if (type !== 'display' || data == null) return data;"
                    "  var s = String(data);"
                    f"  if (s.length <= {TRUNCATE_LENGTH}) return s;"
                    f"  var shortText = s.slice(0, {TRUNCATE_LENGTH}) + '…';"
                    "  var fullAttr = s.replace(/\"/g, '&quot;');"
                    "  return '<span class=\"trunc\" data-full=\"' + fullAttr + '\">' + shortText + '</span>';"
                    "}"
                ),
            })

        dt_kwargs = dict(
            showIndex=False,
            lengthMenu=[10, 25, 50, 100],
            pageLength=10,
            style="width:100%",
            classes="display compact",
            scrollX=True,
        )
        if col_defs:
            dt_kwargs["columnDefs"] = col_defs

        table_html = to_html_datatable(df_display, **dt_kwargs)
        return ui.HTML(table_html)

    # ── Edit modal: open on NCT click ────────────────────────────────────────

    @reactive.effect
    @reactive.event(input.ti_edit_nct)
    def _show_ti_edit_modal():
        nct = input.ti_edit_nct()
        if not nct:
            return
        ui.modal_remove()   # clear any existing modal first
        df = active_data()
        if df is None:
            return
        rows = df[df["nct_number"] == nct]
        if rows.empty:
            return
        row = rows.iloc[0].to_dict()

        body_items = []

        for field in _modal_field_order(df):
            label = TRIAL_TABLE_LABELS.get(field, field)
            value = _edit_value(row, field)
            if field in _TI_EDITABLE_FIELDS:
                input_id = f"ti_edit_{nct}_{field}"
                if field in _TI_LONG_FIELDS:
                    widget = ui.input_text_area(input_id, None, value=value,
                                                width="100%", rows=3)
                else:
                    widget = ui.input_text(input_id, None, value=value, width="100%")
                hint = ui.span(" (YYYY-MM-DD)", class_="text-muted small") \
                    if field in _TI_DATE_FIELDS else ui.span()
                body_items.append(
                    ui.div(
                        ui.div(
                            ui.span(label, class_="fw-semibold small"),
                            hint,
                            class_="mb-1",
                        ),
                        widget,
                        class_="mb-3",
                    )
                )
            else:
                body_items.append(
                    ui.div(
                        ui.span(label, class_="fw-semibold small d-block"),
                        ui.span(value or "—", class_="text-muted small"),
                        class_="mb-2",
                    )
                )

        ui.modal_show(
            ui.modal(
                *body_items,
                title=f"Edit — {nct}",
                footer=ui.div(
                    ui.input_action_button(
                        "btn_ti_edit_save", "Save",
                        class_="btn btn-primary me-2",
                    ),
                    ui.modal_button("Cancel"),
                ),
                size="xl",
                easy_close=True,
            )
        )

    @reactive.effect
    @reactive.event(input.btn_ti_edit_save)
    def _on_ti_edit_save():
        nct = input.ti_edit_nct()
        if not nct:
            ui.modal_remove()
            return
        base = active_data()
        if base is None:
            ui.modal_remove()
            return
        df = base.copy()
        mask = df["nct_number"] == nct
        if not mask.any():
            ui.modal_remove()
            return

        own_field_vals = {}
        for field in _editable_fields(df):
            input_id = f"ti_edit_{nct}_{field}"
            try:
                val = getattr(input, input_id)()
            except Exception:
                continue
            if val is None:
                continue
            val = str(val)

            if field in _TI_DATE_FIELDS:
                raw_col = field + "_raw"
                if raw_col in df.columns:
                    if df[raw_col].dtype != object:
                        df[raw_col] = df[raw_col].astype(object)
                    df.loc[mask, raw_col] = val.strip()
                parsed = (pd.to_datetime(_pad_month_only(val.strip()), errors="coerce")
                          if val.strip() else pd.NaT)
                df.loc[mask, field] = parsed
                own_field_vals[field] = parsed
            elif field == "enrollment":
                try:
                    num = float(val) if val.strip() != "" else float("nan")
                    df.loc[mask, field] = num
                    own_field_vals[field] = num
                except ValueError:
                    if df[field].dtype != object:
                        df[field] = df[field].astype(object)
                    df.loc[mask, field] = val
                    own_field_vals[field] = val
            else:
                if df[field].dtype != object:
                    df[field] = df[field].astype(object)
                df.loc[mask, field] = val
                own_field_vals[field] = val

        own = _own_edits.get().copy()
        own[nct] = own_field_vals
        _own_edits.set(own)

        if edited_ncts is not None:
            s = edited_ncts.get().copy()
            s.add(nct)
            edited_ncts.set(s)

        # Write edits back to whichever source feeds active_data
        if api_data is not None and api_data.get() is not None:
            api_data.set(df)
        elif upload_data is not None:
            upload_data.set(df)

        if log_fn:
            log_fn(f"Edited trial {nct}", level="ok")
        ui.modal_remove()