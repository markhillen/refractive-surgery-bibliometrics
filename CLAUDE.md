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

Corneal laser refractive surgery (surface ablation, LASIK, KLEx/SMILE, wavefront-
and topography-guided, laser presbyopia correction) and eyes that have had it.
Excludes lens-based refractive surgery, incisional/implant corneal procedures,
PTK without refractive aim, femtosecond keratoplasty/cataract, CXL alone, errata.
Decision rule: `validation/screening/decision_rule.md`.

Start year: 1988 (first clinical excimer PRK reports). DO NOT lower this.

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

- `ALL_TIME_START = 1988`, `END_YEAR = 2025` (frozen for the JRS submission)
- Query v2 = `PUBMED_QUERY_SPECIFIC OR (PUBMED_QUERY_GENERIC AND PUBMED_QUERY_ANCHOR)`, no NOT block
- `ANALYSIS_PERIODS`: all_time + last_25/20/15/10/5yr; `RECENT_PERIOD = "last_5yr"`
- `HIGHLIGHT_JOURNAL = None` (do not single out the target journal in figures)
- `MIN_KEYWORD_FREQ = 20` / `MIN_COOCCURRENCE = 20`

## Data conventions

- Institutions use first-author attribution (consistent with kc_biblio/cxl_biblio).
- Citation accumulation bias applies: recent years show lower cites/paper.
- The corpus is large (~15,000–25,000 expected). Full CrossRef enrichment
  will be slow; last_5yr enrichment first is recommended.

## Published analysis (JRS submission, 7 Oct 2026)

- 14,112 retrieved → 12,887 analyzed (`data/final_pmids.txt`); screening log in
  `data/screening_summary.txt`. 1,840 records screened individually (Claude
  proposed; MH confirmed all 847 exclusions; inclusions not checked).
- Extra steps beyond the shared engine: `procedures.py` (multi-label procedure
  families), `field_share.py` (per 1,000 PubMed ophthalmology records),
  `validate_pubmed.py` (PubMed recount), `manuscript_figures.py` (Figs 1–5).
- Run: `python3 main.py --skip-fetch --skip-citations --use-openalex`; after a
  screening change use `--reparse --screen-only` first; after a disambiguation
  change delete `cache/records_disambig.json` and `cache/records_cited.json`.
- OpenAlex rate limits by IP: if the cloud IP gets 429, run `openalex_batch.py`
  elsewhere in time-limited slices (`--max-seconds 160`).

## Outstanding tasks

- Journal of Refractive Surgery submission and revision.
