"""
geo.py — Country extraction from affiliation strings
=====================================================

One country table (ISO-3166 alpha-2 → display name → name variants → city and
institution hints) drives both the affiliation-string parser used here and the
ISO-code → name mapping used by the OpenAlex overlay, so "Czechia" and
"Czech Republic", or "England" and "United Kingdom", can never be counted as
two countries again.

Resolution rule for an affiliation string:
  1. word-bounded country NAME anywhere in the string; if several, the LAST one
     wins (PubMed affiliations end "…, City, Country.");
  2. else a city / institution hint, last occurrence wins;
  3. else Unknown.
Every pattern is word-bounded — "uk" no longer matches Fukuoka or Lucknow.

Country attribution is FIRST AUTHOR ONLY.  Journal country of publication is
never used as a fallback (it is not an author's country).
"""

from __future__ import annotations

import csv
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import config

# ── Country table ─────────────────────────────────────────────────────────────
# (iso2, display name, [country-name variants], [city/institution hints])
COUNTRIES: list[tuple[str, str, list[str], list[str]]] = [
    ("US", "United States", ["united states", "usa", "u.s.a", "u.s.", "united states of america"],
     ["new york", "boston", "los angeles", "chicago", "baltimore", "philadelphia", "san francisco",
      "houston", "miami", "cleveland", "pittsburgh", "rochester", "bethesda", "stanford", "harvard",
      "yale", "johns hopkins", "mayo clinic", "wilmer", "bascom palmer", "cole eye", "wills eye",
      "atlanta", "seattle", "denver", "dallas", "san diego", "minneapolis", "st. louis", "saint louis",
      "ann arbor", "new haven", "iowa city", "cincinnati", "portland", "salt lake city", "nashville",
      "durham, nc", "chapel hill", "emory", "duke university", "ucla", "ucsf", "usc ", "nyu"]),
    ("GB", "United Kingdom", ["united kingdom", "u.k.", "uk", "england", "scotland", "wales",
                              "northern ireland", "great britain"],
     ["london", "manchester", "birmingham", "liverpool", "edinburgh", "glasgow", "oxford", "cambridge",
      "moorfields", "nottingham", "leeds", "sheffield", "bristol", "cardiff", "belfast", "newcastle upon tyne",
      "southampton", "leicester"]),
    ("DE", "Germany", ["germany", "deutschland"],
     ["berlin", "munich", "münchen", "hamburg", "cologne", "köln", "frankfurt", "heidelberg", "dresden",
      "düsseldorf", "freiburg", "tübingen", "tuebingen", "erlangen", "homburg", "mainz", "münster", "muenster",
      "bochum", "hannover", "leipzig", "würzburg", "wuerzburg", "regensburg", "rostock", "kiel", "essen",
      "göttingen", "goettingen", "aachen", "ulm", "halle (saale)", "bonn", "marburg", "giessen", "gießen"]),
    ("IT", "Italy", ["italy", "italia"],
     ["rome", "roma", "milan", "milano", "siena", "florence", "firenze", "naples", "napoli", "bologna",
      "turin", "torino", "brescia", "catania", "padova", "padua", "genoa", "genova", "verona", "bari",
      "pisa", "parma", "modena", "palermo", "messina", "chieti", "humanitas", "rozzano"]),
    ("CH", "Switzerland", ["switzerland", "schweiz", "suisse", "svizzera"],
     ["zurich", "zürich", "geneva", "genève", "genf", "bern", "basel", "lausanne", "lugano", "st. gallen",
      "st gallen", "lucerne", "luzern", "dietikon", "elza institute", "iroc"]),
    ("FR", "France", ["france"],
     ["paris", "lyon", "bordeaux", "marseille", "toulouse", "strasbourg", "nantes", "lille", "montpellier",
      "nice", "grenoble", "rennes", "créteil", "creteil", "rothschild"]),
    ("ES", "Spain", ["spain", "españa"],
     ["madrid", "barcelona", "valencia", "seville", "sevilla", "zaragoza", "alicante", "murcia",
      "valladolid", "bilbao", "oviedo", "vissum", "santiago de compostela"]),
    ("CN", "China", ["china", "p.r. china", "p. r. china", "pr china", "people's republic of china"],
     ["beijing", "shanghai", "guangzhou", "wuhan", "chengdu", "wenzhou", "hangzhou", "shenzhen", "tianjin",
      "nanjing", "xi'an", "fudan", "peking", "tsinghua", "zhongshan", "sun yat-sen", "sichuan", "zhejiang",
      "chongqing", "shandong", "jinan", "qingdao", "changsha", "harbin", "xiamen", "tongji", "jiangsu",
      "hebei", "henan", "zhengzhou", "kunming", "nanchang", "shenyang", "dalian", "fujian", "hubei"]),
    ("JP", "Japan", ["japan"],
     ["tokyo", "osaka", "kyoto", "nagoya", "yokohama", "sapporo", "fukuoka", "keio", "waseda", "tohoku",
      "kobe", "hiroshima", "sendai", "okayama", "kanazawa", "tsukuba", "chiba", "niigata", "kumamoto",
      "juntendo", "kitasato", "yamaguchi", "gifu", "shiga", "nara"]),
    ("KR", "South Korea", ["south korea", "republic of korea", "korea"],
     ["seoul", "busan", "incheon", "daejeon", "daegu", "yonsei", "severance", "samsung medical center",
      "asan medical center", "gwangju", "suwon"]),
    ("IR", "Iran", ["iran"],
     ["tehran", "mashhad", "isfahan", "shiraz", "tabriz", "noor eye", "farabi", "kerman", "yazd",
      "ahvaz", "labbafinejad"]),
    ("IN", "India", ["india"],
     ["mumbai", "delhi", "bangalore", "bengaluru", "hyderabad", "chennai", "kolkata", "pune", "aiims",
      "l v prasad", "lv prasad", "l.v. prasad", "sankara nethralaya", "aravind", "narayana nethralaya",
      "chandigarh", "lucknow", "ahmedabad", "jaipur", "kochi", "cochin", "coimbatore", "madurai"]),
    ("BR", "Brazil", ["brazil", "brasil"],
     ["são paulo", "sao paulo", "rio de janeiro", "unifesp", "curitiba", "belo horizonte", "porto alegre",
      "campinas", "brasília", "brasilia", "salvador", "recife", "fortaleza", "ribeirão preto"]),
    ("TR", "Turkey", ["turkey", "türkiye", "turkiye"],
     ["ankara", "istanbul", "izmir", "hacettepe", "gazi university", "ege university", "bursa", "antalya",
      "konya", "adana", "kayseri", "eskisehir", "samsun", "trabzon", "diyarbakir", "erzurum", "kocaeli"]),
    ("GR", "Greece", ["greece"],
     ["athens", "thessaloniki", "crete", "heraklion", "patras", "ioannina", "laservision"]),
    ("AU", "Australia", ["australia"],
     ["sydney", "melbourne", "brisbane", "perth", "adelaide", "unsw", "monash", "queensland", "canberra",
      "hobart", "newcastle, nsw"]),
    ("CA", "Canada", ["canada"],
     ["toronto", "montreal", "montréal", "vancouver", "ottawa", "calgary", "edmonton", "quebec", "québec",
      "halifax", "winnipeg", "hamilton, on", "mcgill"]),
    ("NL", "Netherlands", ["netherlands", "the netherlands", "holland"],
     ["amsterdam", "rotterdam", "maastricht", "utrecht", "leiden", "erasmus", "nijmegen", "groningen"]),
    ("BE", "Belgium", ["belgium", "belgique", "belgië"],
     ["brussels", "bruxelles", "leuven", "ghent", "gent", "liège", "liege", "antwerp", "antwerpen"]),
    ("PL", "Poland", ["poland", "polska"],
     ["warsaw", "warszawa", "kraków", "krakow", "gdańsk", "gdansk", "poznan", "poznań", "wroclaw", "wrocław",
      "lodz", "łódź", "katowice", "lublin", "szczecin", "bialystok"]),
    ("PT", "Portugal", ["portugal"], ["lisbon", "lisboa", "porto", "coimbra", "braga"]),
    ("EG", "Egypt", ["egypt"], ["cairo", "alexandria", "ain shams", "mansoura", "assiut", "tanta", "zagazig",
                                  "minia", "benha", "sohag", "kasr al ainy", "kasr el aini"]),
    ("SA", "Saudi Arabia", ["saudi arabia", "kingdom of saudi arabia", "ksa"],
     ["riyadh", "jeddah", "king saud", "king abdulaziz", "king khalid", "dhahran", "dammam", "makkah"]),
    ("SG", "Singapore", ["singapore"], ["snec", "singapore national eye centre"]),
    ("IL", "Israel", ["israel"], ["tel aviv", "jerusalem", "hadassah", "rambam", "technion", "haifa",
                                  "beer sheva", "beersheba", "sheba", "tel hashomer", "petah tikva"]),
    ("SE", "Sweden", ["sweden"], ["stockholm", "gothenburg", "göteborg", "karolinska", "uppsala", "lund",
                                  "umeå", "umea", "linköping", "linkoping", "örebro"]),
    ("AT", "Austria", ["austria", "österreich"], ["vienna", "wien", "graz", "innsbruck", "linz", "salzburg"]),
    ("CZ", "Czechia", ["czechia", "czech republic", "czech"], ["prague", "praha", "brno", "olomouc"]),
    ("DK", "Denmark", ["denmark", "danmark"], ["copenhagen", "københavn", "aarhus", "odense", "aalborg"]),
    ("FI", "Finland", ["finland"], ["helsinki", "tampere", "turku", "oulu", "kuopio"]),
    ("NO", "Norway", ["norway", "norge"], ["oslo", "bergen", "trondheim", "tromsø"]),
    ("AR", "Argentina", ["argentina"], ["buenos aires", "córdoba, argentina", "rosario", "mendoza"]),
    ("MX", "Mexico", ["mexico", "méxico"], ["ciudad de mexico", "mexico city", "guadalajara", "monterrey",
                                             "puebla", "asociación para evitar la ceguera"]),
    ("PK", "Pakistan", ["pakistan"], ["karachi", "lahore", "islamabad", "rawalpindi", "peshawar"]),
    ("RU", "Russia", ["russia", "russian federation"], ["moscow", "saint petersburg", "st. petersburg",
                                                        "novosibirsk", "ufa", "kazan", "yekaterinburg",
                                                        "fyodorov"]),
    ("UA", "Ukraine", ["ukraine"], ["kyiv", "kiev", "odessa", "odesa", "kharkiv", "lviv", "filatov"]),
    ("RO", "Romania", ["romania"], ["bucharest", "bucuresti", "cluj", "iasi", "timisoara"]),
    ("HU", "Hungary", ["hungary"], ["budapest", "debrecen", "szeged", "pécs"]),
    ("CO", "Colombia", ["colombia"], ["bogotá", "bogota", "medellín", "medellin", "cali"]),
    ("CL", "Chile", ["chile"], ["santiago, chile", "santiago de chile", "valparaíso"]),
    ("MY", "Malaysia", ["malaysia"], ["kuala lumpur", "penang", "kelantan", "selangor"]),
    ("TW", "Taiwan", ["taiwan", "republic of china"], ["taipei", "taichung", "tainan", "kaohsiung",
                                                       "chang gung", "national taiwan university"]),
    ("HK", "Hong Kong", ["hong kong"], ["hkust", "cuhk", "hku", "kowloon"]),
    ("NZ", "New Zealand", ["new zealand"], ["auckland", "wellington", "christchurch", "dunedin", "otago"]),
    ("LB", "Lebanon", ["lebanon"], ["beirut", "american university of beirut"]),
    ("MA", "Morocco", ["morocco", "maroc"], ["casablanca", "rabat", "marrakech", "fez", "fès"]),
    ("NG", "Nigeria", ["nigeria"], ["lagos", "abuja", "ibadan", "enugu"]),
    ("ZA", "South Africa", ["south africa"], ["johannesburg", "cape town", "pretoria", "durban",
                                              "stellenbosch"]),
    ("IE", "Ireland", ["ireland", "republic of ireland"], ["dublin", "cork", "galway", "limerick"]),
    ("JO", "Jordan", ["jordan"], ["amman", "irbid"]),
    ("AE", "United Arab Emirates", ["united arab emirates", "uae", "u.a.e"], ["dubai", "abu dhabi", "sharjah",
                                                                            "al ain"]),
    ("KW", "Kuwait", ["kuwait"], ["al-bahar"]),
    ("QA", "Qatar", ["qatar"], ["doha"]),
    ("IQ", "Iraq", ["iraq"], ["baghdad", "basra", "mosul", "erbil", "najaf", "babylon, iraq", "al-mustaqbal"]),
    ("TH", "Thailand", ["thailand"], ["bangkok", "chiang mai", "mahidol", "chulalongkorn", "siriraj",
                                      "khon kaen"]),
    ("VN", "Vietnam", ["vietnam", "viet nam"], ["hanoi", "ho chi minh"]),
    ("ID", "Indonesia", ["indonesia"], ["jakarta", "surabaya", "bandung", "yogyakarta"]),
    ("PH", "Philippines", ["philippines"], ["manila", "quezon city", "cebu"]),
    ("BD", "Bangladesh", ["bangladesh"], ["dhaka", "chittagong"]),
    ("NP", "Nepal", ["nepal"], ["kathmandu", "tilganga"]),
    ("LK", "Sri Lanka", ["sri lanka"], ["colombo", "kandy"]),
    ("SK", "Slovakia", ["slovakia", "slovak republic"], ["bratislava", "košice", "kosice"]),
    ("SI", "Slovenia", ["slovenia"], ["ljubljana", "maribor"]),
    ("HR", "Croatia", ["croatia"], ["zagreb", "split, croatia", "rijeka", "osijek"]),
    ("RS", "Serbia", ["serbia"], ["belgrade", "beograd", "novi sad", "niš"]),
    ("BG", "Bulgaria", ["bulgaria"], ["sofia", "plovdiv", "varna"]),
    ("LT", "Lithuania", ["lithuania"], ["vilnius", "kaunas"]),
    ("LV", "Latvia", ["latvia"], ["riga"]),
    ("EE", "Estonia", ["estonia"], ["tallinn", "tartu"]),
    ("CY", "Cyprus", ["cyprus"], ["nicosia", "limassol", "larnaca"]),
    ("TN", "Tunisia", ["tunisia", "tunisie"], ["tunis", "sfax", "monastir", "sousse"]),
    ("DZ", "Algeria", ["algeria", "algérie"], ["algiers", "oran", "constantine, algeria"]),
    ("PE", "Peru", ["peru", "perú"], ["lima, peru", "lima, perú", "arequipa"]),
    ("VE", "Venezuela", ["venezuela"], ["caracas", "maracaibo"]),
    ("CU", "Cuba", ["cuba"], ["havana", "la habana"]),
    ("ET", "Ethiopia", ["ethiopia"], ["addis ababa"]),
    ("KE", "Kenya", ["kenya"], ["nairobi"]),
    ("GH", "Ghana", ["ghana"], ["accra", "kumasi"]),
    ("UZ", "Uzbekistan", ["uzbekistan"], ["tashkent"]),
    ("KZ", "Kazakhstan", ["kazakhstan"], ["almaty", "astana"]),
    ("GE", "Georgia (country)", ["republic of georgia"], ["tbilisi"]),
    ("AM", "Armenia", ["armenia"], ["yerevan"]),
    ("BY", "Belarus", ["belarus"], ["minsk"]),
    ("LU", "Luxembourg", ["luxembourg"], []),
    ("IS", "Iceland", ["iceland"], ["reykjavik", "reykjavík"]),
    ("MT", "Malta", ["malta"], ["msida", "valletta"]),
    ("OM", "Oman", ["oman"], ["muscat"]),
    ("BH", "Bahrain", ["bahrain"], ["manama"]),
    ("SY", "Syria", ["syria", "syrian arab republic"], ["damascus", "aleppo"]),
    ("PS", "Palestine", ["palestine"], ["gaza", "ramallah", "nablus"]),
    ("LY", "Libya", ["libya"], ["tripoli", "benghazi"]),
    ("SD", "Sudan", ["sudan"], ["khartoum"]),
    ("UG", "Uganda", ["uganda"], ["kampala"]),
    ("TZ", "Tanzania", ["tanzania"], ["dar es salaam"]),
    ("CM", "Cameroon", ["cameroon"], ["yaoundé", "yaounde", "douala"]),
    ("SN", "Senegal", ["senegal"], ["dakar"]),
    ("EC", "Ecuador", ["ecuador"], ["quito", "guayaquil"]),
    ("BO", "Bolivia", ["bolivia"], ["la paz", "cochabamba"]),
    ("UY", "Uruguay", ["uruguay"], ["montevideo"]),
    ("PY", "Paraguay", ["paraguay"], ["asunción", "asuncion"]),
    ("CR", "Costa Rica", ["costa rica"], ["san josé, costa rica"]),
    ("PA", "Panama", ["panama"], []),
    ("GT", "Guatemala", ["guatemala"], []),
    ("DO", "Dominican Republic", ["dominican republic"], ["santo domingo"]),
    ("PR", "Puerto Rico", ["puerto rico"], ["san juan, puerto rico"]),
    ("MO", "Macao", ["macao", "macau"], []),
    ("MN", "Mongolia", ["mongolia"], ["ulaanbaatar"]),
    ("KG", "Kyrgyzstan", ["kyrgyzstan"], ["bishkek"]),
    ("AZ", "Azerbaijan", ["azerbaijan"], ["baku"]),
    ("AF", "Afghanistan", ["afghanistan"], ["kabul"]),
    ("MM", "Myanmar", ["myanmar", "burma"], ["yangon"]),
    ("KH", "Cambodia", ["cambodia"], ["phnom penh"]),
    ("BN", "Brunei", ["brunei"], []),
    ("MK", "North Macedonia", ["north macedonia", "macedonia"], ["skopje"]),
    ("BA", "Bosnia and Herzegovina", ["bosnia"], ["sarajevo", "tuzla"]),
    ("ME", "Montenegro", ["montenegro"], ["podgorica"]),
    ("AL", "Albania", ["albania"], ["tirana"]),
    ("MD", "Moldova", ["moldova"], ["chișinău", "chisinau"]),
    ("XK", "Kosovo", ["kosovo"], ["pristina", "prishtina"]),
]

