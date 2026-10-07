#!/usr/bin/env python3
"""
crossref_batch.py — CrossRef cited-by counts with a few polite parallel workers
==============================================================================
Fills cache/citation_cache.json (DOI → is-referenced-by-count), the same cache
citations.enrich_citations() reads, but saves as it goes and uses four workers
within CrossRef's polite-pool limits, so a corpus of ~10,000 DOIs takes minutes
rather than an hour and a half.  CrossRef is the cross-check source; OpenAlex
supplies the primary citation counts.

Usage:  python3 crossref_batch.py [--records cache/records.json] [--workers 4]
"""
import argparse
import concurrent.futures as cf
import json
import pathlib
import threading
import time
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
CACHE = HERE / "cache" / "citation_cache.json"
UA = "rs-biblio/2.0 (mailto:mhillen@elza-institute.com)"
_lock = threading.Lock()


def fetch(doi: str):
    url = "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="")
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode()).get("message", {}).get("is-referenced-by-count")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(1.5 * (attempt + 1))
        except Exception:  # noqa: BLE001
            time.sleep(1.5 * (attempt + 1))
    return "__retry__"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", default=str(HERE / "cache" / "records.json"))
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    recs = json.load(open(a.records))
    cache = json.load(open(CACHE)) if CACHE.exists() else {}
    dois = sorted({r["doi"] for r in recs if r.get("doi")} - set(cache))
    print(f"[crossref] {len(dois)} DOIs to fetch ({len(cache)} cached)")
    done = 0

    def work(d):
        c = fetch(d)
        time.sleep(0.08)
        return d, c

    with cf.ThreadPoolExecutor(a.workers) as ex:
        for d, c in ex.map(work, dois):
            if c != "__retry__":
                with _lock:
                    cache[d] = c
            done += 1
            if done % 250 == 0:
                json.dump(cache, open(CACHE, "w"))
                print(f"  {done}/{len(dois)}", flush=True)
    json.dump(cache, open(CACHE, "w"))
    print(f"[crossref] done; cache holds {len(cache)} DOIs")


if __name__ == "__main__":
    main()
