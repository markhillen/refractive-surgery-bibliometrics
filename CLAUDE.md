# CLAUDE.md — Refractive Surgery Bibliometrics

Standing context for Claude Code sessions in this repo.

## What this is

A bibliometric analysis pipeline for the **corneal laser refractive surgery**
research literature, 1988–present. It pulls records from PubMed, disambiguates
authors, enriches country + citation data, and produces figures, CSVs, and an
Excel workbook. Output feeds a manuscript targeting the **Journal of Refractive
Surgery** (JRS; Slack).

Sister projects: `kc_biblio` (keratoconus → *CLAE*), `cxl_biblio` (CXL → *Cornea*).
All three share near-identical pipeline architecture. Changes should be ported
across projects where relevant.

## Scope

Covers: LASIK, PRK, SMILE/ReLEx, LASEK, TransPRK, excimer laser surgery,
wavefront-guided and topography-guided procedures, presbyopia laser correction
(PRESBYOND/presbyLASIK). Excludes: cataract/IOL surgery, phakic IOL,
orthokeratology, contact lens wear.

Start year: 1988 (first clinical excimer PRK trials). DO NOT lower this —
the literature does not predate it meaningfully.

## Environment

- System Python, no venv. pip needs `--break-system-packages`.
- Dependencies: `numpy`, `matplotlib`, `networkx`, `openpyxl` only.
- NCBI API key: `NCBI_API_KEY` env var. Key: `<set via the NCBI_API_KEY environment variable>`
- GUI runs at http://localhost:**7434** (not 7432 — that's kc_biblio/cxl_biblio).

## How to run

```bash
# Full run from PubMed query
python3 main.py --api-key "$NCBI_API_KEY"

# Reuse cached records (fast)
python3 main.py --skip-fetch --skip-citations

# Local web GUI
python3 gui.py        # opens http://localhost:7434
```

## Architecture

Identical to kc_biblio — 8-step pipeline (fetch → disambiguate → geo →
citations → analyze → periods → visualize → report). See kc_biblio/CLAUDE.md
for full architecture notes.

## config.py essentials

- `ALL_TIME_START = 1988`
- `END_YEAR = date.today().year`
- `ANALYSIS_PERIODS`: all_time + last_25/20/15/10/5yr
- `OUTPUT_DIR` overridable via `RS_OUTPUT_DIR`
- `CACHE_DIR` overridable via `RS_CACHE_DIR`
- `FIGURE_FORMAT = "pdf"` for CLI; GUI overrides to `png`
- `MIN_KEYWORD_FREQ = 20` / `MIN_COOCCURRENCE = 20` (higher — larger corpus)

## Data conventions

- Institutions use first-author attribution (consistent with kc_biblio/cxl_biblio).
- Citation accumulation bias applies: recent years show lower cites/paper.
- The corpus is large (~15,000–25,000 expected). Full CrossRef enrichment
  will be slow; last_5yr enrichment first is recommended.

## Outstanding tasks

- First full fetch and analysis run.
- Manuscript draft targeting Journal of Refractive Surgery.
- GitHub repo: `markhillen/refractive-surgery-bibliometrics` (to be created).
