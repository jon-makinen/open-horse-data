"""Download the hwaitt/horse-racing archive from Kaggle into raw/hwaitt.zip.

LICENCE: CC BY-NC 4.0. Non-commercial only, attribution required. This is fine
for a free community mod and is NOT fine shipped inside a paid game. Everything
else in this pipeline is commercially usable; this one source is not.

The dataset is rpscrape output republished by a third party, so its CC tag
cannot grant rights over Racing Post's own derived data. Only the `OR` column
(the BHA official rating, published as a regulatory act) is used downstream;
`RPR` and `TR` are Racing Post proprietary and are ignored.

Kaggle's download endpoint 302s to a signed Google Storage URL that needs no
API key, so no credentials are required.
"""
import pathlib
import sys
import urllib.request

UA = "open-horse-data/1.0 (+https://github.com/jon-makinen/open-horse-data)"
DOWNLOAD = "https://www.kaggle.com/api/v1/datasets/download/hwaitt/horse-racing"


def main():
    out = pathlib.Path(__file__).resolve().parent / "raw" / "hwaitt.zip"
    out.parent.mkdir(exist_ok=True)
    if out.exists():
        print(f"{out} already present ({out.stat().st_size} bytes), skipping")
        return
    print("CC BY-NC 4.0: non-commercial use only. Mod, not shipped game.")
    req = urllib.request.Request(DOWNLOAD, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=600) as resp, open(out, "wb") as fh:
        total = 0
        while chunk := resp.read(1 << 20):
            fh.write(chunk)
            total += len(chunk)
            print(f"\r  {total / 1e6:.0f} MB", end="", file=sys.stderr)
    print(f"\nwrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
