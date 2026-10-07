"""
Refractive Surgery Bibliometrics — Configuration
=================================================
Edit this file to change search parameters, date ranges, API keys, and output paths.
"""

import os
from datetime import date

# ── Project identity ──────────────────────────────────────────────────────────
PROJECT_NAME    = "Refractive Surgery Bibliometrics"
PROJECT_VERSION = "2.0.0"   # rebased on the shared cxl/kc 3.x engine, Oct 2026
# Bump when the parsed-record schema changes; main.py refuses stale caches.
CACHE_SCHEMA    = 4   # 4: author keywords split from NLM keyword lists

# ── API Credentials ───────────────────────────────────────────────────────────
NCBI_API_KEY = os.environ.get("NCBI_API_KEY", "")   # set env var or paste here

# ── Date Range ────────────────────────────────────────────────────────────────
# Clinical excimer laser photorefractive keratectomy began in 1988 (Trokel 1983
# was experimental; McDonald's first sighted-eye PRK series followed), so 1988
# captures the indexed laser refractive literature.  The analysis ends with the
# last complete calendar year, 2025: a partial 2026 would put a false cliff at
# the end of every time series.
ALL_TIME_START = 1988
END_YEAR       = 2025
START_YEAR     = ALL_TIME_START

# Which date defines a record's publication year ("earliest" = min of journal
# issue year and online-first year, mirroring PubMed's [PDAT] filter).
YEAR_RULE      = "earliest"

# ── Analysis time windows ─────────────────────────────────────────────────────
# Nested and trailing, each ending in END_YEAR; the recent window (last_5yr,
# 2021–2025) is the one reported in producer-level detail.
ANALYSIS_PERIODS = [
    ("all_time",   ALL_TIME_START, END_YEAR),
    ("last_25yr",  END_YEAR - 24,  END_YEAR),
    ("last_20yr",  END_YEAR - 19,  END_YEAR),
    ("last_15yr",  END_YEAR - 14,  END_YEAR),
    ("last_10yr",  END_YEAR - 9,   END_YEAR),
    ("last_5yr",   END_YEAR - 4,   END_YEAR),
]
RECENT_PERIOD = "last_5yr"

