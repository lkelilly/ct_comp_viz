"""
modules/trial_filters.py
─────────────────────────
Shared "TRIAL FILTERS" sidebar (Compound / Indication / Phase checkboxes +
"Sort rows by") and its server-side wiring. Reused by the Trial Information,
Visualization, and Archive Checking tabs, keyed by a per-tab `prefix`
("ti", "viz", "chk") for input/output ids.
"""

from shiny import reactive, render, ui


def input_exists(input, name):
    """True if a (possibly dynamically-rendered) input exists and has a value
    available on this reactive flush."""
    try:
        input[name]()
        return True
    except Exception:
        return False


def resolve_selection(input, input_id, valid_values):
    """Active selection for a checkbox group, falling back to *all* valid
    values when the input doesn't exist yet or holds a stale selection with
    no overlap in `valid_values` (e.g. after a dataset swap). An existing
    input that is legitimately empty (every box unchecked) is respected as
    "select nothing." `valid_values` = the column's current unique values."""
    valid = set(valid_values)
    if not input_exists(input, input_id):
        return sorted(valid)
    raw = list(input[input_id]())
    if raw and not set(raw).issubset(valid):
        return sorted(valid)
    return raw


def filter_by_selections(df, input, mappings):
    """Filter `df` by one or more checkbox-group selections. `mappings` is an
    iterable of (column, input_id) pairs. Columns absent from `df` are skipped.
    Each column's valid domain is computed from the full, unfiltered `df` (not
    a running/narrowed copy), so a deliberate selection with no overlap with
    another filter's selection — e.g. a compound that has no studies at the
    selected phase — correctly empties the result instead of being treated as
    a stale/invalid input."""
    full = df
    for col, input_id in mappings:
        if col not in df.columns:
            continue
        full_valid = full[col].dropna().unique()
        keep = resolve_selection(input, input_id, full_valid)
        if set(keep) != set(full_valid):
            df = df[df[col].isin(keep)]
    return df


# (column, id suffix, label) triples shared by every trial-filters sidebar.
_FILTER_FIELDS = [
    ("compound",   "compound",   "Compound:"),
    ("indication", "indication", "Indication:"),
    ("phases",     "phase",      "Phase:"),
]


def _make_filter_ui(active_data, col, input_id, label):
    """Render a checkbox-group filter for `col`'s unique values, or an empty
    div if no data is loaded."""
    df = active_data()
    if df is None or df.empty:
        return ui.div()
    choices = sorted(df[col].dropna().unique().tolist())
    return ui.input_checkbox_group(input_id, label, choices=choices, selected=choices)


def _bind_filter_renderer(active_data, col, input_id, label):
    """Return a zero-arg render function bound to this (col, input_id, label),
    isolated in its own scope so each loop iteration in
    `register_trial_filters` captures its own values (not the loop variable)."""
    def _render():
        return _make_filter_ui(active_data, col, input_id, label)
    return _render


