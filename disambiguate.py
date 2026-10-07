"""
disambiguate.py — Author name disambiguation
=============================================
Heuristic approach combining:
  1. ORCID identity (gold standard — merges trivially)
  2. Exact last + forename match
  3. Last + initial + shared co-author overlap
  4. Affiliation string similarity for borderline cases

Output: assigns each author occurrence a canonical "author_id".
"""

import re
import collections
import json
import pathlib
import sys
import unicodedata

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import config


_UMLAUT = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "æ": "ae", "ø": "o"}


def _norm_last(s: str) -> str:
    """Normalize last name for bucketing: lowercase; German umlauts to their
    transliterations (Spörl = Spoerl); other diacritics stripped; hyphens,
    apostrophes and spaces removed (Sinha-Roy = Sinha Roy, O'Brart = OBrart)."""
    s = s.lower().strip()
    for k, v in _UMLAUT.items():
        s = s.replace(k, v)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[\s\-'’.]", "", s)


def _norm_fore(s: str) -> str:
    return s.lower().strip()


def _initials(fore: str, initials: str = "") -> str:
    """
    Initials string for an author occurrence.

    PubMed's own <Initials> field is authoritative when present ("TG" for
    "Theo Günter"); it is used first.  Deriving initials from the forename
    alone turned "TG" (a one-word forename) into "t", which put Theo Seiler
    senior and junior into the same bucket where the KNOWN_DISTINCT safelist
    could not reach them.
    """
    from_fore = "".join(w[0] for w in re.split(r"[\s.]+", fore) if w).lower()
    if initials and initials.strip():
        ini = re.sub(r"[^a-z]", "", initials.lower())
        # "D P S" with Initials "DP": the forename carries more information
        if from_fore.startswith(ini) and len(from_fore) > len(ini):
            return from_fore
        return ini
    return from_fore


def _fore_key(fore: str, initials: str) -> str:
    """Grouping key inside a surname bucket: full forename, or the full
    initials for initials-only occurrences ("__init__:tg")."""
    f = _norm_fore(fore) if fore else ""
    toks = [t for t in re.split(r"[\s.]+", f) if t]
    if toks and any(len(t) > 1 for t in toks):        # a real forename, not "T G" / "T.G."
        return f
    return "__init__:" + _initials(fore, initials)


def _initials_compatible(key_a: str, key_b: str) -> bool:
    """Initials of two group keys agree: equal, or one is a prefix of the other
    ("t" ~ "ta"; "tg" !~ "t" only when both are complete — a bare "t" may be an
    abbreviation of anything, so prefix relations are allowed)."""
    ia = key_a.split(":", 1)[1] if key_a.startswith("__init__:") else _initials(key_a)
    ib = key_b.split(":", 1)[1] if key_b.startswith("__init__:") else _initials(key_b)
    return ia == ib or ia.startswith(ib) or ib.startswith(ia)


def _key_forms(key: str) -> set[str]:
    """All name forms a group key can be compared under: the forename itself
    (if any) and its initials."""
    if key.startswith("__init__:"):
        return {key.split(":", 1)[1]}
    return {key, _initials(key)}


_NAME_SUFFIXES = {"junior", "júnior", "jr", "filho", "neto", "sobrinho", "senior", "sr"}


def _first_forename(fore_key: str) -> str:
    """First full forename token of a group key, folded ('' for initials only)."""
    if not fore_key or fore_key.startswith("__init__"):
        return ""
    toks = [t for t in re.split(r"[\s.]+", fore_key.lower()) if t and t not in _NAME_SUFFIXES]
    if not toks or len(toks[0]) < 2:
        return ""
    t = unicodedata.normalize("NFKD", toks[0]).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", t)


def _first_forenames_compatible(a: set, b: set) -> bool:
    """Every first forename in one cluster equals, or is a prefix of, every
    first forename in the other ('theo' ~ 'theodor'; 'yan' !~ 'yiran')."""
    for x in a:
        for y in b:
            if not (x == y or x.startswith(y) or y.startswith(x)):
                return False
    return True


def _forenames_compatible(a: str, b: str) -> bool:
    """'theo g' ~ 'theo günter' (same person, one abbreviates the other);
    'theo' !~ 'theo günter' (left to the co-author rule and the safelist)."""
    ta, tb = a.split(), b.split()
    if ta == tb:
        return True
    if len(ta) != len(tb) or not ta or ta[0] != tb[0]:
        return False
    for x, y in zip(ta[1:], tb[1:]):
        x, y = x.rstrip("."), y.rstrip(".")
        if x == y or (len(x) == 1 and y.startswith(x)) or (len(y) == 1 and x.startswith(y)):
            continue
        return False
    return True


def _affil_tokens(affil: str) -> set:
    """Tokenise affiliation string for rough similarity."""
    words = re.findall(r"[a-z]{4,}", affil.lower())
    return set(words)


def _affil_sim(a1: list, a2: list) -> float:
    """Jaccard similarity between two affiliation token sets."""
    t1 = set()
    for a in a1:
        t1 |= _affil_tokens(a)
    t2 = set()
    for a in a2:
        t2 |= _affil_tokens(a)
    if not t1 or not t2:
        return 0.0
    return len(t1 & t2) / len(t1 | t2)


# ── Known-distinct author pairs (same surname, different people) ──────────────
# Each entry is (last_norm, fore_norm_A, fore_norm_B).
# The disambiguator will NEVER merge an occurrence from group A with group B,
# regardless of co-author overlap or affiliation similarity.
# Add new entries here whenever a disambiguation error is identified.
KNOWN_DISTINCT: list[tuple[str, str, str]] = [
    # Theo Seiler Sr (Theo) vs Theo Günter Seiler Jr (Theo Günter / T.G.)
    ("seiler",  "theo",         "theo günter"),
    ("seiler",  "theo",         "theo g"),
    ("seiler",  "t",            "tg"),           # initials-only variants
    ("seiler",  "theo",         "tg"),           # forename vs junior's initials
    ("seiler",  "theo günter",  "t"),
    ("seiler",  "theo g",       "t"),
    # Farhad Hafezi (ELZA Institute, Zurich) vs Nikki L. Hafezi (ELZA Institute)
    ("hafezi",  "farhad",       "nikki"),
    ("hafezi",  "f",            "n"),
    # Add further forename-pair entries as needed:
    # ("surname", "forename_a",  "forename_b"),
]

# Build a fast lookup: (last_norm, init_a, init_b) → True (unordered)
_DISTINCT_SET: set[frozenset] = set()
for _last, _fa, _fb in KNOWN_DISTINCT:
    _DISTINCT_SET.add(frozenset({(_last, _fa), (_last, _fb)}))

# ── Affiliation-based exclusions ──────────────────────────────────────────────
# For cases where two authors share an IDENTICAL full name but are confirmed
# different people at different institutions/specialties.
# Each entry: (last_norm, fore_norm, affil_keyword_lowercase)
# Any occurrence whose affiliation contains affil_keyword will NEVER be merged
# with occurrences that lack it — even though forenames match exactly.
#
# Known case: Prof. Farhad Hafezi (plastic surgeon, Tehran University of Medical
# Sciences / Iran University of Medical Sciences) shares an identical full name
# with Prof. Farhad Hafezi (ophthalmologist, ELZA Institute Zurich / CXL pioneer).
# Layer 2 (exact forename match) would otherwise unconditionally merge these.
KNOWN_DISTINCT_AFFIL: list[tuple[str, str, str]] = [
    ("hafezi", "farhad", "tehran university"),
    ("hafezi", "farhad", "iran university of medical"),
    ("hafezi", "farhad", "iums.ac.ir"),
    # Add further entries as new same-name collisions are identified:
    # ("surname_norm", "fore_norm", "affil_keyword_lowercase"),
]

# Build fast lookup: (last_norm, fore_norm) → [affil_keywords]
_DISTINCT_AFFIL_MAP: dict[tuple[str, str], list[str]] = {}
for _last, _fore, _akw in KNOWN_DISTINCT_AFFIL:
    _DISTINCT_AFFIL_MAP.setdefault((_last.lower(), _fore.lower()), []).append(_akw.lower())


def _has_excluded_affil(last_n: str, fore_n: str, affils: list[str]) -> bool:
    """Return True if this occurrence carries an affiliation that marks it as
    a known distinct person who must never be merged with same-name occurrences
    lacking that affiliation keyword."""
    keywords = _DISTINCT_AFFIL_MAP.get((last_n.lower(), fore_n.lower()), [])
    if not keywords:
        return False
    affil_blob = " ".join(affils).lower()
    return any(kw in affil_blob for kw in keywords)


def _are_known_distinct(last_n: str, key_a: str, key_b: str) -> bool:
    """True if two group keys (forename or "__init__:xx") for the same surname
    are listed as different people, compared under every name form each key
    has (forename, initials)."""
    for fa in _key_forms(key_a.lower()):
        for fb in _key_forms(key_b.lower()):
            if frozenset({(last_n, fa), (last_n, fb)}) in _DISTINCT_SET:
                return True
    return False


def _display_name(last: str, fore: str, initials: str) -> str:
    """
    Build a standardised display name: 'Surname AB' format.
    Examples:
      Hafezi, Farhad        → Hafezi F
      Seiler, Theo Günter   → Seiler TG
      Seiler, Theo          → Seiler T
      Wollensak, Gregor     → Wollensak G
      Zhang, Lei            → Zhang L
    Always uses the forename to derive initials if available,
    falls back to the initials field, then to the raw last name.
    """
    if not last:
        return "Unknown"
    src = fore or initials or ""
    if src:
        inits = "".join(w[0].upper() for w in src.split() if w)
    else:
        inits = ""
    return f"{last} {inits}".strip() if inits else last


# ── Institution extraction for disambiguation ────────────────────────────────
# Lightweight version — just enough to split "Zhang L at Wenzhou" from
# "Zhang L at Peking University". Does NOT need the full analyze.py extractor.

# Surnames so common in CXL literature that same-initial = almost certainly
# different people unless institution also matches.
_COMMON_SURNAMES: set[str] = {
    # Chinese
    "zhang", "wang", "li", "liu", "chen", "yang", "huang", "zhao", "wu",
    "zhou", "sun", "ma", "zhu", "lin", "he", "gao", "luo", "zheng", "tang",
    "xu", "han", "feng", "cao", "xie", "wei", "deng", "ye", "liang", "xiao",
    # Korean
    "kim", "lee", "park", "choi", "jung", "kang", "cho", "yoon", "jang",
    "lim", "han", "oh", "seo", "shin", "kwon", "hong", "moon",
    # Japanese
    "sato", "suzuki", "takahashi", "tanaka", "watanabe", "ito", "yamamoto",
    "nakamura", "kobayashi", "kato", "yoshida", "yamada", "sasaki",
    # Indian (common in ophthalmology)
    "sharma", "kumar", "singh", "patel", "gupta", "mishra", "joshi",
    "agarwal", "mehta", "shah", "reddy", "nair", "pillai",
}

# Tokens that reliably identify an institution in an affiliation string.
# We only need city/institution-level discrimination, not full normalisation.
_INST_TOKENS_DIS = [
    # Universities — extract the word before "university" as the key
    r"(\b\w+(?:\s+\w+)?)\s+university",
    r"university\s+of\s+(\w+(?:\s+\w+)?)",
    # Hospitals / institutes with city names
    r"(\b\w+)\s+eye\s+(?:hospital|institute|centre|center)",
    r"(\b\w+)\s+(?:medical|ophthalmology)\s+(?:center|centre|hospital)",
    # Named institutes
    r"(elza|moorfields|bascom\s+palmer|wills\s+eye|noor|aravind|sankara|"
    r"lv\s+prasad|l\.v\.\s*prasad|narayana\s+nethralaya|iroc)",
    # City as fallback discriminator
    r",\s*([a-z\s]{4,20}),\s*(?:china|japan|korea|india|iran|taiwan)",
]

import re as _re

def _inst_key(affils: list[str]) -> str | None:
    """
    Extract a short institution discriminator key from affiliation strings.
    Returns a lowercase string like 'wenzhou' or 'peking' or None if unclear.
    """
    for affil in affils:
        al = affil.lower()
        for pattern in _INST_TOKENS_DIS:
            m = _re.search(pattern, al)
            if m:
                toks = [t for t in m.group(1).strip().rstrip(".,").split()
                        if t not in _KEY_STOPWORDS]
                key = " ".join(toks[-2:])
                if len(key) >= 3:
                    return key
    return None


_KEY_STOPWORDS = {"of", "to", "the", "at", "and", "an", "a", "in", "for", "with", "affiliated",
                  "from", "de", "di", "del", "della", "la", "le", "des", "der", "die", "das",
                  "national", "state", "medical", "normal", "technical", "technological"}


def _inst_conflict(affils_i: list[str], affils_j: list[str]) -> bool:
    """
    Return True if two affiliation sets clearly point to DIFFERENT institutions.
    Conservative: only returns True when we have confident keys for BOTH sides
    that are clearly different (not just missing data).
    """
    ki = _inst_key(affils_i)
    kj = _inst_key(affils_j)
    if ki is None or kj is None:
        return False   # can't tell — don't block merge
    # Allow partial match: "peking" matches "peking university hospital"
    if ki in kj or kj in ki:
        return False   # same institution
    return True        # clearly different institutions


# ── Build author occurrence table ─────────────────────────────────────────────

def build_occurrence_table(records: list[dict], oa_cache: dict | None = None) -> list[dict]:
    """
    Returns flat list of author occurrence dicts:
      pmid, position, last, fore, initials, affils, orcid, oa_id (when an
      OpenAlex cache is supplied; aligned by author order as in the overlay),
      co_authors (set of (last_norm, init) tuples of other authors in same paper)
    """
    occurrences = []
    for rec in records:
        authors = rec.get("authors", [])
        pmid = rec["pmid"]
        year = rec.get("year", "")
        oa_authors = []
        if oa_cache:
            w = oa_cache.get(str(pmid)) or {}
            if w.get("found"):
                oa_authors = w.get("authors") or []
        # Build co-author fingerprint set for this paper
        co_fps = set()
        for a in authors:
            if a["last"]:
                co_fps.add((_norm_last(a["last"]), _initials(a.get("fore", ""), a.get("initials", ""))))

        for pos, a in enumerate(authors):
            if not a["last"]:
                continue  # skip collective names
            occ = {
                "pmid":      pmid,
                "year":      year,
                "position":  pos,
                "last":      a["last"],
                "fore":      a["fore"],
                "initials":  a["initials"],
                "affils":    a["affils"],
                "orcid":     a["orcid"],
                "oa_id":     (oa_authors[pos].get("id") if pos < len(oa_authors) and len(oa_authors) == len(authors) else None),
                "last_norm": _norm_last(a["last"]),
                "init":      _initials(a.get("fore", ""), a.get("initials", "")),
                "fore_key":  _fore_key(a.get("fore", ""), a.get("initials", "")),
                "co_fps":    co_fps - {(_norm_last(a["last"]),
                                        _initials(a.get("fore", ""), a.get("initials", "")))},
            }
            occurrences.append(occ)
    return occurrences


# ── Disambiguation algorithm ──────────────────────────────────────────────────

def disambiguate(occurrences: list[dict]) -> dict[int, str]:
    """
    Returns mapping: occurrence_index -> canonical_author_id string.
    canonical_author_id  = "LastNorm_ForenameNorm"  (most common full name for that cluster)
    """
    n = len(occurrences)
    parent = list(range(n))  # Union-Find

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    # Cannot-link constraints, checked on every merge: two name forms that sit
    # on the same paper are two people (e.g. Xingtao and Xueyi Zhou, Jacek and
    # Jerzy Szaflik), and two clusters whose full first forenames differ are two
    # people however many co-authors they share (Yan / Yiran Wang).  Without
    # these an initials-only group ("Wang Y") can chain unrelated people.
    pm: dict[int, set] = {i: {occurrences[i]["pmid"]} for i in range(n)}
    fo: dict[int, set] = {i: ({_first_forename(occurrences[i]["fore_key"])} - {""}) for i in range(n)}

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx == ry:
            return
        if pm[rx] & pm[ry]:
            return
        if not _first_forenames_compatible(fo[rx], fo[ry]):
            return
        parent[rx] = ry
        pm[ry] |= pm.pop(rx)
        fo[ry] |= fo.pop(rx)

    # ── Pass 1: ORCID identity ─────────────────────────────────────────────
    # PubMed occasionally attaches an ORCID to the wrong author of a paper, so
    # an ORCID merges two occurrences only when their surnames are compatible
    # (equal, or one ending in the other, e.g. a double-barrelled surname).
    # Without this check one misplaced iD merges two different people.
    orcid_map: dict[str, list[int]] = collections.defaultdict(list)
    for i, occ in enumerate(occurrences):
        if not occ["orcid"]:
            continue
        la = occ["last_norm"]
        for j in orcid_map[occ["orcid"]]:
            lb = occurrences[j]["last_norm"]
            if la == lb or la.endswith(lb) or lb.endswith(la):
                union(i, j)
                break
        else:
            orcid_map[occ["orcid"]].append(i)

    # ── Pass 1b: OpenAlex author ID (when supplied) ────────────────────────
    # Same OpenAlex author ID + compatible surname → same person, unless the
    # pair is on the KNOWN_DISTINCT safelist (OpenAlex conflates the two Theo
    # Seilers under one ID) or one side carries a KNOWN_DISTINCT_AFFIL marker.
    oa_map: dict[str, int] = {}
    for i, occ in enumerate(occurrences):
        oid = occ.get("oa_id")
        if not oid:
            continue
        if oid not in oa_map:
            oa_map[oid] = i
            continue
        j = oa_map[oid]
        a, b = occurrences[i], occurrences[j]
        la, lb = a["last_norm"], b["last_norm"]
        if not (la == lb or la.endswith(lb) or lb.endswith(la)):
            continue
        if _are_known_distinct(la, a["fore_key"], b["fore_key"]):
            continue
        fa = "" if a["fore_key"].startswith("__init__") else a["fore_key"]
        fb = "" if b["fore_key"].startswith("__init__") else b["fore_key"]
        if _has_excluded_affil(la, fa, a["affils"]) != _has_excluded_affil(lb, fb, b["affils"]):
            continue
        union(i, j)

    # ── Pass 2: Group by (last_norm, first initial) ───────────────────────
    # The coarse bucket keeps "T" and "TG" variants of one surname as merge
    # candidates; inside it, occurrences are grouped by full forename, or by
    # full initials for initials-only occurrences ("__init__:tg").
    bucket: dict[tuple, list[int]] = collections.defaultdict(list)
    for i, occ in enumerate(occurrences):
        bucket[(occ["last_norm"], occ["init"][:1])].append(i)

    for (last_n, init), indices in bucket.items():
        fore_groups: dict[str, list[int]] = collections.defaultdict(list)
        for i in indices:
            fore_groups[occurrences[i]["fore_key"]].append(i)

        # Merge groups that share ≥ N co-authors (same-lab heuristic)
        group_list = list(fore_groups.items())
        for gi in range(len(group_list)):
            for gj in range(gi + 1, len(group_list)):
                fname_i, idxs_i = group_list[gi]
                fname_j, idxs_j = group_list[gj]

                # If one of them is the initials-only group, check co-author overlap
                co_i = set().union(*(occurrences[k]["co_fps"] for k in idxs_i))
                co_j = set().union(*(occurrences[k]["co_fps"] for k in idxs_j))
                overlap = len(co_i & co_j)

                # Affiliation similarity (take first available)
                affil_i = next((occurrences[k]["affils"] for k in idxs_i if occurrences[k]["affils"]), [])
                affil_j = next((occurrences[k]["affils"] for k in idxs_j if occurrences[k]["affils"]), [])
                asim = _affil_sim(affil_i, affil_j)

                # Decision: merge if strong evidence
                should_merge = False

                # Hard block 1: never merge known-distinct people
                if _are_known_distinct(last_n, fname_i, fname_j):
                    should_merge = False

                # Hard block 2: confirmed different institutions → different people
                # Applied more aggressively for common surnames
                elif _inst_conflict(affil_i, affil_j):
                    should_merge = False

                elif not fname_i.startswith("__init__") and not fname_j.startswith("__init__"):
                    # Both have forenames: merge only if the same or one
                    # abbreviates the other ("theo g" ~ "theo günter").
                    if _forenames_compatible(fname_i, fname_j):
                        if last_n in _COMMON_SURNAMES and _inst_conflict(affil_i, affil_j):
                            should_merge = False
                        else:
                            should_merge = True
                    else:
                        should_merge = False

                elif not _initials_compatible(fname_i, fname_j):
                    # e.g. "__init__:tg" vs forename "theo" (initials "t"):
                    # the initials disagree, so these are not one person
                    should_merge = False

                elif overlap >= config.DISAMBIGUATION_CO_AUTHOR_THRESHOLD:
                    # Initials-only group merging: for common surnames, also
                    # require that institutions are not in conflict
                    if last_n in _COMMON_SURNAMES and _inst_conflict(affil_i, affil_j):
                        should_merge = False
                    else:
                        should_merge = True

                elif asim >= config.DISAMBIGUATION_AFFIL_JACCARD and overlap >= 1:
                    # Affiliation-similarity merge: tighter threshold for
                    # common surnames to avoid false positives
                    if last_n in _COMMON_SURNAMES:
                        should_merge = (asim >= config.DISAMBIGUATION_AFFIL_JACCARD_COMMON
                                        and overlap >= config.DISAMBIGUATION_CO_AUTHOR_THRESHOLD_COMMON)
                    else:
                        should_merge = True

                if should_merge:
                    # Occurrences carrying a KNOWN_DISTINCT_AFFIL marker never
                    # take part in cross-group merges; they only merge with
                    # exact-forename occurrences carrying the same marker.
                    def _plain(idxs, fname):
                        fn = "" if fname.startswith("__init__") else fname.lower()
                        return [k for k in idxs
                                if not _has_excluded_affil(last_n, fn, occurrences[k]["affils"])]
                    for ki in _plain(idxs_i, fname_i):
                        for kj in _plain(idxs_j, fname_j):
                            union(ki, kj)

        # Within each fore_group, union occurrences (same forename = same person)
        # EXCEPTION 1: for common surnames, split by institution if clearly different.
        # EXCEPTION 2: for any surname, block merge if one occurrence carries an
        #   affiliation keyword that marks it as a known distinct person
        #   (KNOWN_DISTINCT_AFFIL safelist — handles same full-name collisions).
        # Use a secondary union-find within the group to handle chains correctly.
        for fname, idxs in fore_groups.items():
            fore_norm = "" if fname.startswith("__init__") else fname.lower()
            # Partition by affiliation-exclusion first: occurrences carrying an
            # excluded affiliation are kept permanently separate from those that don't.
            excluded_idxs = [k for k in idxs
                             if _has_excluded_affil(last_n, fore_norm, occurrences[k]["affils"])]
            normal_idxs   = [k for k in idxs if k not in excluded_idxs]

            # Union normal occurrences (with common-surname institution check)
            def _union_group(group_idxs: list[int]) -> None:
                if last_n not in _COMMON_SURNAMES or len(group_idxs) == 1:
                    for k in group_idxs[1:]:
                        union(k, group_idxs[0])
                else:
                    sub_clusters: list[list[int]] = []
                    for k in group_idxs:
                        affil_k = occurrences[k]["affils"]
                        merged = False
                        for cluster in sub_clusters:
                            rep = cluster[0]
                            all_affils = []
                            for m in cluster:
                                all_affils.extend(occurrences[m]["affils"])
                            if not _inst_conflict(affil_k, all_affils or occurrences[rep]["affils"]):
                                cluster.append(k)
                                merged = True
                                break
                        if not merged:
                            sub_clusters.append([k])
                    for cluster in sub_clusters:
                        for k in cluster[1:]:
                            union(k, cluster[0])

            if normal_idxs:
                _union_group(normal_idxs)
            # Excluded occurrences are unioned among themselves only
            if excluded_idxs:
                _union_group(excluded_idxs)
            # Normal and excluded groups are NEVER unioned with each other

    # ── Build canonical IDs ────────────────────────────────────────────────
    # For each component, pick the most frequent (last, fore) pair as canonical name
    comp_names: dict[int, collections.Counter] = collections.defaultdict(collections.Counter)
    for i, occ in enumerate(occurrences):
        root = find(i)
        fore = occ["fore"] or occ["initials"]
        comp_names[root][(occ["last"], fore)] += 1

    # Also collect affiliation samples per component for institution disambiguation
    comp_affils: dict[int, list] = collections.defaultdict(list)
    for i, occ in enumerate(occurrences):
        root = find(i)
        if occ["affils"]:
            comp_affils[root].extend(occ["affils"][:1])

    comp_canonical: dict[int, str] = {}
    for root, counter in comp_names.items():
        best_last, best_fore = counter.most_common(1)[0][0]
        # Prefer the longest forename for deriving initials — but only among
        # occurrences that use the modal surname, so a "Netto, Emilio A Torres"
        # parse cannot lend its initials to "Torres-Netto".
        # A variant seen once cannot set the label: "Júnior Renato" once
        # against "Renato" 114 times gave "Ambrósio JR", and "Seyed-Hassan"
        # once against "Hassan" 114 times gave "Hashemi S".  Generational
        # suffixes parsed into the forename are ignored for the same reason.
        best_initials = ""
        multi = [(k, n) for k, n in counter.most_common() if n >= 2] or counter.most_common()
        for (last, fore), _ in multi:
            if not fore or last != best_last:
                continue
            if re.search(r"\b(j[uú]nior|jr|filho|neto|sobrinho)\b", fore, re.I):
                continue
            if len(fore) > len(best_initials):
                best_initials = fore
        canonical = _display_name(best_last, best_initials, best_fore)

        # For common surnames, append institution discriminator to the display
        # name so that different Zhang Ls are visually distinguishable in outputs.
        # e.g. "Zhang L (Wenzhou)" vs "Zhang L (Peking)"
        if _norm_last(best_last) in _COMMON_SURNAMES:
            inst_key = _inst_key(comp_affils.get(root, []))
            if inst_key:
                # Capitalise first letter for readability
                inst_label = inst_key.title()
                canonical = f"{canonical} ({inst_label})"

        comp_canonical[root] = canonical

    # Two different components must never share one author_id: downstream
    # counting is keyed by the id string, so a collision would silently merge
    # people the disambiguator had kept apart (e.g. the two Farhad Hafezis).
    by_name: dict[str, list[int]] = collections.defaultdict(list)
    for root, name in comp_canonical.items():
        by_name[name].append(root)
    for name, roots in by_name.items():
        if len(roots) < 2:
            continue
        roots.sort(key=lambda r: -sum(comp_names[r].values()))   # largest keeps the bare name
        used = {name}
        for k, root in enumerate(roots[1:], start=2):
            key = _inst_key(comp_affils.get(root, []))
            label = key.title() if key else f"#{k}"
            cand = f"{name} ({label})"
            if cand in used or name.endswith(f"({label})"):
                # same institution too (e.g. Xingtao and Xueyi Zhou, both at
                # Fudan): distinguish by the component's modal forename
                fore = comp_names[root].most_common(1)[0][0][1] or f"#{k}"
                cand = (name[:-1] + f", {fore})") if name.endswith(")") else f"{name} ({fore})"
            while cand in used:
                cand = f"{cand} #{k}"
            used.add(cand)
            comp_canonical[root] = cand

    result = {i: comp_canonical[find(i)] for i in range(n)}
    return result


def assign_author_ids(records: list[dict], oa_cache: dict | None = None) -> tuple[list[dict], dict]:
    """
    Adds 'author_id' field to each author in every record.
    Returns (enriched_records, occurrence_table).
    """
    print("[disambiguate] Building author occurrence table …")
    if oa_cache is None:
        try:
            from openalex_integrate import load_cache
            oa_cache = load_cache() or None
        except Exception:  # noqa: BLE001
            oa_cache = None
    if oa_cache:
        print(f"[disambiguate] OpenAlex author IDs available for {len(oa_cache)} records (used as identity signal)")
    occ = build_occurrence_table(records, oa_cache)
    print(f"[disambiguate] {len(occ)} author occurrences across {len(records)} records")
    print("[disambiguate] Running disambiguation …")
    mapping = disambiguate(occ)

    # Count unique authors
    unique_ids = set(mapping.values())
    print(f"[disambiguate] Resolved to {len(unique_ids)} unique authors")

    # Write back into records
    occ_idx = 0
    for rec in records:
        authors = rec.get("authors", [])
        for a in authors:
            if not a["last"]:
                a["author_id"] = "__collective__"
            else:
                a["author_id"] = mapping[occ_idx]
                occ_idx += 1

    return records, occ


if __name__ == "__main__":
    cache_path = pathlib.Path(config.CACHE_DIR) / "records.json"
    with open(cache_path) as f:
        records = json.load(f)
    records, _ = assign_author_ids(records)
    out = pathlib.Path(config.CACHE_DIR) / "records_disambig.json"
    with open(out, "w") as f:
        json.dump(records, f, indent=2)
    print(f"Saved to {out}")
