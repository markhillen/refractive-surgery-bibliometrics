"""
relevance.py — corpus relevance filter with a complete, reproducible exclusion log
==================================================================================

Decides, for every record the PubMed query returns, whether it belongs in the
corneal laser refractive surgery corpus.  Every decision — kept or excluded — is
written to ``output/exclusion_log.csv`` with the stage, rule id and the string
that matched, so the log can be published as supplemental content and
re-screened by hand.

Decision order (first stage that decides wins):

  0. manual     data/manual_screening.csv — hand decisions, always win
  1. allowlist  ophthalmology / vision-science journal → skip journal exclusions
  2. journal    word-bounded stop-patterns on the journal title (non-allowlisted
                journals whose title does not name the disease) -> queued for
                screening, excluded unless screened in
  3. mesh       non-ophthalmic MeSH, only when NO corneal/ocular MeSH is present
                and the title does not name the disease -> queued, as above
  4. content    title + abstract must carry a laser refractive procedure signal AND an ophthalmic term;
                phototherapeutic keratectomy (PTK) with no refractive signal is excluded
  5. screen     survivors in non-ophthalmology journals lacking a disease/agent
                term are kept but queued for manual screening
                (output/screening_queue.csv); --strict-screening makes an
                undecided queue an error.

The earlier filter matched bare substrings ("plastic" removed *Ophthalmic
Plastic and Reconstructive Surgery*; "oral" hit *Behavioral*), excluded on a
single MeSH heading regardless of corneal context, and tested a title/abstract
string that the XML parser had truncated at the first inline tag — which is
how records containing "corneal" seven times were logged as having no
ophthalmic term.
"""

from __future__ import annotations

import csv
import dataclasses
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import config

MANUAL_PATH = pathlib.Path(config.DATA_DIR) / "manual_screening.csv"


@dataclasses.dataclass
class Decision:
    keep: bool
    stage: str
    rule_id: str = ""
    detail: str = ""
    flags: list[str] = dataclasses.field(default_factory=list)


# ── 0. manual decisions ───────────────────────────────────────────────────────

_manual_cache: dict[str, dict] | None = None


def load_manual(path: pathlib.Path | None = None) -> dict[str, dict]:
    global _manual_cache
    if _manual_cache is not None:
        return _manual_cache
    path = path or MANUAL_PATH
    out: dict[str, dict] = {}
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                pmid = (row.get("pmid") or "").strip()
                if pmid and (row.get("decision") or "").strip():
                    out[pmid] = {k: (v or "").strip() for k, v in row.items()}
    _manual_cache = out
    return out


def reset_manual_cache() -> None:
    global _manual_cache
    _manual_cache = None


# ── 1. journal allow-list ─────────────────────────────────────────────────────

# Ophthalmology / vision-science journal titles (matched on title and ISO abbr).
_ALLOW_RE = re.compile(
    r"\b(ophthalm|ophtalm|oftalm|augenheilk|augenärzt|cornea|corneal|"
    r"eye|eyes|ocul|vision|vis(?:ual)?\s*sci|optom|refract|cataract|kerato|"
    r"retina|retinal|glaucoma|strabism|oculoplast|orbit|contact\s+lens|"
    r"klin(?:ische)?\s+monatsbl|graefe|vestn(?:ik)?\s+oftalm|arq(?:uivos)?\s+bras(?:ileiros)?\s+de\s+oftalm|"
    r"ocular\s+surface|acta\s+ophthalmol|jama\s+ophthalmol|br(?:itish)?\s+j(?:ournal)?\s+ophthalmol|"
    r"ganka|augen|oftalmol|ophtalmol)",
    re.I,
)
# ISSN-L values for journals whose titles do not carry an obvious ophthalmic word.
_ALLOW_ISSN = {
    "0146-0404",  # Invest Ophthalmol Vis Sci (title has it, belt and braces)
    "2164-2591",  # Transl Vis Sci Technol
    "1542-0124",  # Ocul Surf
    "1367-0484",  # Cont Lens Anterior Eye
    "0721-832X",  # Graefes Arch
    "1120-6721",  # Eur J Ophthalmol
    "0023-2165",  # Klin Monbl Augenheilkd
    "0042-465X",  # Vestn Oftalmol
    "0004-2749",  # Arq Bras Oftalmol
}