_ISO_TO_NAME = {iso: name for iso, name, _, _ in COUNTRIES}
# ISO codes OpenAlex can return that have no affiliation-matching entry above;
# names only, so they display and count correctly (never matched from text).
_ISO_EXTRA = {"AG": "Antigua and Barbuda", "BT": "Bhutan", "CD": "Democratic Republic of the Congo",
              "CI": "Côte d'Ivoire", "MG": "Madagascar", "RW": "Rwanda", "SM": "San Marino",
              "TT": "Trinidad and Tobago", "YE": "Yemen", "ZW": "Zimbabwe", "KH": "Cambodia"}
for _k, _v in _ISO_EXTRA.items():
    _ISO_TO_NAME.setdefault(_k, _v)
_NAME_TO_ISO = {name: iso for iso, name, _, _ in COUNTRIES}
# Names returned by other sources that must fold into ours.
_NAME_ALIASES = {
    "Czech Republic": "Czechia", "England": "United Kingdom", "Scotland": "United Kingdom",
    "Wales": "United Kingdom", "Northern Ireland": "United Kingdom", "Korea": "South Korea",
    "Republic of Korea": "South Korea", "Korea, Republic of": "South Korea",
    "Russian Federation": "Russia", "Iran, Islamic Republic of": "Iran",
    "Viet Nam": "Vietnam", "Türkiye": "Turkey", "Turkiye": "Turkey",
    "United States of America": "United States", "USA": "United States", "UK": "United Kingdom",
    "Taiwan, Province of China": "Taiwan", "Hong Kong SAR": "Hong Kong",
}


