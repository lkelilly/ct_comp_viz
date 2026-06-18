"""
modules/viz.py
──────────────
Visualization tab — Plotly Gantt-style timeline chart.

"""

import pandas as pd
import plotly.graph_objects as go
from shiny import reactive, render, ui

MAX_VIZ_TRIALS = 300

# ── Enrollment bucket thresholds ─────────────────────────────────────────────

_ENROLLMENT_BUCKETS = [
    (None, 100,   "< 100",         4),
    (100,  500,   "100 to 500",    8),
    (500,  1000,  "500 to 1000",   12),
    (1000, 5000,  "1000 to 5000",  18),
    (5000, None,  "≥ 5000",        26),
]

def _enrollment_label(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "< 100"
    for lo, hi, label, _ in _ENROLLMENT_BUCKETS:
        if (lo is None or n >= lo) and (hi is None or n < hi):
            return label

def _enrollment_linewidth(label, multiplier=1.0):
    for _, _, lbl, width in _ENROLLMENT_BUCKETS:
        if lbl == label:
            return width * multiplier
    return 8 * multiplier


# ── Color palette for indications ────────────────────────────────────────────

_INDICATION_COLORS = [
    "#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3",
    "#937860", "#DA8BC3", "#8C8C8C", "#CCB974", "#64B5CD",
    "#2D6A4F", "#B5E48C", "#F4A261", "#E76F51", "#264653",
]


_COL_LABELS = {"indication": "Indication", "compound": "Compound", "phases": "Phase"}


# ── UI ────────────────────────────────────────────────────────────────────────

def viz_ui():
    sidebar = ui.sidebar(
        ui.h6(
            "SORTING OPTIONS",
            style="letter-spacing:.08em; color:#333; font-size:.85rem; font-weight:700;",
        ),
        ui.input_radio_buttons(
            "viz_group_by", "Group rows by:",
            choices={"compound": "Compound", "indication": "Indication", "phases": "Phase"},
            selected="compound",
        ),
        ui.input_radio_buttons(
            "viz_color_by", "Color bars by:",
            choices={"indication": "Indication", "compound": "Compound", "phases": "Phase"},
            selected="indication",
        ),
        ui.input_select(
            "viz_sort_by", "Sort rows by:",
            choices={
                "start_date":              "Start Date",
                "primary_completion_date": "Primary Completion Date",
                "completion_date":         "Completion Date",
                "phases":                  "Phase",
            },
            selected="start_date",
        ),

        ui.hr(style="margin:.4rem 0;"),
        ui.h6(
            "TRIAL FILTERS",
            style="letter-spacing:.08em; color:#333; margin-bottom:.5rem; font-size:.85rem; font-weight:700;",
        ),
        ui.output_ui("viz_compound_ui"),
        ui.output_ui("viz_indication_ui"),
        ui.output_ui("viz_phase_ui"),

        ui.hr(style="margin:.4rem 0;"),
        ui.h6(
            "DISPLAY OPTIONS",
            style="letter-spacing:.08em; color:#333; margin-bottom:.5rem; font-size:.85rem; font-weight:700;",
        ),
        ui.input_radio_buttons(
            "viz_reflect_size", "Bar width reflects enrollment:",
            choices={"yes": "Yes", "no": "No"},
            selected="yes",
        ),
        ui.input_radio_buttons(
            "viz_mark_primary", "Mark primary completion date:",
            choices={"yes": "Yes", "no": "No"},
            selected="yes",
        ),
        ui.input_radio_buttons(
            "viz_mark_acronym", "Show acronym label:",
            choices={"yes": "Yes", "no": "No"},
            selected="yes",
        ),
        ui.input_slider("viz_bar_width",   "Bar width multiplier (%):",  20, 300, 100, step=10),
        ui.input_slider("viz_font_size",   "Font size multiplier (%):",  50, 200, 100, step=10),
        ui.input_slider("viz_fig_height",  "Figure height multiplier (%):", 20, 500, 100, step=10),

        width="280px",
        style="overflow-y:hidden;",
        id="viz_sidebar",
    )

    return ui.nav_panel(
        "Visualization",
        ui.layout_sidebar(
            sidebar,
            ui.div(
                ui.output_ui("viz_notice"),
                ui.output_ui("viz_plot"),
                style="overflow-y:auto; overflow-x:auto; padding:.5rem; width:100%;",
            ),
        ),
    )


# ── Server ────────────────────────────────────────────────────────────────────

def viz_server(input, output, session, active_data):

    # ── Dynamic filter widgets ────────────────────────────────────────────────

    @output
    @render.ui
    def viz_compound_ui():
        df = active_data()
        if df is None or df.empty:
            return ui.p("No data loaded.", style="color:#aaa; font-size:1rem;")
        choices = sorted(df["compound"].dropna().unique().tolist())
        return ui.input_checkbox_group(
            "viz_compound", "Compound:",
            choices=choices,
            selected=choices,
        )

    @output
    @render.ui
    def viz_indication_ui():
        df = active_data()
        if df is None or df.empty:
            return ui.div()
        choices = sorted(df["indication"].dropna().unique().tolist())
        return ui.input_checkbox_group(
            "viz_indication", "Indication:",
            choices=choices,
            selected=choices,
        )

    @output
    @render.ui
    def viz_phase_ui():
        df = active_data()
        if df is None or df.empty:
            return ui.div()
        choices = sorted(df["phases"].dropna().unique().tolist())
        return ui.input_checkbox_group(
            "viz_phase", "Phase:",
            choices=choices,
            selected=choices,
        )

    # ── Filtered + sorted data ────────────────────────────────────────────────

    @reactive.calc
    def _viz_filtered():
        df = active_data()
        if df is None or df.empty:
            return pd.DataFrame(), 0
        compounds   = list(input.viz_compound())   if _input_exists(input, "viz_compound")   else []
        indications = list(input.viz_indication())  if _input_exists(input, "viz_indication") else []
        phases      = list(input.viz_phase())       if _input_exists(input, "viz_phase")      else []
        if compounds:
            df = df[df["compound"].isin(compounds)]
        if indications:
            df = df[df["indication"].isin(indications)]
        if phases:
            df = df[df["phases"].isin(phases)]
        before = len(df)
        df = df.dropna(subset=["start_date", "completion_date"])
        df["start_date"]      = pd.to_datetime(df["start_date"])
        df["completion_date"] = pd.to_datetime(df["completion_date"])
        df = df[df["completion_date"] > df["start_date"]]
        return df, before

    @reactive.calc
    def viz_data():
        df, _ = _viz_filtered()
        if df.empty:
            return df
        sort_by  = input.viz_sort_by()
        group_by = input.viz_group_by()
        sort_cols = [group_by]
        if sort_by != group_by and sort_by in (
            "start_date", "completion_date", "primary_completion_date", "indication", "phases"
        ):
            sort_cols.append(sort_by)
        sort_cols.append("start_date")
        seen_cols: set = set()
        sort_cols = [c for c in sort_cols if not (c in seen_cols or seen_cols.add(c))]
        valid_sort = [c for c in sort_cols if c in df.columns]
        return df.sort_values(valid_sort).reset_index(drop=True)

    @reactive.calc
    def viz_dropped_count():
        df, before = _viz_filtered()
        return before - len(df)

    # ── Plot ──────────────────────────────────────────────────────────────────

    @output
    @render.ui
    def viz_notice():
        dropped = viz_dropped_count()
        if dropped <= 0:
            return ui.div()
        return ui.div(
            ui.tags.i(class_="bi bi-info-circle", style="margin-right:.4rem;"),
            f"{dropped:,} trial(s) in `Trial Information` not displayed due to missing or invalid start/end date",
            style=(
                "background:#fff8e1; border:1px #ffe082; border-radius:8px;"
                " padding:.5rem .75rem; font-size:0.85rem; color:#7b6000; margin:0 1rem .5rem 1rem;"
            ),
        )

    @output
    @render.ui
    def viz_plot():
        df = viz_data()
        if df.empty:
            return ui.div(
                ui.p("No data to display. Load data and adjust filters.",
                     style="color:#aaa;"),
                style=(
                    "height:40vh; display:flex; align-items:center; justify-content:center;"
                    " border:2px #ddd; border-radius:8px; margin:1rem;"
                ),
            )

        n = len(df)
        if n > MAX_VIZ_TRIALS:
            return ui.div(
                ui.h5("Too many trials to render! :-(",
                      style="color:#c0392b; margin-bottom:.5rem;"),
                ui.p(f"{n:,} trials match your current filters."),
                ui.p(
                    f"The visualization supports up to {MAX_VIZ_TRIALS:,} at a time. "
                    "Please narrow your search using the filters on the left (compound, indication, etc.).",
                    style="color:#555; max-width:520px; text-align:center;",
                ),
                style=(
                    "height:40vh; display:flex; flex-direction:column; align-items:center;"
                    " justify-content:center; border:2px #e74c3c; border-radius:8px;"
                    " margin:1rem; padding:.5rem .75rem; background:#fff8f8;"
                ),
            )

        with ui.Progress(min=0, max=3) as p:
            p.set(0, message="Building visualization", detail="Preparing data...")

            bar_w_mult   = input.viz_bar_width()  / 100
            font_mult    = input.viz_font_size()  / 100
            height_mult  = input.viz_fig_height() / 100
            color_by     = input.viz_color_by()
            group_by     = input.viz_group_by()
            reflect_size = input.viz_reflect_size() == "yes"
            mark_primary = input.viz_mark_primary() == "yes"
            mark_acronym = input.viz_mark_acronym() == "yes"

            group_col = group_by

            # Assign stable colors to the chosen color-by column
            color_col  = color_by
            categories = sorted(df[color_col].dropna().unique().tolist())
            color_map  = {cat: _INDICATION_COLORS[i % len(_INDICATION_COLORS)]
                          for i, cat in enumerate(categories)}

            # ── Build integer y-positions + group axis labels ─────────────────────
            y_pos       = {}   # nct → int
            y_cursor    = 0
            group_items = []   # (label, group_start, group_end)

            groups = df[group_col].dropna().unique().tolist()
            for grp_val in groups:
                sub         = df[df[group_col] == grp_val]
                group_start = y_cursor
                for nct in sub["nct_number"]:
                    if nct not in y_pos:
                        y_pos[nct] = y_cursor
                        y_cursor  += 1
                group_end = y_cursor
                group_items.append((grp_val, group_start, group_end))

            total_rows = y_cursor
            row_px = 32 * bar_w_mult
            n_legend = 0
            if mark_primary:
                n_legend += 1
            n_legend += 1
            n_legend += len(categories)
            if reflect_size:
                n_legend += 1 + len(_ENROLLMENT_BUCKETS)
            legend_px = int(n_legend * 22 * font_mult + 60)   # ~22px per row + padding

            data_px = int(total_rows * row_px * height_mult)
            fig_height = max(300, data_px, legend_px)

            p.set(1, message="Building visualization", detail="Drawing chart...")

            fig = go.Figure()

            # ── Background bands + group column annotations ───────────────────────
            for idx, (grp_val, group_start, group_end) in enumerate(group_items):
                fig.add_hrect(
                    y0=group_start - 0.5,
                    y1=group_end   - 0.5,
                    layer="below",
                    line_width=0,
                )
                mid = (group_start + group_end - 1) / 2
                fig.add_annotation(
                    x=-0.2, y=mid,
                    xref="paper", yref="y",
                    text=f"<b>{grp_val}</b>",
                    showarrow=False,
                    xanchor="right",
                    yanchor="middle",
                    font=dict(size=11 * font_mult, color="#333"),
                )

            for _, _, group_end in group_items[:-1]:
                fig.add_hrect(
                    y0=group_end - 0.62,
                    y1=group_end - 0.38,
                    fillcolor="white",
                    layer="below",
                    line_width=0,
                )
                fig.add_hline(y=group_end - 0.5, line=dict(color="#cccccc", width=1))

            group_label = _COL_LABELS.get(group_col, group_col.capitalize())
            fig.add_annotation(
                x=-0.12, y=-0.7,
                xref="paper", yref="y",
                text=f"Group by: <b>{group_label}</b>",
                showarrow=False,
                xanchor="right",
                yanchor="bottom",
                font=dict(size=12 * font_mult, color="black"),
            )

            p.set(2, message="Building visualization", detail="Adding trial bands...")

            # ── Study bars ────────────────────────────────────────────────────────
            if mark_primary:
                fig.add_trace(go.Scatter(
                    x=[None], y=[None], mode="markers",
                    marker=dict(symbol="triangle-up", size=10 * font_mult, color="black"),
                    name="Primary Completion Date",
                    legendgroup="__primary__",
                    showlegend=True,
                    legendrank=1,
                ))

            color_section_title = _COL_LABELS.get(color_by, color_by.capitalize() if color_by else "")
            fig.add_trace(go.Scatter(
                x=[None], y=[None], mode="markers",
                marker=dict(size=0, opacity=0),
                name=f"Color by: <b>{_wrap_legend_name(color_section_title)}</b>",
                legendgroup="__header_colors__",
                showlegend=True,
                legendrank=99,
            ))

            for i, cat in enumerate(categories):
                fig.add_trace(go.Scatter(
                    x=[None], y=[None], mode="lines",
                    line=dict(color=color_map[cat], width=8),
                    name=_wrap_legend_name(cat),
                    legendgroup=cat,
                    showlegend=True,
                    legendrank=100 + i,
                ))

            if reflect_size:
                fig.add_trace(go.Scatter(
                    x=[None], y=[None], mode="markers",
                    marker=dict(size=0, opacity=0),
                    name=f"<b>Enrollment Size</b>",
                    legendgroup="__header_enroll__",
                    showlegend=True,
                    legendrank=199,
                ))
                for i, (_, _, label, width) in enumerate(_ENROLLMENT_BUCKETS):
                    fig.add_trace(go.Scatter(
                        x=[None], y=[None], mode="lines",
                        line=dict(color="#888888", width=width * bar_w_mult),
                        name=label,
                        legendgroup=f"__enroll_{label}__",
                        showlegend=True,
                        legendrank=200 + i,
                    ))

            for _, trial in df.iterrows():
                nct       = trial.get("nct_number", "")
                y_val     = y_pos.get(nct, 0)
                cat       = trial.get(color_col, "Other") or "Other"
                color     = color_map.get(cat, "#888888")
                acronym   = trial.get("acronym", nct)
                title     = str(trial.get("study_title", ""))[:120]
                phase     = trial.get("phases", "")
                indication = trial.get("indication", "")
                status    = trial.get("study_status", "")
                enroll    = trial.get("enrollment", None)
                t_start   = trial.get("start_date")
                t_end     = trial.get("completion_date")
                t_primary = trial.get("primary_completion_date")

                enroll_label = _enrollment_label(enroll)
                lw = _enrollment_linewidth(enroll_label, bar_w_mult) if reflect_size else 12 * bar_w_mult

                hover = (
                    f"<b>{nct}</b><br>"
                    f"Acronym: {acronym}<br>"
                    f"Title: {title}{'…' if len(str(trial.get('study_title', ''))) > 120 else ''}<br>"
                    f"Compound: {trial.get('compound', '')}<br>"
                    f"Indication: {indication}<br>"
                    f"Phase: {phase}<br>"
                    f"Status: {status}<br>"
                    f"Enrollment: {int(enroll) if pd.notna(enroll) else 'N/A'}<br>"
                    f"Start: {_fmt_date(t_start)}<br>"
                    f"Primary completion: {_fmt_date(t_primary)}<br>"
                    f"Completion: {_fmt_date(t_end)}"
                )

                _pts = pd.date_range(t_start, t_end, periods=20).tolist() if pd.notna(t_start) and pd.notna(t_end) else [t_start, t_end]
                fig.add_trace(go.Scatter(
                    x=_pts,
                    y=[y_val] * len(_pts),
                    mode="lines",
                    line=dict(color=color, width=lw),
                    name=cat,
                    legendgroup=cat,
                    showlegend=False,
                    hovertemplate=hover + "<extra></extra>",
                ))

                if mark_primary and pd.notna(t_primary):
                    fig.add_trace(go.Scatter(
                        x=[t_primary],
                        y=[y_val],
                        mode="markers",
                        marker=dict(symbol="triangle-up", size=10 * font_mult, color="black"),
                        name="Primary Completion",
                        legendgroup="__primary__",
                        showlegend=False,
                        hovertemplate=f"Primary completion: {_fmt_date(t_primary)}<extra></extra>",
                    ))

                # Right-side label: acronym only (if enabled and differs from NCT)
                if mark_acronym and acronym != nct:
                    fig.add_annotation(
                        x=t_end,
                        y=y_val,
                        text=f"  {acronym}",
                        showarrow=False,
                        xanchor="left",
                        font=dict(size=11 * font_mult, color="#333"),
                    )

            p.set(3, message="Building visualization", detail="Adding details...")

            base_font = 12 * font_mult
            fig.update_layout(
                height=fig_height,
                autosize=True,
                font=dict(size=base_font),
                hovermode="closest",
                legend=dict(
                    orientation="v",
                    x=1.05,
                    y=1,
                    yanchor="top",
                    font=dict(size=base_font),
                    entrywidth=170,
                    entrywidthmode="pixels",
                ),
                margin=dict(l=260, r=220, t=50, b=60),
                plot_bgcolor="#ffffff",
                paper_bgcolor="#ffffff",
            )
            date_min = pd.to_datetime(df["start_date"]).min()
            date_max = pd.to_datetime(df["completion_date"]).max()
            year_span = (date_max - date_min).days / 365.25
            x_range = [
                (date_min - pd.DateOffset(months=6)).strftime("%Y-%m-%d"),
                (date_max + pd.DateOffset(months=6)).strftime("%Y-%m-%d"),
            ]
            x_dtick = "M60" if year_span > 30 else "M36" if year_span >= 24 else "M12"

            fig.update_xaxes(
                type="date",
                range=x_range,
                tickformat="%Y",
                dtick=x_dtick,
                tickangle=45,
                tickfont=dict(size=base_font),
                showgrid=True,
                gridcolor="#e0e0e0",
                gridwidth=1,
            )
            tick_vals = list(y_pos.values())
            tick_text = list(y_pos.keys())
            fig.update_yaxes(
                tickvals=tick_vals,
                ticktext=tick_text,
                tickfont=dict(size=base_font),
                showgrid=False,
                zeroline=False,
                autorange=False,
                range=[total_rows, -1.0],
                ticklabelstandoff=20,
            )
            p.set(3, message="Rendering", detail="This won't take too long...")
            html = fig.to_html(full_html=False, include_plotlyjs=False, config={"responsive": True})

        return ui.HTML(html)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _wrap_legend_name(text: str, max_chars: int = 20) -> str:
    words = str(text).split()
    lines, current = [], []
    length = 0
    for word in words:
        if current and length + 1 + len(word) > max_chars:
            lines.append(" ".join(current))
            current, length = [word], len(word)
        else:
            current.append(word)
            length += (1 if current else 0) + len(word)
    if current:
        lines.append(" ".join(current))
    return "<br>".join(lines)


def _fmt_date(d):
    if isinstance(d, str):
        if not d:
            return "N/A"
    elif pd.isna(d):
        return "N/A"
    try:
        return pd.Timestamp(d).strftime("%Y-%m-%d")
    except Exception:
        return str(d)


def _input_exists(input_obj, name):
    try:
        input_obj[name]()
        return True
    except Exception:
        return False
