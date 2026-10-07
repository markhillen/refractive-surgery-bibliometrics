#!/usr/bin/env python3
"""
checkpoint.py — snapshot the headline numbers of a pipeline run and diff two
snapshots (optionally against the numbers printed in the manuscript).

    python3 checkpoint.py snapshot <label> [--output output]
    python3 checkpoint.py diff <label_a> <label_b> [--manuscript data/manuscript_numbers.csv]
    python3 checkpoint.py list

Snapshots are written to checkpoints/<label>.json as a flat {metric: value}
dictionary so that any two runs can be compared metric by metric, and so the
final run can be compared with what the manuscript currently says.
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
CHECKPOINT_DIR = HERE / "checkpoints"

# Names whose rows we always want to track, even if they fall out of the top-N
TRACK_AUTHORS = [
    "Hafezi F", "Kymionis GD", "Mazzotta C", "Spoerl E", "Seiler T", "Seiler TG",
    "Torres-Netto EA", "Kanellopoulos AJ", "Wollensak G", "Zhou X (Fudan)",
    "Hafezi NL", "Kling S", "Randleman JB", "Vinciguerra P", "Grentzelos MA",
]
TRACK_COUNTRIES = [
    "United States", "China", "Turkey", "India", "Italy", "Germany",
    "United Kingdom", "Switzerland", "Iran", "Greece", "Unknown",
]
TRACK_INSTITUTIONS = [
    "Wenzhou Medical University", "Fudan University", "Tianjin Eye Hospital",
    "Laservision Institute Athens", "University of Crete", "ELZA Institute",
    "University of Zurich", "IROC Zurich", "Moorfields Eye Hospital",
    "TU Dresden", "University Hospital Dresden", "University of Siena",
    "University of Geneva", "Mass Eye and Ear / Harvard",
]
TRACK_JOURNALS = ["Cornea", "J Refract Surg", "J Cataract Refract Surg", "Am J Ophthalmol"]
TRACK_KEYWORDS = [
    "LASIK", "photorefractive keratectomy (PRK)", "lenticule extraction (SMILE/KLEx)",
    "dry eye", "corneal ectasia", "corneal biomechanics", "artificial intelligence",
]


def _load(path: pathlib.Path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _period_json(output: pathlib.Path, period: str) -> dict | None:
    p = output / period / "analysis.json"
    return _load(p) if p.exists() else None


def _rows_by(rows, key):
    return {r.get(key): r for r in rows if isinstance(r, dict)}


def snapshot(label: str, output: pathlib.Path) -> dict:
    m: dict[str, object] = {}
    at = _period_json(output, "all_time")
    if at is None:
        sys.exit(f"no output/all_time/analysis.json under {output}")

    m["n_records"] = at.get("n_records")

    # temporal
    t = at.get("temporal") or {}
    for y, c in zip(t.get("years", []), t.get("counts", [])):
        m[f"year.{y}"] = c
    cites = t.get("citations") or []
    for y, c in zip(t.get("years", []), cites):
        m[f"year_citations.{y}"] = c
    if t.get("counts"):
        years = t["years"]; counts = t["counts"]
        m["peak_year"] = years[counts.index(max(counts))]
        m["peak_count"] = max(counts)

    # journals
    jr = _rows_by(at.get("journals") or [], "abbr")
    jr_full = _rows_by(at.get("journals") or [], "journal")
    for j in TRACK_JOURNALS:
        r = jr.get(j) or jr_full.get(j)
        m[f"journal.{j}.n"] = r.get("count", r.get("publications")) if r else None
        m[f"journal.{j}.pct"] = r.get("percentage") if r else None
    m["n_journals"] = len(at.get("journals") or [])

    # countries
    cr = _rows_by(at.get("countries") or [], "country")
    for c in TRACK_COUNTRIES:
        r = cr.get(c)
        m[f"country.{c}.n"] = r.get("publications", r.get("count")) if r else None
        m[f"country.{c}.pct"] = r.get("percentage") if r else None
        m[f"country.{c}.cites"] = r.get("total_citations", r.get("citations")) if r else None
        m[f"country.{c}.per_million"] = r.get("pubs_per_million") if r else None
    m["n_countries"] = len([c for c in cr if c != "Unknown"])

    # authors
    ar = _rows_by(at.get("authors") or [], "author_id")
    for a in TRACK_AUTHORS:
        r = ar.get(a)
        m[f"author.{a}.n"] = r.get("pub_count") if r else None
        m[f"author.{a}.first"] = r.get("first_author_count") if r else None
        m[f"author.{a}.last"] = r.get("last_author_count") if r else None
        m[f"author.{a}.cites"] = r.get("citation_total") if r else None
    m["n_authors_ge3"] = len(at.get("authors") or [])

    # institutions
    ir = _rows_by(at.get("institutions") or [], "institution")
    for i in TRACK_INSTITUTIONS:
        r = ir.get(i)
        m[f"institution.{i}.n"] = r.get("count", r.get("publications")) if r else None
    top10 = [r.get("institution") for r in (at.get("institutions") or [])[:10]]
    m["institutions.top10"] = " | ".join(str(x) for x in top10)

    # keywords
    kw = at.get("keywords") or {}
    freq = kw.get("freq", {}) if isinstance(kw, dict) else _rows_by(kw, "keyword")
    for k in TRACK_KEYWORDS:
        v = freq.get(k)
        m[f"keyword.{k}.n"] = (v.get("frequency") if isinstance(v, dict) else v)
    if isinstance(kw, dict) and "coverage" in kw:
        m["keyword.coverage_pct"] = kw["coverage"].get("overall_pct")

    # publication types
    pt = at.get("pub_types") or {}
    if isinstance(pt, dict):
        m["pubtype.RCT"] = pt.get("Randomized Controlled Trial")
        m["pubtype.Review"] = pt.get("Review")
        m["pubtype.SystematicReview"] = pt.get("Systematic Review")
        m["pubtype.MetaAnalysis"] = pt.get("Meta-Analysis")
    elif isinstance(pt, list):
        d = {r.get("type", r.get("pub_type")): r.get("count") for r in pt if isinstance(r, dict)}
        m["pubtype.RCT"] = d.get("Randomized Controlled Trial")
        m["pubtype.Review"] = d.get("Review")
        m["pubtype.SystematicReview"] = d.get("Systematic Review")
        m["pubtype.MetaAnalysis"] = d.get("Meta-Analysis")

    # summary stats csv (total citations)
    ss = output / "all_time" / "summary_stats.csv"
    if ss.exists():
        with open(ss, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row.get("metric", "").startswith("Total citations"):
                    m["total_citations"] = int(float(row["value"]))
                if row.get("metric", "") == "Unique countries":
                    m["n_countries_summary"] = int(float(row["value"]))

    # last 5 years window
    l5 = _period_json(output, "last_5yr")
    if l5:
        m["last5.n_records"] = l5.get("n_records")
        cr5 = _rows_by(l5.get("countries") or [], "country")
        for c in ("United States", "China", "Unknown"):
            r = cr5.get(c)
            m[f"last5.country.{c}.n"] = r.get("publications", r.get("count")) if r else None

    # period comparison
    pc = output / "period_comparison.csv"
    if pc.exists():
        with open(pc, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                lab = row.get("period") or row.get("label")
                if lab:
                    for k, v in row.items():
                        if k not in ("period", "label") and v not in (None, ""):
                            m[f"period.{lab}.{k}"] = v

    # SDC / sensitivity extras, when present
    prov = output / "sdc" / "data_provenance.csv"
    if prov.exists():
        with open(prov, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                m[f"provenance.{row.get('metric')}"] = row.get("value")

    CHECKPOINT_DIR.mkdir(exist_ok=True)
    out = CHECKPOINT_DIR / f"{label}.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(m, fh, indent=1, ensure_ascii=False, default=str)
    print(f"[checkpoint] {len(m)} metrics → {out}")
    return m


def _fmt(v):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def diff(a: str, b: str, manuscript: pathlib.Path | None, only_changed: bool):
    ma = _load(CHECKPOINT_DIR / f"{a}.json")
    mb = _load(CHECKPOINT_DIR / f"{b}.json")
    ms: dict[str, tuple[str, str]] = {}
    if manuscript and manuscript.exists():
        with open(manuscript, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                ms[row["metric"]] = (row.get("manuscript_value", ""), row.get("location", ""))
    keys = sorted(set(ma) | set(mb) | set(ms))
    hdr = ["metric", "manuscript", a, b, "delta", "location"] if ms else ["metric", a, b, "delta"]
    rows = []
    for k in keys:
        va, vb = ma.get(k), mb.get(k)
        if only_changed and va == vb and (k not in ms):
            continue
        d = ""
        try:
            if va is not None and vb is not None and not isinstance(va, str):
                d = f"{float(vb) - float(va):+g}"
        except (TypeError, ValueError):
            d = ""
        if ms:
            mv, loc = ms.get(k, ("", ""))
            rows.append([k, mv, _fmt(va), _fmt(vb), d, loc])
        else:
            rows.append([k, _fmt(va), _fmt(vb), d])
    widths = [max(len(str(r[i])) for r in rows + [hdr]) for i in range(len(hdr))]
    def line(r): return " | ".join(str(x).ljust(w) for x, w in zip(r, widths))
    print(line(hdr)); print("-+-".join("-" * w for w in widths))
    for r in rows:
        print(line(r))
    out = CHECKPOINT_DIR / f"diff_{a}_vs_{b}.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(hdr); w.writerows(rows)
    print(f"\n[checkpoint] diff → {out}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot"); s.add_argument("label"); s.add_argument("--output", default="output")
    d = sub.add_parser("diff"); d.add_argument("a"); d.add_argument("b")
    d.add_argument("--manuscript", default="data/manuscript_numbers.csv")
    d.add_argument("--all", action="store_true", help="show unchanged metrics too")
    sub.add_parser("list")
    args = ap.parse_args()
    if args.cmd == "snapshot":
        snapshot(args.label, HERE / args.output)
    elif args.cmd == "diff":
        diff(args.a, args.b, HERE / args.manuscript, only_changed=not args.all)
    else:
        for p in sorted(CHECKPOINT_DIR.glob("*.json")):
            print(p.stem)


if __name__ == "__main__":
    main()
