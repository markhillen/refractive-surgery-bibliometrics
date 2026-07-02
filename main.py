#!/usr/bin/env python3
"""
main.py — Refractive Surgery Bibliometric Analysis Pipeline
============================================================
Orchestrates the full analysis pipeline:

  1. Fetch PubMed records (cached)
  2. Relevance filtering
  3. Author disambiguation
  4. Country enrichment
  5. Citation enrichment (CrossRef)
  6. Multi-period bibliometric analysis (all-time / last 25/20/15/10/5yr)
  7. Visualization + reports per period
  8. Period comparison summary

Usage:
  python3 main.py --api-key YOUR_NCBI_KEY
  python3 main.py --api-key YOUR_NCBI_KEY --refresh
  python3 main.py --skip-fetch
  python3 main.py --skip-citations
  python3 main.py --pmid-file pmids.txt
  python3 main.py --period all_time          # single period only
"""

import argparse
import json
import pathlib
import sys
import time


class _SetEncoder(json.JSONEncoder):
    """Convert sets to sorted lists for JSON serialisation."""
    def default(self, obj):
        if isinstance(obj, set):
            return sorted(obj)
        return super().default(obj)

sys.path.insert(0, str(pathlib.Path(__file__).parent))


def main():
    parser = argparse.ArgumentParser(
        description="Refractive Surgery Bibliometric Analysis Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--api-key",        default="",   help="NCBI API key")
    parser.add_argument("--pmid-file",      default="",   help="Path to PMID list file")
    parser.add_argument("--refresh",        action="store_true", help="Force re-download")
    parser.add_argument("--skip-fetch",     action="store_true", help="Use cached records only")
    parser.add_argument("--skip-citations", action="store_true", help="Skip CrossRef lookup")
    parser.add_argument("--skip-viz",       action="store_true", help="Skip chart generation")
    parser.add_argument("--use-openalex",   action="store_true",
                        help="Hybrid mode: overlay OpenAlex citations + ROR country (needs cache/openalex_cache.json from openalex_enrich.py)")
    parser.add_argument("--period",         default="",
                        help="Run a single period only (e.g. all_time, last_10yr)")
    parser.add_argument("--start-year",     type=int, default=None,
                        help="Override ALL_TIME_START in config")
    parser.add_argument("--end-year",       type=int, default=None,
                        help="Override END_YEAR in config")
    args = parser.parse_args()

    # ── Verify dependencies before doing any work ──────────────────────────────
    try:
        import check_deps
        if check_deps.check():
            sys.exit(1)
    except ImportError:
        pass  # check_deps.py not present — proceed and let imports fail naturally

    import config
    if args.api_key:
        config.NCBI_API_KEY = args.api_key
    if args.skip_citations:
        config.FETCH_CITATIONS = False

    # ── Config overrides ───────────────────────────────────────────────────────
    if args.start_year is not None:
        config.ALL_TIME_START = args.start_year
        config.START_YEAR     = args.start_year
    if args.end_year is not None:
        config.END_YEAR = args.end_year

    # Rebuild periods if date overrides were applied
    if args.start_year is not None or args.end_year is not None:
        s = config.ALL_TIME_START
        e = config.END_YEAR
        config.ANALYSIS_PERIODS = [
            ("all_time",  s,      e),
            ("last_25yr", e - 24, e),
            ("last_20yr", e - 19, e),
            ("last_15yr", e - 14, e),
            ("last_10yr", e - 9,  e),
            ("last_5yr",  e - 4,  e),
        ]

    if args.period:
        config.ANALYSIS_PERIODS = [p for p in config.ANALYSIS_PERIODS if p[0] == args.period]
        if not config.ANALYSIS_PERIODS:
            print(f"[main] ERROR: Unknown period '{args.period}'.")
            sys.exit(1)

    pathlib.Path(config.CACHE_DIR).mkdir(parents=True, exist_ok=True)
    pathlib.Path(config.OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    print("=" * 60)
    print(f"  {config.PROJECT_NAME} v{config.PROJECT_VERSION}")
    print(f"  All-time fetch: {config.ALL_TIME_START}–{config.END_YEAR}")
    print(f"  Periods: {[p[0] for p in config.ANALYSIS_PERIODS]}")
    print("=" * 60)

    # ── Step 1: Fetch ─────────────────────────────────────────────────────────
    print(f"\n[1/8] Fetching records …")
    cited_path  = pathlib.Path(config.CACHE_DIR) / "records_cited.json"
    disamb_path = pathlib.Path(config.CACHE_DIR) / "records_disambig.json"
    raw_path    = pathlib.Path(config.CACHE_DIR) / "records.json"

    if args.skip_fetch:
        for p in [cited_path, disamb_path, raw_path]:
            if p.exists():
                print(f"[main] Loading {p.name} from cache …")
                with open(p) as f:
                    records = json.load(f)
                print(f"[main] {len(records):,} records loaded")
                break
        else:
            print("[main] ERROR: No cached records. Run without --skip-fetch first.")
            sys.exit(1)
    else:
        if args.pmid_file:
            from fetch import run_fetch_from_pmids
            records = run_fetch_from_pmids(
                pmid_file=args.pmid_file,
                api_key=config.NCBI_API_KEY,
                force_refresh=args.refresh,
            )
        else:
            from fetch import run_fetch
            records = run_fetch(api_key=config.NCBI_API_KEY, force_refresh=args.refresh)
    print(f"[main] {len(records):,} records after filtering")

    # ── Step 2: Disambiguation ────────────────────────────────────────────────
    print(f"\n[2/8] Disambiguating authors …")
    has_ids = any(
        a.get("author_id")
        for rec in records[:50]
        for a in rec.get("authors", [])
    )
    if args.skip_fetch and has_ids:
        print("[main] Author IDs already present — skipping disambiguation")
    else:
        from disambiguate import assign_author_ids
        records, _ = assign_author_ids(records)
        with open(disamb_path, "w") as f:
            json.dump(records, f, cls=_SetEncoder)
        print(f"[main] Disambiguation complete")

    # ── Step 3: Country enrichment ────────────────────────────────────────────
    print(f"\n[3/8] Enriching countries …")
    from geo import enrich_countries
    records = enrich_countries(records)

    # ── Step 4: Citations ─────────────────────────────────────────────────────
    print(f"\n[4/8] Citation enrichment …")
    if config.FETCH_CITATIONS:
        from citations import enrich_citations
        records = enrich_citations(records)
        with open(cited_path, "w") as f:
            json.dump(records, f, cls=_SetEncoder)
    else:
        print("[main] Skipped")

    # ── Step 4.5: OpenAlex hybrid overlay ──────────────────────────
    if args.use_openalex:
        print(f"\n[4.5] Applying OpenAlex hybrid overlay …")
        from openalex_integrate import overlay, load_cache, author_disagreements
        oa = load_cache()
        if not oa:
            print("[main] WARNING: --use-openalex set but cache/openalex_cache.json "
                  "not found. Run: python3 openalex_enrich.py")
        else:
            records, _ = overlay(records, oa)
            rep_path = pathlib.Path(config.OUTPUT_DIR) / "openalex_author_disagreements.md"
            rep_path.write_text(author_disagreements(records))
            print(f"[main] Author-disagreement report: {rep_path}")

    # ── Steps 5–8: Multi-period ───────────────────────────────────────────────
    print(f"\n[5–8/8] Multi-period analysis …")
    from periods import run_all_periods
    all_results = run_all_periods(records, output_root=config.OUTPUT_DIR,
                                  skip_viz=args.skip_viz)

    elapsed = time.time() - t0
    print()
    print("=" * 60)
    print("  PIPELINE COMPLETE")
    for label, res in all_results.items():
        p = res.get("_period", {})
        print(f"  {label:<14}  {p.get('n', '?'):>7,} records  "
              f"({p.get('start')}–{p.get('end')})")
    print(f"\n  Elapsed: {elapsed:.1f}s  |  Output: {config.OUTPUT_DIR}/")
    print("=" * 60)


if __name__ == "__main__":
    main()
