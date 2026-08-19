"""Cut horses.csv down to something Google Sheets will actually open.

Sheets caps a spreadsheet at 10 million cells, which the full build blows past
on row count alone. This keeps the competitive population and every ancestor
behind it, so no pedigree dead-ends mid-tree. Anyone who wants the whole thing
runs build_csv.py.

Turkey is dropped because TJK ratings are a separate scale, so a single rating
threshold would cut them at a rate that means nothing.
"""
import csv
import sys

DEFAULT_MIN_RATING = 70
DROP_COUNTRIES = {"Turkey"}
SRC = "out/horses.csv"
DST = "out/horses_sheets.csv"
CELL_CAP = 10_000_000


def rating(row):
    try:
        return float(row["Rating"])
    except ValueError:
        return 0.0


def ancestors(seed, by_name):
    """Every horse the seed's pedigree reaches, so no Sire or Dam dangles."""
    seen = set(seed)
    stack = list(seed)
    while stack:
        row = by_name.get(stack.pop())
        if row is None:
            continue
        for parent in (row["Sire"], row["Dam"]):
            if parent in by_name and parent not in seen:
                seen.add(parent)
                stack.append(parent)
    return seen


def select(rows, min_rating=DEFAULT_MIN_RATING):
    by_name = {r["Name"]: r for r in rows}
    seed = {r["Name"] for r in rows
            if r["Country"] not in DROP_COUNTRIES and rating(r) >= min_rating}
    return ancestors(seed, by_name)


def main():
    min_rating = DEFAULT_MIN_RATING
    if "--min-rating" in sys.argv:
        min_rating = float(sys.argv[sys.argv.index("--min-rating") + 1])
    csv.field_size_limit(10 ** 9)
    with open(SRC, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames
        rows = list(reader)

    keep = select(rows, min_rating)
    cells = len(keep) * len(columns)
    with open(DST, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        for row in rows:
            if row["Name"] in keep:
                writer.writerow([row.get(c, "") for c in columns])

    print(f"rating >= {min_rating:g}: {len(rows)} -> {len(keep)} rows, "
          f"{len(columns)} columns, {cells / 1e6:.2f}M cells "
          f"({100 * cells / CELL_CAP:.0f}% of the Sheets cap)")
    if cells > CELL_CAP:
        print("over the cap, raise --min-rating", file=sys.stderr)
        return 1
    return 0


def demo():
    """A foal below the bar still drags its whole pedigree in behind it."""
    rows = [{"Name": "Foal", "Country": "England", "Rating": "40",
             "Sire": "Pa", "Dam": "Ma"},
            {"Name": "Star", "Country": "England", "Rating": "99",
             "Sire": "Pa", "Dam": ""},
            {"Name": "Pa", "Country": "England", "Rating": "10",
             "Sire": "Grandpa", "Dam": ""},
            {"Name": "Grandpa", "Country": "England", "Rating": "10",
             "Sire": "", "Dam": ""},
            {"Name": "Ma", "Country": "England", "Rating": "10",
             "Sire": "", "Dam": ""},
            {"Name": "Ali", "Country": "Turkey", "Rating": "99",
             "Sire": "", "Dam": ""}]
    keep = select(rows)
    assert "Star" in keep, "rated horses are kept"
    assert "Pa" in keep and "Grandpa" in keep, "ancestors chain all the way up"
    assert "Foal" not in keep, "a low rating with no descendants goes"
    assert "Ma" not in keep, "and so does an ancestor only that foal needed"
    assert "Ali" not in keep, "dropped countries go regardless of rating"
    assert "Foal" in select(rows, 30), "a lower bar lets the foal itself in"
    assert "Star" not in select(rows, 100), "a higher bar shuts everything out"
    print("demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        sys.exit(main())
