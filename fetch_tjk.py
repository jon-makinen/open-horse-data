"""Dump the Turkish Jockey Club Orijin table: every horse TJK has ever registered.

TJK is the only public source for Turkish-bred pedigrees, ~113k horses, and it
carries sire, dam and damsire for each one. There is no API. The site renders
the table in 50-row pages through an ajax endpoint that answers a plain form
POST, so the whole set comes out in ~2,266 requests.

Two quirks the hard way:
  - the CDN 404s valid pages unless the User-Agent looks like a real browser.
  - the Orijin table has two distinct Owner columns (registered owner with the
    share percentage, and the owner the horse actually ran for), so duplicate
    header labels get the field code appended to keep the keys unique.

Column keys are read off the live <th> row rather than hardcoded, so a TJK
layout change shows up as new keys instead of silently shifted values.
"""
import argparse
import html
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
TABLE = "https://www.tjk.org/EN/YarisSever/Query/Data/Orijin"
ROWS = "https://www.tjk.org/EN/YarisSever/Query/DataRows/Orijin"
PER_PAGE = 50
PAUSE = 0.3

HEADER = re.compile(r'<th[^>]*>\s*<a name="([^"]+)"[^>]*>(.*?)</a>', re.S)
CELL = re.compile(r'<td class="sorgu-Orijin-([A-Za-z0-9]+)"[^>]*>(.*?)</td>', re.S)
ROW = re.compile(r'<tr[^>]*>(.*?)</tr>', re.S)
HORSE_ID = re.compile(r"QueryParameter_AtId=(\d+)")
TOTAL = re.compile(r"records out of\s+([\d]+)\s+are shown")
TAG = re.compile(r"<[^>]+>")


def call(url, data=None, attempts=4):
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers={"User-Agent": UA})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read().decode("utf-8", "replace")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            if attempt == attempts - 1:
                raise
            wait = 5 * (attempt + 1)
            print(f"  retry in {wait}s after {exc}", file=sys.stderr)
            time.sleep(wait)


def text(fragment):
    return re.sub(r"\s+", " ", html.unescape(TAG.sub(" ", fragment))).strip()


def columns(page):
    """{field code: key} from the live header row, deduped on repeated labels."""
    keys, seen = {}, set()
    for code, label in HEADER.findall(page):
        label = text(label)
        keys[code] = f"{label} ({code})" if label in seen else label
        seen.add(label)
    return keys


def parse(fragment, keys):
    horses = []
    for row in ROW.findall(fragment):
        cells = CELL.findall(row)
        if not cells:
            continue
        horse = {keys.get(code, code): text(value) for code, value in cells}
        found = HORSE_ID.search(row)
        if found:
            horse["AtId"] = found.group(1)
        horses.append(horse)
    return horses


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pages", type=int, default=10,
                    help="pages to fetch, 50 horses each; 0 means all of them")
    ap.add_argument("--resume", action="store_true",
                    help="keep raw/tjk.json and carry on after the last full page")
    args = ap.parse_args()

    out = pathlib.Path(__file__).resolve().parent / "raw" / "tjk.json"
    out.parent.mkdir(exist_ok=True)

    first = call(TABLE)
    keys = columns(first)
    total = TOTAL.search(first)
    total = int(total.group(1)) if total else 0
    print(f"{total} horses, {-(-total // PER_PAGE)} pages")
    print(f"columns: {', '.join(keys.values())}")

    horses = []
    start = 1
    if args.resume and out.exists():
        horses = json.loads(out.read_text())
        start = len(horses) // PER_PAGE + 1
        horses = horses[:(start - 1) * PER_PAGE]
        print(f"resuming from page {start} with {len(horses)} horses")

    page = start
    while args.pages == 0 or page < start + args.pages:
        batch = parse(call(ROWS, {"PageNumber": page}), keys)
        if not batch:
            print(f"page {page} is empty, done")
            break
        horses += batch
        if page % 20 == 0 or page == start:
            print(f"{len(horses)} horses after page {page}")
            out.write_text(json.dumps(horses, indent=1, ensure_ascii=False))
        page += 1
        time.sleep(PAUSE)

    out.write_text(json.dumps(horses, indent=1, ensure_ascii=False))
    print(f"wrote {out} ({len(horses)} horses)")


if __name__ == "__main__":
    main()
