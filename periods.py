"""
periods.py — Multi-period bibliometric analysis
================================================
Slices a single fetched record set into multiple time windows and runs
the full bibliometric analysis pipeline on each, writing per-period
output subdirectories.

Usage (called automatically by main.py):
    from periods import run_all_periods
    run_all_periods(records, output_root="output")
"""

import os
import pathlib

import config


def _filter_by_period(records: list[dict], start: int, end: int) -> list[dict]:
    """Return records whose publication year falls within [start, end] inclusive."""
    out = []
    for rec in records:
        try:
            yr = int(rec.get("year", 0))
        except (ValueError, TypeError):
            yr = 0
        if yr and start <= yr <= end:
            out.append(rec)
    return out


def run_all_periods(records: list[dict], output_root: str = None,
                    skip_viz: bool = False) -> dict:
    """
    Run the full analysis pipeline for every period defined in
    config.ANALYSIS_PERIODS.

    Returns a dict keyed by period label containing the analysis results
    for each window.  Also writes per-period output subdirectories and
    a combined summary CSV.
    """
    import analyze
    import report
    import visualize

    output_root = output_root or config.OUTPUT_DIR
    all_results: dict[str, dict] = {}

    for label, start, end in config.ANALYSIS_PERIODS:
        period_records = _filter_by_period(records, start, end)
        n = len(period_records)
        if n == 0:
            print(f"[periods] {label}: no records — skipping")
            continue

        print(f"\n{'='*60}")
        print(f"[periods] {label}: {n:,} records ({start}–{end})")
        print(f"{'='*60}")

        # Per-period output directory
        period_dir = pathlib.Path(output_root) / label
        period_dir.mkdir(parents=True, exist_ok=True)

        # Override OUTPUT_DIR for this period so visualize/report write there
        _orig = config.OUTPUT_DIR
        config.OUTPUT_DIR = str(period_dir)

        try:
            results = analyze.run_analysis(period_records)
            report.generate_reports(results)
            if not skip_viz:
                visualize.run_visualizations(results, period_records)
            # Write per-period analysis.json so the GUI's /api/results?period=X can serve it
            import json as _json
            with open(period_dir / "analysis.json", "w") as _f:
                _json.dump(results, _f, default=str)
        finally:
            config.OUTPUT_DIR = _orig

        # Field-level h-index: largest h s.t. ≥h papers each have ≥h citations.
        # Must be computed here while per-paper records are still in scope.
        cite_counts = sorted(
            [r.get("citation_count") or 0 for r in period_records],
            reverse=True,
        )
        results["h_index_field"] = sum(
            1 for i, c in enumerate(cite_counts, 1) if c >= i
        )

        results["_period"] = {"label": label, "start": start, "end": end, "n": n}
        all_results[label] = results

    # ── Combined summary table ────────────────────────────────────────────────
    _write_period_summary(all_results, output_root)

    return all_results


def _write_period_summary(all_results: dict, output_root: str) -> None:
    """Write a single CSV comparing headline metrics across all time windows."""
    import csv

    rows = []
    for label, res in all_results.items():
        p = res.get("_period", {})
        n_records = res.get("n_records", 0)
        total_cites = sum(res.get("temporal", {}).get("citations", []))
        rows.append({
            "period":              label,
            "start_year":          p.get("start", ""),
            "end_year":            p.get("end", ""),
            "total_publications":  p.get("n", ""),
            "total_citations":     total_cites,
            "unique_authors":      len(res.get("authors", [])),
            "unique_journals":     len(res.get("journals", [])),
            "unique_countries":    len(res.get("countries", [])),
            "mean_cites_per_pub":  round(total_cites / n_records, 2) if n_records else "",
            "h_index_field":       res.get("h_index_field", ""),
        })

    outpath = pathlib.Path(output_root) / "period_comparison.csv"
    if not rows:
        return
    fields = list(rows[0].keys())
    with open(outpath, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"\n[periods] Period comparison saved → {outpath}")
