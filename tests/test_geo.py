import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import geo


def test_uk_not_matched_inside_words():
    assert geo.extract_country(["Department of Ophthalmology, Fukuoka University, Fukuoka, Japan."]) == "Japan"
    assert geo.extract_country(["King George's Medical University, Lucknow, India."]) == "India"
    assert geo.extract_country(["Institute of Clinical Medicine, University of Tsukuba, Japan"]) == "Japan"


def test_country_name_beats_city_hint():
    assert geo.extract_country(["Cambridge Eye Unit, Cambridge, MA, USA"]) == "United States"
    assert geo.extract_country(["Moorfields Eye Hospital, London, UK."]) == "United Kingdom"
    assert geo.extract_country(["Geneva University Hospitals, Geneva, Switzerland."]) == "Switzerland"


def test_first_affiliation_segment_wins():
    # A first author's primary (first-listed) affiliation sets the country;
    # the engine takes the first ";"-segment that yields one (cxl_biblio fix, Sep 2026).
    s = "Department of Ophthalmology, TU Dresden, Germany; ELZA Institute, Zurich, Switzerland."
    assert geo.extract_country([s]) == "Germany"


def test_email_domain_ignored():
    assert geo.extract_country(["ELZA Institute, Zurich, Switzerland. Electronic address: x@ucl.ac.uk"]) == "Switzerland"


def test_unknown_when_nothing():
    assert geo.extract_country(["Department of Ophthalmology."]) == "Unknown"
    assert geo.extract_country([]) == "Unknown"


def test_display_name_folding():
    assert geo.display_name("CZ") == "Czechia"
    assert geo.display_name("Czech Republic") == "Czechia"
    assert geo.display_name("England") == "United Kingdom"
    assert geo.display_name("GB") == "United Kingdom"
    assert geo.display_name("KR") == "South Korea"


def test_enrich_first_author_only_no_journal_fallback():
    recs = [{"pmid": "1", "pub_country": "England",
             "authors": [{"last": "A", "affils": ["Department of Ophthalmology."]},
                         {"last": "B", "affils": ["Wenzhou Medical University, Wenzhou, China"]}]}]
    geo.enrich_countries(recs)
    assert recs[0]["country"] == "Unknown"
    assert recs[0]["authors"][1]["country"] == "China"
    assert recs[0]["countries_all"] == ["China"]


def test_country_name_false_friends():
    import geo
    assert geo.extract_country(["The Eye Institute, Chatswood, New South Wales."]) == "Australia"
    assert geo.extract_country(["Eye Hospital, Fudan University, Shanghai, People's Republic of China."]) == "China"
    assert geo.extract_country(["Chang Gung Memorial Hospital, Taipei, Republic of China"]) == "Taiwan"
    assert geo.extract_country(["Ocni klinika LF UK a FN, Hradec Kralove."]) != "United Kingdom"
    assert geo.extract_country(["Moorfields Eye Hospital, London, UK."]) == "United Kingdom"