# ── PubMed Search Query ───────────────────────────────────────────────────────
# Corneal laser refractive surgery: PRK and surface ablation, LASEK/epi-LASIK,
# LASIK (microkeratome and femtosecond), lenticule extraction (SMILE/ReLEx/
# KLEx/SmartSight), transepithelial PRK, wavefront- and topography-guided
# treatments and laser presbyopia correction.
#
# v2 (Oct 2026) changes against v1 (manuscript V3–V6):
#  * Procedure-specific terms stand alone.  v1 required every term to co-occur
#    with an ophthalmic context word, which dropped LASIK papers whose title
#    and abstract never say cornea/myopia/visual acuity (dry eye after LASIK,
#    flap complications, IOL power after LASIK).
#  * MeSH arms added for LASIK, PRK and LASEK, so records indexed under the
#    procedure but using other wording in the abstract are retrieved.
#  * Generic or ambiguous terms (PRK as an abbreviation, excimer laser, surface
#    ablation, wavefront/topography-guided) still need an ophthalmic anchor:
#    "excimer laser" alone retrieves dermatology, angioplasty and optics papers.
#    The anchor no longer includes bare "refractive" (it matched "refractive
#    index" in optics papers).
#  * No NOT block.  v1's NOT (cataract OR intraocular lens OR IOL OR phakic OR
#    orthokeratology OR contact lens wear) removed genuine refractive-surgery
#    papers (IOL power after LASIK, LASIK versus phakic IOL).  Off-topic records
#    are removed by the logged relevance filter instead (relevance.py), so every
#    exclusion is visible in output/exclusion_log.csv.
#  v1 1988–2025: 9,680 records; v2: 14,112; v1 NOT v2: 0.
PUBMED_QUERY_SPECIFIC = (
    '"laser in situ keratomileusis"[tiab] OR "LASIK"[tiab] OR "femto-LASIK"[tiab] OR '
    '"FS-LASIK"[tiab] OR "keratomileusis"[tiab] OR '
    '"photorefractive keratectomy"[tiab] OR "photorefractive keratectomies"[tiab] OR '
    '"LASEK"[tiab] OR "laser epithelial keratomileusis"[tiab] OR '
    '"laser subepithelial keratomileusis"[tiab] OR "epi-LASIK"[tiab] OR '
    '"small incision lenticule extraction"[tiab] OR '
    '"small-incision lenticule extraction"[tiab] OR "lenticule extraction"[tiab] OR '
    '"ReLEx"[tiab] OR "femtosecond lenticule extraction"[tiab] OR "KLEx"[tiab] OR '
    '"SmartSight"[tiab] OR "transepithelial photorefractive keratectomy"[tiab] OR '
    '"TransPRK"[tiab] OR "trans-PRK"[tiab] OR "laser vision correction"[tiab] OR '
    '"laser refractive surgery"[tiab] OR "corneal refractive surgery"[tiab] OR '
    '"keratorefractive surgery"[tiab] OR "laser refractive correction"[tiab] OR '
    '"PRESBYOND"[tiab] OR "presbyLASIK"[tiab] OR '
    '"Keratomileusis, Laser In Situ"[MeSH Terms] OR '
    '"Photorefractive Keratectomy"[MeSH Terms] OR '
    '"Keratectomy, Subepithelial, Laser-Assisted"[MeSH Terms]'
)
PUBMED_QUERY_GENERIC = (
    '"PRK"[tiab] OR "excimer laser"[tiab] OR "excimer lasers"[tiab] OR '
    '"surface ablation"[tiab] OR "wavefront-guided"[tiab] OR "wavefront guided"[tiab] OR '
    '"wavefront-optimized"[tiab] OR "topography-guided"[tiab] OR '
    '"topography guided"[tiab] OR "Lasers, Excimer"[MeSH Terms]'
)
PUBMED_QUERY_ANCHOR = (
    '"cornea"[tiab] OR "corneal"[tiab] OR "myopia"[tiab] OR "myopic"[tiab] OR '
    '"hyperopia"[tiab] OR "hyperopic"[tiab] OR "astigmatism"[tiab] OR '
    '"astigmatic"[tiab] OR "presbyopia"[tiab] OR "ametropia"[tiab] OR '
    '"refractive error"[tiab] OR "refractive errors"[tiab] OR '
    '"refractive surgery"[tiab] OR "refractive outcome"[tiab] OR '
    '"refractive outcomes"[tiab] OR "visual acuity"[tiab] OR "Cornea"[MeSH Terms] OR '
    '"Refractive Errors"[MeSH Terms] OR "Refractive Surgical Procedures"[MeSH Terms]'
)
PUBMED_QUERY_BASE = (
    f'({PUBMED_QUERY_SPECIFIC}) OR '
    f'(({PUBMED_QUERY_GENERIC}) AND ({PUBMED_QUERY_ANCHOR}))'
)
PUBMED_QUERY = (
    f'({PUBMED_QUERY_BASE}) '
    f'AND ("{ALL_TIME_START}/01/01"[PDAT] : "{END_YEAR}/12/31"[PDAT])'
)

# Previous query (v1, manuscript V3–V6), kept for the audit trail and for
# validation.py --compare-queries.
PUBMED_QUERY_V1 = (
    '('
    '"laser in situ keratomileusis"[tiab] OR "LASIK"[tiab] OR '
    '"photorefractive keratectomy"[tiab] OR "PRK"[tiab] OR '
    '"LASEK"[tiab] OR "laser epithelial keratomileusis"[tiab] OR '
    '"small incision lenticule extraction"[tiab] OR '
    '"ReLEx SMILE"[tiab] OR "ReLEx"[tiab] OR '
    '"transepithelial PRK"[tiab] OR "TransPRK"[tiab] OR '
    '"laser vision correction"[tiab] OR '
    '"corneal refractive surgery"[tiab] OR '
    '"laser refractive surgery"[tiab] OR '
    '"excimer laser"[tiab] OR '
    '"femtosecond LASIK"[tiab] OR '
    '"PRESBYOND"[tiab] OR "presbyLASIK"[tiab] OR '
    '"wavefront-guided"[tiab] OR "wavefront guided"[tiab] OR '
    '"topography-guided"[tiab] OR "topography guided"[tiab]'
    ') AND ('
    '"cornea"[tiab] OR "corneal"[tiab] OR '
    '"myopia"[tiab] OR "myopic"[tiab] OR '
    '"hyperopia"[tiab] OR "hyperopic"[tiab] OR '
    '"astigmatism"[tiab] OR "astigmatic"[tiab] OR '
    '"ametropia"[tiab] OR "refractive error"[tiab] OR '
    '"refractive outcome"[tiab] OR "visual acuity"[tiab]'
    ') NOT ('
    '"cataract"[tiab] OR "phacoemulsification"[tiab] OR '
    '"intraocular lens"[tiab] OR "IOL"[tiab] OR '
    '"phakic intraocular"[tiab] OR '
    '"orthokeratology"[tiab] OR "ortho-k"[tiab] OR '
    '"contact lens wear"[tiab]'
    ') '
    f'AND ("{ALL_TIME_START}/01/01"[PDAT] : "{END_YEAR}/12/31"[PDAT])'
)
PUBMED_QUERY_V2 = PUBMED_QUERY_V1   # name used by validation.py

