"""
analyze.py — Bibliometric calculations
=======================================
Computes all summary statistics from enriched records:
  - Temporal trends
  - Author rankings (publications + estimated h-index)
  - Journal rankings
  - Country rankings
  - Keyword / MeSH co-occurrence
  - Collaboration networks (author, country, institution)
"""

import collections
import itertools
import re
import math
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import config
from geo import extract_country

# ─────────────────────────────────────────────────────────────────────────────
# 1. Temporal trends
# ─────────────────────────────────────────────────────────────────────────────

def temporal_trends(records: list[dict]) -> dict:
    """Publications per year, cumulative, and moving average."""
    by_year: dict[int, int] = collections.Counter()
    cite_by_year: dict[int, int] = collections.defaultdict(int)
    for rec in records:
        try:
            y = int(rec.get("year", 0))
        except (ValueError, TypeError):
            continue
        if config.START_YEAR <= y <= config.END_YEAR:
            by_year[y] += 1
            cc = rec.get("citation_count") or 0
            cite_by_year[y] += cc

    years = sorted(by_year.keys())
    counts = [by_year[y] for y in years]
    cumulative = list(itertools.accumulate(counts))
    citations = [cite_by_year[y] for y in years]

    # 3-year moving average
    def moving_avg(vals, window=3):
        out = []
        for i in range(len(vals)):
            lo = max(0, i - window // 2)
            hi = min(len(vals), i + window // 2 + 1)
            out.append(sum(vals[lo:hi]) / (hi - lo))
        return out

    return {
        "years":       years,
        "counts":      counts,
        "cumulative":  cumulative,
        "moving_avg":  moving_avg(counts),
        "citations":   citations,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2. Author analysis
# ─────────────────────────────────────────────────────────────────────────────

def author_stats(records: list[dict]) -> list[dict]:
    """
    Returns list of author dicts sorted by publication count desc.
    Fields: author_id, pub_count, first_author_count, last_author_count,
            citation_total, h_index_est, years_active, journals, affiliations_sample
    """
    # Per-author aggregation
    pubs:       dict[str, list[dict]] = collections.defaultdict(list)
    first_auth: dict[str, int]        = collections.Counter()
    last_auth:  dict[str, int]        = collections.Counter()
    citations:  dict[str, int]        = collections.defaultdict(int)
    affils_sample: dict[str, list]    = collections.defaultdict(list)
    journals_per_auth: dict[str, set] = collections.defaultdict(set)
    years_per_auth: dict[str, set]    = collections.defaultdict(set)

    for rec in records:
        cc = rec.get("citation_count") or 0
        jrnl = rec.get("journal_abbr") or rec.get("journal", "")
        try:
            yr = int(rec.get("year", 0))
        except (ValueError, TypeError):
            yr = 0

        authors = rec.get("authors", [])
        # Filter out collective/anonymous entries for position calculation
        named = [a for a in authors if a.get("author_id") and a["author_id"] != "__collective__"]
        n_named = len(named)
        for pos, a in enumerate(authors):
            aid = a.get("author_id")
            if not aid or aid == "__collective__":
                continue
            pubs[aid].append(rec)
            citations[aid] += cc
            journals_per_auth[aid].add(jrnl)
            if yr:
                years_per_auth[aid].add(yr)
            if pos == 0:
                first_auth[aid] += 1
            # Last author: final named position (senior/PI convention).
            # Only meaningful for multi-author papers (≥2 named authors).
            named_pos = named.index(a) if a in named else -1
            if n_named >= 2 and named_pos == n_named - 1:
                last_auth[aid] += 1
            if a.get("affils") and len(affils_sample[aid]) < 3:
                affils_sample[aid].extend(a["affils"][:2])

    # Estimate h-index from available citation counts
    # (real h-index needs per-paper citations, not author totals)
    # We estimate: h ≈ √(total_citations / pub_count) × correction
    def est_h(total_cites, n_pubs):
        if n_pubs == 0 or total_cites is None:
            return 0
        return round(math.sqrt(total_cites * 0.5))

    rows = []
    for aid, rec_list in pubs.items():
        n = len(rec_list)
        if n < config.MIN_AUTHOR_PUBS:
            continue
        tc = citations[aid]
        yrs = sorted(years_per_auth[aid])
        rows.append({
            "author_id":          aid,
            "pub_count":          n,
            "first_author_count": first_auth[aid],
            "last_author_count":  last_auth[aid],
            "citation_total":     tc,
            "h_index_est":        est_h(tc, n),
            "year_first":         yrs[0]  if yrs else None,
            "year_last":          yrs[-1] if yrs else None,
            "years_active":       len(yrs),
            "journal_count":      len(journals_per_auth[aid]),
            "affils_sample":      list(dict.fromkeys(affils_sample[aid]))[:3],
        })

    rows.sort(key=lambda x: x["pub_count"], reverse=True)
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# 3. Journal analysis
# ─────────────────────────────────────────────────────────────────────────────

def journal_stats(records: list[dict]) -> list[dict]:
    counter: dict[str, dict] = {}
    for rec in records:
        jname = rec.get("journal") or "Unknown"
        jabbr = rec.get("journal_abbr") or jname
        cc = rec.get("citation_count") or 0
        if jname not in counter:
            counter[jname] = {"journal": jname, "abbr": jabbr,
                               "count": 0, "citations": 0}
        counter[jname]["count"] += 1
        counter[jname]["citations"] += cc

    rows = sorted(counter.values(), key=lambda x: x["count"], reverse=True)
    total = len(records)
    for r in rows:
        r["percentage"] = round(r["count"] / total * 100, 2)
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# 4. Country analysis
# ─────────────────────────────────────────────────────────────────────────────

def country_stats(records: list[dict]) -> list[dict]:
    """Publication and citation counts per country (first author).

    Per-capita metrics use 2024 UN population estimates (millions).
    Countries absent from the lookup table receive pubs_per_million = None.
    """
    # 2024 UN population estimates (millions), covering all countries likely
    # to appear in the keratoconus literature.
    _POP_MILLIONS: dict[str, float] = {
        "Australia":       26.5,
        "Austria":          9.1,
        "Belgium":         11.7,
        "Brazil":         215.3,
        "Canada":          38.8,
        "China":         1412.0,
        "Czech Republic":  10.9,
        "Denmark":          5.9,
        "Egypt":          107.0,
        "Finland":          5.6,
        "France":          68.4,
        "Germany":         84.4,
        "Greece":          10.4,
        "Hungary":          9.7,
        "India":         1441.0,
        "Iran":            89.2,
        "Israel":           9.8,
        "Italy":           59.0,
        "Japan":          123.3,
        "Jordan":          10.3,
        "Lebanon":          5.5,
        "Netherlands":     17.9,
        "New Zealand":      5.1,
        "Norway":           5.5,
        "Poland":          41.0,
        "Portugal":        10.3,
        "Romania":         19.0,
        "Saudi Arabia":    36.4,
        "Singapore":        6.0,
        "South Korea":     51.7,
        "Spain":           47.4,
        "Sweden":          10.5,
        "Switzerland":      8.8,
        "Taiwan":          23.6,
        "Turkey":          85.3,
        "Ukraine":         43.5,
        "United Arab Emirates": 9.8,
        "United Kingdom":  67.7,
        "United States":  335.9,
    }

    counter: dict[str, dict] = {}
    for rec in records:
        c = rec.get("country", "Unknown")
        cc = rec.get("citation_count") or 0
        if c not in counter:
            counter[c] = {"country": c, "count": 0, "citations": 0}
        counter[c]["count"] += 1
        counter[c]["citations"] += cc

    rows = sorted(counter.values(), key=lambda x: x["count"], reverse=True)
    total = len(records)
    for r in rows:
        r["percentage"] = round(r["count"] / total * 100, 2)
        pop = _POP_MILLIONS.get(r["country"])
        if pop:
            r["pubs_per_million"]   = round(r["count"]   / pop, 2)
            r["cites_per_million"]  = round(r["citations"] / pop, 1)
        else:
            r["pubs_per_million"]  = None
            r["cites_per_million"] = None
    return rows


def country_collab_network(records: list[dict]) -> dict:
    """
    Country-level collaboration network.
    Edge weight = number of papers with authors from both countries.
    """
    node_counts: dict[str, int] = collections.Counter()
    edge_weights: dict[tuple, int] = collections.Counter()

    for rec in records:
        countries_in_paper: set[str] = set()
        for a in rec.get("authors", []):
            c = a.get("oa_country_name")
            if not c:
                affils = a.get("affils", [])
                c = extract_country(affils) if affils else "Unknown"
            if c and c != "Unknown":
                countries_in_paper.add(c)
        for c in countries_in_paper:
            node_counts[c] += 1
        for c1, c2 in itertools.combinations(sorted(countries_in_paper), 2):
            edge_weights[(c1, c2)] += 1

    return {
        "nodes": dict(node_counts),
        "edges": {f"{k[0]}|{k[1]}": v for k, v in edge_weights.items()},
    }


# ─────────────────────────────────────────────────────────────────────────────
# 5. Keyword / MeSH co-occurrence
# ─────────────────────────────────────────────────────────────────────────────

# ── Keyword synonym map ───────────────────────────────────────────────────────
# All variants on the left collapse to the canonical term on the right.
# Applied BEFORE counting, so merged terms appear as a single entry.
_KW_SYNONYMS: dict[str, str] = {
    # ── CXL procedure name variants ──────────────────────────────────────────
    # These are all the same procedure — merge into one canonical term so the
    # keyword chart reflects clinical themes, not indexing inconsistency.
    "corneal cross-linking":                    "corneal cross-linking (CXL)",
    "corneal crosslinking":                     "corneal cross-linking (CXL)",
    "corneal collagen cross-linking":           "corneal cross-linking (CXL)",
    "corneal collagen crosslinking":            "corneal cross-linking (CXL)",
    "collagen cross-linking":                   "corneal cross-linking (CXL)",
    "collagen crosslinking":                    "corneal cross-linking (CXL)",
    "cross-linking":                            "corneal cross-linking (CXL)",
    "crosslinking":                             "corneal cross-linking (CXL)",
    "cxl":                                      "corneal cross-linking (CXL)",
    "corneal collagen cxl":                     "corneal cross-linking (CXL)",
    "uva/riboflavin cross-linking":             "corneal cross-linking (CXL)",
    "uva-riboflavin cross-linking":             "corneal cross-linking (CXL)",
    "riboflavin/uva cross-linking":             "corneal cross-linking (CXL)",
    "riboflavin/ultraviolet-a cross-linking":   "corneal cross-linking (CXL)",
    "riboflavin uv-a corneal cross-linking":    "corneal cross-linking (CXL)",
    "corneal collagen cross linking":           "corneal cross-linking (CXL)",
    "cross linking":                            "corneal cross-linking (CXL)",
    "kxl":                                      "corneal cross-linking (CXL)",

    # ── Accelerated CXL variants ─────────────────────────────────────────────
    "accelerated cxl":                          "accelerated CXL",
    "accelerated corneal cross-linking":        "accelerated CXL",
    "accelerated corneal crosslinking":         "accelerated CXL",
    "accelerated collagen cross-linking":       "accelerated CXL",
    "a-cxl":                                    "accelerated CXL",
    "acxl":                                     "accelerated CXL",

    # ── Epithelium-on/off variants ────────────────────────────────────────────
    "epithelium-off cxl":                       "epi-off CXL",
    "epi-off cxl":                              "epi-off CXL",
    "epithelium off cxl":                       "epi-off CXL",
    "standard cxl":                             "epi-off CXL",
    "dresden protocol":                         "epi-off CXL",
    "transepithelial cxl":                      "epi-on CXL (transepithelial)",
    "epithelium-on cxl":                        "epi-on CXL (transepithelial)",
    "epi-on cxl":                               "epi-on CXL (transepithelial)",
    "trans-epithelial cxl":                     "epi-on CXL (transepithelial)",
    "iontophoresis cxl":                        "epi-on CXL (transepithelial)",

    # ── PACK-CXL / infectious keratitis ──────────────────────────────────────
    # NOTE: PACK-CXL treats infectious keratitis, not keratoconus/ectasia.
    # These terms are NOT canonical keywords for the keratoconus literature.
    # Papers mentioning PACK-CXL only are excluded by the fetch relevance filter.
    # Any that remain (e.g. papers discussing CXL mechanism broadly) will appear
    # under the general CXL synonym group above, which is appropriate.

    # ── Keratoconus variants ─────────────────────────────────────────────────
    "keratoconus":                              "keratoconus",
    "progressive keratoconus":                  "keratoconus",
    "pediatric keratoconus":                    "paediatric keratoconus",
    "paediatric keratoconus":                   "paediatric keratoconus",
    "childhood keratoconus":                    "paediatric keratoconus",

    # ── Corneal ectasia variants ──────────────────────────────────────────────
    # All clinical variants of the ectasia disease spectrum
    "corneal ectasia":                          "corneal ectasia",
    "ectasia":                                  "corneal ectasia",
    "keratectasia":                             "corneal ectasia",
    "ectatic corneal disease":                  "corneal ectasia",
    "corneal ectatic disease":                  "corneal ectatic disease",

    # Post-refractive ectasia
    "post-lasik ectasia":                       "post-refractive ectasia",
    "post lasik ectasia":                       "post-refractive ectasia",
    "post-refractive ectasia":                  "post-refractive ectasia",
    "post refractive ectasia":                  "post-refractive ectasia",
    "post-surgical ectasia":                    "post-refractive ectasia",
    "post surgical ectasia":                    "post-refractive ectasia",
    "iatrogenic ectasia":                       "post-refractive ectasia",
    "ectasia after lasik":                      "post-refractive ectasia",
    "ectasia after refractive surgery":         "post-refractive ectasia",
    "laser in situ keratomileusis ectasia":     "post-refractive ectasia",

    # Pellucid marginal degeneration
    "pellucid marginal degeneration":           "pellucid marginal degeneration (PMD)",
    "pellucid marginal corneal degeneration":   "pellucid marginal degeneration (PMD)",
    "pmd":                                      "pellucid marginal degeneration (PMD)",
    "pellucid":                                 "pellucid marginal degeneration (PMD)",

    # Keratoglobus
    "keratoglobus":                             "keratoglobus",
    "kerato-globus":                            "keratoglobus",

    # Forme fruste / subclinical keratoconus
    "forme fruste keratoconus":                 "forme fruste / subclinical keratoconus",
    "forme fruste":                             "forme fruste / subclinical keratoconus",
    "subclinical keratoconus":                  "forme fruste / subclinical keratoconus",
    "suspected keratoconus":                    "forme fruste / subclinical keratoconus",
    "keratoconus suspect":                      "forme fruste / subclinical keratoconus",
    "keratoconus susceptibility":               "forme fruste / subclinical keratoconus",
    "pre-clinical keratoconus":                 "forme fruste / subclinical keratoconus",
    "preclinical keratoconus":                  "forme fruste / subclinical keratoconus",

    # Posterior keratoconus
    "posterior keratoconus":                    "posterior keratoconus",

    # ── Riboflavin/UVA — keep as clinical concept, not just procedural label ─
    "riboflavin":                               "riboflavin",
    "vitamin b2":                               "riboflavin",
    "uva":                                      "ultraviolet-A (UVA)",
    "ultraviolet-a":                            "ultraviolet-A (UVA)",
    "ultraviolet a":                            "ultraviolet-A (UVA)",
    "uv-a":                                     "ultraviolet-A (UVA)",

    # ── Corneal topography/imaging ────────────────────────────────────────────
    "corneal topography":                       "corneal topography",
    "scheimpflug":                              "corneal topography",
    "pentacam":                                 "corneal topography",
    "corneal tomography":                       "corneal topography",
    "optical coherence tomography":             "OCT",
    "oct":                                      "OCT",
    "anterior segment oct":                     "OCT",

    # ── Biomechanics ─────────────────────────────────────────────────────────
    "corneal biomechanics":                     "corneal biomechanics",
    "corneal hysteresis":                       "corneal biomechanics",
    "ocular response analyzer":                 "corneal biomechanics",
    "corvis st":                                "corneal biomechanics",
    "young's modulus":                          "corneal biomechanics",
    "stress-strain":                            "corneal biomechanics",

    # ── Infectious keratitis ─────────────────────────────────────────────────
    "infectious keratitis":                     "infectious keratitis",
    "fungal keratitis":                         "infectious keratitis",
    "bacterial keratitis":                      "infectious keratitis",
    "acanthamoeba keratitis":                   "infectious keratitis",
    "microbial keratitis":                      "infectious keratitis",
    "corneal ulcer":                            "infectious keratitis",
}

# Terms to exclude entirely from keyword charts — too generic or purely procedural
_KW_EXCLUDE: set[str] = {
    "cornea",           # everything in the dataset involves the cornea
    "humans",           # MeSH noise
    "adult",
    "female",
    "male",
    "aged",
    "middle aged",
    "prospective studies",
    "retrospective studies",
    "treatment outcome",
    "follow-up studies",
    "visual acuity",    # near-universal in ophthalmology, not discriminating
    "refraction, ocular",
}


def _clean_keyword(kw: str) -> str | None:
    """
    Normalise a keyword: lowercase, strip punctuation, apply synonym map.
    Returns None if the term should be excluded entirely.
    """
    cleaned = kw.lower().strip().rstrip(".,;:")
    # Apply synonym map (exact match first, then substring for common prefixes)
    if cleaned in _KW_SYNONYMS:
        cleaned = _KW_SYNONYMS[cleaned]
    # Exclude generic terms
    if cleaned in _KW_EXCLUDE:
        return None
    return cleaned if cleaned else None


def keyword_stats(records: list[dict], use_mesh: bool = False) -> dict:
    """
    Returns:
      - freq: {keyword: count}
      - cooccurrence: {(kw1, kw2): count}  (edges for network)
    Synonymous keyword variants are merged before counting.
    """
    freq:  dict[str, int]   = collections.Counter()
    cooc:  dict[tuple, int] = collections.Counter()

    for rec in records:
        kws = rec.get("mesh", []) if use_mesh else rec.get("keywords", [])
        if use_mesh:
            kws = list(kws) + rec.get("keywords", [])

        # Clean, deduplicate, and exclude after synonym mapping
        cleaned = list({
            ck for k in kws
            if k.strip()
            for ck in [_clean_keyword(k)]
            if ck is not None
        })

        for k in cleaned:
            freq[k] += 1
        for k1, k2 in itertools.combinations(sorted(cleaned), 2):
            cooc[(k1, k2)] += 1

    # Filter by minimum frequency / co-occurrence
    freq_filtered = {k: v for k, v in freq.items() if v >= config.MIN_KEYWORD_FREQ}
    cooc_filtered = {k: v for k, v in cooc.items()
                     if v >= config.MIN_COOCCURRENCE
                     and k[0] in freq_filtered
                     and k[1] in freq_filtered}

    return {
        "freq":        freq_filtered,
        "cooccurrence": {f"{k[0]}|||{k[1]}": v for k, v in cooc_filtered.items()},
    }


# ─────────────────────────────────────────────────────────────────────────────
# 6. Institution analysis
# ─────────────────────────────────────────────────────────────────────────────

# ── Institution alias table ──────────────────────────────────────────────────
# Maps lowercase fragments → canonical institution name.
# Checked BEFORE the generic extractor. Add new entries here freely.
_INST_ALIASES = {
    # Switzerland
    "elza institute":                   "ELZA Institute",
    "iroc":                             "IROC Zurich",
    "universitätsspital zürich":        "University Hospital Zurich",
    "university hospital zurich":       "University Hospital Zurich",
    "inselspital":                      "Inselspital Bern",
    "university of zurich":             "University of Zurich",
    "univ zurich":                      "University of Zurich",
    "univ. of zurich":                  "University of Zurich",
    # Germany
    "tu dresden":                       "TU Dresden",
    "technische universität dresden":   "TU Dresden",
    "universitätsklinikum dresden":     "University Hospital Dresden",
    "charité":                          "Charité – Universitätsmedizin Berlin",
    "ludwig-maximilians-universität":   "Ludwig Maximilian University Munich",
    "lmu munich":                       "Ludwig Maximilian University Munich",
    "university of erlangen":           "University of Erlangen-Nuremberg",
    "university of marburg":            "University of Marburg",
    # Greece
    "university of crete":              "University of Crete",
    "laservision":                      "Laservision Institute Athens",
    "athens eye":                       "Athens Eye Hospital",
    # Italy
    "university of siena":              "University of Siena",
    "humanitas":                        "Humanitas University Milan",
    "milan eye":                        "Milan Eye Center",
    "university of rome":               "Sapienza University of Rome",
    "sapienza":                         "Sapienza University of Rome",
    "university of milan":              "University of Milan",
    # United States
    "bascom palmer":                    "Bascom Palmer Eye Institute",
    "wills eye":                        "Wills Eye Hospital",
    "mayo clinic":                      "Mayo Clinic",
    "harvard":                          "Harvard Medical School",
    "johns hopkins":                    "Johns Hopkins University",
    "massachusetts eye":                "Mass Eye and Ear / Harvard",
    "university of southern california":"University of Southern California",
    "usc roski":                        "University of Southern California",
    "emory":                            "Emory University",
    "rutgers":                          "Rutgers University",
    "university of miami":              "University of Miami",
    "university of illinois":           "University of Illinois Chicago",
    "university of arizona":            "University of Arizona",
    "stanford":                         "Stanford University",
    "ucsf":                             "University of California San Francisco",
    "columbia university":              "Columbia University",
    "new york eye":                     "New York Eye and Ear Infirmary",
    # United Kingdom
    "moorfields":                       "Moorfields Eye Hospital",
    "university of nottingham":         "University of Nottingham",
    "university of liverpool":          "University of Liverpool",
    "university of edinburgh":          "University of Edinburgh",
    "university of bristol":            "University of Bristol",
    "university of manchester":         "University of Manchester",
    "king's college":                   "King's College London",
    "ucl":                              "University College London",
    # Iran
    "noor eye":                         "Noor Eye Hospital Tehran",
    "tehran university of medical":     "Tehran University of Medical Sciences",
    "shahid beheshti":                  "Shahid Beheshti University of Medical Sciences",
    "mashhad university":               "Mashhad University of Medical Sciences",
    "isfahan university":               "Isfahan University of Medical Sciences",
    # India
    "lv prasad":                        "LV Prasad Eye Institute",
    "l v prasad":                       "LV Prasad Eye Institute",
    "aravind":                          "Aravind Eye Care System",
    "sankara nethralaya":               "Sankara Nethralaya Chennai",
    "narayana nethralaya":              "Narayana Nethralaya Bangalore",
    "aiims":                            "All India Institute of Medical Sciences",
    "all india institute":              "All India Institute of Medical Sciences",
    # Singapore
    "singapore national eye":           "Singapore National Eye Centre",
    "snec":                             "Singapore National Eye Centre",
    "nanyang technological":            "Nanyang Technological University",
    # China / Hong Kong / Taiwan
    "wenzhou medical":                  "Wenzhou Medical University",
    "peking university":                "Peking University",
    "tianjin eye":                      "Tianjin Eye Hospital",
    "chinese university of hong kong":  "Chinese University of Hong Kong",
    "cuhk":                             "Chinese University of Hong Kong",
    "university of hong kong":          "University of Hong Kong",
    # Australia
    "royal victorian eye":              "Royal Victorian Eye and Ear Hospital",
    "centre for eye research australia":"Centre for Eye Research Australia",
    "cera":                             "Centre for Eye Research Australia",
    "university of melbourne":          "University of Melbourne",
    # Spain
    "universidad de alicante":          "University of Alicante",
    "university of alicante":           "University of Alicante",
    # Belgium
    "university of ghent":              "Ghent University",
    "ghent university":                 "Ghent University",
    "katholieke universiteit leuven":   "KU Leuven",
    "ku leuven":                        "KU Leuven",
    # Netherlands
    "maastricht university":            "Maastricht University",
    "erasmus":                          "Erasmus University Rotterdam",
    # Israel
    "tel aviv university":              "Tel Aviv University",
    "hadassah":                         "Hadassah Medical Center",
    # Brazil
    "unifesp":                          "Federal University of São Paulo",
    "federal university of são paulo":  "Federal University of São Paulo",
    "universidade de são paulo":        "University of São Paulo",
    # Other
    "irwin army":                       "Irwin Army Community Hospital",
}

# ── Prefixes that indicate a sub-unit, NOT the institution itself ─────────────
# Any comma-separated segment STARTING with one of these should be SKIPPED.
_DEPT_PREFIXES = (
    # English department/division patterns
    "department of", "dept of", "dept.", "the department of",
    "a department of", "from the department",
    "division of", "div of",
    "section of", "unit of",
    "laboratory of", "lab of",
    "faculty of",
    "school of",                         # "School of Materials…", "School of Medicine"
    "institute of ophthalmology",        # too generic — thousands of institutions have this
    "research institute of eye",         # "Research Institute of Eye Diseases" alone = no institution
    "institute of biochemical",
    "ophthalmology department",
    "eye department",
    "optometry department",
    # German
    "augenklinik",                       # generic "eye clinic"
    "klinik für",                        # "Klinik für Augenheilkunde"
    "abteilung für",                     # "Abteilung für…" = department of
    "augenabteilung",
    # French
    "service d'ophtalmologie",
    "clinique ophtalmologique",
    "département d'ophtalmologie",
    # Spanish / Portuguese
    "centro de",
    "departamento de",
    "servicio de",
    # Italian
    "dipartimento di",
    "clinica oculistica",
    # Trailing stopwords that indicate incomplete affiliation
    "school of medicine",                # bare "School of Medicine" with no university
    "school of optometry",
    "college of medicine",
    # Specific strings reported from real data
    "division of clinical",              # "Division of Clinical Neuroscience" alone
    "research institute of eye diseases",# without a following university
    "institute of biochemical",
    "institute of biomedical",
)

# ── Tokens that strongly indicate a real institution ─────────────────────────
_INST_TOKENS = (
    "university", "université", "universität", "università", "universidad",
    "universidade", "universiteit", "universitetet",
    "hospital", "hôpital", "krankenhaus", "klinikum", "spital",
    "institute", "institut", "istituto",
    "college", "school of medicine", "medical school", "medical center",
    "medical centre", "eye centre", "eye center", "eye care",
    "eye hospital", "eye institute", "eye clinic",
    "nethralaya", "sankara", "aravind",   # named Indian eye centres
    "foundation", "academy",
    "clinic",
)


def _is_dept(segment: str) -> bool:
    """Return True if this segment looks like a department/sub-unit, not an institution."""
    sl = segment.lower().strip()
    return any(sl.startswith(p) for p in _DEPT_PREFIXES)


def _is_inst(segment: str) -> bool:
    """Return True if this segment looks like a genuine institution."""
    sl = segment.lower()
    return any(tok in sl for tok in _INST_TOKENS)


def _norm_institution(affil: str) -> str:
    """
    Extract the canonical parent institution from a PubMed affiliation string.

    Strategy (in order):
    1. Check alias table — fast path for known institutions.
    2. Split on commas; skip leading department/sub-unit segments.
    3. Among remaining segments, prefer those containing university/hospital tokens.
    4. Fall back to the first non-department segment of reasonable length.
    5. If all else fails, return the whole string truncated.
    """
    if not affil:
        return "Unknown"

    al = affil.lower()

    # ── 1. Alias lookup ────────────────────────────────────────────────────────
    # Named hospitals/eye centres beat generic universities when both match.
    # Within each tier, longest key wins (more specific match preferred).
    _PRIORITY_TOKENS = ("eye", "hospital", "clinic", "nethralaya", "palmer",
                        "moorfields", "wills", "aravind", "sankara", "prasad",
                        "bascom", "elza", "iroc", "snec", "noor")
    tier1 = {}  # named clinical institutions
    tier2 = {}  # universities / everything else
    for key, canonical in _INST_ALIASES.items():
        if key in al:
            if any(t in key for t in _PRIORITY_TOKENS):
                tier1[key] = canonical
            else:
                tier2[key] = canonical
    for tier in (tier1, tier2):
        if tier:
            best_key = max(tier, key=len)
            return tier[best_key]

    # ── 2. Split on commas and score each segment ─────────────────────────────
    parts = [p.strip() for p in affil.split(",") if p.strip()]

    # Score: dept-like = -1, inst-like = +1, neutral = 0; skip very short/country-only
    COUNTRY_WORDS = {"usa", "uk", "germany", "france", "italy", "spain",
                     "china", "india", "iran", "brazil", "australia",
                     "switzerland", "netherlands", "israel", "japan",
                     "south korea", "turkey", "egypt", "canada"}

    candidates = []
    for seg in parts:
        sl = seg.lower().strip(".")
        if len(seg) < 5:
            continue
        if sl in COUNTRY_WORDS or sl.isdigit():
            continue
        # Skip zip/postal codes
        if re.match(r'^[0-9\s\-]+$', sl):
            continue
        score = 0
        if _is_dept(seg):
            score -= 2
        if _is_inst(seg):
            score += 2
        # Longer = more likely to be the full institution name
        score += min(len(seg) / 40, 1.0)
        candidates.append((score, seg))

    if not candidates:
        return None

    # Sort by score descending; among ties keep original order (stable)
    candidates.sort(key=lambda x: x[0], reverse=True)
    best_score, best = candidates[0]

    # If the best candidate is still dept-like, no recoverable institution → None
    if best_score <= -1:
        return None

    # Final guard: reject any result that is itself a generic sub-unit label
    # (catches cases where a division/institute name is the only segment)
    _GENERIC_RESULTS = {
        "division of clinical neuroscience", "school of medicine",
        "school of optometry", "college of medicine",
        "institute of biochemical and biomedical engineering",
        "research institute of eye diseases",
        "augenheilkunde", "augenabteilung",
    }
    if best.lower().strip(".").rstrip(",") in _GENERIC_RESULTS:
        return None

    return best


def institution_stats(records: list[dict],
                      first_author_only: bool = False) -> list[dict]:
    """Institutional publication and citation counts.

    Args:
        first_author_only: If True, count only the first author's institution
            per paper (corresponding to the originating research group).
            If False (default), count all co-authors' institutions, which
            inflates counts for institutions that frequently appear as
            co-authors on others' papers.
    """
    counter:  dict[str, int] = collections.Counter()
    cite_sum: dict[str, int] = collections.defaultdict(int)
    for rec in records:
        cc = rec.get("citation_count") or 0
        seen = set()
        authors = rec.get("authors", [])
        if first_author_only:
            # Only the first named author
            authors = authors[:1]
        for a in authors:
            for affil in a.get("affils", []):
                inst = _norm_institution(affil)
                if not inst or len(inst) < 6:
                    continue
                if inst not in seen:
                    counter[inst] += 1
                    cite_sum[inst] += cc
                    seen.add(inst)
    rows = [{"institution": k, "count": v, "citations": cite_sum[k]}
            for k, v in counter.most_common(50)]
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# 7. Publication type breakdown
# ─────────────────────────────────────────────────────────────────────────────

def pubtype_stats(records: list[dict]) -> dict[str, int]:
    counter: dict[str, int] = collections.Counter()
    for rec in records:
        for pt in rec.get("pub_types", []):
            counter[pt] += 1
    return dict(counter.most_common())


# ─────────────────────────────────────────────────────────────────────────────
# 8. Language breakdown
# ─────────────────────────────────────────────────────────────────────────────

def language_stats(records: list[dict]) -> dict[str, int]:
    counter: dict[str, int] = collections.Counter()
    for rec in records:
        lang = rec.get("language", "Unknown") or "Unknown"
        counter[lang] += 1
    return dict(counter.most_common())


# ─────────────────────────────────────────────────────────────────────────────
# 9. Author collaboration network
# ─────────────────────────────────────────────────────────────────────────────

def author_collab_network(records: list[dict], top_n: int = None) -> dict:
    """
    Returns co-authorship network for top N authors by publication count.

    Strategy: compute ALL pairwise co-authorship edges across the full
    literature first, then select the top_n nodes by publication count.
    This means edges to highly-cited collaborators outside the top-N by
    volume are still captured — a top-30 author who co-authored with a
    lower-volume but notable collaborator will have that edge present.
    """
    top_n = top_n or config.TOP_N_AUTHORS

    # Pass 1: count publications and edges for ALL authors
    all_counts:  dict[str, int] = collections.Counter()
    all_edges:   dict[tuple, int] = collections.Counter()

    for rec in records:
        paper_authors = [
            a["author_id"] for a in rec.get("authors", [])
            if a.get("author_id") and a["author_id"] != "__collective__"
        ]
        unique = sorted(set(paper_authors))
        for aid in unique:
            all_counts[aid] += 1
        for a1, a2 in itertools.combinations(unique, 2):
            all_edges[(a1, a2)] += 1

    # Pass 2: select top_n nodes by publication count
    top_ids = {aid for aid, _ in all_counts.most_common(top_n)}

    # Pass 3: include edges where AT LEAST ONE endpoint is in top_n
    # (so a top-30 author's connection to a notable collaborator is visible)
    # but cap to edges where BOTH endpoints have ≥ MIN_PUBS to avoid noise
    MIN_PUBS = max(1, all_counts.most_common(top_n)[-1][1] // 3
                   if len(all_counts) >= top_n else 1)

    node_counts: dict[str, int] = {}
    edge_weights: dict[tuple, int] = {}

    for (a1, a2), w in all_edges.items():
        a1_top = a1 in top_ids
        a2_top = a2 in top_ids
        if not (a1_top or a2_top):
            continue
        # Both must meet minimum pub threshold to appear as nodes
        if all_counts[a1] < MIN_PUBS or all_counts[a2] < MIN_PUBS:
            continue
        node_counts[a1] = all_counts[a1]
        node_counts[a2] = all_counts[a2]
        edge_weights[(a1, a2)] = w

    # Ensure all top_n nodes appear even if isolated
    for aid in top_ids:
        if aid not in node_counts:
            node_counts[aid] = all_counts[aid]

    return {
        "nodes": dict(node_counts),
        "edges": {f"{k[0]}|||{k[1]}": v for k, v in edge_weights.items()},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Master runner
# ─────────────────────────────────────────────────────────────────────────────

def run_analysis(records: list[dict]) -> dict:
    print("[analyze] Computing temporal trends …")
    temporal = temporal_trends(records)

    print("[analyze] Computing author statistics …")
    authors = author_stats(records)

    print("[analyze] Computing journal statistics …")
    journals = journal_stats(records)

    print("[analyze] Computing country statistics …")
    countries = country_stats(records)

    print("[analyze] Computing country collaboration network …")
    country_net = country_collab_network(records)

    print("[analyze] Computing keyword statistics …")
    kw_stats = keyword_stats(records, use_mesh=False)
    mesh_stats = keyword_stats(records, use_mesh=True)

    print("[analyze] Computing institution statistics …")
    institutions            = institution_stats(records, first_author_only=True)
    institutions_all_authors = institution_stats(records, first_author_only=False)

    print("[analyze] Computing publication type breakdown …")
    pubtypes = pubtype_stats(records)

    print("[analyze] Computing language breakdown …")
    languages = language_stats(records)

    print("[analyze] Computing author collaboration network …")
    auth_net = author_collab_network(records)

    return {
        "n_records":     len(records),
        "temporal":      temporal,
        "authors":       authors,
        "journals":      journals,
        "countries":     countries,
        "country_net":   country_net,
        "keywords":      kw_stats,
        "mesh":          mesh_stats,
        "institutions":         institutions,
        "institutions_all":     institutions_all_authors,
        "pub_types":     pubtypes,
        "languages":     languages,
        "author_net":    auth_net,
    }


if __name__ == "__main__":
    # Quick test with cached data
    for fname in ["records_cited.json", "records_disambig.json", "records.json"]:
        p = pathlib.Path(config.CACHE_DIR) / fname
        if p.exists():
            with open(p) as f:
                records = json.load(f)
            break

    from geo import enrich_countries
    records = enrich_countries(records)
    results = run_analysis(records)

    out = pathlib.Path(config.DATA_DIR) / "analysis.json"
    with open(out, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nSaved analysis to {out}")
    print(f"Total records: {results['n_records']}")
    print(f"Unique authors (≥{config.MIN_AUTHOR_PUBS} pubs): {len(results['authors'])}")
    print(f"Journals: {len(results['journals'])}")
    print(f"Countries: {len(results['countries'])}")
