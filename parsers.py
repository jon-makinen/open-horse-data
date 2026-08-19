# horse-data/parsers.py
"""Pure string parsing for the horse CSV build. Run this file to self-check."""
import re

WIKILINK = re.compile(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]")
REF = re.compile(r"<ref[^>]*>.*?</ref>|<ref[^>]*/>", re.S | re.I)
TAG = re.compile(r"<[^>]+>")
# Any two or three letter code in trailing brackets is a country of birth, plus
# the Wikipedia disambiguation words. A whitelist of codes was tried first and
# split the file: TUR, CHI, URU and PER are not on it, so "Adonise" and
# "Adonise (TUR)" became separate keys and the same horse appeared twice.
SUFFIX = re.compile(
    r"\s*\((?:[A-Za-z]{2,3}|horse|racehorse|filly|colt|mare|stallion|gelding)\)\s*$",
    re.I,
)
RECORD = re.compile(r"(\d+)\s*:\s*(\d+)\s*[–—-]\s*(\d+)\s*[–—-]\s*(\d+)")
YEAR = re.compile(r"(1[6-9]\d\d|20\d\d)")

# Longest and most specific first: a bare "$" must be the last thing tried, or
# "HKD$130,250,975" is read as US dollars.
CURRENCIES = [
    ("HKD", "HKD"), ("AED", "AED"), ("AUD", "AUD"), ("NZD", "NZD"),
    ("CAD", "CAD"), ("USD", "USD"), ("GBP", "GBP"), ("EUR", "EUR"),
    ("JPY", "JPY"), ("ZAR", "ZAR"), ("SGD", "SGD"),
    ("US$", "USD"), ("A$", "AUD"), ("AU$", "AUD"), ("C$", "CAD"), ("CA$", "CAD"),
    ("HK$", "HKD"), ("NZ$", "NZD"), ("R$", "BRL"),
    ("£", "GBP"), ("€", "EUR"), ("¥", "JPY"), ("$", "USD"),
]

COUNTRIES = {
    "great britain": "England", "united kingdom": "England", "uk": "England",
    "england": "England", "gb": "England", "britain": "England",
    "british": "England", "kingdom of great britain": "England",
    "kingdom of great britain and ireland": "England",
    "united kingdom of great britain and ireland": "England",
    "scotland": "England", "wales": "England", "scotland/uk": "England",
    "united states": "USA", "united states of america": "USA", "us": "USA",
    "u.s.": "USA", "u.s": "USA", "usa": "USA", "u.s.a.": "USA", "america": "USA",
    "republic of ireland": "Ireland", "ireland": "Ireland", "ire": "Ireland",
    "nz": "New Zealand", "aus": "Australia", "jpn": "Japan", "fr": "France",
    "ger": "Germany", "can": "Canada",
}

# Values that mean "this cell was filled in wrong", not a country.
NOT_A_COUNTRY = {"north america", "europe", "unknown", "n/a"}

COLOURS = {
    "bay": "Bay", "chestnut": "Chestnut", "black": "Black",
    "grey": "Grey", "gray": "Grey", "roan": "Roan",
    "brown": "Seal Brown", "seal brown": "Seal Brown",
    "dark bay": "Seal Brown", "dark bay or brown": "Seal Brown",
    "bay or brown": "Seal Brown", "chestnut flaxen": "Chestnut Flaxen",
    "dark bay/brown": "Seal Brown", "dark brown": "Seal Brown",
    "bay/brown": "Seal Brown", "brown/bay": "Seal Brown",
    "black/brown": "Seal Brown", "brown/black": "Seal Brown",
    "brown or black": "Seal Brown",
    "dark chestnut": "Chestnut", "liver chestnut": "Chestnut",
    "gray or roan": "Roan", "grey or roan": "Roan",
    "gray/roan": "Roan", "grey/roan": "Roan",
}

BREEDS = {
    "thoroughbred": "Thoroughbred", "standardbred": "Standardbred",
    "arabian": "Arabian", "arabian horse": "Arabian", "arab": "Arabian",
    "purebred arabian": "Arabian", "pure bred arabian": "Arabian",
    "anglo arabian": "Arabian", "anglo-arab": "Arabian",
    "akhal-teke": "Akhal-Teke", "akhal teke": "Akhal-Teke",
    "american quarter horse": "American Quarter Horse",
    "quarter horse": "American Quarter Horse",
}

# Suffix codes on registered names, e.g. "KODI BEAR (IRE)". Country of birth.
SUFFIX_COUNTRY = {
    "GB": "England", "IRE": "Ireland", "FR": "France", "GER": "Germany",
    "USA": "USA", "US": "USA", "AUS": "Australia", "NZ": "New Zealand",
    "SAF": "South Africa", "SWE": "Sweden", "CAN": "Canada", "DEN": "Denmark",
    "ITY": "Italy", "SPA": "Spain", "JPN": "Japan", "ARG": "Argentina",
    "BRZ": "Brazil", "CHI": "Chile", "URU": "Uruguay", "TUR": "Turkey",
    "HUN": "Hungary", "POL": "Poland", "UAE": "UAE", "IND": "India",
    "SWI": "Switzerland", "BEL": "Belgium", "NED": "Netherlands",
    "TUR": "Turkey", "RU": "Russia", "HUN": "Hungary", "CZE": "Czech Republic",
    "CZE": "Czech Republic", "RUS": "Russia", "PER": "Peru", "VEN": "Venezuela",
}

MALE = {"stallion", "colt", "horse", "entire", "male", "male organism", "rig"}
FEMALE = {"mare", "filly", "female", "female organism"}


def strip_wiki(s):
    """Remove wikilinks, refs, html tags and <br/> alternatives; keep the first value."""
    if not s:
        return ""
    s = REF.sub("", s)
    s = re.sub(r"'{2,}", "", s)      # wikitext italics, e.g. an unnamed mare
    s = WIKILINK.sub(r"\1", s)
    s = re.sub(r"<br\s*/?>", "|", s, flags=re.I)
    s = TAG.sub("", s)
    s = s.split("|")[0]
    s = re.sub(r"\{\{[^}]*\}\}", "", s)
    return re.sub(r"\s+", " ", s).strip(" ,;")


BARE_SUFFIX = re.compile(r"\s+([A-Z]{2,3})$")


