"""Dump {{競走馬}} infoboxes from Japanese Wikipedia, plus a name crosswalk.

Japanese Wikipedia carries ~5,700 racehorse articles, ~3,500 of which have no
English article at all, and its infobox is richer than the English one. It also
carries a romanised English name in the 英 field, so katakana never has to be
transliterated.

Two files come out:
  raw/ja_wikipedia.json   {ja article title: {param: raw value}}
  raw/ja_crosswalk.csv    ja article title -> English label, from Wikidata

The crosswalk exists because 父 and 母 are wikilinks to Japanese titles. To chain
a pedigree those have to become English names, and Wikidata covers sires that
have no 競走馬 article of their own.
"""
import csv
import io
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "open-horse-data/1.0 (+https://github.com/jon-makinen/open-horse-data)"
API = "https://ja.wikipedia.org/w/api.php"
WDQS = "https://query.wikidata.org/sparql"
TEMPLATE = "Template:競走馬"

INFOBOX_START = re.compile(r"\{\{\s*競走馬")
PARAM = re.compile(r"^\s*\|\s*([^\s=|{}]+)\s*=\s*(.*?)\s*$", re.M)

# Infobox 競走馬 fields worth keeping. Anything else is presentation.
KEEP = {
    "名",    # katakana name
    "英",    # English name, the reason this source is usable at all
    "種",    # breed
    "性",    # sex
    "色",    # coat colour
    "生",    # foaled
    "死",    # died
    "父",    # sire
    "母",    # dam
    "母父",  # damsire
    "国",    # country of birth
    "産",    # breeder
    "主",    # owner
    "績",    # career record
    "金",    # earnings
}

CROSSWALK_QUERY = """
SELECT ?jaTitle ?enLabel WHERE {
  ?h wdt:P31 wd:Q726 .
  ?a schema:about ?h ; schema:isPartOf <https://ja.wikipedia.org/> ; schema:name ?jaTitle .
  ?h rdfs:label ?enLabel FILTER(lang(?enLabel) = "en")
}
"""


def call(params, attempts=4):
    params["format"] = "json"
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            if attempt == attempts - 1:
                raise
            wait = 10 * (attempt + 1)
            print(f"  retry in {wait}s after {exc}", file=sys.stderr)
            time.sleep(wait)


def extract_infobox(text):
    """Brace-balanced body of the {{競走馬}} template, or None."""
    m = INFOBOX_START.search(text)
    if not m:
        return None
    start = i = m.end()
    depth = 1
    while i < len(text) and depth:
        if text.startswith("{{", i):
            depth += 1
            i += 2
        elif text.startswith("}}", i):
            depth -= 1
            i += 2
        else:
            i += 1
    return text[start:i - 2] if depth == 0 else None


def list_titles():
    titles, cont = [], {}
    while True:
        data = call({
            "action": "query", "list": "embeddedin", "eititle": TEMPLATE,
            "eilimit": "500", "einamespace": "0", **cont,
        })
        titles += [p["title"] for p in data["query"]["embeddedin"]]
        if "continue" not in data:
            return titles
        cont = data["continue"]
        time.sleep(0.3)


def fetch_infoboxes(titles):
    result = {}
    for i in range(0, len(titles), 50):
        batch = titles[i:i + 50]
        data = call({
            "action": "query", "prop": "revisions", "rvprop": "content",
            "rvslots": "main", "titles": "|".join(batch),
        })
        for page in data["query"]["pages"].values():
            revs = page.get("revisions")
            if not revs:
                continue
            box = extract_infobox(revs[0]["slots"]["main"]["*"])
            if box is None:
                continue
            params = {k.strip(): v for k, v in PARAM.findall(box)}
            kept = {k: v for k, v in params.items() if k in KEEP and v}
            if kept:
                result[page["title"]] = kept
        print(f"{len(result)} infoboxes after {i + len(batch)} titles")
        time.sleep(0.3)
    return result


def fetch_crosswalk():
    url = WDQS + "?" + urllib.parse.urlencode({"query": CROSSWALK_QUERY})
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/csv"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                return resp.read().decode("utf-8")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            if attempt == 3:
                raise
            print(f"  crosswalk retry after {exc}", file=sys.stderr)
            time.sleep(10 * (attempt + 1))


def main():
    out = pathlib.Path(__file__).resolve().parent / "raw"
    out.mkdir(exist_ok=True)

    titles = list_titles()
    print(f"{len(titles)} pages transclude {TEMPLATE}")
    boxes = fetch_infoboxes(titles)
    (out / "ja_wikipedia.json").write_text(
        json.dumps(boxes, indent=1, ensure_ascii=False))
    print(f"wrote {out / 'ja_wikipedia.json'} ({len(boxes)} infoboxes)")

    body = fetch_crosswalk()
    (out / "ja_crosswalk.csv").write_text(body)
    n = sum(1 for _ in csv.DictReader(io.StringIO(body)))
    print(f"wrote {out / 'ja_crosswalk.csv'} ({n} ja->en name pairs)")


if __name__ == "__main__":
    main()
