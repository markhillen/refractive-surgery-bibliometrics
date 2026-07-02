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
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
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


def country_name(cc: str) -> str:
    return CC.get(cc, cc)


def load_cache() -> dict:
    p = CACHE / "openalex_cache.json"
    return json.load(open(p)) if p.exists() else {}


def overlay(records: list[dict], oa: dict, verbose: bool = True) -> tuple[list[dict], dict]:
    """Mutate records in place with OpenAlex fields. Returns (records, stats)."""
    n_match = n_cite = n_country = 0
    for rec in records:
        w = oa.get(str(rec.get("pmid")))
        if not w or not w.get("found"):
            rec["oa_matched"] = False
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
        # First-author country via ROR; if the first author has no resolved
        # institution, fall back to the first co-author who does; never guess
        # from the journal's country of publication (the baseline's bug).
        cc = None
        if first and first.get("countries"):
            cc = first["countries"][0]
        else:
            for a in aus:
                if a.get("countries"):
                    cc = a["countries"][0]
                    break
        rec["country"] = country_name(cc) if cc else "Unknown"
        if cc:
            n_country += 1

        # attach per-author signals (aligned by author order)
        recauth = rec.get("authors", [])
        for idx, a in enumerate(recauth):
            if idx < len(aus):
                oaa = aus[idx]
                a["oa_id"] = oaa.get("id")
                a["orcid"] = a.get("orcid") or oaa.get("orcid")
                ccs = oaa.get("countries") or []
                if ccs:
                    a["oa_country_name"] = country_name(ccs[0])

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
