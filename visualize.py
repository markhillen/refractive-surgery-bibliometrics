"""
visualize.py — Generate all bibliometric charts
================================================
Produces publication-quality figures saved to OUTPUT_DIR.
"""

import json
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
    "font.family":       "DejaVu Sans",
    "font.size":         10,
    "axes.spines.top":   False,
    "axes.spines.right": False,
    "axes.grid":         True,
    "grid.alpha":        0.3,
    "figure.facecolor":  "white",
})

PALETTE = ["#2C6FAC", "#E05C1B", "#3A9E6B", "#9B59B6",
           "#E8A020", "#16A085", "#C0392B", "#2980B9"]


def _save(fig, name: str):
    # Replace extension with configured format
    fmt  = getattr(config, "FIGURE_FORMAT", "pdf")
    stem = pathlib.Path(name).stem
    fname = f"{stem}.{fmt}"
    path  = _out_dir() / fname
    kwargs = {"bbox_inches": "tight"}
    if fmt == "png":
        kwargs["dpi"] = 300           # high-dpi raster only
    # PDF and SVG are vector — dpi argument is ignored/irrelevant
    fig.savefig(path, **kwargs)
    plt.close(fig)
    print(f"  saved: {path.name}")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Temporal trends
# ─────────────────────────────────────────────────────────────────────────────

