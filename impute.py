"""
impute.py — recover author affiliations that PubMed does not carry
==================================================================

Some journals deposit an affiliation for the corresponding author only, or for
nobody. In this corpus 316 records (9.8%) carry no affiliation on any author,
186 of them from a single journal. Institutional counts built from affiliation
strings therefore under-count every group that publishes in those journals, and
they under-count it unevenly, by journal rather than at random.

Where an author appears elsewhere in the same corpus within a short window and
does carry an affiliation there, that affiliation is the best available estimate
for the record that lacks one. This module attaches it, marked as imputed, so
that the choice is visible in the data and can be switched off.

The rule is applied to every author in the corpus, never to one group. An
imputed affiliation is used for institutional counting only; first-author
country attribution continues to use what PubMed actually recorded, because a
country claim rests on the record itself.
"""

from __future__ import annotations

import collections

import config


def impute_affiliations(records: list[dict], window: int = 2) -> dict:
    """Attach each author's nearest-in-time known affiliation where none is given.

    Returns a summary dict; records are modified in place. Authors given an
    imputed affiliation carry affil_source="imputed" and affil_imputed_from,
    the year the affiliation was taken from.
    """
    known: dict[str, list[tuple[int, list[str]]]] = collections.defaultdict(list)
    for rec in records:
        try:
            yr = int(rec.get("year") or 0)
        except (TypeError, ValueError):
            yr = 0
        for a in rec.get("authors") or []:
            aid = a.get("author_id")
            if aid and a.get("affils") and a.get("affil_source") != "imputed":
                known[aid].append((yr, list(a["affils"])))

    n_missing = n_imputed = 0
    recs_touched: set = set()
    for rec in records:
        try:
            yr = int(rec.get("year") or 0)
        except (TypeError, ValueError):
            yr = 0
        for a in rec.get("authors") or []:
            aid = a.get("author_id")
            if not aid or a.get("affils"):
                continue
            n_missing += 1
            near = [(abs(y - yr), y, af) for (y, af) in known.get(aid, [])
                    if abs(y - yr) <= window]
            if not near:
                continue
            near.sort(key=lambda t: (t[0], -t[1]))
            _, src_year, af = near[0]
            a["affils"] = list(af)
            a["affil_source"] = "imputed"
            a["affil_imputed_from"] = src_year
            n_imputed += 1
            recs_touched.add(rec.get("pmid"))

    summary = {"window_years": window,
               "author_slots_without_affiliation": n_missing,
               "author_slots_imputed": n_imputed,
               "records_touched": len(recs_touched)}
    print(f"[impute] {n_imputed:,} of {n_missing:,} author slots without an affiliation "
          f"filled from the same author within ±{window} years "
          f"({len(recs_touched):,} records)")
    return summary