def is_allowlisted(rec: dict) -> bool:
    j = f"{rec.get('journal','')} {rec.get('journal_abbr','')}"
    if _ALLOW_RE.search(j):
        return True
    issn = rec.get("issn_linking") or rec.get("issn") or ""
    return issn in _ALLOW_ISSN


# ── 2. journal stop-patterns (word-bounded) ───────────────────────────────────

_JOURNAL_RULES: list[tuple[str, re.Pattern]] = [(rid, re.compile(rx, re.I)) for rid, rx in [
    ("journal.plastic",       r"\bplastic\b"),
    ("journal.aesthetic",     r"\baesthetic"),
    ("journal.rhinoplasty",   r"\brhinoplast"),
    ("journal.reconstructive",r"\breconstructive surg"),
    ("journal.surgery_general", r"\bannals of surgery\b"),
    ("journal.dental",        r"\bdental\b|\bdentist|\bdent\b"),
    ("journal.oral",          r"\boral\b"),
    ("journal.maxillofacial", r"\bmaxillofac"),
    ("journal.orthodont",     r"\borthodont"),
    ("journal.endodont",      r"\bendodont"),
    ("journal.periodont",     r"\bperiodont"),
    ("journal.biomaterials",  r"\bbiomaterial"),
    ("journal.polymer",       r"\bpolymer"),
    ("journal.hydrogel",      r"\bhydrogel"),
    ("journal.tissue_eng",    r"\btissue engineering\b"),
    ("journal.wound",         r"\bwound repair\b|\bwound care\b|\bwounds\b"),
    ("journal.cartilage",     r"\bcartilage\b"),
    ("journal.bone",          r"\bbone\b|\bbones\b"),
    ("journal.spine",         r"\bspine\b|\bspinal\b"),
    ("journal.orthop",        r"\borthop(?!t)"),           # orthopaedic, not orthoptic
    ("journal.dermatol",      r"\bdermatol"),
    ("journal.skin",          r"\bskin\b"),
    ("journal.vascular",      r"\bvascular\b"),
    ("journal.cardio",        r"\bcardio"),
    ("journal.thoracic",      r"\bthoracic\b"),
    ("journal.urology",       r"\burolog"),
    ("journal.gyn",           r"\bgyn(?:a)?ecol|\bobstet"),
    ("journal.hepatol",       r"\bhepatol"),
    ("journal.gastro",        r"\bgastroenter"),
    ("journal.neurosurg",     r"\bneurosurg"),
    ("journal.neurol",        r"\bneurol(?!.*ophthalm)"),
    ("journal.psychiatr",     r"\bpsychiatr"),
    ("journal.oncol",         r"\boncol"),
    ("journal.hematol",       r"\bh(?:a)?ematol"),
    ("journal.endocrinol",    r"\bendocrinol"),
    ("journal.nephrol",       r"\bnephrol"),
    ("journal.pulmonol",      r"\bpulmonol|\brespirat"),
]]


# ── 3. MeSH exclusions, conditional on no corneal/ocular MeSH ─────────────────

_MESH_RULES: list[tuple[str, re.Pattern]] = [(rid, re.compile(rx, re.I)) for rid, rx in [
    ("mesh.rhinoplasty",      r"^rhinoplasty$"),
    ("mesh.plastic_surgery",  r"^surgery, plastic$|^plastic surgery"),
    ("mesh.reconstructive",   r"^reconstructive surgical procedures$"),
    ("mesh.skin_transplant",  r"^skin transplantation$"),
    ("mesh.cartilage",        r"^cartilage"),
    ("mesh.bone",             r"^bone and bones$|^bone "),
    ("mesh.dental",           r"^dental |^dentin$|^tooth|^periodont|^orthodont"),
    ("mesh.tissue_scaffolds", r"^tissue scaffolds$|^tissue engineering$"),
    ("mesh.cardiovascular",   r"^cardiovascular|^aorta"),
    ("mesh.blood_vessels",    r"^blood vessels$"),
]]

