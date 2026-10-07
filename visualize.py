"""
visualize.py — Generate all bibliometric charts
================================================
Produces publication-quality figures saved to OUTPUT_DIR.
"""

import json
import os
import pathlib
import sys
import collections
import math

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import matplotlib.cm as cm
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import config

def _out_dir() -> pathlib.Path:
    """Return current output dir — evaluated at call time so period overrides work."""
    p = pathlib.Path(config.OUTPUT_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p
    # Output dir created on demand by _out_dir()

# ── Style ─────────────────────────────────────────────────────────────────────
plt.rcParams.update({
    "figure.dpi":        150,
    "font.family":       "sans-serif",
    "font.sans-serif":   ["Arial"],
    "font.size":         8,
    "axes.titlesize":    9,
    "axes.labelsize":    8,
    "legend.fontsize":   7,
    "pdf.fonttype":      42,          # embed TrueType so text stays editable
    "ps.fonttype":       42,
    "axes.spines.top":   False,
    "axes.spines.right": False,
    "axes.grid":         True,
    "grid.alpha":        0.3,
    "figure.facecolor":  "white",
})

# Arial is required for every figure (house style).  Without it matplotlib would
# silently substitute another sans-serif, so fail loudly instead.
from matplotlib import font_manager as _fm
try:
    _fm.findfont("Arial", fallback_to_default=False)
except ValueError:
    raise SystemExit("Arial is not installed: install Arial (e.g. Microsoft core fonts) "
                     "and clear ~/.cache/matplotlib before drawing figures")

PALETTE = ["#2C6FAC", "#E05C1B", "#3A9E6B", "#9B59B6",
           "#E8A020", "#16A085", "#C0392B", "#2980B9"]


FIG_MAX_WIDTH_IN = getattr(config, "FIG_MAX_WIDTH_IN", 7.0)


def _cite_label(prefix: str = "Total citations") -> str:
    return f"{prefix} ({getattr(config, 'CITATION_SOURCE_LABEL', 'OpenAlex')})"


def _panel_letter(ax, letter: str):
    ax.text(-0.02, 1.04, letter, transform=ax.transAxes, fontsize=10, fontweight="bold",
            va="bottom", ha="right")


def _save(fig, name: str):
    # Replace extension with configured format
    fmt  = os.environ.get("BIB_FIGURE_FORMAT") or getattr(config, "FIGURE_FORMAT", "pdf")
    stem = pathlib.Path(name).stem
    fname = f"{stem}.{fmt}"
    path  = _out_dir() / fname
    w, h = fig.get_size_inches()
    if w > FIG_MAX_WIDTH_IN + 0.01:
        print(f"  [warn] {fname}: figure is {w:.1f} in wide; journal maximum is {FIG_MAX_WIDTH_IN} in")
    # Save at the declared figure size (no bbox expansion) so the page width
    # never exceeds the journal maximum; layout is packed first so tick labels
    # stay inside the canvas.
    try:
        if not fig.get_constrained_layout():
            fig.tight_layout()
    except Exception:  # noqa: BLE001
        pass
    kwargs = {"bbox_inches": None, "pad_inches": 0.02}
    # Raster formats need an explicit resolution. Journals require at least
    # 300 dpi for halftones and considerably more for line art, so allow the
    # value to be raised from the environment (BIB_FIGURE_DPI).
    if fmt in ("png", "jpg", "jpeg", "tif", "tiff"):
        kwargs["dpi"] = int(os.environ.get("BIB_FIGURE_DPI", "300"))
        if fmt in ("jpg", "jpeg"):
            kwargs["pil_kwargs"] = {"quality": 95}
        elif fmt in ("tif", "tiff"):
            # Uncompressed TIFF at 600 dpi runs to hundreds of MB per figure.
            # LZW is lossless and universally accepted by publishers.
            kwargs["pil_kwargs"] = {"compression": "tiff_lzw"}
    # PDF, EPS and SVG are vector — the dpi argument is ignored/irrelevant
    fig.savefig(path, **kwargs)
    plt.close(fig)
    print(f"  saved: {path.name}")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Temporal trends
# ─────────────────────────────────────────────────────────────────────────────

def plot_temporal(temporal: dict):
    """Fig 1. A: annual publications (bars) + 3-yr moving average (solid line)
    with total citations received by that year's papers on a right axis.
    B: cumulative publications."""
    years  = temporal["years"]
    counts = temporal["counts"]
    cumul  = temporal["cumulative"]
    mavg   = temporal["moving_avg"]
    cites  = temporal.get("citations") or []

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7, 6), sharex=True,
                                   gridspec_kw={"height_ratios": [3, 2]})
    fig.suptitle(f"{config.FIELD_LABEL.capitalize()} publications, "
                 f"{config.ALL_TIME_START}–{config.END_YEAR}", fontsize=10, fontweight="bold")

    b1 = ax1.bar(years, counts, color=PALETTE[0], alpha=0.75, label="Publications per year")
    l1, = ax1.plot(years, mavg, color=PALETTE[1], linewidth=2, marker="o", markersize=3,
                   label="3-year moving average")
    ax1.set_ylabel("Publications per year")
    handles = [b1, l1]
    if any(cites):
        ax1b = ax1.twinx()
        l2, = ax1b.plot(years, cites, color=PALETTE[2], linewidth=1.6, marker="s", markersize=3,
                        linestyle="-", label=_cite_label("Citations received by that year's papers"))
        ax1b.set_ylabel(_cite_label("Citations"), color=PALETTE[2])
        ax1b.tick_params(axis="y", colors=PALETTE[2])
        ax1b.spines["right"].set_visible(True)
        ax1b.grid(False)
        handles.append(l2)
    ax1.legend(handles, [h.get_label() for h in handles], loc="upper left")
    _panel_letter(ax1, "A")

    ax2.bar(years, cumul, color=PALETTE[3], alpha=0.65)
    ax2.set_ylabel("Cumulative publications")
    ax2.set_xlabel("Year")
    _panel_letter(ax2, "B")

    plt.tight_layout()
    _save(fig, "fig1_temporal_trends.pdf")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Top journals
# ─────────────────────────────────────────────────────────────────────────────

