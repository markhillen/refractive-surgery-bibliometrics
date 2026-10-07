#!/usr/bin/env python3
"""
manuscript_figures.py — the five main-text figures for the JRS manuscript
=========================================================================
Reads only pipeline outputs (cache/records_final.json, output/*.csv) and
writes Fig1–Fig5 as vector PDF and as 600-dpi LZW TIFF (the journal accepts
TIFF or JPEG at ≥300 dpi) to output/manuscript_figures/.  Arial throughout.
"""
from __future__ import annotations

import collections, csv, json, pathlib, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
from matplotlib.patches import FancyBboxPatch

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import config  # noqa: E402
import procedures  # noqa: E402

fm.findfont("Arial", fallback_to_default=False)   # raises if Arial is missing
plt.rcParams.update({
    "font.family": "Arial", "font.size": 8, "axes.titlesize": 9, "axes.labelsize": 8,
    "legend.fontsize": 7, "xtick.labelsize": 7, "ytick.labelsize": 7,
    "pdf.fonttype": 42, "ps.fonttype": 42, "axes.spines.top": False, "axes.spines.right": False,
    "figure.facecolor": "white", "savefig.facecolor": "white",
})
BLUE, ORANGE, GREEN, GREY, PURPLE, RED = "#2C6FAC", "#E05C1B", "#3A9E6B", "#8C8C8C", "#7B4FA0", "#B8322A"
CN, US = "#1B7F79", "#7B4FA0"   # neutral pair for country comparisons
OUT = pathlib.Path(config.OUTPUT_DIR) / "manuscript_figures"
OUT.mkdir(parents=True, exist_ok=True)


def _save(fig, name):
    fig.savefig(OUT / f"{name}.pdf", bbox_inches="tight")
    fig.savefig(OUT / f"{name}.tif", dpi=600, bbox_inches="tight", pil_kwargs={"compression": "tiff_lzw"})
    plt.close(fig)
    print("  saved", name)


def _letter(ax, s):
    ax.text(-0.2, 1.05, s, transform=ax.transAxes, fontsize=10, fontweight="bold", va="bottom")


def _year(r):
    return int(r.get("year") or 0)


def load():
    return json.load(open(pathlib.Path(config.CACHE_DIR) / "records_final.json"))


def fig1(recs):
    by = collections.Counter(_year(r) for r in recs)
    ys = list(range(config.ALL_TIME_START, config.END_YEAR + 1))
    n = [by[y] for y in ys]
    ma = [sum(n[max(0, i - 1):i + 2]) / len(n[max(0, i - 1):i + 2]) for i in range(len(n))]
    fs = list(csv.DictReader(open(pathlib.Path(config.OUTPUT_DIR) / "field_share_by_year.csv")))
    fig, ax = plt.subplots(1, 2, figsize=(7.0, 2.7))
    ax[0].bar(ys, n, color=BLUE, width=0.8, label="Publications")
    ax[0].plot(ys, ma, color=ORANGE, lw=1.4, label="3-year moving average")
    ax[0].set_ylabel("Publications per year"); ax[0].set_xlim(1987, config.END_YEAR + 1)
    ax[0].set_ylim(0, 620); ax[0].legend(frameon=False, loc="upper left", ncol=2); _letter(ax[0], "A")
    fy = [int(r["year"]) for r in fs]
    ax[1].plot(fy, [float(r["per_1000_ophthalmology_mesh"]) for r in fs], color=BLUE, lw=1.4,
               label="Ophthalmology records by MeSH heading")
    ax[1].plot(fy, [float(r["per_1000_ophthalmology_text"]) for r in fs], color=ORANGE, lw=1.4, ls="--",
               label="Ophthalmology records by title/abstract terms")
    ax[1].set_ylabel("Per 1,000 ophthalmology records"); ax[1].set_xlim(1987, config.END_YEAR + 1)
    ax[1].set_ylim(0, 50); ax[1].legend(frameon=False, loc="upper right"); _letter(ax[1], "B")
    for a in ax:
        a.set_xlabel("Year of publication")
    fig.tight_layout(w_pad=2.5)
    _save(fig, "Fig2_output")


