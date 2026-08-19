"""Download the deltaromeo UK/Ireland archive into raw/deltaromeo.zip.

Despite the Kaggle title saying 2015-2025 it holds archive_1988-2004,
archive_2005-2014, the recent years, and a BHA ratings folder. Columns include
sire, dam, DAMSIRE, sex, age, owner, official rating, RPR, topspeed and prize.

LICENCE: Community Data License Agreement - Sharing - Version 1.0. That is a
real open data licence permitting commercial redistribution, provided the data
is passed on under the same terms. Unlike the Kaggle hwaitt set (CC BY-NC) and
the ayuser Japan set (no licence at all), this one can ship in a paid build.

It is ~3.9 GB, easily the largest source here.
"""
import pathlib
import sys
import urllib.request

UA = "open-horse-data/1.0 (+https://github.com/jon-makinen/open-horse-data)"
DOWNLOAD = ("https://www.kaggle.com/api/v1/datasets/download/"
            "deltaromeo/horse-racing-results-ukireland-2015-2025")


def main():
    out = pathlib.Path(__file__).resolve().parent / "raw" / "deltaromeo.zip"
    out.parent.mkdir(exist_ok=True)
    if out.exists():
        print(f"{out} already present ({out.stat().st_size} bytes), skipping")
        return
    req = urllib.request.Request(DOWNLOAD, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=3600) as resp, open(out, "wb") as fh:
        total = 0
        while chunk := resp.read(1 << 22):
            fh.write(chunk)
            total += len(chunk)
            print(f"\r  {total / 1e9:.2f} GB", end="", file=sys.stderr)
    print(f"\nwrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