def plot_journals(journals: list[dict], top_n: int = None):
    top_n = top_n or config.TOP_N_JOURNALS
    top = journals[:top_n]
    labels = [r["abbr"] or r["journal"] for r in top]
    counts = [r["count"] for r in top]
    pcts   = [r["percentage"] for r in top]

    fig, ax = plt.subplots(figsize=(7, max(4.5, top_n * 0.28)))
    y = range(len(labels))
    bars = ax.barh(list(y), counts, color=PALETTE[0], alpha=0.8)
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=7.5)
    ax.invert_yaxis()
    ax.set_xlabel("Number of publications")
    ax.set_title(f"Top {top_n} journals publishing {config.FIELD_LABEL} research", fontweight="bold")

    for bar, pct in zip(bars, pcts):
        ax.text(bar.get_width() + counts[0] * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{pct:.1f}%", va="center", fontsize=8, color="gray")

    plt.tight_layout()
    _save(fig, "fig2_top_journals.pdf")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Top countries
# ─────────────────────────────────────────────────────────────────────────────

def plot_countries(countries: list[dict], top_n: int = 15):
    """Fig 3, 2×2: A volume, B total citations, C median citations per paper,
    D publications per million population."""
    top = [c for c in countries if c["country"] != "Unknown"][:top_n]
    labels  = [r["country"] for r in top]
    counts  = [r["count"] for r in top]
    cites   = [r.get("citations", 0) or 0 for r in top]
    medians = [r.get("citations_median") for r in top]
    percap  = [r.get("pubs_per_million") for r in top]
    has_cites = any(cites)
    has_percap = any(v is not None for v in percap)

    fig, axes = plt.subplots(2, 2, figsize=(7, 8.5))
    axes = axes.ravel()
    fig.suptitle(f"Top {top_n} first-author countries in {config.FIELD_LABEL} research",
                 fontsize=10, fontweight="bold")
    y = list(range(len(labels)))

    axes[0].barh(y, counts, color=PALETTE[0], alpha=0.85)
    axes[0].set_yticks(y); axes[0].set_yticklabels(labels, fontsize=7)
    axes[0].invert_yaxis(); axes[0].set_xlabel("Publications (first author)")
    axes[0].set_title("Publication volume"); _panel_letter(axes[0], "A")

    if has_cites:
        order = sorted(range(len(top)), key=lambda i: cites[i], reverse=True)
        axes[1].barh(y, [cites[i] for i in order], color=PALETTE[2], alpha=0.85)
        axes[1].set_yticks(y); axes[1].set_yticklabels([labels[i] for i in order], fontsize=7)
        axes[1].invert_yaxis(); axes[1].set_xlabel(_cite_label())
        axes[1].set_title("Total citations"); _panel_letter(axes[1], "B")

        vals = [m if m is not None else 0 for m in medians]
        order = sorted(range(len(top)), key=lambda i: vals[i], reverse=True)
        bars = axes[2].barh(y, [vals[i] for i in order], color=PALETTE[3], alpha=0.85)
        axes[2].set_yticks(y); axes[2].set_yticklabels([labels[i] for i in order], fontsize=7)
        axes[2].invert_yaxis(); axes[2].set_xlabel("Median citations per publication")
        axes[2].set_title("Median citations"); _panel_letter(axes[2], "C")
        for bar, i in zip(bars, order):
            axes[2].text(bar.get_width() + 0.3, bar.get_y() + bar.get_height() / 2,
                         f"{vals[i]:g}", va="center", fontsize=6)
    else:
        axes[1].axis("off"); axes[2].axis("off")

    if has_percap:
        # Panel D ranks per-capita output over ALL countries with at least
        # PER_CAPITA_MIN_PUBS first-author publications, not the top-N by volume
        min_pubs = getattr(config, "PER_CAPITA_MIN_PUBS", 20)
        elig = [c for c in countries if c["country"] != "Unknown" and c.get("pubs_per_million") is not None
                and c["count"] >= min_pubs]
        elig.sort(key=lambda c: c["pubs_per_million"], reverse=True)
        elig = elig[:top_n]
        pl = [c["country"] for c in elig]; pv = [c["pubs_per_million"] for c in elig]
        bars = axes[3].barh(list(range(len(pl))), pv, color=PALETTE[4], alpha=0.85)
        axes[3].set_yticks(list(range(len(pl)))); axes[3].set_yticklabels(pl, fontsize=7)
        axes[3].invert_yaxis(); axes[3].set_xlabel("Publications per million population")
        axes[3].set_title(f"Per-capita output (≥{min_pubs} publications)"); _panel_letter(axes[3], "D")
        for bar, v in zip(bars, pv):
            axes[3].text(bar.get_width() + 0.1, bar.get_y() + bar.get_height() / 2, f"{v:.1f}", va="center", fontsize=6)
    else:
        axes[3].axis("off")

    plt.tight_layout()
    _save(fig, "fig3_top_countries.pdf")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Top authors
# ─────────────────────────────────────────────────────────────────────────────

def plot_authors(authors: list[dict], top_n: int = 20):
    """Fig 4, 1×3: A publications (first/last overlaid), B total citations,
    C median citations per publication."""
    top    = authors[:top_n]
    labels = [r["author_id"] for r in top]
    pubs   = [r["pub_count"] for r in top]
    first  = [r["first_author_count"] for r in top]
    last   = [r.get("last_author_count", 0) or 0 for r in top]
    cites  = [r.get("citation_total", 0) or 0 for r in top]
    meds   = [r.get("citations_median") for r in top]
    has_cites = any(cites)
    ncols = 3 if has_cites else 1
    fig, axes = plt.subplots(1, ncols, figsize=(7, max(6, top_n * 0.36)))
    if ncols == 1:
        axes = [axes]
    fig.suptitle(f"Top {top_n} most productive authors in {config.FIELD_LABEL} research",
                 fontsize=10, fontweight="bold")
    y = np.arange(len(labels))

    axes[0].barh(y, pubs, color=PALETTE[0], alpha=0.75, label="All positions")
    axes[0].barh(y - 0.18, first, height=0.35, color=PALETTE[1], alpha=0.9, label="First author")
    axes[0].barh(y + 0.18, last, height=0.35, color=PALETTE[3], alpha=0.9, label="Last author")
    axes[0].set_yticks(y); axes[0].set_yticklabels(labels, fontsize=6.5)
    axes[0].invert_yaxis(); axes[0].set_xlabel("Publications")
    axes[0].set_title("Publications"); axes[0].legend(fontsize=6, loc="lower right")
    _panel_letter(axes[0], "A")

    if has_cites:
        order = sorted(range(len(top)), key=lambda i: cites[i], reverse=True)
        axes[1].barh(y, [cites[i] for i in order], color=PALETTE[2], alpha=0.85)
        axes[1].set_yticks(y); axes[1].set_yticklabels([labels[i] for i in order], fontsize=6.5)
        axes[1].invert_yaxis(); axes[1].set_xlabel(_cite_label())
        axes[1].set_title("Total citations"); _panel_letter(axes[1], "B")

        vals = [m if m is not None else 0 for m in meds]
        order = sorted(range(len(top)), key=lambda i: vals[i], reverse=True)
        bars = axes[2].barh(y, [vals[i] for i in order], color=PALETTE[3], alpha=0.85)
        axes[2].set_yticks(y); axes[2].set_yticklabels([labels[i] for i in order], fontsize=6.5)
        axes[2].invert_yaxis(); axes[2].set_xlabel("Median citations per publication")
        axes[2].set_title("Median citations"); _panel_letter(axes[2], "C")
        for bar, i in zip(bars, order):
            axes[2].text(bar.get_width() + 0.3, bar.get_y() + bar.get_height() / 2,
                         f"{vals[i]:.0f}", va="center", fontsize=5.5)

    plt.tight_layout()
    _save(fig, "fig4_top_authors.pdf")


# ─────────────────────────────────────────────────────────────────────────────
# 5. Keywords bubble chart
# ─────────────────────────────────────────────────────────────────────────────

def plot_keywords(kw_data: dict, top_n: int = None, title_suffix: str = ""):
    top_n = top_n or config.TOP_N_KEYWORDS
    freq = kw_data["freq"]
    top_kws = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:top_n]

    labels = [k for k, _ in top_kws]
    counts = [v for _, v in top_kws]

    fig, ax = plt.subplots(figsize=(7, max(5, top_n * 0.18)))
    y = range(len(labels))
    ax.barh(list(y), counts, color=PALETTE[3], alpha=0.75)
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=6.5)
    ax.invert_yaxis()
    ax.set_xlabel("Records carrying the term")
    src = kw_data.get("source", "")
    cov = (kw_data.get("coverage") or {}).get("overall_pct")
    sub = f" ({cov}% of records carry author keywords)" if (src == "author" and cov is not None) else ""
    kind = "author keywords" if src == "author" else ("MeSH terms" if "mesh" in title_suffix.lower() else "keywords")
    ax.set_title(f"Top {top_n} normalized {kind}{sub}", fontweight="bold", fontsize=9)
    plt.tight_layout()
    safe = title_suffix.replace("(","").replace(")","").replace(" ","_").lower()
    fname = f"fig5_{safe}.pdf" if title_suffix else "fig5_keywords.pdf"
    _save(fig, fname)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Publication type pie
