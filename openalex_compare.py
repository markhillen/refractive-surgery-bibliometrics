#!/usr/bin/env python3
"""
openalex_compare.py — side-by-side: current pipeline vs OpenAlex
================================================================
Computes top authors / countries / journals / citations two ways on the
EXACT SAME matched record set:

  • "Current"  — Opus's own disambiguation (disambiguate.assign_author_ids),
                 geo.extract_country (first-author country), raw journal field,
                 CrossRef citation counts (from records_cited.json).
  • "OpenAlex" — OpenAlex author IDs, ROR country codes, source journal,
                 OpenAlex cited_by counts (from cache/openalex_cache.json).

Both sides are restricted to papers OpenAlex actually indexes, so any ranking
difference reflects method, not corpus. Writes output/openalex_comparison.md.

Run:  python3 openalex_enrich.py   (first, to build the cache)
      python3 openalex_compare.py
"""
import collections
import json
import pathlib

import geo
from disambiguate import assign_author_ids

HERE = pathlib.Path(__file__).resolve().parent
CACHE = HERE / "cache"
OUT = HERE / "output" / "openalex_comparison.md"

WINDOWS = {"all_time (2001–2025)": (2001, 2025),
           "last_5yr (2021–2025)": (2021, 2025)}

# ISO-2 → names aligned with geo.py's output for the common entries.
CC = {"US": "United States", "GB": "United Kingdom", "CN": "China", "IT": "Italy",
      "TR": "Turkey", "DE": "Germany", "CH": "Switzerland", "IN": "India",
      "JP": "Japan", "KR": "South Korea", "FR": "France", "ES": "Spain",
      "NL": "Netherlands", "AU": "Australia", "CA": "Canada", "BR": "Brazil",
      "IR": "Iran", "EG": "Egypt", "GR": "Greece", "AT": "Austria", "BE": "Belgium",
      "SE": "Sweden", "PL": "Poland", "RU": "Russia", "MX": "Mexico",
      "SG": "Singapore", "IL": "Israel", "SA": "Saudi Arabia", "TW": "Taiwan",
      "TH": "Thailand", "PT": "Portugal", "DK": "Denmark", "NO": "Norway",
      "FI": "Finland", "CZ": "Czechia", "HU": "Hungary", "RO": "Romania",
      "PK": "Pakistan", "CO": "Colombia", "AR": "Argentina", "CL": "Chile"}


def _year(r):
    try:
        return int(str(r.get("year"))[:4])
    except Exception:
        return None


def _load():
    recs = json.load(open(CACHE / "records_disambig.json"))
    cited = json.load(open(CACHE / "records_cited.json"))
    cmap = {str(r["pmid"]): (r.get("citation_count") or 0)
            for r in cited if r.get("pmid")}
    oa = json.load(open(CACHE / "openalex_cache.json"))
    return recs, cmap, oa


def _norm_journal(s):
    return (s or "").lower().split("(")[0].strip().rstrip(".")


def _fmt_table(title, cur, oa, cols):
    """cur / oa are lists of (label, count). Aligned by rank."""
    lines = [f"\n### {title}\n",
             "| # | Current method | n | | OpenAlex | n |",
             "|--:|---|--:|---|---|--:|"]
    for i in range(max(len(cur), len(oa))):
        c = cur[i] if i < len(cur) else ("", "")
        o = oa[i] if i < len(oa) else ("", "")
        lines.append(f"| {i+1} | {c[0]} | {c[1]} | | {o[0]} | {o[1]} |")
    return "\n".join(lines)


