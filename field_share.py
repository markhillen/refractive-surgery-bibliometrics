#!/usr/bin/env python3
"""
field_share.py — the corpus as a share of PubMed and of ophthalmology, by year
==============================================================================
Absolute counts cannot show whether a field is growing relative to the
literature around it.  For every year this writes the corpus count next to
PubMed's total and an ophthalmology denominator (records indexed with the MeSH
headings Eye Diseases, Eye, Ophthalmology or Ophthalmologic Surgical
Procedures), using NCBI esearch counts cached in cache/benchmarks.json.

Output: output/field_share_by_year.csv
"""
from __future__ import annotations

import csv
import json
import pathlib
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import config  # noqa: E402

OPHTH = ('("Eye Diseases"[MeSH Terms] OR "Eye"[MeSH Terms] OR "Ophthalmology"[MeSH Terms] '
         'OR "Ophthalmologic Surgical Procedures"[MeSH Terms])')
# A text-based denominator as a check on MeSH-indexing lag for recent years
# (MeSH is assigned months after publication; the corpus itself is text-based).
OPHTH_TEXT = ('(ophthalm*[tiab] OR eye[tiab] OR eyes[tiab] OR ocular[tiab] OR cornea[tiab] '
              'OR corneal[tiab] OR retina[tiab] OR retinal[tiab] OR "visual acuity"[tiab])')
CACHE = pathlib.Path(config.CACHE_DIR) / "benchmarks.json"


def _count(q: str, cache: dict, api_key: str = "") -> int | None:
    if q in cache:
        return cache[q]
    p = {"db": "pubmed", "term": q, "retmax": 0, "retmode": "json"}
    if api_key:
        p["api_key"] = api_key
    u = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?" + urllib.parse.urlencode(p)
    for i in range(4):
        try:
            n = int(json.load(urllib.request.urlopen(u, timeout=60))["esearchresult"]["count"])
            cache[q] = n
            time.sleep(0.12 if api_key else 0.4)
            return n
        except Exception:
            time.sleep(2 * (i + 1))
    return None


def run(records: list[dict], api_key: str = "") -> None:
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    by: dict[int, int] = {}
    for r in records:
        try:
            y = int(r.get("year") or 0)
        except ValueError:
            continue
        by[y] = by.get(y, 0) + 1
    rows = []
    for y in range(config.ALL_TIME_START, config.END_YEAR + 1):
        date = f'("{y}/01/01"[PDAT] : "{y}/12/31"[PDAT])'
        tot = _count(date, cache, api_key)
        oph = _count(f"{OPHTH} AND {date}", cache, api_key)
        opt = _count(f"{OPHTH_TEXT} AND {date}", cache, api_key)
        n = by.get(y, 0)
        rows.append([y, n, tot, oph, opt,
                     round(1e5 * n / tot, 1) if tot else None,
                     round(1e3 * n / oph, 2) if oph else None,
                     round(1e3 * n / opt, 2) if opt else None])
    CACHE.write_text(json.dumps(cache))
    out = pathlib.Path(config.OUTPUT_DIR) / "field_share_by_year.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["year", "corpus_records", "pubmed_records", "pubmed_ophthalmology_records_mesh",
                    "pubmed_ophthalmology_records_text", "per_100k_pubmed",
                    "per_1000_ophthalmology_mesh", "per_1000_ophthalmology_text"])
        w.writerows(rows)
    print(f"[field_share] {out}")


if __name__ == "__main__":
    p = pathlib.Path(config.CACHE_DIR) / "records_final.json"
    run(json.load(open(p)))
