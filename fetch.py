"""
fetch.py — PubMed retrieval via NCBI E-utilities
=================================================
Downloads all corneal laser refractive surgery records, keeps the raw PubMed XML on disk so that every later
parser or filter change can be re-run offline (``main.py --reparse``), and
caches the parsed records as JSON.

Run standalone:  python3 fetch.py [--api-key YOUR_KEY] [--refresh]

Cache layout (``config.CACHE_DIR``):

    pubmed_xml/<corpus_id>/batch_NNNN.xml   raw efetch responses, one per batch
    records_raw.json                        every parsed record, before filtering
    records.json                            records retained by the relevance filter
    year_window_excluded.json               records whose year fell outside the window
    manifest.json                           what produced the cache (schema, query, dates)
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

# ── allow running standalone or imported ─────────────────────────────────────
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import config

BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"

# NCBI rejects efetch retstart >= this value even with usehistory=y.
_NCBI_EFETCH_LIMIT = 9_999


# ── HTTP ──────────────────────────────────────────────────────────────────────

def _get(url: str, retries: int = config.MAX_RETRIES) -> str:
    """HTTP GET with retry/back-off."""
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001 — network errors of any kind
            wait = 2 ** attempt
            print(f"  [warn] GET failed ({e}), retry {attempt+1}/{retries} in {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"Failed to fetch: {url[:120]}")


def _delay(api_key: str) -> float:
    return config.REQUEST_DELAY if api_key else 0.34


# ── esearch ───────────────────────────────────────────────────────────────────

def esearch(query: str, api_key: str = "") -> tuple[str, str, int]:
    """
    Post query to PubMed history server.
    Returns (WebEnv, query_key, total_count).
    Using usehistory=y avoids the 10 000-PMID cap on direct ID retrieval.
    """
    params = {
        "db":         "pubmed",
        "term":       query,
        "retmax":     "0",
        "retmode":    "json",
        "usehistory": "y",
    }
    if api_key:
        params["api_key"] = api_key
    url = BASE_URL + "esearch.fcgi?" + urllib.parse.urlencode(params)
    print("[esearch] Querying PubMed …")
    data    = json.loads(_get(url))
    result  = data["esearchresult"]
    total   = int(result["count"])
    webenv  = result["webenv"]
    qkey    = result["querykey"]
    print(f"[esearch] Found {total} records (WebEnv history server, query_key={qkey})")
    return webenv, qkey, total


def esearch_count(query: str, api_key: str = "") -> int:
    """Return only the hit count for a query (used by validation and benchmarks)."""
    params = {"db": "pubmed", "term": query, "retmax": "0", "retmode": "json"}
    if api_key:
        params["api_key"] = api_key
    url = BASE_URL + "esearch.fcgi?" + urllib.parse.urlencode(params)
    data = json.loads(_get(url))
    time.sleep(_delay(api_key))
    return int(data["esearchresult"]["count"])


def esearch_ids(query: str, api_key: str = "") -> list[str]:
    """
    Return the complete PMID list for a query, in PubMed's default (relevance-
    independent, most-recent-first) order.  Chunks by year when the count
    exceeds NCBI's 10 000-ID ceiling for a single request.
    """
    def _one(q: str) -> list[str]:
        params = {"db": "pubmed", "term": q, "retmax": "10000", "retmode": "json"}
        if api_key:
            params["api_key"] = api_key
        url = BASE_URL + "esearch.fcgi?" + urllib.parse.urlencode(params)
        data = json.loads(_get(url))["esearchresult"]
        time.sleep(_delay(api_key))
        return list(data.get("idlist", [])), int(data.get("count", 0))

    ids, count = _one(query)
    if count <= 10_000:
        return ids
    print(f"[esearch] {count} ids > 10 000; collecting by year …")
    out: list[str] = []
    seen: set[str] = set()
    for yr in range(config.ALL_TIME_START, config.END_YEAR + 1):
        chunk, _ = _one(_query_for_years(yr, yr))
        for p in chunk:
            if p not in seen:
                seen.add(p); out.append(p)
    return out


def _query_for_years(start_yr: int, end_yr: int) -> str:
    """Rebuild the query with a narrower date window for chunked fetching."""
    base = getattr(config, "PUBMED_QUERY_BASE", None)
    if base is None:  # legacy config without the split
        base = config.PUBMED_QUERY.rsplit(' AND (', 1)[0]
    return f'({base}) AND ("{start_yr}/01/01"[PDAT] : "{end_yr}/12/31"[PDAT])'


# ── efetch with raw-XML persistence ───────────────────────────────────────────

def corpus_id_for_query(query: str) -> str:
    return "q_" + hashlib.sha1(query.encode("utf-8")).hexdigest()[:12]


def corpus_id_for_pmids(pmids: list[str]) -> str:
    return "p_" + hashlib.sha1("\n".join(sorted(pmids)).encode("utf-8")).hexdigest()[:12]


def xml_dir(corpus_id: str) -> pathlib.Path:
    d = pathlib.Path(config.CACHE_DIR) / "pubmed_xml" / corpus_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_batch(xdir: pathlib.Path | None, idx: int, xml_text: str) -> None:
    if xdir is None:
        return
    (xdir / f"batch_{idx:04d}.xml").write_text(xml_text, encoding="utf-8")


def efetch_from_history(webenv: str, query_key: str, total: int,
                        api_key: str = "", xdir: pathlib.Path | None = None,
                        batch_offset: int = 0) -> list[dict]:
    """Fetch all records stored on the NCBI history server in batches."""
    records    = []
    batch_size = config.BATCH_SIZE
    delay      = _delay(api_key)

    for n, retstart in enumerate(range(0, total, batch_size)):
        end = min(retstart + batch_size, total)
        pct = end / total * 100
        print(f"  fetching records {retstart+1}–{end} / {total}  ({pct:.1f}%)", end="\r")

        params = {
            "db":        "pubmed",
            "query_key": query_key,
            "WebEnv":    webenv,
            "retstart":  retstart,
            "retmax":    batch_size,
            "rettype":   "xml",
            "retmode":   "xml",
        }
        if api_key:
            params["api_key"] = api_key
        url = BASE_URL + "efetch.fcgi?" + urllib.parse.urlencode(params)
        xml_text = _get(url)
        _save_batch(xdir, batch_offset + n, xml_text)
        records.extend(_parse_pubmed_xml(xml_text))
        time.sleep(delay)

    print(f"\n[efetch] Parsed {len(records)} records from history server")
    return records


def efetch_batch(pmids: list[str], api_key: str = "",
                 xdir: pathlib.Path | None = None) -> list[dict]:
    """Fetch full records for a list of PMIDs in batches."""
    records = []
    total = len(pmids)
    batch_size = config.BATCH_SIZE
    delay = _delay(api_key)

    for n, i in enumerate(range(0, total, batch_size)):
        batch = pmids[i: i + batch_size]
        pct = (i + len(batch)) / total * 100
        print(f"  fetching records {i+1}–{i+len(batch)} / {total}  ({pct:.1f}%)", end="\r")

        params = {
            "db": "pubmed",
            "id": ",".join(batch),
            "rettype": "xml",
            "retmode": "xml",
        }
        if api_key:
            params["api_key"] = api_key
        url = BASE_URL + "efetch.fcgi?" + urllib.parse.urlencode(params)
        xml_text = _get(url)
        _save_batch(xdir, n, xml_text)
        records.extend(_parse_pubmed_xml(xml_text))
        time.sleep(delay)

    print(f"\n[efetch] Parsed {len(records)} records")
    return records


def parse_cached_xml(corpus_id: str) -> list[dict]:
    """Re-parse every stored efetch batch for a corpus without touching the network."""
    xdir = pathlib.Path(config.CACHE_DIR) / "pubmed_xml" / corpus_id
    files = sorted(xdir.glob("batch_*.xml"))
    if not files:
        raise FileNotFoundError(f"no cached XML under {xdir}")
    records: list[dict] = []
    seen: set[str] = set()
    for f in files:
        for rec in _parse_pubmed_xml(f.read_text(encoding="utf-8")):
            pmid = rec.get("pmid")
            if pmid and pmid in seen:
                continue
            if pmid:
                seen.add(pmid)
            records.append(rec)
    print(f"[reparse] {len(records)} records from {len(files)} cached XML batches ({corpus_id})")
    return records


# ── XML parsing ───────────────────────────────────────────────────────────────

def _itertext(node) -> str:
    """Full text of an element including text inside inline children
    (<i>, <b>, <sub>, <sup> …).  ElementTree's .text stops at the first child."""
    if node is None:
        return ""
    return "".join(node.itertext()).strip()


