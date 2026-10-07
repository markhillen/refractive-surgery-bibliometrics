import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import institutions as I


def test_dresden_variants_merge():
    for s in ["Department of Ophthalmology, University Hospital Carl Gustav Carus, TU Dresden, Dresden, Germany.",
              "Klinik und Poliklinik für Augenheilkunde, Universitätsklinikum Carl Gustav Carus, Dresden, Germany",
              "Department of Ophthalmology, Technische Universität Dresden, Germany",
              "Augenklinik, Dresden, Germany"]:
        r = I.resolve(s)
        assert r.canonical == "TU Dresden / University Hospital Carl Gustav Carus", (s, r)
        assert r.parent == "TU Dresden"


def test_siena_and_zurich_cluster():
    assert I.resolve("Siena Crosslinking Center, Siena, Italy").parent == "University of Siena"
    assert I.resolve("Department of Medicine, Surgery and Neurosciences, University of Siena, Italy").canonical == "University of Siena"
    z = I.resolve("ELZA Institute, Dietikon, Switzerland")
    assert z.canonical == "ELZA Institute" and z.cluster == "zurich_cluster"
    u = I.resolve("Laboratory for Ocular Cell Biology, CABMM, University of Zurich, Zurich, Switzerland")
    assert u.canonical == "University of Zurich" and u.cluster == "zurich_cluster"
    assert I.resolve("Universitätsspital Zürich, Zürich, Switzerland").at("parent") == "University of Zurich"


def test_mee_is_not_hand_merged_with_harvard():
    r = I.resolve("Massachusetts Eye and Ear, Harvard Medical School, Boston, MA, USA")
    assert r.canonical == "Massachusetts Eye and Ear"
    assert r.parent == "Harvard Medical School"
    assert I.resolve("Harvard Medical School, Boston, MA").canonical == "Harvard Medical School"


def test_primary_vs_all():
    a = {"affils": ["ELZA Institute, Dietikon, Switzerland; Faculty of Medicine, University of Geneva, Geneva, Switzerland."]}
    res = I.author_institutions(a, "Hafezi")
    assert [r.canonical for r in res] == ["ELZA Institute", "University of Geneva"]
    assert I.primary_institution(a, "Hafezi").canonical == "ELZA Institute"


def test_competition_ranks():
    assert I.competition_ranks([30, 29, 29, 28]) == ["1", "=2", "=2", "4"]