def split_suffix(s, home=""):
    """Return (name, country) from a registered name like "KODI BEAR (IRE)".

    Racing names are unique within a studbook, not globally, which is exactly
    why the industry writes the country of birth after the name. An unsuffixed
    name in a national register means home-bred, so `home` supplies that.
    """
    raw = strip_wiki(s)
    m = re.search(r"\(([A-Za-z]{2,3})\)\s*$", raw)
    if m:
        return clean_name(raw), SUFFIX_COUNTRY.get(m.group(1).upper(), "")
    # Some feeds drop the brackets: "Alamode GB" rather than "Alamode (GB)".
    # 20,760 dam references were written that way and matched nothing.
    m = BARE_SUFFIX.search(raw)
    if m and m.group(1).upper() in SUFFIX_COUNTRY:
        return clean_name(BARE_SUFFIX.sub("", raw)), SUFFIX_COUNTRY[m.group(1).upper()]
    return clean_name(raw), home


# Central European studbooks number their entries: "Abel 36474", "Absalon 1090".
# The number is not part of the horse's name.
STUDBOOK_NUMBER_SUFFIX = re.compile(r"\s+\d{3,6}$")


def clean_name(s):
    """Display name: wiki markup gone, disambiguation suffix gone, case preserved."""
    v = STUDBOOK_NUMBER_SUFFIX.sub("", SUFFIX.sub("", strip_wiki(s)).strip()).strip()
    # A trailing country code without brackets is still a country code, and
    # leaving it on splits the same horse into two keys.
    m = BARE_SUFFIX.search(v)
    if m and m.group(1).upper() in SUFFIX_COUNTRY:
        v = BARE_SUFFIX.sub("", v).strip()
    return v


def norm_name(s):
    """Join key: uppercase, no punctuation, no country or disambiguation suffix."""
    return re.sub(r"[^A-Z0-9 ]", "", clean_name(s).upper()).strip()


# Reverse of SUFFIX_COUNTRY, using the code the industry actually prints. Built
# from a preferred list rather than inverting the dict, because several codes map
# to the same country (US/USA, IRE/IRL) and only one is correct for output.
COUNTRY_CODE = {
    "England": "GB", "Ireland": "IRE", "USA": "USA", "France": "FR",
    "Germany": "GER", "Japan": "JPN", "Australia": "AUS", "New Zealand": "NZ",
    "Canada": "CAN", "Italy": "ITY", "Spain": "SPA", "Turkey": "TUR",
    "South Africa": "SAF", "Argentina": "ARG", "Brazil": "BRZ", "Chile": "CHI",
    "Uruguay": "URU", "Peru": "PER", "Hungary": "HUN", "Poland": "POL",
    "Sweden": "SWE", "Denmark": "DEN", "Switzerland": "SWI", "Belgium": "BEL",
    "Netherlands": "NED", "Czech Republic": "CZE", "Russia": "RUS",
    "UAE": "UAE", "India": "IND", "Korea": "KOR", "Hong Kong": "HK",
    "Finland": "FIN", "Norway": "NOR", "Mexico": "MEX", "Venezuela": "VEN",
    "Puerto Rico": "PR", "Philippines": "PHI", "Indonesia": "INA",
    "Czechoslovakia": "CZE", "Prussia": "GER",
}


ANY_SUFFIX = re.compile(r"\s*\([A-Za-z]{2,3}\)\s*$")


def suffixed(name, country):
    """Write a name the way a racing programme does: "Frankel (GB)".

    Names are only unique within a studbook, so the country of birth is what
    makes them globally unique. A horse with no known country keeps a bare name.

    Any suffix already on the name is stripped first. Countries whose code is
    not in SUFFIX_COUNTRY survive clean_name with their suffix intact, and
    without this they came out as "A Piacere (CHI) (CHI)".
    """
    if not name:
        return ""
    name = ANY_SUFFIX.sub("", name).strip()
    code = COUNTRY_CODE.get(country or "")
    return f"{name} ({code})" if code else name


def country_from_suffix(s):
    """Country of birth from a registered-name suffix, or "" if there is none."""
    m = re.search(r"\(([A-Za-z]{2,3})\)\s*$", s or "")
    return SUFFIX_COUNTRY.get(m.group(1).upper(), "") if m else ""


# Turkish dotted capital I lowercases to "i" plus a combining dot, which renders
# as "Hali̇l". Fold it to plain ASCII I before lowering.
TR_FOLD = str.maketrans({"\u0130": "I", "\u0131": "i"})
WORD = re.compile(r"[^\W\d_](?:[^\W\d_]|')*", re.UNICODE)


# Words that stay lowercase inside a name. Sources that shout their names turn
# "Lope de Vega" into "Lope De Vega", which then fails to match the canonical
# row: 43 stallions existed as two separate pedigree nodes because of this.
NAME_PARTICLES = {
    "de", "del", "della", "di", "du", "da", "das", "dos", "der", "den", "van",
    "von", "of", "the", "and", "la", "le", "les", "el", "il", "lo", "a", "in",
    "on", "at", "for", "to", "by",
}


def smart_title(s):
    """Title-case a SHOUTED registered name.

    str.title() breaks on apostrophes ("Sadler'S Wells") and an ASCII-only regex
    breaks on Turkish and other non-ASCII letters ("AğA Bakirtaş").
    """
    if not s or not s.isupper():
        return s
    lowered = s.translate(TR_FOLD).lower()
    out = []
    first = True
    for token in re.split(r"(\s+)", lowered):
        if not token.strip():
            out.append(token)
            continue
        if not first and token in NAME_PARTICLES:
            out.append(token)
        else:
            out.append(WORD.sub(lambda m: m.group(0)[0].upper() + m.group(0)[1:], token))
        first = False
    return "".join(out)


# Single-letter sex codes used on racing ratings sheets (HRI, IFHA, TJK).
SEX_CODES = {
    "C": ("M", "FALSE"), "H": ("M", "FALSE"), "S": ("M", "FALSE"),
    "G": ("M", "TRUE"), "R": ("M", "FALSE"),
    "F": ("F", ""), "M": ("F", ""),
}


