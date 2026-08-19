"""Dump Hong Kong Jockey Club horse profiles for every horse currently in training.

HKJC is the only source that publishes a full, current pedigree + rating + prize
money record for a whole jurisdiction on one page per horse, server-rendered.
Roughly 1,250 horses are in training at any time.

One file comes out:
  raw/hkjc.json   {horseid: {field: value}}

Horse ids come from the A-Z index, never guessed: the id encodes a season and a
sequence (HK_2024_K564) with gaps all through it.

Only the in-training index is walked. The historical race archive is a different
crawl an order of magnitude larger, and none of it is horse data.

Usage:
  python3 fetch_hkjc.py          all horses
  python3 fetch_hkjc.py 15       first 15, for a cheap test
"""
import html
import json
import pathlib
import re
import string
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "open-horse-data/1.0 (+https://github.com/jon-makinen/open-horse-data)"
BASE = "https://racing.hkjc.com/en-us/local/information/"
INDEX = BASE + "selecthorsebychar?ordertype="
HORSE = BASE + "horse?horseid="
DELAY = 0.5

ANCHOR = re.compile(r'horse\?horseid=(HK_\d{4}_\w+)"[^>]*>([^<]+)</a>')

# The profile table is <tr><td>label</td><td>:</td><td>value</td></tr> throughout.
# The label cell must not swallow a nested <td>, or the page nav lands in it.
ROW = re.compile(
    r"<tr[^>]*>\s*<td[^>]*>((?:(?!<td)[\s\S])*?)</td>"
    r"\s*<td[^>]*>\s*:\s*</td>\s*<td[^>]*>([\s\S]*?)</td>")
TITLE = re.compile(r"<title>\s*(.*?)\s*(?:-\s*Horses)?\s*</title>", re.S)

# Labels worth keeping. Everything else on the page is navigation, or the
# "Same Sire" cross-sell list, which is a link farm not a field.
KEEP = {
    "Country of Origin / Age",
    "Colour / Sex",
    "Import Type",
    "Season Stakes*",
    "Total Stakes*",          # HKD
    "No. of 1-2-3-Starts*",   # wins-2nds-3rds-starts
    "Trainer",
    "Owner",
    "Current Rating",
    "Start of Season Rating",
    "Sire",
    "Dam",
    "Dam's Sire",
}


def call(url, attempts=4):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read().decode("utf-8", "replace")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            if attempt == attempts - 1:
                raise
            wait = 10 * (attempt + 1)
            print(f"  retry in {wait}s after {exc}", file=sys.stderr)
            time.sleep(wait)


def text(fragment):
    """Cell markup to plain text. <br /> is a line break, not a word join."""
    fragment = re.sub(r"<br\s*/?>", " ", fragment)
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    return " ".join(html.unescape(fragment).split())


def list_horses():
    """{horseid: name} for every horse in training, from the A-Z index."""
    horses = {}
    for letter in string.ascii_uppercase:
        page = call(INDEX + letter)
        found = ANCHOR.findall(page)
        horses.update({hid: text(name) for hid, name in found})
        print(f"{letter}: {len(found)} horses ({len(horses)} total)")
        time.sleep(DELAY)
    return horses


def parse_horse(page, name):
    record = {"name": name}
    for label, value in ROW.findall(page):
        label = text(label)
        if label in KEEP and label not in record:
            record[label] = text(value)
    return record


def fetch_horses(horses):
    result = {}
    for i, (hid, name) in enumerate(horses.items(), 1):
        page = call(HORSE + urllib.parse.quote(hid))
        record = parse_horse(page, name)
        if len(record) > 1:
            result[hid] = record
        else:
            print(f"  no fields parsed for {hid} ({name})", file=sys.stderr)
        if i % 50 == 0 or i == len(horses):
            print(f"{len(result)} profiles after {i} horses")
        time.sleep(DELAY)
    return result


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    out = pathlib.Path(__file__).resolve().parent / "raw"
    out.mkdir(exist_ok=True)

    horses = list_horses()
    print(f"{len(horses)} horses in the A-Z index")
    if limit:
        horses = dict(list(horses.items())[:limit])
        print(f"limited to {len(horses)}")

    profiles = fetch_horses(horses)
    (out / "hkjc.json").write_text(
        json.dumps(profiles, indent=1, ensure_ascii=False))
    print(f"wrote {out / 'hkjc.json'} ({len(profiles)} profiles)")


if __name__ == "__main__":
    main()
