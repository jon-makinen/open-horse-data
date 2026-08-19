"""Pull every item typed as a horse (Q726) from Wikidata into raw/wikidata.csv.

Two phases on purpose. A single query carrying all eight OPTIONALs plus the
label service silently truncates: it returns ~14,500 of the ~18,800 horses with
no error. So phase one asks only for the QID list, which is exact and stable,
and phase two fetches the details in chunks pinned to those QIDs. The row count
at the end must match the QID count, which is the check that the truncation has
not come back.
"""
import csv
import io
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "open-horse-data/1.0 (+https://github.com/jon-makinen/open-horse-data)"
ENDPOINT = "https://query.wikidata.org/sparql"
CHUNK = 400

LIST_QUERY = "SELECT ?h WHERE { ?h wdt:P31 wd:Q726 }"

DETAIL_QUERY = """
SELECT ?h ?hLabel ?foaled ?died ?sexLabel ?breedLabel ?sireLabel ?damLabel ?colourLabel ?countryLabel WHERE {
  VALUES ?h { %s }
  OPTIONAL { ?h wdt:P569 ?foaled }
  OPTIONAL { ?h wdt:P570 ?died }
  OPTIONAL { ?h wdt:P21 ?sex }
  OPTIONAL { ?h wdt:P4743 ?breed }
  OPTIONAL { ?h wdt:P22 ?sire }
  OPTIONAL { ?h wdt:P25 ?dam }
  OPTIONAL { ?h wdt:P462 ?colour }
  OPTIONAL { ?h wdt:P17 ?country }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""

FIELDS = ["h", "hLabel", "foaled", "died", "sexLabel", "breedLabel",
          "sireLabel", "damLabel", "colourLabel", "countryLabel"]


def query(sparql, attempts=4):
    url = ENDPOINT + "?" + urllib.parse.urlencode({"query": sparql})
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/csv"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                return resp.read().decode("utf-8")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            if attempt == attempts - 1:
                raise
            wait = 5 * (attempt + 1)
            print(f"  retry in {wait}s after {exc}", file=sys.stderr)
            time.sleep(wait)


def main():
    out = pathlib.Path(__file__).resolve().parent / "raw" / "wikidata.csv"
    out.parent.mkdir(exist_ok=True)

    qids = [r["h"].rsplit("/", 1)[-1]
            for r in csv.DictReader(io.StringIO(query(LIST_QUERY)))]
    print(f"{len(qids)} horses listed")

    rows, seen = [], set()
    for i in range(0, len(qids), CHUNK):
        chunk = qids[i:i + CHUNK]
        values = " ".join("wd:" + q for q in chunk)
        for r in csv.DictReader(io.StringIO(query(DETAIL_QUERY % values))):
            rows.append(r)
            seen.add(r["h"])
        print(f"  {i + len(chunk)}/{len(qids)} listed, {len(seen)} fetched")
        time.sleep(0.2)

    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"wrote {out}: {len(rows)} rows, {len(seen)} distinct horses")
    if len(seen) != len(qids):
        print(f"WARNING: expected {len(qids)} horses, got {len(seen)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
