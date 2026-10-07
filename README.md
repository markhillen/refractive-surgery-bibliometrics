# Refractive Surgery Bibliometrics

A reproducible, open-source bibliometric analysis pipeline for the global
scientific literature on **corneal laser refractive surgery** (1988–present).
Pulls data from PubMed (corpus) and OpenAlex (citations, countries, institutions; CrossRef retained as a cross-check) — no Web of Science or Scopus subscription required.

---

## Quick start (no technical knowledge needed)

**Double-click `Start.command`** — it sets up everything (a private Python
environment and the required packages, about a minute the first time) and opens
the app in your browser. See `QUICKSTART.txt` for troubleshooting.

**First run:** a fresh download does *not* include the dataset — it ships the
PubMed ID list instead. On first use, open the app and click **Run Analysis**
(PMID-file mode, with `pmids_expanded.txt`) to build the dataset. This takes a
few minutes; an NCBI API key (below) just makes it faster. After that, results
load instantly from the local cache.

---

## Requirements

**Python 3.10 or later.** Check: `python3 --version`

```bash
python3 -m pip install -r requirements.txt
# On system-managed Python (macOS Homebrew, Debian/Ubuntu):
python3 -m pip install -r requirements.txt --break-system-packages
```

No `requests`, `pandas`, `seaborn`, or `scipy` required. Optional `pyvis`
for interactive HTML co-authorship network.

Verify before running:
```bash
python3 check_deps.py
```

---

## NCBI API Key

Free at <https://www.ncbi.nlm.nih.gov/account/> → Settings → API Key Management.
10 req/s with key, 3 without. Pass via `--api-key` or `NCBI_API_KEY` env var.

---

## Data Sources

### Option A — PubMed query (recommended)
```bash
python3 main.py --api-key YOUR_KEY
```
Uses the query in `config.py` covering LASIK, PRK, SMILE/ReLEx, LASEK,
TransPRK, and related corneal laser procedures (1988–present).

### Option B — PMID list file
```bash
python3 main.py --api-key YOUR_KEY --pmid-file pmids_expanded.txt
```

### Option C — Cached records only (fastest, no network)

> Note: a fresh download has no cache yet — run Option A once first.
```bash
python3 main.py --skip-fetch --skip-citations
```

---

## Running the Pipeline

### Launch the web GUI

```bash
python3 gui.py
```

Opens a local app in your browser (date-range sliders, results tables, figures,
and downloadable CSV/Excel). Non-technical users can just double-click
`Start.command` instead (see Quick start).



### Full run (fetch + citations + analysis)
```bash
python3 main.py --api-key YOUR_KEY
```

### OpenAlex hybrid enrichment (recommended)

By default the pipeline can also use **OpenAlex** — a free, CC0-licensed index
of works, authors, institutions, and citations — instead of CrossRef. OpenAlex
resolves author affiliations to ROR institution IDs and clean country codes
(fixing affiliation-string errors) and supplies citation counts, all keyed to
our records by DOI/PMID.

```bash
# 1. fetch the corpus from PubMed (uses the included PMID list)
python3 main.py --api-key YOUR_KEY --pmid-file pmids_expanded.txt --skip-citations
# 2. enrich with OpenAlex (country + institution + citations)
python3 openalex_enrich.py
# 3. regenerate the analysis in hybrid mode
python3 main.py --skip-fetch --skip-citations --use-openalex
```

`openalex_compare.py` prints a side-by-side of OpenAlex vs the current numbers.
CrossRef counts are retained in parallel as a cross-check. OpenAlex requires a
free API key as of 2026 (single-record lookups by DOI/PMID remain free).

### Skip CrossRef (fast first pass, ~5–10 min)
```bash
python3 main.py --api-key YOUR_KEY --skip-citations
```

### Re-run analysis on cached data (~60 s)
```bash
python3 main.py --skip-fetch --skip-citations
```

### Single time window only
```bash
python3 main.py --skip-fetch --skip-citations --period last_5yr
```

---

## GUI (browser-based interface)

```bash
python3 gui.py
```

Opens at <http://localhost:7434>

---

## Scope

A record is in scope if corneal laser refractive surgery, or eyes that have had
it, is a subject of the work: surface ablation (PRK, LASEK, epi-LASIK,
transepithelial PRK), LASIK (including femtosecond-flap LASIK), keratorefractive
lenticule extraction (KLEx: SMILE and other lenticule procedures),
wavefront- and topography-guided treatments, and laser presbyopia correction.
Papers on eyes after these procedures (for example, IOL power calculation after
LASIK, or ectasia after laser refractive surgery) are included.

Excluded: lens-based refractive surgery (phakic IOLs, refractive lens exchange),
incisional and implant corneal procedures unless laser surgery is also a subject,
phototherapeutic keratectomy without a refractive aim, femtosecond laser
keratoplasty and cataract surgery, cross-linking alone, errata, and records that
mention laser refractive surgery only in passing. The written decision rule is
in `validation/screening/decision_rule.md`.

