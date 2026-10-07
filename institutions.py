"""
institutions.py — institution resolution from affiliation strings
=================================================================

The alias table lives in ``data/institution_aliases.csv`` (published with the
SDC) rather than in code:

    pattern, is_regex, canonical, parent, cluster, country, tier, note

  tier 1  named clinical institutions (eye hospitals, institutes) — beat tier 2
  tier 2  universities and everything else
  tier 3  weak fallbacks (a city name), used only when nothing else matches

Within a tier the LONGEST matching pattern wins.  When the alias table does not
match, the comma-segment scorer inherited from analyze.py is used.

Resolution levels:
  canonical  the institution as named (ELZA Institute, University of Zurich …)
  parent     the parent organisation (Massachusetts Eye and Ear → Harvard)
  cluster    a research cluster label (zurich_cluster) — for the sensitivity
             analysis that merges co-located, overlapping groups

Attribution rule for the primary table: the FIRST AUTHOR's PRIMARY affiliation
(the first affiliation segment that resolves).  Whole (every affiliation the
first author lists) and fractional (1/k) counting are produced by sensitivity.py.
"""

from __future__ import annotations

import csv
import dataclasses
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import config

ALIAS_PATH = pathlib.Path(config.DATA_DIR) / "institution_aliases.csv"
CORRECTIONS_PATH = pathlib.Path(config.DATA_DIR) / "affiliation_corrections.csv"


@dataclasses.dataclass
class Alias:
    pattern: str
    regex: re.Pattern
    canonical: str
    parent: str
    cluster: str
    country: str
    tier: int
    note: str = ""


@dataclasses.dataclass
class Resolution:
    canonical: str | None
    parent: str | None = None
    cluster: str = ""
    matched_by: str = ""
    tier: int = 0

    def at(self, level: str) -> str | None:
        if level == "parent":
            return self.parent or self.canonical
        if level == "cluster":
            return self.cluster or self.parent or self.canonical
        return self.canonical


_ALIASES: list[Alias] | None = None


