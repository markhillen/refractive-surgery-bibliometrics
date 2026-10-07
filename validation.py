#!/usr/bin/env python3
"""
validation.py — corpus validation helpers
=========================================

  --delta        added/removed PMIDs of the current corpus vs a reference list
                 (default data/pmids_manuscript_v1.txt) → output/pmid_delta.csv
  --recall       every PMID in validation/known_true_positives.csv must be in the
                 corpus (hard gate); Yang et al. top-100 recall if
                 validation/yang_top100.csv has been transcribed
  --sample N     random sample of corpus records (and of records added since the
                 reference list) for hand precision screening →
                 validation/precision_sample.csv
  --anneotate    compare top journals/authors with validation/anneotate_cxl.json
  --arms         which query arm(s) retrieve each added record (offline heuristic)

All offline except --recall's optional DOI/title lookups.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib
import random
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import config

HERE = pathlib.Path(__file__).resolve().parent
VAL = HERE / "validation"
OUT = pathlib.Path(config.OUTPUT_DIR)


def _records(path="cache/records.json") -> list[dict]:
    with open(HERE / path, encoding="utf-8") as fh:
        return json.load(fh)


def _raw() -> list[dict]:
    p = HERE / "cache" / "records_raw.json"
    return json.load(open(p, encoding="utf-8")) if p.exists() else []


def _pmids(path: pathlib.Path) -> list[str]:
    return [l.strip() for l in path.read_text().splitlines() if l.strip().isdigit()]


# ── which query arm retrieved a record (heuristic, offline) ───────────────────

_ARMS = [
    ("corneal_cxl_phrase", re.compile(r"corneal (collagen )?cross[\s-]?link", re.I)),
    ("collagen_cxl_phrase", re.compile(r"collagen cross[\s-]?link", re.I)),
    ("stromal_cxl", re.compile(r"stromal cross[\s-]?link", re.I)),
    ("CXL_abbrev", re.compile(r"\b(a-?cxl|pack-cxl|cxl)\b", re.I)),
    ("epi_on_off", re.compile(r"\bepi(?:thelium)?-?(on|off)\b", re.I)),
    ("riboflavin_uv", re.compile(r"riboflavin.{0,120}(ultraviolet|uv-?a\b|uv a\b)|(ultraviolet|uv-?a\b).{0,120}riboflavin", re.I | re.S)),
    ("photoactivated_chromophore", re.compile(r"photoactivated chromophore", re.I)),
    ("KXL_C3R", re.compile(r"\b(kxl|c3-r)\b", re.I)),
    ("bare_crosslink+disease", re.compile(r"cross[\s-]?link", re.I)),
]


def query_arms(rec: dict) -> str:
    text = f"{rec.get('title','')} {rec.get('abstract','')} {' '.join(rec.get('keywords',[]))}"
    hits = [name for name, rx in _ARMS if rx.search(text)]
    if "Corneal Cross-Linking" in (rec.get("mesh") or []):
        hits.append("mesh_CXL")
    # bare cross-link only counts when no stronger phrase matched
    if "bare_crosslink+disease" in hits and any(h in hits for h in
            ("corneal_cxl_phrase", "collagen_cxl_phrase", "stromal_cxl")):
        hits.remove("bare_crosslink+disease")
    return "|".join(hits) or "none_in_text"


# ── delta ─────────────────────────────────────────────────────────────────────

def delta(reference: pathlib.Path) -> None:
    recs = {r["pmid"]: r for r in _records()}
    raw = {r["pmid"]: r for r in _raw()}
    ref = set(_pmids(reference))
    cur = set(recs)
    rows = []
    for p in sorted(cur - ref, key=lambda x: -int(x)):
        r = recs[p]
        rows.append({"pmid": p, "status": "added", "year": r.get("year"), "journal": r.get("journal"),
                     "title": (r.get("title") or "")[:160], "arm": query_arms(r),
                     "flags": ";".join((r.get("relevance") or {}).get("flags", []))})
    for p in sorted(ref - cur, key=lambda x: -int(x)):
        r = raw.get(p)
        rel = (r or {}).get("relevance") or {}
        rows.append({"pmid": p, "status": "removed",
                     "year": (r or {}).get("year", ""), "journal": (r or {}).get("journal", ""),
                     "title": ((r or {}).get("title") or "")[:160],
                     "arm": ("filtered:" + rel.get("rule", "")) if r else "not_retrieved_by_query",
                     "flags": ";".join(rel.get("flags", []))})
    OUT.mkdir(exist_ok=True)
    with open(OUT / "pmid_delta.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["pmid", "status", "year", "journal", "title", "arm", "flags"])
        w.writeheader(); w.writerows(rows)
    n_add = sum(1 for r in rows if r["status"] == "added")
    n_rem = len(rows) - n_add
    print(f"[delta] reference {len(ref)} | current {len(cur)} | added {n_add} | removed {n_rem} "
          f"| unchanged {len(cur & ref)} → {OUT / 'pmid_delta.csv'}")
    arms: dict[str, int] = {}
    for r in rows:
        if r["status"] == "added":
            arms[r["arm"]] = arms.get(r["arm"], 0) + 1
    print("[delta] added records by retrieving arm:")
    for k, v in sorted(arms.items(), key=lambda kv: -kv[1])[:25]:
        print(f"   {v:5d}  {k}")
    rem_reasons: dict[str, int] = {}
    for r in rows:
        if r["status"] == "removed":
            rem_reasons[r["arm"]] = rem_reasons.get(r["arm"], 0) + 1
    print("[delta] removed records by reason:")
    for k, v in sorted(rem_reasons.items(), key=lambda kv: -kv[1]):
        print(f"   {v:5d}  {k}")


# ── recall ────────────────────────────────────────────────────────────────────

def recall(strict: bool = True) -> int:
    recs = {r["pmid"] for r in _records()}
    raw = {r["pmid"]: r for r in _raw()}
    ok = True
    kp = VAL / "known_true_positives.csv"
    if kp.exists():
        rows = list(csv.DictReader(open(kp, encoding="utf-8")))
        miss = []
        for row in rows:
            p = row["pmid"].strip()
            if p not in recs:
                why = "filtered:" + ((raw.get(p) or {}).get("relevance") or {}).get("rule", "?") \
                      if p in raw else "not_retrieved_by_query"
                miss.append((p, row.get("label", ""), why))
        print(f"[recall] known true positives: {len(rows) - len(miss)}/{len(rows)} in corpus")
        for m in miss:
            print(f"   MISSING {m[0]}  {m[1]}  ({m[2]})")
        ok = ok and not miss
    yp = VAL / "yang_top100.csv"
    if yp.exists():
        rows = [r for r in csv.DictReader(open(yp, encoding="utf-8")) if r.get("pmid", "").strip()]
        hit = sum(1 for r in rows if r["pmid"].strip() in recs)
        print(f"[recall] Yang et al. top-100 (resolved PMIDs): {hit}/{len(rows)} = {hit/len(rows):.1%}")
        for r in rows:
            p = r["pmid"].strip()
            if p not in recs:
                why = "filtered:" + ((raw.get(p) or {}).get("relevance") or {}).get("rule", "?") \
                      if p in raw else "not_retrieved_by_query"
                print(f"   MISSING {p}  {r.get('first_author','')} {r.get('year','')}  ({why})")
    if strict and not ok:
        print("[recall] FAIL")
        return 1
    return 0


# ── precision sample ──────────────────────────────────────────────────────────

def sample(n: int, seed: int, reference: pathlib.Path) -> None:
    recs = _records()
    rng = random.Random(seed)
    ref = set(_pmids(reference)) if reference.exists() else set()
    added = [r for r in recs if r["pmid"] not in ref]
    s_all = rng.sample(recs, min(n, len(recs)))
    s_add = rng.sample(added, min(n, len(added))) if added else []
    VAL.mkdir(exist_ok=True)
    with open(VAL / "precision_sample.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["stratum", "pmid", "year", "journal", "title", "abstract_start",
                    "arm", "relevant_yn", "screened_by", "date", "note"])
        for stratum, rows in (("corpus", s_all), ("added", s_add)):
            for r in rows:
                w.writerow([stratum, r["pmid"], r.get("year"), r.get("journal"),
                            (r.get("title") or "")[:200], (r.get("abstract") or "")[:300],
                            query_arms(r), "", "", "", ""])
    print(f"[sample] {len(s_all)} corpus + {len(s_add)} added records → {VAL / 'precision_sample.csv'}")


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def precision_report() -> None:
    p = VAL / "precision_sample.csv"
    if not p.exists():
        print("[precision] no sample file"); return
    rows = list(csv.DictReader(open(p, encoding="utf-8")))
    for stratum in ("corpus", "added"):
        s = [r for r in rows if r["stratum"] == stratum and r["relevant_yn"].strip().lower() in ("y", "n")]
        if not s:
            print(f"[precision] {stratum}: not yet screened"); continue
        k = sum(1 for r in s if r["relevant_yn"].strip().lower() == "y")
        lo, hi = wilson(k, len(s))
        print(f"[precision] {stratum}: {k}/{len(s)} = {k/len(s):.1%} (95% Wilson CI {lo:.1%}–{hi:.1%})")


# ── Anne O'Tate ───────────────────────────────────────────────────────────────

def _spearman(a: list[float], b: list[float]) -> float:
    n = len(a)
    if n < 2:
        return float("nan")
    def ranks(x):
        order = sorted(range(n), key=lambda i: x[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and x[order[j + 1]] == x[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den else float("nan")


def anneotate() -> None:
    p = VAL / "anneotate_cxl.json"
    a = json.load(open(p, encoding="utf-8"))
    an = json.load(open(HERE / "output" / "all_time" / "analysis.json", encoding="utf-8"))
    print(f"[anneotate] Anne O'Tate job {a.get('job_id')} query '{a.get('query')}' n={a.get('n_records')} "
          f"vs pipeline n={an.get('n_records')}")
    # journals
    pj = {r["abbr"]: r["count"] for r in an["journals"]}
    aj = dict(a["journals"])
    common = [j for j in aj if j in pj]
    print(f"[anneotate] journals: {len(common)}/{len(aj)} of Anne O'Tate's top-20 in pipeline top-{len(pj)}; "
          f"Spearman ρ on counts (common set) = {_spearman([aj[j] for j in common], [pj[j] for j in common]):.3f}")
    # authors: Anne O'Tate uses surname + first initial
    pa: dict[str, int] = {}
    for r in an["authors"]:
        key = re.sub(r"\s*\(.*\)$", "", r["author_id"])
        m = re.match(r"^(.*)\s+([A-Z])[A-Z]*$", key)
        k = f"{m.group(1)} {m.group(2)}" if m else key
        pa[k] = pa.get(k, 0) + r["pub_count"]
    aa = dict(a["authors"])
    common = [x for x in aa if x in pa]
    rho_all = _spearman([aa[x] for x in common], [pa[x] for x in common])
    print(f"[anneotate] authors: {len(common)}/{len(aa)} of Anne O'Tate's top-20 present; "
          f"Spearman ρ on counts over ALL common names = {rho_all:.3f}")
    for x in aa:
        print(f"   {x:20s} AnneOTate={aa[x]:4d}  pipeline={pa.get(x, 0):4d}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delta", action="store_true")
    ap.add_argument("--reference", default="data/pmids_manuscript_v1.txt")
    ap.add_argument("--recall", action="store_true")
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--precision", action="store_true")
    ap.add_argument("--anneotate", action="store_true")
    args = ap.parse_args()
    rc = 0
    if args.delta:
        delta(HERE / args.reference)
    if args.recall:
        rc |= recall()
    if args.sample:
        sample(args.sample, args.seed, HERE / args.reference)
    if args.precision:
        precision_report()
    if args.anneotate:
        anneotate()
    sys.exit(rc)


if __name__ == "__main__":
    main()
