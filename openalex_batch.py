#!/usr/bin/env python3
"""
openalex_batch.py — batched OpenAlex enrichment, 50 PMIDs per request
====================================================================
Same cache format as openalex_enrich.py (cache/openalex_cache.json), but looks
records up fifty at a time through the list endpoint:

    /works?filter=pmid:1|2|…|50&per_page=50&select=…

so a corpus of ~11,000 records costs ~230 requests instead of ~11,000.  That
keeps a keyless run inside OpenAlex's free daily budget (1,000 requests per
day per IP in 2026).

Incremental and resumable: only PMIDs missing from the cache (or fetched
before --refetch-older-than) are requested, the cache is saved after every
request, and --max-seconds stops cleanly so the script can be re-run in short
slices on machines that cap a command's run time.

Standard library only.

Usage:
    python3 openalex_batch.py --pmids data/final_pmids.txt
    python3 openalex_batch.py --pmids data/final_pmids.txt --max-seconds 160
"""
import argparse
import datetime as _dt
import json
import os
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
CACHE = HERE / "cache" / "openalex_cache.json"
API = "https://api.openalex.org/works"
UA = "rs-biblio/2.0 (mailto:mhillen@elza-institute.com)"
SELECT = "id,ids,publication_year,cited_by_count,primary_location,authorships"
BATCH = 50
SLEEP = 0.25


def _compact(work: dict) -> dict:
    """Identical to openalex_enrich._compact, so both scripts share one cache."""
    auths = []
    for a in work.get("authorships") or []:
        au = a.get("author") or {}
        insts = a.get("institutions") or []
        auths.append({
            "id": au.get("id"),
            "name": au.get("display_name"),
            "orcid": au.get("orcid"),
            "pos": a.get("author_position"),
            "countries": a.get("countries") or [],
            "insts": [{"ror": i.get("ror"), "name": i.get("display_name"),
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


def _pmid_of(work: dict) -> str:
    p = ((work.get("ids") or {}).get("pmid") or "").rstrip("/")
    return p.rsplit("/", 1)[-1] if p else ""


def _get(pmids: list[str], api_key: str = "") -> tuple[list[dict], dict]:
    params = {"filter": "pmid:" + "|".join(pmids), "per_page": str(BATCH),
              "select": SELECT, "mailto": "mhillen@elza-institute.com"}
    if api_key:
        params["api_key"] = api_key
    url = API + "?" + urllib.parse.urlencode(params, safe="|:,")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        hdr = {k.lower(): v for k, v in r.headers.items()}
        body = json.loads(r.read().decode("utf-8", "replace"))
    return body.get("results") or [], hdr


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pmids", required=True, help="one PMID per line")
    ap.add_argument("--api-key", default=os.environ.get("OPENALEX_API_KEY", ""))
    ap.add_argument("--max-seconds", type=float, default=0, help="stop cleanly after this long")
    ap.add_argument("--refetch-older-than", default="", help="YYYY-MM-DD")
    ap.add_argument("--cache", default=str(CACHE))
    a = ap.parse_args()

    cache_p = pathlib.Path(a.cache)
    cache_p.parent.mkdir(parents=True, exist_ok=True)
    cache = json.load(open(cache_p)) if cache_p.exists() else {}
    pmids = [l.strip() for l in open(a.pmids) if l.strip() and not l.startswith("#")]

    def stale(p):
        e = cache.get(p)
        if e is None:
            return True
        return bool(a.refetch_older_than) and (e.get("fetched") or "") < a.refetch_older_than

    todo = [p for p in pmids if stale(p)]
    print(f"[openalex] {len(pmids)} PMIDs; {len(pmids) - len(todo)} cached; {len(todo)} to fetch "
          f"(~{(len(todo) + BATCH - 1) // BATCH} requests)")
    t0 = time.time()
    today = _dt.date.today().isoformat()
    done_req = 0
    remaining = None
    for i in range(0, len(todo), BATCH):
        if a.max_seconds and time.time() - t0 > a.max_seconds:
            print(f"[openalex] time slice used; {len(todo) - i} PMIDs remain — re-run to continue")
            break
        chunk = todo[i:i + BATCH]
        try:
            works, hdr = _get(chunk, a.api_key)
        except urllib.error.HTTPError as e:
            print(f"[openalex] STOP: HTTP {e.code} {e.read()[:200]!r}")
            break
        except Exception as e:  # noqa: BLE001
            print(f"[openalex] warning: {e}; retrying this batch next run")
            time.sleep(2)
            continue
        got = set()
        for w in works:
            p = _pmid_of(w)
            if p in chunk:
                e = _compact(w)
                e["fetched"] = today
                e["source"] = "openalex"
                cache[p] = e
                got.add(p)
        for p in chunk:
            if p not in got:
                cache[p] = {"found": False, "fetched": today, "source": "openalex"}
        done_req += 1
        remaining = hdr.get("x-ratelimit-remaining")
        tmp = cache_p.with_suffix(".tmp")
        json.dump(cache, open(tmp, "w"))
        tmp.replace(cache_p)
        time.sleep(SLEEP)
    n = sum(1 for p in pmids if p in cache)
    f = sum(1 for p in pmids if (cache.get(p) or {}).get("found"))
    print(f"[openalex] requests this run {done_req}; daily budget remaining {remaining}; "
          f"cached {n}/{len(pmids)}; matched {f} ({100 * f / max(n, 1):.1f}%)")


if __name__ == "__main__":
    main()