def load_aliases(path: pathlib.Path | None = None) -> list[Alias]:
    global _ALIASES
    if _ALIASES is not None and path is None:
        return _ALIASES
    path = path or ALIAS_PATH
    out: list[Alias] = []
    with open(path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            pat = (row.get("pattern") or "").strip()
            if not pat:
                continue
            is_rx = (row.get("is_regex") or "0").strip() in ("1", "true", "True", "yes")
            rx = re.compile(pat if is_rx else re.escape(pat.lower()), re.I)
            out.append(Alias(pat, rx, row["canonical"].strip(), (row.get("parent") or "").strip() or row["canonical"].strip(),
                             (row.get("cluster") or "").strip(), (row.get("country") or "").strip(),
                             int(row.get("tier") or 2), (row.get("note") or "").strip()))
    if path == ALIAS_PATH:
        _ALIASES = out
    return out


def reset() -> None:
    global _CORRECTIONS
    _CORRECTIONS = None
    global _ALIASES
    _ALIASES = None


# ── Fallback segment scorer (from analyze.py) ─────────────────────────────────

_DEPT_PREFIXES = (
    "department", "dept", "division", "unit", "section", "laboratory", "lab ",
    "service", "clinic for", "faculty", "school of", "college of", "institute of",
    "center for", "centre for", "program", "programme", "group",
    "abteilung", "klinik für", "klinik fur", "augenklinik", "universitäts-augenklinik",
    "servicio", "departamento", "dipartimento", "clinica", "service d'", "unité", "u.o.",
)
_INST_TOKENS = ("university", "universität", "universitat", "université", "universidad", "universidade",
                "università", "universita", "hospital", "hôpital", "hopital", "ospedale", "krankenhaus",
                "klinikum", "institute", "institut", "instituto", "college", "eye center", "eye centre",
                "eye hospital", "medical center", "medical centre", "clinic", "foundation", "academy",
                "infirmary", "nethralaya", "policlinico", "azienda", "ircc")
_GENERIC_RESULTS = {
    "division of clinical neuroscience", "school of medicine", "school of optometry",
    "college of medicine", "institute of biochemical and biomedical engineering",
    "research institute of eye diseases", "augenheilkunde", "augenabteilung",
    "department of ophthalmology", "faculty of medicine", "medical school",
}
_COUNTRY_WORDS = {"usa", "uk", "germany", "france", "italy", "spain", "china", "india", "iran",
                  "brazil", "australia", "switzerland", "netherlands", "israel", "japan",
                  "south korea", "turkey", "egypt", "canada", "greece", "austria", "belgium"}


def _is_dept(seg: str) -> bool:
    sl = seg.lower().strip()
    return any(sl.startswith(p) for p in _DEPT_PREFIXES)


def _is_inst(seg: str) -> bool:
    sl = seg.lower()
    return any(tok in sl for tok in _INST_TOKENS)


def _fallback(affil: str) -> str | None:
    parts = [p.strip() for p in affil.split(",") if p.strip()]
    candidates = []
    for seg in parts:
        sl = seg.lower().strip(".")
        if len(seg) < 5 or sl in _COUNTRY_WORDS or sl.isdigit() or re.match(r"^[0-9\s\-]+$", sl):
            continue
        if "@" in seg:
            continue
        score = 0.0
        if _is_dept(seg):
            score -= 2
        if _is_inst(seg):
            score += 2
        score += min(len(seg) / 40, 1.0)
        candidates.append((score, seg))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    score, best = candidates[0]
    if score <= -1:
        return None
    if best.lower().strip(".").rstrip(",") in _GENERIC_RESULTS:
        return None
    return best.rstrip(".").strip()


# ── Public API ────────────────────────────────────────────────────────────────

def resolve(affil: str) -> Resolution:
    """Resolve ONE affiliation segment to an institution."""
    if not affil or not affil.strip():
        return Resolution(None, matched_by="empty")
    al = affil.lower()
    best: Alias | None = None
    best_len = -1
    for a in load_aliases():
        m = a.regex.search(al)
        if not m:
            continue
        if best is None or a.tier < best.tier or (a.tier == best.tier and len(m.group(0)) > best_len):
            best, best_len = a, len(m.group(0))
    if best is not None:
        return Resolution(best.canonical, best.parent, best.cluster, f"alias:{best.pattern}", best.tier)
    fb = _fallback(affil)
    if fb:
        return Resolution(fb, fb, "", "fallback", 9)
    return Resolution(None, matched_by="unresolved")


_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.\w+\.?")
_ATTRIB_RE = re.compile(r"\([A-Z][a-zA-Z'\-]+(?:,\s*[A-Z][a-zA-Z'\-]+)*\)")


def affil_segments(affil: str, first_surname: str = "") -> list[str]:
    """Split one PubMed <Affiliation> element into institution segments
    (semicolon-joined multi-affiliations; journal-style '(Surname)' blocks)."""
    s = _EMAIL_RE.sub("", affil or "").strip().rstrip(".").strip()
    if not s:
        return []
    if _ATTRIB_RE.search(s):
        # journal-style blocks: "Unit (Surname, Surname), Address; Unit (Surname), Address"
        # or joined with ", and Unit (Surname), Address"
        parts = re.split(r";\s*|,\s+and\s+(?=[A-Z][^,;]*\()", s)
        if first_surname:
            mine = [p for p in parts if "(" in p and re.search(r"\b" + re.escape(first_surname) + r"\b", p)]
            if mine:
                return [p.strip() for p in mine if p.strip()]
        return [parts[0].strip()] if parts else []
    return [p.strip() for p in re.split(r";\s*", s) if p.strip()]


_CORRECTIONS: dict | None = None


def load_corrections(path: pathlib.Path | None = None) -> dict:
    """Curated per-record affiliation corrections, keyed by (pmid, author_id).

    PubMed sometimes carries an affiliation that names a city but no
    institution ("Zurich, Switzerland."), or carries none at all. Where the
    authors can state which institution a record belongs to, the correction is
    recorded here rather than applied by hand, so that every such decision has
    a PMID, a stated basis and a date, and the table ships with the paper.

    Corrections add an institution; they never remove one the record names.
    """
    global _CORRECTIONS
    if _CORRECTIONS is not None and path is None:
        return _CORRECTIONS
    import csv as _csv
    out: dict = {}
    p = path or CORRECTIONS_PATH
    if p.exists():
        with open(p, newline="") as fh:
            for row in _csv.DictReader(fh):
                pmid = (row.get("pmid") or "").strip()
                aid = (row.get("author_id") or "").strip()
                inst = (row.get("institution") or "").strip()
                if not (pmid and aid and inst):
                    continue
                out.setdefault((pmid, aid), []).append(
                    {"institution": inst,
                     "country": (row.get("country") or "").strip() or None,
                     "basis": (row.get("basis") or "").strip()})
    if path is None:
        _CORRECTIONS = out
    return out


def author_institutions(author: dict, first_surname: str = "",
                        pmid: str | None = None) -> list[Resolution]:
    """All distinct resolved institutions an author lists, in the order written.

    When a curated correction exists for this (record, author), the corrected
    institution is appended if the record did not already name it.
    """
    out: list[Resolution] = []
    seen: set[str] = set()
    for affil in author.get("affils", []) or []:
        for seg in affil_segments(affil, first_surname):
            r = resolve(seg)
            if r.canonical and r.canonical not in seen:
                seen.add(r.canonical)
                out.append(r)
    fixes = load_corrections().get((str(pmid), author.get("author_id") or ""), []) \
        if pmid is not None else []
    if fixes:
        # A curated correction states what an unparseable affiliation actually
        # is, so it supersedes whatever the fallback scorer guessed from the
        # same string -- otherwise "Zurich, Switzerland." keeps resolving to a
        # pseudo-institution called "Zurich" and, under primary counting, wins.
        out = [r for r in out if r.matched_by != "fallback"]
        seen = {r.canonical for r in out}
        head = []
        for fix in fixes:
            r = resolve(fix["institution"])
            name = r.canonical or fix["institution"]
            if name not in seen:
                seen.add(name)
                head.append(r if r.canonical else Resolution(name, matched_by="curated"))
        out = head + out
    return out


def primary_institution(author: dict, first_surname: str = "",
                        pmid: str | None = None) -> Resolution:
    """The author's primary affiliation = first resolvable segment."""
    res = author_institutions(author, first_surname, pmid)
    return res[0] if res else Resolution(None, matched_by="unresolved")


def competition_ranks(counts: list[int]) -> list[str]:
    """1224-style ranks with ties marked '=': [30, 29, 29, 28] → ['1', '=2', '=2', '4']."""
    ranks: list[str] = []
    for i, c in enumerate(counts):
        first = counts.index(c) + 1
        tie = counts.count(c) > 1
        ranks.append(f"={first}" if tie else str(first))
    return ranks


def write_alias_export(path: pathlib.Path) -> None:
    """Copy of the alias table for the SDC folder."""
    path.write_bytes(ALIAS_PATH.read_bytes())