def register_trial_filters(output, input, session, prefix, active_data):
    """Register the `{prefix}_compound_ui`/`_indication_ui`/`_phase_ui` render
    functions for a trial-filters sidebar keyed by `prefix`, plus the
    'Apply Multiple Filters' modal observer."""
    for col, suffix, label in _FILTER_FIELDS:
        render_fn = _bind_filter_renderer(active_data, col, f"{prefix}_{suffix}", label)
        output(id=f"{prefix}_{suffix}_ui", suspend_when_hidden=False)(render.ui(render_fn))

    # ── Multi-filter modal ───────────────────────────────────────────────────

    @reactive.effect
    @reactive.event(input[f"{prefix}_multi_filter_btn"])
    def _open_multi_filter_modal():
        df = active_data()
        if df is None or df.empty:
            return

        compound_choices = sorted(df["compound"].dropna().unique().tolist())
        compound_current = resolve_selection(input, f"{prefix}_compound", compound_choices)

        indication_choices = sorted(df["indication"].dropna().unique().tolist())
        indication_current = resolve_selection(input, f"{prefix}_indication", indication_choices)

        phase_choices = sorted(df["phases"].dropna().unique().tolist())
        phase_current = resolve_selection(input, f"{prefix}_phase", phase_choices)

        modal_header = ui.div(
            ui.tags.h4("Apply Multiple Filters", class_="modal-title"),
            ui.tags.button(
                type="button", class_="btn-close",
                **{"data-bs-dismiss": "modal", "aria-label": "Close"},
            ),
            class_="modal-header",
        )

        modal_body = ui.TagList(
            ui.tags.small("Ctrl+Click to select only one item in each field.",
                          class_="d-block mb-1 text-muted"),
            ui.div(
                ui.div(
                    ui.input_checkbox_group(
                        f"{prefix}_mf_compound", "Compound:",
                        choices=compound_choices, selected=compound_current,
                    ),
                    class_="col-md-6",
                ),
                ui.div(
                    ui.input_checkbox_group(
                        f"{prefix}_mf_phase", "Phase:",
                        choices=phase_choices, selected=phase_current,
                    ),
                    class_="col-md-6",
                ),
                class_="row",
            ),
            ui.input_checkbox_group(
                f"{prefix}_mf_indication", "Indication:",
                choices=indication_choices, selected=indication_current,
            ),
        )

        m = ui.modal(
            modal_header,
            modal_body,
            title=None,
            size="l",
            footer=ui.div(
                ui.input_action_button(
                    f"{prefix}_mf_apply", "Apply",
                    class_="btn btn-primary me-2",
                ),
                ui.modal_button("Cancel", class_="btn btn-secondary"),
                class_="d-flex",
            ),
            easy_close=True,
        )
        ui.modal_show(m)

    @reactive.effect
    @reactive.event(input[f"{prefix}_mf_apply"])
    def _apply_multi_filters():
        for _col, suffix, _label in _FILTER_FIELDS:
            mf_id = f"{prefix}_mf_{suffix}"
            if input_exists(input, mf_id):
                selected = list(input[mf_id]())
                ui.update_checkbox_group(f"{prefix}_{suffix}", selected=selected)
        ui.modal_remove()


def apply_trial_filters(df, input, prefix):
    """Apply a trial-filters sidebar's compound/indication/phase selections
    (keyed by `prefix`) to `df`."""
    return filter_by_selections(df, input, [
        (col, f"{prefix}_{suffix}") for col, suffix, _ in _FILTER_FIELDS
    ])


# Shared "Sort rows by" choices used by Trial Information, Visualization, and
# Archive Checking sidebars.
SORT_CHOICES = {
    "start_date":              "Start Date",
    "primary_completion_date": "Primary Completion Date",
    "completion_date":         "Completion Date",
    "phases":                  "Phase",
}


def filter_header(prefix):
    """Shared 'TRIAL FILTERS' sidebar heading with the Ctrl+Click hint and
    an 'Apply Multiple Filters' button that opens a bulk-selection modal."""
    return ui.div(
        ui.input_action_button(
            f"{prefix}_multi_filter_btn", "Apply Multiple Filters",
            class_="btn btn-sm btn-secondary mb-3 w-80",
        ),
        ui.h6("TRIAL FILTERS", class_="fs-6 fw-bold"),
        ui.tags.small("Ctrl+Click to select only one item in each field.",
                      class_="d-block m-0 text-muted"),
    )


def filter_fields_ui(prefix):
    """The filter-header + compound/indication/phase output placeholders,
    keyed by `prefix`, without a sort control or sidebar wrapper. Used by
    tabs (e.g. Visualization) that assemble their own custom sidebar shape."""
    return [
        filter_header(prefix),
        ui.output_ui(f"{prefix}_compound_ui"),
        ui.output_ui(f"{prefix}_indication_ui"),
        ui.output_ui(f"{prefix}_phase_ui"),
    ]


def filter_sort_sidebar(prefix):
    """Shared compound/indication/phase filter + sort-by sidebar, keyed by
    `prefix` (e.g. "ti" or "chk") for its output/input ids. Used by the Trial
    Information tab and the Archive Checking tab, which render an identical
    sidebar shape."""
    return ui.sidebar(
        *filter_fields_ui(prefix),
        ui.hr(class_="my-1"),
        ui.h6("SORT", class_="fs-6 fw-bold"),
        ui.input_select(
            f"{prefix}_sort_by", "Sort rows by:",
            choices=SORT_CHOICES,
            selected="start_date",
        ),
        width="280px",
        id=f"{prefix}_sidebar",
    )