def analyse(recs, cmap, oa, y0, y1):
    # matched subset in window
    sub = [r for r in recs
           if _year(r) and y0 <= _year(r) <= y1
           and str(r.get("pmid")) in oa and oa[str(r["pmid"])].get("found")]
    total_in_window = sum(1 for r in recs if _year(r) and y0 <= _year(r) <= y1)

    # ---- CURRENT side ----
    cur_recs, _ = assign_author_ids([dict(r) for r in sub])
    cur_auth = collections.Counter()
    cur_auth_first = collections.Counter()
    cur_country = collections.Counter()
    cur_journal = collections.Counter()
    cur_cites = 0
    for r in cur_recs:
        cur_cites += cmap.get(str(r.get("pmid")), 0)
        cur_journal[_norm_journal(r.get("journal"))] += 1
        auths = [a for a in r.get("authors", []) if a.get("author_id")
                 and a["author_id"] != "__collective__"]
        for j, a in enumerate(auths):
            cur_auth[a["author_id"]] += 1
            if j == 0:
                cur_auth_first[a["author_id"]] += 1
        if auths:
            c = geo.extract_country(auths[0].get("affils") or [])
            if c:
                cur_country[c] += 1

    # ---- OPENALEX side ----
    oa_auth = collections.Counter()
    oa_auth_name = {}
    oa_country = collections.Counter()
    oa_journal = collections.Counter()
    oa_cites = 0
    oa_no_id = 0
    for r in sub:
        w = oa[str(r["pmid"])]
        oa_cites += w.get("cited_by") or 0
        oa_journal[_norm_journal(w.get("journal"))] += 1
        aus = w.get("authors") or []
        for a in aus:
            key = a.get("id") or ("name:" + (a.get("name") or "?"))
            if not a.get("id"):
                oa_no_id += 1
            oa_auth[key] += 1
            oa_auth_name[key] = a.get("name") or "?"
        # first-author country
        first = next((a for a in aus if a.get("pos") == "first"), aus[0] if aus else None)
        if first:
            ccs = first.get("countries") or []
            if ccs:
                oa_country[CC.get(ccs[0], ccs[0])] += 1

    def top(counter, n=12, namemap=None):
        return [((namemap[k] if namemap else k), v)
                for k, v in counter.most_common(n)]

    return {
        "n_matched": len(sub), "n_window": total_in_window,
        "cur_cites": cur_cites, "oa_cites": oa_cites,
        "cur_auth": top(cur_auth), "oa_auth": top(oa_auth, namemap=oa_auth_name),
        "cur_country": top(cur_country, 10), "oa_country": top(oa_country, 10),
        "cur_journal": top(cur_journal, 10), "oa_journal": top(oa_journal, 10),
        "oa_no_id": oa_no_id, "oa_n_authors": len(oa_auth), "cur_n_authors": len(cur_auth),
    }


def main():
    recs, cmap, oa = _load()
    found = sum(1 for v in oa.values() if v.get("found"))
    md = ["# CXL bibliometrics — Current pipeline vs OpenAlex",
          "",
          f"OpenAlex cache: {len(oa)} records looked up, **{found} matched** "
          f"({100*found/max(len(oa),1):.1f}%). Both columns below are computed on "
          f"the *same* matched papers, so differences reflect method, not corpus size.",
          ""]
    for label, (y0, y1) in WINDOWS.items():
        a = analyse(recs, cmap, oa, y0, y1)
        md += [f"\n## {label}",
               "",
               f"- Papers in window: **{a['n_window']}**; matched in OpenAlex: "
               f"**{a['n_matched']}** ({100*a['n_matched']/max(a['n_window'],1):.1f}%).",
               f"- Total citations — Current (CrossRef): **{a['cur_cites']:,}** · "
               f"OpenAlex: **{a['oa_cites']:,}** "
               f"(ratio {a['oa_cites']/max(a['cur_cites'],1):.2f}×).",
               f"- Distinct authors — Current: **{a['cur_n_authors']:,}** · "
               f"OpenAlex: **{a['oa_n_authors']:,}**. "
               f"OpenAlex authorships lacking an author ID: {a['oa_no_id']}.",
               _fmt_table("Top countries (first author)", a["cur_country"], a["oa_country"], 2),
               _fmt_table("Top journals", a["cur_journal"], a["oa_journal"], 2),
               _fmt_table("Top authors", a["cur_auth"], a["oa_auth"], 2)]
    OUT.write_text("\n".join(md))
    print("\n".join(md))
    print(f"\n[written] {OUT}")


if __name__ == "__main__":
    main()