_OCULAR_MESH_RE = re.compile(
    r"^(cornea|corneal|keratocon|keratitis|keratectas|eye\b|ocular|ophthalm|"
    r"vision|visual acuity|refractive|dilatation, pathologic|contact lens|"
    r"photorefractive|keratomileusis|keratectomy|myopia|hyperopia|astigmatism|presbyopia|"
    r"refractive errors|refractive surgical|corneal surgery|"
    r"riboflavin|cross-linking reagents|photochemotherapy|photosensitizing)",
    re.I,
)


def _has_ocular_mesh(mesh: list[str]) -> bool:
    return any(_OCULAR_MESH_RE.search(m or "") for m in mesh)


# ── 4. content ────────────────────────────────────────────────────────────────

# Laser refractive procedure signal.  Bare "PRK" is also protein kinase R/PKN
# shorthand in molecular biology, so it counts only next to an ophthalmic term
# (enforced by the separate ophthalmic-term test below).
_CXL_SIGNAL_RE = re.compile(      # name kept for the shared engine; carries the refractive-surgery signal
    r"\b(lasik|femto-?lasik|fs-?lasik|sbk|laser in situ keratomileusis|laser-assisted in situ keratomileusis|"
    r"keratomileusis|photorefractive keratectom\w*|prk|lasek|epi-?lasik|laser (?:sub)?epithelial keratomileusis|"
    r"surface ablation|advanced surface ablation|laser[\s-]assisted subepithelial keratectomy|small[\s-]incision lenticule extraction|lenticule extraction|"
    r"refractive lenticule|smile|relex|flex|klex|smartsight|clear procedure|trans-?prk|transepithelial (?:photorefractive|prk|surface)|"
    r"laser vision correction|laser refractive|corneal refractive surgery|keratorefractive|refractive surgery|"
    r"excimer|wavefront[\s-](?:guided|optimi[sz]ed)|topography[\s-]guided|presbylasik|presbyond|"
    r"microkeratome|femtosecond laser flap|lasik flap|flap creation|refractive (?:laser|ablation)|"
    r"intracor|intrastromal femtosecond|small incision lens extraction)\b",
    re.I,
)
_OPHTH_RE = re.compile(
    r"\b(cornea|corneal|corneas|keratocon|ectasi|ectatic|keratitis|keratocyte|stroma|stromal|"
    r"keratometr|pachymetr|topograph|tomograph|scheimpflug|visual acuity|slit[\s-]?lamp|intraocular|"
    r"ophthalm|ocular|\beye\b|\beyes\b|retina|lasik|photorefractive|refractive(?!\s+ind(?:ex|ices))|myopi\w*|hyperop\w*|"
    r"astigmat\w*|presbyop\w*|ametrop\w*|endotheli|epitheli|limb(?:us|al)|conjunctiv|sclera|"
    r"dry eye|tear film|diopt\w*|aberration|vision|eyeglass\w*|spectacle\w*|glasses)",
    re.I,
)
# A procedure term specific enough that a record in a non-ophthalmology journal
# is unambiguous.  Absent → screening queue.
_DISEASE_AGENT_RE = re.compile(
    r"\b(lasik|femto-?lasik|laser in situ keratomileusis|laser-assisted in situ keratomileusis|"
    r"photorefractive keratectom\w*|lasek|epi-?lasik|laser (?:sub)?epithelial keratomileusis|"
    r"small[\s-]incision lenticule extraction|lenticule extraction|relex|klex|smartsight|trans-?prk|"
    r"laser vision correction|laser refractive surg\w*|corneal refractive surg\w*|keratorefractive surg\w*|"
    r"presbylasik|presbyond)\b",
    re.I,
)
# MeSH headings that carry the procedure when it is absent from title,
# abstract and author keywords (records retrieved through the MeSH arm).
_MESH_CXL_SIGNAL_RE = re.compile(
    r"^keratomileusis, laser in situ$|^photorefractive keratectomy$|"
    r"^keratectomy, subepithelial, laser-assisted$|^corneal surgery, laser$|^refractive surgical procedures$",
    re.I,
)
# Phototherapeutic keratectomy shares the excimer platform and the PRK MeSH
# heading but is a therapeutic, not a refractive, procedure.
_PTK_RE = re.compile(r"\b(phototherapeutic keratectom\w*|ptk)\b", re.I)
# Refractive signal that is not merely the platform ("excimer"), used to keep
# PTK papers that also treat refractive error (PTK/PRK combinations).
_REFRACTIVE_NOT_PLATFORM_RE = re.compile(
    r"\b(lasik|keratomileusis|photorefractive|prk|lasek|subepithelial keratectomy|lenticule|smile|relex|klex|refractive surg\w*|"
    r"laser vision correction|myopi\w*|hyperop\w*|astigmat\w*|refractive error)\b",
    re.I,
)


