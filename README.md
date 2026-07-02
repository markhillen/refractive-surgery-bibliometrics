# Refractive Surgery Bibliometrics

A reproducible, open-source bibliometric analysis pipeline for the global
scientific literature on **corneal laser refractive surgery** (1988–present).
Pulls data from PubMed and CrossRef — no Web of Science or Scopus subscription
required.

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
python3 main.py --api-key YOUR_KEY --pmid-file pmids.txt
```

### Option C — Cached records only (fastest, no network)
```bash
python3 main.py --skip-fetch --skip-citations
```

---

## Running the Pipeline

### Full run (fetch + citations + analysis)
```bash
python3 main.py --api-key YOUR_KEY
```

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

Covers corneal laser refractive surgery: LASIK, PRK, SMILE/ReLEx, LASEK,
TransPRK, excimer laser surgery, wavefront-guided and topography-guided
procedures, and presbyopia correction (PRESBYOND/presbyLASIK).

Excludes: cataract/IOL surgery (separate field), phakic IOL implantation,
orthokeratology, contact lens wear.

Start year: **1988** — first clinical excimer PRK trials.

---

## Time Windows

| Label       | Years          |
|-------------|----------------|
| `all_time`  | 1988–present   |
| `last_25yr` | 2002–present   |
| `last_20yr` | 2007–present   |
| `last_15yr` | 2012–present   |
| `last_10yr` | 2017–present   |
| `last_5yr`  | 2022–present   |

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

## License

MIT — see [LICENSE](LICENSE).
