"""Replace the romanised Japanese names in out/horses.csv with the real ones.

build_csv.py resolves a Japanese name three ways: the horse's JBIS id joined to
Wikidata, the ja.wikipedia crosswalk, then Hepburn romanisation of the katakana.
Romanisation is the fallback and it is only an approximation, so Stealth Sonic
ships as "Suterususonikku".

A fan resolved 25,165 of those back to their official English names. The list is
keyed on the romanisation build_csv.py emitted, not on the katakana, which is
what makes it joinable here without rebuilding anything.

    python3 fix_ja_names.py [in.csv] [out.csv]     # both default to out/horses.csv

Run it once, on a file build_csv.py just wrote. A handful of entries chain
("Shitorika" resolves to "Citrica", and a different horse called "Citrica"
resolves to "Elianthos"), so a second pass would follow the chain and merge two
horses that are not the same animal. A file that has already been through here
is detected and left alone.
"""
import collections
import csv
import re
import sys

import parsers as P

SRC = "out/horses.csv"
FANLIST = "raw/Translated Japanese Honse Names - resolved_name.csv"
PEDIGREE = ("Sire", "Dam", "Damsire")

# An unnamed Japanese foal is registered as its dam plus a foaling year, so
# 3,140 rows of the list read "Sunday Story 2006" or just "2006". Taking those
# would be worse than romanising: clean_name reads a trailing number as a
# studbook entry and strips it, filing the foal under its own dam.
UNNAMED = re.compile(r"(?:19|20)\d\d$")

# Names are unique within a studbook, not globally, so every name in the file
# carries its country of birth. Only (JPN) names were ever romanised.
JPN = re.compile(r"\s*\(JPN\)\s*$", re.I)


def load_fanlist(path=FANLIST):
    """{normalised romanisation: official English name}."""
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            official = " ".join((r.get("official_name") or "").split())
            key = P.norm_name(r.get("original_name") or "")
            if key and re.search(r"[A-Za-z]", official) and not UNNAMED.search(official):
                out[key] = official
    return out


def merge_row(keep, drop):
    """Fill the blanks in `keep` from `drop`. The row already under the official
    name wins every conflict: it came from a named source, not a romanisation."""
    for col, value in drop.items():
        if value and not keep.get(col):
            keep[col] = value


def same_horse(a, b):
    """Foaling years within a year of each other, the tolerance build_csv.py
    already uses when it merges a Japanese row into an existing horse."""
    x, y = a.get("Foaled", ""), b.get("Foaled", "")
    return x.isdigit() and y.isdigit() and abs(int(x) - int(y)) <= 1


def main(src=SRC, dst=SRC):
    fan = load_fanlist()
    with open(src, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        columns = reader.fieldnames
        rows = list(reader)

    # Group every row under the name it would end up with. A rename can land on
    # a name the file already holds, which is the point: "Abarurata (JPN)" and
    # "A Ballata (JPN)" are one horse entered twice, and the whole reason they
    # were not merged during the build is that the romanisation hid it.
    def rename_of(row):
        """The official name for this row, or None if the list has nothing new."""
        if not JPN.search(row["Name"]):
            return None
        official = fan.get(P.norm_name(row["Name"]))
        # An entry that agrees with the name the row already carries is not a
        # rename. Treating it as one would park the row in the ambiguous pile
        # under a name the file already holds, which is the one thing to avoid.
        if not official or P.norm_name(official) == P.norm_name(row["Name"]):
            return None
        return official

    # A fresh build matches ~96% of the list; anything under 5% means this file
    # has been through here already. Carrying on would chase the chained entries
    # and silently merge distinct horses, so stop before writing anything.
    candidates = sum(1 for row in rows if rename_of(row))
    if candidates * 20 < len(fan):
        print(f"{src} already has its Japanese names resolved "
              f"({candidates} of {len(fan)} list entries still match). Nothing written.")
        return

    groups = collections.defaultdict(list)
    for row in rows:
        official = rename_of(row)
        groups[(P.norm_name(official or row["Name"]), row.get("Country", ""))].append(
            (official, row))

    renamed = {}                     # normalised romanisation -> official name
    merged = ambiguous = 0
    keep = []
    for members in groups.values():
        # Rows already under the official name are the ones to merge into.
        settled = [row for official, row in members if not official]
        held = []
        for official, row in members:
            if not official:
                continue
            twin = next((r for r in settled if same_horse(r, row)), None)
            if twin is not None:
                merge_row(twin, row)
                renamed[P.norm_name(row["Name"])] = official
                merged += 1
            elif settled:
                # Same name, same country, foaled years apart: two different
                # horses. Renaming would make them indistinguishable, and the
                # romanisation at least keeps them apart.
                ambiguous += 1
                held.append(row)
            else:
                renamed[P.norm_name(row["Name"])] = official
                row["Name"] = P.suffixed(official, row.get("Country") or "Japan")
                settled.append(row)
        keep.extend(settled)
        keep.extend(held)

    # A rename is only half the job: 5,484 sire, dam and damsire fields point at
    # these horses by their romanised name, and leaving those behind would break
    # the pedigree links the dataset exists for.
    refs = 0
    for row in keep:
        for col in PEDIGREE:
            value = row.get(col) or ""
            if not JPN.search(value):
                continue
            official = renamed.get(P.norm_name(value))
            if official:
                row[col] = P.suffixed(official, "Japan")
                refs += 1

    keep.sort(key=lambda r: r["Name"].upper())
    with open(dst, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(keep)

    print(f"fan list: {len(fan)} usable names")
    print(f"renamed {len(renamed)} horses, merged {merged} duplicate rows, "
          f"rewrote {refs} pedigree references")
    print(f"{ambiguous} left romanised: the official name is already taken in "
          f"Japan by a horse foaled more than a year apart")
    print(f"{len(rows)} rows in, {len(keep)} rows out -> {dst}")


def _selfcheck():
    assert not UNNAMED.search("Stealth Sonic")
    assert UNNAMED.search("Sunday Story 2006")
    assert JPN.search("Abarurata (JPN)") and not JPN.search("Frankel (GB)")
    a, b = {"Foaled": "2014"}, {"Foaled": "2015"}
    assert same_horse(a, b) and not same_horse(a, {"Foaled": "2010"})
    assert not same_horse(a, {"Foaled": ""})
    keep, drop = {"Name": "A Ballata", "Sire": "", "Wins": "3"}, {"Sire": "Deep Brillante", "Wins": "0"}
    merge_row(keep, drop)
    assert keep["Sire"] == "Deep Brillante" and keep["Wins"] == "3"
    print("fix_ja_names self-check passed")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        _selfcheck()
    else:
        args = [a for a in sys.argv[1:] if not a.startswith("-")]
        main(*(args or [SRC]))
