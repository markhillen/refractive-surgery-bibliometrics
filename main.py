#!/usr/bin/env python3
"""
main.py — Refractive Surgery Bibliometric Analysis Pipeline
=============================================
Orchestrates the full analysis pipeline:

  1. Fetch PubMed records (cached)          — query: corneal laser refractive surgery
  2. Relevance filtering                    — expel non-ophthalmic records
  3. Author disambiguation                  — 4-layer heuristic + safelists
  4. Country enrichment                     — affiliation → ISO country
  5. Citation enrichment (CrossRef)         — by DOI
  6. Multi-period bibliometric analysis     — all-time / last 20/15/10/5 years
  7. Visualization                          — figures per period (PDF)
  8. Report generation                      — CSV + Excel per period
  9. Period comparison summary              — headline metrics across all windows

Usage:
  python3 main.py --api-key YOUR_NCBI_KEY
  python3 main.py --api-key YOUR_NCBI_KEY --refresh          # force re-download
  python3 main.py --skip-fetch                               # use cached data
  python3 main.py --skip-citations                           # skip CrossRef
  python3 main.py --pmid-file pmids_expanded.txt             # use PMID list
  python3 main.py --period all_time                          # single period only
  python3 main.py --skip-fetch --skip-citations              # figures/reports only
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
        epilog=__doc__
    )
    parser.add_argument("--api-key",        default="",   help="NCBI API key")
    parser.add_argument("--pmid-file",      default="",   help="Path to PMID list file")
    parser.add_argument("--refresh",        action="store_true", help="Force re-download")
    parser.add_argument("--skip-fetch",     action="store_true", help="Use cached records only")
    parser.add_argument("--skip-citations", action="store_true", help="Skip CrossRef lookup")
    parser.add_argument("--skip-viz",       action="store_true", help="Skip chart generation")
    parser.add_argument("--use-openalex",   action="store_true",
                        help="Hybrid mode: overlay OpenAlex citations + ROR country "
                             "(needs cache/openalex_cache.json from openalex_enrich.py)")
    parser.add_argument("--period",         default="",
                        help="Run a single period only (e.g. all_time, last_10yr)")
    parser.add_argument("--start-year",     type=int, default=None,
                        help="Override ALL_TIME_START in config")
    parser.add_argument("--end-year",       type=int, default=None,
                        help="Override END_YEAR in config")
    parser.add_argument("--reparse",        action="store_true",
                        help="Rebuild records.json from the cached PubMed XML (no network)")
    parser.add_argument("--screen-only",    action="store_true",
                        help="Stop after fetch/reparse + relevance filter (writes the exclusion log)")
    parser.add_argument("--strict-screening", action="store_true",
                        help="Fail if output/screening_queue.csv is non-empty")
    parser.add_argument("--allow-stale",    action="store_true",
                        help="Use a cache written by an older parser schema")
    parser.add_argument("--no-sensitivity", action="store_true",
                        help="Skip the SDC / sensitivity tables (output/sdc/)")
    parser.add_argument("--skip-benchmarks", action="store_true",
                        help="Sensitivity tables without the two PubMed-count benchmarks (offline)")
    args = parser.parse_args()

    # ── Verify dependencies before doing any work ──────────────────────────────
    try:
        import check_deps
        if check_deps.check():
            sys.exit(1)
    except ImportError:
        pass  # check_deps.py not present — proceed and let imports fail naturally

    import config

    # ── Config overrides ──────────────────────────────────────────────────────
    if args.api_key:
        config.NCBI_API_KEY = args.api_key
    if args.skip_citations:
        config.FETCH_CITATIONS = False
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

    # Filter to a single period if requested
    if args.period:
        config.ANALYSIS_PERIODS = [
            p for p in config.ANALYSIS_PERIODS if p[0] == args.period
        ]
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

    if args.reparse:
        from fetch import run_reparse
        records = run_reparse()
        for p in (cited_path, disamb_path):      # derived caches are now stale
            if p.exists():
                p.unlink()
    elif args.skip_fetch:
        import fetch as _fetch
        manifest = _fetch.read_manifest() or {}
        if manifest.get("schema") != config.CACHE_SCHEMA and not args.allow_stale:
            print(f"[main] ERROR: cache/manifest.json schema {manifest.get('schema')!r} != "
                  f"{config.CACHE_SCHEMA}. The cached records were written by an older "
                  f"parser. Re-run with --reparse (offline) or --refresh, or pass --allow-stale.")
            sys.exit(1)
        # Newest of the derived caches wins, but never one older than records.json
        candidates = [p for p in (cited_path, disamb_path, raw_path) if p.exists()]
        if not candidates:
            print("[main] ERROR: No cached records. Run without --skip-fetch first.")
            sys.exit(1)
        base_m = raw_path.stat().st_mtime if raw_path.exists() else 0
        fresh = [p for p in candidates if p.stat().st_mtime >= base_m] or [raw_path]
        p = max(fresh, key=lambda q: q.stat().st_mtime)
        print(f"[main] Loading {p.name} from cache …")
        with open(p) as f:
            records = json.load(f)
        print(f"[main] {len(records):,} records loaded")
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
    print(f"[main] {len(records):,} records after fetch + filtering")
    if args.strict_screening:
        q = pathlib.Path(config.OUTPUT_DIR) / "screening_queue.csv"
        n_q = max(0, sum(1 for _ in open(q, encoding="utf-8")) - 1) if q.exists() else 0
        if n_q:
            print(f"[main] ERROR: {n_q} records await manual screening ({q}). "
                  f"Add decisions to data/manual_screening.csv and re-run --reparse.")
            sys.exit(2)
    if args.screen_only:
        print("[main] --screen-only: stopping after relevance filter")
        return

    # ── Step 2: Author disambiguation ─────────────────────────────────────────
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
        print("[main] Disambiguation complete")

    # ── Step 3: Country enrichment ────────────────────────────────────────────
    print(f"\n[3/8] Enriching countries …")
    from geo import enrich_countries
    records = enrich_countries(records)
    print("[main] Country enrichment complete")

    # ── Step 4: Citation enrichment ───────────────────────────────────────────
    print(f"\n[4/8] Citation enrichment …")
    if config.FETCH_CITATIONS:
        from citations import enrich_citations
        records = enrich_citations(records)
        with open(cited_path, "w") as f:
            json.dump(records, f, cls=_SetEncoder)
        print("[main] Citations enriched and cached")
    else:
        print("[main] Skipped (--skip-citations)")

    # ── Step 4.5: OpenAlex hybrid overlay ─────────────────────────────────────
    if args.use_openalex:
        print(f"\n[4.5] Applying OpenAlex hybrid overlay …")
        from openalex_integrate import overlay, load_cache, author_disagreements
        oa = load_cache()
        if not oa:
            print("[main] WARNING: --use-openalex set but cache/openalex_cache.json "
                  "not found. Run: python3 openalex_enrich.py")
        else:
            records, _ = overlay(records, oa)
            report = author_disagreements(records)
            rep_path = pathlib.Path(config.OUTPUT_DIR) / "openalex_author_disagreements.md"
            rep_path.write_text(report)
            print(f"[main] Author-disagreement report: {rep_path}")

    # citation-source label for figure axes
    srcs = {rec.get("citation_source") for rec in records if rec.get("citation_count") is not None}
    config.CITATION_SOURCE_LABEL = ("OpenAlex" if srcs <= {"openalex"} else
                                    "CrossRef" if srcs <= {"crossref", None} else
                                    "OpenAlex; CrossRef/ROR fallback, see SDC")

    if getattr(config, "IMPUTE_MISSING_AFFILIATIONS", False):
        import impute
        _imp = impute.impute_affiliations(
            records, window=getattr(config, "IMPUTE_WINDOW_YEARS", 2))
    else:
        _imp = None

    # Where PubMed gives no affiliation for the first author, OpenAlex's country
    # is a guess from its own author profile.  If the affiliation that author
    # gives on another record within two years (imputed above) names a
    # different country explicitly, that country is used instead.  Records
    # OpenAlex could not resolve stay unresolved: imputation never creates a
    # country, it only arbitrates between two sources.
    if _imp is not None:
        from geo import extract_country_with_source
        from openalex_integrate import _GREATER_CHINA
        n_fix = 0
        for rec in records:
            au = (rec.get("authors") or [None])[0]
            if not au or au.get("affil_source") != "imputed" or rec.get("country_source") != "openalex_ror":
                continue
            c, src = extract_country_with_source(au.get("affils") or [])
            if src == "affil_country_name" and c != rec.get("country") and \
                    not (c in _GREATER_CHINA and rec.get("country") in _GREATER_CHINA):
                rec["country"] = c
                rec["country_source"] = "imputed_affil_country_over_openalex"
                n_fix += 1
        print(f"[main] first-author country corrected from the author's own nearby affiliation: {n_fix} records")
        _imp["country_corrected_from_imputed_affiliation"] = n_fix

    # ── Attribution audit table (one row per record), written after the
    #    imputation-based country correction so it matches every country table ──────────────────────────
    import csv as _csv
    attr_path = pathlib.Path(config.OUTPUT_DIR) / "record_attribution.csv"
    with open(attr_path, "w", newline="", encoding="utf-8") as fh:
        w = _csv.writer(fh)
        w.writerow(["pmid", "year", "country", "country_source", "countries_all",
                    "citation_count", "citation_source", "oa_matched"])
        for rec in records:
            w.writerow([rec.get("pmid"), rec.get("year"), rec.get("country"),
                        rec.get("country_source", ""), "|".join(rec.get("countries_all", []) or []),
                        rec.get("citation_count"), rec.get("citation_source", ""),
                        rec.get("oa_matched", "")])
    print(f"[main] Attribution table: {attr_path}")

    # Final analysed record set (after overlay and imputation), so that tables
    # built outside the pipeline read exactly what the analysis read.
    with open(pathlib.Path(config.CACHE_DIR) / "records_final.json", "w") as f:
        json.dump(records, f, cls=_SetEncoder)
    if _imp:
        with open(pathlib.Path(config.OUTPUT_DIR) / "imputation_summary.json", "w") as f:
            json.dump(_imp, f, indent=1)

    # ── Steps 5–8: Multi-period analysis, viz, reports ────────────────────────
    print(f"\n[5–8/8] Running multi-period analysis …")
    from periods import run_all_periods
    all_results = run_all_periods(
        records,
        output_root=config.OUTPUT_DIR,
        skip_viz=args.skip_viz,
    )

    # ── Step 9: SDC / sensitivity tables from the same records ────────────────
    if not args.no_sensitivity:
        print(f"\n[9/9] Sensitivity analyses and SDC tables …")
        import sensitivity
        from fetch import read_manifest
        sensitivity.run_all(records, read_manifest(), api_key=config.NCBI_API_KEY,
                            skip_benchmarks=args.skip_benchmarks)
        # The manuscript reports producer-level detail for the recent window,
        # so every SDC table is also written for that window.
        rp = dict((p[0], p) for p in config.ANALYSIS_PERIODS).get(getattr(config, "RECENT_PERIOD", "last_5yr"))
        if rp:
            _, y0, y1 = rp
            def _yr(r):
                try: return int(r.get("year") or 0)
                except ValueError: return 0
            recent = [r for r in records if y0 <= _yr(r) <= y1]
            print(f"\n[9/9] SDC tables for the recent window {y0}–{y1} ({len(recent):,} records) …")
            sensitivity.run_all(recent, read_manifest(), api_key=config.NCBI_API_KEY,
                                skip_benchmarks=args.skip_benchmarks,
                                out_dir=pathlib.Path(config.OUTPUT_DIR) / "sdc" / f"recent_{y0}_{y1}")

    # ── Step 10: procedure mix and field share (refractive-surgery specific) ──
    import procedures
    procedures.run(records)
    if not args.skip_benchmarks:
        import field_share
        field_share.run(records, api_key=config.NCBI_API_KEY)

    # ── Summary ───────────────────────────────────────────────────────────────
    elapsed = time.time() - t0
    print()
    print("=" * 60)
    print("  PIPELINE COMPLETE")
    for label, res in all_results.items():
        p = res.get("_period", {})
        print(f"  {label:<14}  {p.get('n', '?'):>6,} records  "
              f"({p.get('start', '?')}–{p.get('end', '?')})")
    print(f"\n  Elapsed:   {elapsed:.1f}s")
    print(f"  Output:    {config.OUTPUT_DIR}/")
    print("=" * 60)


if __name__ == "__main__":
    main()