def display_name(code_or_name: str | None) -> str:
    """ISO-2 code or any name variant → the display name used throughout."""
    if not code_or_name:
        return "Unknown"
    s = str(code_or_name).strip()
    if len(s) == 2 and s.upper() in _ISO_TO_NAME:
        return _ISO_TO_NAME[s.upper()]
    return _NAME_ALIASES.get(s, s)


def iso2(name: str) -> str:
    return _NAME_TO_ISO.get(display_name(name), "")


def write_country_names_csv(path: pathlib.Path | None = None) -> pathlib.Path:
    """Export the table so the SDC can cite the exact name mapping used."""
    path = path or pathlib.Path(config.DATA_DIR) / "country_names.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["iso2", "display_name", "name_variants", "city_institution_hints"])
        for iso, name, variants, hints in COUNTRIES:
            w.writerow([iso, name, "; ".join(variants), "; ".join(hints)])
    return path


# ── Compiled patterns ─────────────────────────────────────────────────────────

def _wb(p: str) -> str:
    """Word-bound a literal. Patterns ending in punctuation get a lookahead instead."""
    esc = re.escape(p)
    lead = r"(?<![\w])"
    trail = r"(?![\w])"
    return lead + esc + trail


_NAME_RX: list[tuple[str, re.Pattern]] = [
    (name, re.compile("|".join(_wb(v) for v in variants), re.I))
    for _, name, variants, _ in COUNTRIES if variants
]
_HINT_RX: list[tuple[str, re.Pattern]] = [
    (name, re.compile("|".join(_wb(h) for h in hints), re.I))
    for _, name, _, hints in COUNTRIES if hints
]


