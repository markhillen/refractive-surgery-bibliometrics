"""
geo.py — Country extraction from affiliation strings
=====================================================
Uses a curated keyword → country mapping.
Falls back to journal's country of publication when affiliation is unavailable.
"""

import re

# ── Country keyword map ───────────────────────────────────────────────────────
# Order matters: more specific strings should come before shorter ones.
_COUNTRY_PATTERNS = [
    # Country name / demonym / major city hints (most unambiguous first)
    ("United States", ["usa", "united states", "u.s.a", "u.s.", "new york", "boston",
                       "los angeles", "chicago", "baltimore", "philadelphia",
                       "san francisco", "houston", "miami", "cleveland",
                       "pittsburgh", "rochester", "bethesda", "stanford",
                       "harvard", "yale", "johns hopkins", "mayo clinic",
                       "wilmer", "bascom", "cole eye", "wills eye",
                       r"\bca\b", r"\bfl\b", r"\btx\b", r"\boh\b", r"\bma\b",
                       r"\bny\b", r"\bpa\b", r"\bil\b", r"\bmd\b"]),
    ("United Kingdom", ["united kingdom", "uk", "england", "scotland", "wales",
                        "london", "manchester", "birmingham", "liverpool",
                        "edinburgh", "glasgow", "oxford", "cambridge"]),
    ("Germany", ["germany", "deutschland", "berlin", "munich", "münchen",
                 "hamburg", "cologne", "köln", "frankfurt", "heidelberg",
                 "dresden", "düsseldorf", "freiburg"]),
    ("Italy", ["italy", "italia", "rome", "roma", "milan", "milano",
               "siena", "florence", "firenze", "naples", "napoli", "bologna",
               "turin", "torino", "brescia", "catania"]),
    ("Switzerland", ["switzerland", "schweiz", "suisse", "zurich", "zürich",
                     "geneva", "genève", "bern", "basel", "lausanne"]),
    ("France", ["france", "paris", "lyon", "bordeaux", "marseille",
                "toulouse", "strasbourg", "nantes"]),
    ("Spain", ["spain", "españa", "madrid", "barcelona", "valencia",
               "seville", "sevilla", "zaragoza"]),
    ("China", ["china", "beijing", "shanghai", "guangzhou", "wuhan",
               "chengdu", "wenzhou", "hangzhou", "shenzhen", "tianjin",
               "nanjing", "xi'an", "fudan", "peking", "tsinghua",
               "zhongshan", "sun yat-sen", "sichuan", "zhejiang"]),
    ("Japan", ["japan", "tokyo", "osaka", "kyoto", "nagoya", "yokohama",
               "sapporo", "fukuoka", "keio", "waseda", "tohoku"]),
    ("South Korea", ["south korea", "korea", "seoul", "busan", "incheon",
                     "daejeon", "yonsei", "snu", "severance"]),
    ("Iran", ["iran", "tehran", "mashhad", "isfahan", "shiraz", "tabriz",
              "noor eye", "farabi"]),
    ("India", ["india", "mumbai", "delhi", "bangalore", "bengaluru",
               "hyderabad", "chennai", "kolkata", "pune", "aiims",
               "lv prasad", "sankara nethralaya", "aravind"]),
    ("Brazil", ["brazil", "brasil", "são paulo", "sao paulo", "rio de janeiro",
                "unifesp", "federal university of são paulo", "curitiba", "belo horizonte"]),
    ("Turkey", ["turkey", "türkiye", "ankara", "istanbul", "izmir",
                "hacettepe", "gazi", "ege university"]),
    ("Greece", ["greece", "athens", "thessaloniki", "crete", "heraklion",
                "university of crete"]),
    ("Australia", ["australia", "sydney", "melbourne", "brisbane", "perth",
                   "adelaide", "unsw", "monash", "queensland"]),
    ("Canada", ["canada", "toronto", "montreal", "vancouver", "ottawa",
                "calgary", "university of british columbia"]),
    ("Netherlands", ["netherlands", "holland", "amsterdam", "rotterdam",
                     "maastricht", "utrecht", "leiden", "erasmus"]),
    ("Belgium", ["belgium", "brussels", "bruxelles", "leuven", "ghent", "liège"]),
    ("Poland", ["poland", "warsaw", "kraków", "gdańsk", "poznan", "wroclaw"]),
    ("Portugal", ["portugal", "lisbon", "porto", "coimbra"]),
    ("Egypt", ["egypt", "cairo", "alexandria", "ain shams", "mansoura"]),
    ("Saudi Arabia", ["saudi arabia", "saudi", "riyadh", "jeddah", "king saud",
                      "king abdulaziz", "king khalid"]),
    ("Singapore", ["singapore", "national university of singapore",
                   "singapore national eye centre", "snec"]),
    ("Israel", ["israel", "tel aviv", "jerusalem", "hadassah", "rambam", "technion"]),
    ("Sweden", ["sweden", "stockholm", "gothenburg", "göteborg", "karolinska"]),
    ("Austria", ["austria", "vienna", "wien", "graz", "innsbruck"]),
    ("Czech Republic", ["czech", "prague", "praha", "brno"]),
    ("Denmark", ["denmark", "copenhagen", "aarhus", "odense"]),
    ("Finland", ["finland", "helsinki", "tampere", "turku"]),
    ("Norway", ["norway", "oslo", "bergen", "trondheim"]),
    ("Argentina", ["argentina", "buenos aires", "córdoba"]),
    ("Mexico", ["mexico", "méxico", "ciudad de mexico", "guadalajara", "monterrey"]),
    ("Pakistan", ["pakistan", "karachi", "lahore", "islamabad"]),
    ("Russia", ["russia", "moscow", "saint petersburg", "novosibirsk"]),
    ("Ukraine", ["ukraine", "kyiv", "odessa", "kharkiv"]),
    ("Romania", ["romania", "bucharest", "cluj", "iasi"]),
    ("Hungary", ["hungary", "budapest", "debrecen"]),
    ("Colombia", ["colombia", "bogotá", "bogota", "medellín", "medellin"]),
    ("Chile", ["chile", "santiago"]),
    ("Malaysia", ["malaysia", "kuala lumpur", "penang"]),
    ("Taiwan", ["taiwan", "taipei", "taichung", "tainan"]),
    ("Hong Kong", ["hong kong", "hkust", "cuhk", "hku"]),
    ("New Zealand", ["new zealand", "auckland", "wellington", "christchurch"]),
    ("Lebanon", ["lebanon", "beirut", "american university of beirut"]),
    ("Morocco", ["morocco", "casablanca", "rabat"]),
    ("Nigeria", ["nigeria", "lagos", "abuja"]),
    ("South Africa", ["south africa", "johannesburg", "cape town", "pretoria"]),
]

