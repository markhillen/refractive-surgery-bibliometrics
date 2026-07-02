#!/usr/bin/env python3
"""
gui.py — Refractive Surgery Bibliometric Analysis — Local Web GUI
====================================================
Zero extra dependencies beyond the standard library.
Launches a local web server and opens the GUI in your browser.

Run:   python3 gui.py
Then:  browser opens automatically at http://localhost:7434
"""

import http.server
import json
import pathlib
import queue
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

# ── Paths — all relative to wherever gui.py lives ────────────────────────────
HERE       = pathlib.Path(__file__).resolve().parent
CACHE_DIR  = HERE / "cache"
DATA_DIR   = HERE / "data"
OUTPUT_DIR = HERE / "output"

for d in [CACHE_DIR, DATA_DIR, OUTPUT_DIR]:
    d.mkdir(parents=True, exist_ok=True)

PORT = 7434

# ── Global state ──────────────────────────────────────────────────────────────
_log_queue:  queue.Queue = queue.Queue()
_run_state = {"running": False, "done": False, "error": False, "pid": None}
_run_lock:   threading.Lock = threading.Lock()

# ── HTML template ─────────────────────────────────────────────────────────────
# Tokens replaced at serve time: __START_YEAR__, __END_YEAR__, __LAST25_START__,
# __LAST10_START__, __LAST5_START__, __SPAN_YEARS__, __PERIODS_JSON__

def _load_html() -> str:
    """Load and return the HTML template from static/index.html."""
    return (HERE / "static" / "index.html").read_text(encoding="utf-8")

# ── (HTML previously embedded here — now in static/index.html) ───────────────

# ── HTTP Request Handler ───────────────────────────────────────────────────────

def _esearch_count(query: str, api_key: str = "") -> int:
    """Return total result count for a PubMed query via esearch."""
    import urllib.request, urllib.parse
    params = {
        "db":      "pubmed",
        "term":    query,
        "retmax":  "0",
        "retmode": "json",
    }
    if api_key:
        params["api_key"] = api_key
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.loads(r.read())
    return int(data["esearchresult"]["count"])

def _list_periods():
    """Return list of period subfolders that contain output."""
    if not OUTPUT_DIR.exists():
        return []
    order = ["all_time", "last_25yr", "last_20yr", "last_15yr", "last_10yr", "last_5yr"]
    found = [d.name for d in OUTPUT_DIR.iterdir() if d.is_dir()]
    return [p for p in order if p in found] + [p for p in found if p not in order]

