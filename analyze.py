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


# ── Citation helpers ──────────────────────────────────────────────────────────
# A record without a citation count (no OpenAlex/CrossRef match) is None, never
# 0: it must not drag means down, and the number of such records is reported.

def _cc(rec: dict):
    v = rec.get("citation_count")
    return None if v is None else int(v)


def _cite_summary(vals: list) -> dict:
    """mean / median / IQR / n over KNOWN citation counts, plus n_null."""
    known = sorted(v for v in vals if v is not None)
    n = len(known)
    out = {"n_cited_known": n, "n_cite_null": len(vals) - n,
           "citations": int(sum(known)), "citations_mean": None,
           "citations_median": None, "citations_q1": None, "citations_q3": None}
    if n:
        out["citations_mean"] = round(sum(known) / n, 1)
        def q(p):
            k = (n - 1) * p
            f, c = int(math.floor(k)), int(math.ceil(k))
            return known[f] if f == c else known[f] + (known[c] - known[f]) * (k - f)
        out["citations_median"] = round(q(0.5), 1)
        out["citations_q1"] = round(q(0.25), 1)
        out["citations_q3"] = round(q(0.75), 1)
    return out
from geo import extract_country

# ─────────────────────────────────────────────────────────────────────────────
# 1. Temporal trends
# ─────────────────────────────────────────────────────────────────────────────