def _last_match(rxs: list[tuple[str, re.Pattern]], text: str) -> str:
    best_pos, best = -1, ""
    for name, rx in rxs:
        for m in rx.finditer(text):
            if m.start() > best_pos:
                best_pos, best = m.start(), name
    return best


def _segments(affil_strings: list[str]) -> list[str]:
    """One author's affiliations, in the order written, one institution each.

    PubMed writes an author's several affiliations either as separate strings
    or as one string with ';' between them. Both orderings are meaningful: the
    author's own institution is written first.
    """
    out: list[str] = []
    for a in (affil_strings or []):
        if not a:
            continue
        a = re.sub(r"\S+@\S+", " ", a)
        for seg in re.split(r";\s*", a):
            if seg.strip():
                out.append(seg.strip())
    return out


_CLEAN = [
    # "People's Republic of China" is China, not the Republic of China (Taiwan)
    (re.compile(r"people'?s\s+republic\s+of\s+china|p\.\s?r\.\s?china", re.I), "China"),
    (re.compile(r"republic\s+of\s+china", re.I), "Taiwan"),
    # Australian and American place names that contain a British country name
    (re.compile(r"new\s+south\s+wales", re.I), "NSW, Australia"),
    (re.compile(r"new\s+england", re.I), "NewEngland"),
    # "UK" is a country only when it ends the affiliation ("London, UK");
    # elsewhere it is usually an abbreviation (Czech "LF UK", Univerzita Karlova)
    (re.compile(r"(?<![\w.])UK(?![\w.])(?!\s*[.;,]?\s*$)"), "U-K"),
]


