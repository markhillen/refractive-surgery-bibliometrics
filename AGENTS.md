# AGENTS.md — Keratoconus Bibliometrics

Standing context for Codex sessions in this repo. Read this first.

## What this is

A bibliometric analysis pipeline for the **keratoconus (KC)** research
literature, 1950–present. It pulls records from PubMed, disambiguates authors,
enriches country + citation data, and produces figures, CSVs, and an Excel
workbook. Output feeds a manuscript targeting **Contact Lens & Anterior Eye
(CLAE)** (Elsevier; EIC Prof. Shehzad Naroo).

There is a **sister project**, `cxl_biblio` (corneal cross-linking → *Cornea*),
with near-identical architecture. Changes here often need porting there and vice
versa. `cxl_biblio` is usually the lead — features tend to land there first.

## Environment (important — non-standard)

- **System Python, not a venv.** A `venv/` may appear "active" in the prompt but
  `source venv/bin/activate` fails — it's broken/stale. Treat this as a system
  Python install.
- **pip needs `--break-system-packages`:**
  `python3 -m pip install -r requirements.txt --break-system-packages`
- **Dependencies are minimal — only four:** `numpy`, `matplotlib`, `networkx`,
  `openpyxl`. HTTP uses the **standard-library `urllib`** — do NOT add
  `requests`. `pandas`/`seaborn`/`scipy` are NOT used; don't reintroduce them
  (the old requirements.txt over-declared these — it has been corrected).
  `pyvis` is optional (interactive network only).
- Verify the environment any time with `python3 check_deps.py`. `main.py` runs
  this guard at startup; `gui.py` warns but still launches.
- **NCBI API key:** read from the `NCBI_API_KEY` env var (or `--api-key`).
  10 req/s with a key, 3 without. Key on file:
  `<set via the NCBI_API_KEY environment variable>`.

## How to run

```bash
# Full run
python3 main.py --api-key "$NCBI_API_KEY"

# Reuse cached records + citations (fast; most common during dev)
python3 main.py --skip-fetch --skip-citations

# Single period only, or a custom window
python3 main.py --period last_25yr
python3 main.py --start-year 1990 --end-year 2010

# Local web GUI (slider runs 1950–present; multi-period toggle)
python3 gui.py        # opens http://localhost:7432

# Synthetic-data smoke test (no network)
python3 demo.py
```

## Architecture

8-step pipeline, one module per concern:

```
fetch.py        PubMed E-utilities (urllib), PMID list or query → records.json cache
disambiguate.py 4-layer author ID (ORCID / forename / co-author overlap / institution)
                with KNOWN_DISTINCT safelists. Note: Hillen M sits ~rank 68 and needs
                a COI declaration in the manuscript.
geo.py          country from affiliation strings
citations.py    CrossRef citation counts by DOI (api.crossref.org)
analyze.py      all metrics — temporal, authors, journals, countries, keywords,
                MeSH, institutions (FIRST-AUTHOR attribution), pub_types, languages
periods.py      slices records into config.ANALYSIS_PERIODS, runs analyze+report+viz per window
visualize.py    matplotlib figures (+ optional pyvis network)
report.py       CSVs + multi-sheet Excel workbook
config.py       all knobs (see below)
main.py         CLI orchestration
gui.py          local web server + single-file HTML/JS UI
check_deps.py   startup dependency guard
demo.py         synthetic records for testing
```

## config.py essentials

- `ALL_TIME_START = 1950` — keratoconus literature is old; 1950 captures the full
  indexed record. **Do not raise this to 2001** (that's CXL's value; KC's whole
  point is the deeper history).
- `END_YEAR = date.today().year` (auto).
- `ANALYSIS_PERIODS`: all_time **plus last_25yr** and last_20/15/10/5yr. KC keeps
  last_25yr because 2001–present is genuinely shorter than 1950–present. (CXL
  omits last_25yr — that difference is intentional, not a bug.)
- `OUTPUT_DIR = output/` (overridable via `KC_OUTPUT_DIR`). Per-period results
  land in `output/<period>/`.
- `FIGURE_FORMAT = "pdf"` for CLI. The GUI overrides this to `png` so figures
  render inline in the browser — PDFs won't show in `<img>`.

## Data conventions / facts to preserve

- Prior run (1950–2026 era): all_time ~9,622 publications; last_5yr ~2,544.
- **CLAE has the highest citation efficiency among the top-20 journals**
  (~22.3 cites/paper) — this is the key selling point for the CLAE submission;
  preserve it if touching journal analysis.
- Institutions use **first-author attribution** (consistent with cxl_biblio).
- Citation accumulation bias applies here too: recent years show lower
  cites/paper purely because less time has elapsed — not a real decline.
- Languages stored as ISO 639-2 codes, mapped to display names in `report.py`.
- Full citation enrichment across all ~9,622 DOIs is slow and historically only
  the last_5yr window has been fully enriched — non-recent windows may show
  pending citation metrics. A full enrichment run is a known outstanding task.

## Known issues / tech debt (shared with cxl_biblio — fix opportunistically)

1. **BUG (active):** `periods._write_period_summary` reads `res.get("summary", {})`,
   but `analyze.run_analysis` returns no `"summary"` key — so `period_comparison.csv`
   has empty metric columns. Fix: compute totals from existing keys
   (`len(res["authors"])`, `sum(res["temporal"]["citations"])`, etc.).
2. `config.OUTPUT_DIR = …` mutate-and-restore (periods.py, gui.py, main.py) is not
   thread-safe; the GUI runs on a daemon thread. Prefer an explicit `output_dir`
   param. `PUBMED_QUERY.rsplit('AND (')` string surgery is fragile.
3. Function-level imports + `importlib.reload` hide the dependency graph.
4. `_filter_by_period` silently drops unparseable-year records without counting.
5. **No tests** — wire `demo.py` into pytest with assertions.
6. The KC `README.md` was not updated with the new install instructions in the
   last pass (CXL's was) — worth syncing.

## Outstanding KC-specific tasks

- Full CrossRef enrichment run across all DOIs (to fill non-last_5yr windows).
- KC SDC document not yet created (CXL has one).
- KC cover letter has pending fill-ins (corresponding author details; suggested
  reviewers Kymionis / Hashemi / Ambrósio).

## Conventions

- Match existing style; no new heavy dependencies (the four-package rule).
- When editing `report.py`, `gui.py`, or `check_deps.py`, check whether the same
  change is needed in `cxl_biblio` — they're kept in parity.
- Commit messages: short imperative summary line; mention which pipeline stage.
- Private research repo on GitHub (`markhillen/keratoconus-bibliometrics`).