# ─────────────────────────────────────────────────────────────────────────────

def plot_pubtypes(pub_types: dict, n_records: int = None):
    """Share of records carrying each PubMed publication type.  Types are
    non-exclusive (a record can be both a Journal Article and a Review), so the
    bars are independent percentages of all records and are not meant to sum
    to 100; a pie chart would imply otherwise.  Funding-support and language
    tags are not study designs and are left out."""
    keep = ["Journal Article", "Case Reports", "Comparative Study", "Review",
            "Letter", "Comment", "Observational Study", "Multicenter Study",
            "Randomized Controlled Trial", "Clinical Trial", "Systematic Review",
            "Meta-Analysis", "Editorial"]
    n = n_records or max(pub_types.values() or [1])
    rows = sorted(((pub_types.get(k, 0), k) for k in keep if pub_types.get(k)), reverse=True)
    fig, ax = plt.subplots(figsize=(7, 4.2))
    y = list(range(len(rows)))
    pct = [100 * v / n for v, _ in rows]
    ax.barh(y, pct, color=PALETTE[0], alpha=0.8)
    ax.set_yticks(y)
    ax.set_yticklabels([k for _, k in rows], fontsize=8)
    ax.invert_yaxis()
    for yi, (v, _), p in zip(y, rows, pct):
        ax.text(p + 0.8, yi, f"{v:,} ({p:.1f}%)", va="center", fontsize=7)
    ax.set_xlim(0, 115)
    ax.set_xlabel(f"Percentage of all {n:,} records carrying the type (types overlap)")
    ax.set_title("PubMed publication types", fontweight="bold")
    plt.tight_layout()
    _save(fig, "fig6_pub_types.pdf")


# ─────────────────────────────────────────────────────────────────────────────
# 7. Country collaboration heatmap (top N)
# ─────────────────────────────────────────────────────────────────────────────

def plot_country_collab(country_net: dict, top_n: int = 20):
    nodes = collections.Counter(country_net["nodes"])
    top_countries = [c for c, _ in nodes.most_common(top_n)
                     if c != "Unknown"][:top_n]
    n = len(top_countries)
    if n < 2:
        return

    idx = {c: i for i, c in enumerate(top_countries)}
    matrix = np.zeros((n, n), dtype=int)
    for edge_key, weight in country_net["edges"].items():
        parts = edge_key.split("|")
        c1, c2 = parts[0], parts[1]
        if c1 in idx and c2 in idx:
            i, j = idx[c1], idx[c2]
            matrix[i][j] = weight
            matrix[j][i] = weight

    fig, ax = plt.subplots(figsize=(7, 6.5))
    im = ax.imshow(np.log1p(matrix), cmap="YlOrRd", aspect="auto")
    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels(top_countries, rotation=45, ha="right", fontsize=8)
    ax.set_yticklabels(top_countries, fontsize=8)
    plt.colorbar(im, ax=ax, label="log(1 + co-publications)", shrink=0.7)
    ax.set_title(f"Country Collaboration Heatmap (Top {top_n})", fontweight="bold")

    # Annotate cells with actual values
    for i in range(n):
        for j in range(n):
            if matrix[i][j] > 0:
                ax.text(j, i, str(matrix[i][j]),
                        ha="center", va="center", fontsize=6,
                        color="black" if matrix[i][j] < matrix.max() * 0.5 else "white")
    plt.tight_layout()
    _save(fig, "fig7_country_collab.pdf")


# ─────────────────────────────────────────────────────────────────────────────
# 8. Temporal keyword trends (top 10 keywords over time)
# ─────────────────────────────────────────────────────────────────────────────

