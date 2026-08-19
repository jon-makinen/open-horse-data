"""Join the raw sources into one CSV of real racehorses and their pedigrees."""
import collections
import csv
import json
import pathlib
import re
import sys

import parsers as P

HERE = pathlib.Path(__file__).resolve().parent
RAW = HERE / "raw"
OUT = HERE / "out"

# Retired, Stud Fee and Stud Fee Currency are not carried here. They are
# properties of a horse at a point in time rather than facts about the animal,
# so whatever consumes this file works them out itself.
# Grouped only to keep the column order readable here. The file itself has one
# header row, so it opens in a spreadsheet and filters without any fuss.
COLUMN_GROUPS = [
    ("Horse", ["Name", "Foaled", "Sex", "Gelded", "Breed", "Colour", "Country"]),
    ("Pedigree", ["Sire", "Dam", "Damsire"]),
    ("Record", ["Rating", "Rating Scale", "Starts", "Wins", "2nds", "3rds",
                "Earnings", "Currency", "Best Distance", "Surface"]),
    ("Connections", ["Owner"]),
    # Where each derived value came from. Rating carries its own scale label.
    ("Source", ["Colour Source", "Distance Source", "Earnings Source"]),
]
COLUMNS = [c for _, cols in COLUMN_GROUPS for c in cols]
OUTPUT_NAME = "horses.csv"

CURRENT_YEAR = 2026


SPEC_FIELDS = ["Foaled", "Sex", "Breed", "Colour", "Country", "Sire", "Dam"]