def _clean(seg: str) -> str:
    for rx, rep in _CLEAN:
        seg = rx.sub(rep, seg)
    return seg


def _first_segment_match(rxs: list[tuple[str, re.Pattern]], affil_strings: list[str]) -> str:
    """Country of the first affiliation segment that yields one.

    Within a segment the last match wins, because a single affiliation ends
    with its country ("Department of X, University of Y, Zurich, Switzerland").
    Across segments the first wins, because an author who lists several
    institutions lists their own first. Taking the last match across the whole
    string, as this function used to, credited a first author with several
    affiliations to whichever country happened to be written last.
    """
    for seg in _segments(affil_strings):
        c = _last_match(rxs, _clean(seg))
        if c:
            return c
    return ""


def extract_country(affil_strings: list[str], fallback: str = "") -> str:
    """
    Country of one author from their affiliation string(s).
    Country names take precedence over city/institution hints; the author's
    first-listed affiliation wins over any later one.
    """
    text = " ".join(a for a in (affil_strings or []) if a)
    if not text.strip():
        return fallback or "Unknown"
    c = _first_segment_match(_NAME_RX, affil_strings)
    if c:
        return c
    c = _first_segment_match(_HINT_RX, affil_strings)
    if c:
        return c
    return fallback or "Unknown"