def plot_keyword_trends(records: list[dict], top_keywords: list[str], n: int = 10):
    """Suppl. Fig: A share (%) of keyword-bearing records carrying each of the
    top-n normalized author keywords, per year; B share of all records that
    carry any author keyword (the denominator, which rises from 0% to >60%)."""
    import keywords as _kw
    kws = top_keywords[:n]
    tr = _kw.trends([r for r in records
                     if config.START_YEAR <= (int(r.get("year") or 0) if str(r.get("year") or "").isdigit() else 0) <= config.END_YEAR],
                    kws, source="author")
    years = tr["years"]
    # start where the denominator is meaningful
    min_den = getattr(config, "KEYWORD_TREND_MIN_RECORDS", 10)
    first = next((i for i, d in enumerate(tr["denominator"]) if d >= min_den), 0)
    years = years[first:]
    if not years:
        return
    DISTINCT_COLORS = ["#1f77b4", "#d62728", "#2ca02c", "#ff7f0e", "#9467bd",
                       "#8c564b", "#e377c2", "#17becf", "#bcbd22", "#7f7f7f"]
    LINE_STYLES = ["-", "--", "-.", ":"]
    MARKERS     = ["o", "s", "^", "D", "v", "P", "X", "*", "h", "p"]

    fig, (ax, axc) = plt.subplots(2, 1, figsize=(7, 6), sharex=True,
                                  gridspec_kw={"height_ratios": [3, 1]})
    for i, kw in enumerate(kws):
        vals = tr["share_pct"][kw][first:]
        ax.plot(years, [v if v is not None else float("nan") for v in vals],
                color=DISTINCT_COLORS[i % 10], linestyle=LINE_STYLES[i % 4],
                marker=MARKERS[i % 10], markersize=3, markevery=2, linewidth=1.5, label=kw)
    ax.set_ylabel("% of keyword-bearing records")
    ax.set_title(f"Temporal trajectories of the top {n} normalized author keywords", fontweight="bold")
    ax.yaxis.grid(True, linestyle="--", alpha=0.4)
    ax.legend(bbox_to_anchor=(1.01, 1), loc="upper left", fontsize=6.5, framealpha=0.9,
              edgecolor="#cccccc", handlelength=2.5)
    _panel_letter(ax, "A")

    cov = [100 * d / nr if nr else 0 for d, nr in zip(tr["denominator"][first:], tr["n_records"][first:])]
    axc.bar(years, cov, color=PALETTE[0], alpha=0.6)
    axc.set_ylabel("% records with\nauthor keywords")
    axc.set_xlabel("Year")
    axc.set_ylim(0, 100)
    _panel_letter(axc, "B")

    plt.tight_layout()
    _save(fig, "fig8_keyword_trends.pdf")


# ─────────────────────────────────────────────────────────────────────────────
# 9. Institutions
# ─────────────────────────────────────────────────────────────────────────────

def plot_institutions(institutions: list[dict], top_n: int = 15):
    """SDC figure, 3×1: A publications, B total citations, C mean citations per
    publication.  Stacked vertically so long institution names fit in 7 in."""
    top = institutions[:top_n]
    _short = {"TU Dresden / University Hospital Carl Gustav Carus": "TU Dresden / Univ. Hosp. Carl Gustav Carus",
              "All India Institute of Medical Sciences": "All India Inst. of Medical Sciences",
              "Federal University of São Paulo": "Federal Univ. of São Paulo",
              "University Medical Center Utrecht": "Univ. Medical Center Utrecht"}
    labels = [_short.get(r["institution"], r["institution"]) for r in top]
    counts = [r["count"] for r in top]
    cites  = [r.get("citations", 0) or 0 for r in top]
    ratios = [c / p if p else 0 for c, p in zip(cites, counts)]
    has_cites = any(cites)
    nrows = 3 if has_cites else 1
    fig, axes = plt.subplots(nrows, 1, figsize=(7, 3.4 * nrows))
    if nrows == 1:
        axes = [axes]
    # Name the scheme that produced the table rather than hardcoding one: the
    # caption is wrong the moment config changes, and nobody notices.
    _scope = ("first author" if getattr(config, "INSTITUTION_FIRST_AUTHOR_ONLY", True)
              else "all authors")
    _count = getattr(config, "INSTITUTION_COUNTING", "primary")
    _count = {"primary": "primary affiliation", "whole": "whole counting",
              "fractional": "fractional counting"}.get(_count, _count)
    fig.suptitle(f"Top {top_n} institutions in {config.FIELD_LABEL} research "
                 f"({_scope}, {_count})",
                 fontsize=10, fontweight="bold")
    y = list(range(len(labels)))
    axes[0].barh(y, counts, color=PALETTE[4], alpha=0.85)
    axes[0].set_yticks(y); axes[0].set_yticklabels(labels, fontsize=7)
    axes[0].invert_yaxis(); axes[0].set_xlabel("Publications"); axes[0].set_title("Publications")
    _panel_letter(axes[0], "A")
    if has_cites:
        order = sorted(range(len(top)), key=lambda i: cites[i], reverse=True)
        axes[1].barh(y, [cites[i] for i in order], color=PALETTE[2], alpha=0.85)
        axes[1].set_yticks(y); axes[1].set_yticklabels([labels[i] for i in order], fontsize=7)
        axes[1].invert_yaxis(); axes[1].set_xlabel(_cite_label()); axes[1].set_title("Total citations")
        _panel_letter(axes[1], "B")
        order = sorted(range(len(top)), key=lambda i: ratios[i], reverse=True)
        bars = axes[2].barh(y, [ratios[i] for i in order], color=PALETTE[3], alpha=0.85)
        axes[2].set_yticks(y); axes[2].set_yticklabels([labels[i] for i in order], fontsize=7)
        axes[2].invert_yaxis(); axes[2].set_xlabel("Mean citations per publication")
        axes[2].set_title("Mean citations per publication"); _panel_letter(axes[2], "C")
        for bar, i in zip(bars, order):
            axes[2].text(bar.get_width() + 0.5, bar.get_y() + bar.get_height() / 2,
                         f"{ratios[i]:.0f}", va="center", fontsize=6)
    plt.tight_layout()
    _save(fig, "fig9_institutions.pdf")


# ─────────────────────────────────────────────────────────────────────────────
# 10. Network graph (author collaboration)
# ─────────────────────────────────────────────────────────────────────────────