def _text(elem, path, default=""):
    node = elem.find(path)
    return _itertext(node) if node is not None else default


_YEAR_RE = re.compile(r"(19|20)\d{2}")


def _year_of(node) -> str:
    """Year from a date-like element: <Year>, else first 4-digit year in <MedlineDate>."""
    if node is None:
        return ""
    y = _text(node, "Year")
    if y:
        return y
    md = _text(node, "MedlineDate")
    m = _YEAR_RE.search(md)
    return m.group(0) if m else ""


def _extract_year(article) -> dict:
    """
    Publication year under three definitions, plus the one selected by
    config.YEAR_RULE:

      year_issue         Journal/JournalIssue/PubDate (Year or MedlineDate) — the
                         issue (print) date.
      year_epub          ArticleDate[@DateType='Electronic'] — online-first date.
      year_pubmed_entry  PubMedPubDate[@PubStatus='pubmed'] — the date the record
                         entered PubMed (what earlier versions of this pipeline
                         used, which is not a publication date).

    YEAR_RULE = "earliest" → min(issue, epub) when both exist (matches the
    behaviour of PubMed's own [PDAT] filter, which accepts either date);
    "issue" → issue year, falling back to epub, then PubMed entry.
    """
    issue_node = article.find("MedlineCitation/Article/Journal/JournalIssue/PubDate")
    epub_node  = article.find("MedlineCitation/Article/ArticleDate[@DateType='Electronic']")
    if epub_node is None:
        epub_node = article.find("MedlineCitation/Article/ArticleDate")
    entry_node = article.find(".//PubMedPubDate[@PubStatus='pubmed']")

    y_issue = _year_of(issue_node)
    y_epub  = _text(epub_node, "Year") if epub_node is not None else ""
    y_entry = _text(entry_node, "Year") if entry_node is not None else ""
    month   = _text(issue_node, "Month") if issue_node is not None else ""

    rule = getattr(config, "YEAR_RULE", "earliest")
    candidates = [y for y in (y_issue, y_epub) if y]
    if rule == "earliest" and candidates:
        year = min(candidates)
    else:
        year = y_issue or y_epub or y_entry
    return {
        "year": year,
        "year_issue": y_issue,
        "year_epub": y_epub,
        "year_pubmed_entry": y_entry,
        "month": month,
    }