def plot_temporal(temporal: dict):
    years  = temporal["years"]
    counts = temporal["counts"]
    cumul  = temporal["cumulative"]
    mavg   = temporal["moving_avg"]
    cites  = temporal["citations"]

    # Panel 1: annual + moving average + cumulative
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    fig.suptitle("Keratoconus & Corneal Ectasia Publications Over Time", fontsize=14, fontweight="bold")

    ax1.bar(years, counts, color=PALETTE[0], alpha=0.7, label="Annual publications")
    ax1.plot(years, mavg, color=PALETTE[1], linewidth=2.5,
             marker="o", markersize=4, label="3-yr moving average")
    ax1.set_ylabel("Publications per year")
    ax1.legend(fontsize=9)

    ax2b = ax2.twinx()
    ax2.bar(years, cumul, color=PALETTE[2], alpha=0.6, label="Cumulative publications")
    if any(cites):
        ax2b.plot(years, cites, color=PALETTE[1], linewidth=2,
                  marker="s", markersize=4, label="Total citations")
        ax2b.set_ylabel("Total citations (CrossRef)", color=PALETTE[1])
        ax2b.tick_params(axis="y", colors=PALETTE[1])
    ax2.set_ylabel("Cumulative publications")
    ax2.set_xlabel("Year")
    ax2.legend(loc="upper left", fontsize=9)

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

    fig, ax = plt.subplots(figsize=(10, max(6, top_n * 0.35)))
    y = range(len(labels))
    bars = ax.barh(list(y), counts, color=PALETTE[0], alpha=0.8)
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("Number of publications")
    ax.set_title(f"Top {top_n} Journals Publishing Keratoconus Research", fontweight="bold")

    for bar, pct in zip(bars, pcts):
        ax.text(bar.get_width() + counts[0] * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{pct:.1f}%", va="center", fontsize=8, color="gray")

    plt.tight_layout()
    _save(fig, "fig2_top_journals.pdf")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Top countries
# ─────────────────────────────────────────────────────────────────────────────

def plot_countries(countries: list[dict], top_n: int = None):
    top_n = top_n or config.TOP_N_COUNTRIES
    top = [c for c in countries if c["country"] != "Unknown"][:top_n]

    labels  = [r["country"] for r in top]
    counts  = [r["count"] for r in top]
    cites   = [r["citations"] for r in top]
    ratios  = [r["citations"] / r["count"] if r["count"] else 0 for r in top]
    # Per-capita: only countries with population data
    percap  = [r.get("pubs_per_million") for r in top]
    has_percap = any(v is not None for v in percap)

    has_cites = any(cites)
    ncols = (1 + int(has_cites) * 2 + int(has_percap))
    fig, axes = plt.subplots(1, ncols, figsize=(6 * ncols, max(6, top_n * 0.33)))
    if ncols == 1:
        axes = [axes]
    fig.suptitle(f"Top {top_n} Countries in Keratoconus Research", fontsize=13, fontweight="bold")

    y = range(len(labels))

    # Panel 1: publication count (sorted by volume — default order)
    axes[0].barh(list(y), counts, color=PALETTE[0], alpha=0.85)
    axes[0].set_yticks(list(y)); axes[0].set_yticklabels(labels, fontsize=9)
    axes[0].invert_yaxis(); axes[0].set_xlabel("Publications")
    axes[0].set_title("Publication volume")

    ax_idx = 1
    if has_cites:
        # Panel 2: total citations (re-sorted)
        cite_order = sorted(range(len(top)), key=lambda i: cites[i], reverse=True)
        axes[ax_idx].barh(list(y), [cites[i] for i in cite_order], color=PALETTE[2], alpha=0.85)
        axes[ax_idx].set_yticks(list(y))
        axes[ax_idx].set_yticklabels([labels[i] for i in cite_order], fontsize=9)
        axes[ax_idx].invert_yaxis(); axes[ax_idx].set_xlabel("Total citations (CrossRef)")
        axes[ax_idx].set_title("Total citation impact")
        ax_idx += 1

        # Panel 3: citation efficiency (re-sorted)
        ratio_order = sorted(range(len(top)), key=lambda i: ratios[i], reverse=True)
        colors_r = [PALETTE[3] if ratios[i] > np.median(ratios) else PALETTE[4]
                    for i in ratio_order]
        bars = axes[ax_idx].barh(list(y), [ratios[i] for i in ratio_order],
                                  color=colors_r, alpha=0.85)
        axes[ax_idx].set_yticks(list(y))
        axes[ax_idx].set_yticklabels([labels[i] for i in ratio_order], fontsize=9)
        axes[ax_idx].invert_yaxis()
        axes[ax_idx].set_xlabel("Mean citations per publication")
        axes[ax_idx].set_title("Citation efficiency (above median = darker)")
        for bar, i in zip(bars, ratio_order):
            axes[ax_idx].text(bar.get_width() + 0.5, bar.get_y() + bar.get_height() / 2,
                              f"{ratios[i]:.1f}", va="center", fontsize=7.5)
        ax_idx += 1

    if has_percap:
        # Panel 4: publications per million population (re-sorted; skip unknowns)
        pc_order = sorted(
            [i for i in range(len(top)) if percap[i] is not None],
            key=lambda i: percap[i], reverse=True
        )
        # Include all countries; those without data plotted at 0 with hatching
        pc_vals   = [percap[i] if percap[i] is not None else 0 for i in range(len(top))]
        pc_sorted = sorted(range(len(top)),
                           key=lambda i: (percap[i] or 0), reverse=True)
        colors_pc = [PALETTE[3] if (percap[i] or 0) > np.median([v for v in percap if v])
                     else PALETTE[4] for i in pc_sorted]
        bars_pc = axes[ax_idx].barh(
            list(range(len(top))),
            [pc_vals[i] for i in pc_sorted],
            color=colors_pc, alpha=0.85
        )
        # Hatch bars with no population data
        for bar, i in zip(bars_pc, pc_sorted):
            if percap[i] is None:
                bar.set_hatch("///")
        axes[ax_idx].set_yticks(list(range(len(top))))
        axes[ax_idx].set_yticklabels([labels[i] for i in pc_sorted], fontsize=9)
        axes[ax_idx].invert_yaxis()
        axes[ax_idx].set_xlabel("Publications per million population")
        axes[ax_idx].set_title("Per-capita output\n(2024 UN population estimates)")
        for bar, i in zip(bars_pc, pc_sorted):
            if percap[i] is not None:
                axes[ax_idx].text(
                    bar.get_width() + 0.05, bar.get_y() + bar.get_height() / 2,
                    f"{percap[i]:.1f}", va="center", fontsize=7.5
                )

    plt.tight_layout()
    _save(fig, "fig3_top_countries.pdf")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Top authors
# ─────────────────────────────────────────────────────────────────────────────

def plot_authors(authors: list[dict], top_n: int = 25):
    top    = authors[:top_n]
    labels = [r["author_id"] for r in top]
    pubs   = [r["pub_count"] for r in top]
    first  = [r["first_author_count"] for r in top]
    last   = [r.get("last_author_count", 0) or 0 for r in top]
    cites  = [r.get("citation_total", 0) or 0 for r in top]
    ratios = [c / p if p else 0 for c, p in zip(cites, pubs)]

    has_cites = any(cites)
    ncols = 3 if has_cites else 1
    fig, axes = plt.subplots(1, ncols, figsize=(7 * ncols, max(6, top_n * 0.35)))
    if ncols == 1:
        axes = [axes]
    fig.suptitle(f"Top {top_n} Most Productive Authors — Keratoconus Research", fontsize=13, fontweight="bold")

    y = np.arange(len(labels))

    # Panel 1: total pubs, with first- and last-author overlaid
    axes[0].barh(y,       pubs,  color=PALETTE[0], alpha=0.75, label="Total")
    axes[0].barh(y - 0.18, first, height=0.35, color=PALETTE[1], alpha=0.9,  label="First-author")
    axes[0].barh(y + 0.18, last,  height=0.35, color=PALETTE[3], alpha=0.9,  label="Last-author")
    axes[0].set_yticks(y); axes[0].set_yticklabels(labels, fontsize=9)
    axes[0].invert_yaxis(); axes[0].set_xlabel("Publications")
    axes[0].set_title("Publication volume\n(first- and last-authorship overlaid)")
    axes[0].legend(fontsize=8, loc="lower right")

    if has_cites:
        # Panel 2: total citations — re-sorted
        cite_order = sorted(range(len(top)), key=lambda i: cites[i], reverse=True)
        axes[1].barh(list(range(len(top))), [cites[i] for i in cite_order],
                     color=PALETTE[2], alpha=0.85)
        axes[1].set_yticks(list(range(len(top))))
        axes[1].set_yticklabels([labels[i] for i in cite_order], fontsize=9)
        axes[1].invert_yaxis(); axes[1].set_xlabel("Total citations (CrossRef)")
        axes[1].set_title("Total citation impact")

        # Panel 3: citation efficiency — re-sorted
        ratio_order = sorted(range(len(top)), key=lambda i: ratios[i], reverse=True)
        med = float(np.median(ratios))
        colors_r = [PALETTE[3] if ratios[i] >= med else PALETTE[4]
                    for i in ratio_order]
        bars = axes[2].barh(list(range(len(top))), [ratios[i] for i in ratio_order],
                             color=colors_r, alpha=0.85)
        axes[2].set_yticks(list(range(len(top))))
        axes[2].set_yticklabels([labels[i] for i in ratio_order], fontsize=9)
        axes[2].invert_yaxis()
        axes[2].set_xlabel("Mean citations per publication")
        axes[2].set_title("Citation efficiency (above median = darker)")
        for bar, i in zip(bars, ratio_order):
            axes[2].text(bar.get_width() + 0.5, bar.get_y() + bar.get_height() / 2,
                         f"{ratios[i]:.1f}", va="center", fontsize=7)

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

    fig, ax = plt.subplots(figsize=(10, max(6, top_n * 0.28)))
    y = range(len(labels))
    ax.barh(list(y), counts, color=PALETTE[3], alpha=0.75)
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=8.5)
    ax.invert_yaxis()
    ax.set_xlabel("Frequency")
    ax.set_title(f"Top {top_n} Keywords {title_suffix}", fontweight="bold")
    plt.tight_layout()
    safe = title_suffix.replace("(","").replace(")","").replace(" ","_").lower()
    fname = f"fig5_{safe}.pdf" if title_suffix else "fig5_keywords.pdf"
    _save(fig, fname)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Publication type pie
