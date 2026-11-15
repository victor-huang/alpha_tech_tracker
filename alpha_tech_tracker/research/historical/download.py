"""Download the raw source files behind the 2005-2019 historical dataset (Phase 1 of
research/docs/historical_data_2005_2019_plan.md).

Usage (from the repo root, with the keys in .env exported):

    python -m alpha_tech_tracker.research.historical.download wiki
    python -m alpha_tech_tracker.research.historical.download tiingo sec_cik alphavantage
    python -m alpha_tech_tracker.research.historical.download all

Each source lands untouched in market_data/historical/raw/<source>/; files that already exist are skipped, so a rerun
only fetches what is missing. Downloads stream to a .part file and are renamed only once complete.

Keys: NASDAQ_DATA_LINK_API_KEY (wiki), ALPHAVANTAGE_API_KEY (alphavantage), SEC_USER_AGENT (sec_cik).
"""
import argparse
import os
import time
from datetime import date
from typing import Callable, Dict, List, Optional

import requests

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DEFAULT_RAW_DIR = os.path.join(REPO_ROOT, "market_data", "historical", "raw")
WIKI_EXPORT_URL = "https://data.nasdaq.com/api/v3/datatables/WIKI/PRICES.json"
TIINGO_TICKERS_URL = "https://apimedia.tiingo.com/docs/tiingo/daily/supported_tickers.zip"
SEC_CIK_LOOKUP_URL = "https://www.sec.gov/Archives/edgar/cik-lookup-data.txt"
ALPHAVANTAGE_URL = "https://www.alphavantage.co/query"
ALPHAVANTAGE_FIRST_YEAR = 2013
ALPHAVANTAGE_LAST_YEAR = 2020
ALPHAVANTAGE_STATES = ("active", "delisted")
ALPHAVANTAGE_PAUSE_SECONDS = 15
EXPORT_POLL_SECONDS = 30
EXPORT_MAX_POLLS = 40
RETRIES = 4
CHUNK_BYTES = 1 << 20


def _request(url: str, params: Optional[dict] = None, headers: Optional[dict] = None,
             stream: bool = False, sleep: Callable[[float], None] = time.sleep) -> requests.Response:
    for attempt in range(RETRIES):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=300, stream=stream)
        except (requests.ConnectionError, requests.Timeout):
            if attempt + 1 == RETRIES:
                raise
            sleep(2 ** attempt * 5)
            continue
        if response.status_code not in (429, 500, 502, 503, 504):
            response.raise_for_status()
            return response
        sleep(2 ** attempt * 5)
    response.raise_for_status()
    return response


def download_file(url: str, path: str, params: Optional[dict] = None, headers: Optional[dict] = None) -> bool:
    """Stream url to path; False when path already exists."""
    if os.path.exists(path):
        print(f"exists, skipping {path}", flush=True)
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    partial = path + ".part"
    with _request(url, params=params, headers=headers, stream=True) as response, open(partial, "wb") as fh:
        for chunk in response.iter_content(CHUNK_BYTES):
            fh.write(chunk)
    os.replace(partial, path)
    print(f"wrote {path} ({os.path.getsize(path) / 1e6:.1f} MB)", flush=True)
    return True


def wiki_export_link(api_key: str, sleep: Callable[[float], None] = time.sleep) -> Dict[str, str]:
    """Ask for the WIKI/PRICES bulk export and wait until its zip is ready; returns the file block (link, status,
    data_snapshot_time)."""
    for _ in range(EXPORT_MAX_POLLS):
        body = _request(WIKI_EXPORT_URL, params={"qopts.export": "true", "api_key": api_key}).json()
        file_info = body["datatable_bulk_download"]["file"]
        if file_info["status"] in ("fresh", "regenerating") and file_info.get("link"):
            return file_info
        print(f"WIKI export status {file_info['status']}, waiting", flush=True)
        sleep(EXPORT_POLL_SECONDS)
    raise RuntimeError("WIKI export link was not ready in time")


def download_wiki(raw_dir: str) -> None:
    path = os.path.join(raw_dir, "wiki", "WIKI_PRICES.zip")
    if os.path.exists(path):
        print(f"exists, skipping {path}", flush=True)
        return
    file_info = wiki_export_link(os.environ["NASDAQ_DATA_LINK_API_KEY"])
    print(f"WIKI snapshot {file_info.get('data_snapshot_time')}", flush=True)
    download_file(file_info["link"], path)


def download_tiingo_tickers(raw_dir: str) -> None:
    download_file(TIINGO_TICKERS_URL, os.path.join(raw_dir, "tiingo", "supported_tickers.zip"))


def download_sec_cik_lookup(raw_dir: str) -> None:
    agent = os.environ.get("SEC_USER_AGENT", "").strip()
    if "@" not in agent:
        raise RuntimeError("set SEC_USER_AGENT to 'Your Name your.email@example.com' (SEC fair-access policy)")
    download_file(SEC_CIK_LOOKUP_URL, os.path.join(raw_dir, "sec", "cik-lookup-data.txt"),
                  headers={"User-Agent": agent, "Accept-Encoding": "gzip, deflate"})


def alphavantage_snapshot_dates(first_year: int = ALPHAVANTAGE_FIRST_YEAR,
                                last_year: int = ALPHAVANTAGE_LAST_YEAR) -> List[date]:
    """The first weekday of each January (the API rejects dates before 2010-01-01)."""
    days = []
    for year in range(first_year, last_year + 1):
        day = date(year, 1, 2)
        while day.weekday() >= 5:
            day = date(year, 1, day.day + 1)
        days.append(day)
    return days


def download_alphavantage(raw_dir: str, sleep: Callable[[float], None] = time.sleep) -> None:
    api_key = os.environ["ALPHAVANTAGE_API_KEY"]
    for day in alphavantage_snapshot_dates():
        for state in ALPHAVANTAGE_STATES:
            path = os.path.join(raw_dir, "alphavantage", f"listing_{day.isoformat()}_{state}.csv")
            if os.path.exists(path):
                continue
            text = _request(ALPHAVANTAGE_URL, params={"function": "LISTING_STATUS", "date": day.isoformat(),
                                                      "state": state, "apikey": api_key}).text
            if not text.startswith("symbol,"):
                raise RuntimeError(f"Alpha Vantage {day} {state}: {text[:200]}")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as fh:
                fh.write(text)
            print(f"wrote {path} ({text.count(chr(10)) - 1} rows)", flush=True)
            sleep(ALPHAVANTAGE_PAUSE_SECONDS)


SOURCES: Dict[str, Callable[[str], None]] = {
    "wiki": download_wiki,
    "tiingo": download_tiingo_tickers,
    "sec_cik": download_sec_cik_lookup,
    "alphavantage": download_alphavantage,
}


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("sources", nargs="+", choices=sorted(SOURCES) + ["all"])
    p.add_argument("--raw-dir", default=DEFAULT_RAW_DIR)
    return p.parse_args(argv)


def run(args: argparse.Namespace) -> None:
    names = sorted(SOURCES) if "all" in args.sources else args.sources
    for name in names:
        SOURCES[name](args.raw_dir)


if __name__ == "__main__":
    run(parse_args())
