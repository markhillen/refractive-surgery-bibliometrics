#!/usr/bin/env python3
"""
sensitivity.py — Supplemental Digital Content tables and sensitivity analyses
============================================================================
Every table here is computed from the SAME final record set as the main
analysis (post-overlay), so text, tables, figures and SDC cannot disagree.
Output: output/sdc/*.csv, output/sdc/sdc_tables.xlsx, output/sdc/README.md

  country_counts        first-author / fractional / whole counting
  institution_counts    primary / whole / fractional × canonical / parent / cluster
  zurich_merge          ELZA, UZH, IROC separately and as one cluster
  per_capita            all countries with ≥ N records (N = 20 and 10)
  exclude_author_group  rankings with the author group's records removed
  china_vs_usa          2021–2025 with best/worst case for unresolved records
                        and a bootstrap CI on the difference
  citation_indicators   mean/median/IQR, year-normalised score, fixed window
  journal_share         refractive surgery output as a share of each journal's total output
  rct_benchmark         RCT share across comparable ophthalmic literatures
  author_identity_audit both Seilers, Hafezi F/NL, Zhou X … with OA IDs
  oa_vs_crossref        paired citation-source comparison
  provenance            where every number came from, with dates

Network calls (journal_share, rct_benchmark) use NCBI esearch counts, cached in
cache/benchmarks.json; --skip-benchmarks disables them.
"""
from __future__ import annotations

import collections
import csv
import datetime as _dt
import json
import math
import pathlib
import random
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import config  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
SDC = pathlib.Path(config.OUTPUT_DIR) / "sdc"   # reassigned by run_all(out_dir=…)
BENCH_CACHE = pathlib.Path(config.CACHE_DIR) / "benchmarks.json"


# ── helpers ───────────────────────────────────────────────────────────────────

def _year(rec) -> int:
    try:
        return int(rec.get("year") or 0)
    except ValueError:
        return 0


def _cc(rec):
    v = rec.get("citation_count")
    return None if v is None else int(v)


def _write(name: str, header: list[str], rows: list[list]) -> pathlib.Path:
    SDC.mkdir(parents=True, exist_ok=True)
    p = SDC / name
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    return p


def _ranks(counts: list) -> list[str]:
    from institutions import competition_ranks
    return competition_ranks(counts)


def _quantile(sorted_vals: list, p: float):
    n = len(sorted_vals)
    if not n:
        return None
    k = (n - 1) * p
    f, c = int(math.floor(k)), int(math.ceil(k))
    return sorted_vals[f] if f == c else sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def _summary(vals: list):
    known = sorted(v for v in vals if v is not None)
    n = len(known)
    if not n:
        return {"n": 0, "mean": None, "median": None, "q1": None, "q3": None, "sum": 0}
    return {"n": n, "mean": round(sum(known) / n, 1), "median": round(_quantile(known, .5), 1),
            "q1": round(_quantile(known, .25), 1), "q3": round(_quantile(known, .75), 1), "sum": sum(known)}


def _author_group() -> set[str]:
    p = pathlib.Path(config.DATA_DIR) / "author_group.csv"
    if not p.exists():
        return set()
    with open(p, encoding="utf-8") as fh:
        return {row["author_id"].strip() for row in csv.DictReader(fh) if row.get("author_id", "").strip()}


# ── 1. country counting schemes ───────────────────────────────────────────────

def country_counts(records: list[dict]) -> dict[str, list]:
    first = collections.Counter()
    whole = collections.Counter()
    frac = collections.Counter()
    n_unres_first = 0
    for rec in records:
        c = rec.get("country") or "Unknown"
        if c == "Unknown":
            n_unres_first += 1
        else:
            first[c] += 1
        cs = [a.get("country") for a in rec.get("authors", []) or [] if a.get("country") not in (None, "", "Unknown")]
        if cs:
            for c2 in set(cs):
                whole[c2] += 1
            k = len(cs)
            for c2 in cs:
                frac[c2] += 1.0 / k
    out = {}
    for name, ctr in (("first", first), ("whole", whole), ("fractional", frac)):
        rows = ctr.most_common()
        tot = sum(v for _, v in rows)
        ranks = _ranks([round(v, 2) for _, v in rows])
        out[name] = [[rk, c, (round(v, 2) if name == "fractional" else v), round(100 * v / tot, 2) if tot else ""]
                     for (c, v), rk in zip(rows, ranks)]
        _write(f"countries_{name}.csv", ["rank", "country", "publications", "pct"], out[name])
    _write("countries_scheme_comparison.csv",
           ["country", "first_author", "rank_first", "whole", "rank_whole", "fractional", "rank_fractional"],
           [[c, first[c], dict((r[1], r[0]) for r in out["first"]).get(c, ""),
             whole[c], dict((r[1], r[0]) for r in out["whole"]).get(c, ""),
             round(frac[c], 2), dict((r[1], r[0]) for r in out["fractional"]).get(c, "")]
            for c, _ in first.most_common(30)])
    out["n_unresolved_first"] = n_unres_first
    return out


