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
    python3 openalex_enrich.py --api-key KEY   # enrich records not yet cached
    python3 openalex_enrich.py --limit 200     # quick partial test
    python3 openalex_enrich.py --records cache/records.json --budget 900

OpenAlex requires an API key since 2026 (free accounts: $1/day ≈ 1,000
requests).  Pass --api-key or set OPENALEX_API_KEY.  --budget caps the number
of requests made in one run so a free key is never exceeded; the run is
incremental — only PMIDs missing from cache/openalex_cache.json are fetched —
so re-running the next day continues where it stopped.  Every entry records
the date it was fetched and its source ("openalex" or "ror_fallback").
"""
import argparse
import datetime as _dt
import json
import os
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


class OpenAlexAuthError(RuntimeError):
    pass


def _fetch(pmid: str, api_key: str = "") -> dict | None:
    url = API + str(pmid)
    if api_key:
        url += "?api_key=" + api_key
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"__notfound__": True}
        if e.code in (401, 402, 403, 429):
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")[:300]
            except Exception:  # noqa: BLE001
                pass
            raise OpenAlexAuthError(f"HTTP {e.code}: {body or e.reason}")
        raise
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", default=str(CACHE / "records.json"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--api-key", default=os.environ.get("OPENALEX_API_KEY", ""))
    ap.add_argument("--budget", type=int, default=900,
                    help="max requests this run (free key: $1/day ≈ 1,000)")
    ap.add_argument("--refetch-older-than", default="",
                    help="YYYY-MM-DD: also refetch entries fetched before this date (or undated)")
    args = ap.parse_args()

    records = _load_records(pathlib.Path(args.records))
    if args.limit:
        records = records[: args.limit]
    cache = _load_cache()
    print(f"[openalex] {len(records)} records; {len(cache)} already cached")

    def _stale(pmid: str) -> bool:
        if not args.refetch_older_than:
            return False
        f = (cache.get(pmid) or {}).get("fetched") or ""
        return f < args.refetch_older_than

    todo = [r for r in records if str(r["pmid"]) not in cache or _stale(str(r["pmid"]))]
    print(f"[openalex] {len(todo)} to fetch (~{len(todo)*SLEEP/60:.1f} min); budget {args.budget}")
    if todo and not args.api_key:
        print("[openalex] WARNING: no API key (--api-key / OPENALEX_API_KEY). OpenAlex "
              "requires one since 2026; expect HTTP 401/403. Alternative: python3 ror_fallback.py")

    today = _dt.date.today().isoformat()
    done = 0
    for r in todo:
        if done >= args.budget:
            print(f"\n[openalex] budget of {args.budget} requests reached; "
                  f"{len(todo) - done} remain — re-run later to continue")
            break
        pmid = str(r["pmid"])
        try:
            work = _fetch(pmid, args.api_key)
        except OpenAlexAuthError as e:
            print(f"\n[openalex] STOP: {e}\n  Use a valid --api-key (free account: $1/day) "
                  f"or run ror_fallback.py for the remaining {len(todo) - done} records.")
            break
        except Exception as e:
            print(f"\n  [warn] pmid {pmid}: {e} — will retry on next run")
            continue
        if work is None:
            continue
        if work.get("__notfound__"):
            cache[pmid] = {"found": False, "fetched": today, "source": "openalex"}
        else:
            entry = _compact(work)
            entry["fetched"] = today
            entry["source"] = "openalex"
            cache[pmid] = entry
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
