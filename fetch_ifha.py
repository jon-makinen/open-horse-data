"""Dump the IFHA Longines World's Best Racehorse Rankings into raw/ifha.json.

Every edition since June 2013 lives at LWBRR.asp?batch=N, N counting up from 1.
An edition is a snapshot of the ratings as they stood on its closing date, so
the same horse recurs across editions and that repetition IS the useful part:
it is the only free source of a rating history for the top of world racing.

Rows are kept exactly as published, one dict per horse-per-edition, no dedupe.

  raw/ifha.json   [{batch, period_start, period_end, ranking, rating, ...}]

robots.txt for www.ifhaonline.org is "User-agent: *" / "Disallow:" (permissive).
"""
import html
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

UA = "open-horse-data/1.0 (+https://github.com/jon-makinen/open-horse-data)"
URL = "https://www.ifhaonline.org/resources/WTRRankings/LWBRR.asp?batch={}"

# Column headers as published: Ranking | Rating | Cat | Surface | Horse | YOF |
# Sex | Owner | Trainer | Trained. (A twelfth "Age" <th> exists but is commented
# out in the source, so the header row shows one more label than there are cells.)
FIELDS = ["ranking", "rating", "cat", "surface", "horse", "yof", "sex",
          "owner", "trainer", "trained"]

ROW = re.compile(r"<tr>(.*?)</tr>", re.S | re.I)
CELL = re.compile(r"<td[^>]*\bclass='(rank[A-Za-z]*)'[^>]*>(.*?)</td>", re.S | re.I)
TITLE = re.compile(r"<span class=\"Htwo\">(.*?)</span>", re.S | re.I)
PERIOD = re.compile(r"between\s+(.*?)\s+-\s+(.*)$", re.I)
ANNUAL = re.compile(r"raced in (\d{4})", re.I)
BRED = re.compile(r"\(([A-Z]{2,3})\)")


def call(url, attempts=4):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                # The server sends no charset and the bytes are cp1252, not
                # utf-8: André Fabre arrives as a bare 0xe9.
                return resp.read().decode("cp1252", "replace")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            if attempt == attempts - 1:
                raise
            wait = 10 * (attempt + 1)
            print(f"  retry in {wait}s after {exc}", file=sys.stderr)
            time.sleep(wait)


def text(raw):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", raw)).split())


def parse(page, batch):
    """Rows of one edition. Empty list means the batch number holds no edition."""
    m = TITLE.search(page)
    caption = " ".join(text(m.group(1)).split()) if m else ""
    # Interim editions caption a date span; the January annual, which is the
    # one that lists every horse rated 115+, captions a whole year instead.
    period, annual = PERIOD.search(caption), ANNUAL.search(caption)
    if period:
        start, end = period.groups()
    elif annual:
        start, end = f"1st January {annual.group(1)}", f"31st December {annual.group(1)}"
    else:
        start, end = "", ""

    rows = []
    for body in ROW.findall(page):
        cells = CELL.findall(body)
        # Legend tables at the foot of the page have plain <td>s, so the class
        # prefix alone separates ranking rows from decoration.
        if len(cells) != len(FIELDS) or cells[0][0] != "rankOne":
            continue
        row = {f: text(v) for f, (_, v) in zip(FIELDS, cells)}
        # Surface is spelled by the cell's class as well as its letter, and the
        # class is the unambiguous one: rankTurf / rankDirt / rankArt.
        row["surface_class"] = cells[3][0]
        # "Ka Ying Rising (NZ)", but Hong Kong imports trail a former-name note
        # after the country: "Lucky Nine (IRE) (ex Luck or Design)".
        country = BRED.search(row["horse"])
        row["horse"] = " ".join(BRED.sub("", row["horse"], count=1).split())
        row["bred"] = country.group(1) if country else ""
        rows.append({"batch": batch, "period_start": start, "period_end": end,
                     "annual": bool(annual), "edition": caption, **row})
    return rows


def fetch_all(start=1, stop_after_empty=2):
    """Walk batch numbers up from `start` until the editions run out."""
    rows, batches, empty, batch = [], [], 0, start
    while empty < stop_after_empty:
        found = parse(call(URL.format(batch)), batch)
        if found:
            rows += found
            batches.append(batch)
            empty = 0
        else:
            empty += 1
        if batch % 20 == 0 or not found:
            print(f"batch {batch}: {len(found)} rows ({len(rows)} total)")
        batch += 1
        time.sleep(0.5)
    return rows, batches


def main():
    out = pathlib.Path(__file__).resolve().parent / "raw"
    out.mkdir(exist_ok=True)

    rows, batches = fetch_all()
    (out / "ifha.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    horses = {r["horse"] for r in rows}
    print(f"wrote {out / 'ifha.json'} ({len(rows)} rows, {len(horses)} horses, "
          f"batches {batches[0]}-{batches[-1]})")


def demo():
    page = """<span class="Htwo">The LONGINES World's Best Racehorse Rankings
       for 3yos and upwards which raced between <BR>1st January 2026 - 9th August 2026</span>
<tr><td class='rankOne'>1</td>
<td class='rankTwo'>131</td><td class='rankThree'>S   </td><td class='rankTurf'>T   </td>
<td class='rankFiveShort'>Ka Ying Rising (NZ)   </td><td class='rankSix'>2020</td>
<td class='rankSeven'>G</td><td class='rankEight'>Ka Ying Syndicate</td>
<td class='rankEight'>David Hayes</td><td class='rankEight'>HK  </td></tr>
<tr><td>G</td><td align="center"><b>Gelding</b></td></tr>"""
    (row,) = parse(page, 144)
    assert row == {"batch": 144, "period_start": "1st January 2026",
                   "period_end": "9th August 2026", "annual": False,
                   "edition": "The LONGINES World's Best Racehorse Rankings for 3yos "
                              "and upwards which raced between 1st January 2026 - "
                              "9th August 2026",
                   "ranking": "1", "rating": "131", "cat": "S", "surface": "T",
                   "horse": "Ka Ying Rising", "yof": "2020", "sex": "G",
                   "owner": "Ka Ying Syndicate", "trainer": "David Hayes",
                   "trained": "HK", "surface_class": "rankTurf", "bred": "NZ"}, row
    year = page.replace("between <BR>1st January 2026 - 9th August 2026", "in 2025")
    assert parse(year, 138)[0]["period_end"] == "31st December 2025"
    assert parse(year, 138)[0]["annual"] is True
    assert parse("<tr><td>G</td><td><b>Gelding</b></td></tr>", 145) == []
    hk = page.replace("Ka Ying Rising (NZ)", "Lucky Nine (IRE)\n(ex Luck or Design)")
    assert parse(hk, 144)[0]["horse"] == "Lucky Nine (ex Luck or Design)"
    assert parse(hk, 144)[0]["bred"] == "IRE"
    print("demo ok")


if __name__ == "__main__":
    demo() if "--demo" in sys.argv else main()