# ── 2. institution counting schemes ──────────────────────────────────────────

def institution_counts(records: list[dict]) -> None:
    from analyze import institution_stats_meta
    # Both attribution scopes, so the manuscript can cite either without the
    # supplemental table silently answering a different question.
    for scope, first_only in (("firstauthor", True), ("allauthors", False)):
        for counting in ("primary", "whole", "fractional"):
            for level in ("canonical", "parent", "cluster"):
                rows, meta = institution_stats_meta(records, first_only, level, counting, 40)
                _write(f"institutions_{scope}_{counting}_{level}.csv",
                       ["rank", "institution", "publications", "pct_of_resolved",
                        "citations", "n_cited_known"],
                       [[r["rank"], r["institution"], r["count"], r["pct_of_resolved"],
                         r["citations"], r["n_cited_known"]] for r in rows])


def zurich_merge(records: list[dict]) -> list[list]:
    from analyze import institution_stats_meta
    rows = []
    for scope, first_only in (("first author", True), ("all authors", False)):
        for counting in ("primary", "whole"):
            canon, _ = institution_stats_meta(records, first_only, "canonical", counting, 200)
            clus, _ = institution_stats_meta(records, first_only, "cluster", counting, 200)
            cmap = {r["institution"]: r for r in canon}
            kmap = {r["institution"]: r for r in clus}
            for name in ("ELZA Institute", "University of Zurich", "IROC Zurich",
                         "University Hospital Zurich"):
                r = cmap.get(name)
                rows.append([scope, counting, "separate", name,
                             r["count"] if r else 0, r["rank"] if r else ""])
            r = kmap.get("zurich_cluster")
            rows.append([scope, counting, "merged", "Zurich cluster (ELZA + UZH/CABMM + IROC)",
                         r["count"] if r else 0, r["rank"] if r else ""])
            for name in ("Tehran University of Medical Sciences", "Shahid Beheshti University of Medical Sciences",
                         "Wenzhou Medical University", "LV Prasad Eye Institute", "Moorfields Eye Hospital"):
                r = kmap.get(name)
                rows.append([scope, counting, "merged-table context", name,
                             r["count"] if r else 0, r["rank"] if r else ""])
    _write("zurich_sensitivity.csv",
           ["scope", "counting", "treatment", "institution", "publications", "rank"], rows)
    return rows


# ── 3. per-capita over all countries ─────────────────────────────────────────

def per_capita(records: list[dict], min_pubs: int = 20, zurich_cluster: str = "zurich_cluster") -> list[list]:
    from analyze import load_populations
    from institutions import primary_institution
    pops = load_populations()
    counts = collections.Counter(r.get("country") for r in records if r.get("country") not in (None, "", "Unknown"))
    ch_ex = 0
    for r in records:
        if r.get("country") == "Switzerland":
            a0 = (r.get("authors") or [None])[0]
            if a0 and primary_institution(a0, a0.get("last", "")).cluster != zurich_cluster:
                ch_ex += 1
    rows = []
    for c, n in counts.items():
        pop = pops.get(c)
        if pop and n >= min_pubs:
            rows.append([c, n, pop, round(n / (pop / 1e6), 2)])
    rows.sort(key=lambda r: -r[3])
    ranks = _ranks([r[3] for r in rows])
    rows = [[rk] + r for rk, r in zip(ranks, rows)]
    pop_ch = pops.get("Switzerland")
    if pop_ch:
        rows.append(["", f"Switzerland excluding {zurich_cluster} first-author records", ch_ex, pop_ch,
                     round(ch_ex / (pop_ch / 1e6), 2)])
    missing = sorted(c for c in counts if not pops.get(c))
    _write(f"per_capita_min{min_pubs}.csv", ["rank", "country", "publications", "population_2024", "pubs_per_million"], rows)
    if missing:
        _write("per_capita_no_population.csv", ["country", "publications"], [[c, counts[c]] for c in missing])
    return rows