def plot_author_network(auth_net: dict, top_n: int = 30):
    try:
        import networkx as nx
    except ImportError:
        print("  [skip] networkx not available for author network graph")
        return

    nodes = auth_net["nodes"]
    edges = auth_net["edges"]

    if not nodes:
        print("  [skip] No nodes in author network")
        return

    # ── 1. Keep only the top_n authors by publication count ──────────────────
    top_authors = sorted(nodes.items(), key=lambda x: x[1], reverse=True)[:top_n]
    top_set = {n for n, _ in top_authors}

    G = nx.Graph()
    for node, weight in top_authors:
        G.add_node(node, weight=weight)

    # Only edges between top_n authors; require ≥2 shared papers to reduce clutter
    MIN_EDGE_WEIGHT = 2
    for edge_key, weight in edges.items():
        n1, n2 = edge_key.split("|||")
        if n1 in top_set and n2 in top_set and weight >= MIN_EDGE_WEIGHT:
            G.add_edge(n1, n2, weight=weight)

    # ── 2. Remove isolates and tiny disconnected components ────────────────────
    # Isolates (degree 0) are removed entirely.
    # Small components (≤ 2 nodes) disconnected from the main graph are also
    # removed — they cause large whitespace in spring layout and carry little
    # network information. They are counted in the title for transparency.
    isolates = list(nx.isolates(G))
    G.remove_nodes_from(isolates)

    # Find the largest connected component; drop everything else that is small
    if G.number_of_nodes() > 0:
        components = sorted(nx.connected_components(G), key=len, reverse=True)
        main_comp  = components[0]
        small_comps = [c for c in components[1:] if len(c) <= 2]
        small_nodes = set().union(*small_comps) if small_comps else set()
        G.remove_nodes_from(small_nodes)
        isolates = list(set(isolates) | small_nodes)  # count them all together

    if G.number_of_nodes() == 0:
        print("  [skip] No connected nodes in author network after filtering")
        return

    # ── 3. Detect communities for colouring ───────────────────────────────────
    try:
        from networkx.algorithms.community import greedy_modularity_communities
        communities = list(greedy_modularity_communities(G))
        # Map node → community index
        node_community = {}
        for i, comm in enumerate(communities):
            for node in comm:
                node_community[node] = i
    except Exception:
        node_community = {n: 0 for n in G.nodes()}

    # Assign colours by community (up to 8 communities)
    COMM_COLORS = [
        "#2166ac", "#d6604d", "#4dac26", "#8073ac",
        "#e08214", "#01665e", "#c51b7d", "#762a83",
    ]
    node_colors = [COMM_COLORS[node_community.get(n, 0) % len(COMM_COLORS)]
                   for n in G.nodes()]

    # ── 4. Layout — Kamada-Kawai on the connected graph spreads a 20-30 node
    #       network evenly; each extra component is laid out on its own and
    #       placed beside the main one so no cluster is pushed into a corner.
    comps = sorted(nx.connected_components(G), key=len, reverse=True)
    pos = {}
    x_off = 0.0
    for ci, comp in enumerate(comps):
        H = G.subgraph(comp)
        if len(comp) == 1:
            p = {next(iter(comp)): (0.0, 0.0)}
        else:
            p = nx.kamada_kawai_layout(H, weight=None)
        xs = [v[0] for v in p.values()]; ys = [v[1] for v in p.values()]
        w = (max(xs) - min(xs)) or 0.4
        scale = 1.0 if ci == 0 else 0.45 * math.sqrt(len(comp) / max(len(comps[0]), 1)) + 0.15
        for n, (x, y) in p.items():
            pos[n] = ((x - min(xs)) * scale + x_off, y * scale)
        x_off += w * scale + 0.45

    # ── 5. Visual scales ──────────────────────────────────────────────────────
    pub_counts = nx.get_node_attributes(G, "weight")
    max_pubs   = max(pub_counts.values()) if pub_counts else 1
    node_sizes = [60 + 540 * math.sqrt(pub_counts.get(n, 1) / max_pubs) for n in G.nodes()]
    max_ew = max((G[u][v]["weight"] for u, v in G.edges()), default=1)
    edge_widths = [0.4 + 2.6 * (G[u][v]["weight"] / max_ew) for u, v in G.edges()]
    edge_alphas = [0.25 + 0.5 * (G[u][v]["weight"] / max_ew) for u, v in G.edges()]

    # ── 6. Draw ───────────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(7, 6.2))
    for (u, v), lw, alpha in zip(G.edges(), edge_widths, edge_alphas):
        ax.plot([pos[u][0], pos[v][0]], [pos[u][1], pos[v][1]],
                color="#888888", linewidth=lw, alpha=alpha, zorder=1)
    nc = nx.draw_networkx_nodes(G, pos, node_size=node_sizes, node_color=node_colors,
                                alpha=0.92, linewidths=0.8, edgecolors="white", ax=ax)
    if nc is not None:
        nc.set_zorder(2)

    # ── 7. Labels beside the nodes, nudged apart so none overlap ───────────────
    texts = []
    for node in G.nodes():
        x, y = pos[node]
        texts.append(ax.text(x, y, node.split(",")[0].strip(), fontsize=6.5,
                             ha="center", va="center", zorder=3,
                             bbox=dict(boxstyle="round,pad=0.12", fc="white", ec="none", alpha=0.75)))
    xs = [p[0] for p in pos.values()]; ys = [p[1] for p in pos.values()]
    ax.set_xlim(min(xs) - 0.25, max(xs) + 0.25)
    ax.set_ylim(min(ys) - 0.2, max(ys) + 0.2)
    try:
        from adjustText import adjust_text
        adjust_text(texts, x=xs, y=ys, ax=ax, expand=(1.15, 1.35),
                    arrowprops=dict(arrowstyle="-", color="#999999", lw=0.4))
    except ImportError:
        pass

    # ── 8. Legends below the plot (community colours, node size) ──────────────
    from matplotlib.lines import Line2D
    n_comm = max(node_community.values()) + 1 if node_community else 1
    handles = [Line2D([0], [0], marker="o", color="w", markersize=7,
                      markerfacecolor=COMM_COLORS[i % len(COMM_COLORS)], label=f"Cluster {i + 1}")
               for i in range(min(n_comm, len(COMM_COLORS)))]
    leg1 = ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.0, -0.01),
                     ncol=min(n_comm, 5), fontsize=7, frameon=False, columnspacing=1.0,
                     title="Co-authorship cluster", title_fontsize=7)
    ax.add_artist(leg1)
    lo, hi = min(pub_counts.values()), max_pubs
    mid = int(round((lo + hi) / 2))
    size_handles = [Line2D([0], [0], marker="o", color="w", markerfacecolor="#777777",
                           markersize=math.sqrt(60 + 540 * math.sqrt(v / max_pubs)),
                           label=f"{v} publications" if v == hi else f"{v}")
                    for v in (lo, mid, hi)]
    ax.legend(handles=size_handles, loc="upper right", bbox_to_anchor=(1.0, -0.03), ncol=3,
              fontsize=7, frameon=False, columnspacing=1.0)

    n_removed = len(isolates)
    ax.set_title(f"Co-authorship network of the {top_n} most productive authors",
                 fontweight="bold", fontsize=10, pad=16)
    ax.text(0.5, 1.0, f"{G.number_of_nodes()} connected authors shown; {n_removed} without a link of "
            f"{MIN_EDGE_WEIGHT} or more shared papers omitted", transform=ax.transAxes,
            ha="center", va="bottom", fontsize=7, color="#555555")
    ax.axis("off")
    plt.tight_layout()
    _save(fig, "fig10_author_network.pdf")