def _parse_author(auth_elem) -> dict:
    """Parse a single <Author> element."""
    last     = _text(auth_elem, "LastName")
    fore     = _text(auth_elem, "ForeName")
    initials = _text(auth_elem, "Initials")
    affils = [
        _itertext(aff)
        for aff in auth_elem.findall("AffiliationInfo/Affiliation")
    ]
    affils = [a for a in affils if a]
    orcid = ""
    for ident in auth_elem.findall("Identifier"):
        if ident.get("Source") == "ORCID":
            orcid = (_itertext(ident)
                     .replace("https://orcid.org/", "")
                     .replace("http://orcid.org/", "")
                     .strip())
    collective = _text(auth_elem, "CollectiveName")
    return {
        "last": last,
        "fore": fore,
        "initials": initials,
        "affils": affils,
        "orcid": orcid,
        "collective": collective,
    }


def _parse_pubmed_xml(xml_text: str) -> list[dict]:
    """Parse PubmedArticleSet XML into list of record dicts."""
    records = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"\n  [warn] XML parse error: {e}")
        return records

    for article in root.findall(".//PubmedArticle"):
        rec: dict = {}
        art = article.find("MedlineCitation/Article")

        # ── PMID ──────────────────────────────────────────────────────────
        rec["pmid"] = _text(article, "MedlineCitation/PMID") or _text(article, ".//PMID")

        # ── Publication date ───────────────────────────────────────────────
        rec.update(_extract_year(article))

        # ── Article title ──────────────────────────────────────────────────
        rec["title"] = _text(art, "ArticleTitle") if art is not None else _text(article, ".//ArticleTitle")

        # ── Abstract (the record's own; OtherAbstract kept separately) ─────
        abstract_parts = []
        abs_nodes = art.findall("Abstract/AbstractText") if art is not None else []
        for ab in abs_nodes:
            label = ab.get("Label", "")
            text  = _itertext(ab)
            if not text:
                continue
            abstract_parts.append(f"{label}: {text}" if label else text)
        rec["abstract"] = " ".join(abstract_parts)
        rec["has_abstract"] = bool(abstract_parts)
        other = [_itertext(ab) for ab in article.findall("MedlineCitation/OtherAbstract/AbstractText")]
        rec["other_abstract"] = " ".join(t for t in other if t)

        # ── Journal ───────────────────────────────────────────────────────
        rec["journal"]      = _text(article, ".//Journal/Title")
        rec["journal_abbr"] = _text(article, ".//Journal/ISOAbbreviation")
        rec["issn"]         = _text(article, ".//Journal/ISSN")
        rec["issn_linking"] = _text(article, ".//MedlineJournalInfo/ISSNLinking")
        rec["nlm_id"]       = _text(article, ".//MedlineJournalInfo/NlmUniqueID")
        rec["volume"]       = _text(article, ".//Volume")
        rec["issue"]        = _text(article, ".//Issue")

        # ── DOI ───────────────────────────────────────────────────────────
        doi = ""
        for eloc in article.findall(".//ELocationID"):
            if eloc.get("EIdType") == "doi":
                doi = _itertext(eloc)
        if not doi:
            for aid in article.findall(".//ArticleIdList/ArticleId"):
                if aid.get("IdType") == "doi":
                    doi = _itertext(aid)
        rec["doi"] = doi

        # ── Publication type ──────────────────────────────────────────────
        rec["pub_types"] = [
            _itertext(pt)
            for pt in article.findall(".//PublicationTypeList/PublicationType")
        ]

        # ── Authors ───────────────────────────────────────────────────────
        authors = [
            parsed
            for a in article.findall(".//AuthorList/Author")
            for parsed in [_parse_author(a)]
            if parsed["last"] or parsed["collective"]
        ]

        # ── Affiliation fallbacks for legacy PubMed record formats ────────
        # Format A (pre-~2013): single <Affiliation> at Article level,
        # path is MedlineCitation/Article/Affiliation — shared by all authors.
        if not any(a["affils"] for a in authors):
            legacy_node = (article.find("MedlineCitation/Article/Affiliation")
                           or article.find(".//Article/Affiliation"))
            legacy = _itertext(legacy_node)
            if legacy:
                for a in authors:
                    a["affils"] = [legacy]
                    a["affil_source"] = "article_level"

        # Format B (mid-era ~2010–2013): only the first author has
        # <AffiliationInfo>; co-authors are blank. Propagate to blanks, but
        # remember that it was propagated so attribution code can tell.
        if authors:
            first_affils = next((a["affils"] for a in authors if a["affils"]), [])
            if first_affils:
                for a in authors:
                    if not a["affils"]:
                        a["affils"] = first_affils
                        a["affil_source"] = "propagated"

        rec["authors"] = authors

        # ── MeSH terms ────────────────────────────────────────────────────
        rec["mesh"] = [
            _text(mh, "DescriptorName")
            for mh in article.findall(".//MeshHeadingList/MeshHeading")
        ]
        rec["mesh_major"] = [
            _text(mh, "DescriptorName")
            for mh in article.findall(".//MeshHeadingList/MeshHeading")
            if (mh.find("DescriptorName") is not None
                and mh.find("DescriptorName").get("MajorTopicYN") == "Y")
        ]

        # ── Keywords ──────────────────────────────────────────────────────
        # Author keywords only (KeywordList Owner="NOTNLM").  OLDMEDLINE records
        # (1950s–60s) carry NLM subject terms in a KeywordList with Owner="NLM";
        # counting those as author keywords put a 100% "author keyword" coverage
        # spike at the start of every keyword time series.  They are kept
        # separately because PubMed's [tiab] searches them, so the relevance
        # filter must still see them.
        rec["keywords"], rec["keywords_nlm"] = [], []
        for kl in article.findall(".//KeywordList"):
            dest = rec["keywords_nlm"] if (kl.get("Owner") or "").upper() == "NLM" else rec["keywords"]
            dest.extend(k for k in (_itertext(kw) for kw in kl.findall("Keyword")) if k)

        # ── Grant info ────────────────────────────────────────────────────
        rec["grants"] = [
            {
                "id":      _text(g, "GrantID"),
                "agency":  _text(g, "Agency"),
                "country": _text(g, "Country"),
            }
            for g in article.findall(".//GrantList/Grant")
        ]

        # ── Language ──────────────────────────────────────────────────────
        rec["language"] = _text(article, ".//Language")

        # ── Country of publication (journal's, not the authors') ──────────
        rec["pub_country"] = _text(article, ".//MedlineJournalInfo/Country")

        # ── Citation count placeholder ─────────────────────────────────────
        rec["citation_count"] = None

        records.append(rec)

    return records