# ── 4. rankings without the author group ─────────────────────────────────────

def exclude_author_group(records: list[dict]) -> dict:
    from analyze import author_stats, country_stats, institution_stats
    grp = _author_group()
    if not grp:
        _write("rankings_ex_author_group.csv", ["note"], [["data/author_group.csv missing or empty"]])
        return {}
    kept = [r for r in records if not any(a.get("author_id") in grp for a in r.get("authors", []) or [])]
    n_removed = len(records) - len(kept)
    rows = [["records", "all", len(records), ""], ["records", "without author group", len(kept), ""],
            ["records", "removed", n_removed, ""]]
    for r in author_stats(kept)[:20]:
        rows.append(["author", r["author_id"], r["pub_count"], ""])
    for r in [c for c in country_stats(kept) if c["country"] != "Unknown"][:15]:
        rows.append(["country", r["country"], r["count"], r["rank"]])
    for r in institution_stats(kept,
                               first_author_only=getattr(config, "INSTITUTION_FIRST_AUTHOR_ONLY", True),
                               level=getattr(config, "INSTITUTION_LEVEL", "canonical"),
                               counting=getattr(config, "INSTITUTION_COUNTING", "primary"))[:15]:
        rows.append(["institution", r["institution"], r["count"], r["rank"]])
    _write("rankings_ex_author_group.csv", ["table", "name", "publications", "rank"], rows)
    return {"n_removed": n_removed, "group": sorted(grp)}


# ── 5. China vs USA, 2021–2025 ────────────────────────────────────────────────

def china_vs_usa(records: list[dict], y0: int = 2021, y1: int = 2025, n_boot: int = 5000, seed: int = 20260901) -> dict:
    win = [r for r in records if y0 <= _year(r) <= y1]
    cn = sum(1 for r in win if r.get("country") == "China")
    us = sum(1 for r in win if r.get("country") == "United States")
    unk = sum(1 for r in win if r.get("country") in (None, "", "Unknown"))
    rng = random.Random(seed)
    labels = [r.get("country") for r in win]
    diffs = []
    n = len(labels)
    for _ in range(n_boot):
        s = rng.choices(labels, k=n)
        diffs.append(s.count("China") - s.count("United States"))
    diffs.sort()
    lo, hi = diffs[int(0.025 * n_boot)], diffs[int(0.975 * n_boot) - 1]
    p_cn_ahead = sum(1 for d in diffs if d > 0) / n_boot
    p_tie = sum(1 for d in diffs if d == 0) / n_boot
    # exact two-sided binomial test on the resolved US+China records (H0: p = 0.5)
    import math
    n2 = cn + us
    k = min(cn, us)
    p_binom = min(1.0, 2 * sum(math.comb(n2, i) for i in range(0, k + 1)) / 2 ** n2) if n2 else None
    rows = [
        ["window", f"{y0}–{y1}"], ["records_in_window", n],
        ["China_first_author", cn], ["USA_first_author", us], ["difference_CN_minus_US", cn - us],
        ["unresolved_country_in_window", unk],
        ["best_case_China (all unresolved → China)", f"{cn + unk} vs {us}"],
        ["best_case_USA (all unresolved → USA)", f"{cn} vs {us + unk}"],
        ["bootstrap_95pct_CI_difference", f"[{lo}, {hi}] ({n_boot} resamples of records)"],
        ["bootstrap_share_of_resamples_with_China_ahead", round(p_cn_ahead, 3)],
        ["bootstrap_share_of_resamples_tied", round(p_tie, 3)],
        ["binomial_two_sided_P_resolved_US_China_records", round(p_binom, 3) if p_binom is not None else ""],
    ]
    _write("china_vs_usa_2021_2025.csv", ["metric", "value"], rows)
    return {"cn": cn, "us": us, "unk": unk, "ci": (lo, hi), "p_cn_ahead": p_cn_ahead}


