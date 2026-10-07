#!/usr/bin/env python3
"""
Diff pipeline per-year counts (from cached records.json) against
PubMed E-utilities direct esearch counts for the same query string.
"""
import os
import json, time, urllib.request, urllib.parse, sys
from collections import Counter

API_KEY = os.environ.get("NCBI_API_KEY", "")
BASE    = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402
QUERY_TERMS = f'({config.PUBMED_QUERY_BASE})'

def esearch_count(year):
    params = {
        "db":       "pubmed",
        "term":     QUERY_TERMS + f' AND ("{year}/01/01"[PDAT] : "{year}/12/31"[PDAT])',
        "retmax":   "0",
        "rettype":  "count",
        "api_key":  API_KEY,
    }
    url = BASE + "?" + urllib.parse.urlencode(params)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                text = resp.read().decode()
            import re
            m = re.search(r"<Count>(\d+)</Count>", text)
            if m:
                return int(m.group(1))
            raise ValueError(f"No count in response: {text[:200]}")
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
            else:
                raise
    return None

def esearch_total():
    """Single query for the entire date range (1950–2026)."""
    params = {
        "db":      "pubmed",
        "term":    QUERY_TERMS + ' AND ("1950/01/01"[PDAT] : "2026/12/31"[PDAT])',
        "retmax":  "0",
        "rettype": "count",
        "api_key": API_KEY,
    }
    url = BASE + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=15) as resp:
        text = resp.read().decode()
    import re
    m = re.search(r"<Count>(\d+)</Count>", text)
    return int(m.group(1)) if m else None

# ── 1. Load pipeline per-year counts ────────────────────────────────────────
print("Loading cached records …", flush=True)
with open("cache/records.json") as f:
    records = json.load(f)

pipeline_counts = Counter()
null_year = 0
for r in records:
    y = r.get("year")
    if y and str(y).isdigit() and 1950 <= int(y) <= 2026:
        pipeline_counts[int(y)] += 1
    else:
        null_year += 1

pipeline_total = sum(pipeline_counts.values())
print(f"Pipeline: {pipeline_total} records with parseable year ({null_year} without)")

# ── 2. Query PubMed directly ─────────────────────────────────────────────────
years = list(range(1950, 2027))
print(f"Querying PubMed for {len(years)} years (this takes ~30 s with API key) …", flush=True)

pubmed_counts = {}
for i, yr in enumerate(years):
    pubmed_counts[yr] = esearch_count(yr)
    if (i + 1) % 10 == 0:
        print(f"  {i+1}/{len(years)} done …", flush=True)
    time.sleep(0.12)   # 10 req/s with key → ~8 req/s to be safe

pubmed_total = sum(pubmed_counts.values())

# Also get the single-query total (should match sum)
print("Fetching single-query total …", flush=True)
pubmed_single = esearch_total()

# ── 3. Diff ──────────────────────────────────────────────────────────────────
print("\n" + "="*70)
print(f"{'TOTALS':}")
print(f"  Pipeline total  : {pipeline_total:>6}")
print(f"  PubMed sum/year : {pubmed_total:>6}")
print(f"  PubMed one-shot : {pubmed_single:>6}")
print(f"  Diff (pipe−PM)  : {pipeline_total - pubmed_total:>+6}")
print("="*70)

all_years = sorted(set(pipeline_counts) | set(pubmed_counts))
discrepancies = []
for yr in all_years:
    p = pipeline_counts.get(yr, 0)
    m = pubmed_counts.get(yr, 0)
    if p != m:
        discrepancies.append((yr, p, m, p - m))

if discrepancies:
    print(f"\nYEARS WITH DISCREPANCIES ({len(discrepancies)} of {len(all_years)}):")
    print(f"  {'Year':>6}  {'Pipeline':>10}  {'PubMed':>8}  {'Diff':>8}")
    print(f"  {'-'*6}  {'-'*10}  {'-'*8}  {'-'*8}")
    for yr, p, m, d in discrepancies:
        flag = "  ← LARGE" if abs(d) >= 20 else ""
        print(f"  {yr:>6}  {p:>10}  {m:>8}  {d:>+8}{flag}")
else:
    print("\nNo per-year discrepancies found — pipeline and PubMed match exactly.")

print("\nFULL PER-YEAR TABLE:")
print(f"  {'Year':>6}  {'Pipeline':>10}  {'PubMed':>8}  {'Diff':>8}")
print(f"  {'-'*6}  {'-'*10}  {'-'*8}  {'-'*8}")
for yr in all_years:
    p = pipeline_counts.get(yr, 0)
    m = pubmed_counts.get(yr, 0)
    d = p - m
    marker = " *" if d != 0 else ""
    print(f"  {yr:>6}  {p:>10}  {m:>8}  {d:>+8}{marker}")
