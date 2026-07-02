#!/usr/bin/env python3
"""
openalex_enrich.py — OPT-IN OpenAlex enrichment (evaluation prototype)
======================================================================
Looks up each cached record in OpenAlex by PMID and stores a compact
per-work record: OpenAlex author IDs (their ML-disambiguated identities),
institutions with ROR IDs and country codes, the journal source, and the
OpenAlex citation count.

This does NOT touch the existing pipeline or its outputs. It only writes
cache/openalex_cache.json. Run it, then run openalex_compare.py to see a
side-by-side comparison against the current numbers.

Standard library only — no extra dependencies.

Usage:
    python3 openalex_enrich.py                 # enrich all cached records
    python3 openalex_enrich.py --limit 200     # quick partial test
    python3 openalex_enrich.py --records cache/records_disambig.json
"""
import argparse
import json
import pathlib
import sys
import time
import urllib.request
import urllib.error

HERE = pathlib.Path(__file__).resolve().parent
CACHE = HERE / "cache"
OA_CACHE = CACHE / "openalex_cache.json"
API = "https://api.openalex.org/works/pmid:"
# A descriptive User-Agent is courteous and helps OpenAlex contact us if needed.
UA = "cxl-biblio-eval/1.0 (mailto:markhillen@gmail.com)"
SLEEP = 0.12          # ~8 req/s, well under the 10/s ceiling
SAVE_EVERY = 50       # checkpoint the cache periodically


def _load_records(path: pathlib.Path) -> list[dict]:
    d = json.load(open(path))
    recs = d if isinstance(d, list) else (d.get("records") or list(d.values()))
    return [r for r in recs if isinstance(r, dict) and r.get("pmid")]


def _load_cache() -> dict:
    if OA_CACHE.exists():
        try:
            return json.load(open(OA_CACHE))
        except Exception:
            pass
    return {}


def _save_cache(cache: dict) -> None:
    tmp = OA_CACHE.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(cache, f)
    tmp.replace(OA_CACHE)   # atomic


def _compact(work: dict) -> dict:
    """Extract only the fields we need, to keep the cache small."""
    auths = []
    for a in work.get("authorships") or []:
        au = a.get("author") or {}
        insts = a.get("institutions") or []
        auths.append({
            "id": au.get("id"),
            "name": au.get("display_name"),
            "orcid": au.get("orcid"),
            "pos": a.get("author_position"),          # first / middle / last
            "countries": a.get("countries") or [],
            "insts": [{"ror": i.get("ror"),
                       "name": i.get("display_name"),
                       "cc": i.get("country_code")} for i in insts],
        })
    src = (work.get("primary_location") or {}).get("source") or {}
    return {
        "found": True,
        "oa_id": work.get("id"),
        "year": work.get("publication_year"),
        "cited_by": work.get("cited_by_count"),
        "journal": src.get("display_name"),
        "issn_l": src.get("issn_l"),
        "authors": auths,
    }


def _fetch(pmid: str) -> dict | None:
    req = urllib.request.Request(API + str(pmid), headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"__notfound__": True}
        raise
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", default=str(CACHE / "records_disambig.json"))
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    records = _load_records(pathlib.Path(args.records))
    if args.limit:
        records = records[: args.limit]
    cache = _load_cache()
    print(f"[openalex] {len(records)} records; {len(cache)} already cached")

    todo = [r for r in records if str(r["pmid"]) not in cache]
    print(f"[openalex] {len(todo)} to fetch (~{len(todo)*SLEEP/60:.1f} min)")

    done = 0
    for r in todo:
        pmid = str(r["pmid"])
        try:
            work = _fetch(pmid)
        except Exception as e:
            print(f"\n  [warn] pmid {pmid}: {e} — will retry on next run")
            continue
        if work is None:
            continue
        if work.get("__notfound__"):
            cache[pmid] = {"found": False}
        else:
            cache[pmid] = _compact(work)
        done += 1
        if done % SAVE_EVERY == 0:
            _save_cache(cache)
            pct = 100 * done / max(len(todo), 1)
            print(f"  fetched {done}/{len(todo)} ({pct:.0f}%)", end="\r", flush=True)
        time.sleep(SLEEP)

    _save_cache(cache)
    found = sum(1 for v in cache.values() if v.get("found"))
    print(f"\n[openalex] done. cached={len(cache)}, matched in OpenAlex={found} "
          f"({100*found/max(len(cache),1):.1f}%)")


if __name__ == "__main__":
    main()
