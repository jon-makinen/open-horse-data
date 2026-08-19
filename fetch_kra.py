"""Dump the Korean Racing Authority studbook registers to raw/kra.json.

studbook.kra.co.kr is a server-rendered JSP site in EUC-KR. Every register page
builds a hidden "download to Excel" form whose <input name="id"> values carry the
WHOLE register as semicolon-joined rows, first row being the column headers, no
matter what the visible table is paged to. So one request per register is enough
and the crawl-delay of 10s costs a minute for the lot.

Two headers are mandatory:
  User-Agent  a browser string, anything else gets 403 on /studbook.jsp
  Cookie      jsCheck=valid, otherwise /html/ pages return a 91-byte JS stub
              that only sets that cookie and reloads

robots.txt allows everything except /board and asks for Crawl-delay:10.

Pass register names as arguments to fetch a subset, e.g.
  python3 fetch_kra.py stallions racehorses
"""
import html
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

BASE = "https://studbook.kra.co.kr"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
CRAWL_DELAY = 10

# linecount is what the paged registers honour; the rest ignore it and dump
# everything anyway. 99999 clears the biggest register (retirements, ~22.5k).
QUERY = "?pg=1&sort=0&search=&linecount=99999&meet="

REGISTERS = {
    "racehorses":  "/html/info/com/s_rhr_list2.jsp",    # 경주마내역
    "youngstock":  "/html/info/com/s_ghr_list.jsp",     # 육성마내역
    "stallions":   "/html/info/com/s_bhr_list.jsp",     # 씨수말내역
    "broodmares":  "/html/info/com/s_bhr_list2.jsp",    # 씨암말내역
    "geldings":    "/html/info/s_sex_clinic_list.jsp",  # 거세수술내역
    "retirements": "/html/info/s_discard_list.jsp",     # 경주마퇴역내역
}

ROW = re.compile(r'<input type="hidden" name="id" value="([^"]*)">')


def call(path, attempts=4):
    req = urllib.request.Request(
        BASE + path, headers={"User-Agent": UA, "Cookie": "jsCheck=valid"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                body = resp.read()
                break
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            if attempt == attempts - 1:
                raise
            wait = CRAWL_DELAY * (attempt + 1)
            print(f"  retry in {wait}s after {exc}", file=sys.stderr)
            time.sleep(wait)
    try:
        return body.decode("euc-kr")
    except UnicodeDecodeError:
        return body.decode("cp949", "replace")


def parse(page):
    """Hidden Excel-form rows to dicts keyed by the Korean column headers."""
    rows = [html.unescape(r).split(";") for r in ROW.findall(page)]
    if not rows:
        return []
    header = rows[0]
    assert len(header) > 1, f"no column header, got {header!r}"
    return [dict(zip(header, r)) for r in rows[1:]]


def main():
    out = pathlib.Path(__file__).resolve().parent / "raw"
    out.mkdir(exist_ok=True)

    wanted = sys.argv[1:] or list(REGISTERS)
    data = {}
    for i, name in enumerate(wanted):
        if i:
            time.sleep(CRAWL_DELAY)
        page = call(REGISTERS[name] + QUERY)
        data[name] = parse(page)
        print(f"{name}: {len(data[name])} rows "
              f"({', '.join(data[name][0]) if data[name] else 'empty'})")

    path = out / "kra.json"
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    print(f"wrote {path} ({sum(len(v) for v in data.values())} rows)")


if __name__ == "__main__":
    main()
