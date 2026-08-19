"""Dump raw {{Infobox racehorse}} parameters for every English Wikipedia racehorse.

Raw wikitext on purpose, not DBpedia. DBpedia coerces these fields to numbers
and destroys them: the record "13: 9-2-1" becomes 1398.0 and the currency symbol
is stripped off earnings. The wikitext keeps "14: 14-0-0" and "GBP 2,998,302"
intact.
"""
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "open-horse-data/1.0 (+https://github.com/jon-makinen/open-horse-data)"
API = "https://en.wikipedia.org/w/api.php"
INFOBOX_START = re.compile(r"\{\{\s*Infobox racehorse", re.I)
PARAM = re.compile(r"^\s*\|\s*([A-Za-z0-9_ ]+?)\s*=\s*(.*?)\s*$", re.M)

# Only real Infobox racehorse fields. Params of templates nested inside a value
# sit on their own lines too, and without this whitelist they get scraped up as
# if they were top-level fields.
KEEP = {
    "horsename", "sire", "grandsire", "dam", "damsire", "sex", "foaled",
    "country", "colour", "color", "breeder", "owner", "trainer", "record",
    "earnings", "race", "awards", "honours", "honors", "breed", "death",
}


def extract_infobox(text):
    """Return the infobox body, brace-balanced.

    A `(.*?)\\n\\}\\}` regex misses every infobox that closes inline or contains a
    nested template, which cost ~570 pages on the first run.
    """
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
            wait = 5 * (attempt + 1)
            print(f"  retry in {wait}s after {exc}", file=sys.stderr)
            time.sleep(wait)


def list_titles():
    titles, cont = [], {}
    while True:
        data = call({
            "action": "query", "list": "embeddedin",
            "eititle": "Template:Infobox racehorse",
            "eilimit": "500", "einamespace": "0", **cont,
        })
        titles += [p["title"] for p in data["query"]["embeddedin"]]
        if "continue" not in data:
            return titles
        cont = data["continue"]
        time.sleep(0.2)


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
            text = revs[0]["slots"]["main"]["*"]
            box = extract_infobox(text)
            if box is None:
                continue
            params = {k.strip().lower(): v for k, v in PARAM.findall(box)}
            result[page["title"]] = {k: v for k, v in params.items()
                                     if k in KEEP and v}
        print(f"{len(result)} infoboxes after {i + len(batch)} titles")
        time.sleep(0.2)
    return result


def main():
    out = pathlib.Path(__file__).resolve().parent / "raw" / "wikipedia.json"
    out.parent.mkdir(exist_ok=True)
    titles = list_titles()
    print(f"{len(titles)} pages transclude the template")
    out.write_text(json.dumps(fetch_infoboxes(titles), indent=1, ensure_ascii=False))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
