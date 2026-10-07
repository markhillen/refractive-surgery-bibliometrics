"""Parser tests: inline markup, structured abstracts, date precedence, OtherAbstract."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import config
import fetch

XML = """<?xml version="1.0"?>
<PubmedArticleSet>
<PubmedArticle>
 <MedlineCitation Status="MEDLINE" Owner="NLM">
  <PMID Version="1">1001</PMID>
  <Article PubModel="Print-Electronic">
   <Journal><ISSN IssnType="Print">0002-9394</ISSN>
    <JournalIssue CitedMedium="Internet"><Volume>224</Volume>
     <PubDate><Year>2026</Year><Month>Jan</Month></PubDate></JournalIssue>
    <Title>American journal of ophthalmology</Title><ISOAbbreviation>Am J Ophthalmol</ISOAbbreviation></Journal>
   <ArticleTitle>Effect of <i>in vivo</i> corneal cross-linking on K<sub>max</sub> in keratoconus.</ArticleTitle>
   <Abstract>
    <AbstractText Label="PURPOSE">To test riboflavin/UVA <i>in vivo</i> in ultrathin corneas.</AbstractText>
    <AbstractText Label="RESULTS">K<sub>max</sub> fell by 1.2 D (<i>p</i> &lt; 0.01) with wound healing at 12 months.</AbstractText>
   </Abstract>
   <AuthorList><Author ValidYN="Y"><LastName>Seiler</LastName><ForeName>Theo G</ForeName><Initials>TG</Initials>
     <AffiliationInfo><Affiliation>Department of Ophthalmology, <i>Inselspital</i>, Bern, Switzerland.</Affiliation></AffiliationInfo></Author></AuthorList>
   <ArticleDate DateType="Electronic"><Year>2025</Year><Month>11</Month><Day>30</Day></ArticleDate>
  </Article>
  <OtherAbstract Language="fre"><AbstractText>Résumé en français sur le kératocône.</AbstractText></OtherAbstract>
  <MeshHeadingList><MeshHeading><DescriptorName UI="D000094504" MajorTopicYN="Y">Corneal Cross-Linking</DescriptorName></MeshHeading></MeshHeadingList>
  <KeywordList><Keyword MajorTopicYN="N">accelerated <i>CXL</i></Keyword></KeywordList>
 </MedlineCitation>
 <PubmedData><History><PubMedPubDate PubStatus="pubmed"><Year>2025</Year></PubMedPubDate></History>
  <ArticleIdList><ArticleId IdType="doi">10.1000/test.1001</ArticleId></ArticleIdList></PubmedData>
</PubmedArticle>
<PubmedArticle>
 <MedlineCitation Status="MEDLINE" Owner="NLM">
  <PMID Version="1">1002</PMID>
  <Article PubModel="Print">
   <Journal><JournalIssue CitedMedium="Print"><PubDate><MedlineDate>2003 Jan-Feb</MedlineDate></PubDate></JournalIssue>
    <Title>Cornea</Title></Journal>
   <ArticleTitle>Riboflavin/UVA collagen crosslinking for keratoconus.</ArticleTitle>
   <AuthorList><Author><LastName>Seiler</LastName><ForeName>Theo</ForeName><Initials>T</Initials></Author></AuthorList>
  </Article>
 </MedlineCitation>
 <PubmedData><History><PubMedPubDate PubStatus="pubmed"><Year>2004</Year></PubMedPubDate></History></PubmedData>
</PubmedArticle>
</PubmedArticleSet>
"""


def _parse():
    return {r["pmid"]: r for r in fetch._parse_pubmed_xml(XML)}


def test_inline_markup_is_kept():
    r = _parse()["1001"]
    assert r["title"] == "Effect of in vivo corneal cross-linking on Kmax in keratoconus."
    assert "Kmax fell by 1.2 D (p < 0.01) with wound healing at 12 months." in r["abstract"]
    assert r["abstract"].startswith("PURPOSE: To test riboflavin/UVA in vivo")
    assert r["keywords"] == ["accelerated CXL"]
    assert r["authors"][0]["affils"] == ["Department of Ophthalmology, Inselspital, Bern, Switzerland."]
    assert r["mesh"] == ["Corneal Cross-Linking"]
    assert r["mesh_major"] == ["Corneal Cross-Linking"]


def test_other_abstract_kept_separately():
    r = _parse()["1001"]
    assert "kératocône" not in r["abstract"]
    assert "kératocône" in r["other_abstract"]
    assert r["has_abstract"] is True


def test_year_earliest_rule(monkeypatch):
    monkeypatch.setattr(config, "YEAR_RULE", "earliest")
    r = _parse()["1001"]
    assert r["year_issue"] == "2026"
    assert r["year_epub"] == "2025"
    assert r["year_pubmed_entry"] == "2025"
    assert r["year"] == "2025"


def test_year_issue_rule(monkeypatch):
    monkeypatch.setattr(config, "YEAR_RULE", "issue")
    r = _parse()["1001"]
    assert r["year"] == "2026"


def test_medlinedate_is_parsed():
    r = _parse()["1002"]
    assert r["year_issue"] == "2003"
    assert r["year"] == "2003"          # not the 2004 PubMed entry date
    assert r["has_abstract"] is False
    assert r["authors"][0]["initials"] == "T"


def test_year_window_split():
    recs = list(_parse().values())
    inside, outside = fetch.check_year_window(recs, 2001, 2025)
    assert {r["pmid"] for r in inside} == {"1001", "1002"}
    assert outside == []
    inside, outside = fetch.check_year_window(recs, 2001, 2024)
    assert {r["pmid"] for r in outside} == {"1001"}