def author_ranking_common_rule_off(records: list[dict], top_n: int = 40) -> None:
    """Re-run author disambiguation with the high-collision-surname rule
    disabled (no stricter thresholds, no institutional splitting) and compare
    the top-N author counts with the primary run."""
    import copy
    import disambiguate as D
    from openalex_integrate import load_cache
    # Disambiguation runs on PubMed metadata only (the OpenAlex overlay later
    # fills ORCIDs from OpenAlex, which must not feed the ORCID identity pass),
    # so the pre-overlay records are reloaded from the cache.
    pre = pathlib.Path(config.CACHE_DIR) / "records_disambig.json"
    base_recs = json.load(open(pre, encoding="utf-8")) if pre.exists() else records
    keep = {str(r.get("pmid")) for r in records}
    base_recs = [r for r in base_recs if str(r.get("pmid")) in keep]
    primary = collections.Counter(a.get("author_id") for r in records for a in r.get("authors", [])
                                  if a.get("author_id") and a["author_id"] != "__collective__")
    saved = D._COMMON_SURNAMES
    try:
        D._COMMON_SURNAMES = set()
        alt_recs, _ = D.assign_author_ids(copy.deepcopy(base_recs), load_cache() or None)
    finally:
        D._COMMON_SURNAMES = saved
    # match identities by their occurrences (pmid, author position), not by label
    prim_occ = {(str(r.get("pmid")), i): a.get("author_id") for r in records
                for i, a in enumerate(r.get("authors", [])) if a.get("author_id")}
    alt_occ: dict[str, list] = collections.defaultdict(list)
    for r in alt_recs:
        for i, a in enumerate(r.get("authors", [])):
            if a.get("author_id") and a["author_id"] != "__collective__":
                alt_occ[a["author_id"]].append((str(r.get("pmid")), i))
    rows = []
    for name, occs in sorted(alt_occ.items(), key=lambda kv: -len(kv[1]))[:top_n]:
        prim_ids = collections.Counter(prim_occ.get(o) for o in occs)
        modal, shared = prim_ids.most_common(1)[0]
        rows.append([name, len(occs), modal, primary.get(modal, ""), shared, len(prim_ids)])
    _write("authors_common_surname_rule_off.csv",
           ["author_id (rule off)", "publications (rule off)", "matching identity in primary run",
            "its publications in primary run", "occurrences shared", "primary identities covered"], rows)


# ── 6. citation indicators ────────────────────────────────────────────────────

def citation_indicators(records: list[dict], fixed=(2015, 2020), min_pubs: int = 20) -> None:
    by_year_mean = collections.defaultdict(list)
    for r in records:
        c = _cc(r)
        if c is not None and _year(r):
            by_year_mean[_year(r)].append(c)
    ymean = {y: (sum(v) / len(v)) for y, v in by_year_mean.items() if v}

    def table(key_fn, name, min_n):
        groups = collections.defaultdict(list)
        for r in records:
            k = key_fn(r)
            if k and k != "Unknown":
                groups[k].append(r)
        rows = []
        for k, recs in groups.items():
            if len(recs) < min_n:
                continue
            cites = [_cc(r) for r in recs]
            s = _summary(cites)
            ncs = [(_cc(r) / ymean[_year(r)]) for r in recs if _cc(r) is not None and ymean.get(_year(r))]
            fw = [_cc(r) for r in recs if fixed[0] <= _year(r) <= fixed[1] and _cc(r) is not None]
            fs = _summary(fw)
            ncs_sorted = sorted(ncs)
            rows.append([k, len(recs), s["n"], s["sum"], s["mean"], s["median"], s["q1"], s["q3"],
                         round(sum(ncs) / len(ncs), 2) if ncs else None,
                         round(_quantile(ncs_sorted, 0.5), 2) if ncs else None,
                         fs["n"], fs["mean"], fs["median"]])
        rows.sort(key=lambda r: -(r[4] or 0))
        _write(f"citations_{name}.csv",
               ["name", "publications", "n_with_citation_count", "citations_total", "mean", "median", "q1", "q3",
                "mean_normalised_citation_score", "median_normalised_citation_score",
                f"n_{fixed[0]}_{fixed[1]}", f"mean_{fixed[0]}_{fixed[1]}", f"median_{fixed[0]}_{fixed[1]}"], rows)

    table(lambda r: r.get("country"), "by_country", min_pubs)
    table(lambda r: r.get("journal_abbr") or r.get("journal"), "by_journal", min_pubs)
    # authors: any authorship position
    def authors_table():
        groups = collections.defaultdict(list)
        for r in records:
            for a in r.get("authors", []) or []:
                aid = a.get("author_id")
                if aid and aid != "__collective__":
                    groups[aid].append(r)
        rows = []
        for k, recs in groups.items():
            if len(recs) < min_pubs:
                continue
            cites = [_cc(r) for r in recs]
            s = _summary(cites)
            ncs = [(_cc(r) / ymean[_year(r)]) for r in recs if _cc(r) is not None and ymean.get(_year(r))]
            rows.append([k, len(recs), s["n"], s["sum"], s["mean"], s["median"], s["q1"], s["q3"],
                         round(sum(ncs) / len(ncs), 2) if ncs else None,
                         round(_quantile(sorted(ncs), 0.5), 2) if ncs else None])
        rows.sort(key=lambda r: -r[1])
        _write("citations_by_author.csv",
               ["author", "publications", "n_with_citation_count", "citations_total", "mean", "median", "q1", "q3",
                "mean_normalised_citation_score", "median_normalised_citation_score"], rows)
    authors_table()
    _write("citations_year_means.csv", ["year", "n", "mean_citations"],
           [[y, len(by_year_mean[y]), round(ymean[y], 2)] for y in sorted(ymean)])