# ─────────────────────────────────────────────────────────────────────────────

def plot_pubtypes(pub_types: dict):
    # Keep only top categories, merge rest as "Other"
    keep = ["Journal Article", "Review", "Randomized Controlled Trial",
            "Clinical Trial", "Meta-Analysis", "Comparative Study",
            "Case Reports", "Letter", "Editorial", "Comment"]
    labels, sizes = [], []
    other = 0
    for k, v in pub_types.items():
        if k in keep:
            labels.append(k)
            sizes.append(v)
        else:
            other += v
    if other:
        labels.append("Other")
        sizes.append(other)

    # Sort
    pairs = sorted(zip(sizes, labels), reverse=True)
    sizes, labels = zip(*pairs) if pairs else ([], [])

    fig, ax = plt.subplots(figsize=(8, 6))
    colors = cm.Set3(np.linspace(0, 1, len(labels)))
    wedges, texts, autotexts = ax.pie(
        sizes, labels=None, autopct="%1.1f%%",
        colors=colors, startangle=140, pctdistance=0.82
    )
    ax.legend(wedges, labels, title="Publication Type",
              loc="center left", bbox_to_anchor=(1, 0, 0.5, 1), fontsize=9)
    ax.set_title("Publication Types", fontweight="bold")
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

    fig, ax = plt.subplots(figsize=(12, 10))
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
    # ── Keyword normalisation must match analyze.py synonym map ──────────────
    # Import the same cleaner so trend lookups find merged terms correctly
    try:
        from analyze import _clean_keyword, _KW_SYNONYMS
    except ImportError:
        def _clean_keyword(k): return k.lower().strip().rstrip(".,;:")

    kws = top_keywords[:n]
    year_kw: dict[int, dict[str, int]] = collections.defaultdict(
        lambda: collections.defaultdict(int))

    for rec in records:
        try:
            yr = int(rec.get("year", 0))
        except (ValueError, TypeError):
            continue
        if not (config.START_YEAR <= yr <= config.END_YEAR):
            continue
        # Apply the same synonym cleaning as the analysis step
        raw_kws = rec.get("keywords", []) + rec.get("mesh", [])
        cleaned_set = {ck for k in raw_kws
                       if k.strip()
                       for ck in [_clean_keyword(k)]
                       if ck is not None}
        for kw in kws:
            if kw in cleaned_set:
                year_kw[yr][kw] += 1

    years = sorted(year_kw.keys())
    if not years:
        return

    # ── Visually distinct style assignments ──────────────────────────────────
    # 10 colours chosen to be maximally distinct (colourblind-safe set +
    # supplementary colours), paired with 4 line styles so every line is
    # uniquely identifiable by colour AND dash pattern.
    DISTINCT_COLORS = [
        "#1f77b4",  # steel blue
        "#d62728",  # brick red
        "#2ca02c",  # forest green
        "#ff7f0e",  # orange
        "#9467bd",  # purple
        "#8c564b",  # brown
        "#e377c2",  # pink
        "#17becf",  # teal
        "#bcbd22",  # olive/yellow-green
        "#7f7f7f",  # mid grey
    ]
    LINE_STYLES = ["-", "--", "-.", ":"]
    MARKERS     = ["o", "s", "^", "D", "v", "P", "X", "*", "h", "p"]
    MARKER_SIZE = [4,   4,   4,   4,   4,   5,   5,   6,   4,   5  ]

    fig, ax = plt.subplots(figsize=(13, 6))

    for i, kw in enumerate(kws):
        vals  = [year_kw[y].get(kw, 0) for y in years]
        color = DISTINCT_COLORS[i % len(DISTINCT_COLORS)]
        ls    = LINE_STYLES[i % len(LINE_STYLES)]
        mk    = MARKERS[i % len(MARKERS)]
        ms    = MARKER_SIZE[i % len(MARKER_SIZE)]
        ax.plot(years, vals,
                color=color, linestyle=ls,
                marker=mk, markersize=ms, markevery=2,
                linewidth=1.8, alpha=0.88,
                label=kw)

    ax.set_xlabel("Year", fontsize=11)
    ax.set_ylabel("Papers containing keyword", fontsize=11)
    ax.set_title(f"Temporal Trends of Top {n} Keywords", fontweight="bold", fontsize=13)
    ax.set_xlim(min(years) - 0.5, max(years) + 0.5)
    ax.yaxis.grid(True, linestyle="--", alpha=0.4)
    ax.set_axisbelow(True)

    # Legend outside right, sorted by final-year value (most prominent on top)
    final_vals = {kw: year_kw[max(years)].get(kw, 0) for kw in kws}
    handles, labels = ax.get_legend_handles_labels()
    order = sorted(range(len(labels)), key=lambda i: final_vals.get(labels[i], 0), reverse=True)
    ax.legend(
        [handles[i] for i in order],
        [labels[i]  for i in order],
        bbox_to_anchor=(1.01, 1), loc="upper left",
        fontsize=8.5, framealpha=0.9, edgecolor="#cccccc",
        handlelength=2.5,   # show enough of the dash pattern to distinguish styles
    )

    plt.tight_layout()
    _save(fig, "fig8_keyword_trends.pdf")


