"""
modules/compare.py
──────────────────
Compare tab — UI and server logic.

Owns:
  UI:     compare_ui — upload box + download box side by side
  Server: compare_upload_status, download_processed handler
"""

import io

import pandas as pd
from shiny import render, ui

from core.utils import read_uploaded_csv


def compare_ui():
    return ui.nav_panel(
        "Compare",
        ui.div(
            ui.layout_columns(
                ui.card(
                    ui.card_header("Upload Dataset for Comparison"),
                    ui.div(
                        ui.input_file("upload_compare", None, accept=".csv",
                                      button_label="Choose CSV", multiple=False),
                        ui.div(ui.output_text("compare_upload_status"),
                               class_="text-muted small mt-1",
                               style="min-height:1.1rem;"),
                        class_="text-center p-2",
                    ),
                ),
                ui.card(
                    ui.card_header("Download Processed Data"),
                    ui.div(
                        ui.p(
                            "Download the current processed dataset (API or uploaded) as CSV.",
                            class_="text-muted small mb-3",
                        ),
                        ui.download_button(
                            "download_processed", "Download CSV",
                            class_="btn btn-dark",
                        ),
                        class_="text-center p-2",
                    ),
                ),
                col_widths=[6, 6],
            ),
            ui.layout_columns(
                ui.card(
                    ui.card_header("Uploaded Data"),
                    ui.div(ui.p("Uploaded dataset will render here.", class_="text-muted"),
                           class_="d-flex align-items-center justify-content-center",
                           style="height:45vh;"),
                ),
                ui.card(
                    ui.card_header("API / Current Query Data"),
                    ui.div(ui.p("API query results will render here.", class_="text-muted"),
                           class_="d-flex align-items-center justify-content-center",
                           style="height:45vh;"),
                ),
                col_widths=[6, 6],
            ),
            class_="m-3",
        ),
    )


def compare_server(input, output, session, active_data, compare_data, log_fn):

    @output
    @render.text
    def compare_upload_status():
        f = input.upload_compare()
        if f is None:
            return ""
        name = f[0]["name"]
        path = f[0]["datapath"]
        try:
            df = read_uploaded_csv(path)
            compare_data.set(df)
            log_fn(f"Comparison file {name}: {len(df)} rows × {len(df.columns)} columns", level="ok")
            return f"✓  {name}  ({len(df):,} rows)"
        except Exception as e:
            log_fn(f"Error reading {name}: {e}", level="error")
            return f"⚠  Could not read {name}"

    @render.download(filename="processed_data.csv")
    def download_processed():
        df = active_data()
        if df is None or (isinstance(df, pd.DataFrame) and df.empty):
            yield ""
            return
        df = df.copy()
        date_cols = [c for c in ("start_date", "primary_completion_date", "completion_date") if c in df.columns]
        for col in date_cols:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.strftime("%Y-%m-%d")
        buf = io.BytesIO()
        df.to_csv(buf, index=False, encoding="utf-8-sig")
        yield buf.getvalue()