# ── 7. journal share and RCT benchmark (network) ──────────────────────────────

def _bench_cache() -> dict:
    return json.load(open(BENCH_CACHE, encoding="utf-8")) if BENCH_CACHE.exists() else {}


def _bench_save(d: dict) -> None:
    json.dump(d, open(BENCH_CACHE, "w", encoding="utf-8"), indent=1)


def _count(query: str, cache: dict, api_key: str) -> int | None:
    if query in cache:
        return cache[query]["count"]
    from fetch import esearch_count
    try:
        n = esearch_count(query, api_key)
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] esearch failed: {e}")
        return None
    cache[query] = {"count": n, "date": _dt.date.today().isoformat()}
    return n


def journal_share(records: list[dict], api_key: str = "", top_n: int = 20) -> None:
    cache = _bench_cache()
    ctr = collections.Counter()
    nlm = {}
    for r in records:
        j = r.get("journal_abbr") or r.get("journal")
        ctr[j] += 1
        if r.get("nlm_id"):
            nlm[j] = r["nlm_id"]
    rows = []
    yrs = [_year(r) for r in records if _year(r)]
    y0, y1 = (min(yrs), max(yrs)) if yrs else (config.ALL_TIME_START, config.END_YEAR)
    for j, n in ctr.most_common(top_n):
        q = (f'"{nlm[j]}"[nlmid]' if nlm.get(j) else f'"{j}"[ta]') + f' AND ("{y0}/01/01"[PDAT] : "{y1}/12/31"[PDAT])'
        tot = _count(q, cache, api_key)
        q2 = q + ' NOT ("Letter"[pt] OR "Comment"[pt] OR "Editorial"[pt])'
        tot2 = _count(q2, cache, api_key)
        rows.append([j, n, tot, round(100 * n / tot, 2) if tot else None, tot2,
                     round(100 * n / tot2, 2) if tot2 else None, q])
    _bench_save(cache)
    _write("journal_share.csv", ["journal", "rs_records", f"journal_total_{y0}_{y1}", "rs_share_pct",
                                 "journal_total_excl_letters_comments_editorials", "rs_share_pct_excl", "pubmed_query"], rows)


RCT_TOPICS = {
    "Corneal laser refractive surgery (this corpus query)": None,
    "Keratoconus": '"Keratoconus"[MeSH Terms]',
    "Corneal cross-linking": '"Corneal Cross-Linking"[MeSH Terms] OR "corneal cross-linking"[tiab] OR "corneal crosslinking"[tiab]',
    "Corneal transplantation": '"Corneal Transplantation"[MeSH Terms]',
    "Glaucoma": '"Glaucoma"[MeSH Terms]',
    "Dry eye": '"Dry Eye Syndromes"[MeSH Terms]',
    "Cataract extraction": '"Cataract Extraction"[MeSH Terms]',
    "Age-related macular degeneration": '"Macular Degeneration"[MeSH Terms]',
}


