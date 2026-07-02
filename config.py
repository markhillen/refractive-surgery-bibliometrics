"""
Refractive Surgery Bibliometrics — Configuration
=================================================
Edit this file to change search parameters, date ranges, API keys, and output paths.
"""

import os
from datetime import date

# ── Project identity ──────────────────────────────────────────────────────────
PROJECT_NAME    = "Refractive Surgery Bibliometrics"
PROJECT_VERSION = "1.0.0"

# ── API Credentials ───────────────────────────────────────────────────────────
NCBI_API_KEY = os.environ.get("NCBI_API_KEY", "")

# ── Date Range ────────────────────────────────────────────────────────────────
# ALL_TIME_START: corneal excimer laser surgery began clinically in 1988 (PRK).
# 1988 captures the full indexed laser refractive surgery literature.
ALL_TIME_START = 1988
END_YEAR       = date.today().year

START_YEAR = ALL_TIME_START

# ── Analysis time windows ─────────────────────────────────────────────────────
ANALYSIS_PERIODS = [
    ("all_time",    ALL_TIME_START, END_YEAR),
    ("last_25yr",   END_YEAR - 24,  END_YEAR),
    ("last_20yr",   END_YEAR - 19,  END_YEAR),
    ("last_15yr",   END_YEAR - 14,  END_YEAR),
    ("last_10yr",   END_YEAR - 9,   END_YEAR),
    ("last_5yr",    END_YEAR - 4,   END_YEAR),
]

# ── PubMed Search Query ───────────────────────────────────────────────────────
# Covers corneal laser refractive surgery: LASIK, PRK, SMILE/ReLEx, LASEK,
# TransPRK, wavefront/topography-guided procedures, and presbyopia correction.
# The AND clause anchors generic terms (wavefront-guided, excimer laser) to
# the ophthalmic/refractive context. NOT clause removes cataract/IOL surgery
# (a separate field) and orthokeratology (non-surgical).
PUBMED_QUERY = (
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

# ── Fetch Settings ─────────────────────────────────────────────────────────────
BATCH_SIZE        = 200
REQUEST_DELAY     = 0.15
MAX_RETRIES       = 3

# ── Author Disambiguation ──────────────────────────────────────────────────────
DISAMBIGUATION_CO_AUTHOR_THRESHOLD = 2
MIN_AUTHOR_PUBS = 3

# ── Citation Enrichment ────────────────────────────────────────────────────────
FETCH_CITATIONS      = True
CITATION_BATCH_DELAY = 0.5

# ── Co-occurrence / Network ────────────────────────────────────────────────────
# Higher thresholds — refractive surgery corpus is large
MIN_KEYWORD_FREQ = 20
MIN_COOCCURRENCE = 20

# ── Output ────────────────────────────────────────────────────────────────────
TOP_N_AUTHORS      = 25
TOP_N_COUNTRIES    = 20
TOP_N_INSTITUTIONS = 20
TOP_N_JOURNALS     = 20
TOP_N_KEYWORDS     = 25

# ── Figure format ─────────────────────────────────────────────────────────────
FIGURE_FORMAT = "pdf"

OUTPUT_DIR = os.environ.get("RS_OUTPUT_DIR", "output")
CACHE_DIR  = os.environ.get("RS_CACHE_DIR",  "cache")