# ── Year window ───────────────────────────────────────────────────────────────

def check_year_window(records: list[dict], start: int, end: int) -> tuple[list[dict], list[dict]]:
    """Split records into (in_window, out_of_window) by rec["year"]; blank years are out."""
    inside, outside = [], []
    for rec in records:
        try:
            y = int(rec.get("year") or 0)
        except ValueError:
            y = 0
        (inside if start <= y <= end else outside).append(rec)
    return inside, outside


# ── Relevance filter ──────────────────────────────────────────────────────────

def is_kc_relevant(rec: dict) -> tuple[bool, str]:
    """Backward-compatible wrapper around relevance.classify()."""
    import relevance
    d = relevance.classify(rec)
    return d.keep, ("" if d.keep else f"{d.stage}:{d.rule_id} {d.detail}".strip())


def filter_records(records: list[dict], write_log: bool = True) -> list[dict]:
    """Apply the relevance filter, write the full exclusion log, return kept records."""
    import relevance
    return relevance.filter_records(records, write_log=write_log)


# ── Cache bookkeeping ─────────────────────────────────────────────────────────

def _save_json(path: pathlib.Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def write_manifest(**fields) -> dict:
    m = {
        "schema": config.CACHE_SCHEMA,
        "project_version": config.PROJECT_VERSION,
        "written": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "year_rule": getattr(config, "YEAR_RULE", "earliest"),
        "window": [config.ALL_TIME_START, config.END_YEAR],
    }
    m.update(fields)
    _save_json(pathlib.Path(config.CACHE_DIR) / "manifest.json", m)
    return m


def read_manifest() -> dict | None:
    p = pathlib.Path(config.CACHE_DIR) / "manifest.json"
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _finalise(raw: list[dict], corpus_id: str, mode: str, **extra) -> list[dict]:
    """Common tail: window check → filter → caches → manifest."""
    cache = pathlib.Path(config.CACHE_DIR)
    _save_json(cache / "records_raw.json", raw)

    inside, outside = check_year_window(raw, config.ALL_TIME_START, config.END_YEAR)
    if outside:
        print(f"[fetch] {len(outside)} records outside {config.ALL_TIME_START}–{config.END_YEAR} "
              f"(year rule: {getattr(config, 'YEAR_RULE', 'earliest')}) → year_window_excluded.json")
    _save_json(cache / "year_window_excluded.json", [
        {"pmid": r.get("pmid"), "year": r.get("year"), "year_issue": r.get("year_issue"),
         "year_epub": r.get("year_epub"), "year_pubmed_entry": r.get("year_pubmed_entry"),
         "title": r.get("title"), "journal": r.get("journal")} for r in outside])

    records = filter_records(inside)
    _save_json(cache / "records.json", records)
    write_manifest(mode=mode, corpus_id=corpus_id, n_raw=len(raw),
                   n_out_of_window=len(outside), n_kept=len(records), **extra)
    print(f"[fetch] Saved {len(records)} records to {cache / 'records.json'}")
    return records


# ── Top-level runners ─────────────────────────────────────────────────────────

def _load_cached() -> list[dict]:
    cache_path = pathlib.Path(config.CACHE_DIR) / "records.json"
    print(f"[fetch] Loading cached records from {cache_path}")
    with open(cache_path, encoding="utf-8") as f:
        records = json.load(f)
    print(f"[fetch] Loaded {len(records)} cached records")
    return records


def run_fetch(api_key: str = "", force_refresh: bool = False) -> list[dict]:
    """
    Query-mode fetch: esearch → efetch (XML persisted) → parse → window → filter.
    Results cached to CACHE_DIR/records.json.
    """
    cache_path = pathlib.Path(config.CACHE_DIR) / "records.json"
    if cache_path.exists() and not force_refresh:
        return _load_cached()

    api_key = api_key or config.NCBI_API_KEY
    query = config.PUBMED_QUERY
    corpus_id = corpus_id_for_query(query)
    xdir = xml_dir(corpus_id)
    for old in xdir.glob("batch_*.xml"):
        old.unlink()

    webenv, query_key, total = esearch(query, api_key=api_key)
    esearch_date = _dt.date.today().isoformat()

    # Frozen PMID list — the reproducibility artefact.
    ids = esearch_ids(query, api_key=api_key)
    _save_json(pathlib.Path(config.CACHE_DIR) / "pmids.json",
               {"total": total, "method": "esearch", "date": esearch_date, "pmids": ids})
    data_dir = pathlib.Path(config.DATA_DIR)
    data_dir.mkdir(exist_ok=True)
    (data_dir / f"pmids_corpus_{esearch_date}.txt").write_text(
        "\n".join(ids) + "\n", encoding="utf-8")

    if total <= _NCBI_EFETCH_LIMIT:
        print(f"[fetch] {total} records; paginating via history server …")
        raw = efetch_from_history(webenv, query_key, total, api_key=api_key, xdir=xdir)
    else:
        print(f"[fetch] {total} records > {_NCBI_EFETCH_LIMIT} limit; fetching by decade …")
        raw, seen, batch_offset = [], set(), 0
        start = config.ALL_TIME_START
        while start <= config.END_YEAR:
            end = min(start + 9, config.END_YEAR)
            wenv, qk, n = esearch(_query_for_years(start, end), api_key=api_key)
            if n:
                chunk = efetch_from_history(wenv, qk, n, api_key=api_key, xdir=xdir,
                                            batch_offset=batch_offset)
                batch_offset += (n + config.BATCH_SIZE - 1) // config.BATCH_SIZE
                added = 0
                for rec in chunk:
                    pmid = rec.get("pmid", "")
                    if pmid and pmid not in seen:
                        seen.add(pmid); raw.append(rec); added += 1
                    elif not pmid:
                        raw.append(rec)
                print(f"  [{start}–{end}] {n} found, {added} added after dedup")
            start = end + 1
        print(f"[fetch] Chunked fetch complete: {len(raw)} unique records")

    return _finalise(raw, corpus_id, mode="query", query=query,
                     esearch_count=total, esearch_date=esearch_date,
                     api_key_used=bool(api_key))


def load_pmids_from_file(filepath: str) -> list[str]:
    """Load PMIDs from a plain text file (one per line)."""
    lines = pathlib.Path(filepath).read_text().strip().splitlines()
    pmids = [l.strip() for l in lines if l.strip() and l.strip().isdigit()]
    print(f"[fetch] Loaded {len(pmids)} PMIDs from {filepath}")
    return pmids


def run_fetch_from_pmids(pmid_file: str, api_key: str = "",
                         force_refresh: bool = False) -> list[dict]:
    """
    Fetch full records for a provided PMID list file (skips esearch).
    Results cached to CACHE_DIR/records.json.
    """
    cache_path = pathlib.Path(config.CACHE_DIR) / "records.json"
    if cache_path.exists() and not force_refresh:
        return _load_cached()

    api_key = api_key or config.NCBI_API_KEY
    pmids = load_pmids_from_file(pmid_file)
    corpus_id = corpus_id_for_pmids(pmids)
    xdir = xml_dir(corpus_id)
    for old in xdir.glob("batch_*.xml"):
        old.unlink()

    _save_json(pathlib.Path(config.CACHE_DIR) / "pmids.json",
               {"total": len(pmids), "method": "pmid_file", "source": str(pmid_file),
                "date": _dt.date.today().isoformat(), "pmids": pmids})

    raw = efetch_batch(pmids, api_key=api_key, xdir=xdir)
    return _finalise(raw, corpus_id, mode="pmid_file", pmid_file=str(pmid_file),
                     api_key_used=bool(api_key))


def run_reparse(corpus_id: str | None = None) -> list[dict]:
    """Rebuild records.json from the stored XML of the last fetch (no network)."""
    manifest = read_manifest() or {}
    corpus_id = corpus_id or manifest.get("corpus_id")
    if not corpus_id:
        raise SystemExit("[reparse] no manifest/corpus_id; run a fetch first")
    raw = parse_cached_xml(corpus_id)
    keep = {k: v for k, v in manifest.items()
            if k in ("query", "esearch_count", "esearch_date", "pmid_file", "api_key_used")}
    return _finalise(raw, corpus_id, mode=manifest.get("mode", "reparse"),
                     reparsed_from=manifest.get("written"), **keep)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch refractive surgery PubMed records")
    parser.add_argument("--api-key", default="", help="NCBI API key")
    parser.add_argument("--refresh", action="store_true", help="Force re-download")
    parser.add_argument("--pmid-file", default="", help="Fetch this PMID list instead of the query")
    parser.add_argument("--reparse", action="store_true", help="Re-parse cached XML only")
    args = parser.parse_args()
    if args.reparse:
        recs = run_reparse()
    elif args.pmid_file:
        recs = run_fetch_from_pmids(args.pmid_file, api_key=args.api_key, force_refresh=args.refresh)
    else:
        recs = run_fetch(api_key=args.api_key, force_refresh=args.refresh)
    print(f"\nDone. {len(recs)} records ready.")


is_cxl_relevant = is_kc_relevant   # old name, kept for tests
