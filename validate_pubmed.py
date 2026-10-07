#!/usr/bin/env python3
"""
validate_pubmed.py — external check of retrieval, parsing and counting
======================================================================
Re-counts the leading journals and author names directly in PubMed with
esearch (the query AND the journal's NLM ID, or AND the author's name) and
compares the counts with what the pipeline parsed from the downloaded XML,
before relevance screening.  An independent check that the pipeline counts
what PubMed holds; it does not test the search strategy itself.

Output: output/validation_journals.csv, output/validation_authors.csv
"""
from __future__ import annotations

import collections, csv, json, pathlib, sys, time, unicodedata, urllib.parse, urllib.request
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import config  # noqa: E402


def _count(q, api_key=""):
    p = {"db": "pubmed", "term": q, "retmax": 0, "retmode": "json"}
    if api_key:
        p["api_key"] = api_key
    u = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?" + urllib.parse.urlencode(p)
    for i in range(4):
        try:
            n = int(json.load(urllib.request.urlopen(u, timeout=60))["esearchresult"]["count"])
            time.sleep(0.12 if api_key else 0.4)
            return n
        except Exception:
            time.sleep(2 * (i + 1))
    return None


def _fold(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _spearman(a, b):
    def rank(v):
        o = sorted(range(len(v)), key=lambda i: v[i]); r = [0.0] * len(v); i = 0
        while i < len(o):
            j = i
            while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]:
                j += 1
            for k in range(i, j + 1):
                r[o[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    ra, rb = rank(a), rank(b); n = len(a); ma = sum(ra) / n; mb = sum(rb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return round(num / den, 3) if den else None


def run(top_journals=30, top_authors=40, api_key=""):
    raw = json.load(open(pathlib.Path(config.CACHE_DIR) / "records_raw.json"))
    base = f'({config.PUBMED_QUERY_BASE}) AND ("{config.ALL_TIME_START}/01/01"[PDAT] : "{config.END_YEAR}/12/31"[PDAT])'
    out = pathlib.Path(config.OUTPUT_DIR)
    jc = collections.Counter(r.get("nlm_id") for r in raw if r.get("nlm_id"))
    names = {r.get("nlm_id"): r.get("journal_abbr") for r in raw}
    rows = []
    for nlm, n in jc.most_common(top_journals):
        pm = _count(f'{base} AND "{nlm}"[nlmid]', api_key)
        rows.append([names.get(nlm), nlm, n, pm, (pm - n) if pm is not None else None])
    with open(out / "validation_journals.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["journal", "nlm_id", "pipeline_records_before_screening", "pubmed_count", "difference"]); w.writerows(rows)
    rj = _spearman([r[2] for r in rows], [r[3] for r in rows])
    ac = collections.Counter()
    for r in raw:
        seen = set()
        for a in r.get("authors") or []:
            if a.get("collective") or not a.get("last"):
                continue
            k = f'{_fold(a["last"])} {(a.get("initials") or "")[:1]}'
            if k not in seen:
                seen.add(k); ac[k] += 1
    arows = []
    for k, n in ac.most_common(top_authors):
        pm = _count(f'{base} AND {k}[au]', api_key)
        arows.append([k, n, pm, (pm - n) if pm is not None else None])
    with open(out / "validation_authors.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["surname_first_initial", "pipeline_records_before_screening", "pubmed_count", "difference"]); w.writerows(arows)
    ra = _spearman([r[1] for r in arows], [r[2] for r in arows])
    summ = {"journals_compared": len(rows), "journals_identical": sum(1 for r in rows if r[4] == 0),
            "journals_spearman": rj, "authors_compared": len(arows),
            "authors_within_2": sum(1 for r in arows if r[3] is not None and abs(r[3]) <= 2), "authors_spearman": ra}
    json.dump(summ, open(out / "validation_summary.json", "w"), indent=1)
    print("[validate]", summ)


if __name__ == "__main__":
    run()