def extract_country_with_source(affil_strings: list[str]) -> tuple[str, str]:
    text = " ".join(a for a in (affil_strings or []) if a)
    if not text.strip():
        return "Unknown", "no_affiliation"
    c = _first_segment_match(_NAME_RX, affil_strings)
    if c:
        return c, "affil_country_name"
    c = _first_segment_match(_HINT_RX, affil_strings)
    if c:
        return c, "affil_city_hint"
    return "Unknown", "affil_unresolved"


# ── Record enrichment ─────────────────────────────────────────────────────────

def enrich_countries(records: list[dict]) -> list[dict]:
    """
    Set rec["country"] from the FIRST author's own affiliation, and
    a["country"] for every author (used by whole/fractional counting).
    No fallback to co-authors or to the journal's country of publication.
    """
    for rec in records:
        authors = rec.get("authors", []) or []
        for a in authors:
            affils = a.get("affils", []) or []
            if a.get("affil_source") in ("propagated",):
                # a co-author's affiliation copied onto a blank author: usable for
                # legacy single-affiliation records, but mark it
                c, src = extract_country_with_source(affils)
                a["country"], a["country_source"] = c, (src + "_propagated" if c != "Unknown" else src)
            else:
                a["country"], a["country_source"] = extract_country_with_source(affils)
        if authors:
            rec["country"] = authors[0]["country"]
            rec["country_source"] = authors[0]["country_source"]
        else:
            rec["country"], rec["country_source"] = "Unknown", "no_authors"
        rec["countries_all"] = sorted({a["country"] for a in authors if a.get("country") not in (None, "", "Unknown")})
    return records


def build_country_author_map(records: list[dict]) -> dict[str, set]:
    """country → set of author_ids, over ALL authors."""
    country_authors: dict[str, set] = {}
    for rec in records:
        for a in rec.get("authors", []):
            if not a.get("last"):
                continue
            c = a.get("country") or extract_country(a.get("affils", []))
            aid = a.get("author_id", f"{a['last']}, {a.get('fore', '')}")
            country_authors.setdefault(c, set()).add(aid)
    return country_authors