def rct_benchmark(records: list[dict], api_key: str = "") -> None:
    cache = _bench_cache()
    yrs = [_year(r) for r in records if _year(r)]
    y0, y1 = (min(yrs), max(yrs)) if yrs else (config.ALL_TIME_START, config.END_YEAR)
    date = f'("{y0}/01/01"[PDAT] : "{y1}/12/31"[PDAT])'
    rows = []
    n_corpus = len(records)
    n_rct_corpus = sum(1 for r in records if "Randomized Controlled Trial" in (r.get("pub_types") or []))
    rows.append(["Corneal laser refractive surgery (this corpus, after filter)", n_corpus, n_rct_corpus,
                 round(100 * n_rct_corpus / n_corpus, 2), "corpus"])
    for name, topic in RCT_TOPICS.items():
        if topic is None:
            q_all = f"({config.PUBMED_QUERY_BASE}) AND {date}"
        else:
            q_all = f"({topic}) AND {date}"
        q_rct = f'({q_all}) AND "Randomized Controlled Trial"[pt]'
        tot = _count(q_all, cache, api_key)
        rct = _count(q_rct, cache, api_key)
        rows.append([name, tot, rct, round(100 * rct / tot, 2) if tot and rct is not None else None, q_all])
    _bench_save(cache)
    _write("rct_benchmark.csv", ["literature", f"records_{y0}_{y1}", "randomized_controlled_trials", "rct_pct", "pubmed_query"], rows)


# ── 8. author identity audit ──────────────────────────────────────────────────

def author_identity_audit(records: list[dict]) -> None:
    names_p = pathlib.Path(config.DATA_DIR) / "author_audit_names.csv"
    names = []
    if names_p.exists():
        with open(names_p, encoding="utf-8") as fh:
            names = [row["author_id"].strip() for row in csv.DictReader(fh) if row.get("author_id", "").strip()]
    stats = collections.defaultdict(lambda: {"n": 0, "first": 0, "last": 0, "years": set(), "affils": collections.Counter(),
                                             "oa": collections.Counter(), "orcid": set()})
    for r in records:
        auths = [a for a in r.get("authors", []) or [] if a.get("author_id") and a["author_id"] != "__collective__"]
        for i, a in enumerate(auths):
            s = stats[a["author_id"]]
            s["n"] += 1
            if i == 0:
                s["first"] += 1
            if len(auths) > 1 and i == len(auths) - 1:
                s["last"] += 1
            if _year(r):
                s["years"].add(_year(r))
            for af in (a.get("affils") or [])[:1]:
                s["affils"][af[:90]] += 1
            if a.get("oa_id"):
                s["oa"][a["oa_id"].split("/")[-1]] += 1
            if a.get("orcid"):
                s["orcid"].add(a["orcid"])
    rows = []
    targets = names or [k for k, _ in sorted(stats.items(), key=lambda kv: -kv[1]["n"])[:30]]
    for aid in targets:
        s = stats.get(aid)
        if not s:
            rows.append([aid, 0, "", "", "", "", "", "", "not in corpus"])
            continue
        yrs = sorted(s["years"])
        rows.append([aid, s["n"], s["first"], s["last"], f"{yrs[0]}–{yrs[-1]}" if yrs else "",
                     "; ".join(f"{k} (×{v})" for k, v in s["affils"].most_common(2)),
                     "; ".join(f"{k}×{v}" for k, v in s["oa"].most_common(4)), len(s["oa"]),
                     "; ".join(sorted(s["orcid"])[:2])])
    _write("author_identity_audit.csv",
           ["author_id", "publications", "first_author", "last_author", "years_active", "top_affiliations",
            "openalex_ids", "n_distinct_openalex_ids", "orcid"], rows)


# ── 9. OpenAlex vs CrossRef ───────────────────────────────────────────────────