def temporal_trends(records: list[dict]) -> dict:
    """Publications per year, cumulative, and moving average."""
    by_year: dict[int, int] = collections.Counter()
    cite_by_year: dict[int, int] = collections.defaultdict(int)
    cite_null_by_year: dict[int, int] = collections.Counter()
    cites_list_by_year: dict[int, list] = collections.defaultdict(list)
    for rec in records:
        try:
            y = int(rec.get("year", 0))
        except (ValueError, TypeError):
            continue
        if config.START_YEAR <= y <= config.END_YEAR:
            by_year[y] += 1
            cc = _cc(rec)
            if cc is None:
                cite_null_by_year[y] += 1
            else:
                cite_by_year[y] += cc
                cites_list_by_year[y].append(cc)

    years = sorted(by_year.keys())
    counts = [by_year[y] for y in years]
    cumulative = list(itertools.accumulate(counts))
    citations = [cite_by_year[y] for y in years]
    cite_null = [cite_null_by_year[y] for y in years]
    cite_mean = [round(cite_by_year[y] / len(cites_list_by_year[y]), 1) if cites_list_by_year[y] else None
                 for y in years]
    cite_median = [_cite_summary(cites_list_by_year[y])["citations_median"] for y in years]

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
        "citations_null": cite_null,
        "citations_mean_per_paper": cite_mean,
        "citations_median_per_paper": cite_median,
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
    cite_lists: dict[str, list]       = collections.defaultdict(list)
    affils_sample: dict[str, list]    = collections.defaultdict(list)
    journals_per_auth: dict[str, set] = collections.defaultdict(set)
    years_per_auth: dict[str, set]    = collections.defaultdict(set)

    for rec in records:
        cc = _cc(rec)
        jrnl = rec.get("journal_abbr") or rec.get("journal", "")
        try:
            yr = int(rec.get("year", 0))
        except (ValueError, TypeError):
            yr = 0

        authors = rec.get("authors", [])
        # Filter out collective/anonymous entries for position calculation.
        # Build an index by object id so last-author detection is O(1) and
        # immune to duplicate dicts (named.index() would return the first match).
        named = [a for a in authors if a.get("author_id") and a["author_id"] != "__collective__"]
        n_named = len(named)
        named_last_id = id(named[-1]) if named else None
        for pos, a in enumerate(authors):
            aid = a.get("author_id")
            if not aid or aid == "__collective__":
                continue
            pubs[aid].append(rec)
            cite_lists[aid].append(cc)
            if cc is not None:
                citations[aid] += cc
            journals_per_auth[aid].add(jrnl)
            if yr:
                years_per_auth[aid].add(yr)
            if pos == 0:
                first_auth[aid] += 1
            # Last author: final named position (senior/PI convention).
            # Only meaningful for multi-author papers (≥2 named authors).
            if n_named >= 2 and id(a) == named_last_id:
                last_auth[aid] += 1
            if a.get("affils") and len(affils_sample[aid]) < 3:
                affils_sample[aid].extend(a["affils"][:2])

    # Estimate h-index from available citation counts
    # (real h-index needs per-paper citations, not author totals)
    # We estimate: h ≈ √(total_citations / pub_count) × correction
    def est_h(total_cites, n_pubs):
        if n_pubs == 0 or total_cites is None:
            return 0
        return min(round(math.sqrt(total_cites * 0.5)), n_pubs)

    rows = []
    for aid, rec_list in pubs.items():
        n = len(rec_list)
        if n < config.MIN_AUTHOR_PUBS:
            continue
        tc = citations[aid]
        yrs = sorted(years_per_auth[aid])
        csum = _cite_summary(cite_lists[aid])
        rows.append({
            "author_id":          aid,
            "pub_count":          n,
            "n_cited_known":      csum["n_cited_known"],
            "citations_median":   csum["citations_median"],
            "citations_q1":       csum["citations_q1"],
            "citations_q3":       csum["citations_q3"],
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
        cc = _cc(rec)
        if jname not in counter:
            counter[jname] = {"journal": jname, "abbr": jabbr,
                               "count": 0, "_cites": []}
        counter[jname]["count"] += 1
        counter[jname]["_cites"].append(cc)

    rows = sorted(counter.values(), key=lambda x: x["count"], reverse=True)
    total = len(records)
    for r in rows:
        r.update(_cite_summary(r.pop("_cites")))
        r["percentage"] = round(r["count"] / total * 100, 2)
        r["cites_per_pub"] = r["citations_mean"]
    return rows


def bradford_zones(journals: list[dict], n_records: int = None,
                   n_zones: int = 3) -> dict:
    """Partition the journal list into Bradford zones of equal productivity.

    Bradford's Law of Scattering holds that if journals are ranked by the
    number of papers they carry on a subject and then divided into zones
    each containing roughly the same number of papers, the number of
    journals in successive zones grows in the ratio 1 : n : n^2.

    The partition here is the standard one: walk the rank-ordered list
    accumulating publications and close a zone as soon as its running
    total reaches total/n_zones.  The journal that crosses the boundary is
    kept in the zone it completes, so zone totals are approximately, not
    exactly, equal - which is what the law describes.

    Returns a dict with per-zone summaries, the Bradford multipliers
    between consecutive zones, and the rank-ordered cumulative curve used
    to draw the Bradford plot.
    """
    ranked = sorted(journals, key=lambda r: r["count"], reverse=True)
    total  = n_records if n_records is not None else sum(r["count"] for r in ranked)
    if not ranked or total <= 0:
        return {"total_publications": 0, "total_journals": 0,
                "n_zones": n_zones, "zones": [], "multipliers": [],
                "curve": []}

    target = total / float(n_zones)

    zones: list[dict] = []
    cum = 0
    running = 0
    zone_idx = 1
    members: list[dict] = []
    curve: list[dict] = []

    for rank, r in enumerate(ranked, 1):
        members.append(r)
        running += r["count"]
        cum     += r["count"]
        curve.append({
            "rank":            rank,
            "journal":         r["journal"],
            "abbr":            r.get("abbr") or r["journal"],
            "count":           r["count"],
            "cumulative":      cum,
            "cumulative_pct":  round(cum / total * 100, 2),
            "zone":            zone_idx,
        })
        # Close the zone once it holds its share, unless this is the last
        # zone (which takes the remainder) or nothing would be left over.
        if zone_idx < n_zones and running >= target and rank < len(ranked):
            zones.append(_zone_summary(zone_idx, members, total))
            members = []
            running = 0
            zone_idx += 1

    if members:
        zones.append(_zone_summary(zone_idx, members, total))

    multipliers = []
    for a, b in zip(zones, zones[1:]):
        multipliers.append(round(b["journal_count"] / a["journal_count"], 2)
                           if a["journal_count"] else None)

    return {
        "total_publications": total,
        "total_journals":     len(ranked),
        "n_zones":            n_zones,
        "zones":              zones,
        "multipliers":        multipliers,
        "curve":              curve,
    }


def _zone_summary(idx: int, members: list[dict], total: int) -> dict:
    pubs  = sum(r["count"] for r in members)
    cites = sum(r.get("citations", 0) for r in members)
    return {
        "zone":                idx,
        "journal_count":       len(members),
        "publications":        pubs,
        "publication_pct":     round(pubs / total * 100, 2),
        "citations":           cites,
        "citations_per_pub":   round(cites / pubs, 2) if pubs else 0.0,
        "journals":            [{"journal": r["journal"],
                                 "abbr":    r.get("abbr") or r["journal"],
                                 "count":   r["count"],
                                 "citations": r.get("citations", 0)}
                                for r in members],
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4. Country analysis
# ─────────────────────────────────────────────────────────────────────────────

_POP_CACHE: dict[str, int] | None = None


def load_populations() -> dict[str, int]:
    """country display name → 2024 population (data/populations_worldbank_2024.csv)."""
    global _POP_CACHE
    if _POP_CACHE is None:
        import csv as _csv
        p = pathlib.Path(config.DATA_DIR) / "populations_worldbank_2024.csv"
        d: dict[str, int] = {}
        if p.exists():
            with open(p, encoding="utf-8") as fh:
                for row in _csv.DictReader(l for l in fh if not l.startswith("#")):
                    try:
                        d[row["country"]] = int(row["population_2024"])
                    except (KeyError, ValueError):
                        pass
        _POP_CACHE = d
    return _POP_CACHE


def country_stats(records: list[dict], min_pubs_per_capita: int = 0) -> list[dict]:
    """Publication and citation counts per country (first author).

    Per-capita output uses the 2024 populations in
    data/populations_worldbank_2024.csv (World Bank WDI SP.POP.TOTL, which
    follows UN WPP 2024).  Rows carry percentage of all records and of the
    records with a resolved country; ranks are competition ranks (ties '=n').
    """
    counter: dict[str, dict] = {}
    for rec in records:
        c = rec.get("country", "Unknown") or "Unknown"
        if c not in counter:
            counter[c] = {"country": c, "count": 0, "_cites": []}
        counter[c]["count"] += 1
        counter[c]["_cites"].append(_cc(rec))

    rows = sorted(counter.values(), key=lambda x: (-x["count"], x["country"]))
    total = len(records)
    resolved = sum(r["count"] for r in rows if r["country"] != "Unknown")
    pops = load_populations()
    from institutions import competition_ranks
    ranks = competition_ranks([r["count"] for r in rows if r["country"] != "Unknown"])
    ri = iter(ranks)
    for r in rows:
        r.update(_cite_summary(r.pop("_cites")))
        r["percentage"] = round(r["count"] / total * 100, 2)
        r["pct_of_resolved"] = round(r["count"] / resolved * 100, 2) if resolved and r["country"] != "Unknown" else None
        r["rank"] = next(ri) if r["country"] != "Unknown" else ""
        r["cites_per_pub"] = r["citations_mean"]
        pop = pops.get(r["country"])
        r["population_2024"] = pop
        if pop and r["count"] >= min_pubs_per_capita:
            r["pubs_per_million"]  = round(r["count"] / (pop / 1e6), 2)
            r["cites_per_million"] = round(r["citations"] / (pop / 1e6), 1)
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
            # Prefer OpenAlex/ROR country when the hybrid overlay supplied it;
            # fall back to affiliation-string parsing otherwise.
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
# Keyword synonyms now live in data/keyword_synonyms.csv (keywords.py).
# MeSH noise headings excluded from thematic charts:
_KW_EXCLUDE: set[str] = {
    "cornea", "humans", "adult", "female", "male", "aged", "middle aged",
    "prospective studies", "retrospective studies", "treatment outcome",
    "follow-up studies", "visual acuity", "refraction, ocular", "young adult",
    "adolescent", "child", "aged, 80 and over", "animals",
}


def _clean_keyword(kw: str) -> str | None:
    """Backward-compatible wrapper: normalise one author keyword (keywords.py)."""
    import keywords
    t = keywords.normalize(kw)
    if t is None or t.lower() in _KW_EXCLUDE:
        return None
    return t


def keyword_stats(records: list[dict], use_mesh: bool | None = None,
                  source: str = "author", exclude_search_terms: bool = True) -> dict:
    """
    Keyword frequencies and co-occurrences.

    source: "author" (author-supplied keywords, normalised via keywords.py),
            "mesh" (MeSH descriptors only), or "both".
    use_mesh: deprecated alias — True → "mesh" (was MeSH ∪ author keywords in
            v2, which the paper mislabelled as MeSH).
    exclude_search_terms: drop the canonical search concept ("corneal
            cross-linking (CXL)") from freq; its count is kept in "excluded".
    Returns freq, cooccurrence, excluded, coverage (share of records with any
    author keyword — the denominator for every thematic statement).
    """
    import keywords as _kw
    if use_mesh is not None:
        source = "mesh" if use_mesh else "author"
    freq:  dict[str, int]   = collections.Counter()
    cooc:  dict[tuple, int] = collections.Counter()
    excluded: dict[str, int] = collections.Counter()

    for rec in records:
        terms = set()
        for t in _kw.record_terms(rec, source):
            if t.lower() in _KW_EXCLUDE:
                continue
            if exclude_search_terms and t in _kw.SEARCH_TERM_CANONICALS:
                excluded[t] += 1
                continue
            terms.add(t)
        for k in terms:
            freq[k] += 1
        for k1, k2 in itertools.combinations(sorted(terms), 2):
            cooc[(k1, k2)] += 1

    freq_filtered = {k: v for k, v in freq.items() if v >= config.MIN_KEYWORD_FREQ}
    cooc_filtered = {k: v for k, v in cooc.items()
                     if v >= config.MIN_COOCCURRENCE
                     and k[0] in freq_filtered and k[1] in freq_filtered}
    cov = _kw.coverage_overall(records) if source != "mesh" else \
        {"n_records": len(records), "n_with_author_keywords": sum(1 for r in records if r.get("mesh")),
         "pct": round(100 * sum(1 for r in records if r.get("mesh")) / len(records), 1) if records else 0.0}

    return {
        "source":       source,
        "freq":         freq_filtered,
        "cooccurrence": {f"{k[0]}|||{k[1]}": v for k, v in cooc_filtered.items()},
        "excluded":     dict(excluded),
        "coverage":     {"overall_pct": cov["pct"], "n_with_keywords": cov["n_with_author_keywords"],
                         "n_records": cov["n_records"],
                         "by_year": _kw.coverage_by_year(records) if source != "mesh" else []},
    }


# ─────────────────────────────────────────────────────────────────────────────
# 6. Institution analysis
# ─────────────────────────────────────────────────────────────────────────────

# ── Institution alias table ──────────────────────────────────────────────────
# Maps lowercase fragments → canonical institution name.
# Checked BEFORE the generic extractor. Add new entries here freely.
# Institution alias table now lives in data/institution_aliases.csv (institutions.py).

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


# ── Affiliation segmentation (added: fixes institution attribution) ───────────
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.\w+\.?")
_ATTRIB_RE = re.compile(r"\([A-Z][a-zA-Z'\-]+(?:,\s*[A-Z][a-zA-Z'\-]+)*\)")


def _affil_segments(affil: str, first_surname: str = "") -> list[str]:
    """Split one PubMed <Affiliation> element into individual institution segments.

    PubMed supplies an author's affiliations in two shapes that the naive
    parser mishandles:

    1. All affiliations joined into ONE element with semicolons.  Taking the
       whole string yields only the first institution and silently discards
       every other one the author listed.
    2. Journal-style combined blocks that list SEVERAL authors' affiliations
       with parenthesised name attributions, e.g.
       "Dept, Inst A, City (Smith, Jones); Dept, Inst B, City (Brown)".
       Parsing the whole string credits Inst A to every first author on such a
       paper, regardless of where that author actually works.

    A trailing corresponding-author e-mail also defeats the parser, which then
    returns fragments like "Switzerland. name@example.com".
    """
    s = _EMAIL_RE.sub("", affil or "").strip().rstrip(".").strip()
    if not s:
        return []
    if _ATTRIB_RE.search(s):
        parts = re.split(r";\s*", s)
        if first_surname:
            mine = [p for p in parts
                    if "(" in p and re.search(r"\b" + re.escape(first_surname) + r"\b", p)]
            if mine:
                return [p.strip() for p in mine if p.strip()]
        return [parts[0].strip()] if parts else []
    return [p.strip() for p in re.split(r";\s*", s) if p.strip()]


def _norm_institution(affil: str) -> str | None:
    """Canonical institution for one affiliation segment (see institutions.py)."""
    import institutions
    return institutions.resolve(affil).canonical


def institution_stats(records: list[dict],
                      first_author_only: bool = False,
                      level: str = "canonical",
                      counting: str = "primary",
                      top_n: int = 50) -> list[dict]:
    """Institutional publication and citation counts.

    first_author_only: True → the first author only (the originating group);
        False → all co-authors' institutions (inflates frequent co-authors).
    level: "canonical" | "parent" | "cluster" (institutions.py alias table).
    counting: "primary" → one institution per author (their first resolvable
        affiliation); "whole" → every institution the author lists, 1 each;
        "fractional" → every institution, 1/k each.
    Rows carry competition ranks (ties shown as '=n').  Use
    institution_stats_meta() to also get the unresolved counts.
    """
    rows, _ = institution_stats_meta(records, first_author_only, level, counting, top_n)
    return rows


def institution_stats_meta(records: list[dict], first_author_only: bool = False,
                           level: str = "canonical", counting: str = "primary",
                           top_n: int = 50) -> tuple[list[dict], dict]:
    import institutions
    counter: dict[str, float] = collections.Counter()
    cite_sum: dict[str, float] = collections.defaultdict(float)
    n_cited: dict[str, int] = collections.Counter()
    meta = {"n_records": len(records), "n_no_affiliation": 0, "n_unresolved": 0,
            "n_resolved": 0, "level": level, "counting": counting,
            "first_author_only": first_author_only}
    for rec in records:
        cc = rec.get("citation_count")
        authors = rec.get("authors", []) or []
        if first_author_only:
            authors = authors[:1]
        surname = (authors[0].get("last") or "") if authors else ""
        seen: dict[str, float] = {}
        any_affil = False
        for a in authors:
            if a.get("affils"):
                any_affil = True
            res = institutions.author_institutions(a, surname, rec.get("pmid"))
            if not res:
                continue
            if counting == "primary":
                res = res[:1]
            w = 1.0 / len(res) if counting == "fractional" else 1.0
            for r in res:
                name = r.at(level)
                if not name or len(name) < 4:
                    continue
                seen[name] = max(seen.get(name, 0.0), w)
        # Denominators, on the same basis as the counting scheme: a record counts
        # as resolved when the authors being credited yield at least one
        # institution. Reported percentages then share a denominator with the
        # counts above them, whichever scheme is in use.
        if not any_affil:
            meta["n_no_affiliation"] += 1
        elif not seen:
            meta["n_unresolved"] += 1
        else:
            meta["n_resolved"] += 1
        for name, w in seen.items():
            counter[name] += w
            if cc is not None:
                cite_sum[name] += w * cc
                n_cited[name] += 1
    top = counter.most_common(top_n)
    counts = [round(v, 3) for _, v in top]
    ranks = institutions.competition_ranks([int(round(c)) if counting != "fractional" else c for c in counts])
    rows = []
    for (k, v), rk in zip(top, ranks):
        rows.append({"institution": k, "count": (int(round(v)) if counting != "fractional" else round(v, 2)),
                     "citations": int(round(cite_sum[k])), "n_cited_known": n_cited[k],
                     "rank": rk,
                     "pct_of_total": round(100 * v / len(records), 2) if records else 0.0,
                     "pct_of_resolved": (round(100 * v / meta["n_resolved"], 2)
                                         if meta["n_resolved"] else None)})
    return rows, meta


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

    print("[analyze] Computing Bradford zones …")
    bradford = bradford_zones(journals, n_records=len(records))

    print("[analyze] Computing country statistics …")
    countries = country_stats(records)

    print("[analyze] Computing country collaboration network …")
    country_net = country_collab_network(records)

    print("[analyze] Computing keyword statistics …")
    kw_stats = keyword_stats(records, source="author")
    mesh_stats = keyword_stats(records, source="mesh")
    kw_both = keyword_stats(records, source="both")

    print("[analyze] Computing institution statistics …")
    _first_only = getattr(config, "INSTITUTION_FIRST_AUTHOR_ONLY", True)
    institutions, institutions_meta = institution_stats_meta(
        records, first_author_only=_first_only,
        level=getattr(config, "INSTITUTION_LEVEL", "canonical"),
        counting=getattr(config, "INSTITUTION_COUNTING", "primary"))
    # The scheme not used as the headline is always computed too, so the
    # manuscript's sensitivity table cannot drift from the main one.
    institutions_alt, institutions_alt_meta = institution_stats_meta(
        records, first_author_only=not _first_only,
        level=getattr(config, "INSTITUTION_LEVEL", "canonical"),
        counting="primary" if _first_only else "primary")
    institutions_all_authors = institution_stats(records, first_author_only=False, counting="whole")

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
        "bradford":      bradford,
        "countries":     countries,
        "country_net":   country_net,
        "keywords":      kw_stats,
        "mesh":          mesh_stats,
        "keywords_combined": kw_both,
        "institutions":         institutions,
        "institutions_meta":    institutions_meta,
        "institutions_alt":      institutions_alt,
        "institutions_alt_meta": institutions_alt_meta,
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