def load_wikidata():
    """Return {norm_name: row}.

    Two stages. Wikidata returns one row per combination of multi-valued
    properties, so first collapse to one record per QID (first value wins).
    Only then collapse to names, and where two different horses share a name
    keep the more complete one outright rather than merging their fields.
    Merging would invent a horse: Adelaide 1866 and Adelaide 2011 are not the
    same animal, and the spec needs one row per name for Sire/Dam to resolve.
    """
    per_qid = {}
    with open(RAW / "wikidata.csv", newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            name = P.clean_name(r["hLabel"])
            if not name or (name.startswith("Q") and name[1:].isdigit()):
                continue
            row = per_qid.setdefault(r["h"], {"Name": name})
            for src, dst, fn in [
                ("foaled", "Foaled", P.parse_year),
                ("died", "_died", P.parse_year),
                ("breedLabel", "Breed", P.map_breed),
                ("sireLabel", "Sire", P.clean_name),
                ("damLabel", "Dam", P.clean_name),
                ("colourLabel", "Colour", P.map_colour),
                ("countryLabel", "Country", P.map_country),
            ]:
                if not row.get(dst) and r.get(src):
                    row[dst] = fn(r[src])
            if not row.get("Sex") and r.get("sexLabel"):
                sex, gelded = P.parse_sex(r["sexLabel"])
                if sex:
                    row["Sex"], row["Gelded"] = sex, gelded

    horses, dropped = {}, 0
    for row in per_qid.values():
        key = P.norm_name(row["Name"])
        if not key:
            continue
        current = horses.get(key)
        if current is None:
            horses[key] = row
            continue
        dropped += 1
        score = sum(1 for f in SPEC_FIELDS if row.get(f))
        if score > sum(1 for f in SPEC_FIELDS if current.get(f)):
            horses[key] = row
    print(f"wikidata: {len(per_qid)} named horses, {len(horses)} unique names "
          f"({dropped} same-name duplicates dropped)")
    return horses


# Two horses of the same name foaled this far apart are two different horses.
NAMESAKE_YEARS = 5


def merge_wikipedia(horses):
    data = json.loads((RAW / "wikipedia.json").read_text(encoding="utf-8"))
    added = namesakes = 0
    for title, box in data.items():
        name = P.clean_name(box.get("horsename") or title)
        key = P.norm_name(name)
        if not key:
            continue
        row = horses.get(key)
        if row is None:
            row = horses[key] = {"Name": name}
            added += 1
        # Wikidata and Wikipedia can hold two different horses under one name:
        # the 1854 Lambourn and the 2022 Derby winner, the 1888 Kingman and the
        # 2011 one. Foaled is only written when empty, so the old year survived
        # while the modern horse's career merged in on top of it.
        foaled = P.parse_year(box.get("foaled", ""))
        known = row.get("Foaled", "")
        if (foaled.isdigit() and known.isdigit()
                and abs(int(foaled) - int(known)) > NAMESAKE_YEARS):
            namesakes += 1
            continue

        starts, wins, seconds, thirds = P.parse_record(box.get("record", ""))
        amount, currency = P.parse_earnings(box.get("earnings", ""))
        sex, gelded = P.parse_sex(box.get("sex", ""))
        for dst, value in [
            ("Foaled", foaled),
            ("Sire", P.clean_name(box.get("sire", ""))),
            ("Dam", P.clean_name(box.get("dam", ""))),
            ("Damsire", P.clean_name(box.get("damsire", ""))),
            # American articles write "color", British ones "colour". Reading
            # only one of them threw away 572 real coats and left Secretariat,
            # the most famous chestnut in racing, showing as a modelled grey.
            ("Colour", P.map_colour(box.get("colour") or box.get("color", ""))),
            ("Country", P.map_country(box.get("country", ""))),
            ("Owner", P.first_owner(box.get("owner", ""))),
            ("Breed", P.map_breed(box.get("breed", ""))),
            ("Starts", starts), ("Wins", wins), ("2nds", seconds),
            ("3rds", thirds),
            # An amount with no currency at all cannot be used: an unlabelled
            # figure reads as euros, and the pre-war French totals are francs.
            ("Earnings", amount if currency else ""),
            ("Currency", currency),
            ("Earnings Source", "published" if (amount and currency) else ""),
        ]:
            if value and not row.get(dst):
                row[dst] = value
        if sex and not row.get("Sex"):
            row["Sex"], row["Gelded"] = sex, gelded
        elif gelded == "TRUE":
            row["Gelded"] = "TRUE"
    print(f"wikipedia: {len(data)} infoboxes, {added} horses new to wikidata, "
          f"{namesakes} skipped as a different horse of the same name")
    return horses


JA_LINK = re.compile(r"\[\[([^|\]]+)(?:\|([^\]]+))?\]\]")
LATIN = re.compile(r"[A-Za-z]")


def _ja_parent(value, crosswalk):
    """Resolve a 父/母 field to an English name, or "" if it cannot be romanised.

    The field is normally a wikilink to a Japanese article title. Sometimes the
    display text is already Latin, as in [[アルザオ|Alzao]] for a foreign sire.
    """
    if not value:
        return ""
    m = JA_LINK.search(value)
    if m:
        target, display = m.group(1), m.group(2)
        if display and LATIN.search(display):
            return P.clean_name(display)
        return crosswalk.get(P.ja_title(target), "")
    plain = P.strip_wiki(value)
    if LATIN.search(plain):
        return P.clean_name(plain)
    return crosswalk.get(P.ja_title(plain), "")


def merge_ja_wikipedia(horses):
    """Japanese Wikipedia: ~5,700 racehorses, ~3,500 with no English article.

    Its infobox carries a romanised English name in the 英 field, so katakana is
    never transliterated here. Horses with no English name at all are skipped
    rather than shipped under a katakana name.

    Skipped entirely if the files are absent.
    """
    box_path = RAW / "ja_wikipedia.json"
    if not box_path.exists():
        print("ja: raw/ja_wikipedia.json not found, skipping (see README)")
        return horses

    boxes = json.loads(box_path.read_text(encoding="utf-8"))

    crosswalk = {}
    cross_path = RAW / "ja_crosswalk.csv"
    if cross_path.exists():
        with open(cross_path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                name = P.clean_name(r["enLabel"])
                if name and LATIN.search(name):
                    crosswalk[P.ja_title(r["jaTitle"])] = name
    # The 英 field is the official English name, so it outranks a Wikidata label.
    for title, box in boxes.items():
        english = P.ja_english_name(box.get("英", ""))
        if english and LATIN.search(english):
            crosswalk[P.ja_title(title)] = english

    added = enriched = skipped = 0
    for title, box in boxes.items():
        english = crosswalk.get(P.ja_title(title), "")
        if not english:
            skipped += 1
            continue
        key = P.norm_name(english)
        if not key:
            skipped += 1
            continue

        year = P.parse_year(P.strip_wiki(box.get("生", "")))
        sex, gelded = P.ja_sex(box.get("性", ""))
        starts, wins = P.ja_record(box.get("績", ""))
        earnings = P.ja_earnings(box.get("金", ""))

        row = horses.get(key)
        if row is None:
            if not (year and sex):
                skipped += 1
                continue
            row = horses[key] = {"Name": english}
            added += 1
        else:
            enriched += 1

        for dst, value in [
            ("Foaled", year),
            ("Breed", P.ja_breed(box.get("種", ""))),
            ("Colour", P.ja_colour(box.get("色", ""))),
            ("Country", P.ja_country(box.get("国", ""))),
            ("Sire", _ja_parent(box.get("父", ""), crosswalk)),
            ("Dam", _ja_parent(box.get("母", ""), crosswalk)),
            ("Damsire", _ja_parent(box.get("母父", ""), crosswalk)),
            ("Owner", P.clean_name(P.ja_first(box.get("主", "")))),
            ("Starts", starts), ("Wins", wins), ("Earnings", earnings),
            ("Earnings Source", "published" if earnings else ""),
        ]:
            if value and not row.get(dst):
                row[dst] = value
        if earnings and not row.get("Currency"):
            row["Currency"] = "JPY"
        if sex and not row.get("Sex"):
            row["Sex"], row["Gelded"] = sex, gelded
        elif gelded == "TRUE":
            row["Gelded"] = "TRUE"
        if box.get("死") and not row.get("_died"):
            row["_died"] = "1"

    print(f"ja: {len(boxes)} infoboxes, added {added}, enriched {enriched}, "
          f"skipped {skipped} (no English name)")
    return horses


# Currencies the spec understands. Anything else it treats as 1:1 with euros,
# which would turn 1.7m Turkish lira into 1.7m euros, so those are left blank.
SPEC_CURRENCIES = {"EUR", "USD", "GBP", "AUD", "CAD", "JPY", "HKD", "AED", "JMD"}


def merge_hkjc(horses):
    """Hong Kong Jockey Club: ~1,258 horses in training, richest single page.

    Current Rating IS imported as the pound scale. Nine HKJC horses also carry
    an IFHA world ranking (Ka Ying Rising, Romantic Warrior, Lucky Sweynesse and
    friends) and the median gap between the two figures is about 3 points, so
    the scales agree. The outliers are horses past their peak, since HKJC
    publishes a current mark and IFHA a peak one.

    Stakes are HKD, which the spec understands, so earnings are kept.

    Hong Kong is overwhelmingly geldings, which skews the sex balance.
    """
    path = RAW / "hkjc.json"
    if not path.exists():
        print("hkjc: raw/hkjc.json not found, skipping (see README)")
        return horses

    data = json.loads(path.read_text(encoding="utf-8"))
    added = enriched = 0
    for horseid, h in data.items():
        name = P.smart_title(P.clean_name(h.get("name", "")))
        key = P.norm_name(name)
        if not key:
            continue

        origin, _, age = (h.get("Country of Origin / Age") or "").partition("/")
        colour, _, sex_raw = (h.get("Colour / Sex") or "").partition("/")
        age = age.strip()
        year = str(CURRENT_YEAR - int(age)) if age.isdigit() else ""
        sex, gelded = P.parse_sex(sex_raw)

        # "7-3-6-55" is wins-2nds-3rds-starts, in that order.
        record = [p for p in (h.get("No. of 1-2-3-Starts*") or "").split("-")]
        wins, seconds, thirds, starts = (record + ["", "", "", ""])[:4]

        row = horses.get(key)
        if row is None:
            if not (sex and year):
                continue
            row = horses[key] = {"Name": name, "Foaled": year, "Sex": sex,
                                 "Gelded": gelded, "Breed": "Thoroughbred",
                                 "_active": True}
            added += 1
        else:
            enriched += 1
            if gelded == "TRUE":
                row["Sex"], row["Gelded"] = "M", "TRUE"

        row["_country_birth"] = True
        for dst, value in [
            ("Colour", P.map_colour(colour)),
            ("Country", P.SUFFIX_COUNTRY.get(origin.strip().upper(), "")),
            ("Sire", P.smart_title(P.clean_name(h.get("Sire", "")))),
            ("Dam", P.smart_title(P.clean_name(h.get("Dam", "")))),
            ("Owner", P.first_owner(h.get("Owner", ""))),
            ("Starts", starts.strip()), ("Wins", wins.strip()),
            ("2nds", seconds.strip()), ("3rds", thirds.strip()),
        ]:
            if value and value.strip() and not row.get(dst):
                row[dst] = value.strip()

        rating = (h.get("Current Rating") or "").strip()
        if rating.isdigit() and int(rating) >= 40 and not row.get("Rating"):
            row["Rating"] = rating
            row["Rating Scale"] = "BHA"

        stakes = P.parse_earnings(h.get("Total Stakes*", ""))[0]
        if stakes and not row.get("Earnings"):
            row["Earnings"] = stakes
            row["Currency"] = "HKD"
            row["Earnings Source"] = "published"

    print(f"hkjc: {len(data)} horses, enriched {enriched}, added {added}")
    return horses


JA_JUMPS = re.compile(r"障害|障碍")


DELTA_FILES = ("archive_1988-2004/archive_1988-2004/1988-2004.csv",
               "archive_2005-2014/archive_2005-2014/2005-2014.csv",
               "form_2015-present/form_2015-present/raceform.csv")
DELTA_JUMPS = re.compile(r"hurdle|chase|nh flat|bumper", re.I)

# Filtering on race type is necessary but not sufficient. A jumps horse running
# on the flat still carries its CHASE mark in the `or` column: Galopin Des
# Champs has three Flat rows, one of them showing 175. The highest flat mark
# anywhere in this data is 142 (Ka Ying Rising; Frankel and Flightline are 140),
# so anything above that is a jumps rating that leaked through and is rejected
# rather than imported.
FLAT_RATING_MAX = 142


def merge_deltaromeo(horses):
    """UK and Ireland 1988-2026 with sire, dam, DAMSIRE, sex, owner and OR.

    Licence is CDLA-Sharing-1.0, a real open data licence permitting commercial
    redistribution under the same terms. That makes this the only large race
    archive here that could ship in a paid build, unlike the CC BY-NC hwaitt set
    and the unlicensed Japanese one.

    It carries a sex column, which hwaitt lacks, so horses can be ADDED and not
    only enriched. It also reaches back to 1988 against a file that is otherwise
    89% post-2000.

    Flat races only, on the `type` column. This is a flat-racing dataset, and a
    chase mark is not comparable to a flat one, so mixing them would corrupt the
    rating column.
    """
    path = RAW / "deltaromeo.zip"
    if not path.exists():
        print("delta: raw/deltaromeo.zip not found, skipping (see README)")
        return horses

    import io
    import zipfile

    agg = {}
    ped = {}
    with zipfile.ZipFile(path) as z:
        present = set(z.namelist())
        for member in DELTA_FILES:
            if member not in present:
                print(f"delta: {member} missing from the archive, skipping it")
                continue
            with z.open(member) as fh:
                reader = csv.DictReader(io.TextIOWrapper(fh, "utf-8", errors="replace"))
                reader.fieldnames = [(f or "").strip().lower()
                                     for f in (reader.fieldnames or [])]
                for r in reader:
                    # 1988-2004.csv repeats its header as the first data row.
                    if (r.get("date") or "") == "date":
                        continue
                    # The type column is not always right: the Hennessy Gold Cup
                    # and the Grand Military Gold Cup are steeplechases tagged
                    # as Flat, so the race name is checked as well.
                    jumps = bool(DELTA_JUMPS.search(r.get("type") or "")
                                 or DELTA_JUMPS.search(r.get("race_name") or ""))
                    # Horse, sire and dam all carry the country of birth:
                    # "Definitly Red (IRE)", sire "Definite Article (GB)".
                    name, country = P.split_suffix(r.get("horse", ""))
                    key = P.norm_name(name)
                    if not key:
                        continue
                    # A hurdler's parents are as real as a flat horse's, so the
                    # pedigree is read from every race while the record below
                    # stays flat only. 116,934 horses here never ran on the
                    # flat, and dropping their rows dropped their dams with
                    # them. They are never ADDED from a jump race: a flat-only
                    # start count would read zero for a horse that ran 40 times.
                    if jumps:
                        p = ped.setdefault(key, {})
                        for col in ("sire", "dam", "damsire"):
                            if not p.get(col) and (r.get(col) or "").strip():
                                p[col], p[col + "_c"] = P.split_suffix(r[col])
                        year = (r.get("date") or "")[:4]
                        try:
                            age = int(float(r.get("age") or 0))
                        except ValueError:
                            age = 0
                        if year.isdigit() and 1 <= age <= 20:
                            born = str(int(year) - age)
                            if not p.get("foaled") or born < p["foaled"]:
                                p["foaled"] = born
                        continue
                    a = agg.get(key)
                    if a is None:
                        a = agg[key] = {"name": name, "st": 0, "w": 0, "s2": 0,
                                        "s3": 0, "or": 0, "sire": "", "dam": "",
                                        "damsire": "", "sex": "", "foaled": "",
                                        "owner": "", "country": country,
                                        "sire_c": "", "dam_c": "", "purse": collections.Counter(),
                                        "wd": 0.0, "wn": 0, "ad": 0.0, "an": 0,
                                        "surf": collections.Counter()}
                    if not a["country"] and country:
                        a["country"] = country
                    a["st"] += 1
                    try:
                        pos = int(r.get("pos") or 0)
                    except ValueError:
                        pos = 0
                    if pos == 1:
                        a["w"] += 1
                    elif pos == 2:
                        a["s2"] += 1
                    elif pos == 3:
                        a["s3"] += 1
                    try:
                        a["or"] = max(a["or"], int(float(r.get("or") or 0)))
                    except ValueError:
                        pass
                    for src, dst in (("sex", "sex"), ("owner", "owner")):
                        if not a[dst] and (r.get(src) or "").strip():
                            a[dst] = r[src].strip()
                    if not a["sire"] and (r.get("sire") or "").strip():
                        a["sire"], a["sire_c"] = P.split_suffix(r["sire"])
                    if not a["dam"] and (r.get("dam") or "").strip():
                        a["dam"], a["dam_c"] = P.split_suffix(r["dam"])
                    if not a["damsire"] and (r.get("damsire") or "").strip():
                        a["damsire"] = P.split_suffix(r["damsire"])[0]
                    metres = P.parse_distance(r.get("dist"))
                    if metres:
                        a["ad"] += metres
                        a["an"] += 1
                        if pos == 1:
                            a["wd"] += metres
                            a["wn"] += 1
                    surface = P.race_surface(r.get("going"), r.get("course"))
                    if surface:
                        a["surf"][surface] += 1

                    # Prize is this runner's own winnings for the race, not the
                    # race total, so a career sum is just an addition.
                    amount, cur = P.race_prize(r.get("prize"), r.get("course"))
                    if amount and cur:
                        a["purse"][cur] += amount

                    year = (r.get("date") or "")[:4]
                    try:
                        age = int(float(r.get("age") or 0))
                    except ValueError:
                        age = 0
                    if year.isdigit() and 1 <= age <= 20:
                        born = str(int(year) - age)
                        if not a["foaled"] or born < a["foaled"]:
                            a["foaled"] = born

    added = enriched = skipped = 0
    for key, a in agg.items():
        sex, gelded = P.parse_sex_code(a["sex"])
        row = horses.get(key)
        if row is None:
            if not (sex and a["foaled"]):
                skipped += 1
                continue
            row = horses[key] = {"Name": P.smart_title(a["name"]),
                                 "Foaled": a["foaled"], "Sex": sex,
                                 "Gelded": gelded, "Breed": "Thoroughbred"}
            row["_country_birth"] = True
            added += 1
        else:
            ours = row.get("Foaled", "")
            if ours.isdigit() and a["foaled"] and abs(int(ours) - int(a["foaled"])) > 1:
                skipped += 1
                continue
            enriched += 1
            if gelded == "TRUE":
                row["Sex"], row["Gelded"] = "M", "TRUE"

        row.setdefault("_sire_country", a["sire_c"])
        row.setdefault("_dam_country", a["dam_c"])
        for dst, value in [
            ("Foaled", a["foaled"]),
            ("Country", a["country"]),
            ("Sire", P.smart_title(P.clean_name(a["sire"]))),
            ("Dam", P.smart_title(P.clean_name(a["dam"]))),
            ("Damsire", P.smart_title(P.clean_name(a["damsire"]))),
            ("Owner", P.first_owner(a["owner"])),
            ("Starts", str(a["st"])), ("Wins", str(a["w"])),
            ("2nds", str(a["s2"])), ("3rds", str(a["s3"])),
        ]:
            if value and not row.get(dst):
                row[dst] = value
        # Best Distance is where the horse actually won, falling back to where
        # it ran. A horse that only ever won over five furlongs is a sprinter
        # whatever else it contested.
        if not row.get("Best Distance"):
            if a["wn"]:
                row["Best Distance"] = str(round(a["wd"] / a["wn"]))
                row["Distance Source"] = "raced"
            elif a["an"]:
                row["Best Distance"] = str(round(a["ad"] / a["an"]))
                row["Distance Source"] = "raced"
        if a["surf"] and not row.get("Surface"):
            row["Surface"] = a["surf"].most_common(1)[0][0]

        # A horse can earn in several currencies across a career; the spec has
        # one Earnings column, so report the currency it earned most in.
        if a["purse"] and not row.get("Earnings"):
            cur, total = a["purse"].most_common(1)[0]
            if total >= 1 and cur in SPEC_CURRENCIES:
                row["Earnings"] = str(int(round(total)))
                row["Currency"] = cur
                row["Earnings Source"] = "summed"

        if 40 <= a["or"] <= FLAT_RATING_MAX and not row.get("Rating"):
            row["Rating"] = str(a["or"])
            row["Rating Scale"] = "BHA"

    jump_filled = jump_skipped = 0
    for key, p in ped.items():
        row = horses.get(key)
        if row is None:
            continue
        # Same guard as the flat merge: British jump racing shares names with
        # horses everywhere, and a wrong dam is worse than no dam.
        ours, theirs = row.get("Foaled", ""), p.get("foaled", "")
        if ours.isdigit() and theirs and abs(int(ours) - int(theirs)) > 1:
            jump_skipped += 1
            continue
        touched = False
        for col in ("Sire", "Dam", "Damsire"):
            value = P.smart_title(P.clean_name(p.get(col.lower(), "")))
            if value and not row.get(col):
                row[col] = value
                touched = True
        row.setdefault("_sire_country", p.get("sire_c", ""))
        row.setdefault("_dam_country", p.get("dam_c", ""))
        jump_filled += touched
    print(f"delta: {len(agg)} horses in archive, added {added}, "
          f"enriched {enriched}, {skipped} skipped; "
          f"{jump_filled} more got a pedigree from their jump races, "
          f"{jump_skipped} of those skipped on a foaling-year mismatch")
    return horses


def merge_nar(horses):
    """Japanese NAR and JRA race results 2010-2021: ~90,600 horses WITH pedigree.

    This is the only reachable Japanese source that carries sire and dam. Every
    other one is either licence-blocked (JBIS, JRA-VAN) or results-only
    (takamotoki, which has no pedigree at all).

    Names are katakana. Three ways to a Latin name, best first:
      1. the horse's JBIS id, joined to Wikidata's P10785, giving the official
         English name. An ID join, so no same-name risk.
      2. the ja.wikipedia crosswalk, by katakana title.
      3. Hepburn romanisation, which is an approximation: Silence Suzuka comes
         out as Sairensusuzuka. The famous horses are the loanword-named ones
         and they resolve by 1 or 2, so romanisation mostly lands on genuinely
         Japanese names where it reads correctly.

    LICENCE: "Unknown" on Kaggle, which grants nothing explicitly. Community
    builds only. Delete raw/ayuser_japan.zip to build without it.
    """
    path = RAW / "ayuser_japan.zip"
    if not path.exists():
        print("nar: raw/ayuser_japan.zip not found, skipping (see README)")
        return horses

    import io
    import zipfile

    jbis = {}
    jpath = RAW / "jbis_crosswalk.csv"
    if jpath.exists():
        with open(jpath, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("jbis") and r.get("enLabel"):
                    jbis[r["jbis"].strip()] = P.clean_name(r["enLabel"])

    kana = {}
    cpath = RAW / "ja_crosswalk.csv"
    if cpath.exists():
        with open(cpath, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                kana[P.ja_title(r["jaTitle"])] = P.clean_name(r["enLabel"])

    # The 英 field on a ja.wikipedia infobox is the official English name, and
    # merge_ja_wikipedia already uses it. Without it here the same horse lands
    # twice: once as "A Shin Erwin" from the infobox and once as "Eishineruvin"
    # from romanising the katakana in this archive.
    bpath = RAW / "ja_wikipedia.json"
    if bpath.exists():
        for title, box in json.loads(bpath.read_text(encoding="utf-8")).items():
            english = P.ja_english_name(box.get("英", ""))
            if not english:
                continue
            kana.setdefault(P.ja_title(title), english)
            named = P.ja_title(P.strip_wiki(box.get("名", "")))
            if named:
                kana.setdefault(named, english)

    def resolve(name, hid):
        """Official English name if either crosswalk knows it, else romanised."""
        known = jbis.get((hid or "").strip())
        if known:
            return known, P.split_suffix(name)[1]
        return P.ja_horse_name(name, kana)

    agg = {}
    with zipfile.ZipFile(path) as z:
        member = next(n for n in z.namelist() if n.endswith(".csv"))
        with z.open(member) as fh:
            for r in csv.DictReader(io.TextIOWrapper(fh, "utf-8", errors="replace")):
                if JA_JUMPS.search(r.get("race_class") or ""):
                    continue                      # flat-racing dataset
                hid = (r.get("horse_id") or "").strip()
                raw_name = (r.get("horse_name") or "").strip()
                if not raw_name:
                    continue
                key = hid or raw_name
                a = agg.get(key)
                if a is None:
                    a = agg[key] = {"name": raw_name, "id": hid, "st": 0, "w": 0,
                                    "s2": 0, "s3": 0, "sex": "", "foaled": "",
                                    "sire": "", "sire_id": "", "dam": "",
                                    "dam_id": "", "surface": "", "purse": 0.0,
                                    "wd": 0.0, "wn": 0, "ad": 0.0, "an": 0}
                a["st"] += 1
                try:
                    place = int(r.get("place") or 0)
                except ValueError:
                    place = 0
                if place == 1:
                    a["w"] += 1
                elif place == 2:
                    a["s2"] += 1
                elif place == 3:
                    a["s3"] += 1
                # prize1..prize5 are the race's prizes for positions 1 to 5, so
                # this runner earned the one matching where it finished.
                if 1 <= place <= 5:
                    # Prizes are written "21,000,000円" but sometimes in myriad
                    # form ("1,000万円"), which a plain digit strip turns into
                    # 1000 instead of 10,000,000.
                    won = P.ja_earnings(r.get(f"prize{place}") or "")
                    if won:
                        a["purse"] += int(won)

                m = re.match(r"(\d+)", (r.get("distance") or "").strip())
                if m:
                    metres = int(m.group(1))
                    if 400 <= metres <= 7000:
                        a["ad"] += metres
                        a["an"] += 1
                        if place == 1:
                            a["wd"] += metres
                            a["wn"] += 1

                a["sex"] = a["sex"] or (r.get("sex") or "").strip()
                for src, dst in (("sire", "sire"), ("dam", "dam"),
                                 ("sire_id", "sire_id"), ("dam_id", "dam_id")):
                    if not a[dst] and (r.get(src) or "").strip():
                        a[dst] = r[src].strip()
                if not a["surface"]:
                    track = (r.get("track") or "").strip()
                    a["surface"] = "Dirt" if "ダ" in track else "Turf" if "芝" in track else ""
                date, age = (r.get("date") or "")[:4], (r.get("age") or "").strip()
                if date.isdigit() and age.isdigit() and 1 <= int(age) <= 20:
                    born = str(int(date) - int(age))
                    if not a["foaled"] or born < a["foaled"]:
                        a["foaled"] = born

    added = enriched = skipped = 0
    for a in agg.values():
        name, country = resolve(a["name"], a["id"])
        key = P.norm_name(name)
        sex, gelded = P.kr_sex_ja(a["sex"])
        if not key or not (sex and a["foaled"]):
            skipped += 1
            continue

        row = horses.get(key)
        if row is None:
            row = horses[key] = {"Name": name, "Foaled": a["foaled"], "Sex": sex,
                                 "Gelded": gelded, "Breed": "Thoroughbred"}
            added += 1
        else:
            ours = row.get("Foaled", "")
            if ours.isdigit() and abs(int(ours) - int(a["foaled"])) > 1:
                skipped += 1
                continue
            enriched += 1

        sire_name = resolve(a["sire"], a["sire_id"])[0] if a["sire"] else ""
        dam_name = resolve(a["dam"], a["dam_id"])[0] if a["dam"] else ""
        row["_country_birth"] = True
        for dst, value in [
            ("Country", country or "Japan"),
            ("Sire", sire_name), ("Dam", dam_name),
            ("Starts", str(a["st"])), ("Wins", str(a["w"])),
            ("2nds", str(a["s2"])), ("3rds", str(a["s3"])),
            ("Surface", a["surface"]),
            ("Earnings", str(int(a["purse"])) if a["purse"] else ""),
            ("Earnings Source", "summed" if a["purse"] else ""),
            ("Best Distance", str(round(a["wd"] / a["wn"])) if a["wn"]
             else (str(round(a["ad"] / a["an"])) if a["an"] else "")),
            ("Distance Source", "raced" if (a["wn"] or a["an"]) else ""),
        ]:
            if value and not row.get(dst):
                row[dst] = value
        if a["purse"] and not row.get("Currency"):
            row["Currency"] = "JPY"
        if gelded == "TRUE":
            row["Sex"], row["Gelded"] = "M", "TRUE"

    print(f"nar: {len(agg)} horses in archive, added {added}, enriched {enriched}, "
          f"{skipped} skipped")
    return horses


def merge_kaggle(horses):
    """hwaitt/horse-racing: 4.1m race-runner rows over 1990-2020, ~371k horses.

    ENRICHMENT ONLY. The horses_*.csv files carry no sex column and the spec
    makes Sex required, so no new rows are created here. That is a feature: the
    raw set is 371,287 horses and importing it wholesale would bury the world.

    LICENCE: CC BY-NC 4.0, non-commercial, attribution required. Fine for a free
    community mod, NOT fine shipped inside a paid game. Delete raw/hwaitt.zip to
    build without it.

    Only the OR column is read. RPR and TR are Racing Post proprietary derived
    data, the same category Timeform was excluded for.

    FLAT RACES ONLY. The archive covers British racing, which is over a quarter
    National Hunt, and a chase mark is not comparable to a flat one: including
    them put Sprinter Sacre on 188 above every flat horse alive. The races_*.csv
    `hurdles` column is empty for flat and populated for jumps.
    """
    path = RAW / "hwaitt.zip"
    if not path.exists():
        print("kaggle: raw/hwaitt.zip not found, skipping (see README)")
        return horses

    import io
    import zipfile

    agg = {}
    ped = {}
    with zipfile.ZipFile(path) as z:
        # The hurdles column alone is not enough: it is empty for steeplechases,
        # which have fences rather than hurdles, so 200+ chases per season leak
        # through and put Desert Orchid on 185 above every flat horse alive.
        jumps = re.compile(r"\b(chase|hurdle|steeple|bumper|n\.?h\.? flat)", re.I)
        flat_rids = set()
        for member in sorted(n for n in z.namelist() if n.startswith("races_")):
            with z.open(member) as fh:
                for r in csv.DictReader(io.TextIOWrapper(fh, "utf-8", errors="replace")):
                    if (r.get("hurdles") or "").strip():
                        continue
                    if jumps.search(r.get("title") or ""):
                        continue
                    flat_rids.add(r.get("rid"))
        print(f"kaggle: {len(flat_rids)} flat races (jumps excluded)")

        for member in sorted(n for n in z.namelist() if n.startswith("horses_")):
            year = int(re.search(r"(\d{4})", member).group(1))
            with z.open(member) as fh:
                for r in csv.DictReader(io.TextIOWrapper(fh, "utf-8", errors="replace")):
                    key = P.norm_name(r.get("horseName") or "")
                    if not key:
                        continue
                    # A hurdler's dam is still his dam, so pedigree is read
                    # from every race here while the record stays flat only.
                    p = ped.setdefault(key, {})
                    for src, dst in (("father", "sire"), ("mother", "dam"),
                                     ("gfather", "damsire")):
                        v = (r.get(src) or "").strip()
                        if v and not p.get(dst):
                            p[dst] = v
                    try:
                        p_age = int(float(r.get("age") or 0))
                    except ValueError:
                        p_age = 0
                    if 1 <= p_age <= 20:
                        born = str(year - p_age)
                        if not p.get("foaled") or born < p["foaled"]:
                            p["foaled"] = born
                    if r.get("rid") not in flat_rids:
                        continue
                    a = agg.get(key)
                    if a is None:
                        a = agg[key] = {"st": 0, "w": 0, "s2": 0, "s3": 0,
                                        "or": 0, "foaled": ""}
                    a["st"] += 1
                    try:
                        pos = int(r.get("position") or 0)
                    except ValueError:
                        pos = 0
                    if pos == 1:
                        a["w"] += 1
                    elif pos == 2:
                        a["s2"] += 1
                    elif pos == 3:
                        a["s3"] += 1
                    try:
                        a["or"] = max(a["or"], int(float(r.get("OR") or 0)))
                    except ValueError:
                        pass
                    # The age column is written as a float string ("5.0"), so
                    # isdigit() is False on every one of the 4.1m rows.
                    try:
                        age = int(float(r.get("age") or 0))
                    except ValueError:
                        age = 0
                    if 1 <= age <= 20:
                        born = str(year - age)
                        if not a["foaled"] or born < a["foaled"]:
                            a["foaled"] = born

    REFERENCE_RATINGS.extend(a["or"] for a in agg.values() if a["or"] > 0)
    print(f"kaggle: {len(REFERENCE_RATINGS)} official ratings kept as the "
          f"reference population for unknown horses")

    enriched = skipped = 0
    for key, a in agg.items():
        row = horses.get(key)
        if row is None:
            continue
        # Same name, different horse. The archive is British racing and holds
        # 322k horses, so collisions with famous names are common: a British
        # "Deep Impact" handed the Japanese one an official mark of 88. Require
        # the foaling years to agree before trusting the match.
        ours, theirs = row.get("Foaled", ""), a["foaled"]
        if ours and theirs and abs(int(ours) - int(theirs)) > 1:
            skipped += 1
            continue
        enriched += 1
        for dst, value in [
            ("Foaled", a["foaled"]),
            ("Starts", str(a["st"])), ("Wins", str(a["w"])),
            ("2nds", str(a["s2"])), ("3rds", str(a["s3"])),
        ]:
            if value and not row.get(dst):
                row[dst] = value
        if 40 <= a["or"] <= FLAT_RATING_MAX and not row.get("Rating"):
            row["Rating"] = str(a["or"])
            row["Rating Scale"] = "BHA"

    ped_filled = ped_skipped = 0
    for key, p in ped.items():
        row = horses.get(key)
        if row is None:
            continue
        ours, theirs = row.get("Foaled", ""), p.get("foaled", "")
        if ours.isdigit() and theirs and abs(int(ours) - int(theirs)) > 1:
            ped_skipped += 1
            continue
        touched = False
        for col in ("Sire", "Dam", "Damsire"):
            value = P.smart_title(P.clean_name(p.get(col.lower(), "")))
            if value and not row.get(col):
                row[col] = value
                touched = True
        ped_filled += touched
    print(f"kaggle: {len(agg)} horses in archive, enriched {enriched}, "
          f"{skipped} skipped on a foaling-year mismatch; "
          f"{ped_filled} got a pedigree from {len(ped)} horses seen in any "
          f"race, {ped_skipped} skipped on the year")
    return horses


def merge_ifha(horses):
    """IFHA Longines World's Best Racehorse Rankings, 2013-2026, ~2,500 horses.

    The only imported ratings besides Britain and Ireland. IFHA classifications
    are the international pound scale, the same units as a BHA mark, so they can
    share the BHA scale label. Turkey, Hong Kong and Korea publish local scales
    and are deliberately not imported as ratings.

    A horse appears in many editions; the peak rating is kept.
    """
    path = RAW / "ifha.json"
    if not path.exists():
        print("ifha: raw/ifha.json not found, skipping (see README)")
        return horses

    rows = json.loads(path.read_text(encoding="utf-8"))
    best = {}
    for r in rows:
        name = P.ifha_name(r.get("horse", ""))
        key = P.norm_name(name)
        if not key:
            continue
        try:
            rating = int(float(r.get("rating") or 0))
        except ValueError:
            rating = 0
        cur = best.get(key)
        if cur is None or rating > cur["rating"]:
            best[key] = {"name": name, "rating": rating, "row": r}
        elif not cur["row"].get("trained"):
            cur["row"] = r

    added = enriched = 0
    for key, item in best.items():
        r = item["row"]
        sex, gelded = P.parse_sex_code(r.get("sex", ""))
        year = (r.get("yof") or "").strip()

        row = horses.get(key)
        if row is None:
            if not (sex and year.isdigit()):
                continue
            row = horses[key] = {"Name": P.smart_title(item["name"]),
                                 "Foaled": year, "Sex": sex, "Gelded": gelded,
                                 "Breed": "Thoroughbred"}
            added += 1
        else:
            enriched += 1
            if gelded == "TRUE":
                row["Sex"], row["Gelded"] = "M", "TRUE"

        for dst, value in [
            ("Foaled", year if year.isdigit() else ""),
            ("Country", P.SUFFIX_COUNTRY.get((r.get("bred") or "").strip().upper(), "")),
            ("Surface", P.ifha_surface(r.get("surface", ""))),
            ("Best Distance", P.ifha_distance(r.get("cat", ""))),
            ("Distance Source", "category" if P.ifha_distance(r.get("cat", "")) else ""),
            ("Owner", P.first_owner(r.get("owner", ""))),
        ]:
            if value and not row.get(dst):
                row[dst] = value
        if item["rating"] >= 100 and not row.get("Rating"):
            row["Rating"] = str(item["rating"])
            row["Rating Scale"] = "BHA"

    print(f"ifha: {len(rows)} ranking rows, {len(best)} distinct horses, "
          f"enriched {enriched}, added {added}")
    return horses


def merge_kra(horses):
    """Korean Racing Authority studbook: six registers, ~34,000 rows.

    Licence is KOGL Type 0, "no restriction on scope of use", commercial
    included. Names are 100% Hangul, so they are romanised; the results are
    readable approximations, not official English names.

    youngstock is skipped: it has no horse-name column, only dam and sire.
    Ratings are not published in these registers, so nothing is imported there.
    """
    path = RAW / "kra.json"
    if not path.exists():
        print("kra: raw/kra.json not found, skipping (see README)")
        return horses

    data = json.loads(path.read_text(encoding="utf-8"))
    added = enriched = mismatched = 0

    def touch(raw_name, born=""):
        nonlocal added, enriched, mismatched
        name = P.kr_name(raw_name)
        key = P.norm_name(name)
        if not key:
            return None, None
        row = horses.get(key)
        if row is None:
            row = horses[key] = {"Name": name, "Breed": "Thoroughbred"}
            added += 1
            return key, row
        ours = row.get("Foaled", "")
        if ours.isdigit() and born.isdigit() and abs(int(ours) - int(born)) > 1:
            mismatched += 1
            return None, None
        enriched += 1
        return key, row

    def put(row, dst, value):
        if value and not row.get(dst):
            row[dst] = value

    for reg in ("racehorses", "stallions", "broodmares", "retirements", "geldings"):
        for r in data.get(reg, []):
            key, row = touch(r.get("마명", ""), (r.get("출생일") or "")[:4])
            if row is None:
                continue
            put(row, "Foaled", (r.get("출생일") or "")[:4])
            put(row, "Colour", P.kr_colour(r.get("털색", "")))
            put(row, "Country", P.kr_country(r.get("생산국", "")))
            row["_country_birth"] = True
            put(row, "Sire", P.kr_name(r.get("부마명", "")))
            put(row, "Dam", P.kr_name(r.get("모마명", "")))
            put(row, "Owner", P.kr_name(r.get("마주") or r.get("소유자") or ""))

            sex, gelded = P.kr_sex(r.get("성별", ""))
            if reg == "geldings":
                row["Sex"], row["Gelded"] = "M", "TRUE"
            elif gelded == "TRUE":
                row["Sex"], row["Gelded"] = "M", "TRUE"
            elif sex and not row.get("Sex"):
                row["Sex"], row["Gelded"] = sex, gelded
            elif reg == "stallions" and not row.get("Sex"):
                row["Sex"], row["Gelded"] = "M", "FALSE"
            elif reg == "broodmares" and not row.get("Sex"):
                row["Sex"] = "F"

            if reg == "retirements" and r.get("퇴역일"):
                row["Retired"] = "TRUE"

    print(f"kra: {sum(len(v) for v in data.values())} rows, enriched {enriched}, "
          f"added {added}, {mismatched} skipped as a different horse")
    return horses


def merge_tjk(horses):
    """Turkish Jockey Club: ~113,000 horses, name/sex/breed/colour/sire/dam/country.

    A quarter of the file is Purebred Arabian, which makes this the largest free
    Arabian source found anywhere.

    The HP column is imported under its own `TJK` scale label, never as `BHA`.
    It is a Turkish handicap running 0-99 and it cannot be converted: 105 TJK
    names also appear in IFHA, but the correlation between the two figures is
    r=0.11, i.e. none. Those "matches" are Turkish horses sharing a name with
    Runhappy, Camelot and Brando, not the same animals. Turkish marks also sit
    on a different distribution, median 35 against 72, so no offset lines them
    up. They are labelled `TJK` and left alone.

    Earnings are dropped: they are in lira, which the spec would read as euros
    at 1:1.
    """
    path = RAW / "tjk.json"
    if not path.exists():
        print("tjk: raw/tjk.json not found, skipping (see README)")
        return horses

    rows = json.loads(path.read_text(encoding="utf-8"))
    added = enriched = mismatched = 0
    for r in rows:
        raw_name = (r.get("Horse Name") or "").strip()
        dead = "(Dead)" in raw_name
        name = P.smart_title(P.clean_name(re.sub(r"\(Dead\)", "", raw_name)).strip())
        key = P.norm_name(name)
        if not key:
            continue

        sex, gelded = P.parse_sex(r.get("Sex", ""))
        age = (r.get("Age") or "").strip()
        year = str(CURRENT_YEAR - int(age)) if age.isdigit() else ""
        # "LADY MARIA - OCEAN BLUE" is dam then damsire in one cell.
        dam_raw, sire_raw = (r.get("Dam") or "").split(" - ")[0], r.get("Sire") or ""
        dam_n, dam_c = P.split_suffix(dam_raw, "Turkey")
        sire_n, sire_c = P.split_suffix(sire_raw, "Turkey")
        dam = P.smart_title(dam_n)
        # "ADNAN KARAKEÇİ (%75) - ZAFER GEZİCİ": first owner, share stripped.
        owner = P.first_owner(
            re.sub(r"\s*\(%\d+\)", "", (r.get("Owner") or "")).split(" - ")[0])

        row = horses.get(key)
        if row is None:
            if not (sex and year):
                continue
            row = horses[key] = {"Name": name, "Foaled": year, "Sex": sex,
                                 "Gelded": gelded}
            added += 1
        else:
            # Same name, different horse. Turkish racing is a modern register,
            # so a row already dated to the 18th century is not the horse this
            # file means: Eclipse (1764) and Careless (1693) were being handed
            # Turkish identity and TJK marks. Age is only present on ~63% of
            # rows, so an absent year is treated as no evidence and the older
            # row wins.
            ours = row.get("Foaled", "")
            if ours.isdigit():
                if not year or abs(int(ours) - int(year)) > 1:
                    mismatched += 1
                    continue
            enriched += 1

        row["_country_birth"] = True
        for dst, value in [
            ("Foaled", year),
            ("Breed", P.map_breed(r.get("Breed", ""))),
            ("Colour", P.map_colour(r.get("Colour", ""))),
            ("Country", P.SUFFIX_COUNTRY.get((r.get("Country") or "").strip().upper(), "")),  # TJK: birth
            ("Sire", P.smart_title(sire_n)),
            ("Dam", dam),
            ("Owner", P.smart_title(owner)),
        ]:
            if value and not row.get(dst):
                row[dst] = value
        row.setdefault("_sire_country", sire_c)
        row.setdefault("_dam_country", dam_c)
        if sex and not row.get("Sex"):
            row["Sex"], row["Gelded"] = sex, gelded
        hp = (r.get("HP") or "").strip()
        if hp.isdigit() and int(hp) > 0:
            # Stashed, not applied. TJK merges early but is the least reliable
            # rating source, and whichever merge runs first would otherwise win:
            # a Turkish horse called Winx handed the Australian one a mark of 16.
            row.setdefault("_tjk_hp", hp)
        if dead:
            row["_died"] = "1"

    print(f"tjk: {len(rows)} rows, enriched {enriched}, added {added}, "
          f"{mismatched} skipped as a different horse of the same name")
    return horses


def merge_hri(horses):
    """Horse Racing Ireland official ratings, from two manually saved pages.

    HRI's terms forbid "systematic or automated data collection", so these two
    pages are saved by hand in a browser, exactly like the BHA file. See README.

    Flat sheet:  Horse Name, YOFL, Sex, Dam, Sire, Trainer, Flat Rating, AWT Rating
    NH sheet:    same, with Hurdle Rating and Chase Rating instead.
    Sex is C/F/G, so the gelded flag comes free, and country of birth arrives as
    the (GB)/(FR) suffix on the name.
    """
    files = [p for p in (RAW / "hri_flat.html", RAW / "hri_nh.html") if p.exists()]
    if not files:
        print("hri: raw/hri_flat.html / hri_nh.html not found, skipping (see README)")
        return horses

    # Flat and all-weather only. National Hunt marks are a different population:
    # chasers run to 180 where the best flat horse in the world is 140, so a
    # handicap chaser would outrank Frankel. The NH sheet still contributes the
    # horses themselves, just not their ratings.
    RATINGS = ["Flat Rating", "AWT Rating"]
    added = enriched = 0
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for rows in P.html_tables(text):
            recs = P.table_dicts(rows)
            if not recs or "Horse Name" not in recs[0]:
                continue
            for r in recs:
                raw_name = r.get("Horse Name", "")
                key = P.norm_name(raw_name)
                year = (r.get("YOFL") or "").strip()
                if not key or not year.isdigit():
                    continue
                sex, gelded = P.parse_sex_code(r.get("Sex", ""))
                rating = next((r[c].strip() for c in RATINGS
                               if (r.get(c) or "").strip().isdigit()), "")

                row = horses.get(key)
                if row is None:
                    if not sex:
                        continue
                    row = horses[key] = {
                        "Name": P.smart_title(P.clean_name(raw_name)),
                        "Foaled": year,
                        "Sex": sex,
                        "Gelded": gelded,
                        "Breed": "Thoroughbred",
                        "_active": True,
                    }
                    added += 1
                else:
                    enriched += 1
                    if gelded == "TRUE":
                        row["Sex"], row["Gelded"] = "M", "TRUE"
                    elif sex and not row.get("Sex"):
                        row["Sex"], row["Gelded"] = sex, gelded

                sire_n, sire_c = P.split_suffix(r.get("Sire", ""), "Ireland")
                dam_n, dam_c = P.split_suffix(r.get("Dam", ""), "Ireland")
                row.setdefault("_sire_country", sire_c)
                row.setdefault("_dam_country", dam_c)
                row["_country_birth"] = True
                for dst, value in [
                    ("Sire", P.smart_title(sire_n)),
                    ("Dam", P.smart_title(dam_n)),
                    ("Country", P.country_from_suffix(raw_name)),
                ]:
                    if value and not row.get(dst):
                        row[dst] = value
                if rating and not row.get("Rating"):
                    row["Rating"] = rating
                    # Irish official ratings share the BHA pound scale; the spec
                    # has no separate IRE option.
                    row["Rating Scale"] = "BHA"

    print(f"hri: {len(files)} file(s), enriched {enriched}, added {added}")
    return horses


def merge_bha(horses):
    """Official BHA ratings, and the horses themselves.

    The file is horses currently in training in Britain, so it barely overlaps a
    set of historically notable horses: on first run it enriched 107 rows out of
    ~12,000. The value is in the rest. Every row carries a sire, a dam and a
    country-of-birth suffix, and two thirds carry an official rating, so unmatched
    rows are added as new horses rather than discarded.

    Skipped entirely if the file is absent, see README for where to get it.
    """
    path = RAW / "bha.csv"
    if not path.exists():
        print("bha: raw/bha.csv not found, skipping ratings (see README)")
        return horses

    enriched = added = 0
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            raw_name = r.get("Name", "")
            key = P.norm_name(raw_name)
            if not key:
                continue
            sex, gelded = P.parse_sex(r.get("Sex", ""))
            rating = (r.get("Flat rating") or "").strip()
            country = P.country_from_suffix(raw_name)

            row = horses.get(key)
            if row is None:
                year = (r.get("Year") or "").strip()
                if not (sex and year.isdigit()):
                    continue
                row = horses[key] = {
                    "Name": P.smart_title(P.clean_name(raw_name)),
                    "Foaled": year,
                    "Sex": sex,
                    "Gelded": gelded,
                    "Breed": "Thoroughbred",
                    "Sire": P.smart_title(P.clean_name(r.get("Sire", ""))),
                    "Dam": P.smart_title(P.clean_name(r.get("Dam", ""))),
                    # In training, so not retired whatever its foaling year says.
                    "_active": True,
                }
                added += 1
            else:
                enriched += 1
                if gelded == "TRUE":
                    row["Sex"], row["Gelded"] = "M", "TRUE"
                elif sex and not row.get("Sex"):
                    row["Sex"], row["Gelded"] = sex, gelded

            if country and not row.get("Country"):
                row["Country"] = country
            if rating.isdigit() and not row.get("Rating"):
                row["Rating"] = rating
                row["Rating Scale"] = "BHA"

    print(f"bha: enriched {enriched} existing horses, added {added} new")
    return horses


def finalise(row):
    """Fill the derived columns the sources do not carry."""
    if not row.get("Breed"):
        row["Breed"] = "Thoroughbred"
    return row


# Pull short careers toward the population mean. At 5 this was far too weak: a
# horse winning its only start still mapped to the top quantile, so 2,904 one-run
# maidens were rated 110 where real handicappers give them about 89. Weighting a
# single run against 20 notional average runs puts them where they belong.
SHRINK_STARTS = 20.0

SHRINK_PRIOR = 0.18


# "<DAM> <YEAR> Tayı" is Turkish for "foal of", i.e. a foal registered before it
# was named. 7,361 of them, nothing references them as a parent, and they would
# appear in game under that literal string.
PLACEHOLDER_NAME = re.compile(r"\bTay[\u0131i]\b", re.I)

# "241 Nonius", "117 Amurath-2": Hungarian and Austrian state-stud numbering.
# Genuine historical records, but not names a game can show.
STUDBOOK_NUMBER = re.compile(r"^\d+\s")


def find_conflated_names(horses):
    """Plain-name keys where the sources disagree about country of birth.

    Those rows are chimeras: two different horses that happen to share a name,
    merged into one because the merge key is the name alone. A Turkish colt
    called Abstract and an Irish one are not the same animal, and the blended
    row has one horse's colour and the other's pedigree.

    Read straight from the raw files, so no merge function has to change.

    Returns {name: country} giving the identity the most authoritative source
    claims. Dropping these rows was tried and was worse: it deleted real horses
    whose names a Turkish horse happens to share (Street Cry among them) and cost
    four points of sire resolution. Keeping the row with the right country beats
    losing the pedigree link.

    Turkey is in roughly 90% of the conflicts, being much the largest register
    and full of horses named after famous foreign ones, so it ranks last.
    """
    evidence = collections.defaultdict(dict)

    def note(source, name, country):
        key = P.norm_name(name or "")
        if key and country:
            evidence[key].setdefault(source, country)

    wd = RAW / "wikidata.csv"
    if wd.exists():
        with open(wd, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                note("wikidata", P.clean_name(r["hLabel"]), P.map_country(r.get("countryLabel", "")))

    bha = RAW / "bha.csv"
    if bha.exists():
        with open(bha, newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                note("bha", *P.split_suffix(r.get("Name", "")))

    tjk = RAW / "tjk.json"
    if tjk.exists():
        for r in json.loads(tjk.read_text(encoding="utf-8")):
            note("tjk", re.sub(r"\(Dead\)", "", r.get("Horse Name") or ""),
                 P.SUFFIX_COUNTRY.get((r.get("Country") or "").strip().upper(), ""))

    hk = RAW / "hkjc.json"
    if hk.exists():
        for h in json.loads(hk.read_text(encoding="utf-8")).values():
            origin = (h.get("Country of Origin / Age") or "").split("/")[0]
            note("hkjc", h.get("name", ""), P.SUFFIX_COUNTRY.get(origin.strip().upper(), ""))

    kra = RAW / "kra.json"
    if kra.exists():
        data = json.loads(kra.read_text(encoding="utf-8"))
        for reg in ("racehorses", "stallions", "broodmares", "retirements", "geldings"):
            for r in data.get(reg, []):
                note("kra", P.kr_name(r.get("마명", "")), P.kr_country(r.get("생산국", "")))

    ifha = RAW / "ifha.json"
    if ifha.exists():
        for r in json.loads(ifha.read_text(encoding="utf-8")):
            note("ifha", P.ifha_name(r.get("horse", "")),
                 P.SUFFIX_COUNTRY.get((r.get("bred") or "").strip().upper(), ""))

    # Most authoritative first. Turkey last: biggest register, most collisions.
    priority = ("ifha", "bha", "hkjc", "kra", "wikidata", "tjk")
    resolved = {}
    for key, sources in evidence.items():
        if len(set(sources.values())) < 2:
            continue
        for src in priority:
            if src in sources:
                resolved[key] = sources[src]
                break
    return resolved


def sanity_pass(written):
    """Drop links and values that are impossible, rather than shipping them.

    Everything here traces back to one thing: names are not unique. A Turkish
    colt called Saratoga and a broodmare called Saratoga collapse to one row, so
    some Sire and Dam fields end up pointing at the wrong animal. Rather than
    guess which horse was meant, the bad link is cleared and the pedigree simply
    stops there, which the spec explicitly allows.

    Not touched: very long careers (Rambling Willie really did run 305 times)
    and very old horses (Markham Arabian 1610 is genuine foundation stock).
    """
    before = len(written)
    written = [r for r in written
               if not PLACEHOLDER_NAME.search(r["Name"])
               and not STUDBOOK_NUMBER.match(r["Name"])]
    if before != len(written):
        print(f"sanity: dropped {before - len(written)} unnamed-foal placeholders")

    conflated = find_conflated_names(None)
    fixed = cleared = 0
    for row in written:
        country = conflated.get(P.norm_name(row["Name"]))
        if not country:
            continue
        if row.get("Country") != country:
            row["Country"] = country
            fixed += 1
        # The row is a blend of two horses and there is no per-field provenance
        # to say which contributed what: Winx ended up with a Turkish dam. The
        # country can be resolved by source authority, the pedigree cannot, so
        # it goes rather than ship a wrong parent.
        if row.get("Sire") or row.get("Dam") or row.get("Damsire"):
            row["Sire"] = row["Dam"] = row["Damsire"] = ""
            cleared += 1
    if conflated:
        print(f"sanity: {len(conflated)} names claimed by two countries; "
              f"{fixed} reassigned to the more authoritative source, "
              f"{cleared} had their pedigree cleared as unattributable")

    by_name = {r["Name"]: r for r in written}
    counts = collections.Counter()

    def year(row):
        v = row.get("Foaled", "")
        return int(v) if v.isdigit() else None

    for row in written:
        for col in ("Sire", "Dam"):
            name = row.get(col)
            if not name:
                continue
            if name == row["Name"]:
                row[col] = ""
                counts[f"{col.lower()} is the horse itself"] += 1
                continue
            parent = by_name.get(name)
            if not parent:
                continue
            # Only compare against a country we know is country of BIRTH.
            # Wikidata's P17 is country of registration, so Urban Sea reads
            # France there while her pedigree suffix says USA; trusting it
            # would sever Galileo from his dam.
            #
            # A disagreement here says the NAME MATCHED THE WRONG ROW, not that
            # the name is wrong: this horse is out of a New Zealand Music and
            # the row found is a British one. So the link is dropped and the
            # name kept. Clearing it instead threw away 46,000 real parents to
            # fix what is only a lookup problem, and the suffix pass can still
            # write "Music (NZ)" from the country the source declared.
            declared = row.get(f"_{col.lower()}_country")
            actual = parent.get("Country") if parent.get("_country_birth") else ""
            if declared and actual and declared != actual:
                row[f"_{col.lower()}_unlinked"] = True
                counts[f"{col.lower()} matched a row in another country"] += 1
                continue
            py, cy = year(parent), year(row)
            gap = cy - py if (py is not None and cy is not None) else None
            wrong = ""
            if gap is not None and gap < MIN_BREEDING_AGE:
                wrong = f"{col.lower()} too young to be the parent"
            elif gap is not None and col == "Dam" and gap > MAX_DAM_AGE:
                wrong = "dam too old to be the parent"
            elif gap is not None and col == "Sire" and gap > MAX_SIRE_AGE:
                wrong = "sire too old to be the parent"
            elif col == "Sire" and parent.get("Sex") == "F":
                wrong = "sire recorded as female"
            elif col == "Sire" and parent.get("Gelded") == "TRUE":
                wrong = "sire is a gelding"
            elif col == "Dam" and parent.get("Sex") == "M":
                wrong = "dam recorded as male"
            if not wrong:
                continue
            # A mare cannot foal at two and a stallion is not a gelding, so
            # something is wrong, but it is usually the MATCH rather than the
            # name. Keeping the name is only safe when the suffix will send it
            # somewhere else, which means the declared country has to differ
            # from this row's. Agreeing countries mean the name would resolve
            # straight back to the same bad row, so then it has to go.
            if declared and declared != (parent.get("Country") or ""):
                row[f"_{col.lower()}_unlinked"] = True
                counts[f"{col.lower()} matched the wrong horse, link dropped"] += 1
            else:
                row[col] = ""
                counts[wrong] += 1

        # The damsire sits two generations up, so MAX_SIRE_AGE does not apply
        # to him: a mare can be 20 when she foals and her own sire 25 when she
        # was born. Only the floor and his sex are worth checking.
        damsire = row.get("Damsire")
        if damsire:
            grand = by_name.get(damsire)
            cy = year(row)
            if damsire == row["Name"]:
                row["Damsire"] = ""
                counts["damsire is the horse itself"] += 1
            elif grand and (grand.get("Sex") == "F"
                            or (year(grand) is not None and cy is not None
                                and cy - year(grand) < 2 * MIN_BREEDING_AGE)):
                # Same rule as above: the row found is the wrong horse, so the
                # link goes and the name stays.
                row["_damsire_unlinked"] = True
                counts["damsire matched the wrong horse"] += 1

        def n(col):
            v = (row.get(col) or "").replace(",", "")
            return int(v) if v.isdigit() else 0

        starts = row.get("Starts", "")
        if starts.isdigit():
            if int(starts) == 0:
                for col in ("Starts", "Wins", "2nds", "3rds"):
                    row[col] = ""
                counts["career record of zero starts cleared"] += 1
            elif n("Wins") + n("2nds") + n("3rds") > int(starts):
                for col in ("Starts", "Wins", "2nds", "3rds"):
                    row[col] = ""
                counts["placings exceeded starts"] += 1

        owner = row.get("Owner") or ""
        if owner and not re.search(r"[A-Za-z]", owner):
            row["Owner"] = ""
            counts["owner not in latin script"] += 1

        if row.get("Sex") == "F" and row.get("Gelded") == "TRUE":
            row["Gelded"] = ""
            counts["female marked as gelded"] += 1

    total = sum(counts.values())
    print(f"sanity: {total} impossible values cleared")
    for k, v in counts.most_common():
        print(f"    {v:>5}  {k}")
    return written


def _career_score(row):
    """Placing-weighted strike rate, shrunk toward the mean by sample size."""
    starts = (row.get("Starts") or "").replace(",", "")
    if not starts.isdigit() or int(starts) < 1:
        return None
    st = int(starts)

    def n(col):
        v = (row.get(col) or "").replace(",", "")
        return int(v) if v.isdigit() else 0

    credit = n("Wins") + 0.3 * n("2nds") + 0.1 * n("3rds")
    return (credit + SHRINK_STARTS * SHRINK_PRIOR) / (st + SHRINK_STARTS)


def estimate_ratings(written):
    """Give a rating to horses that have a career record but no published one.

    Quantile mapping, not a fitted model: rank a horse by strike rate among all
    horses that have BOTH a record and a real pound-scale rating, then hand it
    the rating sitting at the same rank in that population. Correlation between
    strike rate and rating over ~9,900 horses is r=0.51, and the decile medians
    rise monotonically from 57 to 118, so the signal is real but loose.

    Marked `Rating Scale = Estimated` so nothing downstream mistakes these for
    published marks. Horses with no record at all are left blank for the world
    generator, which is what the guide asks for.

    Horses are ranked among THEMSELVES and laid onto the rated population in
    rank order, rather than looked up by score against it. Looking up by score
    assumes both populations run the same strike rates, and they do not: it put
    0.46% of estimates at 130 or better where the real marks put 0.045%, a tail
    ten times too fat. Ranking within the population reproduces the real spread
    almost exactly.

    Ties are broken at random, which is also what fixes the collapse. Every
    horse with one start and no wins scores identically, and handing that whole
    block one rating once put 35% of 490,000 horses in a single ten-point band.
    Spread across the block, they take the range the real population has there.
    """
    import random

    known = [(_career_score(r), int(r["Rating"]))
             for r in written
             if r.get("Rating", "").isdigit() and r.get("Rating Scale") == "BHA"
             and _career_score(r) is not None]
    if len(known) < 500:
        print("estimate: too few rated horses with records, skipping")
        return written

    ladder = sorted(v for _, v in known)

    rng = random.Random(20260818)
    pending = []
    for row in written:
        if row.get("Rating"):
            continue
        score = _career_score(row)
        if score is not None:
            pending.append((score, rng.random(), row))
    if not pending:
        return written

    pending.sort(key=lambda t: (t[0], t[1]))
    steps, total = len(ladder), len(pending)
    for position, (_, _, row) in enumerate(pending):
        row["Rating"] = str(ladder[min(steps - 1, position * steps // total)])
        row["Rating Scale"] = "Estimated"

    print(f"estimate: {len(pending)} ratings derived from career record "
          f"(matched to the spread of {len(known)} rated horses)")
    return written


# Heritability of racing ability. Published estimates for Thoroughbred
# performance ratings cluster around 0.3-0.4, so offspring regress most of the
# way back to the population mean. Offspring-on-midparent regression is h^2;
# offspring on a single parent is h^2/2.
HERITABILITY = 0.35

# Share of foals of a grey parent that are themselves grey. Measured at 48% over
# the real foal/sire pairs in this file, which is what the textbook predicts for
# a dominant allele carried heterozygously.
GREY_INHERITANCE = 0.48

# How many real foals a parent-colour pair needs before its own cell is trusted
# ahead of the sire's marginal.
JOINT_MIN_PAIRS = 40

# A foal cannot be born before its sire turns three, and a mare's last foal
# comes well before thirty. Anything outside that is two horses sharing a name:
# the 1999 sire Acclamation was being linked through a different Acclamation
# foaled 2006.
MIN_BREEDING_AGE = 3
MAX_DAM_AGE = 28

# A stallion covers into his late twenties at the outside. Without a ceiling the
# 1748 Matchem was recorded as the sire of a 2023 foal, because the modern horse
# of the same name is not a row and the reference bound to the historical one.
MAX_SIRE_AGE = 30

# Share of racehorses that never win anything, measured over the 371,287 horses
# in the Kaggle race archive (225,644 of them). Used as the prior for a horse we
# know nothing about, when no better reference population is available.
NEVER_WON_RATE = 0.61

# Ceiling for a horse with no record anywhere. These horses left no trace in any
# of twelve sources, so they are treated as modest by default: 70 sits just
# below the median of the real handicapped population.
UNRECORDED_RATING_MAX = 90

# Official ratings of every flat horse in the Kaggle archive, filled in by
# merge_kaggle. This is the least biased picture of what an ordinary racehorse
# is worth that this pipeline has: 132,810 handicapped horses rather than only
# the ones famous enough to carry a published mark.
REFERENCE_RATINGS = []

# Ratings that live on the international pound scale and can be averaged
# together. TJK is its own scale and is only ever combined with itself.
POUND_SCALES = {"BHA", "Estimated", "Pedigree"}


def derive_ratings_from_pedigree(written, passes=3):
    """Give unrated horses a rating inferred from their parents.

    est = mean + h^2 * (midparent - mean), or h^2/2 for a single known parent.
    That is the standard breeder's-equation form, so a horse by a good sire out
    of an unknown mare lands a little above average rather than inheriting its
    sire's mark outright.

    Repeated for a few passes so a value can travel down a generation, but each
    pass regresses harder toward the mean, which is honest: the further from a
    measured horse, the less is actually known. Marked `Rating Scale = Pedigree`.

    Residual spread is then added back. Regression gives the best estimate for a
    single horse, but this output seeds a whole population, and a population of
    point estimates is flat: every foal of a good sire lands on the same number.
    The unexplained part of the variance is sigma * sqrt(1 - h^2), so that is
    sampled and added, which reproduces a realistic spread instead of a world of
    identical average horses. Seeded, so builds stay reproducible.
    """
    import random

    rng = random.Random(20260818)
    by_name = {r["Name"]: r for r in written}

    def scale_of(row):
        s = row.get("Rating Scale", "")
        return "TJK" if s == "TJK" else "pound"

    means, spreads = {}, {}
    for pool in ("pound", "TJK"):
        vals = [int(r["Rating"]) for r in written
                if r.get("Rating", "").isdigit() and scale_of(r) == pool]
        if len(vals) > 1:
            means[pool] = sum(vals) / len(vals)
            var = sum((v - means[pool]) ** 2 for v in vals) / len(vals)
            spreads[pool] = (var ** 0.5) * ((1 - HERITABILITY) ** 0.5)
    if not means:
        return written

    lo = min(int(r["Rating"]) for r in written if r.get("Rating", "").isdigit())
    hi = max(int(r["Rating"]) for r in written if r.get("Rating", "").isdigit())

    total = 0
    for _ in range(passes):
        filled = 0
        for row in written:
            if row.get("Rating"):
                continue
            parents = []
            for col in ("Sire", "Dam"):
                p = by_name.get(row.get(col) or "")
                if p and p.get("Rating", "").isdigit():
                    parents.append((int(p["Rating"]), scale_of(p)))
            if not parents:
                continue
            # Only ever average like with like. A Turkish handicap mark and a
            # pound-scale mark cannot be combined, and a child of two Turkish
            # parents is on the Turkish scale, so it must not be emitted as
            # `Pedigree`, which the spec defines as the pound scale.
            parents = [v for v, s in parents if s != "TJK"]
            if not parents:
                continue
            pool = "pound"
            mean = means[pool]
            coeff = HERITABILITY if len(parents) == 2 else HERITABILITY / 2
            est = mean + coeff * (sum(parents) / len(parents) - mean)
            est += rng.gauss(0, spreads[pool])
            row["Rating"] = str(max(lo, min(hi, round(est))))
            row["Rating Scale"] = "Pedigree"
            filled += 1
        total += filled
        if not filled:
            break

    print(f"pedigree: {total} ratings inferred from parents")
    return written


def fill_remaining_ratings(written, seed=20260818):
    """Give every remaining horse a rating drawn from the observed distribution.

    ON by default, because the game derives every stat from the rating and a
    blank leaves it nothing to work with. Disable with --leave-unrated.

    Be clear about what this is: these horses have no rating,
    no career record and no rated ancestor, so any number here is invention
    rather than inference. The guide already says a blank rating gets filled by
    the world generator, and the generator can weigh context this file does not
    carry. Baking a random number into the CSV only moves where the dice are
    rolled, while making the data look more certain than it is.

    These horses are NOT sampled from the published distribution, which is badly
    selection-biased: a horse only carries a published mark if it was good
    enough to be handicapped, ranked or written about. Sampling that pool put
    29% of unknown horses above 110, i.e. Group class, which is absurd.

    The reference is instead the official ratings in the race archives, ordinary
    handicapped horses rather than famous ones.

    That pool is then capped. These horses have no record in any of twelve
    sources, and a horse good enough to be rated above 100 runs in listed or
    stakes company, where it would be written up somewhere. Leaving the cap off
    produced Korean retirement-register entries rated 138, which is world class
    for a horse nothing is known about.

    Seeded, so builds stay reproducible.
    """
    import random

    def wins(row):
        v = (row.get("Wins") or "").replace(",", "")
        return int(v) if v.isdigit() else None

    rng = random.Random(seed)

    if REFERENCE_RATINGS:
        # The real handicapped population, minus anything good enough that its
        # absence from every source would be implausible.
        pool = [v for v in REFERENCE_RATINGS if v <= UNRECORDED_RATING_MAX]
        draw = lambda: rng.choice(pool or REFERENCE_RATINGS)
    else:
        # Fallback when the Kaggle archive is absent. Published marks split by
        # whether the horse ever won, mixed at the measured never-won rate.
        published = [r for r in written
                     if r.get("Rating", "").isdigit()
                     and r.get("Rating Scale") in ("BHA", "Estimated")
                     and wins(r) is not None]
        never_won = [int(r["Rating"]) for r in published if wins(r) == 0]
        winners = [int(r["Rating"]) for r in published if wins(r) > 0]
        if not never_won or not winners:
            return written
        draw = lambda: rng.choice(
            never_won if rng.random() < NEVER_WON_RATE else winners)

    filled = 0
    for row in written:
        if row.get("Rating"):
            continue
        row["Rating"] = str(draw())
        row["Rating Scale"] = "Random"
        filled += 1
    print(f"fill-all: {filled} ratings sampled from the observed distribution")
    return written


def apply_tjk_ratings(horses):
    """Apply stashed Turkish marks, but only to horses still unrated.

    Runs after every pound-scale source so a TJK handicap can never displace a
    published international mark.
    """
    applied = 0
    for row in horses.values():
        hp = row.pop("_tjk_hp", None)
        if hp and not row.get("Rating"):
            row["Rating"] = hp
            row["Rating Scale"] = "TJK"
            applied += 1
    print(f"tjk ratings: {applied} applied where nothing better existed")
    return horses


# Thoroughbred and Standardbred are the two breeds this dataset covers: flat
# racing and harness racing. Arabians are dropped by default, being ~32,000 rows
# almost entirely from the Turkish register, with no comparable coverage
# elsewhere and no ratings on a shared scale.
RACING_BREEDS = {"Thoroughbred", "Standardbred"}


def filter_breeds(written, keep):
    """Drop breeds the game has no race type for."""
    if not keep:
        return written
    before = len(written)
    written = [r for r in written if r.get("Breed") in keep]
    print(f"breeds: {before} -> {len(written)} rows (kept {', '.join(sorted(keep))})")
    return written


def model_colours(written):
    """Fill missing coat colour by inheritance, learned from the real rows.

    Colour is a studbook field and every studbook that publishes it at scale is
    licence-blocked, so 90% of rows have none. It is also genuinely heritable,
    and the ~26,000 foal/sire pairs already in the file reproduce the textbook
    genetics without being told them:

        bay sire      -> 77% bay, 15% chestnut     (bay dominant)
        chestnut sire -> 47% chestnut, 45% bay     (chestnut recessive)
        grey sire     -> 48% grey                  (grey dominant, usually
                                                    heterozygous, so ~half)

    The table is keyed on BOTH parents where enough real pairs exist, falling
    back to a sire or dam marginal. A marginal is averaged over every mate, so
    using it for one specific mating imports the wrong distribution: it gave
    chestnut x chestnut only 71% chestnut against 94% in the real pairs.

    Two rules are then enforced outright. Chestnut is homozygous recessive, so
    two chestnut parents can only make a chestnut. Grey is a single dominant, so
    a horse is grey only if a parent is, one grey parent gives about half and
    two give about three quarters.

    Horses are filled oldest first, letting a modelled sire inform its foals.

    Marked nowhere in the file, because the spec has no column for it. Disable
    with --no-modelled-colours to leave the field blank for the world generator.
    """
    import random

    by_name = {r["Name"]: r for r in written}
    known = [r for r in written if r.get("Colour")]
    if len(known) < 1000:
        print("colour: too few known colours to model from, skipping")
        return written

    for row in known:
        row["Colour Source"] = "data"

    base = collections.Counter(r["Colour"] for r in known)

    # A joint table keyed on BOTH parents. A sire-only table is a marginal
    # averaged over every mare he covered, so using it for a specific mating
    # imports the wrong dam distribution: chestnut x chestnut came out 71%
    # chestnut where the real pairs are 94%, and chestnut was over-produced by
    # ten points overall.
    joint = collections.defaultdict(collections.Counter)
    from_sire = collections.defaultdict(collections.Counter)
    from_dam = collections.defaultdict(collections.Counter)
    for r in known:
        sire, dam = by_name.get(r.get("Sire") or ""), by_name.get(r.get("Dam") or "")
        sc = sire.get("Colour") if sire else ""
        dc = dam.get("Colour") if dam else ""
        if sc:
            from_sire[sc][r["Colour"]] += 1
        if dc:
            from_dam[dc][r["Colour"]] += 1
        if sc and dc:
            joint[(sc, dc)][r["Colour"]] += 1

    def pick(rng, counter):
        total = sum(counter.values())
        roll = rng.random() * total
        for value, weight in counter.items():
            roll -= weight
            if roll <= 0:
                return value
        return next(iter(counter))

    rng = random.Random(20260818)

    # Grey propagates upward as well as down: a horse that IS grey must have had
    # a grey parent, so where that parent's colour is unknown it can be inferred.
    # Without this, grey only ever flows down from the few greys that happen to
    # be recorded, and the modelled population ends up at 2% against a real 5%.
    seeded = 0
    for row in written:
        if row.get("Colour") != "Grey":
            continue
        sire = by_name.get(row.get("Sire") or "")
        dam = by_name.get(row.get("Dam") or "")
        if (sire and sire.get("Colour") == "Grey") or (dam and dam.get("Colour") == "Grey"):
            continue
        parent = sire if (sire and not sire.get("Colour")) else (
            dam if (dam and not dam.get("Colour")) else None)
        if parent is not None:
            parent["Colour"] = "Grey"
            parent["Colour Source"] = "modelled"
            seeded += 1
    if seeded:
        print(f"colour: inferred {seeded} grey parents from a grey foal")

    # Oldest first, so a modelled sire is available to its own foals.
    order = sorted(written, key=lambda r: int(r["Foaled"]) if r["Foaled"].isdigit() else 0)
    filled = corrected = 0
    for row in order:
        if row.get("Colour"):
            continue
        sire = by_name.get(row.get("Sire") or "")
        dam = by_name.get(row.get("Dam") or "")
        sire_c = (sire or {}).get("Colour", "")
        dam_c = (dam or {}).get("Colour", "")

        # Grey is a single dominant locus. One grey parent gives about half
        # grey; two give about three quarters, since each independently passes
        # the allele. Treating it as one flat draw left grey x grey at 48%.
        greys = sum(1 for c in (sire_c, dam_c) if c == "Grey")
        if greys:
            chance = GREY_INHERITANCE if greys == 1 else 1 - (1 - GREY_INHERITANCE) ** 2
            if rng.random() < chance:
                row["Colour"] = "Grey"
                row["Colour Source"] = "modelled"
                filled += 1
                continue
        elif sire_c and dam_c:
            corrected += 1          # both parents known and neither grey

        # Chestnut is homozygous recessive, so two chestnut parents can only
        # produce a chestnut foal. The measured pairs agree at 94%.
        if sire_c == "Chestnut" and dam_c == "Chestnut":
            row["Colour"] = "Chestnut"
            row["Colour Source"] = "modelled"
            filled += 1
            continue

        # Both parents known and seen together often enough to trust the cell,
        # else the sire's marginal, else the dam's, else the population.
        table = joint.get((sire_c, dam_c)) if sire_c and dam_c else None
        if not table or sum(table.values()) < JOINT_MIN_PAIRS:
            table = from_sire.get(sire_c) or from_dam.get(dam_c) or base
        table = collections.Counter({k: v for k, v in table.items() if k != "Grey"})
        colour = pick(rng, table or base)

        row["Colour"] = colour
        row["Colour Source"] = "modelled"
        filled += 1

    print(f"colour: modelled {filled} coats from inheritance "
          f"({corrected} had two known non-grey parents, so grey was ruled out)")
    return written


# Distance aptitude is heritable at roughly the same strength as ability:
# stayers get stayers. Same equation as ratings, different trait.
DISTANCE_HERITABILITY = 0.35


def derive_distance_from_pedigree(written, passes=3):
    """Give horses with no race record a Best Distance from their parents.

    Same breeder's equation as the ratings: an estimate regressed toward the
    population mean, with the residual spread added back so the population does
    not collapse onto one distance. Run oldest first over a few passes so a
    derived sire can pass its aptitude down.
    """
    import random

    by_name = {r["Name"]: r for r in written}

    def metres(row):
        v = (row.get("Best Distance") or "").strip()
        return int(v) if v.isdigit() else None

    known = [m for m in (metres(r) for r in written) if m]
    if len(known) < 500:
        print("distance: too few measured distances to model from, skipping")
        return written

    mean = sum(known) / len(known)
    var = sum((v - mean) ** 2 for v in known) / len(known)
    residual = (var ** 0.5) * ((1 - DISTANCE_HERITABILITY) ** 0.5)
    lo, hi = min(known), max(known)

    rng = random.Random(20260818)
    order = sorted(written, key=lambda r: int(r["Foaled"]) if r["Foaled"].isdigit() else 0)
    total = 0
    for _ in range(passes):
        filled = 0
        for row in order:
            if row.get("Best Distance"):
                continue
            parents = [m for m in (metres(by_name[n]) for n in
                                   (row.get("Sire") or "", row.get("Dam") or "")
                                   if n in by_name) if m]
            if not parents:
                continue
            coeff = DISTANCE_HERITABILITY if len(parents) == 2 else DISTANCE_HERITABILITY / 2
            est = mean + coeff * (sum(parents) / len(parents) - mean)
            est += rng.gauss(0, residual)
            row["Best Distance"] = str(int(max(lo, min(hi, round(est / 100) * 100))))
            row["Distance Source"] = "pedigree"
            filled += 1
        total += filled
        if not filled:
            break

    print(f"distance: {total} best distances inferred from parents")
    return written


# A mare's own birth year is not recorded anywhere here, but the year of her
# first known foal is. Measured over the 59,798 mares who do have a row, the gap
# between the two depends on how many of her foals are actually visible: 7 years
# when only one or two turn up, 5 when nine or more do. That is the same bias in
# both directions, since only foals that RACED are visible and her earliest ones
# often did not, so the fewer we see the later her "first" foal looks.
#
# It corrects by a year or two, not more. Where a mare's early produce is missing
# entirely the estimate still lands years late: Dance Attendance reads 2001 and
# was foaled 1987. Treat the year as a placeholder, not a fact.
def broodmare_age(visible_foals):
    if visible_foals <= 2:
        return 7
    return 6 if visible_foals <= 8 else 5


# Punctuation and particle case are not part of a horse's identity, so
# "T.M. Opera O" and "T M Opera O" are one animal entered twice. Japanese names
# dominate because a katakana name has no canonical Latin punctuation: the
# crosswalk writes one form and the race archive another.
SPELLING_NOISE = re.compile(r"[.\u2019'\-\s]+")

# The same tolerance the archive merges use. Two horses of one name foaled a
# year apart in one country do not exist; a studbook will not register it.
SPELLING_YEARS = 1


def merge_spelling_variants(written):
    """Fold rows whose names differ only in punctuation, spacing or particle case.

    Grouped on the stripped name plus country, then split into clusters by
    foaling year so a name reused decades later stays two horses. A cluster is
    left alone when its rows name different sires, since that is the one signal
    that says they really are two animals.

    The surviving spelling is whichever one the rest of the file already points
    at as a sire or dam. That keeps the most pedigree links intact and is not a
    matter of taste: 163 rows call him T M Opera O and none call him
    T.M. Opera O.
    """
    def key(name):
        return SPELLING_NOISE.sub("", name).lower()

    refs = collections.Counter()
    for row in written:
        for col in ("Sire", "Dam", "Damsire"):
            if row.get(col):
                refs[row[col]] += 1
    seen_name = collections.Counter(r["Name"] for r in written)

    # "Vril (AUS)" against "Vuriru" is one stallion romanised twice, not two.
    # A differing sire only proves two animals when both spellings name a horse
    # this file actually holds.
    known = {r["Name"] for r in written}

    groups = collections.defaultdict(list)
    for row in written:
        groups[(key(row["Name"]), row.get("Country", ""))].append(row)

    drop, rename = set(), {}
    merged = skipped = 0
    for rows in groups.values():
        if len({r["Name"] for r in rows}) < 2:
            continue
        rows.sort(key=lambda r: int(r["Foaled"]) if r["Foaled"].isdigit() else 0)
        cluster = []
        for row in rows + [None]:
            if cluster and row is not None:
                last = cluster[-1]["Foaled"]
                if (last.isdigit() and row["Foaled"].isdigit()
                        and int(row["Foaled"]) - int(last) <= SPELLING_YEARS):
                    cluster.append(row)
                    continue
            if len({r["Name"] for r in cluster}) > 1:
                sires = {r["Sire"] for r in cluster if r.get("Sire")}
                if len({key(n) for n in sires}) > 1 and all(n in known for n in sires):
                    skipped += 1
                else:
                    merged += _fold(cluster, refs, seen_name, known, drop, rename)
            cluster = [row] if row is not None else []

    if not drop:
        return written
    written = [r for r in written if id(r) not in drop]
    for row in written:
        for col in ("Sire", "Dam", "Damsire"):
            if row.get(col) in rename:
                row[col] = rename[row[col]]
    print(f"names: folded {merged} horses written under two spellings "
          f"(T.M. Opera O and T M Opera O were both in the file), "
          f"{skipped} left alone because the spellings name different sires")
    return written


def _fold(cluster, refs, seen_name, known, drop, rename):
    """Keep one row from a cluster, fill its blanks from the rest, drop the others."""
    # The two rows are two views of one career, and one is usually a fragment:
    # T.M.Sunday ran 38 times under one spelling and 1 time under the other.
    # Blank-filling cannot repair that, because Starts was already filled with
    # the wrong number, so the fuller RECORD picks the base row and the count of
    # filled columns only breaks ties. Most referenced spelling wins the NAME.
    def starts(row):
        v = (row.get("Starts") or "").replace(",", "")
        return int(v) if v.isdigit() else -1

    order = sorted(cluster, key=lambda r: (-starts(r),
                                           -sum(1 for c in COLUMNS if r.get(c))))
    keeper = order[0]
    name = max(cluster, key=lambda r: (refs[r["Name"]],
                                       sum(1 for c in COLUMNS if r.get(c)),
                                       r["Name"]))["Name"]
    for other in order[1:]:
        for col in COLUMNS:
            if not keeper.get(col) and other.get(col):
                keeper[col] = other[col]
        # A parent name that resolves to a row beats one that does not, even
        # when the keeper already has something: the two spellings are the same
        # stallion, and "Vril (AUS)" is usable where "Vuriru" is a dead end.
        for col in ("Sire", "Dam", "Damsire"):
            theirs = other.get(col)
            if theirs and theirs in known and keeper.get(col) not in known:
                keeper[col] = theirs
        # Only redirect a spelling that belongs to this horse alone. A name
        # shared with an unrelated row would drag that row's children along.
        if seen_name[other["Name"]] == 1 and other["Name"] != name:
            rename[other["Name"]] = name
        drop.add(id(other))
    if keeper["Name"] != name:
        if seen_name[keeper["Name"]] == 1:
            rename[keeper["Name"]] = name
        keeper["Name"] = name
    return len(order) - 1


def add_broodmares(written):
    """Give a row to the mares who exist here only as a Dam.

    Every source in this file records horses that RAN. A mare who raced twice at
    Redcar, or never raced at all, never appears as a runner, so 135,329 mares
    are a name on a foal's row and nothing else and the pedigree dead-ends after
    one generation. That is not a coverage gap that more race data would fix.

    What is known about her is real and already here: the foals name her, the
    source declared her country of birth, and the Damsire column on her foals is
    her own sire. So the row is assembled from her produce rather than invented.
    Only Foaled is an estimate, taken from her first known foal, so it can
    be several years late.

    A mare is skipped when her bare name is already used by a horse that ran.
    Two rows would then share a name, and a foal looking its dam up by name
    could reach the wrong one. That costs 15% of them, which is cheaper than a
    wrong pedigree. She is also skipped when her foals disagree about her
    country, since that means two different mares share the name.

    Runs before the derived passes, so a broodmare gets her colour, rating and
    country suffix by the same rules as everyone else.
    """
    # A name used as a Sire or Damsire anywhere belongs to a stallion, whatever
    # one stray Dam field says. Without this, one bad Dam value turned Lomitas,
    # Deep Run and Song into mares and took 3,968 sire references down with them.
    # Matched the way merge_spelling_variants matches, or a Dam field spelled
    # "Dance In The Mood" mints a second mare beside the "Dance in the Mood"
    # who already has a row.
    def spelling(name):
        return SPELLING_NOISE.sub("", name).lower()

    taken = {spelling(r["Name"]) for r in written}
    taken.update(spelling(r["Sire"]) for r in written if r.get("Sire"))
    taken.update(spelling(r["Damsire"]) for r in written if r.get("Damsire"))
    produce = {}
    for row in written:
        dam = (row.get("Dam") or "").strip()
        if not dam or spelling(dam) in taken:
            continue
        m = produce.setdefault(spelling(dam), {"years": [], "countries": set(),
                                               "sires": collections.Counter(),
                                               "breeds": collections.Counter(),
                                               "spellings": collections.Counter()})
        m["spellings"][dam] += 1
        year = row.get("Foaled", "")
        if year.isdigit():
            m["years"].append(int(year))
        m["countries"].add(row.get("_dam_country") or "")
        if row.get("Damsire"):
            m["sires"][row["Damsire"]] += 1
        if row.get("Breed"):
            m["breeds"][row["Breed"]] += 1

    by_name = {r["Name"]: r for r in written}
    mares = []
    ambiguous = undated = spread = 0
    respell = {}
    for _, m in produce.items():
        # Her foals may not agree how to write her. Take the commonest spelling
        # and point the rest of them at it, or half her produce fails to chain.
        name = m["spellings"].most_common(1)[0][0]
        for written_as in m["spellings"]:
            if written_as != name:
                respell[written_as] = name
        countries = {c for c in m["countries"] if c}
        if len(countries) > 1:
            ambiguous += 1
            continue
        if not m["years"]:
            undated += 1
            continue
        # No mare breeds for longer than she can live. Charming Jenny was named
        # as the dam of Jigg in 1701 and of an American colt in 2007, which is
        # two mares sharing a name, and taking the earliest foal would have
        # dated her to 1686.
        if max(m["years"]) - min(m["years"]) > MAX_DAM_AGE - MIN_BREEDING_AGE:
            spread += 1
            continue
        foaled = min(m["years"]) - broodmare_age(len(m["years"]))
        mare = {"Name": name, "Foaled": str(foaled), "Sex": "F",
                "Breed": m["breeds"].most_common(1)[0][0] if m["breeds"]
                         else "Thoroughbred",
                "Country": countries.pop() if countries else ""}
        if mare["Country"]:
            mare["_country_birth"] = True
        if m["sires"]:
            sire = m["sires"].most_common(1)[0][0]
            # Her sire has to be old enough to be her sire. The damsire link was
            # checked against her FOAL, which is a generation further down.
            his = by_name.get(sire)
            if not (his and his.get("Foaled", "").isdigit()
                    and foaled - int(his["Foaled"]) < MIN_BREEDING_AGE):
                mare["Sire"] = sire
        mares.append(mare)

    if respell:
        for row in written:
            if row.get("Dam") in respell:
                row["Dam"] = respell[row["Dam"]]
    written.extend(mares)
    with_sire = sum(1 for m in mares if m.get("Sire"))
    print(f"broodmares: {len(mares)} mares given a row of their own "
          f"({with_sire} with a sire from the Damsire column), "
          f"{len(produce) - len(mares)} skipped ({ambiguous} whose foals "
          f"disagree on her country, {spread} whose foals span more years than "
          f"a mare can breed, {undated} undated)")
    return written


def cap_per_country(written, limit):
    """Keep at most `limit` horses per country, best-documented first.

    Turkey and Korea publish far more than anyone else, so an uncapped build is
    72% those two. Ranking is by rating first, then by how many spec columns are
    filled, so the horses that survive are the ones with the most to work with.

    Any horse still named as a Sire or Dam by a survivor is kept regardless,
    otherwise capping would orphan pedigrees mid-chain.
    """
    if not limit:
        return written

    def score(r):
        rating = int(r["Rating"]) if r.get("Rating", "").isdigit() else 0
        return (rating, sum(1 for c in COLUMNS if r.get(c)))

    by_country = {}
    for r in written:
        by_country.setdefault(r.get("Country", ""), []).append(r)

    keep = []
    for country, rs in by_country.items():
        if not country:            # unknown country is the historical ancestor pool
            keep.extend(rs)
            continue
        rs.sort(key=score, reverse=True)
        keep.extend(rs[:limit])

    kept_names = {r["Name"] for r in keep}
    parents = set()
    for r in keep:
        for col in ("Sire", "Dam"):
            v = r.get(col)
            if v and v not in kept_names:
                parents.add(v)
    if parents:
        rescued = [r for r in written if r["Name"] in parents and r["Name"] not in kept_names]
        keep.extend(rescued)
        print(f"  kept {len(rescued)} extra horses referenced as a sire or dam")

    keep.sort(key=lambda r: P.norm_name(r["Name"]))
    print(f"capped at {limit}/country: {len(written)} -> {len(keep)} rows")
    return keep


NUMBERED_NAME = re.compile(r"\s+(I{1,3}|IV|V|VI{1,3})$")


def strip_lonely_numerals(written):
    """Drop the Kaggle archive's disambiguation index where it disambiguates nothing.

    That archive appends a roman numeral to the earlier of two horses sharing a
    name, so "Abdicate I" foaled 1988 and "Abdicate" foaled 2008 are two real
    animals and the numeral has to stay: 10,636 Sire and Dam fields point at a
    numbered name. Where no bare-name twin exists the numeral is noise, and no
    horse is ever officially named "Tailormade I".
    """
    names = {r["Name"] for r in written}
    rename = {}
    for row in written:
        if not NUMBERED_NAME.search(row["Name"]):
            continue
        stem = NUMBERED_NAME.sub("", row["Name"])
        if stem not in names:
            rename[row["Name"]] = stem

    # Two numbered names can share a stem. Renaming both would merge two horses.
    taken = collections.Counter(rename.values())
    rename = {k: v for k, v in rename.items() if taken[v] == 1}
    if not rename:
        return written

    for row in written:
        row["Name"] = rename.get(row["Name"], row["Name"])
        for col in ("Sire", "Dam", "Damsire"):
            if row.get(col):
                row[col] = rename.get(row[col], row[col])
    print(f"names: dropped a meaningless roman numeral from {len(rename)} names")
    return written


def apply_name_suffixes(written):
    """Rewrite Name, Sire and Dam as "NAME (CODE)", the way a racing programme does.

    Names are unique within a studbook, not globally, so the country of birth is
    what makes them a usable key. Run last, after every merge and after
    cap_per_country, so all internal logic stays plain-name based and only the
    emitted file changes.

    A Sire or Dam that resolves to a row takes THAT row's country, so every link
    that resolves today still resolves. An unresolved parent falls back to the
    country its source declared, and a horse with no known country keeps a bare
    name, which the spec allows.
    """
    by_name = {r["Name"]: r for r in written}
    suffixed_parents = bare = 0

    for row in written:
        for col in ("Sire", "Dam", "Damsire"):
            name = row.get(col)
            if not name:
                continue
            parent = by_name.get(name)
            if row.get(f"_{col.lower()}_unlinked"):
                parent = None
            country = (parent or {}).get("Country") or \
                row.get(f"_{col.lower()}_country") or ""
            row[col] = P.suffixed(name, country)
            if country:
                suffixed_parents += 1

    seen = {}
    collisions = 0
    for row in written:
        row["Name"] = P.suffixed(row["Name"], row.get("Country"))
        if not row.get("Country"):
            bare += 1
        # Two distinct keys can romanise to the same display name, e.g. a pair
        # of Korean horses both landing on "Tohamsan". Keep names unique, since
        # the whole point of the suffix is that Sire and Dam resolve by name.
        if row["Name"] in seen:
            collisions += 1
            row["Name"] = f"{row['Name']} {seen[row['Name']] + 1}"
        seen[row["Name"]] = seen.get(row["Name"], 0) + 1
    if collisions:
        print(f"names: {collisions} display-name collisions disambiguated")

    # sanity_pass validated links against plain names. Renaming can make a
    # reference resolve to a different row than it did then, and the broodmare
    # rows arrive after it runs, so every link is checked once more against the
    # names actually written out. Nothing can be renamed after this point, so a
    # link that is still impossible here is cleared rather than dropped.
    #
    # A damsire is two generations up, so his window is the two others stacked:
    # his daughter can be born when he is 30 and foal when she is 28.
    LIMITS = {"Sire": (MIN_BREEDING_AGE, MAX_SIRE_AGE),
              "Dam": (MIN_BREEDING_AGE, MAX_DAM_AGE),
              "Damsire": (2 * MIN_BREEDING_AGE, MAX_SIRE_AGE + MAX_DAM_AGE)}
    final = {r["Name"]: r for r in written}
    stale = collections.Counter()
    for row in written:
        for col, (floor, ceiling) in LIMITS.items():
            parent = final.get(row.get(col) or "")
            if not parent:
                continue
            wanted = "F" if col == "Dam" else "M"
            if parent.get("Sex") and parent["Sex"] != wanted:
                row[col] = ""
                stale[f"{col.lower()} is recorded as the other sex"] += 1
                continue
            if col == "Sire" and parent.get("Gelded") == "TRUE":
                row[col] = ""
                stale["sire is a gelding"] += 1
                continue
            py, cy = parent.get("Foaled", ""), row.get("Foaled", "")
            if py.isdigit() and cy.isdigit():
                gap = int(cy) - int(py)
                if gap < floor or gap > ceiling:
                    row[col] = ""
                    stale[f"{col.lower()} cannot be that age"] += 1
    if stale:
        print(f"names: {sum(stale.values())} parent links cleared after renaming")
        for reason, count in stale.most_common():
            print(f"    {count:7d}  {reason}")

    print(f"names: {len(written) - bare} suffixed with a country, {bare} left bare; "
          f"{suffixed_parents} parent references suffixed")
    return written


def main():
    horses = apply_tjk_ratings(merge_kaggle(merge_deltaromeo(merge_nar(merge_ifha(merge_hkjc(merge_kra(merge_tjk(merge_hri(
        merge_bha(merge_ja_wikipedia(merge_wikipedia(load_wikidata()))))))))))))

    written = [finalise(horses[k]) for k in sorted(horses)]
    written = [r for r in written
               if r.get("Name") and r.get("Foaled") and r.get("Sex")]

    written = sanity_pass(written)
    written = strip_lonely_numerals(written)
    written = merge_spelling_variants(written)

    if "--no-broodmares" not in sys.argv:
        written = add_broodmares(written)

    if "--no-estimated-ratings" not in sys.argv:
        written = derive_distance_from_pedigree(written)

    if "--no-modelled-colours" not in sys.argv:
        written = model_colours(written)

    if "--all-breeds" not in sys.argv:
        written = filter_breeds(written, RACING_BREEDS)

    if "--no-estimated-ratings" not in sys.argv:
        written = estimate_ratings(written)
        written = derive_ratings_from_pedigree(written)
        if "--leave-unrated" not in sys.argv:
            written = fill_remaining_ratings(written)

    limit = 0
    if "--max-per-country" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--max-per-country") + 1])
    written = cap_per_country(written, limit)

    if "--plain-names" not in sys.argv:
        written = apply_name_suffixes(written)

    OUT.mkdir(exist_ok=True)
    path = OUT / OUTPUT_NAME
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(COLUMNS)
        for row in written:
            writer.writerow([row.get(c, "") for c in COLUMNS])

    # A gzipped copy travels in the repo: the plain CSV is 64 MB, over GitHub's
    # warning threshold and rewritten in full on every build.
    import gzip
    import shutil
    with open(path, "rb") as raw, gzip.open(f"{path}.gz", "wb", compresslevel=9) as gz:
        shutil.copyfileobj(raw, gz)

    print(f"\nwrote {path}")
    print(f"wrote {path}.gz ({(path.stat().st_size) / 1e6:.0f} MB -> "
          f"{pathlib.Path(str(path) + '.gz').stat().st_size / 1e6:.0f} MB)")
    print(f"{len(written)} rows written\n")
    for col in COLUMNS:
        filled = sum(1 for r in written if r.get(col))
        if filled:
            print(f"  {col:<20} {filled:>6}  {100 * filled / len(written):5.1f}%")


if __name__ == "__main__":
    main()