Start year: **1988** — first clinical excimer PRK reports.

---

## Time Windows

Six nested windows, all ending in 2025 (`END_YEAR` in `config.py`):

| Label       | Years      |
|-------------|------------|
| `all_time`  | 1988–2025  |
| `last_25yr` | 2001–2025  |
| `last_20yr` | 2006–2025  |
| `last_15yr` | 2011–2025  |
| `last_10yr` | 2016–2025  |
| `last_5yr`  | 2021–2025  |

---

## Output Structure

```
output/
├── all_time/
│   ├── fig1_temporal_trends.pdf
│   ├── fig2_top_journals.pdf
│   ├── fig3_top_countries.pdf
│   ├── fig4_top_authors.pdf
│   ├── fig5_author_keywords.pdf
│   ├── fig5_mesh_terms.pdf
│   ├── fig6_pub_types.pdf
│   ├── fig7_country_collab.pdf
│   ├── fig8_keyword_trends.pdf
│   ├── fig9_institutions.pdf
│   ├── fig10_author_network.pdf
│   ├── refractive_surgery_bibliometrics.xlsx
│   ├── summary_stats.csv  temporal.csv  authors_top.csv
│   ├── journals_top.csv  countries_top.csv  keywords_top.csv
│   ├── mesh_top.csv  institutions_top.csv  languages.csv
│   └── analysis.json
├── last_25yr/  last_20yr/  last_15yr/  last_10yr/  last_5yr/
└── period_comparison.csv
```

**Figure format:** CLI produces PDF + SVG. GUI produces PNG.

---

## Module Overview

```
config.py        settings, query, thresholds, paths
fetch.py         PubMed E-utilities retrieval + XML parsing
disambiguate.py  author name disambiguation
geo.py           country extraction from affiliations
citations.py     CrossRef citation count lookup
analyze.py       all bibliometric calculations
visualize.py     figure generation (matplotlib)
report.py        CSV + Excel output
periods.py       multi-period pipeline runner
main.py          CLI orchestrator
gui.py           browser GUI (http://localhost:7434)
check_deps.py    dependency checker
demo.py          synthetic smoke test
```

---

## Troubleshooting

**`HTTP 429 Too Many Requests`** — increase `REQUEST_DELAY` in `config.py` or set API key.

**CrossRef enrichment slow** — expected (~1 req/s). Use `--skip-citations` for fast pass.

**`ModuleNotFoundError`** — run `python3 check_deps.py` for diagnosis.

---

## Data behind the published analysis

The analysis in the paper was run on 7 October 2026 for publications dated
1988–2025. Everything needed to check or repeat it is in this repository:

| Path | Contents |
|------|----------|
| `sdc/SupplementalFile1_search_strategy.txt` | The PubMed query |
| `data/retrieved_pmids.txt` | The 14,112 identifiers the query returned |
| `data/final_pmids.txt` | The 12,887 publications analyzed (fixed list) |
| `data/screening_summary.txt` | How 14,112 became 12,887 |
| `data/excluded_records.csv` | The 1,210 excluded records with rule and reason |
| `data/manual_screening.csv` | All 1,840 individual screening decisions (every exclusion confirmed by an author) |
| `validation/screening/` | Decision rule, precision sample, recall samples and the procedure-classification check |
| `data/affiliation_corrections.csv`, `data/institution_aliases.csv`, `data/keyword_synonyms.csv` | Curated corrections and normalization tables |
| `data/author_group.csv` | The pre-specified author group removed in the sensitivity analysis |
| `sdc/` | Every supplementary and sensitivity table (all years; `sdc/recent_2021_2025/` for 2021–2025), plus the procedure mix (`procedure_mix_*.csv`), field share per 1,000 ophthalmology records (`field_share_by_year.csv`) and the PubMed recount of journals and authors (`validation_*.csv`) |
| `results/<window>/` | The main ranking and trend tables for each time window |

`manuscript_figures.py` redraws the manuscript figures (Arial; PDF and 600-dpi
TIFF) from these outputs. To rebuild the dataset from the fixed list, run
`python3 main.py --pmid-file data/final_pmids.txt --use-openalex`. PubMed and
OpenAlex keep changing, so a fresh run of the query will return a slightly
different set, and citation counts will have grown.

---

## Citation

If you use this pipeline in published research, please cite:

> Hillen M, Torres-Netto EA, Furrer ML, Kollros L, Hafezi NL, Hafezi F.
> From LASIK to keratorefractive lenticule extraction: a bibliometric analysis
> of corneal laser refractive surgery research, 1988–2025. *Journal of
> Refractive Surgery* [submitted].

---

## License

MIT — see [LICENSE](LICENSE).
