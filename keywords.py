"""
keywords.py — author-keyword normalisation
==========================================

Author keywords in PubMed are free text: the same concept arrives as
"SMILE", "small incision lenticule extraction (SMILE)", "ReLEx SMILE",
"KLEx", "FS-LASIK", "femtosecond laser-assisted in situ keratomileusis" …  Before
counting, every keyword passes through:

  1. Unicode NFKC, case folding, all dash variants → "-", accents stripped,
     whitespace collapsed, trailing punctuation removed
  2. rule-based family normalisation (cross-link*, transepithelial/epi-on,
     epi-off, UVA, A-CXL, PACK-CXL, keratoconus in any language)
  3. light singularisation
  4. exact lookup in data/keyword_synonyms.csv (variant → canonical)
  5. family fallbacks for anything still carrying a recognisable stem

The synonym table is data, published with the SDC.  ``coverage_by_year`` gives
the denominator every temporal keyword statement needs: the share of records
that carry any author keyword at all.
"""

from __future__ import annotations

import csv
import pathlib
import re
import sys
import unicodedata

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import config

SYN_PATH = pathlib.Path(config.DATA_DIR) / "keyword_synonyms.csv"

CANON_CXL = "corneal cross-linking (CXL)"
CANON_ACCEL = "accelerated CXL"
CANON_EPI_ON = "transepithelial (epi-on) CXL"
CANON_EPI_OFF = "epi-off CXL"
CANON_PACK = "PACK-CXL"
CANON_KC = "keratoconus"
CANON_UVA = "ultraviolet-A (UVA)"
CANON_SUBCLIN = "subclinical keratoconus"
CANON_ECTASIA = "corneal ectasia"
CANON_POSTREF = "post-refractive ectasia"
CANON_PMD = "pellucid marginal degeneration"
CANON_TOPO = "corneal topography"
CANON_TOMO = "corneal tomography"
CANON_BIOMECH = "corneal biomechanics"
CANON_ICRS = "intracorneal ring segments"
CANON_DALK = "deep anterior lamellar keratoplasty (DALK)"
CANON_PK = "penetrating keratoplasty"
CANON_SCLERAL = "scleral lens"
CANON_RGP = "rigid gas-permeable contact lens"
CANON_AI = "artificial intelligence"
CANON_ML = "machine learning"
CANON_DL = "deep learning"
CANON_INF_KER = "infectious keratitis"
CANON_LASIK = "LASIK"
CANON_PRK = "photorefractive keratectomy (PRK)"
CANON_TPRK = "transepithelial PRK"
CANON_LASEK = "LASEK / epi-LASIK"
CANON_LENT = "lenticule extraction (SMILE/KLEx)"
CANON_RS = "refractive surgery"

# The generic field label excluded from thematic charts by default (every record
# is a refractive-surgery record); the individual procedures stay in the charts.
SEARCH_TERM_CANONICALS = {"refractive surgery"}

_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−­﹣－"), "-")

_syn: dict[str, str] | None = None


def load_synonyms(path: pathlib.Path | None = None) -> dict[str, str]:
    global _syn
    if _syn is not None and path is None:
        return _syn
    path = path or SYN_PATH
    d: dict[str, str] = {}
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                v = _basic(row.get("variant", ""))
                c = (row.get("canonical") or "").strip()
                if v and c:
                    d[v] = c
    if path == SYN_PATH:
        _syn = d
    return d


def reset() -> None:
    global _syn
    _syn = None