def parse_sex_code(s):
    """Racing shorthand: C colt, F filly, G gelding, H horse, M mare, R rig.

    Kept separate from parse_sex because "M" means mare here and male elsewhere.
    """
    v = strip_wiki(s).strip().upper()
    if v in SEX_CODES:
        return SEX_CODES[v]
    return parse_sex(s)


def parse_sex(s):
    v = strip_wiki(s).lower().strip()
    if not v:
        return "", ""
    if "geld" in v:
        return "M", "TRUE"
    if v in MALE:
        return "M", "FALSE"
    if v in FEMALE:
        return "F", ""
    return "", ""


def parse_record(s):
    m = RECORD.search(strip_wiki(s))
    return m.groups() if m else ("", "", "", "")


FRANC = re.compile(r"francs?\b", re.I)


def parse_earnings(s):
    """Amount and currency, taking the currency attached to THAT amount.

    Infoboxes often list a conversion or a second jurisdiction:
    "¥ 346,273,172 (£2,627,475)". Scanning the whole string for a symbol picked
    whichever came first in the symbol table, so Nakayama Festa's yen total was
    labelled pounds. The symbol immediately before the number is the right one.
    """
    raw = strip_wiki(s)
    if not raw:
        return "", ""
    # Infoboxes sometimes carry the race record in the earnings field. Casual
    # Conquest reads "9: 4-2-2", which otherwise parses as nine of something.
    if RECORD.search(raw):
        return "", ""
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)", raw)
    if not m:
        return "", ""
    currency = ""
    prefix = raw[:m.start()][-12:]
    for symbol, code in CURRENCIES:
        if symbol in prefix:
            currency = code
            break
    # A suffix is just as binding as a prefix: El Condor Pasa's "453,000,800
    # [[JPY]]" leaves the prefix empty, and the franc check below then read the
    # French line further down the field and called his yen francs. Only a
    # currency touching the amount counts, or Ardan's "+ £1,712,000" would
    # claim the francs in front of it.
    if not currency:
        tail = raw[m.end():].lstrip()
        for symbol, code in CURRENCIES:
            if tail.startswith(symbol):
                currency = code
                break
    # "[[French franc|F]]8,498,090 + £1,712,000" collapses to a bare F, so the
    # pound belonging to the second figure won the whole-string fallback below
    # and Ardan's francs were labelled sterling.
    if not currency and FRANC.search(s):
        currency = "FRF"
    if not currency:
        for symbol, code in CURRENCIES:
            if symbol in raw:
                currency = code
                break
    # Money, so it leaves here as a plain integer: no separators, no decimals.
    return m.group(1).split(".")[0].replace(",", ""), currency


# Currency of a race, from the prize symbol if present, else the course suffix.
# rpscrape writes Irish prizes as "€5520" but American ones bare, so the symbol
# alone is not enough.
COURSE_CURRENCY = {
    "IRE": "EUR", "FR": "EUR", "GER": "EUR", "ITY": "EUR", "SPA": "EUR",
    "USA": "USD", "CAN": "CAD", "AUS": "AUD", "NZ": "NZD", "SAF": "ZAR",
    "UAE": "AED", "HK": "HKD", "JPN": "JPY", "TUR": "TRY", "SWE": "SEK",
}


def race_prize(prize, course=""):
    """Return (amount, currency) for one runner's prize money."""
    raw = (prize or "").strip()
    if not raw:
        return 0.0, ""
    currency = ""
    for sym, code in (("€", "EUR"), ("£", "GBP"), ("¥", "JPY"), ("$", "USD")):
        if sym in raw:
            currency = code
            break
    if not currency:
        m = re.search(r"\(([A-Za-z]{2,3})\)\s*$", course or "")
        # A bare course name in a British and Irish archive means Britain.
        currency = COURSE_CURRENCY.get(m.group(1).upper(), "") if m else "GBP"
    m = re.search(r"([\d.]+)", raw.replace(",", ""))
    if not m:
        return 0.0, ""
    try:
        return float(m.group(1)), currency
    except ValueError:
        return 0.0, ""


FLAT_DISTANCE_MAX = 4600
FURLONG_M = 201.168
MILE_M = 1609.344
VULGAR = {"½": 0.5, "¼": 0.25, "¾": 0.75, "⅛": 0.125, "⅜": 0.375, "⅝": 0.625, "⅞": 0.875}
DIST_RE = re.compile(r"(?:(\d+)\s*m)?\s*(?:(\d+)?\s*([½¼¾⅛⅜⅝⅞])?\s*f)?", re.I)

# All-weather goings. Turf is described by how soft it is, dirt by how fast.
SYNTHETIC_GOING = {"standard", "standard to slow", "standard to fast", "slow"}
DIRT_GOING = {"fast", "sloppy", "muddy", "wet fast", "good to fast"}

# Standard and Slow mean all-weather in Britain, where the course name carries
# an (AW) marker. At a foreign course the same words mean dirt: Hipodromo Chile
# is an all-dirt oval and reports Standard for 868 of its runs.
SYNTHETIC_COURSES = {
    "deauville", "chantilly", "cagnes-sur-mer", "pornichet-la baule",
    "lyon-la soie", "lyon villeurbanne", "marseille pont-de-vivaux", "pau",
    "meydan", "newcastle", "kempton", "lingfield", "southwell",
    "wolverhampton", "dundalk", "chelmsford city",
}


def parse_distance(s):
    """Race distance to metres. "1m2f" -> 2414, "6f" -> 1207, "1m½f" -> 1710."""
    raw = (s or "").strip().lower()
    if not raw:
        return 0
    m = DIST_RE.match(raw)
    if not m or not any(m.groups()):
        return 0
    miles = int(m.group(1)) if m.group(1) else 0
    furlongs = int(m.group(2)) if m.group(2) else 0
    if m.group(3):
        furlongs += VULGAR[m.group(3)]
    metres = miles * MILE_M + furlongs * FURLONG_M
    # The longest flat race anywhere is a shade over 4,000m (the Queen Alexandra
    # at Royal Ascot). Anything longer is a jumps race, and the archives do
    # mislabel some: the Hennessy Gold Cup and the Grand Military Gold Cup are
    # both steeplechases tagged as Flat.
    return round(metres) if 800 <= metres <= FLAT_DISTANCE_MAX else 0


