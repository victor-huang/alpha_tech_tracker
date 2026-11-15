# Plan: 2005–2019 daily data for the research backtests

Goal: run the research scripts (`uptrend_formation`, `selection_filters`, `recommended_rules`, the `top_n_by_year` books) on 2005–2019. The universe should include companies that were later delisted or acquired, and the research code should stay unchanged.

## What the backtests read today

Every research script gets its data through these interfaces, so they are the points where new data plugs in:

| Interface | Used for | Current source | Limit |
|---|---|---|---|
| `AlpacaData.listed_stocks()` → index `symbol`, cols `name`, `exchange` | universe, `drop_funds` name filter | Alpaca active assets | stocks listed today only |
| `AlpacaData.daily_bars(symbols, start, end)` → long rows `symbol, timestamp (UTC), close, volume`, split + dividend adjusted | `DailyBarCache` → wide close / dollar volume | Alpaca SIP | starts 2016 |
| `AlpacaData.raw_closes(symbols, day)` → `{symbol: unadjusted close}` | market cap → tier | Alpaca SIP raw | starts 2016 |
| `SharesCache(path, fetcher)` → share-count series per symbol | market cap → tier | yfinance `get_shares_full` | starts ~2015 |
| `FundamentalsCache` / `IndustryCache` | Small and Mid factors, industry caps | SEC companyfacts.zip, SIC | XBRL from 2009; ticker → CIK map is current tickers only |
| `top_n_charts.fetch_ohlc` | trade chart PDFs | Alpaca bars (OHLC) | starts 2016 |

`DailyBarCache.seed(bars, fetched_on, symbols)` already splits one bulk download into monthly partitions. Every script also accepts `--cache-dir`, so the historical data can live in its own cache. That matters because its adjustment basis differs from Alpaca's, so the two caches must not mix.

## Sources

| Source | Gives | Cost | Covers |
|---|---|---|---|
| Quandl WIKI/PRICES (Nasdaq Data Link bulk export) | raw + adjusted OHLCV, split ratio, dividends | free key | ~3,000 names, 2005 → 2018-03-27, includes some dead names (to verify) |
| Alpha Vantage `LISTING_STATUS` (active + delisted, `date=`) | which tickers were listed on a date, with name, exchange, asset type, IPO and delist dates | free key, 25 calls/day | the universe for each year (check how far back `date=` goes) |
| Tiingo `supported_tickers.zip` | ticker start/end dates, exchange, asset type | free, no key | cross-check of the universe |
| yfinance | OHLCV for names still listed that WIKI lacks | free | names still listed today only (tested: CELG, YHOO, TWX, SHLD empty) |
| Tiingo EOD API | OHLCV for delisted names WIKI lacks | free tier: 500 symbols/month (paid ~$30/month, not used) | delisted tickers no other company has reused |
| Alpaca SIP (already cached) | 2016-10 onward | have it | overlaps WIKI 2016-10 → 2018-03, used to check the join |
| SEC companyfacts.zip (already have, 1.42 GB) + `cik-lookup-data.txt` | shares outstanding and fundamentals from 2009; CIKs for old names | free | XBRL filings 2009+ |

## Phases