def _first_match(rx: re.Pattern, text: str) -> str:
    m = rx.search(text)
    return m.group(0) if m else ""


# ── classify ──────────────────────────────────────────────────────────────────

def classify(rec: dict) -> Decision:
    pmid = str(rec.get("pmid", "") or "")
    manual = load_manual().get(pmid)
    if manual:
        dec = manual["decision"].lower()
        keep = dec in ("include", "keep", "in")
        who = manual.get("screened_by", "")
        return Decision(keep, "manual", "manual." + ("include" if keep else "exclude"),
                        f"{manual.get('reason','')} [{who} {manual.get('date','')}]".strip())

    # Errata and retraction notices are notices about a publication, not
    # publications; the corrected or retracted article is counted itself.
    ptypes = set(rec.get("pub_types") or [])
    if ptypes & {"Published Erratum", "Retraction of Publication"}:
        return Decision(False, "content", "content.notice_not_publication",
                        "; ".join(sorted(ptypes & {"Published Erratum", "Retraction of Publication"})), [])

    title    = rec.get("title", "") or ""
    abstract = rec.get("abstract", "") or ""
    journal  = f"{rec.get('journal','')} {rec.get('journal_abbr','')}"
    mesh     = rec.get("mesh", []) or []
    combined = f"{title} {abstract}"
    flags: list[str] = []

    allow = is_allowlisted(rec)
    # A record whose TITLE names a laser refractive procedure is about it
    # wherever it was published (LASIK in aviation or military medicine
    # journals, PRK in sports medicine).  The journal and MeSH stop-lists, which the CXL
    # engine uses to remove cross-linking of skin, tendon and polymers, are
    # therefore applied only when the title does not name the disease, and even
    # then they queue the record for screening rather than excluding it outright.
    title_names_disease = bool(_DISEASE_AGENT_RE.search(title))
    if title_names_disease:
        flags.append("disease_in_title")
    if allow:
        flags.append("ophthalmology_journal")
    elif not title_names_disease:
        for rid, rx in _JOURNAL_RULES:
            m = rx.search(journal)
            if m:
                return Decision(False, "screen", "screen.stoplist_" + rid, m.group(0), flags + ["screen"])

    if not title_names_disease and not _has_ocular_mesh(mesh):
        for rid, rx in _MESH_RULES:
            hit = next((mm for mm in mesh if rx.search(mm or "")), None)
            if hit:
                return Decision(False, "screen", "screen.stoplist_" + rid, hit, flags + ["screen"])

    if not rec.get("has_abstract", bool(abstract)):
        flags.append("no_abstract")

    kw_text = " ".join((rec.get("keywords", []) or []) + (rec.get("keywords_nlm", []) or []))
    sig = _first_match(_CXL_SIGNAL_RE, combined)
    oph = _first_match(_OPHTH_RE, combined)
    ocular_mesh = _has_ocular_mesh(mesh)

    if not sig:
        # PubMed's [tiab] also indexes author keywords, and the query has a MeSH
        # arm, so a record can be retrieved without the term in title/abstract.
        if _CXL_SIGNAL_RE.search(kw_text):
            sig = _first_match(_CXL_SIGNAL_RE, kw_text)
            flags.append("procedure_signal_in_keywords_only")
        elif (allow or ocular_mesh) and any(_MESH_CXL_SIGNAL_RE.search(mm or "") for mm in mesh):
            sig = next(mm for mm in mesh if _MESH_CXL_SIGNAL_RE.search(mm or ""))
            flags.append("no_procedure_signal_in_text")
            flags.append("procedure_signal_in_mesh_only")
        else:
            return Decision(False, "content", "content.no_procedure_signal",
                            "no laser refractive procedure term in title, abstract or keywords", flags)

    if not oph:
        if title_names_disease:
            # the title names a laser refractive procedure: that is ophthalmic
            flags.append("ophthalmic_term_absent_title_names_procedure")
        elif allow and sig:
            # Letters/editorials without abstracts in ophthalmology journals
            flags.append("ophthalmic_term_absent_journal_vouches")
        elif ocular_mesh and sig:
            flags.append("ophthalmic_term_absent_mesh_vouches")
        elif _OPHTH_RE.search(kw_text) and sig:
            flags.append("ophthalmic_term_in_keywords_only")
        else:
            return Decision(False, "content", "content.no_ophthalmic_term",
                            "no ophthalmic term in title, abstract, keywords or MeSH", flags)

    # Only when the TITLE names PTK: excimer wound-healing studies often mention
    # PTK in passing while studying the PRK problem (haze, keratocyte loss).
    if _PTK_RE.search(title) and not _REFRACTIVE_NOT_PLATFORM_RE.search(combined):
        return Decision(False, "content", "content.ptk_only",
                        "phototherapeutic keratectomy with no refractive procedure or refractive error term", flags)

    if not allow and not _DISEASE_AGENT_RE.search(combined):
        flags.append("screen")
        return Decision(True, "screen", "screen.non_ophth_journal_no_disease_term",
                        f"signal='{sig}' ophth='{oph}'", flags)

    return Decision(True, "keep", "keep.content", f"signal='{sig}' ophth='{oph}'", flags)


