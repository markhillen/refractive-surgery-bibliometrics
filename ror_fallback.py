#!/usr/bin/env python3
"""
ror_fallback.py — no-key substitute for OpenAlex enrichment
===========================================================
For every record in cache/records.json that has no entry in
cache/openalex_cache.json, build a cache entry of the same compact shape from
two free, keyless services:

  citations   CrossRef  is-referenced-by-count  (by DOI; citations.py, cached)
  countries   ROR affiliation matching API      (per author affiliation string)
              https://api.ror.org/v2/organizations?affiliation=…  → the item
              flagged "chosen" gives the ROR id, name and country code

Entries are tagged  source = "ror_fallback"  so openalex_integrate.overlay()
propagates the provenance into every record (country_source / citation_source)
and the SDC provenance table can say exactly which records came from which
source.  Standard library only.

    python3 ror_fallback.py                 # fill the gaps
    python3 ror_fallback.py --limit 50      # quick test
    python3 ror_fallback.py --agreement 100 # re-resolve 100 OpenAlex-cached
                                            # records via ROR and report agreement
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import pathlib
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import config  # noqa: E402
import citations  # noqa: E402

CACHE = pathlib.Path(config.CACHE_DIR)
OA_CACHE = CACHE / "openalex_cache.json"
ROR_CACHE = CACHE / "ror_affil_cache.json"
ROR_API = "https://api.ror.org/v2/organizations?affiliation="
UA = "cxl-biblio/3.0 (mailto:markhillen@gmail.com)"
SLEEP = 0.5


def _load(p: pathlib.Path) -> dict:
    return json.load(open(p, encoding="utf-8")) if p.exists() else {}


def _save(p: pathlib.Path, obj) -> None:
    tmp = p.with_suffix(p.suffix + ".tmp")
    json.dump(obj, open(tmp, "w", encoding="utf-8"))
    tmp.replace(p)


def ror_lookup(affil: str, cache: dict) -> dict | None:
    """{"ror","name","cc","score"} for the ROR-chosen match, or None."""
    key = hashlib.sha1(affil.strip().lower().encode("utf-8")).hexdigest()
    if key in cache:
        return cache[key] or None
    url = ROR_API + urllib.parse.quote(affil[:300])
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] ROR: {e}")
        return None
    time.sleep(SLEEP)
    chosen = next((it for it in d.get("items", []) if it.get("chosen")), None)
    out = None
    if chosen:
        org = chosen.get("organization", {})
        cc = None
        for loc in org.get("locations", []) or []:
            cc = (loc.get("geonames_details") or {}).get("country_code") or cc
        name = next((n["value"] for n in org.get("names", []) if "ror_display" in n.get("types", [])),
                    (org.get("names") or [{}])[0].get("value"))
        out = {"ror": org.get("id"), "name": name, "cc": cc, "score": chosen.get("score")}
    cache[key] = out or {}
    return out


def build_entry(rec: dict, ror_cache: dict, cr_cache: dict, today: str) -> dict:
    authors = rec.get("authors", []) or []
    n = len(authors)
    aus = []
    for i, a in enumerate(authors):
        pos = "first" if i == 0 else ("last" if i == n - 1 and n > 1 else "middle")
        insts, ccs = [], []
        for affil in a.get("affils", []) or []:
            for seg in [s.strip() for s in affil.split(";") if s.strip()]:
                hit = ror_lookup(seg, ror_cache)
                if hit and hit.get("ror"):
                    insts.append({"ror": hit["ror"], "name": hit["name"], "cc": hit["cc"]})
                    if hit["cc"] and hit["cc"] not in ccs:
                        ccs.append(hit["cc"])
        aus.append({"id": None, "name": f"{a.get('fore','')} {a.get('last','')}".strip(),
                    "orcid": a.get("orcid") or None, "pos": pos, "countries": ccs, "insts": insts})
    doi = rec.get("doi") or ""
    cited = None
    if doi:
        if doi not in cr_cache:
            cr_cache[doi] = citations.fetch_citation_count(doi)
            time.sleep(config.CITATION_BATCH_DELAY)
        cited = cr_cache[doi]
    return {"found": True, "source": "ror_fallback", "fetched": today, "oa_id": None,
            "year": None, "cited_by": cited, "journal": rec.get("journal"),
            "issn_l": rec.get("issn_linking"), "authors": aus}


def agreement(n: int, seed: int = 1) -> None:
    """Re-resolve n OpenAlex-cached records' first-author affiliation via ROR;
    report how often country and ROR id agree with OpenAlex."""
    oa = _load(OA_CACHE)
    recs = {r["pmid"]: r for r in json.load(open(CACHE / "records.json", encoding="utf-8"))}
    ror_cache = _load(ROR_CACHE)
    cands = [p for p, w in oa.items() if w.get("found") and w.get("source", "openalex") == "openalex"
             and p in recs and recs[p].get("authors") and recs[p]["authors"][0].get("affils")
             and (w.get("authors") or [{}])[0].get("countries")]
    random.Random(seed).shuffle(cands)
    rows = []
    for p in cands[:n]:
        first_oa = oa[p]["authors"][0]
        affil = recs[p]["authors"][0]["affils"][0].split(";")[0]
        hit = ror_lookup(affil, ror_cache)
        rows.append({"pmid": p, "oa_cc": (first_oa.get("countries") or [None])[0],
                     "oa_ror": [i.get("ror") for i in first_oa.get("insts") or []],
                     "ror_cc": (hit or {}).get("cc"), "ror_id": (hit or {}).get("ror")})
    _save(ROR_CACHE, ror_cache)
    n_cc = sum(1 for r in rows if r["ror_cc"] and r["ror_cc"] == r["oa_cc"])
    n_id = sum(1 for r in rows if r["ror_id"] and r["ror_id"] in r["oa_ror"])
    n_res = sum(1 for r in rows if r["ror_cc"])
    out = pathlib.Path(config.OUTPUT_DIR) / "sdc"
    out.mkdir(parents=True, exist_ok=True)
    import csv
    with open(out / "ror_agreement.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["metric", "value"])
        w.writerow(["records_sampled", len(rows)])
        w.writerow(["ror_resolved", n_res])
        w.writerow(["country_agrees_with_openalex", n_cc])
        w.writerow(["ror_id_agrees_with_openalex", n_id])
        w.writerow(["country_agreement_pct_of_resolved", round(100 * n_cc / n_res, 1) if n_res else ""])
    print(f"[ror] sampled {len(rows)}: ROR resolved {n_res}; country agrees {n_cc}; ROR id agrees {n_id}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", default=str(CACHE / "records.json"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--agreement", type=int, default=0)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    if args.agreement:
        agreement(args.agreement, args.seed)
        return
    records = json.load(open(args.records, encoding="utf-8"))
    oa = _load(OA_CACHE)
    ror_cache = _load(ROR_CACHE)
    cr_cache = _load(CACHE / "citation_cache.json")
    todo = [r for r in records if str(r.get("pmid")) not in oa or not oa[str(r["pmid"])].get("found")]
    if args.limit:
        todo = todo[: args.limit]
    print(f"[ror] {len(todo)} records without OpenAlex data → CrossRef + ROR fallback")
    today = _dt.date.today().isoformat()
    for i, rec in enumerate(todo, 1):
        oa[str(rec["pmid"])] = build_entry(rec, ror_cache, cr_cache, today)
        if i % 20 == 0:
            _save(OA_CACHE, oa); _save(ROR_CACHE, ror_cache); _save(CACHE / "citation_cache.json", cr_cache)
            print(f"  {i}/{len(todo)}", end="\r", flush=True)
    _save(OA_CACHE, oa); _save(ROR_CACHE, ror_cache); _save(CACHE / "citation_cache.json", cr_cache)
    print(f"\n[ror] done; cache now {len(oa)} entries")


if __name__ == "__main__":
    main()
