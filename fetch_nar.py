"""Download the ayuser/horse-racing-in-japan archive into raw/ayuser_japan.zip.

Japanese NAR and JRA race results 2010-2021, ~2.17m runner rows covering ~90,600
distinct horses. Unlike every other Japanese source that is reachable, this one
carries SIRE and DAM per runner, which is what the pipeline was missing.

LICENCE: the Kaggle page declares "Unknown", which grants nothing explicitly.
That is weaker than CC BY-NC, not equal to it. The contents are race results,
and facts are not copyrightable, but there is no licence here to rely on. Use
for a free community build only, and delete raw/ayuser_japan.zip to build
without it.

Kaggle's download endpoint 302s to a signed Google Storage URL needing no key.
"""
import pathlib
import sys
import urllib.parse
import urllib.request

UA = "open-horse-data/1.0 (+https://github.com/jon-makinen/open-horse-data)"
DOWNLOAD = "https://www.kaggle.com/api/v1/datasets/download/ayuser/horse-racing-in-japan"
WDQS = "https://query.wikidata.org/sparql"

# The archive keys horses by their JBIS id, and Wikidata carries that id (P10785)
# alongside an English label. That is an ID join rather than a name match, so it
# gives the official English name for every horse both sources know.
JBIS_QUERY = """
SELECT ?jbis ?enLabel WHERE {
  ?h wdt:P31 wd:Q726 ; wdt:P10785 ?jbis ; rdfs:label ?enLabel .
  FILTER(lang(?enLabel) = "en")
}
"""


def main():
    out = pathlib.Path(__file__).resolve().parent / "raw" / "ayuser_japan.zip"
    out.parent.mkdir(exist_ok=True)
    if out.exists():
        print(f"{out} already present ({out.stat().st_size} bytes), skipping")
        return
    print("Licence is 'Unknown' on Kaggle. Community build only.")
    req = urllib.request.Request(DOWNLOAD, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=900) as resp, open(out, "wb") as fh:
        total = 0
        while chunk := resp.read(1 << 20):
            fh.write(chunk)
            total += len(chunk)
            print(f"\r  {total / 1e6:.0f} MB", end="", file=sys.stderr)
    print(f"\nwrote {out} ({out.stat().st_size} bytes)")
    fetch_jbis_crosswalk(out.parent)


def fetch_jbis_crosswalk(raw):
    path = raw / "jbis_crosswalk.csv"
    url = WDQS + "?" + urllib.parse.urlencode({"query": JBIS_QUERY})
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/csv"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        body = resp.read()
    path.write_bytes(body)
    print("wrote %s (%d JBIS id to English name pairs)" % (path, body.count(b"\n") - 1))


if __name__ == "__main__":
    main()