# ─────────────────────────────────────────────────────────────────────────────
# 11. Interactive co-authorship network (pyvis → HTML)
# ─────────────────────────────────────────────────────────────────────────────

def plot_author_network_interactive(auth_net: dict, records: list[dict] = None,
                                    top_n: int = 60, min_edge: int = 1):
    """
    Produce an interactive HTML co-authorship network using pyvis.
    Opens in any browser — nodes are draggable, zoomable, hoverable.

    Node size    = publication count (√-scaled)
    Node colour  = community cluster (greedy modularity)
    Edge width   = number of shared papers
    Edge opacity = scaled by weight
    Hover tooltip = name · publications · citations · institution

    Requires:  pip install pyvis networkx
    Output:    <OUTPUT_DIR>/author_network_interactive.html
    """
    try:
        from pyvis.network import Network
        import networkx as nx
    except ImportError:
        print("  [skip] pyvis not installed — run: pip install pyvis")
        print("         Interactive network requires pyvis + networkx.")
        return

    nodes = auth_net["nodes"]
    edges = auth_net["edges"]

    if not nodes:
        print("  [skip] No nodes for interactive network")
        return

    # ── Build citation lookup from records if available ───────────────────────
    author_citations: dict[str, int] = collections.defaultdict(int)
    author_institution: dict[str, str] = {}
    if records:
        import sys, pathlib as _pl
        sys.path.insert(0, str(_pl.Path(__file__).parent))
        try:
            from analyze import _norm_institution
        except ImportError:
            _norm_institution = None

        for rec in records:
            cc = rec.get("citation_count") or 0
            for a in rec.get("authors", []):
                aid = a.get("author_id")
                if not aid or aid == "__collective__":
                    continue
                author_citations[aid] += cc
                if aid not in author_institution and a.get("affils") and _norm_institution:
                    inst = _norm_institution(a["affils"][0])
                    if inst:
                        author_institution[aid] = inst

    # ── Select top_n nodes by publication count ───────────────────────────────
    top_authors = sorted(nodes.items(), key=lambda x: x[1], reverse=True)[:top_n]
    top_set = {n for n, _ in top_authors}

    # ── Build NetworkX graph for community detection ──────────────────────────
    G = nx.Graph()
    for node, weight in top_authors:
        G.add_node(node, weight=weight)
    for edge_key, weight in edges.items():
        n1, n2 = edge_key.split("|||")
        if n1 in top_set and n2 in top_set and weight >= min_edge:
            G.add_edge(n1, n2, weight=weight)

    # Community detection
    try:
        from networkx.algorithms.community import greedy_modularity_communities
        communities = list(greedy_modularity_communities(G))
        node_community = {}
        for i, comm in enumerate(communities):
            for node in comm:
                node_community[node] = i
    except Exception:
        node_community = {n: 0 for n in G.nodes()}

    # Colour palette for communities (hex strings for pyvis)
    COMM_HEX = [
        "#2166ac", "#d6604d", "#4dac26", "#8073ac",
        "#e08214", "#01665e", "#c51b7d", "#762a83",
        "#35978f", "#bf812d", "#80cdc1", "#f6e8c3",
    ]

    max_pubs = max(nodes.values()) if nodes else 1
    max_cites = max(author_citations.values()) if author_citations else 1
    max_ew = max(edges.values()) if edges else 1

    # ── Build pyvis network ───────────────────────────────────────────────────
    net = Network(
        height="820px", width="100%",
        bgcolor="#1a1a2e",          # dark background — nodes pop
        font_color="#e0e0e0",
        directed=False,
        notebook=False,
    )

    # Physics: Barnes-Hut for good spreading, tuned for ophthalmology network size
    net.set_options("""
    {
      "physics": {
        "barnesHut": {
          "gravitationalConstant": -8000,
          "centralGravity": 0.25,
          "springLength": 180,
          "springConstant": 0.04,
          "damping": 0.12,
          "avoidOverlap": 0.6
        },
        "stabilization": { "iterations": 200 }
      },
      "interaction": {
        "hover": true,
        "tooltipDelay": 100,
        "hideEdgesOnDrag": true,
        "navigationButtons": true,
        "keyboard": true
      },
      "edges": {
        "smooth": { "type": "continuous" },
        "color": { "inherit": false }
      },
      "nodes": {
        "font": { "size": 13, "face": "Arial, sans-serif" },
        "borderWidth": 1.5,
        "borderWidthSelected": 3
      }
    }
    """)

    # Add nodes
    for node, pub_count in top_authors:
        comm_idx  = node_community.get(node, 0)
        color     = COMM_HEX[comm_idx % len(COMM_HEX)]
        cites     = author_citations.get(node, 0)
        inst      = author_institution.get(node, "—")
        cpm       = cites / pub_count if pub_count else 0

        # Size: √-scaled between 18 and 55 px
        size = 18 + 37 * math.sqrt(pub_count / max_pubs)

        # Tooltip (HTML supported by pyvis)
        title = (
            f"<b>{node}</b><br>"
            f"Publications: <b>{pub_count}</b><br>"
            f"Citations: <b>{cites:,}</b><br>"
            f"Cites/paper: <b>{cpm:.1f}</b><br>"
            f"Institution: {inst}<br>"
            f"Cluster: {comm_idx + 1}"
        )

        net.add_node(
            node,
            label=node,
            title=title,
            size=size,
            color={
                "background": color,
                "border":     "#ffffff",
                "highlight":  {"background": "#ffe066", "border": "#ffffff"},
                "hover":      {"background": "#ffe066", "border": "#ffffff"},
            },
            font={"color": "#ffffff", "size": max(11, int(size * 0.55))},
        )

    # Add edges
    for edge_key, weight in edges.items():
        n1, n2 = edge_key.split("|||")
        if n1 not in top_set or n2 not in top_set:
            continue
        if weight < min_edge:
            continue

        # Width 1–8px, opacity 0.25–0.85
        width   = 1 + 7 * (weight / max_ew)
        opacity = 0.25 + 0.60 * (weight / max_ew)
        # Blend edge colour from both endpoint community colours
        c1 = COMM_HEX[node_community.get(n1, 0) % len(COMM_HEX)]
        c2 = COMM_HEX[node_community.get(n2, 0) % len(COMM_HEX)]
        edge_color = c1 if node_community.get(n1) == node_community.get(n2) else "#888888"

        net.add_edge(
            n1, n2,
            value=weight,
            width=width,
            title=f"{n1} ↔ {n2}<br><b>{weight}</b> shared paper{'s' if weight > 1 else ''}",
            color={"color": edge_color, "opacity": opacity,
                   "highlight": "#ffe066", "hover": "#ffe066"},
        )

    # ── Legend as a static HTML block injected into the page ─────────────────
    n_communities = max(node_community.values()) + 1 if node_community else 1
    legend_items = "".join(
        f'<div style="display:flex;align-items:center;margin:3px 0">'
        f'<div style="width:14px;height:14px;border-radius:50%;'
        f'background:{COMM_HEX[i % len(COMM_HEX)]};margin-right:8px;'
        f'border:1px solid #fff"></div>'
        f'<span>Cluster {i + 1}</span></div>'
        for i in range(min(n_communities, len(COMM_HEX)))
    )
    legend_html = f"""
    <div style="position:fixed;top:12px;left:12px;z-index:999;
                background:rgba(20,20,40,0.88);color:#e0e0e0;
                padding:12px 16px;border-radius:8px;
                font-family:Arial,sans-serif;font-size:12px;
                border:1px solid #444;min-width:140px">
      <b style="font-size:13px">Co-authorship clusters</b><br>
      <div style="margin-top:6px">{legend_items}</div>
      <hr style="border-color:#444;margin:8px 0">
      <div style="font-size:11px;color:#aaa">
        Node size = publication volume<br>
        Edge width = shared papers<br>
        Hover for details · drag to explore
      </div>
    </div>
    """

    # Save and inject legend
    out_path = pathlib.Path(config.OUTPUT_DIR) / "author_network_interactive.html"
    net.save_graph(str(out_path))

    # Inject legend into the saved HTML
    html = out_path.read_text(encoding="utf-8")
    html = html.replace("<body>", "<body>" + legend_html, 1)
    out_path.write_text(html, encoding="utf-8")

    print(f"  saved: author_network_interactive.html  ({G.number_of_nodes()} nodes, "
          f"{G.number_of_edges()} edges, {n_communities} clusters)")