# ── filter + log ──────────────────────────────────────────────────────────────

LOG_FIELDS = ["pmid", "year", "journal", "title", "decision", "stage", "rule_id",
              "detail", "flags"]


def filter_records(records: list[dict], write_log: bool = True,
                   strict_screening: bool = False) -> list[dict]:
    """Apply classify() to every record; write exclusion_log.csv, exclusion_summary.csv
    and screening_queue.csv under config.OUTPUT_DIR."""
    reset_manual_cache()
    kept, rows, queue = [], [], []
    summary: dict[str, int] = {}
    for rec in records:
        d = classify(rec)
        rec["relevance"] = {"keep": d.keep, "stage": d.stage, "rule": d.rule_id, "flags": d.flags}
        rows.append({
            "pmid": rec.get("pmid", ""), "year": rec.get("year", ""),
            "journal": rec.get("journal", ""), "title": (rec.get("title", "") or "")[:200],
            "decision": "keep" if d.keep else "exclude", "stage": d.stage,
            "rule_id": d.rule_id, "detail": d.detail, "flags": ";".join(d.flags),
        })
        key = f"{'keep' if d.keep else 'exclude'}:{d.stage}:{d.rule_id}"
        summary[key] = summary.get(key, 0) + 1
        if d.keep:
            kept.append(rec)
        if "screen" in d.flags:
            queue.append(rows[-1])

    n_ex = len(records) - len(kept)
    print(f"[filter] {len(kept)} records retained, {n_ex} excluded, "
          f"{len(queue)} queued for manual screening")
    for k, v in sorted(summary.items(), key=lambda kv: -kv[1]):
        print(f"  [filter]   {v:5d}  {k}")

    if write_log:
        out = pathlib.Path(config.OUTPUT_DIR)
        out.mkdir(parents=True, exist_ok=True)
        with open(out / "exclusion_log.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=LOG_FIELDS); w.writeheader(); w.writerows(rows)
        with open(out / "exclusion_summary.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh); w.writerow(["decision", "stage", "rule_id", "n"])
            for k, v in sorted(summary.items(), key=lambda kv: -kv[1]):
                w.writerow(k.split(":") + [v])
        with open(out / "screening_queue.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=LOG_FIELDS); w.writeheader(); w.writerows(queue)

    if strict_screening and queue:
        raise SystemExit(f"[filter] {len(queue)} records await manual screening "
                         f"(see output/screening_queue.csv); add decisions to "
                         f"{MANUAL_PATH} or run without --strict-screening")
    return kept