# ─────────────────────────────────────────────────────────────────────────────
# 9. Institutions
# ─────────────────────────────────────────────────────────────────────────────

def plot_institutions(institutions: list[dict], top_n: int = 20):
    top = institutions[:top_n]
    labels = [r["institution"] for r in top]
    counts = [r["count"] for r in top]
    cites  = [r.get("citations", 0) or 0 for r in top]
    ratios = [c / p if p else 0 for c, p in zip(cites, counts)]

    has_cites = any(cites)
    ncols = 3 if has_cites else 1
    fig, axes = plt.subplots(1, ncols, figsize=(7 * ncols, max(6, top_n * 0.35)))
    if ncols == 1:
        axes = [axes]
    fig.suptitle(
        f"Top {top_n} Institutions in Keratoconus Research (first-author attribution)",
        fontsize=13, fontweight="bold"
    )
    fig.text(0.5, 0.97,
             "Each publication credited once to the first author's institution only",
             ha="center", va="top", fontsize=9, style="italic", color="#555555")

    y = range(len(labels))
    axes[0].barh(list(y), counts, color=PALETTE[4], alpha=0.85)
    axes[0].set_yticks(list(y)); axes[0].set_yticklabels(labels, fontsize=9)
    axes[0].invert_yaxis(); axes[0].set_xlabel("Publications")
    axes[0].set_title("Publication volume")

    if has_cites:
        cite_order = sorted(range(len(top)), key=lambda i: cites[i], reverse=True)
        axes[1].barh(list(range(len(top))), [cites[i] for i in cite_order],
                     color=PALETTE[2], alpha=0.85)
        axes[1].set_yticks(list(range(len(top))))
        axes[1].set_yticklabels([labels[i] for i in cite_order], fontsize=9)
        axes[1].invert_yaxis(); axes[1].set_xlabel("Total citations (CrossRef)")
        axes[1].set_title("Total citation impact")

        ratio_order = sorted(range(len(top)), key=lambda i: ratios[i], reverse=True)
        med = float(np.median(ratios)) if ratios else 0
        colors_r = [PALETTE[3] if ratios[i] >= med else PALETTE[4]
                    for i in ratio_order]
        bars = axes[2].barh(list(range(len(top))), [ratios[i] for i in ratio_order],
                             color=colors_r, alpha=0.85)
        axes[2].set_yticks(list(range(len(top))))
        axes[2].set_yticklabels([labels[i] for i in ratio_order], fontsize=9)
        axes[2].invert_yaxis()
        axes[2].set_xlabel("Mean citations per publication")
        axes[2].set_title("Citation efficiency (above median = darker)")
        for bar, i in zip(bars, ratio_order):
            axes[2].text(bar.get_width() + 0.5, bar.get_y() + bar.get_height() / 2,
                         f"{ratios[i]:.1f}", va="center", fontsize=7)

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

    # ── 4. Layout — spring with higher k so nodes spread out ─────────────────
    k_val = 3.5 / math.sqrt(max(G.number_of_nodes(), 1))
    pos = nx.spring_layout(G, k=k_val, seed=42, iterations=200)

    # ── 5. Visual scales ──────────────────────────────────────────────────────
    pub_counts = nx.get_node_attributes(G, "weight")
    max_pubs   = max(pub_counts.values()) if pub_counts else 1
    # Node size: proportional to sqrt(pub_count), range ~200–1800
    node_sizes = [200 + 1600 * math.sqrt(pub_counts.get(n, 1) / max_pubs)
                  for n in G.nodes()]

    max_ew = max((G[u][v]["weight"] for u, v in G.edges()), default=1)
    edge_widths = [0.5 + 3.5 * (G[u][v]["weight"] / max_ew) for u, v in G.edges()]
    edge_alphas = [0.25 + 0.55 * (G[u][v]["weight"] / max_ew) for u, v in G.edges()]

    # ── 6. Draw ───────────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(16, 13))
    fig.patch.set_facecolor("#f8f8f8")
    ax.set_facecolor("#f8f8f8")

    # Edges first (behind nodes)
    for (u, v), lw, alpha in zip(G.edges(), edge_widths, edge_alphas):
        x = [pos[u][0], pos[v][0]]
        y = [pos[u][1], pos[v][1]]
        ax.plot(x, y, color="#888888", linewidth=lw, alpha=alpha, zorder=1)

    # Nodes
    nc = nx.draw_networkx_nodes(G, pos,
                                node_size=node_sizes,
                                node_color=node_colors,
                                alpha=0.92,
                                linewidths=0.8,
                                edgecolors="white",
                                ax=ax)
    if nc is not None:
        nc.set_zorder(2)

    # ── 7. Labels: ALL connected nodes, with white background box ─────────────
    # Sort by publication count so we draw high-pub labels last (on top)
    sorted_nodes = sorted(G.nodes(), key=lambda n: pub_counts.get(n, 0))
    for node in sorted_nodes:
        x, y = pos[node]
        last_name = node.split(",")[0].strip()
        pub_n = pub_counts.get(node, 0)
        # Font size scales slightly with prominence
        fsize = 7.5 + min(pub_n / max_pubs * 4, 3.5)
        ax.text(x, y, last_name,
                fontsize=fsize,
                fontweight="bold" if pub_n / max_pubs > 0.5 else "normal",
                ha="center", va="center",
                zorder=3,
                bbox=dict(boxstyle="round,pad=0.18", fc="white",
                          ec="none", alpha=0.7))

    # ── 8. Community legend ───────────────────────────────────────────────────
    n_comm = max(node_community.values()) + 1 if node_community else 1
    if n_comm > 1:
        from matplotlib.patches import Patch
        legend_handles = [
            Patch(facecolor=COMM_COLORS[i % len(COMM_COLORS)],
                  edgecolor="white", label=f"Cluster {i + 1}")
            for i in range(min(n_comm, len(COMM_COLORS)))
        ]
        ax.legend(handles=legend_handles,
                  loc="lower left", fontsize=8.5,
                  framealpha=0.9, edgecolor="#cccccc",
                  title="Co-authorship cluster", title_fontsize=8)

    # ── 9. Size legend (publication count scale) ──────────────────────────────
    from matplotlib.lines import Line2D
    size_legend = []
    for label, frac in [("Low", 0.2), ("Mid", 0.5), ("High", 1.0)]:
        s = 200 + 1600 * math.sqrt(frac)
        size_legend.append(
            Line2D([0], [0], marker="o", color="w",
                   markerfacecolor="#555555", markersize=math.sqrt(s) * 0.38,
                   label=label)
        )
    leg2 = ax.legend(handles=size_legend,
                     loc="lower right", fontsize=8.5,
                     framealpha=0.9, edgecolor="#cccccc",
                     title="Publication volume", title_fontsize=8)
    ax.add_artist(leg2)    # keep both legends

    n_shown   = G.number_of_nodes()
    n_removed = len(isolates)
    ax.set_title(
        f"Author Co-authorship Network  ·  Top {top_n} authors  ·  "
        f"{n_shown} connected, {n_removed} isolated (not shown)  ·  "
        f"edges ≥ {MIN_EDGE_WEIGHT} shared papers",
        fontweight="bold", fontsize=11, pad=12
    )
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
        "font": { "size": 13, "face": "Inter, Arial, sans-serif" },
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
                font-family:Inter,Arial,sans-serif;font-size:12px;
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

def run_visualizations(results: dict, records: list[dict] = None):
    print("[visualize] Generating figures …")

    plot_temporal(results["temporal"])
    plot_journals(results["journals"])
    plot_countries(results["countries"])
    plot_authors(results["authors"])
    plot_keywords(results["keywords"], title_suffix="(Author Keywords)")
    if results["mesh"]["freq"]:
        plot_keywords(results["mesh"], title_suffix="(MeSH Terms)")
    plot_pubtypes(results["pub_types"])
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
