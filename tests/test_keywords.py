"""Keyword normalisation tests for the refractive surgery map."""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import keywords as K


def test_lasik_family():
    for v in ["LASIK", "FS-LASIK", "femtosecond laser-assisted in situ keratomileusis",
              "Laser in situ keratomileusis (LASIK)", "laser-assisted in situ keratomileusis"]:
        assert K.normalize(v) == K.CANON_LASIK, v


def test_lenticule_family():
    for v in ["SMILE", "ReLEx SMILE", "small-incision lenticule extraction", "KLEx",
              "keratorefractive lenticule extraction", "SMILE Pro"]:
        assert K.normalize(v) == K.CANON_LENT, v


def test_surface_ablation_family():
    assert K.normalize("PRK") == K.CANON_PRK
    assert K.normalize("photorefractive keratectomy") == K.CANON_PRK
    assert K.normalize("TransPRK") == K.CANON_TPRK
    assert K.normalize("transepithelial photorefractive keratectomy") == K.CANON_TPRK
    assert K.normalize("epi-LASIK") == K.CANON_LASEK


def test_outcomes_and_case():
    assert K.normalize("Dry Eye Disease") == "dry eye"
    assert K.normalize("higher-order aberrations") == "higher-order aberrations"
    assert K.normalize("post-LASIK ectasia") == K.CANON_ECTASIA
    assert K.normalize("refractive surgery") in K.SEARCH_TERM_CANONICALS
