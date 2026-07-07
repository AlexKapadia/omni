"""Shared visual language + dual-renderer helpers for the evidence figures.

Every figure is emitted twice from one data spec: a publication-quality PNG
(matplotlib, print-safe) and an interactive HTML (plotly). The HTMLs use plotly's
'directory' mode so a single shared plotly.min.js sits beside them — the figures/
folder stays self-contained and portable as a unit, without a multi-MB copy of
plotly.js inside every file.

Design: Omni's monochrome language — ink on paper. A restrained greyscale ramp
(black -> mid grey -> light grey) distinguishes series so the figures read the
same in colour, greyscale, and print. No chartjunk: thin axes, no gridlocked
noise, captions that state n and method.

Analysis-only module (matplotlib + plotly); never imported by the engine.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import plotly.graph_objects as go

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FIG_DIR = Path(__file__).resolve().parent

INK = "#0A0A0A"
GREY_DARK = "#3A3A3A"
GREY_MID = "#7A7A7A"
GREY_LIGHT = "#BFBFBF"
GREY_FAINT = "#E6E6E6"
PAPER = "#FFFFFF"
GREY_RAMP = (INK, GREY_MID, GREY_LIGHT, GREY_DARK)

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 11,
        "axes.edgecolor": GREY_MID,
        "axes.linewidth": 0.8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.titlesize": 13,
        "axes.titleweight": "bold",
        "axes.labelcolor": INK,
        "text.color": INK,
        "xtick.color": GREY_DARK,
        "ytick.color": GREY_DARK,
        "figure.facecolor": PAPER,
        "axes.facecolor": PAPER,
    }
)


def load(name: str) -> dict[str, Any]:
    """Load a committed evidence/data/*.json payload."""
    return json.loads((DATA_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _write_html(fig: go.Figure, stem: str) -> None:
    fig.update_layout(
        template="simple_white",
        font={"family": "DejaVu Sans, Arial, sans-serif", "color": INK, "size": 13},
        paper_bgcolor=PAPER,
        plot_bgcolor=PAPER,
        margin={"l": 70, "r": 30, "t": 70, "b": 90},
    )
    fig.write_html(
        FIG_DIR / f"{stem}.html",
        include_plotlyjs="directory",
        full_html=True,
        config={"displayModeBar": True, "responsive": True},
    )


def _finish_png(fig: plt.Figure, stem: str, caption: str) -> None:
    # Reserve bottom space for the (wrapped) caption so it never collides with the
    # x-axis labels; a fixed layout beats bbox='tight' here, which crops the margin.
    fig.subplots_adjust(bottom=0.26, top=0.90)
    fig.text(0.5, 0.03, caption, ha="center", va="bottom", fontsize=8, color=GREY_MID, wrap=True)
    fig.savefig(FIG_DIR / f"{stem}.png", dpi=200, facecolor=PAPER)
    plt.close(fig)


def dual_grouped_bar(
    stem: str,
    title: str,
    y_label: str,
    categories: Sequence[str],
    series: Sequence[tuple[str, Sequence[float], Sequence[float] | None]],
    caption: str,
    y_range: tuple[float, float] | None = None,
) -> None:
    """Grouped bars with optional symmetric error bars (95% CI half-widths)."""
    n_series = len(series)
    width = 0.8 / n_series
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    x = range(len(categories))
    for i, (label, values, errors) in enumerate(series):
        offsets = [xi + (i - (n_series - 1) / 2) * width for xi in x]
        ax.bar(
            offsets, values, width=width * 0.92, label=label,
            color=GREY_RAMP[i % len(GREY_RAMP)], edgecolor=INK, linewidth=0.6,
            yerr=errors, capsize=3, error_kw={"ecolor": INK, "elinewidth": 0.9},
        )
    ax.set_xticks(list(x))
    ax.set_xticklabels(categories)
    ax.set_ylabel(y_label)
    ax.set_title(title)
    if y_range:
        ax.set_ylim(*y_range)
    if n_series > 1:
        # Legend outside the plot area so it never overlaps the bars.
        ax.legend(frameon=False, fontsize=9, loc="upper left", bbox_to_anchor=(1.01, 1.0))
        fig.subplots_adjust(right=0.82)
    ax.grid(axis="y", color=GREY_FAINT, linewidth=0.7)
    ax.set_axisbelow(True)
    _finish_png(fig, stem, caption)

    pfig = go.Figure()
    for i, (label, values, errors) in enumerate(series):
        err = {"type": "data", "array": list(errors), "visible": True} if errors else None
        pfig.add_bar(
            x=list(categories), y=list(values), name=label,
            marker_color=GREY_RAMP[i % len(GREY_RAMP)],
            marker_line_color=INK, marker_line_width=0.6, error_y=err,
        )
    pfig.update_layout(title=title, yaxis_title=y_label, barmode="group")
    if y_range:
        pfig.update_yaxes(range=list(y_range))
    _write_html(pfig, stem)


def dual_histogram(
    stem: str,
    title: str,
    x_label: str,
    samples: Sequence[float],
    markers: Sequence[tuple[str, float]],
    caption: str,
    bins: int = 40,
) -> None:
    """Latency-style histogram with vertical percentile marker lines."""
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    ax.hist(samples, bins=bins, color=GREY_LIGHT, edgecolor=GREY_DARK, linewidth=0.5)
    ymax = ax.get_ylim()[1]
    for i, (name, value) in enumerate(markers):
        ax.axvline(value, color=INK, linestyle=(0, (4, 2)), linewidth=1.1)
        ax.text(value, ymax * (0.95 - 0.08 * i), f" {name}={value:.2f}", color=INK, fontsize=9)
    ax.set_xlabel(x_label)
    ax.set_ylabel("count")
    ax.set_title(title)
    ax.grid(axis="y", color=GREY_FAINT, linewidth=0.7)
    ax.set_axisbelow(True)
    _finish_png(fig, stem, caption)

    pfig = go.Figure()
    pfig.add_histogram(x=list(samples), nbinsx=bins, marker_color=GREY_LIGHT,
                       marker_line_color=GREY_DARK, marker_line_width=0.5, name="samples")
    for name, value in markers:
        pfig.add_vline(x=value, line_dash="dash", line_color=INK,
                       annotation_text=f"{name}={value:.2f}", annotation_position="top")
    pfig.update_layout(title=title, xaxis_title=x_label, yaxis_title="count")
    _write_html(pfig, stem)


def dual_scaling(
    stem: str,
    title: str,
    x: Sequence[float],
    y: Sequence[float],
    y_low: Sequence[float],
    y_high: Sequence[float],
    references: Sequence[tuple[str, Sequence[float]]],
    caption: str,
) -> None:
    """Latency-vs-size curve on a log-x axis with a CI band and reference lines."""
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    ax.fill_between(x, y_low, y_high, color=GREY_FAINT, label="95% CI")
    ax.plot(x, y, color=INK, marker="o", markersize=5, linewidth=1.6, label="measured p50")
    dashes = [(0, (5, 2)), (0, (1, 1.5))]
    for i, (label, values) in enumerate(references):
        ax.plot(x, values, color=GREY_MID, linestyle=dashes[i % len(dashes)],
                linewidth=1.1, label=label)
    ax.set_xscale("log")
    ax.set_xlabel("notes indexed (log scale)")
    ax.set_ylabel("retrieval latency (ms)")
    ax.set_title(title)
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    ax.grid(color=GREY_FAINT, linewidth=0.7)
    ax.set_axisbelow(True)
    _finish_png(fig, stem, caption)

    pfig = go.Figure()
    pfig.add_scatter(x=list(x), y=list(y_high), mode="lines", line={"width": 0},
                     showlegend=False, hoverinfo="skip")
    pfig.add_scatter(x=list(x), y=list(y_low), mode="lines", fill="tonexty",
                     fillcolor="rgba(180,180,180,0.3)", line={"width": 0}, name="95% CI")
    pfig.add_scatter(x=list(x), y=list(y), mode="lines+markers", line={"color": INK},
                     name="measured p50")
    for label, values in references:
        pfig.add_scatter(x=list(x), y=list(values), mode="lines",
                         line={"color": GREY_MID, "dash": "dash"}, name=label)
    pfig.update_xaxes(type="log", title="notes indexed (log scale)")
    pfig.update_layout(title=title, yaxis_title="retrieval latency (ms)")
    _write_html(pfig, stem)


def dual_heatmap(
    stem: str,
    title: str,
    matrix: Sequence[Sequence[float]],
    x_labels: Sequence[str],
    y_labels: Sequence[str],
    caption: str,
) -> None:
    """2x2-style confusion heatmap in greyscale with value annotations."""
    fig, ax = plt.subplots(figsize=(6.0, 4.6))
    im = ax.imshow(matrix, cmap="Greys", aspect="auto")
    ax.set_xticks(range(len(x_labels)))
    ax.set_xticklabels(x_labels)
    ax.set_yticks(range(len(y_labels)))
    ax.set_yticklabels(y_labels)
    vmax = max(max(row) for row in matrix) or 1
    for r, row in enumerate(matrix):
        for c, value in enumerate(row):
            ax.text(c, r, f"{int(value)}", ha="center", va="center",
                    color=PAPER if value > vmax * 0.5 else INK, fontsize=13, fontweight="bold")
    ax.set_title(title)
    fig.colorbar(im, ax=ax, shrink=0.8, label="count")
    fig.subplots_adjust(left=0.22)  # room for the actual-class row labels
    _finish_png(fig, stem, caption)

    pfig = go.Figure(
        go.Heatmap(z=list(matrix), x=list(x_labels), y=list(y_labels), colorscale="Greys",
                   showscale=True, text=[[str(int(v)) for v in row] for row in matrix],
                   texttemplate="%{text}")
    )
    pfig.update_layout(title=title)
    _write_html(pfig, stem)