def race_surface(going="", course=""):
    """Turf, Dirt or Synthetic from the going and the course name."""
    crs = (course or "").strip().lower()
    if "(aw)" in crs:
        return "Synthetic"
    crs = re.sub(r"\s*\([a-z]{2,3}\)$", "", crs).strip()
    g = (going or "").strip().lower()
    if g in SYNTHETIC_GOING:
        return "Synthetic" if crs in SYNTHETIC_COURSES else "Dirt"
    if g in DIRT_GOING:
        return "Dirt"
    return "Turf" if g else ""


def first_owner(s, limit=48):
    """First named owner. Syndicates run to 295 characters of comma-separated
    names, which is not usable as a stable."""
    v = clean_name(s)
    if len(v) <= limit:
        return v
    head = re.split(r"\s*[,;]\s*| and ", v)[0].strip()
    return head if head else v[:limit].strip()


def parse_dotted_number(s):
    """Turkish/European thousands dots: "1.734.123" -> "1734123"."""
    v = re.sub(r"[^\d.,]", "", strip_wiki(s) or "")
    if not v:
        return ""
    v = v.replace(".", "").replace(",", "")
    return v if v.isdigit() and int(v) else ""


def parse_year(s):
    m = YEAR.search(strip_wiki(s))
    return m.group(1) if m else ""


def map_country(s):
    """Normalise a country cell, or return "" when the cell is unusable.

    Wikipedia's country field carries template leftovers ("{{Flagicon"), US
    states ("Kentucky, United States"), parentheticals ("United States
    (Florida)") and the occasional coat colour typed into the wrong field.
    """
    v = strip_wiki(s)
    if "{{" in v or "}}" in v:
        return ""
    v = re.sub(r"\(.*?\)", " ", v)
    v = re.sub(r"^(?:\S*ficial\s+)?flag of ", "", v, flags=re.I)
    v = re.sub(r"\bfoaled in\b", " ", v, flags=re.I)
    v = re.sub(r"\bimported to\b.*", " ", v, flags=re.I)
    v = re.sub(r"\s+", " ", v).strip(" ,.")
    if not v:
        return ""
    if v.lower() in COUNTRIES:
        return COUNTRIES[v.lower()]
    if "," in v:
        v = v.rsplit(",", 1)[-1].strip()
        if v.lower() in COUNTRIES:
            return COUNTRIES[v.lower()]
    key = v.lower()
    if key in NOT_A_COUNTRY or key in COLOURS:
        return ""
    return v


def map_colour(s):
    return COLOURS.get(strip_wiki(s).lower().strip(), "")


def map_breed(s):
    return BREEDS.get(strip_wiki(s).lower().strip(), "")


# --- Japanese Wikipedia ({{競走馬}} infobox) -------------------------------

JA_COLOURS = {
    "鹿毛": "Bay", "黒鹿毛": "Seal Brown", "青鹿毛": "Seal Brown",
    "青毛": "Black", "栗毛": "Chestnut", "栃栗毛": "Chestnut",
    "芦毛": "Grey", "白毛": "", "佐目毛": "", "粕毛": "Roan",
}

JA_BREEDS = {
    "サラブレッド": "Thoroughbred", "サラブレッド系種": "Thoroughbred",
    "準サラブレッド": "Thoroughbred", "アラブ": "Arabian",
    "アングロアラブ": "Arabian", "アラブ系種": "Arabian",
    "アメリカンクォーターホース": "American Quarter Horse",
    "スタンダードブレッド": "Standardbred",
}

# Flag-template codes used in the 国 field.
JA_COUNTRY = {
    "JPN": "Japan", "USA": "USA", "GBR": "England", "IRE": "Ireland",
    "IRL": "Ireland", "FRA": "France", "CAN": "Canada", "AUS": "Australia",
    "NZL": "New Zealand", "GER": "Germany", "DEU": "Germany", "ITA": "Italy",
    "ARG": "Argentina", "BRA": "Brazil", "HKG": "Hong Kong", "IND": "India",
    "ESP": "Spain", "RUS": "Russia", "UAE": "UAE", "ZAF": "South Africa",
}

# Some articles write the country as a plain wikilink or a non-ISO flag template
# rather than {{JPN}}, which cost 492 country labels.
JA_COUNTRY_WORDS = {
    "日本": "Japan", "アメリカ合衆国": "USA", "アメリカ": "USA",
    "イギリス": "England", "英国": "England", "アイルランド": "Ireland",
    "フランス": "France", "ドイツ": "Germany", "カナダ": "Canada",
    "オーストラリア": "Australia", "ニュージーランド": "New Zealand",
    "イタリア": "Italy", "アルゼンチン": "Argentina", "ブラジル": "Brazil",
    "南アフリカ": "South Africa", "香港": "Hong Kong", "韓国": "Korea",
}
JA_FLAG_ALIAS = {"UK": "England", "GBR2": "England", "USA2": "USA", "JPN2": "Japan"}

JA_LANG_EN = re.compile(r"\{\{\s*[Ll]ang\|en\|([^}|]+)\}\}")
JA_FLAG = re.compile(r"\{\{\s*([A-Za-z]{2,4})\s*[|}]")
JA_RECORD = re.compile(r"(\d+)\s*戦\s*(\d+)\s*勝")
JA_MONEY = re.compile(r"(?:(\d+)億)?(?:(\d+)万)?(?:(\d+))?円")


def ja_first(s):
    """First segment of a Japanese infobox value: refs and <br> variants gone."""
    if not s:
        return ""
    s = REF.sub("", s)
    s = re.sub(r"<br\s*/?>", "|", s, flags=re.I)
    head = s.split("|")[0]
    return head if "{{" not in head else s


def ja_english_name(s):
    """The 英 field, e.g. "{{Lang|en|Deep Impact}}" -> "Deep Impact"."""
    if not s:
        return ""
    m = JA_LANG_EN.search(s)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    return clean_name(s)


def ja_title(s):
    """Strip Japanese disambiguation suffixes from an article title."""
    return re.sub(r"\s*\((?:競走馬|馬|繁殖牝馬)\)\s*$", "", s or "").strip()


def ja_sex(s):
    v = strip_wiki(ja_first(s))
    if "セン" in v or "騸" in v:
        return "M", "TRUE"
    if "牡" in v:
        return "M", "FALSE"
    if "牝" in v:
        return "F", ""
    return "", ""


