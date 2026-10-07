#!/usr/bin/env python3
"""
procedures.py — which laser refractive procedure each record is about
=====================================================================
Classifies every record of the final corpus by the procedure families it
names in its title, abstract, author keywords or MeSH headings, and writes the
yearly share of records naming each family.  A record can name several
families (comparative studies), so shares need not add up to 100%.

  LASIK                 LASIK, FS-LASIK, laser (assisted) in situ keratomileusis, SBK
  Surface ablation      PRK, LASEK, epi-LASIK, transepithelial PRK, surface ablation
  Lenticule extraction  SMILE, ReLEx, FLEx, KLEx, SmartSight, CLEAR, lenticule extraction

Output: output/procedure_mix_by_year.csv, output/procedure_mix_by_period.csv,
        output/procedure_mix_records.csv
"""
from __future__ import annotations

import csv
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import config  # noqa: E402

FAMILIES = {
    "LASIK": re.compile(
        r"\b(lasik|fs-?lasik|femto-?lasik|sbk|sub-?bowman'?s? keratomileusis|"
        r"laser[\s-](?:assisted )?in situ keratomileusis|keratomileusis, laser in situ)\b", re.I),
    "Surface ablation": re.compile(
        r"\b(photorefractive keratectom\w*|prk|t-?prk|trans-?prk|lasek|epi-?lasik|"
        r"laser[\s-](?:assisted )?(?:sub)?epithelial keratomileusis|keratectomy, subepithelial, laser-assisted|"
        r"surface ablation|transepithelial (?:photorefractive|surface))\b", re.I),
    "Lenticule extraction": re.compile(
        r"\b(smile|relex|flex|klex|smartsight|lenticule extraction|small[\s-]incision lenticule|"
        r"keratorefractive lenticule|femtosecond lenticule)\b", re.I),
}
# "SMILE" is an ordinary English word; count it only in upper case or when the
# record also names lenticules, ReLEx or small-incision surgery.
_SMILE_WORD = re.compile(r"\bsmile\b", re.I)
_LENTICULE_CONTEXT = re.compile(r"lenticul|relex|small[\s-]incision|klex|visumax", re.I)


def families(rec: dict) -> set[str]:
    text = " ".join([rec.get("title") or "", rec.get("abstract") or "",
                     " ".join(rec.get("keywords") or []), " ".join(rec.get("mesh") or [])])
    out = set()
    for fam, rx in FAMILIES.items():
        m = rx.search(text)
        if not m:
            continue
        if fam == "Lenticule extraction":
            hits = {h.group(0) for h in rx.finditer(text)}
            only_smile = all(_SMILE_WORD.fullmatch(h) for h in hits)
            if only_smile and not ("SMILE" in text or _LENTICULE_CONTEXT.search(text)):
                continue
            if all(h.lower() == "flex" for h in hits):   # "FLEx" alone is ambiguous
                if not _LENTICULE_CONTEXT.search(text):
                    continue
        out.add(fam)
    return out


def _year(r):
    try:
        return int(r.get("year") or 0)
    except ValueError:
        return 0


def run(records: list[dict], out_dir: str | None = None) -> dict:
    out = pathlib.Path(out_dir or config.OUTPUT_DIR)
    out.mkdir(parents=True, exist_ok=True)
    fams = list(FAMILIES)
    by_year: dict[int, dict] = {}
    rows = []
    for r in records:
        y = _year(r)
        f = families(r)
        rows.append([r.get("pmid"), y] + [int(k in f) for k in fams] + [int(not f)])
        d = by_year.setdefault(y, {"n": 0, **{k: 0 for k in fams}, "none": 0})
        d["n"] += 1
        for k in f:
            d[k] += 1
        if not f:
            d["none"] += 1
    with open(out / "procedure_mix_records.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["pmid", "year"] + fams + ["no_family_named"]); w.writerows(rows)
    with open(out / "procedure_mix_by_year.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["year", "records"] + [f"{k} n" for k in fams] + [f"{k} %" for k in fams] + ["no family named n"])
        for y in sorted(by_year):
            d = by_year[y]
            w.writerow([y, d["n"]] + [d[k] for k in fams] +
                       [round(100 * d[k] / d["n"], 1) for k in fams] + [d["none"]])
    per = []
    for label, y0, y1 in config.ANALYSIS_PERIODS:
        sub = [by_year[y] for y in by_year if y0 <= y <= y1]
        n = sum(d["n"] for d in sub)
        per.append([label, y0, y1, n] + [sum(d[k] for d in sub) for k in fams] +
                   [round(100 * sum(d[k] for d in sub) / n, 1) if n else None for k in fams])
    with open(out / "procedure_mix_by_period.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["period", "start", "end", "records"] + [f"{k} n" for k in fams] + [f"{k} %" for k in fams])
        w.writerows(per)
    print(f"[procedures] procedure mix written to {out}")
    return {"by_year": by_year, "families": fams}


if __name__ == "__main__":
    import json
    p = pathlib.Path(config.CACHE_DIR) / "records_final.json"
    run(json.load(open(p)))
