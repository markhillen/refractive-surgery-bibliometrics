"""Relevance filter tests for the corneal laser refractive surgery corpus."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import relevance


def _rec(pmid="1", title="", abstract="", journal="", abbr="", mesh=None, issn=""):
    return {"pmid": pmid, "title": title, "abstract": abstract, "journal": journal,
            "journal_abbr": abbr, "mesh": mesh or [], "has_abstract": bool(abstract),
            "issn_linking": issn}


def test_ophthalmic_plastic_journal_is_kept():
    r = _rec(journal="Ophthalmic plastic and reconstructive surgery",
             title="Eyelid changes after LASIK",
             abstract="Ptosis after laser in situ keratomileusis for myopia.")
    d = relevance.classify(r)
    assert d.keep and "ophthalmology_journal" in d.flags


def test_dermatology_excimer_paper_excluded():
    r = _rec(journal="Journal of the American Academy of Dermatology", title="308-nm excimer laser for vitiligo",
             abstract="Excimer laser treatment of vitiligo patches; repigmentation outcomes.")
    d = relevance.classify(r)
    assert not d.keep


def test_optics_paper_without_procedure_excluded():
    r = _rec(journal="Optics letters", title="Bragg gratings in germanium-doped fibres",
             abstract="Gratings written with an excimer laser change the refractive index of the fibre core.")
    d = relevance.classify(r)
    assert not d.keep


def test_ptk_only_excluded_but_ptk_prk_kept():
    r = _rec(journal="Cornea", title="Phototherapeutic keratectomy for recurrent erosion",
             abstract="Excimer laser phototherapeutic keratectomy (PTK) in corneal dystrophy.")
    d = relevance.classify(r)
    assert not d.keep and d.rule_id == "content.ptk_only"
    r2 = _rec(journal="Cornea", title="Combined PTK and PRK",
              abstract="Phototherapeutic keratectomy combined with photorefractive keratectomy for myopia and scarring.")
    assert relevance.classify(r2).keep


def test_no_abstract_in_ophth_journal_kept_with_flag():
    r = _rec(journal="Journal of refractive surgery", title="LASIK flap complications: a letter")
    d = relevance.classify(r)
    assert d.keep and "no_abstract" in d.flags


def test_mesh_only_signal_in_ophth_journal():
    r = _rec(journal="Cornea", title="Tear film after corneal surgery",
             abstract="Tear film osmolarity changed after surgery in the cornea.",
             mesh=["Keratomileusis, Laser In Situ", "Tears"])
    d = relevance.classify(r)
    assert d.keep and "procedure_signal_in_mesh_only" in d.flags


def test_screening_queue_for_ambiguous_non_ophth_journal():
    r = _rec(journal="Journal of biomechanics", title="Stress in the cornea after excimer ablation",
             abstract="Finite element model of the corneal stroma after excimer ablation for myopia.")
    d = relevance.classify(r)
    assert d.keep and "screen" in d.flags and d.stage == "screen"


def test_manual_decision_wins(tmp_path, monkeypatch):
    p = tmp_path / "manual_screening.csv"
    p.write_text("pmid,decision,reason,screened_by,date\n999,exclude,test,MH,2026-10-07\n")
    monkeypatch.setattr(relevance, "MANUAL_PATH", p)
    relevance.reset_manual_cache()
    r = _rec(pmid="999", journal="Cornea", title="LASIK for myopia", abstract="LASIK outcomes.")
    d = relevance.classify(r)
    assert not d.keep and d.stage == "manual"
    relevance.reset_manual_cache()


def test_procedure_in_title_overrides_journal_stoplist():
    r = _rec(journal="Aviation, space, and environmental medicine", title="LASIK in military aviators.")
    d = relevance.classify(r)
    assert d.keep and "disease_in_title" in d.flags