def ja_colour(s):
    return JA_COLOURS.get(strip_wiki(ja_first(s)).strip(), "")


def ja_breed(s):
    return JA_BREEDS.get(strip_wiki(ja_first(s)).strip(), "")


def ja_country(s):
    if not s:
        return ""
    m = JA_FLAG.search(s)
    if m:
        code = m.group(1).upper()
        found = JA_COUNTRY.get(code) or JA_FLAG_ALIAS.get(code)
        if found:
            return found
    for word, country in JA_COUNTRY_WORDS.items():
        if word in s:
            return country
    return ""


def ja_record(s):
    """The 績 field gives starts and wins only. 2nds and 3rds are not published."""
    m = JA_RECORD.search(REF.sub("", s or ""))
    return (m.group(1), m.group(2)) if m else ("", "")


def ja_earnings(s):
    """Japanese myriad notation: 14億5455万1000円 -> 1454551000.

    The components are positional, so 万 and the trailing part must each be
    below 10,000 or the string is malformed. Wikipedia contains at least one
    horse recorded as 1億61866186万8000円, which parses arithmetically to 618
    billion yen. Rejecting it here beats shipping a horse that earned a
    thousand times the world record.
    """
    raw = strip_wiki(ja_first(s)).replace(",", "").replace("，", "")
    m = JA_MONEY.search(raw)
    if not m or not any(m.groups()):
        return ""
    oku, man, rest = (int(g) if g else 0 for g in m.groups())
    # Only positional when a marker is actually present; a bare "21000000円" is
    # just a number and needs no bounds.
    if (m.group(1) or m.group(2)) and (man >= 10000 or rest >= 10000):
        return ""
    total = oku * 10 ** 8 + man * 10 ** 4 + rest
    return str(total) if total else ""


# --- Generic HTML table reading (for manually saved pages) ----------------

TABLE = re.compile(r"<table[^>]*>(.*?)</table>", re.S | re.I)
ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)


def html_tables(text):
    """Yield each <table> as a list of rows, each row a list of cell strings.

    Deliberately header-agnostic: pages that are saved by hand vary in markup,
    so callers match on the header text rather than on column position.
    """
    import html as _html
    for body in TABLE.findall(text):
        rows = []
        for r in ROW.findall(body):
            cells = [
                re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", c))).strip()
                for c in CELL.findall(r)
            ]
            if cells:
                rows.append(cells)
        if rows:
            yield rows


def table_dicts(rows):
    """Turn [header_row, *data_rows] into dicts keyed by header text."""
    if not rows:
        return []
    header = [h.strip() for h in rows[0]]
    out = []
    for r in rows[1:]:
        if len(r) < len(header):
            r = r + [""] * (len(header) - len(r))
        out.append(dict(zip(header, r)))
    return out


# --- Korean (KRA studbook) -------------------------------------------------

# Revised Romanization of Korean. Hangul syllables decompose arithmetically into
# initial/medial/final jamo, so this needs no lookup table beyond the three
# below. Assimilation rules between syllables are skipped: horse names are
# mostly transliterated foreign words, and readable beats phonetically perfect.
HANGUL_BASE = 0xAC00
HANGUL_LAST = 0xD7A3
RR_INITIAL = ["g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "",
              "j", "jj", "ch", "k", "t", "p", "h"]
RR_MEDIAL = ["a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae",
             "oe", "yo", "u", "wo", "we", "wi", "yu", "eu", "ui", "i"]
RR_FINAL = ["", "k", "k", "ks", "n", "nj", "nh", "t", "l", "lk", "lm", "lb",
            "ls", "lt", "lp", "lh", "m", "p", "ps", "t", "t", "ng", "t", "t",
            "k", "t", "p", "t"]

KR_SEX = {"수": ("M", "FALSE"), "암": ("F", ""), "거": ("M", "TRUE")}

KR_COLOURS = {
    "갈색": "Bay", "갈": "Bay", "밤색": "Chestnut", "밤": "Chestnut",
    "회색": "Grey", "회": "Grey", "흑갈색": "Seal Brown", "흑색": "Black",
    "적갈색": "Chestnut", "백색": "", "월모": "Roan",
}

KR_COUNTRIES = {
    "한국": "Korea", "미국": "USA", "호주": "Australia", "일본": "Japan",
    "뉴질랜드": "New Zealand", "캐나다": "Canada", "아일랜드": "Ireland",
    "영국": "England", "프랑스": "France", "독일": "Germany",
    "아르헨티나": "Argentina", "브라질": "Brazil", "칠레": "Chile",
    "남아공": "South Africa", "아랍에미리트": "UAE",
}