class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass  # silence access log

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path   = parsed.path
        params = dict(urllib.parse.parse_qsl(parsed.query))

        if path == "/" or path == "/index.html":
            import config as _cfg, json as _json
            ey = _cfg.END_YEAR
            ay = _cfg.ALL_TIME_START
            periods_json = _json.dumps([
                {"name": n, "start": s, "end": e}
                for n, s, e in _cfg.ANALYSIS_PERIODS
            ])
            html = (_load_html()
                .replace("__START_YEAR__",    str(ay))
                .replace("__END_YEAR__",      str(ey))
                .replace("__LAST25_START__",  str(ey - 24))
                .replace("__LAST10_START__",  str(ey - 9))
                .replace("__LAST5_START__",   str(ey - 4))
                .replace("__SPAN_YEARS__",    str(ey - ay + 1))
                .replace("__PERIODS_JSON__",  periods_json)
                .replace("__PROJECT_NAME__",  _cfg.PROJECT_NAME)
                .replace("__BRAND_MAIN__",    _cfg.PROJECT_NAME.replace(" Bibliometrics", ""))
                .replace("__PUBMED_QUERY_JS__", _json.dumps(_cfg.PUBMED_QUERY))
            )
            self._send(200, "text/html", html.encode())

        elif path == "/api/logs":
            lines = []
            try:
                while True:
                    lines.append(_log_queue.get_nowait())
            except queue.Empty:
                pass
            payload = json.dumps({
                "lines": lines,
                "done":  _run_state["done"],
                "error": _run_state["error"],
            }).encode()
            self._send(200, "application/json", payload)

        elif path == "/api/results":
            period = params.get("period", "all_time")
            root   = OUTPUT_DIR.resolve()
            per_p  = (OUTPUT_DIR / period / "analysis.json").resolve()
            # Serve period-specific analysis if available, else fall back to
            # the legacy all_time data/analysis.json
            if per_p.is_relative_to(root) and per_p.exists():
                self._send(200, "application/json", per_p.read_bytes())
            else:
                p = DATA_DIR / "analysis.json"
                if p.exists():
                    self._send(200, "application/json", p.read_bytes())
                else:
                    self._send(404, "text/plain", b"not ready")

        elif path == "/api/figures":
            figs = []
            labels = {
                "fig1_temporal_trends":  "Temporal Trends",
                "fig2_top_journals":     "Top Journals",
                "fig3_top_countries":    "Top Countries",
                "fig4_top_authors":      "Top Authors",
                "fig5_author_keywords":  "Author Keywords",
                "fig5_mesh_terms":       "MeSH Terms",
                "fig5b_mesh_terms":      "MeSH Terms",
                "fig6_pub_types":        "Publication Types",
                "fig7_country_collab":   "Country Collaboration",
                "fig8_keyword_trends":   "Keyword Trends",
                "fig9_institutions":     "Institutions",
                "fig10_author_network":  "Author Network",
            }
            period = params.get("period", "all_time")
            pdir = OUTPUT_DIR / period
            if pdir.exists():
                # Prefer PNG (GUI runs produce PNG); fall back to SVG (CLI runs).
                # Skip PDF — browsers can't display them inline.
                seen = set()
                for ext in ("png", "svg"):
                    for f in sorted(pdir.glob(f"fig*.{ext}")):
                        if f.stem not in seen:
                            figs.append({"name": f.name, "label": labels.get(f.stem, f.stem)})
                            seen.add(f.stem)
            self._send(200, "application/json",
                       json.dumps({"figures": figs, "periods": _list_periods()}).encode())

        elif path == "/api/figure":
            name = params.get("name", "")
            period = params.get("period", "all_time")
            p = (OUTPUT_DIR / period / name).resolve()
            ct_map = {".png": "image/png", ".svg": "image/svg+xml"}
            if p.is_relative_to(OUTPUT_DIR.resolve()) and p.exists() and p.suffix in ct_map:
                self._send(200, ct_map[p.suffix], p.read_bytes())
            else:
                self._send(404, "text/plain", b"not found")

        elif path == "/api/downloads":
            files = []
            period = params.get("period", "all_time")
            scan_dir = OUTPUT_DIR / period
            if not scan_dir.exists():
                scan_dir = OUTPUT_DIR
            for f in sorted(scan_dir.iterdir()) if scan_dir.exists() else []:
                if f.suffix in (".png", ".pdf", ".csv", ".xlsx", ".json", ".md", ".txt", ".html"):
                    sz = f.stat().st_size
                    if sz > 1024*1024:
                        size_str = f"{sz/1024/1024:.1f} MB"
                    elif sz > 1024:
                        size_str = f"{sz/1024:.0f} KB"
                    else:
                        size_str = f"{sz} B"
                    files.append({"name": f.name, "ext": f.suffix.lstrip("."),
                                  "size": size_str})
            self._send(200, "application/json", json.dumps({"files": files}).encode())

        elif path == "/api/download":
            name = params.get("name", "")
            period = params.get("period", "all_time")
            root = OUTPUT_DIR.resolve()
            p = (OUTPUT_DIR / period / name).resolve()
            if not p.is_relative_to(root):
                self._send(403, "text/plain", b"forbidden")
                return
            if not p.exists():
                p = (OUTPUT_DIR / name).resolve()
            if p.is_relative_to(root) and p.exists():
                ct = {
                    ".png":  "image/png",
                    ".pdf":  "application/pdf",
                    ".csv":  "text/csv",
                    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ".json": "application/json",
                    ".md":   "text/markdown",
                    ".html": "text/html",
                }.get(p.suffix, "application/octet-stream")
                self.send_response(200)
                self.send_header("Content-Type", ct)
                self.send_header("Content-Disposition", f'attachment; filename="{p.name}"')
                self.send_header("Content-Length", str(p.stat().st_size))
                self.end_headers()
                self.wfile.write(p.read_bytes())
            else:
                self._send(404, "text/plain", b"not found")

        elif path == "/api/status":
            rec_cache = CACHE_DIR / "records.json"
            cached = 0
            cache_date = ""
            if rec_cache.exists():
                try:
                    data = json.loads(rec_cache.read_text())
                    cached = len(data)
                    import datetime
                    mtime = rec_cache.stat().st_mtime
                    cache_date = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
                except Exception:
                    pass
            self._send(200, "application/json",
                       json.dumps({"cached_records": cached,
                                   "cache_date": cache_date,
                                   "output_dir": str(OUTPUT_DIR)}).encode())

        else:
            self._send(404, "text/plain", b"not found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path   = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length) if length else b""

        if path == "/api/run":
            with _run_lock:
                if _run_state["running"]:
                    self._send(409, "text/plain", b"already running")
                    return
                _run_state["running"] = True
            try:
                cfg = json.loads(body)
            except Exception:
                self._send(400, "text/plain", b"bad json")
                return
            threading.Thread(target=_run_pipeline, args=(cfg,), daemon=True).start()
            self._send(200, "application/json", b'{"ok":true}')

        elif path == "/api/stop":
            _run_state["done"]    = True
            _run_state["running"] = False
            _run_state["error"]   = True
            _log_queue.put("Run stopped by user.")
            self._send(200, "application/json", b'{"ok":true}')

        elif path == "/api/validate_query":
            # Run an esearch count for the given query + date range
            try:
                req_data = json.loads(body)
                q     = req_data.get("query", "").strip()
                sy    = int(req_data.get("start_year", 1950))
                ey    = int(req_data.get("end_year",   2026))
                akey  = req_data.get("api_key", "").strip()
                if not q:
                    self._send(200, "application/json",
                               json.dumps({"error": "Empty query"}).encode())
                    return
                # Build date-bounded query
                full_q = f'({q}) AND ("{sy}/01/01"[PDAT] : "{ey}/12/31"[PDAT])'
                count = _esearch_count(full_q, akey)
                self._send(200, "application/json",
                           json.dumps({"count": count, "query": full_q}).encode())
            except Exception as exc:
                self._send(200, "application/json",
                           json.dumps({"error": str(exc)}).encode())

        else:
            self._send(404, "text/plain", b"not found")

    def _send(self, code, ct, body):
        self.send_response(code)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin",
                         f"http://localhost:{self.server.server_address[1]}")
        self.end_headers()
        self.wfile.write(body)

