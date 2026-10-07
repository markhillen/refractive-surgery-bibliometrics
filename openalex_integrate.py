#!/usr/bin/env python3
"""
openalex_integrate.py — hybrid OpenAlex overlay
===============================================
Applies OpenAlex data on top of the existing pipeline records:

  • citation_count  <- OpenAlex cited_by   (CrossRef value kept as
                                             citation_count_crossref)
  • country         <- OpenAlex first-author country via ROR
                       (fixes the ~14% "Unknown" + USA-inflation problem)
  • per-author orcid / oa_id / oa_country_name attached
  • rec["oa_matched"] flag; rec["institutions_oa"] (ROR names, informational)

PubMed still defines the corpus and the journal field; the curated author
safelists in disambiguate.py remain authoritative for author identity. This
overlay only supplies the fields OpenAlex demonstrably does better, and emits
an author-disagreement report for human sign-off.

Standalone use (writes reports, does not touch the pipeline outputs):
    python3 openalex_integrate.py
Pipeline use: main.py --use-openalex  (calls overlay() after citations)
"""
import collections
import json
import re
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import config  # noqa: E402

CACHE = HERE / "cache"
OUT = HERE / "output"

# ISO-3166 alpha-2 → display names aligned with geo.py output.
CC = {"US": "United States", "GB": "United Kingdom", "CN": "China", "IT": "Italy",
      "TR": "Turkey", "DE": "Germany", "CH": "Switzerland", "IN": "India",
      "JP": "Japan", "KR": "South Korea", "FR": "France", "ES": "Spain",
      "NL": "Netherlands", "AU": "Australia", "CA": "Canada", "BR": "Brazil",
      "IR": "Iran", "EG": "Egypt", "GR": "Greece", "AT": "Austria", "BE": "Belgium",
      "SE": "Sweden", "PL": "Poland", "RU": "Russia", "MX": "Mexico",
      "SG": "Singapore", "IL": "Israel", "SA": "Saudi Arabia", "TW": "Taiwan",
      "TH": "Thailand", "PT": "Portugal", "DK": "Denmark", "NO": "Norway",
      "FI": "Finland", "CZ": "Czechia", "HU": "Hungary", "RO": "Romania",
      "PK": "Pakistan", "CO": "Colombia", "AR": "Argentina", "CL": "Chile",
      "NZ": "New Zealand", "IE": "Ireland", "HK": "Hong Kong", "MY": "Malaysia",
      "AE": "United Arab Emirates", "ZA": "South Africa", "LB": "Lebanon",
      "JO": "Jordan", "SK": "Slovakia", "SI": "Slovenia", "HR": "Croatia",
      "RS": "Serbia", "BG": "Bulgaria", "LT": "Lithuania", "UA": "Ukraine"}


def _pick_country(first_author: dict, rec: dict) -> str:
    """Choose the first author's country when OpenAlex resolves more than one.

    OpenAlex returns an author's institutions (and countries) in its own order,
    which is not the order the author listed them in and is not reliably the
    primary affiliation.  Taking countries[0] therefore mis-assigns a country
    on roughly a quarter of the records whose first author lists more than one
    affiliation — about 6% of this corpus — and does so invisibly.  Examples
    from this dataset: a Queen Victoria Hospital (UK) paper assigned to
    Australia, a Columbia University (New York) paper assigned to Egypt, and a
    Geneva University Hospitals paper assigned to the United States because
    OpenAlex matched "Geneva" to Geneva College, Pennsylvania.

    Fix: prefer the country whose resolved institution name actually appears in
    the PubMed affiliation string of the first author, which reflects what the
    author wrote.  Fall back to the previous behaviour when nothing matches.
    """
    countries = first_author.get("countries") or []
    if len(set(countries)) <= 1:
        return countries[0] if countries else None

    authors = rec.get("authors") or []
    affil_text = " ".join(authors[0].get("affils", [])).lower() if authors else ""
    if affil_text:
        # Among the institutions OpenAlex resolved, keep those whose name
        # actually appears in what the author wrote, and prefer the one the
        # author listed FIRST — the primary affiliation by convention.
        # OpenAlex's own array order is arbitrary and must not decide this.
        best_pos, best_cc = None, None
        for inst in first_author.get("insts") or []:
            name = (inst.get("name") or "").lower()
            country = inst.get("cc") or inst.get("country")
            if not name or not country:
                continue
            tokens = [t for t in re.findall(r"[a-z]{4,}", name)
                      if t not in _GENERIC_INST_WORDS]
            if not tokens:
                continue
            positions = [affil_text.find(t) for t in tokens]
            if any(pos < 0 for pos in positions):
                continue
            pos = min(positions)
            if best_pos is None or pos < best_pos:
                best_pos, best_cc = pos, country
        if best_cc:
            return best_cc
    # Nothing the author wrote identifies the institution (often because PubMed
    # carries no affiliation for this author).  OpenAlex's `countries` array is
    # alphabetical, so countries[0] favours whichever country sorts first; use
    # the country most of the author's resolved institutions share instead,
    # breaking ties by OpenAlex's institution order.
    insts = [i.get("cc") or i.get("country") for i in (first_author.get("insts") or [])]
    insts = [c for c in insts if c]
    if insts:
        counts = {c: insts.count(c) for c in insts}
        top = max(counts.values())
        return next(c for c in insts if counts[c] == top)
    return countries[0]