def _spearman(a: list[float], b: list[float]) -> float | None:
    n = len(a)
    if n < 3:
        return None
    def ranks(x):
        order = sorted(range(n), key=lambda i: x[i]); r = [0.0] * n; i = 0
        while i < n:
            j = i
            while j + 1 < n and x[order[j + 1]] == x[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return round(num / den, 3) if den else None


def _crossref_cache() -> dict:
    """CrossRef cited-by counts keyed by DOI, as citations.py leaves them.

    The comparison used to need citation_count_crossref on every record, which
    only a live CrossRef fetch sets — so a --skip-citations run produced an
    empty cross-check table while the manuscript claimed one. Reading the cache
    makes the cross-check reproducible from what is already on disk.
    """
    import json as _json
    p = pathlib.Path(config.CACHE_DIR) / "citation_cache.json"
    if not p.exists():
        return {}
    try:
        raw = _json.load(open(p))
    except Exception:
        return {}
    return {str(k).lower(): v for k, v in raw.items() if isinstance(v, (int, float))}


def oa_vs_crossref(records: list[dict]) -> None:
    cache = _crossref_cache()

    def crossref_for(r):
        v = r.get("citation_count_crossref")
        if v is not None:
            return v
        doi = (r.get("doi") or "").lower()
        return cache.get(doi)

    pairs = [(int(r["citation_count"]), int(crossref_for(r))) for r in records
             if r.get("citation_source") == "openalex" and r.get("citation_count") is not None
             and crossref_for(r) is not None]
    rows = [["records_with_both_counts", len(pairs)]]
    if pairs:
        oa = [p[0] for p in pairs]; cr = [p[1] for p in pairs]
        rows += [["openalex_total", sum(oa)], ["crossref_total", sum(cr)],
                 ["ratio_openalex_to_crossref_total", round(sum(oa) / sum(cr), 3) if sum(cr) else ""],
                 ["spearman_rho", _spearman(oa, cr)],
                 ["median_ratio_per_record", round(_quantile(sorted(o / c for o, c in pairs if c), .5), 3) if any(c for _, c in pairs) else ""],
                 ["records_openalex_gt_crossref", sum(1 for o, c in pairs if o > c)],
                 ["records_differ_more_than_20pct", sum(1 for o, c in pairs if max(o, c) and abs(o - c) / max(o, c) > 0.2)]]
    _write("citation_source_comparison.csv", ["metric", "value"], rows)


# ── 10. provenance ────────────────────────────────────────────────────────────

def provenance(records: list[dict], manifest: dict | None) -> None:
    from openalex_integrate import load_cache
    oa = load_cache()
    cs = collections.Counter(r.get("citation_source") or "none" for r in records)
    cos = collections.Counter(r.get("country_source") or "none" for r in records)
    fetched = collections.Counter((oa.get(str(r["pmid"])) or {}).get("fetched", "undated")[:7]
                                  for r in records if str(r.get("pmid")) in oa)
    rows = [["n_corpus", len(records)],
            ["corpus_mode", (manifest or {}).get("mode", "")],
            ["esearch_date", (manifest or {}).get("esearch_date", "")],
            ["esearch_count", (manifest or {}).get("esearch_count", "")],
            ["n_raw_retrieved", (manifest or {}).get("n_raw", "")],
            ["n_out_of_window", (manifest or {}).get("n_out_of_window", "")],
            ["n_kept_after_filter", (manifest or {}).get("n_kept", "")],
            ["year_rule", (manifest or {}).get("year_rule", "")],
            ["n_openalex_matched", sum(1 for r in records if r.get("oa_matched"))],
            ["n_openalex_unmatched", sum(1 for r in records if not r.get("oa_matched"))],
            ["n_no_doi", sum(1 for r in records if not r.get("doi"))],
            ["n_citation_count_known", sum(1 for r in records if r.get("citation_count") is not None)],
            ["n_citation_count_null", sum(1 for r in records if r.get("citation_count") is None)]]
    rows += [[f"citation_source={k}", v] for k, v in cs.most_common()]
    rows += [[f"country_source={k}", v] for k, v in cos.most_common()]
    rows += [[f"openalex_fetched_month={k}", v] for k, v in sorted(fetched.items())]
    _write("data_provenance.csv", ["metric", "value"], rows)


# ── 11. copies of the audit artefacts ─────────────────────────────────────────

def copy_artefacts() -> None:
    out = pathlib.Path(config.OUTPUT_DIR)
    data = pathlib.Path(config.DATA_DIR)
    for src in (out / "exclusion_log.csv", out / "exclusion_summary.csv", out / "screening_queue.csv",
                out / "pmid_delta.csv", out / "record_attribution.csv",
                data / "manual_screening.csv", data / "keyword_synonyms.csv", data / "institution_aliases.csv",
                data / "populations_worldbank_2024.csv", HERE / "validation" / "known_true_positives.csv",
                HERE / "validation" / "precision_sample.csv"):
        if src.exists():
            shutil.copy(src, SDC / src.name)
    try:
        import geo
        geo.write_country_names_csv(SDC / "country_names.csv")
    except Exception:  # noqa: BLE001
        pass


def keyword_coverage(records: list[dict]) -> None:
    import keywords
    rows = keywords.coverage_by_year(records)
    _write("keyword_coverage_by_year.csv", ["year", "n_records", "n_with_author_keywords", "pct"],
           [[r["year"], r["n_records"], r["n_with_author_keywords"], r["pct"]] for r in rows])
    ov = keywords.coverage_overall(records)
    _write("keyword_coverage_overall.csv", ["n_records", "n_with_author_keywords", "pct"],
           [[ov["n_records"], ov["n_with_author_keywords"], ov["pct"]]])


def write_xlsx() -> None:
    try:
        import openpyxl
    except ImportError:
        return
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for p in sorted(SDC.glob("*.csv")):
        if p.stat().st_size > 2_000_000:
            continue
        ws = wb.create_sheet(p.stem[:31])
        with open(p, encoding="utf-8") as fh:
            for row in csv.reader(fh):
                ws.append(row)
    wb.save(SDC / "sdc_tables.xlsx")


def write_readme(manifest: dict | None) -> None:
    lines = ["# Supplemental Digital Content tables — generated by sensitivity.py",
             f"Generated {_dt.datetime.now().isoformat(timespec='minutes')} from the same record set as the main analysis.", "",
             "| file | content |", "|---|---|"]
    for p in sorted(SDC.glob("*.csv")):
        lines.append(f"| {p.name} | |")
    (SDC / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── entry point ───────────────────────────────────────────────────────────────

def run_all(records: list[dict], manifest: dict | None = None, api_key: str = "",
            skip_benchmarks: bool = False, out_dir: pathlib.Path | None = None) -> None:
    global SDC
    SDC = pathlib.Path(out_dir) if out_dir else pathlib.Path(config.OUTPUT_DIR) / "sdc"
    SDC.mkdir(parents=True, exist_ok=True)
    print("[sdc] country counting schemes …");   country_counts(records)
    print("[sdc] institution counting schemes …"); institution_counts(records)
    print("[sdc] Zurich merge …");                zurich_merge(records)
    print("[sdc] per-capita (all countries) …");  per_capita(records, 20); per_capita(records, 10)
    print("[sdc] rankings without author group …"); exclude_author_group(records)
    print("[sdc] China vs USA 2021–2025 …");      r = china_vs_usa(records)
    print(f"      China {r['cn']} vs USA {r['us']}, unresolved {r['unk']}, bootstrap CI {r['ci']}")
    print("[sdc] citation indicators …");         citation_indicators(records)
    print("[sdc] author identity audit …");       author_identity_audit(records)
    print("[sdc] author ranking, common-surname rule off …"); author_ranking_common_rule_off(records)
    print("[sdc] OpenAlex vs CrossRef …");        oa_vs_crossref(records)
    print("[sdc] keyword coverage …");            keyword_coverage(records)
    print("[sdc] provenance …");                  provenance(records, manifest)
    if not skip_benchmarks:
        print("[sdc] journal share (PubMed counts) …"); journal_share(records, api_key)
        print("[sdc] RCT benchmark (PubMed counts) …"); rct_benchmark(records, api_key)
    copy_artefacts()
    write_xlsx()
    write_readme(manifest)
    print(f"[sdc] written to {SDC}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", default=str(pathlib.Path(config.CACHE_DIR) / "records_disambig.json"))
    ap.add_argument("--api-key", default=config.NCBI_API_KEY)
    ap.add_argument("--skip-benchmarks", action="store_true")
    a = ap.parse_args()
    recs = json.load(open(a.records, encoding="utf-8"))
    from fetch import read_manifest
    run_all(recs, read_manifest(), a.api_key, a.skip_benchmarks)