# Compile patterns
_COMPILED = []
for country, patterns in _COUNTRY_PATTERNS:
    combined = "|".join(
        (p if p.startswith(r"\b") else re.escape(p))
        for p in patterns
    )
    _COMPILED.append((country, re.compile(combined, re.IGNORECASE)))


def extract_country(affil_strings: list[str], fallback: str = "") -> str:
    """
    Extract country from a list of affiliation strings.
    Returns first match or fallback.
    """
    text = " ".join(affil_strings).lower()
    for country, pattern in _COMPILED:
        if pattern.search(text):
            return country
    return fallback or "Unknown"


def enrich_countries(records: list[dict]) -> list[dict]:
    """Add 'country' field to each record based on first author's affiliation."""
    for rec in records:
        authors = rec.get("authors", [])
        # Try first author, then any author
        country = ""
        for a in authors:
            affils = a.get("affils", [])
            if affils:
                country = extract_country(affils, fallback="")
                if country and country != "Unknown":
                    break
        if not country or country == "Unknown":
            country = extract_country([], fallback=rec.get("pub_country", "Unknown"))
        rec["country"] = country
    return records


def build_country_author_map(records: list[dict]) -> dict[str, set]:
    """
    Returns dict: country -> set of author_ids
    Considers ALL authors' affiliations (not just first author).
    """
    country_authors: dict[str, set] = {}
    for rec in records:
        for a in rec.get("authors", []):
            if not a.get("last"):
                continue
            affils = a.get("affils", [])
            c = extract_country(affils)
            aid = a.get("author_id", f"{a['last']}, {a.get('fore','')}")
            country_authors.setdefault(c, set()).add(aid)
    return country_authors