_GENERIC_INST_WORDS = {
    "university", "hospital", "hospitals", "institute", "institution",
    "college", "school", "medical", "medicine", "center", "centre",
    "department", "faculty", "clinic", "national", "research", "health",
}

def country_name(cc: str) -> str:
    """ISO-2 → display name, via the single table in geo.py (CC kept for reference)."""
    from geo import display_name
    return display_name(cc)


def load_cache() -> dict:
    p = CACHE / "openalex_cache.json"
    return json.load(open(p)) if p.exists() else {}


_GREATER_CHINA = {"China", "Hong Kong", "Taiwan", "Macau", "Macao"}


def _text_overrides(author: dict, oa_country: str) -> bool:
    """True when the author's PubMed affiliation names a country explicitly
    (geo.py source 'affil_country_name', or the same from an affiliation PubMed
    printed once for all authors of an older record) and it differs from
    OpenAlex's.
    Greater China is left to ROR, whose SAR/territory coding is more exact
    than affiliation strings that name several of these at once."""
    txt = author.get("country")
    if txt in (None, "", "Unknown"):
        return False
    if author.get("country_source") not in ("affil_country_name", "affil_country_name_propagated"):
        return False
    if txt == oa_country:
        return False
    if txt in _GREATER_CHINA and oa_country in _GREATER_CHINA:
        return False
    return True


def overlay(records: list[dict], oa: dict, verbose: bool = True) -> tuple[list[dict], dict]:
    """Mutate records in place with OpenAlex fields. Returns (records, stats)."""
    n_match = n_cite = n_country = 0
    for rec in records:
        w = oa.get(str(rec.get("pmid")))
        if not w or not w.get("found"):
            rec["oa_matched"] = False
            # Keep any CrossRef count in its own field; the primary citation
            # count is OpenAlex-only unless config.CITATION_FILL_CROSSREF is set,
            # so mixed-source means are never produced silently.
            if "citation_count_crossref" not in rec:
                rec["citation_count_crossref"] = rec.get("citation_count")
            if getattr(config, "CITATION_FILL_CROSSREF", False) and rec.get("citation_count") is not None:
                rec["citation_source"] = "crossref"
            else:
                rec["citation_count"] = None
                rec["citation_source"] = None
            rec.setdefault("country_source", rec.get("country_source", "affil_regex"))
            continue
        rec["oa_matched"] = True
        n_match += 1

        # citations — preserve CrossRef, prefer OpenAlex
        if "citation_count_crossref" not in rec:
            rec["citation_count_crossref"] = rec.get("citation_count")
        if w.get("cited_by") is not None:
            rec["citation_count"] = w["cited_by"]
            n_cite += 1

        aus = w.get("authors") or []
        first = next((a for a in aus if a.get("pos") == "first"),
                     aus[0] if aus else None)
        # First-author country via ROR.  If OpenAlex resolved nothing for the
        # first author, fall back to the first author's OWN PubMed affiliation
        # string (geo.py); never to a co-author, never to the journal's country.
        cc = None
        if first and first.get("countries"):
            cc = _pick_country(first, rec)
        recauth0 = (rec.get("authors") or [None])[0]
        if cc:
            rec["country"] = country_name(cc)
            rec["country_source"] = "openalex_ror" if w.get("source") in (None, "openalex") \
                else str(w.get("source"))
            n_country += 1
            # An explicit country name in the first author's own affiliation
            # outranks a conflicting ROR country: ROR matching occasionally lands
            # on a same-named institution abroad (e.g. "University of Health
            # Sciences" in Istanbul matched to one in Antigua).
            if recauth0 and _text_overrides(recauth0, rec["country"]):
                rec["country"] = recauth0["country"]
                rec["country_source"] = "affil_country_name_over_openalex"
        else:
            if recauth0 and recauth0.get("country") not in (None, "", "Unknown"):
                rec["country"] = recauth0["country"]
                rec["country_source"] = recauth0.get("country_source", "affil_regex")
            else:
                rec["country"] = "Unknown"
                rec["country_source"] = (recauth0 or {}).get("country_source", "unresolved")
        if "citation_source" not in rec:
            rec["citation_source"] = None
        if w.get("cited_by") is not None:
            rec["citation_source"] = "openalex" if w.get("source") in (None, "openalex") \
                else str(w.get("source"))

        # attach per-author signals (aligned by author order)
        recauth = rec.get("authors", [])
        for idx, a in enumerate(recauth):
            if idx < len(aus):
                oaa = aus[idx]
                a["oa_id"] = oaa.get("id")
                a["orcid"] = a.get("orcid") or oaa.get("orcid")
                ccs = oaa.get("countries") or []
                a["oa_countries"] = [country_name(c) for c in ccs]
                if ccs:
                    a["oa_country_name"] = country_name(_pick_country(oaa, {"authors": [a]}) or ccs[0])
                    if not _text_overrides(a, a["oa_country_name"]):
                        a["country"] = a["oa_country_name"]
                        a["country_source"] = "openalex_ror"
        rec["countries_all"] = sorted({a.get("country") for a in recauth
                                       if a.get("country") not in (None, "", "Unknown")})

        insts = []
        for a in aus:
            for i in a.get("insts") or []:
                if i.get("name"):
                    insts.append(i["name"])
        rec["institutions_oa"] = insts

    stats = {"matched": n_match, "total": len(records),
             "citations_set": n_cite, "countries_set": n_country}
    if verbose:
        print(f"[openalex] overlay applied: {n_match}/{len(records)} matched; "
              f"citations set on {n_cite}; country set on {n_country}")
    return records, stats


