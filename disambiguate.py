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

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import config


def _norm_last(s: str) -> str:
    """Normalize last name: lowercase, strip diacritics (simple ASCII fold)."""
    s = s.lower().strip()
    # Simple transliteration of common accented chars
    accents = {'à':'a','á':'a','â':'a','ã':'a','ä':'a','å':'a','ç':'c',
               'è':'e','é':'e','ê':'e','ë':'e','ì':'i','í':'i','î':'i','ï':'i',
               'ñ':'n','ò':'o','ó':'o','ô':'o','õ':'o','ö':'o',
               'ù':'u','ú':'u','û':'u','ü':'u','ý':'y','ÿ':'y'}
    tr = str.maketrans(accents)
    return s.translate(tr)


def _norm_fore(s: str) -> str:
    return s.lower().strip()


def _initials(fore: str) -> str:
    """Return initials string, e.g. 'John A' -> 'ja', 'J' -> 'j'."""
    return "".join(w[0] for w in fore.split() if w).lower()


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
    # Theo Seiler Sr (corneal refractive surgery, IROC Zurich) vs
    # Theo Günter Seiler Jr (ELZA Institute) — both active in keratoconus/ectasia
    ("seiler",  "theo",         "theo günter"),
    ("seiler",  "theo",         "theo g"),
    ("seiler",  "t",            "tg"),
    # Farhad Hafezi (ELZA Institute, Zurich — CXL/keratoconus) vs
    # Nikki L. Hafezi (ELZA Institute — distinct author)
    ("hafezi",  "farhad",       "nikki"),
    ("hafezi",  "f",            "n"),
    # Add further forename-pair entries as disambiguation errors are identified:
    # ("surname", "forename_a", "forename_b"),
]

# Build fast lookup: (last_norm, init_a, init_b) → True (unordered)
_DISTINCT_SET: set[frozenset] = set()
for _last, _fa, _fb in KNOWN_DISTINCT:
    _DISTINCT_SET.add(frozenset({(_last, _fa), (_last, _fb)}))

# ── Affiliation-based exclusions ──────────────────────────────────────────────
# Handles same-full-name collisions between unrelated authors.
# Each entry: (last_norm, fore_norm, affil_keyword_lowercase)
KNOWN_DISTINCT_AFFIL: list[tuple[str, str, str]] = [
    # Prof. Farhad Hafezi (plastic surgeon, Tehran / Iran University of Medical
    # Sciences) vs Prof. Farhad Hafezi (ophthalmologist, ELZA Institute Zurich).
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


def _are_known_distinct(last_n: str, fore_a: str, fore_b: str) -> bool:
    """Return True if these two forenames for the same surname are known to be different people."""
    pair = frozenset({(last_n, fore_a.lower()), (last_n, fore_b.lower())})
    if pair in _DISTINCT_SET:
        return True
    # Also check initials: if one is a full forename, derive its initials
    init_a = _initials(fore_a) if len(fore_a) > 2 else fore_a.lower()
    init_b = _initials(fore_b) if len(fore_b) > 2 else fore_b.lower()
    pair_init = frozenset({(last_n, init_a), (last_n, init_b)})
    return pair_init in _DISTINCT_SET


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
                key = m.group(1).strip().rstrip(".,")
                if len(key) >= 3:
                    return key
    return None


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

def build_occurrence_table(records: list[dict]) -> list[dict]:
    """
    Returns flat list of author occurrence dicts:
      pmid, position, last, fore, initials, affils, orcid,
      co_authors (set of (last_norm, init) tuples of other authors in same paper)
    """
    occurrences = []
    for rec in records:
        authors = rec.get("authors", [])
        pmid = rec["pmid"]
        year = rec.get("year", "")
        # Build co-author fingerprint set for this paper
        co_fps = set()
        for a in authors:
            if a["last"]:
                co_fps.add((_norm_last(a["last"]), _initials(a["fore"] or a["initials"])))

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
                "last_norm": _norm_last(a["last"]),
                "init":      _initials(a["fore"] or a["initials"]),
                "co_fps":    co_fps - {(_norm_last(a["last"]),
                                        _initials(a["fore"] or a["initials"]))},
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

    def union(x, y):
        parent[find(x)] = find(y)

    # ── Pass 1: ORCID identity ─────────────────────────────────────────────
    orcid_map: dict[str, int] = {}  # orcid -> first occurrence index
    for i, occ in enumerate(occurrences):
        if occ["orcid"]:
            if occ["orcid"] in orcid_map:
                union(i, orcid_map[occ["orcid"]])
            else:
                orcid_map[occ["orcid"]] = i

    # ── Pass 2: Group by (last_norm, init) ────────────────────────────────
    bucket: dict[tuple, list[int]] = collections.defaultdict(list)
    for i, occ in enumerate(occurrences):
        bucket[(occ["last_norm"], occ["init"])].append(i)

    for (last_n, init), indices in bucket.items():
        # Everyone with same last + initials is a candidate cluster
        # Sub-split by forename if available
        fore_groups: dict[str, list[int]] = collections.defaultdict(list)
        for i in indices:
            fore_key = _norm_fore(occurrences[i]["fore"]) if occurrences[i]["fore"] else "__init__"
            fore_groups[fore_key].append(i)

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

                elif fname_i != "__init__" and fname_j != "__init__":
                    # Both have full forenames: only merge if identical
                    # For common surnames, also require institution agreement
                    if fname_i == fname_j:
                        if last_n in _COMMON_SURNAMES and _inst_conflict(affil_i, affil_j):
                            should_merge = False
                        else:
                            should_merge = True
                    else:
                        should_merge = False

                elif overlap >= config.DISAMBIGUATION_CO_AUTHOR_THRESHOLD:
                    # Initials-only group merging: for common surnames, also
                    # require that institutions are not in conflict
                    if last_n in _COMMON_SURNAMES and _inst_conflict(affil_i, affil_j):
                        should_merge = False
                    else:
                        should_merge = True

                elif asim >= 0.35 and overlap >= 1:
                    # Affiliation-similarity merge: tighten threshold for
                    # common surnames to avoid false positives
                    if last_n in _COMMON_SURNAMES:
                        should_merge = (asim >= 0.55 and overlap >= 2)
                    else:
                        should_merge = True

                if should_merge:
                    for ki in idxs_i:
                        for kj in idxs_j:
                            union(ki, kj)

        # Within each fore_group, union occurrences (same forename = same person)
        # EXCEPTION 1: for common surnames, split by institution if clearly different.
        # EXCEPTION 2: for any surname, block merge if one occurrence carries an
        #   affiliation keyword that marks it as a known distinct person
        #   (KNOWN_DISTINCT_AFFIL safelist — handles same full-name collisions).
        # Use a secondary union-find within the group to handle chains correctly.
        for fname, idxs in fore_groups.items():
            fore_norm = fname.lower()
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
        # Prefer the longest forename for deriving initials
        best_initials = ""
        for (last, fore), _ in counter.most_common():
            if fore and len(fore) > len(best_initials):
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

    result = {i: comp_canonical[find(i)] for i in range(n)}
    return result


def assign_author_ids(records: list[dict]) -> tuple[list[dict], dict]:
    """
    Adds 'author_id' field to each author in every record.
    Returns (enriched_records, occurrence_table).
    """
    print("[disambiguate] Building author occurrence table …")
    occ = build_occurrence_table(records)
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