# ─────────────────────────────────────────────────────────────────────────────
# Master plot runner
# ─────────────────────────────────────────────────────────────────────────────

def plot_bradford(bradford: dict, highlight: str = None):
    """Two-panel Bradford figure.

    Left:  the Bradford curve - cumulative publications against journal rank
           on a logarithmic axis, with the zone boundaries marked.  A
           scattering law that holds produces a straight central section.
    Right: zone composition - how many journals each zone needs to carry its
           third of the literature, and the citation efficiency of each.
    """
    zones = bradford.get("zones") or []
    curve = bradford.get("curve") or []
    if not zones or not curve:
        print("  skipped: fig11_bradford (no journal data)")
        return

    highlight = highlight or getattr(config, "HIGHLIGHT_JOURNAL", None)
    total     = bradford["total_publications"]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.0, 3.3),
                                   gridspec_kw={"width_ratios": [1.35, 1]})

    # ── Left: cumulative curve ────────────────────────────────────────────
    ranks = [c["rank"] for c in curve]
    cums  = [c["cumulative"] for c in curve]
    ax1.plot(ranks, cums, color=PALETTE[0], lw=1.8)

    boundaries = []
    acc = 0
    for z in zones:
        acc += z["journal_count"]
        boundaries.append(acc)

    zone_colors = ["#2C6FAC", "#E8A020", "#3A9E6B", "#9B59B6"]
    left = 0.5
    for i, (z, b) in enumerate(zip(zones, boundaries)):
        ax1.axvspan(max(left, 0.5), b + 0.5, color=zone_colors[i % len(zone_colors)],
                    alpha=0.10, lw=0)
        if i < len(zones) - 1:
            ax1.axvline(b + 0.5, color="gray", ls="--", lw=1)
        mid = (max(left, 0.6) * (b + 0.5)) ** 0.5   # geometric midpoint on a log axis
        ax1.text(mid, total * 0.97,
                 f"Zone {z['zone']}\n{z['journal_count']} journals",
                 ha="center", va="top", fontsize=7,
                 color=zone_colors[i % len(zone_colors)], fontweight="bold")
        left = b + 0.5

    if highlight:
        hit = next((c for c in curve
                    if highlight.lower() in c["journal"].lower()
                    or highlight.lower() == (c["abbr"] or "").lower()), None)
        if hit:
            ax1.plot([hit["rank"]], [hit["cumulative"]], "o", ms=6,
                     color=PALETTE[1], zorder=5)
            ax1.annotate(f"{hit['abbr']} (rank {hit['rank']}, {hit['count']})",
                         xy=(hit["rank"], hit["cumulative"]),
                         xytext=(hit["rank"] * 1.8, hit["cumulative"] - total * 0.30),
                         fontsize=7, color=PALETTE[1],
                         arrowprops=dict(arrowstyle="-", color=PALETTE[1], lw=0.8))

    ax1.set_xscale("log")
    ax1.set_xlim(0.8, len(curve) * 1.15)
    ax1.set_ylim(0, total * 1.05)
    ax1.set_xlabel("Journal rank (log scale)")
    ax1.set_ylabel("Cumulative publications")
    ax1.set_title("Bradford curve")
    _panel_letter(ax1, "A")

    # ── Right: zone composition ───────────────────────────────────────────
    labels = [f"Zone {z['zone']}" for z in zones]
    x = np.arange(len(zones))
    jc = [z["journal_count"] for z in zones]
    bars = ax2.bar(x, jc, color=[zone_colors[i % len(zone_colors)] for i in range(len(zones))],
                   alpha=0.85, width=0.6)
    ax2.set_yscale("log")
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels)
    ax2.set_ylabel("Journals in zone (log scale)")
    ax2.set_title("Zone composition")
    _panel_letter(ax2, "B")
    ax2.grid(axis="x", visible=False)

    for bar, z in zip(bars, zones):
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() * 1.15,
                 f"{z['journal_count']} journals\n{z['publications']:,} publications\n"
                 f"({z['publication_pct']:.1f}%)",
                 ha="center", va="bottom", fontsize=6.5)
    # Log axis: anchor at 1 so a zone of a handful of journals still reads as a
    # bar rather than a sliver clipped by the axis floor.
    ax2.set_ylim(1, max(jc) * 30)

    mult = bradford.get("multipliers") or []
    if mult and all(m for m in mult):
        ax2.text(0.02, 0.97,
                 "Zone-to-zone multipliers  " + ", ".join(f"×{m:.1f}" for m in mult),
                 transform=ax2.transAxes, va="top", ha="left", fontsize=7,
                 color="dimgray")

    plt.tight_layout()
    _save(fig, "fig11_bradford.pdf")