def author_disagreements(records: list[dict], top_n: int = 30) -> str:
    """Compare heuristic author_id clusters against OpenAlex author IDs
    (aligned by author order) and report where they disagree, for the most
    prolific authors. Returns markdown."""
    # heuristic id -> pub count, and heuristic id -> multiset of oa ids
    pub = collections.Counter()
    hid_to_oa = collections.defaultdict(collections.Counter)
    oa_to_hid = collections.defaultdict(collections.Counter)
    oa_name = {}
    for rec in records:
        for a in rec.get("authors", []):
            hid = a.get("author_id")
            if not hid or hid == "__collective__":
                continue
            pub[hid] += 1
            oaid = a.get("oa_id")
            if oaid:
                hid_to_oa[hid][oaid] += 1
                oa_to_hid[oaid][hid] += 1
                oa_name[oaid] = a.get("fore", "") and f"{a.get('fore','')} {a.get('last','')}".strip() or hid

    lines = ["# OpenAlex author disagreements (for human sign-off)\n",
             "For the most prolific authors, how the curated heuristic identity "
             "maps to OpenAlex author IDs. A clean 1:1 means both agree. "
             "1 heuristic → many OpenAlex = OpenAlex splits this person "
             "(or heuristic over-merged); many heuristic → 1 OpenAlex = "
             "heuristic split someone OpenAlex treats as one.\n",
             "| Heuristic author | pubs | OpenAlex IDs (count) | verdict |",
             "|---|--:|---|---|"]
    for hid, n in pub.most_common(top_n):
        oamap = hid_to_oa.get(hid, {})
        distinct = len(oamap)
        parts = ", ".join(f"{oid.split('/')[-1]}×{c}" for oid, c in oamap.most_common())
        if distinct == 0:
            verdict = "no OpenAlex ID"
        elif distinct == 1:
            oid = next(iter(oamap))
            # does that OA id also appear under other heuristic ids?
            others = [h for h in oa_to_hid.get(oid, {}) if h != hid]
            verdict = "agree" if not others else f"heuristic split (also: {', '.join(others[:2])})"
        else:
            verdict = f"OpenAlex splits into {distinct}"
        lines.append(f"| {hid} | {n} | {parts or '—'} | {verdict} |")
    return "\n".join(lines)


def main():
    recs_path = CACHE / "records_disambig.json"
    records = json.load(open(recs_path))
    oa = load_cache()
    if not oa:
        print("[openalex] no cache — run openalex_enrich.py first."); return
    # records_disambig may lack citation_count; pull CrossRef from records_cited
    cited = {str(r["pmid"]): r.get("citation_count")
             for r in json.load(open(CACHE / "records_cited.json")) if r.get("pmid")}
    for r in records:
        if r.get("citation_count") is None:
            r["citation_count"] = cited.get(str(r.get("pmid")))
    overlay(records, oa)
    rep = author_disagreements(records)
    (OUT / "openalex_author_disagreements.md").write_text(rep)
    print(f"[written] {OUT / 'openalex_author_disagreements.md'}")


if __name__ == "__main__":
    main()
