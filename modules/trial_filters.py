"""
modules/trial_filters.py
─────────────────────────
Shared "TRIAL FILTERS" sidebar (Compound / Indication / Phase checkboxes +
"Sort rows by") and its server-side wiring. Reused by the Trial Information,
Visualization, and Archive Checking tabs, keyed by a per-tab `prefix`
("ti", "viz", "chk") for input/output ids.
"""

from shiny import render, ui


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


def register_trial_filters(output, prefix, active_data):
    """Register the `{prefix}_compound_ui`/`_indication_ui`/`_phase_ui` render
    functions for a trial-filters sidebar keyed by `prefix`."""
    for col, suffix, label in _FILTER_FIELDS:
        render_fn = _bind_filter_renderer(active_data, col, f"{prefix}_{suffix}", label)
        output(id=f"{prefix}_{suffix}_ui", suspend_when_hidden=False)(render.ui(render_fn))


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


def filter_header():
    """Shared 'TRIAL FILTERS' sidebar heading with the Ctrl+Click hint."""
    return ui.div(
        ui.h6("TRIAL FILTERS", class_="fs-6 fw-bold"),
        ui.tags.small("Ctrl+Click to select only one item.",
                      class_="d-block m-0 text-muted"),
    )


def filter_fields_ui(prefix):
    """The filter-header + compound/indication/phase output placeholders,
    keyed by `prefix`, without a sort control or sidebar wrapper. Used by
    tabs (e.g. Visualization) that assemble their own custom sidebar shape."""
    return [
        filter_header(),
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