# ─────────────────────────────────────────────────────────────────────────────
# 12. Cross-period comparison
# ─────────────────────────────────────────────────────────────────────────────

_PERIOD_LABELS = {
    "all_time":  "All time",
    "last_25yr": "Last 25y",
    "last_20yr": "Last 20y",
    "last_15yr": "Last 15y",
    "last_10yr": "Last 10y",
    "last_5yr":  "Last 5y",
}


def plot_period_comparison(rows: list[dict], out_dir: pathlib.Path = None):
    """Four-panel comparison of headline metrics across the analysis windows.

    Drawn from period_comparison.csv, so it always agrees with Table 1.
    Written to the output root rather than a period subdirectory, because it
    spans every window.
    """
    if not rows:
        print("  skipped: fig12_period_comparison (no period data)")
        return

    def _num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    order = list(_PERIOD_LABELS)
    rows = sorted(rows, key=lambda r: order.index(r["period"])
                  if r["period"] in order else 99)
    labels = [_PERIOD_LABELS.get(r["period"], r["period"]) for r in rows]
    x = np.arange(len(rows))

    panels = [
        ("Publications",            [_num(r["total_publications"]) for r in rows], "{:,.0f}"),
        ("Field h-index",           [_num(r["h_index_field"])      for r in rows], "{:,.0f}"),
        ("Citations per publication", [_num(r["mean_cites_per_pub"]) for r in rows], "{:.1f}"),
        ("Journals / countries",    None, None),
    ]

    fig, axes = plt.subplots(2, 2, figsize=(7.0, 5.2))
    axes = axes.ravel()

    for i, (title, values, fmt) in enumerate(panels[:3]):
        ax = axes[i]
        bars = ax.bar(x, values, color=PALETTE[i], alpha=0.85, width=0.62)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=7, rotation=30, ha="right")
        ax.set_title(title)
        _panel_letter(ax, chr(65 + i))
        ax.grid(axis="x", visible=False)
        top = max(values) if values else 1
        for bar, val in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + top * 0.02,
                    fmt.format(val), ha="center", va="bottom", fontsize=6.5)
        ax.set_ylim(0, top * 1.16)

    ax = axes[3]
    j = [_num(r["unique_journals"])  for r in rows]
    c = [_num(r["unique_countries"]) for r in rows]
    w = 0.38
    ax.bar(x - w / 2, j, width=w, color=PALETTE[3], alpha=0.85, label="Journals")
    ax.bar(x + w / 2, c, width=w, color=PALETTE[4], alpha=0.85, label="Countries")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=7, rotation=30, ha="right")
    ax.set_title("Journals and countries")
    _panel_letter(ax, "D")
    ax.grid(axis="x", visible=False)
    ax.legend(fontsize=7, frameon=False)
    top = max(j + c) if (j or c) else 1
    for xi, v_ in zip(x - w / 2, j):
        ax.text(xi, v_ + top * 0.02, f"{v_:,.0f}", ha="center", va="bottom", fontsize=6)
    for xi, v_ in zip(x + w / 2, c):
        ax.text(xi, v_ + top * 0.02, f"{v_:,.0f}", ha="center", va="bottom", fontsize=6)
    ax.set_ylim(0, top * 1.16)

    plt.tight_layout()

    if out_dir is not None:
        _orig = config.OUTPUT_DIR
        config.OUTPUT_DIR = str(out_dir)
        try:
            _save(fig, "fig12_period_comparison.pdf")
        finally:
            config.OUTPUT_DIR = _orig
    else:
        _save(fig, "fig12_period_comparison.pdf")


def run_visualizations(results: dict, records: list[dict] = None):
    print("[visualize] Generating figures …")

    plot_temporal(results["temporal"])
    plot_journals(results["journals"])
    if results.get("bradford"):
        plot_bradford(results["bradford"])
    plot_countries(results["countries"])
    plot_authors(results["authors"])
    plot_keywords(results["keywords"], title_suffix="(Author Keywords)")
    if results["mesh"]["freq"]:
        plot_keywords(results["mesh"], title_suffix="(MeSH Terms)")
    plot_pubtypes(results["pub_types"], results.get("n_records"))
    plot_country_collab(results["country_net"])
    plot_institutions(results["institutions"])
    plot_author_network(results["author_net"])
    plot_author_network_interactive(results["author_net"], records=records)

    if records:
        top_kws = [k for k, _ in sorted(
            results["keywords"]["freq"].items(), key=lambda x: x[1], reverse=True
        )[:10]]
        plot_keyword_trends(records, top_kws)

    print(f"[visualize] All figures saved to {config.OUTPUT_DIR}")


if __name__ == "__main__":
    data_path = pathlib.Path(config.DATA_DIR) / "analysis.json"
    with open(data_path) as f:
        results = json.load(f)

    cache_path = pathlib.Path(config.CACHE_DIR) / "records_cited.json"
    if not cache_path.exists():
        cache_path = pathlib.Path(config.CACHE_DIR) / "records.json"
    with open(cache_path) as f:
        records = json.load(f)

    run_visualizations(results, records)
