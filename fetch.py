"""
fetch.py — PubMed retrieval via NCBI E-utilities
=================================================
Downloads all CXL records and caches them as JSON.
Run standalone:  python3 fetch.py [--api-key YOUR_KEY]
"""

import json
import os
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET
import pathlib
import argparse

# ── allow running standalone or imported ─────────────────────────────────────
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import config

BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"


def _get(url: str, retries: int = config.MAX_RETRIES) -> str:
    """HTTP GET with retry/back-off."""
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:
            wait = 2 ** attempt
            print(f"  [warn] GET failed ({e}), retry {attempt+1}/{retries} in {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"Failed to fetch: {url[:120]}")


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


def efetch_from_history(webenv: str, query_key: str, total: int,
                        api_key: str = "") -> list[dict]:
    """Fetch all records stored on the NCBI history server in batches."""
    records    = []
    batch_size = config.BATCH_SIZE
    delay      = config.REQUEST_DELAY if api_key else 0.34

    for retstart in range(0, total, batch_size):
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
        records.extend(_parse_pubmed_xml(xml_text))
        time.sleep(delay)

    print(f"\n[efetch] Parsed {len(records)} records from history server")
    return records


# NCBI rejects efetch retstart >= this value even with usehistory=y.
_NCBI_EFETCH_LIMIT = 9_999


def _query_for_years(start_yr: int, end_yr: int) -> str:
    """Rebuild PUBMED_QUERY with a narrower date window for chunked fetching."""
    base = config.PUBMED_QUERY.rsplit(' AND (', 1)[0]
    return base + f' AND ("{start_yr}/01/01"[PDAT] : "{end_yr}/12/31"[PDAT])'


def efetch_batch(pmids: list[str], api_key: str = "") -> list[dict]:
    """Fetch full records for a list of PMIDs in batches."""
    records = []
    total = len(pmids)
    batch_size = config.BATCH_SIZE
    delay = config.REQUEST_DELAY if api_key else 0.34

    for i in range(0, total, batch_size):
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
        records.extend(_parse_pubmed_xml(xml_text))
        time.sleep(delay)

    print(f"\n[efetch] Parsed {len(records)} records")
    return records


# ── XML parsing ───────────────────────────────────────────────────────────────

def _text(elem, path, default=""):
    node = elem.find(path)
    return (node.text or "").strip() if node is not None else default


def _parse_author(auth_elem) -> dict:
    """Parse a single <Author> element."""
    last   = _text(auth_elem, "LastName")
    fore   = _text(auth_elem, "ForeName")
    initials = _text(auth_elem, "Initials")
    # Collect affiliations
    affils = [
        (aff.text or "").strip()
        for aff in auth_elem.findall("AffiliationInfo/Affiliation")
    ]
    # ORCID if present
    orcid = ""
    for ident in auth_elem.findall("Identifier"):
        if ident.get("Source") == "ORCID":
            orcid = (ident.text or "").replace("http://orcid.org/", "").strip()
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
        rec = {}

        # ── PMID ──────────────────────────────────────────────────────────
        rec["pmid"] = _text(article, ".//PMID")

        # ── Publication date ───────────────────────────────────────────────
        pub_date = article.find(".//PubMedPubDate[@PubStatus='pubmed']")
        if pub_date is None:
            pub_date = article.find(".//PubDate")
        year  = _text(pub_date, "Year")  if pub_date is not None else ""
        month = _text(pub_date, "Month") if pub_date is not None else ""
        rec["year"]  = year
        rec["month"] = month

        # ── Article title ──────────────────────────────────────────────────
        rec["title"] = _text(article, ".//ArticleTitle")

        # ── Abstract ──────────────────────────────────────────────────────
        abstract_parts = []
        for ab in article.findall(".//AbstractText"):
            label = ab.get("Label", "")
            text  = (ab.text or "").strip()
            if label:
                abstract_parts.append(f"{label}: {text}")
            else:
                abstract_parts.append(text)
        rec["abstract"] = " ".join(abstract_parts)

        # ── Journal ───────────────────────────────────────────────────────
        rec["journal"]     = _text(article, ".//Journal/Title")
        rec["journal_abbr"]= _text(article, ".//Journal/ISOAbbreviation")
        rec["issn"]        = _text(article, ".//Journal/ISSN")
        rec["volume"]      = _text(article, ".//Volume")
        rec["issue"]       = _text(article, ".//Issue")

        # ── DOI ───────────────────────────────────────────────────────────
        doi = ""
        for eloc in article.findall(".//ELocationID"):
            if eloc.get("EIdType") == "doi":
                doi = (eloc.text or "").strip()
        if not doi:
            for aid in article.findall(".//ArticleIdList/ArticleId"):
                if aid.get("IdType") == "doi":
                    doi = (aid.text or "").strip()
        rec["doi"] = doi

        # ── Publication type ──────────────────────────────────────────────
        rec["pub_types"] = [
            (pt.text or "").strip()
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
            legacy = (
                article.findtext("MedlineCitation/Article/Affiliation") or
                article.findtext(".//Article/Affiliation") or
                ""
            ).strip()
            if legacy:
                for a in authors:
                    a["affils"] = [legacy]

        # Format B (mid-era ~2010–2013): only the first author has
        # <AffiliationInfo>; co-authors are blank. Propagate to blanks.
        if authors:
            first_affils = next(
                (a["affils"] for a in authors if a["affils"]), []
            )
            if first_affils:
                for a in authors:
                    if not a["affils"]:
                        a["affils"] = first_affils

        rec["authors"] = authors

        # ── MeSH terms ────────────────────────────────────────────────────
        rec["mesh"] = [
            _text(mh, "DescriptorName")
            for mh in article.findall(".//MeshHeadingList/MeshHeading")
        ]

        # ── Keywords ──────────────────────────────────────────────────────
        rec["keywords"] = [
            (kw.text or "").strip()
            for kw in article.findall(".//KeywordList/Keyword")
        ]

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

        # ── Country of publication ────────────────────────────────────────
        rec["pub_country"] = _text(article, ".//MedlineJournalInfo/Country")

        # ── Citation count placeholder ─────────────────────────────────────
        rec["citation_count"] = None

        records.append(rec)

    return records


# ── Top-level runner ──────────────────────────────────────────────────────────

def is_rs_relevant(rec: dict) -> tuple[bool, str]:
    """
    Return (True, "") if the record is a legitimate corneal laser refractive
    surgery publication, or (False, reason) if it should be excluded.

    Checks applied in order:
      1. Journal-level exclusion — definitively non-ophthalmic journals.
      2. MeSH-level exclusion — non-ophthalmic primary MeSH headings.
      3. Title + abstract must contain at least one refractive-surgery-specific term.
    """
    title    = (rec.get("title",    "") or "").lower()
    abstract = (rec.get("abstract", "") or "").lower()
    journal  = (rec.get("journal",  "") or "").lower()
    mesh     = [m.lower() for m in rec.get("mesh", [])]
    combined = title + " " + abstract

    # ── 1. Journal-level exclusion ────────────────────────────────────────────
    _EXCLUDED_JOURNALS = (
        "plastic", "aesthetic", "rhinoplasty", "reconstructive surgery",
        "annals of surgery", "dental", "oral", "maxillofacial",
        "orthodont", "endodont", "periodon", "biomaterials", "acta biomater",
        "polymer", "hydrogel", "tissue engineering", "wound repair",
        "cartilage", "bone", "spine", "orthop", "dermatol", "skin",
        "vascular", "cardiovasc", "thoracic", "urology", "gynaecol",
        "gynecol", "obstet", "hepatol", "gastroenter", "neurosurg",
        "psychiatr", "oncol", "hematol", "endocrinol", "nephrol",
        "pulmonol", "respirat",
    )
    for jkw in _EXCLUDED_JOURNALS:
        if jkw in journal:
            return False, f"Non-ophthalmic journal: {rec.get('journal', '')}"

    # ── 2. MeSH-level exclusion ───────────────────────────────────────────────
    _EXCLUDED_MESH = (
        "rhinoplasty", "plastic surgery", "reconstructive surgical procedures",
        "skin transplantation", "cartilage", "bone and bones", "dental enamel",
        "dentin", "tooth", "dental pulp", "periodontal", "orthodontic",
        "tissue scaffolds", "tissue engineering", "cardiovascular", "aorta",
        "blood vessels",
    )
    for mkw in _EXCLUDED_MESH:
        if any(mkw in m for m in mesh):
            return False, f"Excluded MeSH term: {mkw}"

    # ── 3. Must contain at least one corneal laser refractive surgery term ────
    # Prevents records where query terms appear only in passing references to
    # other fields. Cataract/IOL papers retrieved via generic terms are caught
    # here.
    _RS_TERMS = (
        "laser in situ keratomileusis", "lasik",
        "photorefractive keratectomy", "photorefractive",
        "laser epithelial keratomileusis", "lasek",
        "transepithelial", "transpk",
        "small incision lenticule extraction", "relex smile", "relex",
        "excimer laser",
        "laser vision correction", "laser refractive",
        "corneal refractive surgery", "refractive surgery",
        "ablation profile", "corneal ablation", "stromal ablation",
        "myopic ablation", "hyperopic ablation", "astigmatic ablation",
        "wavefront-guided", "wavefront guided",
        "topography-guided", "topography guided",
        "femtosecond lasik", "flap creation", "microkeratome",
        "presbyond", "presbylasik",
        "optical zone", "transition zone", "ablation depth",
        "refractive outcome", "refractive correction",
        "residual myopia", "residual refraction",
        "higher-order aberration", "higher order aberration",
        "contrast sensitivity after laser", "dry eye after laser",
        "ectasia after lasik", "ectasia after refractive",
    )
    if not any(term in combined for term in _RS_TERMS):
        return False, "No refractive surgery-specific term in title or abstract"

    # ── 4. Exclude pure cataract/IOL records that slipped through ─────────────
    _CATARACT_TERMS = ("cataract surgery", "phacoemulsification", "intraocular lens implant")
    if any(t in combined for t in _CATARACT_TERMS):
        # Only exclude if NO refractive laser term is more prominent
        laser_terms = ("lasik", "prk", "smile", "relex", "lasek", "excimer laser",
                       "corneal ablation", "photorefractive")
        if not any(t in combined for t in laser_terms):
            return False, "Cataract/IOL record without laser refractive content"

    return True, ""


def filter_records(records: list[dict]) -> list[dict]:
    """Apply is_rs_relevant() and return only relevant records, logging exclusions."""
    kept = []
    excluded_count = 0
    for rec in records:
        relevant, reason = is_rs_relevant(rec)
        if relevant:
            kept.append(rec)
        else:
            excluded_count += 1
            if excluded_count <= 20:
                pmid  = rec.get("pmid", "?")
                title = (rec.get("title", "") or "")[:80]
                print(f"  [filter] Excluded PMID {pmid}: {reason} | \"{title}\"")
    if excluded_count > 20:
        print(f"  [filter] ... and {excluded_count - 20} more excluded (not shown)")
    print(f"[filter] {len(kept)} records retained, {excluded_count} excluded")
    return kept


def run_fetch(api_key: str = "", force_refresh: bool = False) -> list[dict]:
    """
    Full fetch pipeline. Returns list of record dicts.
    Results cached to CACHE_DIR/records.json.
    """
    cache_path = pathlib.Path(config.CACHE_DIR) / "records.json"

    if cache_path.exists() and not force_refresh:
        print(f"[fetch] Loading cached records from {cache_path}")
        with open(cache_path) as f:
            records = json.load(f)
        print(f"[fetch] Loaded {len(records)} cached records")
        return records

    api_key = api_key or config.NCBI_API_KEY
    webenv, query_key, total = esearch(config.PUBMED_QUERY, api_key=api_key)

    pmid_path = pathlib.Path(config.CACHE_DIR) / "pmids.json"
    with open(pmid_path, "w") as f:
        json.dump({"total": total, "method": "usehistory"}, f)

    if total <= _NCBI_EFETCH_LIMIT:
        print(f"[fetch] {total} records; paginating via history server …")
        raw = efetch_from_history(webenv, query_key, total, api_key=api_key)
    else:
        # NCBI silently rejects retstart >= 10 000 even with usehistory=y.
        # Split into decade-sized sub-queries and merge with PMID dedup.
        print(f"[fetch] {total} records > {_NCBI_EFETCH_LIMIT} limit; "
              f"fetching by decade …")
        raw   = []
        seen  = set()
        start = config.ALL_TIME_START
        while start <= config.END_YEAR:
            end   = min(start + 9, config.END_YEAR)
            chunk_q = _query_for_years(start, end)
            wenv, qk, n = esearch(chunk_q, api_key=api_key)
            if n:
                chunk = efetch_from_history(wenv, qk, n, api_key=api_key)
                added = 0
                for rec in chunk:
                    pmid = rec.get("pmid", "")
                    if pmid and pmid not in seen:
                        seen.add(pmid)
                        raw.append(rec)
                        added += 1
                    elif not pmid:
                        raw.append(rec)
                print(f"  [{start}–{end}] {n} found, {added} added after dedup")
            start = end + 1
        print(f"[fetch] Chunked fetch complete: {len(raw)} unique records")

    records = filter_records(raw)

    tmp = cache_path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(records, f, indent=2)
    import os as _os
    _os.replace(tmp, cache_path)
    print(f"[fetch] Saved {len(records)} records to {cache_path}")
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch CXL PubMed records")
    parser.add_argument("--api-key", default="", help="NCBI API key")
    parser.add_argument("--refresh", action="store_true", help="Force re-download")
    args = parser.parse_args()
    records = run_fetch(api_key=args.api_key, force_refresh=args.refresh)
    print(f"\nDone. {len(records)} records ready.")


# ── PMID-file entry point ─────────────────────────────────────────────────────

def load_pmids_from_file(filepath: str) -> list[str]:
    """Load PMIDs from a plain text file (one per line)."""
    lines = pathlib.Path(filepath).read_text().strip().splitlines()
    pmids = [l.strip() for l in lines if l.strip() and l.strip().isdigit()]
    print(f"[fetch] Loaded {len(pmids)} PMIDs from {filepath}")
    return pmids


def run_fetch_from_pmids(pmid_file: str, api_key: str = "",
                         force_refresh: bool = False) -> list[dict]:
    """
    Fetch full records for a provided PMID list file.
    Skips esearch entirely — uses the given PMIDs directly.
    Results cached to CACHE_DIR/records.json.
    """
    cache_path = pathlib.Path(config.CACHE_DIR) / "records.json"

    if cache_path.exists() and not force_refresh:
        print(f"[fetch] Loading cached records from {cache_path}")
        with open(cache_path) as f:
            records = json.load(f)
        print(f"[fetch] Loaded {len(records)} cached records")
        return records

    api_key = api_key or config.NCBI_API_KEY
    pmids = load_pmids_from_file(pmid_file)

    # Save PMID list to cache
    pmid_path = pathlib.Path(config.CACHE_DIR) / "pmids.json"
    with open(pmid_path, "w") as f:
        json.dump(pmids, f)

    records = efetch_batch(pmids, api_key=api_key)
    records = filter_records(records)

    tmp = cache_path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(records, f, indent=2)
    import os as _os
    _os.replace(tmp, cache_path)
    print(f"[fetch] Saved {len(records)} records to {cache_path}")
    return records