# ── Pipeline runner (runs in background thread) ────────────────────────────────

def _log(msg: str):
    _log_queue.put(msg)

def _run_pipeline(cfg: dict):
    _run_state.update({"done": False, "error": False})
    _orig_query = None

    try:
        import importlib
        import sys
        sys.path.insert(0, str(HERE))

        # ── Patch config ──────────────────────────────────────────────────
        import config as conf
        _orig_query            = conf.PUBMED_QUERY
        conf.START_YEAR        = cfg["start_year"]
        conf.END_YEAR          = cfg["end_year"]
        conf.FETCH_CITATIONS   = cfg["fetch_citations"]
        conf.MIN_AUTHOR_PUBS   = cfg["min_author_pubs"]
        conf.TOP_N_AUTHORS     = cfg["top_n"]
        conf.TOP_N_COUNTRIES   = cfg["top_n"]
        conf.TOP_N_JOURNALS    = cfg["top_n"]
        conf.TOP_N_KEYWORDS    = 50
        if cfg.get("api_key"):
            conf.NCBI_API_KEY  = cfg["api_key"]

        # Strip any existing date filter from the base query and add the new range.
        import re as _re
        _date_re = _re.compile(
            r'\s+AND\s+\("\d{4}/\d{2}/\d{2}"\[PDAT\]\s*:\s*"\d{4}/\d{2}/\d{2}"\[PDAT\]\)')
        conf.PUBMED_QUERY = _date_re.sub('', _orig_query).rstrip() + \
            f' AND ("{cfg["start_year"]}/01/01"[PDAT] : "{cfg["end_year"]}/12/31"[PDAT])'

        # ── Step 1: Fetch / load ───────────────────────────────────────────
        mode       = cfg.get("source_mode", "pmid")
        cache_file = pathlib.Path(conf.CACHE_DIR) / "records.json"
        use_cache  = (mode == "cache") or (
                        cfg["use_cache"] and cache_file.exists() and not cfg["force_refresh"])

        _log(f"[1/6] Loading records ({cfg['start_year']}–{cfg['end_year']}) …")
        _log(f"  Source mode: {mode}")

        import json as _json

        if use_cache and mode != "query":
            # Use cached records (skip network entirely)
            if not cache_file.exists():
                _log("  ERROR: No cache found. Switch to PMID File or PubMed Query mode first.")
                raise FileNotFoundError("No cached records")
            _log(f"  Loading from cache …")
            with open(cache_file) as f:
                records = _json.load(f)
            _log(f"  Loaded {len(records)} cached records")

        elif mode == "pmid":
            pmid_file = cfg.get("pmid_file", "").strip()
            if not pmid_file:
                _log("  ERROR: No PMID file specified.")
                raise ValueError("No PMID file")
            pf = pathlib.Path(pmid_file)
            if not pf.is_absolute():
                pf = HERE / pf
            if not pf.exists():
                _log(f"  ERROR: PMID file not found: {pf}")
                raise FileNotFoundError(str(pf))
            importlib.invalidate_caches()
            import fetch as fetch_mod
            records = fetch_mod.run_fetch_from_pmids(
                str(pf), api_key=conf.NCBI_API_KEY, force_refresh=True)

        elif mode == "query":
            raw_query = cfg.get("pubmed_query", "").strip()
            if not raw_query:
                _log("  ERROR: No PubMed query provided.")
                raise ValueError("Empty query")
            # Build date-bounded full query and set on config
            full_query = (f'({raw_query}) AND '
                          f'("{cfg["start_year"]}/01/01"[PDAT] : "{cfg["end_year"]}/12/31"[PDAT])')
            conf.PUBMED_QUERY = full_query
            _log(f"  Query: {raw_query[:100]}{'…' if len(raw_query)>100 else ''}")
            import fetch as fetch_mod
            records = fetch_mod.run_fetch(
                api_key=conf.NCBI_API_KEY, force_refresh=True)

        else:
            _log(f"  ERROR: Unknown source mode: {mode}")
            raise ValueError(f"Unknown mode: {mode}")

        # Filter to date range. In multi-period mode use ALL_TIME_START so
        # pre-slider records (e.g. 1988 PRK papers) are retained for
        # the all-time window; periods.py then slices each window.
        import config as _cfgmod
        _filt_start = (getattr(_cfgmod, "ALL_TIME_START", cfg["start_year"])
                       if cfg.get("multi_period", True) else cfg["start_year"])
        _log(f"  Filtering to {_filt_start}–{cfg['end_year']} …")
        before = len(records)
        def _yr(r):
            try:
                return int(r.get("year") or 0)
            except (ValueError, TypeError):
                return 0
        records = [r for r in records
                   if _filt_start <= _yr(r) <= cfg["end_year"]]
        _log(f"  {len(records)} records in range (dropped {before - len(records)})")

        if not records:
            _log("  ERROR: No records in selected date range.")
            raise ValueError("No records in range")

        # ── Step 2: Author disambiguation ─────────────────────────────────
        _log("[2/6] Disambiguating authors …")
        import disambiguate as da
        records, _ = da.assign_author_ids(records)

        # ── Step 3: Country enrichment ────────────────────────────────────
        _log("[3/6] Extracting countries from affiliations …")
        import geo
        records = geo.enrich_countries(records)

        # ── Step 4: Citations ─────────────────────────────────────────────
        if cfg["fetch_citations"]:
            _log("[4/6] Fetching citation counts from CrossRef …")
            import citations as cit
            records = cit.enrich_citations(records)
        else:
            _log("[4/6] Citation fetch skipped.")

        # ── Force PNG figures so they display inline in the browser ────────
        conf.FIGURE_FORMAT = "png"

        multi = cfg.get("multi_period", True)

        if multi:
            # ── Steps 5–6: Multi-period analysis ──────────────────────────
            _log("[5/6] Running multi-period analysis …")
            # Build period windows from ALL_TIME_START so "all time" reflects
            # the full indexed refractive surgery literature (1988–present). Rolling windows
            # are only included if meaningfully shorter than the all-time span.
            e        = cfg["end_year"]
            at_start = getattr(conf, "ALL_TIME_START", cfg["start_year"])
            windows  = [("all_time", at_start, e)]
            for label, span in [("last_25yr", 25), ("last_20yr", 20),
                                 ("last_15yr", 15), ("last_10yr", 10),
                                 ("last_5yr", 5)]:
                w_start = e - (span - 1)
                if w_start > at_start:          # skip windows == all-time
                    windows.append((label, w_start, e))
            conf.ANALYSIS_PERIODS = windows
            _log(f"  Periods: {[w[0] for w in windows]} "
                 f"(all-time from {at_start})")
            import periods as per
            # Figures need matplotlib; if missing, still produce CSV/Excel reports
            try:
                import matplotlib  # noqa: F401
                _skip_viz = False
            except ImportError:
                _skip_viz = True
                _log("  WARNING: matplotlib not found — skipping figures, "
                     "generating data reports only.")
                _log("  To enable figures, install it for this Python:")
                _log(f"    {sys.executable} -m pip install matplotlib networkx "
                     "--break-system-packages")
            _log("[6/6] Generating " +
                 ("reports per period (no figures) …" if _skip_viz
                  else "figures and reports per period …"))
            all_results = per.run_all_periods(
                records, output_root=str(conf.OUTPUT_DIR), skip_viz=_skip_viz)

            _log("=" * 50)
            _log("PIPELINE COMPLETE ✓")
            for label, res in all_results.items():
                p = res.get("_period", {})
                _log(f"  {label:<12} {p.get('n','?'):>5} records "
                     f"({p.get('start','?')}–{p.get('end','?')})")
            _log(f"  Outputs in   : {conf.OUTPUT_DIR}/<period>/")
            # Save all_time analysis.json for the results panel fallback.
            # DATA_DIR is not defined in RS config — fall back to output/all_time/.
            import json as _json
            at = all_results.get("all_time")
            if at:
                data_dir = pathlib.Path(getattr(conf, "DATA_DIR", None) or
                                        pathlib.Path(conf.OUTPUT_DIR) / "all_time")
                data_dir.mkdir(parents=True, exist_ok=True)
                with open(data_dir / "analysis.json", "w") as f:
                    _json.dump(at, f, indent=2, default=str)
            _run_state.update({"running": False, "done": True, "error": False})

        else:
            # ── Single-window mode (legacy) ───────────────────────────────
            _log("[5/6] Running bibliometric analysis …")
            import analyze as an
            results = an.run_analysis(records)

            import json as _json
            pathlib.Path(conf.DATA_DIR).mkdir(parents=True, exist_ok=True)
            with open(pathlib.Path(conf.DATA_DIR) / "analysis.json", "w") as f:
                _json.dump(results, f, indent=2, default=str)

            _log(f"  {results['n_records']} records · "
                 f"{len(results['authors'])} authors · "
                 f"{len(results['journals'])} journals · "
                 f"{len(results['countries'])} countries")

            # Write single-window output to output/all_time/ for consistency
            single_dir = pathlib.Path(conf.OUTPUT_DIR) / "all_time"
            single_dir.mkdir(parents=True, exist_ok=True)
            _orig_out = conf.OUTPUT_DIR
            conf.OUTPUT_DIR = str(single_dir)

            _log("[6/6] Generating figures and reports …")
            try:
                import visualize as viz
                viz.run_visualizations(results, records)

                import report as rep
                rep.generate_reports(results)
            finally:
                conf.OUTPUT_DIR = _orig_out

            _log("=" * 50)
            _log("PIPELINE COMPLETE ✓")
            _log(f"  Publications : {results['n_records']}")
            _log(f"  Authors      : {len(results['authors'])}")
            _log(f"  Journals     : {len(results['journals'])}")
            _log(f"  Countries    : {len([c for c in results['countries'] if c['country']!='Unknown'])}")
            _log(f"  Outputs in   : {conf.OUTPUT_DIR}/all_time/")
            _run_state.update({"running": False, "done": True, "error": False})

    except Exception as exc:
        import traceback
        _log(f"ERROR: {exc}")
        for line in traceback.format_exc().splitlines():
            _log(line)
        _run_state.update({"running": False, "done": True, "error": True})
    finally:
        # Restore PUBMED_QUERY so the next GUI run starts from the original base string
        if _orig_query is not None:
            try:
                import config as conf
                conf.PUBMED_QUERY = _orig_query
            except Exception:
                pass

# ── Server launch ─────────────────────────────────────────────────────────────

def main():
    # ── Warn about missing packages up front (GUI still launches) ──────────────
    try:
        import check_deps
        missing = check_deps.check(verbose=True)
        if missing:
            print("  NOTE: the GUI will load, but analysis runs will fail or "
                  "skip outputs until the above packages are installed.\n")
    except ImportError:
        pass

    port = PORT
    for _attempt in range(20):
        try:
            server = HTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            port += 1
    else:
        print(f"ERROR: could not find a free port near {PORT}. "
              "Close any other running copies and try again.")
        sys.exit(1)
    url    = f"http://localhost:{server.server_address[1]}"

    print(f"""
╔══════════════════════════════════════════════════╗
║     Refractive Surgery Bibliometrics — Local Web GUI    ║
╠══════════════════════════════════════════════════╣
║  Server: {url:<40}║
║  Press Ctrl+C to quit                            ║
╚══════════════════════════════════════════════════╝
""")

    # Open browser after short delay
    def _open():
        time.sleep(0.8)
        webbrowser.open(url)
    threading.Thread(target=_open, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")

if __name__ == "__main__":
    main()