# ── Fetch Settings ────────────────────────────────────────────────────────────
BATCH_SIZE        = 200
REQUEST_DELAY     = 0.15
MAX_RETRIES       = 3

# ── Author Disambiguation ─────────────────────────────────────────────────────
DISAMBIGUATION_CO_AUTHOR_THRESHOLD        = 2      # shared co-authors to merge name variants
DISAMBIGUATION_AFFIL_JACCARD              = 0.35   # affiliation-token Jaccard to merge (with ≥1 shared co-author)
DISAMBIGUATION_AFFIL_JACCARD_COMMON       = 0.55   # same, for high-collision surnames (_COMMON_SURNAMES)
DISAMBIGUATION_CO_AUTHOR_THRESHOLD_COMMON = 2      # shared co-authors required with the Jaccard rule for common surnames
MIN_AUTHOR_PUBS = 3

# ── Institution attribution (main table; all variants go to output/sdc/) ──────
# counting: "primary" = the first author's first-listed resolvable affiliation
#           (one institution per record, counts are mutually exclusive);
#           "whole"   = every institution the first author lists, 1 each
#           (the rule behind the v16 manuscript's Table 3; counts overlap);
#           "fractional" = every institution, 1/k each.
# level:    "canonical" | "parent" | "cluster"  (data/institution_aliases.csv)
# first_author_only: True  = credit only the first author's institution
#                    False = credit every institution named by any author, which
#                    is what institutional rankings normally report. First-author
#                    -only systematically under-credits groups whose people
#                    publish as senior or middle authors, so the manuscript
#                    reports all-author counting and keeps first-author-only as
#                    the sensitivity analysis. Both tables are always written.
INSTITUTION_FIRST_AUTHOR_ONLY = False

# Some journals deposit an affiliation for one author or for none. When this is
# on, an author with no affiliation on a record takes their own affiliation from
# another record within IMPUTE_WINDOW_YEARS, marked affil_source="imputed".
# Applied to every author in the corpus, never to one group, and used for
# institutional counting only - first-author country still uses what PubMed
# recorded. See impute.py.
IMPUTE_MISSING_AFFILIATIONS = True
IMPUTE_WINDOW_YEARS = 2
INSTITUTION_COUNTING = "whole"
INSTITUTION_LEVEL    = "canonical"

# ── Citation Enrichment ───────────────────────────────────────────────────────
FETCH_CITATIONS      = True
CITATION_BATCH_DELAY = 0.5

# ── Co-occurrence / Network ───────────────────────────────────────────────────
MIN_KEYWORD_FREQ  = 20    # large corpus
MIN_COOCCURRENCE  = 20
TOP_N_AUTHORS     = 30
TOP_N_COUNTRIES   = 20
TOP_N_JOURNALS    = 20
TOP_N_KEYWORDS    = 50
TOP_N_INSTITUTIONS = 20

# Subject named in figure titles
FIELD_LABEL = "corneal laser refractive surgery"

# Journal marked on the Bradford figure (the target journal for the manuscript).
HIGHLIGHT_JOURNAL = None   # never single out the target journal on a figure

# ── Paths ─────────────────────────────────────────────────────────────────────
import pathlib as _pl
_HERE      = _pl.Path(__file__).resolve().parent

BASE_DIR   = str(_HERE)
DATA_DIR   = str(_HERE / "data")
CACHE_DIR  = str(_HERE / "cache")
OUTPUT_DIR = str(_HERE / "output")

for _d in [DATA_DIR, CACHE_DIR, OUTPUT_DIR]:
    _pl.Path(_d).mkdir(parents=True, exist_ok=True)

# ── Figure format ─────────────────────────────────────────────────────────────
# "pdf" — vector, best for journal submission
# "svg" — vector, editable in Illustrator / Inkscape
# "png" — raster (300 dpi); avoid for publication figures
FIGURE_FORMAT = "pdf"
FIG_MAX_WIDTH_IN = 7.0            # journal full-page width; _save() warns beyond this
CITATION_SOURCE_LABEL = "OpenAlex"  # axis label for citation panels (set by main.py per run mode)
PER_CAPITA_MIN_PUBS = 20          # Figure 2D and SDC per-capita table: minimum first-author publications
KEYWORD_TREND_MIN_RECORDS = 100   # Figure 3A: first year with at least this many keyword-bearing records
CITATION_FILL_CROSSREF = False   # True → records without an OpenAlex match take their CrossRef count (source "crossref")