### Phase 0: keys and checks (half a day)
- Add `NASDAQ_DATA_LINK_API_KEY`, `ALPHAVANTAGE_API_KEY` (and `TIINGO_API_KEY` if you pay) to `.env`.
- Checks before downloading in bulk:
  1. ~~WIKI: which dead names are in it?~~ **Checked 2026-11-14.** It has names that died **from 2014 on**: CELG, MON, YHOO (to 2017-06), TWX, and SHLD from 2005. It has **none of the 2008 failures**: LEH, BSC, WaMu, MER, WB and CFC are missing. Old GM is missing too (WIKI's `GM` starts at the 2010 IPO). Its `WM` is Waste Management's history all the way back, not Washington Mutual. WIKI keys history by the ticker's current owner.
  2. ~~Alpha Vantage `LISTING_STATUS` for 2005?~~ **No.** `date=` must be 2010-01-01 or later. Its delisted list (9,638 rows) is also nearly empty before 2013: 1, 2, 5, 40 and 46 delistings for 2006–2010, against ~140–770 a year for 2013–2019. Use it only for 2013+.
  - Tiingo `supported_tickers.zip` (downloaded, 16,342 US stocks): also no LEH, BSC, CFC or WaMu; MER is there 2006–2008. It counts 3,179 listed stocks on 2005-01-02, 3,993 in 2008, 4,769 in 2013 and 5,895 in 2019.
  - **What this means:** no free source (Tiingo's paid data included) has the big 2005–2010 failures. Free 2005–2010 results stay biased toward survivors and should be read as an upper bound. From 2014 on, coverage of delisted names is good: WIKI to 2018-03 and Alpaca from 2016.
  - **Universe sources, revised:** 2005–2012 = the WIKI tickers plus the Tiingo listing dates; 2013–2019 = the same, plus the Alpha Vantage snapshots and Alpaca's inactive list.
  3. ~~Alpaca: does `daily_bars` return 2016–2019 bars for an INACTIVE asset?~~ **Yes (checked 2026-11-14).** Alpaca lists 19,150 inactive US equities and returns SIP bars from 2016 for delisted names: CELG, RHT, ANDV, TWX, MON and SHLD all came back. TWX and MON are missing from its inactive list but their bars still return, so request by symbol rather than relying on the list. **Catch:** after the last trade Alpaca pads the series with flat, zero-volume bars. MON repeats 127.95 from 2018-06 to 2019-12-31, and SHLD repeats 0.3372 after its 2018-10 bankruptcy. Every Alpaca series must be cut at its last bar with volume above zero. Alpaca therefore covers delisted names for 2016-01 → 2019, and WIKI is needed only for 2005 → 2015.

- **Phase 1 result (2026-11-14):** `WIKI_PRICES.zip` is 463 MB, one 1.8 GB CSV, snapshot 2026-02-03. It has 15.4M rows and 3,199 tickers, 1962-01-02 → 2018-03-27, with columns `ticker, date, open, high, low, close, volume, ex-dividend, split_ratio, adj_open, adj_high, adj_low, adj_close, adj_volume`. Tickers trading on Jan 3: 2,153 (2005), 2,492 (2008), 2,596 (2010), 2,924 (2013), 2,879 (2016), 2,491 (2018). **No WIKI ticker ends before 2014.** Its 728 dead tickers ended in 2014 (102), 2015 (194), 2016 (216), 2017 (193) and 2018 (23). So WIKI contributes delisted names only from 2014, and every company that died in 2005–2013 is missing. Also downloaded: Tiingo `supported_tickers.zip` (0.8 MB) and SEC `cik-lookup-data.txt` (40.5 MB).

### Phase 1: download raw files (1–2 days, mostly waiting)
Each source goes in its own folder under `market_data/historical/raw/<source>/`. Raw files stay untouched, so any later step can be rerun.
- `wiki/WIKI_PRICES.zip`: one bulk export (`qopts.export=true`).
- `alphavantage/listing_<YYYY>-01-02_{active,delisted}.csv`: 2013–2020 (the API rejects dates before 2010), 16 calls in one day.
- `tiingo/supported_tickers.zip`.
- `sec/cik-lookup-data.txt`.
- Script: `research/historical/download.py <source>`. It skips files that already exist and retries with backoff.

### Phase 2: security master (1 day)
`market_data/historical/wiki_runs.pkl` + `listings.pkl` (pickle like the other caches; no pyarrow in the env), one row per security: `security_id, symbol, name, exchange, asset_type, first_day, last_day, cik, sources`.
- Join the Alpha Vantage snapshots, the Tiingo ticker list and the WIKI symbols on symbol plus overlapping date ranges.
- **Ticker reuse:** when two companies used the same symbol within 2005–2019, the older one gets `symbol~YYYY` (its last year). The research code only ever sees `symbol`, so the two never merge into one price series.
- Drop non-operating names with the existing `NON_OPERATING_NAME_RE` and `asset_type == Stock`.
- Fill CIK from `company_tickers.json` (current tickers), then name-match against `cik-lookup-data.txt` for dead names.

- **Phase 2 result (2026-11-14, `historical/securities.py`):**
  - **WIKI hands over to Alpaca on 2016-01-01**, not 2016-10. Alpaca has every stock, dead ones included, from 2016-01. WIKI went stale for some live companies before its end (AN stops 2017-08 and ATI 2017-04, then both have 5 stray days in 2018-03), so its data after 2015 is used only for the Phase 7 overlap check.
  - **Same company or new one:** a ticker becomes a new company after a gap of over 365 days, or over 30 days with the adjusted price more than 2× off. A plain 30-day rule split 551 tickers, mostly thinly traded names with holes; the new rule splits 24, including the real 2015 Energizer spin-off (ENR) and HERO's change into an ETF.
  - **Names:** 89% of WIKI tickers get a name; 75% get a CIK, from the current SEC ticker list or an exact name match. Only plain-letter symbols count. Tickers spelled NA, NAN or NULL must be read as text, not as missing values.
  - **Coverage (Jan 2, operating stocks on NYSE/NASDAQ/AMEX):**

    | Year | Listed | In WIKI | Missing, still listed today (→ yfinance) | Missing, gone (no free source) |
    |---|---|---|---|---|
    | 2005 | 3,050 | 1,805 | 718 | 527 |
    | 2008 | 3,824 | 2,091 | 896 | 837 |
    | 2010 | 4,008 | 2,174 | 961 | 873 |
    | 2013 | 4,512 | 2,440 | 1,105 | 967 |
    | 2015 | 4,954 | 2,554 | 1,327 | 1,073 |

    "Listed" uses Tiingo's dates, plus Alpha Vantage listings Tiingo lacks. Alpha Vantage's own dates overcount: 7,089 in 2019 against Tiingo's 5,492.

### Phase 3: fill price gaps (1 day of work + Tiingo pull time)
- Gap list = securities listed for any day in 2005–2019 whose days WIKI doesn't cover (before 2018-03) and Alpaca doesn't cover (after 2016-10).
- Still listed → yfinance. Delisted → Alpaca if the Phase 0 check passes, then Tiingo free tier for the 500 most-traded remaining names a month.
- Write each source's rows to `market_data/historical/prices/<source>/<year>.parquet`.

### Phase 4: normalize (1 day)
`market_data/historical/daily/<year>.parquet`, long format: `symbol, day, open, high, low, close, volume, raw_close, adj_factor, source`.
- `close/open/high/low` are split + dividend adjusted, to match Alpaca `Adjustment.ALL`. `raw_close` is unadjusted.
- yfinance `Close` is split-adjusted but not raw, so rebuild `raw_close` from its split history.
- **Cut every series at its last bar with volume above zero**, for every source. Alpaca pads delisted names with flat zero-volume bars (MON, SHLD). WIKI has stray zero-volume rows after the real end: DELL trades until 2013-10-29 at ~$13.85, then has 42 rows in 2015-01..03 at a flat $31.30, which a backtest would book as a +126% jump. Also drop zero-volume rows inside a series when the close differs from the previous close (stale or bad prints).
- Source by date: WIKI through 2015-12-31, Alpaca from 2016-01-01; yfinance (and the Tiingo free tier) only for gaps before 2016. Rescale each source onto the newest source's basis where they overlap (the same chain-link idea as `_link_factors`).

### Phase 5: shares outstanding (1 day)
Build `market_data/historical/shares.json` in the format `SharesCache` reads. Each dated share count is taken from `dei:EntityCommonStockSharesOutstanding` in companyfacts, keyed by filing date. The research code reads that date only, so it never sees a count before it was public.
- **Before 2009** there is no free source of dated share counts. Pick one proxy (decision 2 below).

### Phase 6: adapter + switches in the scripts (1–2 days)
- New `research/historical/data.py` with `HistoricalData`, using the same method names as `AlpacaData`:
  - `listed_stocks(as_of=None)`: the security master (all names, including dead ones). The point-in-time universe already follows from the bars, because `start_of_year_universe` only keeps names with a price and enough liquidity on the day before the year starts.
  - `daily_bars(symbols, start, end)`: read from the Phase 4 parquet and return the same long format with a UTC `timestamp`.
  - `raw_closes(symbols, day)`: the last `raw_close` on or before `day`.
  - `ohlc(symbols, start, end)`: for the chart scripts.
- `research/historical/seed_cache.py`: fills `market_data/historical_cache/daily_bars/` through `DailyBarCache.seed()`.
- Small edit in each script that builds `AlpacaData()` (`uptrend_formation`, `selection_filters`, `winner_factors`, `top_n_charts`): add a `--data-source {alpaca,historical}` flag. It picks the data class, its `--cache-dir` default, and a `SharesCache` fetcher that never calls yfinance (otherwise the 20-day expiry would trigger yfinance calls for 2005 names).
- Unit tests in `tests/unit/test_historical_data.py` (mocked parquet reads). Cover: output format, the `symbol~YYYY` split, the raw vs adjusted close, the overlap rescale, and the source-priority order.

### Phase 7: check the data, then run (1–2 days)
1. **Overlap check, 2016-10 → 2018-03:** WIKI vs Alpaca daily returns for every shared symbol. Flag symbols whose returns disagree by more than 0.5% on more than 1% of days.
2. **2018 rerun:** rerun `uptrend_formation --year 2018 --data-source historical` and compare with the existing 2018 panel. Expect more names (delisted ones added), but ranking and returns should be close for names in both.
3. **Spot checks:** LEH 2008, WM 2008 and SHLD 2018 should end near zero, not vanish from the data.
4. Then run 2006–2017. Each year needs 14 months of lookback, so the bars start in late 2004. Then the downstream books.

## What each year range can test

| Years | Large rule (prices only) | Mid / Small rules (need fundamentals) |
|---|---|---|
| 2005–2008 | yes, with a proxy for tiers; companies that died before 2014 missing | no (no XBRL filings) |
| 2009–2010 | yes; deaths before 2014 missing | partial (296 → 777 filers) |
| 2011–2013 | yes; deaths before 2014 missing | yes, same caveat |
| 2014–2019 | yes (delisted names covered) | yes |

## Decisions (2026-11-14)

1. **Delisted small caps: free tier only.** No Tiingo subscription for now. Delisted names come from WIKI, plus Alpaca where the Phase 0 check passes. Delisted names missing from both stay out, and the findings say so: survivorship bias remains, mostly in Small. Tiingo's free tier (500 symbols a month) can still fill the most important gaps, picked by dollar volume.
2. **Tier proxy before 2009:** back-fill each company's first SEC share count to its earlier years, and list that as a caveat in the findings.
3. **Branch:** `historical-data-2005-2019`, cut from `open_market_momentum_stategy` (d75dbe6), in its own worktree at `../alpha_tech_tracker_hist`. The newer research commits on `wave-a3-shadow` (short hedge hold-off, top-N books) are not on it yet; merge them in before Phase 7 runs those books.

## Disk

WIKI zip about 0.5 GB (unzipped about 2 GB), the normalized parquet about 1 GB, the seeded cache about 2 GB (the size of the current one). All of it goes under `market_data/historical/` and `market_data/historical_cache/`. Both are in `.gitignore`.