def _basic(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.translate(_DASHES)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.casefold()
    s = re.sub(r"\s+", " ", s).strip()
    s = s.strip(" .,;:!?\"'")
    s = re.sub(r"\s*-\s*", "-", s)          # "cross - linking" → "cross-linking"
    s = re.sub(r"\s*/\s*", "/", s)
    return s


_FAMILY_PRE = [
    (re.compile(r"\bcross[\s-]?link(ing|ed|s)?\b"), "cross-linking"),
    (re.compile(r"\bcrosslink(ing|ed|s)?\b"), "cross-linking"),
    (re.compile(r"\btrans[\s-]?epithelial\b"), "transepithelial"),
    (re.compile(r"\bepi(?:thelium|thelial)?[\s-]?on\b"), "epi-on"),
    (re.compile(r"\bepi(?:thelium|thelial)?[\s-]?off\b"), "epi-off"),
    (re.compile(r"\b(?:ultraviolet|uv)[\s-]?a\b"), "uva"),
    (re.compile(r"\bultra[\s-]?violet\b"), "ultraviolet"),
    (re.compile(r"\ba[\s-]?cxl\b"), "accelerated cxl"),
    (re.compile(r"\bpack[\s-]?cxl\b"), "pack-cxl"),
    (re.compile(r"\bkerato?c[oô]ne?\b|\bqueratocono\b|\bcheratocono\b|\bkeratokonus\b"), "keratoconus"),
    (re.compile(r"\bcornee\b|\bcornea\b"), "cornea"),
    (re.compile(r"\bp(?:a)?ediatric\b"), "paediatric"),
    (re.compile(r"\((cxl|kc|uva|prk|oct)\)"), r"\1"),
]

_SINGULAR_EXCEPTIONS = {"lens", "keratoconus", "sclera", "cornea", "stroma", "diabetes", "analysis",
                        "genesis", "series", "hysteresis", "mitosis", "apoptosis", "ptosis", "uveitis",
                        "keratitis", "ectasis", "hydrops", "sis", "iris", "us", "is", "as", "os"}


def _singular(term: str) -> str:
    toks = term.split(" ")
    if not toks:
        return term
    last = toks[-1]
    if last in _SINGULAR_EXCEPTIONS or len(last) < 5 or last.endswith(("ss", "us", "is", "sis", "itis", "ics")):
        return term
    if last.endswith("lenses"):
        toks[-1] = last[:-2]
    elif last.endswith("analyses"):
        toks[-1] = last[:-2] + "is"
    elif last.endswith("ies"):
        toks[-1] = last[:-3] + "y"
    elif last.endswith(("sses", "uses", "xes", "ches", "shes")):
        toks[-1] = last[:-2]
    elif last.endswith("analyses"):
        toks[-1] = last[:-2] + "is"
    elif last.endswith("s"):
        toks[-1] = last[:-1]
    return " ".join(toks)


_FAMILY_POST = [
    # ── procedures ──────────────────────────────────────────────────────────
    (re.compile(r"^(?:(?:femtosecond|femto|fs)[\s-]?(?:laser[\s-])?(?:assisted )?)?(?:lasik|laser[\s-](?:assisted )?in situ keratomileusis)(?: \(?(?:fs-)?lasik\)?)?$"
                r"|^(?:fs|femto|femtosecond)-?lasik$|^femtosecond laser in situ keratomileusis$|^sbk$|^sub-bowman keratomileusis$"
                r"|^laser in situ keratomileusis surgery$|^keratomileusis, laser in situ$"), CANON_LASIK),
    (re.compile(r"^(?:transepithelial|trans-?epithelial|single[\s-]step transepithelial|one[\s-]step transepithelial)"
                r"(?: photorefractive keratectomy| prk| surface ablation)(?: \(?t-?prk\)?)?$|^t-?prk$|^trans-?prk$|^ss-?t-?prk$|^streamlight$"), CANON_TPRK),
    (re.compile(r"^(?:photorefractive keratectom(?:y|ies))(?: \(?prk\)?)?$|^prk$|^excimer laser photorefractive keratectomy$"
                r"|^photorefractive keratectomy, excimer laser$"), CANON_PRK),
    (re.compile(r"^lasek$|^laser[\s-](?:assisted )?(?:sub)?epithelial keratomileusis(?: \(?lasek\)?)?$|^epi-?lasik$|^epipolis lasik$"), CANON_LASEK),
    (re.compile(r"^(?:advanced )?surface ablation$|^asa$"), "surface ablation"),
    (re.compile(r"^(?:femtosecond )?small[\s-]incision lenticule extraction(?: \(?smile\)?)?$|^smile(?: pro)?$|^relex(?: smile)?$"
                r"|^refractive lenticule extraction(?: \(?relex\)?)?$|^keratorefractive lenticule extraction(?: \(?klex\)?)?$|^klex$"
                r"|^femtosecond lenticule extraction(?: \(?flex\)?)?$|^lenticule extraction$|^smartsight$|^clear$"
                r"|^corneal lenticule extraction for advanced refractive correction$"), CANON_LENT),
    (re.compile(r"^(?:corneal |laser |keratorefractive |laser corneal )?refractive surg(?:ery|ical procedures?)$|^refractive surgical procedure$"
                r"|^keratorefractive surgery$|^laser vision correction$|^laser refractive correction$|^corneal refractive procedure$"), CANON_RS),
    (re.compile(r"^wavefront[\s-]guided(?: ablation| treatment| lasik| prk)?$"), "wavefront-guided ablation"),
    (re.compile(r"^wavefront[\s-]optimi[sz]ed(?: ablation| treatment)?$"), "wavefront-optimized ablation"),
    (re.compile(r"^topography[\s-]guided(?: ablation| treatment| lasik| prk| photorefractive keratectomy)?$|^contoura(?: vision)?$|^t-cat$"), "topography-guided ablation"),
    (re.compile(r"^presby-?lasik$|^presbyond$|^laser blended vision$|^intracor$|^presbyopia correction$"), "laser presbyopia correction"),
    (re.compile(r"^(?:femtosecond|fs|femto)(?: laser)?s?$|^femtosecond laser technology$"), "femtosecond laser"),
    (re.compile(r"^excimer(?: laser)?s?$|^excimer laser ablation$"), "excimer laser"),
    # ── refractive errors ───────────────────────────────────────────────────
    (re.compile(r"^(?:high |low |moderate |extreme |pathologic )?myopi(?:a|c)$|^myopic eyes?$"), "myopia"),
    (re.compile(r"^(?:myopic |hyperopic |mixed |high |irregular |residual |corneal )?astigmatism$"), "astigmatism"),
    (re.compile(r"^(?:high )?hyperopi(?:a|c)$|^hypermetropia$"), "hyperopia"),
    (re.compile(r"^presbyopi(?:a|c)$"), "presbyopia"),
    (re.compile(r"^refractive errors?$|^ametropia$"), "refractive error"),
    # ── outcomes and complications ──────────────────────────────────────────
    (re.compile(r"^(?:higher|high)[\s-]order aberrations?(?: \(?hoas?\)?)?$|^hoas?$|^(?:ocular |corneal |optical |wavefront )?aberrations?$|^wavefront aberrations?$"), "higher-order aberrations"),
    (re.compile(r"^dry eyes?(?: disease| syndrome)?(?: \(?ded\)?)?$|^keratoconjunctivitis sicca$|^post-?(?:lasik|refractive surgery) dry eye$"), "dry eye"),
    (re.compile(r"^(?:corneal )?haze$|^subepithelial haze$"), "corneal haze"),
    (re.compile(r"^diffuse lamellar keratitis(?: \(?dlk\)?)?$|^dlk$"), "diffuse lamellar keratitis"),
    (re.compile(r"^epithelial ingrowth$"), "epithelial ingrowth"),
    (re.compile(r"^mitomycin[\s-]?c?$|^mmc$"), "mitomycin C"),
    (re.compile(r"^post-?(?:lasik|refractive(?: surgery)?|surgical|smile|prk|keratorefractive) (?:corneal )?ectasia$"
                r"|^(?:iatrogenic|secondary) (?:corneal )?ectasia$|^ectasia after (?:lasik|refractive surgery|laser in situ keratomileusis|smile|prk)$"
                r"|^(?:corneal )?ectasia$|^keratectasia$|^corneal ectasias$"), CANON_ECTASIA),
    (re.compile(r"^(?:subclinical |forme fruste |progressive )?keratoconus$|^kc$"), "keratoconus"),
    (re.compile(r"^(?:corneal )?(?:collagen )?cross-linking(?: \(?cxl\)?)?$|^(?:corneal )?cxl$|^accelerated cross-linking$"), "corneal cross-linking (CXL)"),
    (re.compile(r"^(?:corneal )?biomechanic\w*$|^corneal hysteresis$|^ocular response analy[sz]er$|^corvis(?: st)?$|^brillouin microscopy$"), CANON_BIOMECH),
    (re.compile(r"^(?:corneal )?topography$|^videokeratograph\w*$|^placido(?: disc| disk)?(?: topography)?$"), CANON_TOPO),
    (re.compile(r"^(?:corneal )?tomography$|^scheimpflug(?: imaging| camera| tomography)?$|^pentacam(?: hr)?$"), CANON_TOMO),
    (re.compile(r"^(?:anterior segment )?(?:optical coherence tomography|oct)$|^as-oct$"), "optical coherence tomography (OCT)"),
    (re.compile(r"^(?:intraocular lens|iol) power(?: calculation)?$|^iol calculation$|^intraocular lens power calculation$"), "IOL power calculation"),
    (re.compile(r"^implantable collamer lens(?: \(?icl\)?)?$|^icl$|^phakic (?:intraocular lens|iol)(?:es|s)?$|^implantable contact lens$"), "phakic IOL / ICL"),
    (re.compile(r"^(?:infectious|fungal|bacterial|microbial|mycobacterial) keratitis$"), "infectious keratitis"),
    # ── data science ────────────────────────────────────────────────────────
    (re.compile(r"^artificial intelligence(?: \(?ai\)?)?$|^ai$"), CANON_AI),
    (re.compile(r"^machine learning$"), CANON_ML),
    (re.compile(r"^deep learning$|^convolutional neural network\w*$|^cnn$"), CANON_DL),
]


def normalize(raw: str) -> str | None:
    """Raw author keyword → canonical term (or None for empty input)."""
    s = _basic(raw)
    if not s:
        return None
    for rx, rep in _FAMILY_PRE:
        s = rx.sub(rep, s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\b(\w+)( \1\b)+", r"\1", s)      # "uva uva" → "uva"
    syn = load_synonyms()
    if s in syn:                                   # table keys may be plural
        return syn[s]
    s = _singular(s)
    if s in syn:
        return syn[s]
    for rx, canon in _FAMILY_POST:
        if rx.search(s):
            return canon
    return s


def coverage_by_year(records: list[dict]) -> list[dict]:
    by: dict[int, list[int]] = {}
    for rec in records:
        try:
            y = int(rec.get("year") or 0)
        except ValueError:
            continue
        if not y:
            continue
        n, k = by.get(y, [0, 0])
        by[y] = [n + 1, k + (1 if rec.get("keywords") else 0)]
    rows = [{"year": y, "n_records": n, "n_with_author_keywords": k,
             "pct": round(100 * k / n, 1) if n else 0.0} for y, (n, k) in sorted(by.items())]
    return rows


def coverage_overall(records: list[dict]) -> dict:
    n = len(records)
    k = sum(1 for r in records if r.get("keywords"))
    return {"n_records": n, "n_with_author_keywords": k, "pct": round(100 * k / n, 1) if n else 0.0}


def record_terms(rec: dict, source: str = "author") -> set[str]:
    """Normalised, de-duplicated terms of one record from the chosen source."""
    raw: list[str] = []
    if source in ("author", "both"):
        raw += rec.get("keywords", []) or []
    if source in ("mesh", "both"):
        raw += rec.get("mesh", []) or []
    out = set()
    for k in raw:
        t = normalize(k) if source != "mesh" else _basic(k)
        if t:
            out.add(t)
    return out


def trends(records: list[dict], terms: list[str], source: str = "author") -> dict:
    """Per-year share (%) of keyword-bearing records that carry each term."""
    cov = {r["year"]: r for r in coverage_by_year(records)}
    counts: dict[str, dict[int, int]] = {t: {} for t in terms}
    for rec in records:
        try:
            y = int(rec.get("year") or 0)
        except ValueError:
            continue
        if not y or not rec.get("keywords"):
            continue
        ts = record_terms(rec, source)
        for t in terms:
            if t in ts:
                counts[t][y] = counts[t].get(y, 0) + 1
    years = sorted(cov)
    return {
        "years": years,
        "denominator": [cov[y]["n_with_author_keywords"] for y in years],
        "n_records": [cov[y]["n_records"] for y in years],
        "counts": {t: [counts[t].get(y, 0) for y in years] for t in terms},
        "share_pct": {t: [round(100 * counts[t].get(y, 0) / cov[y]["n_with_author_keywords"], 1)
                          if cov[y]["n_with_author_keywords"] else None for y in years] for t in terms},
    }


def write_synonyms_export(path: pathlib.Path) -> None:
    path.write_bytes(SYN_PATH.read_bytes())
