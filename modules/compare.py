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

from utils import read_uploaded_csv


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
                               style="font-size:.8rem; color:#888; margin-top:.35rem; min-height:1.1rem;"),
                        style="text-align:center; padding:.5rem;",
                    ),
                ),
                ui.card(
                    ui.card_header("Download Processed Data"),
                    ui.div(
                        ui.p(
                            "Download the current processed dataset (API or uploaded) as CSV.",
                            style="font-size:.85rem; color:#888; margin-bottom:1rem;",
                        ),
                        ui.download_button(
                            "download_processed", "Download CSV",
                            style=(
                                "background:#1a1a2e; color:#fff; border:none;"
                                " padding:.6rem 1.5rem; border-radius:4px; cursor:pointer;"
                            ),
                        ),
                        style="text-align:center; padding:.5rem;",
                    ),
                ),
                col_widths=[6, 6],
            ),
            ui.layout_columns(
                ui.card(
                    ui.card_header("Uploaded Data"),
                    ui.div(ui.p("Uploaded dataset will render here.", style="color:#aaa;"),
                           style="height:45vh; display:flex; align-items:center; justify-content:center;"),
                ),
                ui.card(
                    ui.card_header("API / Current Query Data"),
                    ui.div(ui.p("API query results will render here.", style="color:#aaa;"),
                           style="height:45vh; display:flex; align-items:center; justify-content:center;"),
                ),
                col_widths=[6, 6],
            ),
            style="margin:1rem;",
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
        buf = io.StringIO()
        df.to_csv(buf, index=False)
        yield buf.getvalue()