def fig2(recs):
    fams = ["LASIK", "Surface ablation", "Lenticule extraction"]
    lab = {"LASIK": "LASIK", "Surface ablation": "Surface ablation (PRK, LASEK, epi-LASIK, transepithelial PRK)",
           "Lenticule extraction": "KLEx (SMILE and other lenticule extraction)"}
    col = {"LASIK": BLUE, "Surface ablation": GREEN, "Lenticule extraction": ORANGE}
    by = collections.defaultdict(collections.Counter); tot = collections.Counter()
    kx = collections.defaultdict(collections.Counter)
    for r in recs:
        y = _year(r); tot[y] += 1
        f = procedures.families(r)
        for k in f:
            by[y][k] += 1
        if "Lenticule extraction" in f:
            c = r.get("country") or "Unresolved"
            c = c if c in ("China", "United States") else ("Unresolved" if c in ("Unknown", "Unresolved") else "Other countries")
            kx[y][c] += 1
    ys = list(range(1990, config.END_YEAR + 1))
    fig, ax = plt.subplots(1, 2, figsize=(7.0, 3.4), gridspec_kw={"width_ratios": [1.25, 1]})
    for k in fams:
        ax[0].plot(ys, [100 * by[y][k] / tot[y] for y in ys], color=col[k], lw=1.5, label=lab[k])
    ax[0].set_ylabel("Share of the year's publications (%)"); ax[0].set_ylim(0, 100); ax[0].set_xlim(1990, config.END_YEAR)
    for i, x in enumerate([1995, 1998, 2011, 2016], 1):
        ax[0].axvline(x, color=GREY, lw=0.6, ls=":")
        ax[0].text(x, 102, str(i), ha="center", va="bottom", fontsize=6.5, color="#555555", clip_on=False)
    ax[0].legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.2), fontsize=6.5, ncol=1)
    ax[0].set_xlabel("Year of publication"); _letter(ax[0], "A")
    y2 = list(range(2010, config.END_YEAR + 1))
    bottom = [0] * len(y2)
    for c, cl in [("China", CN), ("United States", US), ("Other countries", GREY), ("Unresolved", "#D9D9D9")]:
        v = [kx[y][c] for y in y2]
        ax[1].bar(y2, v, bottom=bottom, color=cl, width=0.8, label=c)
        bottom = [a + b for a, b in zip(bottom, v)]
    ax[1].set_ylabel("KLEx publications"); ax[1].set_xlabel("Year of publication")
    ax[1].legend(frameon=False, loc="upper left", title="First-author country", title_fontsize=7)
    ax[1].set_xticks(list(range(2010, config.END_YEAR + 1, 5))); _letter(ax[1], "B")
    fig.tight_layout(w_pad=2.5)
    _save(fig, "Fig3_procedures")


def _block(y):
    return f"{(y - 1) // 5 * 5 + 1}–{str((y - 1) // 5 * 5 + 5)[2:]}" if y >= 1991 else "1988–90"


def fig3(recs):
    jb = collections.defaultdict(collections.Counter)
    for r in recs:
        jb[_block(_year(r))][r.get("journal_abbr")] += 1
    blocks = sorted(jb, key=lambda b: int(b[:4]))
    share = [100 * (jb[b]["J Refract Surg"] + jb[b]["J Cataract Refract Surg"]) / sum(jb[b].values()) for b in blocks]
    nj = [len(jb[b]) for b in blocks]
    fig, ax = plt.subplots(1, 2, figsize=(7.0, 2.7))
    ax[0].bar(range(len(blocks)), share, color=BLUE, width=0.7)
    ax[0].set_xticks(range(len(blocks))); ax[0].set_xticklabels(blocks, rotation=45, ha="right")
    ax[0].set_ylabel("Share in JCRS and JRS (%)"); ax[0].set_ylim(0, 60)
    for i, v in enumerate(share):
        ax[0].text(i, v + 1, f"{v:.0f}", ha="center", fontsize=6.5, bbox=dict(fc="white", ec="none", pad=0.6), zorder=5)
    a2 = ax[0].twinx(); a2.spines["right"].set_visible(True)
    a2.plot(range(len(blocks)), nj, color=ORANGE, marker="o", ms=3, lw=1.3)
    a2.set_ylabel("Journals publishing in the period", color=ORANGE); a2.tick_params(axis="y", colors=ORANGE)
    a2.set_ylim(0, max(nj) * 1.15); _letter(ax[0], "A")
    for label, y0, col in [("All years (1988–2025)", config.ALL_TIME_START, BLUE), ("2021–2025", 2021, ORANGE)]:
        c = collections.Counter(r.get("journal_abbr") for r in recs if _year(r) >= y0)
        vals = sorted(c.values(), reverse=True); tot = sum(vals); cum = 0; xs, ys = [], []
        for i, v in enumerate(vals, 1):
            cum += v; xs.append(i); ys.append(100 * cum / tot)
        ax[1].plot(xs, ys, color=col, lw=1.5, label=label)
    ax[1].set_xscale("log"); ax[1].set_ylim(0, 100)
    ax[1].set_xlabel("Journal rank by output (log scale)"); ax[1].set_ylabel("Cumulative share of publications (%)")
    ax[1].legend(frameon=False, loc="lower right"); _letter(ax[1], "B")
    fig.tight_layout(w_pad=3)
    _save(fig, "Fig4_journals")