def romanize_hangul(s):
    """Hangul to Latin, Revised Romanization. Non-Hangul passes through."""
    if not s:
        return ""
    out = []
    for ch in s:
        code = ord(ch)
        if HANGUL_BASE <= code <= HANGUL_LAST:
            i = code - HANGUL_BASE
            out.append(RR_INITIAL[i // 588])
            out.append(RR_MEDIAL[(i % 588) // 28])
            out.append(RR_FINAL[i % 28])
        else:
            out.append(ch)
    return "".join(out)


def kr_name(s):
    """A Korean register name as a Latin display name."""
    v = (s or "").strip()
    # "<DAM>_자마" is an unnamed foal, not a name. Stripping the suffix would
    # leave the dam's own name and merge the foal into her row.
    if "자마" in v:
        return ""
    if not v:
        return ""
    roman = romanize_hangul(v).strip()
    if not roman:
        return ""
    return smart_title(roman.upper()) if roman.isupper() or roman.islower() else roman


def kr_sex_ja(s):
    """Japanese sex column: 牡 colt/horse, 牝 mare/filly, セン gelding."""
    v = (s or "").strip()
    if "セ" in v or "騸" in v:
        return "M", "TRUE"
    if "牡" in v:
        return "M", "FALSE"
    if "牝" in v:
        return "F", ""
    return "", ""


def kr_sex(s):
    return KR_SEX.get((s or "").strip(), ("", ""))


def kr_colour(s):
    return KR_COLOURS.get((s or "").strip(), "")


def kr_country(s):
    return KR_COUNTRIES.get((s or "").strip(), "")


# --- IFHA world rankings ---------------------------------------------------

IFHA_SURFACE = {"T": "Turf", "D": "Dirt", "A": "Synthetic"}

# IFHA distance categories, in metres. Midpoint of each published band:
# Sprint 1000-1300, Mile 1301-1899, Intermediate 1900-2100, Long 2101-2700,
# Extended 2701+. A category is a real statement of aptitude, which is what the
# Best Distance column drives, so this is a measurement rather than a guess.
IFHA_CATEGORY = {"S": "1150", "M": "1600", "I": "2000", "L": "2400", "E": "3000"}

IFHA_EX = re.compile(r"\s*\(ex [^)]*\)\s*", re.I)


def ifha_name(s):
    """Strip the country suffix and any Hong Kong former-name note."""
    return clean_name(SUFFIX.sub("", IFHA_EX.sub(" ", s or "")).strip())


def ifha_surface(s):
    return IFHA_SURFACE.get((s or "").strip().upper(), "")


def ifha_distance(s):
    """Only accept a clean single-letter category; compound values are dropped."""
    return IFHA_CATEGORY.get((s or "").strip().upper(), "")


# --- Katakana romanisation (Hepburn) ---------------------------------------

# Japanese racing names are written in katakana, which is phonetic, so unlike
# kanji it romanises deterministically. The result is an approximation of the
# official English name, not a match: JRA segments names into words, so
# サイレンススズカ is officially "Silence Suzuka" where this yields
# "Sairensusuzuka". Correct names are used wherever a crosswalk supplies one.
KANA_DIGRAPHS = {
    "キャ": "kya", "キュ": "kyu", "キョ": "kyo", "シャ": "sha", "シュ": "shu",
    "ショ": "sho", "チャ": "cha", "チュ": "chu", "チョ": "cho", "ニャ": "nya",
    "ニュ": "nyu", "ニョ": "nyo", "ヒャ": "hya", "ヒュ": "hyu", "ヒョ": "hyo",
    "ミャ": "mya", "ミュ": "myu", "ミョ": "myo", "リャ": "rya", "リュ": "ryu",
    "リョ": "ryo", "ギャ": "gya", "ギュ": "gyu", "ギョ": "gyo", "ジャ": "ja",
    "ジュ": "ju", "ジョ": "jo", "ビャ": "bya", "ビュ": "byu", "ビョ": "byo",
    "ピャ": "pya", "ピュ": "pyu", "ピョ": "pyo", "ファ": "fa", "フィ": "fi",
    "フェ": "fe", "フォ": "fo", "フュ": "fyu", "ティ": "ti", "ディ": "di",
    "デュ": "dyu", "トゥ": "tu", "ドゥ": "du", "ウィ": "wi", "ウェ": "we",
    "ウォ": "wo", "シェ": "she", "ジェ": "je", "チェ": "che", "ツァ": "tsa",
    "ツィ": "tsi", "ツェ": "tse", "ツォ": "tso", "ヴァ": "va", "ヴィ": "vi",
    "ヴェ": "ve", "ヴォ": "vo", "ヴュ": "vyu",
}
KANA = {
    "ア": "a", "イ": "i", "ウ": "u", "エ": "e", "オ": "o",
    "カ": "ka", "キ": "ki", "ク": "ku", "ケ": "ke", "コ": "ko",
    "ガ": "ga", "ギ": "gi", "グ": "gu", "ゲ": "ge", "ゴ": "go",
    "サ": "sa", "シ": "shi", "ス": "su", "セ": "se", "ソ": "so",
    "ザ": "za", "ジ": "ji", "ズ": "zu", "ゼ": "ze", "ゾ": "zo",
    "タ": "ta", "チ": "chi", "ツ": "tsu", "テ": "te", "ト": "to",
    "ダ": "da", "ヂ": "ji", "ヅ": "zu", "デ": "de", "ド": "do",
    "ナ": "na", "ニ": "ni", "ヌ": "nu", "ネ": "ne", "ノ": "no",
    "ハ": "ha", "ヒ": "hi", "フ": "fu", "ヘ": "he", "ホ": "ho",
    "バ": "ba", "ビ": "bi", "ブ": "bu", "ベ": "be", "ボ": "bo",
    "パ": "pa", "ピ": "pi", "プ": "pu", "ペ": "pe", "ポ": "po",
    "マ": "ma", "ミ": "mi", "ム": "mu", "メ": "me", "モ": "mo",
    "ヤ": "ya", "ユ": "yu", "ヨ": "yo",
    "ラ": "ra", "リ": "ri", "ル": "ru", "レ": "re", "ロ": "ro",
    "ワ": "wa", "ヰ": "i", "ヱ": "e", "ヲ": "o", "ン": "n", "ヴ": "vu",
    "ァ": "a", "ィ": "i", "ゥ": "u", "ェ": "e", "ォ": "o",
    "ャ": "ya", "ュ": "yu", "ョ": "yo",
}


def romanize_katakana(s):
    """Katakana to Hepburn. Non-katakana characters pass through unchanged."""
    if not s:
        return ""
    out = []
    i = 0
    while i < len(s):
        pair = s[i:i + 2]
        if pair in KANA_DIGRAPHS:
            out.append(KANA_DIGRAPHS[pair])
            i += 2
            continue
        ch = s[i]
        if ch == "ッ":                      # geminate: double the next consonant
            nxt = s[i + 1:i + 3]
            roman = KANA_DIGRAPHS.get(nxt) or KANA.get(s[i + 1:i + 2], "")
            if roman:
                out.append(roman[0])
            i += 1
            continue
        if ch == "ー":                      # long-vowel mark: JRA drops it
            i += 1
            continue
        out.append(KANA.get(ch, ch))
        i += 1
    return "".join(out)


def ja_horse_name(katakana, crosswalk=None):
    """Best available Latin name: a real English name if known, else romanised."""
    raw = (katakana or "").strip()
    if not raw:
        return ""
    name, country = split_suffix(raw)          # "エイシンペキン(USA)"
    if crosswalk:
        known = crosswalk.get(ja_title(name))
        if known:
            return known, country
    if not re.search(r"[\u30A0-\u30FF\u3040-\u309F]", name):
        return clean_name(name), country       # already Latin
    return smart_title(romanize_katakana(name).upper()), country


def _selfcheck():
    assert strip_wiki("[[Galileo (horse)|Galileo]]") == "Galileo"
    assert clean_name("Frankel (horse)") == "Frankel"
    assert clean_name("Abel 36474") == "Abel"
    assert clean_name("Alamode GB") == "Alamode"
    assert norm_name("Alamode GB") == norm_name("Alamode (GB)")
    assert clean_name("Sea The Stars") == "Sea The Stars"
    assert norm_name("FRANKEL (GB)") == "FRANKEL"
    assert norm_name("Adonise (TUR)") == norm_name("Adonise")
    assert clean_name("Ajuste Fiscal (URU)") == "Ajuste Fiscal"
    assert norm_name("Sadler's Wells (horse)") == "SADLERS WELLS"
    assert parse_sex("[[Stallion]]") == ("M", "FALSE")
    assert parse_sex("Gelding") == ("M", "TRUE")
    assert parse_sex("female organism") == ("F", "")
    assert parse_record("14: 14–0–0") == ("14", "14", "0", "0")
    assert parse_record("13: 9-2-1") == ("13", "9", "2", "1")
    assert parse_record("nonsense") == ("", "", "", "")
    assert parse_earnings("£2,998,302") == ("2998302", "GBP")
    assert parse_earnings("US$1,316,808") == ("1316808", "USD")
    assert parse_earnings("¥ 346,273,172 (£2,627,475)") == ("346273172", "JPY")
    assert parse_earnings("¥308,978,000 + HK$30,500,000") == ("308978000", "JPY")
    assert parse_earnings("HKD$130,250,975") == ("130250975", "HKD")
    assert parse_earnings("9: 4-2-2") == ("", "")               # a record, not earnings
    assert parse_earnings("4,116,150 francs") == ("4116150", "FRF")
    assert parse_earnings("[[French franc|F]]8,498,090 + £1,712,000") == ("8498090", "FRF")
    # A trailing code binds tighter than a franc mention later in the field.
    assert parse_earnings("453,000,800 [[JPY]]<br>[[France|FR]]: 3,800,000 "
                          "[[French franc|francs]]") == ("453000800", "JPY")
    assert parse_earnings("615,485,000 [[Yen|JPY]] + 1,000,000 "
                          "[[French franc|FF]]") == ("615485000", "JPY")
    assert parse_earnings("1,446,200 francs ($2,780)") == ("1446200", "FRF")
    assert parse_year("11 February 2008") == "2008"
    assert map_country("Great Britain") == "England"
    assert map_country("United Kingdom of Great Britain and Ireland") == "England"
    assert map_country("Kentucky, United States") == "USA"
    assert map_country("United States (Florida)") == "USA"
    assert map_country("Racine, Wisconsin, United States") == "USA"
    assert map_country("foaled in England, imported to U.S.") == "England"
    assert map_country("{{Flagicon") == ""
    assert map_country("Chestnut") == ""
    assert map_country("North America") == ""
    assert map_country("IRE") == "Ireland"
    assert map_country("Oficial flag of Japan") == "Japan"
    assert map_country("U.S") == "USA"
    assert country_from_suffix("KODI BEAR (IRE)") == "Ireland"
    assert country_from_suffix("A DAUGHTERS LOVE (GB)") == "England"
    assert country_from_suffix("Frankel") == ""
    assert split_suffix("KODI BEAR (IRE)") == ("KODI BEAR", "Ireland")
    assert split_suffix("ABBAS YOLCU", "Turkey") == ("ABBAS YOLCU", "Turkey")
    assert split_suffix("Starspangledbanner (AUS)") == ("Starspangledbanner", "Australia")
    assert split_suffix("Alamode GB") == ("Alamode", "England")
    assert split_suffix("Ms Gree GB") == ("Ms Gree", "England")
    assert suffixed("Frankel", "England") == "Frankel (GB)"
    assert suffixed("Galileo", "Ireland") == "Galileo (IRE)"
    assert suffixed("Nameless", "") == "Nameless"
    assert suffixed("A Piacere (CHI)", "Chile") == "A Piacere (CHI)"
    assert suffixed("Frankel (GB)", "England") == "Frankel (GB)"
    assert split_suffix(suffixed("Frankel", "England")) == ("Frankel", "England")
    assert smart_title("SADLER'S WELLS") == "Sadler's Wells"
    assert smart_title("A BEAR AFFAIR") == "A Bear Affair"
    assert smart_title("LOPE DE VEGA") == "Lope de Vega"
    assert smart_title("ROCK OF GIBRALTAR") == "Rock of Gibraltar"
    assert smart_title("SEA THE STARS") == "Sea the Stars"
    assert smart_title("THE TETRARCH") == "The Tetrarch"      # a particle may lead
    assert smart_title("Frankel") == "Frankel"
    # Python lowercases ASCII I to "i", not Turkish dotless "ı"; readable is enough.
    assert smart_title("AĞA BAKIRTAŞ") == "Ağa Bakirtaş"
    assert smart_title("MÜYESSER ESTHETICS") == "Müyesser Esthetics"
    assert smart_title("İ.HALİL DEMİR") == "I.Halil Demir"
    assert map_country("Japan (Yokohama, Aomori)") == "Japan"
    assert map_colour("[[Bay (color)|Bay]]") == "Bay"
    assert map_colour("[[Chestnut (coat)|Chestnut]]") == "Chestnut"
    assert map_colour("Dark Bay/Brown") == "Seal Brown"
    assert map_colour("Liver chestnut") == "Chestnut"
    assert map_colour("Gray or Roan") == "Roan"
    assert map_colour("Dark bay or brown") == "Seal Brown"
    assert map_breed("Thoroughbred") == "Thoroughbred"
    # Japanese, checked against the guide's own example values
    assert ja_english_name("{{Lang|en|Deep Impact}}<ref name=\"jbis\"/>") == "Deep Impact"
    assert ja_english_name("{{lang|en|Oguri Cap}}") == "Oguri Cap"
    assert ja_title("ディープインパクト (競走馬)") == "ディープインパクト"
    assert ja_sex("[[牡馬|牡]]") == ("M", "FALSE")
    assert ja_sex("[[牝馬|牝]]") == ("F", "")
    assert ja_sex("セン") == ("M", "TRUE")
    assert ja_colour("[[鹿毛]]") == "Bay"
    assert ja_colour("[[芦毛]]") == "Grey"
    assert ja_colour("[[黒鹿毛]]") == "Seal Brown"
    assert ja_breed("[[サラブレッド]]") == "Thoroughbred"
    assert ja_country("{{JPN}}（[[北海道]][[早来町]]）") == "Japan"
    assert ja_country("{{USA}}") == "USA"
    assert ja_country("{{UK}}") == "England"
    assert ja_country("[[日本]]（[[北海道]][[浦河町]]）") == "Japan"
    assert ja_country("[[アメリカ合衆国]]") == "USA"
    assert ja_country("[[アイルランド]]") == "Ireland"
    assert ja_record("14戦12勝<ref name=\"jbis\"/><br />13戦12勝") == ("14", "12")
    assert ja_record("32戦22勝") == ("32", "22")
    # The guide lists Deep Impact's earnings as 1,454,551,000 JPY.
    assert ja_earnings("14億5455万1000円") == "1454551000"
    assert ja_earnings("9億1251万2000円") == "912512000"
    assert ja_earnings("2281万円") == "22810000"
    assert ja_earnings("1億61866186万8000円") == ""      # malformed source value
    assert ja_earnings("21000000円") == "21000000"
    assert parse_year(strip_wiki("[[2002年]][[3月25日]]")) == "2002"
    assert map_breed("Purebred Arabian") == "Arabian"
    assert country_from_suffix("SOMETHING (TUR)") == "Turkey"
    assert race_prize("€5520", "Fairyhouse (IRE)") == (5520.0, "EUR")
    assert race_prize("14615.38", "Laurel Park (USA)") == (14615.38, "USD")
    assert race_prize("4873.5", "Catterick") == (4873.5, "GBP")
    assert race_prize("", "Catterick") == (0.0, "")
    assert parse_distance("1m") == 1609
    assert parse_distance("6f") == 1207
    assert parse_distance("1m2f") == 2012
    assert parse_distance("1m4f") == 2414   # the classic mile and a half
    assert parse_distance("1m½f") == 1710
    assert parse_distance("") == 0
    assert parse_distance("4m2f") == 0      # Grand National trip, not a flat race
    assert parse_distance("2m6f") == 4426   # about the longest real flat race
    assert race_surface("Good", "Ascot") == "Turf"
    assert race_surface("Standard", "Kempton (AW)") == "Synthetic"
    assert race_surface("Good", "Lingfield (AW)") == "Synthetic"
    assert race_surface("Fast", "Aqueduct (USA)") == "Dirt"
    assert race_surface("Standard", "Hipodromo Chile (CHI)") == "Dirt"
    assert race_surface("Slow", "Palermo") == "Dirt"
    assert race_surface("Standard", "Sha Tin (HK)") == "Dirt"
    assert race_surface("Standard", "Deauville (FR)") == "Synthetic"
    assert first_owner("Godolphin") == "Godolphin"
    assert first_owner("Yes Yes Yes, BF Sokolski, BR Broomhead, A Kheir, "
                       "Property Heavyweights No 3, Ocean Five Racing") == "Yes Yes Yes"
    assert parse_dotted_number("1.734.123") == "1734123"
    assert parse_dotted_number("100.925") == "100925"
    assert parse_dotted_number("") == ""
    assert parse_sex_code("C") == ("M", "FALSE")
    assert parse_sex_code("G") == ("M", "TRUE")
    assert parse_sex_code("F") == ("F", "")
    assert parse_sex_code("M") == ("F", "")
    assert parse_sex_code("[[Stallion]]") == ("M", "FALSE")
    assert romanize_hangul("가라카이") == "garakai"
    assert romanize_hangul("돈스피치") == "donseupichi"
    assert romanize_hangul("CARACARO") == "CARACARO"
    assert kr_name("가라카이") == "Garakai"
    assert kr_name("ADVENTURE BAY_자마") == ""
    assert kr_sex("거") == ("M", "TRUE")
    assert kr_sex_ja("牡") == ("M", "FALSE")
    assert kr_sex_ja("牝") == ("F", "")
    assert kr_sex_ja("セン") == ("M", "TRUE")
    assert kr_sex("암") == ("F", "")
    assert kr_colour("밤색") == "Chestnut"
    assert kr_colour("흑갈색") == "Seal Brown"
    assert kr_country("미국") == "USA"
    assert kr_country("한국") == "Korea"
    assert ifha_name("Lucky Nine (IRE) (ex Luck or Design)") == "Lucky Nine"
    assert ifha_name("BLACK CAVIAR") == "BLACK CAVIAR"
    assert ifha_name("Sosie (IRE)") == "Sosie"
    assert ifha_surface("T") == "Turf"
    assert ifha_surface("A") == "Synthetic"
    assert ifha_distance("S") == "1150"
    assert ifha_distance("M-I") == ""
    assert country_from_suffix("Hartnell (GB)") == "England"
    assert romanize_katakana("シンザン") == "shinzan"
    assert romanize_katakana("ステルスソニック") == "suterususonikku"
    assert romanize_katakana("ディープインパクト") == "dipuinpakuto"
    assert romanize_katakana("キタサンブラック") == "kitasanburakku"
    assert romanize_katakana("ゴールドシップ") == "gorudoshippu"   # official "Gold Ship"
    assert romanize_katakana("シンザン") == "shinzan"              # official "Shinzan", exact
    assert romanize_katakana("マアーラウ") == "maarau"
    assert ja_horse_name("シンザン", {"シンザン": "Shinzan"}) == ("Shinzan", "")
    assert ja_horse_name("ステルスソニック")[0] == "Suterususonikku"
    assert ja_horse_name("エイシンペキン(USA)")[1] == "USA"
    _t = "<table><tr><th>Horse Name</th><th>Sex</th></tr>" \
         "<tr><td>A Boy Named Susie</td><td>C</td></tr></table>"
    _rows = list(html_tables(_t))
    assert len(_rows) == 1 and _rows[0][0] == ["Horse Name", "Sex"]
    assert table_dicts(_rows[0]) == [{"Horse Name": "A Boy Named Susie", "Sex": "C"}]
    print("parsers self-check passed")


if __name__ == "__main__":
    _selfcheck()
