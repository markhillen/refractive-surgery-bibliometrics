"""
citations.py — Citation count enrichment via CrossRef free API
==============================================================
Fetches citation counts (times-cited) for each record that has a DOI.
CrossRef polite pool: include mailto in User-Agent.
"""

import json
import time
import pathlib
import sys
import urllib.request
import urllib.parse
import urllib.error

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import config

CROSSREF_BASE = "https://api.crossref.org/works/"
MAILTO = "bibliometric-tool@example.com"   # polite pool


def fetch_citation_count(doi: str) -> int | None:
    """Return citation count for a DOI from CrossRef, or None on failure."""
    if not doi:
        return None
    url = CROSSREF_BASE + urllib.parse.quote(doi, safe="")
    req = urllib.request.Request(url)
    req.add_header("User-Agent", f"CXL-Bibliometric/1.0 (mailto:{MAILTO})")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
        return data.get("message", {}).get("is-referenced-by-count", None)
    except Exception:
        return None


def enrich_citations(records: list[dict], cache_file: str = "") -> list[dict]:
    """
    Adds 'citation_count' to each record.
    Caches results to avoid re-fetching.
    """
    if not config.FETCH_CITATIONS:
        print("[citations] Skipped (FETCH_CITATIONS=False in config)")
        return records

    cache_path = pathlib.Path(cache_file or (config.CACHE_DIR + "/citation_cache.json"))
    cache: dict[str, int | None] = {}
    if cache_path.exists():
        with open(cache_path) as f:
            cache = json.load(f)
        print(f"[citations] Loaded {len(cache)} cached citation counts")

    needs_fetch = [r for r in records if r.get("doi") and r["doi"] not in cache]
    total = len(needs_fetch)

    if total:
        print(f"[citations] Fetching citation counts for {total} DOIs …")
        for i, rec in enumerate(needs_fetch):
            doi = rec["doi"]
            count = fetch_citation_count(doi)
            cache[doi] = count
            pct = (i + 1) / total * 100
            print(f"  {i+1}/{total} ({pct:.1f}%)  {doi[:60]}  -> {count}", end="\r")
            time.sleep(config.CITATION_BATCH_DELAY)

        print(f"\n[citations] Done. Saving cache …")
        with open(cache_path, "w") as f:
            json.dump(cache, f, indent=2)

    # Apply to records
    for rec in records:
        doi = rec.get("doi", "")
        if doi and doi in cache:
            rec["citation_count"] = cache[doi]

    return records


if __name__ == "__main__":
    cache_path = pathlib.Path(config.CACHE_DIR) / "records_disambig.json"
    if not cache_path.exists():
        cache_path = pathlib.Path(config.CACHE_DIR) / "records.json"
    with open(cache_path) as f:
        records = json.load(f)
    records = enrich_citations(records)
    out = pathlib.Path(config.CACHE_DIR) / "records_cited.json"
    with open(out, "w") as f:
        json.dump(records, f, indent=2)
    print(f"Saved to {out}")