def fig4(recs):
    by = collections.defaultdict(collections.Counter)
    for r in recs:
        by[_year(r)][r.get("country") or "Unknown"] += 1
    ys = list(range(1990, config.END_YEAR + 1))
    fig, ax = plt.subplots(1, 2, figsize=(7.0, 3.0), gridspec_kw={"width_ratios": [1.1, 1]})
    ax[0].plot(ys, [by[y]["United States"] for y in ys], color=US, lw=1.5, label="United States")
    ax[0].plot(ys, [by[y]["China"] for y in ys], color=CN, lw=1.5, label="China")
    ax[0].set_xlabel("Year of publication"); ax[0].set_ylabel("First-author publications per year")
    ax[0].legend(frameon=False, loc="upper left"); _letter(ax[0], "A")
    rows = list(csv.DictReader(open(pathlib.Path(config.OUTPUT_DIR) / "last_5yr" / "countries_top.csv")))[:15]
    names = [r["country"] for r in rows][::-1]; vals = [int(r["publications"]) for r in rows][::-1]
    pct = [float(r["pct_of_resolved"]) for r in rows][::-1]
    ax[1].barh(range(len(names)), vals, color=[CN if n == "China" else (US if n == "United States" else GREY) for n in names])
    ax[1].set_yticks(range(len(names))); ax[1].set_yticklabels(names)
    for i, (v, p) in enumerate(zip(vals, pct)):
        ax[1].text(v + 5, i, f"{v} ({p:.1f}%)", va="center", fontsize=6.5)
    ax[1].set_xlabel("First-author publications, 2021–2025"); ax[1].set_xlim(0, max(vals) * 1.3)
    ax[1].text(0.98, 0.02, f"Country unresolved: {sum(1 for r in recs if _year(r) >= 2021 and (r.get('country') or 'Unknown') == 'Unknown')}", transform=ax[1].transAxes, ha="right", va="bottom", fontsize=6.5, color="#555555")
    ax[1].grid(False); _letter(ax[1], "B")
    fig.tight_layout(w_pad=2.5)
    _save(fig, "Fig5_countries")


def fig5(flow: dict):
    """Screening flow; flow holds the counts (see manuscript build)."""
    fig, ax = plt.subplots(figsize=(7.0, 4.3)); ax.axis("off"); ax.set_xlim(0, 100); ax.set_ylim(0, 100)

    def box(x, y, w, h, text, fc="#F2F6FB"):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.4,rounding_size=1.2", fc=fc, ec="#4A6A8A", lw=0.8))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=7, wrap=True)

    def arrow(x1, y1, x2, y2):
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1), arrowprops=dict(arrowstyle="-|>", lw=0.8, color="#4A6A8A"))
    L, W = 4, 46
    box(L, 88, W, 9, f"PubMed records retrieved by the search,\n1988–2025: n = {flow['retrieved']:,}")
    box(L, 72, W, 10, f"Journal records parsed: n = {flow['parsed']:,}\n(NCBI Bookshelf items not analyzed: n = {flow['books']})")
    box(L, 50, W, 15, "Rule-based relevance filter\n(content, journal and MeSH rules;\nevery decision logged)")
    box(L, 26, W, 17, f"Individually screened records: n = {flow['screened']:,}\n"
                      f"rule-unresolved queue {flow['queue']}, random precision sample {flow['sample']},\n"
                      f"procedure term in abstract or keywords only {flow['stratum']:,}\n"
                      f"(decisions proposed by Claude; exclusions checked by an author)", fc="#FFF6EC")
    box(L, 4, W, 13, f"Publications analyzed: n = {flow['final']:,}", fc="#EAF5EE")
    for y1, y2 in [(88, 82), (72, 65), (50, 43), (26, 17)]:
        arrow(L + W / 2, y1, L + W / 2, y2)
    R = 58; RW = 38
    box(R, 70, RW, 13, f"Excluded by rule: n = {flow['rule_excluded']:,}\nphototherapeutic keratectomy only {flow['ptk']}\n"
                       f"no procedure term {flow['nosignal']}; no ophthalmic term {flow['nooph']}\nerrata and retraction notices {flow['notices']}", fc="#FBEFEF")
    box(R, 30, RW, 12, f"Excluded on screening: n = {flow['manual_excluded']:,}\n(mentioned in passing, non-refractive laser use,\nor unrelated)", fc="#FBEFEF")
    arrow(L + W, 57, R, 76); arrow(L + W, 34, R, 36)
    _save(fig, "Fig1_flow")


if __name__ == "__main__":
    recs = load()
    fig1(recs); fig2(recs); fig3(recs); fig4(recs)
    flow_p = pathlib.Path(config.OUTPUT_DIR) / "screening_flow.json"
    if flow_p.exists():
        fig5(json.load(open(flow_p)))
