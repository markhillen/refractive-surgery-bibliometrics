"""
periods.py — Multi-period bibliometric analysis
================================================
Slices the fetched refractive surgery record set into multiple time windows and runs
the full bibliometric analysis pipeline on each, writing per-period
output subdirectories.

Time windows (defined in config.ANALYSIS_PERIODS):
  all_time  — 1988–2025 (full indexed laser refractive literature)
  last_20yr — 20 years to present
  last_15yr — 15 years to present
  last_10yr — 10 years to present
  last_5yr  —  5 years to present

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
    for each window. Also writes per-period output subdirectories and
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

        # Override OUTPUT_DIR so visualize/report write to the period subdir
        _orig = config.OUTPUT_DIR
        config.OUTPUT_DIR = str(period_dir)

        try:
            results = analyze.run_analysis(period_records)
            report.generate_reports(results)
            if not skip_viz:
                visualize.run_visualizations(results, period_records)
        finally:
            config.OUTPUT_DIR = _orig

        # Save per-period analysis.json so the GUI Results tab can show
        # period-specific data without a re-run.
        import json as _json
        with open(period_dir / "analysis.json", "w") as _f:
            _json.dump(results, _f, indent=2, default=str)

        # Compute field-level h-index now while period_records is in scope
        cite_counts = sorted(
            (rec["citation_count"] for rec in period_records if rec.get("citation_count") is not None),
            reverse=True,
        )
        h_field = sum(1 for i, c in enumerate(cite_counts, 1) if c >= i)

        results["_period"] = {
            "label": label, "start": start, "end": end, "n": n
        }
        results["_h_index_field"] = h_field
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
        n_pubs = p.get("n", 0)
        total_cites = sum(res.get("temporal", {}).get("citations", []))
        unique_authors = len(res.get("authors", []))
        unique_journals = len(res.get("journals", []))
        unique_countries = len(
            [c for c in res.get("countries", []) if c.get("country") != "Unknown"]
        )
        n_null = sum(res.get("temporal", {}).get("citations_null", []) or [])
        n_known = n_pubs - n_null
        mean_cites = round(total_cites / n_known, 1) if n_known else ""
        n_unknown_country = sum(c.get("count", 0) for c in res.get("countries", [])
                                if c.get("country") == "Unknown")
        rows.append({
            "period":             label,
            "start_year":         p.get("start", ""),
            "end_year":           p.get("end", ""),
            "total_publications": n_pubs,
            "total_citations":    total_cites,
            "records_with_citation_count": n_known,
            "records_without_citation_count": n_null,
            "unique_authors":     unique_authors,
            "unique_journals":    unique_journals,
            "unique_countries":   unique_countries,
            "records_country_unresolved": n_unknown_country,
            "mean_cites_per_pub": mean_cites,
            "h_index_field":      res.get("_h_index_field", ""),
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

    try:
        import visualize
        visualize.plot_period_comparison(rows, out_dir=pathlib.Path(output_root))
    except Exception as exc:          # a figure must never break the pipeline
        print(f"[periods] cross-period figure skipped: {exc}")
