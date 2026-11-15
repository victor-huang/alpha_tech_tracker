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

## Phases 3–7 results (2026-11-14)

**Data built** (`market_data/historical/daily/<year>.pkl`): 15.9M rows, 7,239 companies, 2003-01 → 2020-06. WIKI and yfinance supply up to 2015, Alpaca from 2016-01. Securities per year: about 2,600–4,200 before 2016 (WIKI 2,047–3,154 plus yfinance 571–1,160) and about 5,000–5,400 from 2016.

**Source quirks found and handled:**
- **Alpaca drops history across identifier changes.** A request spanning a stock's identifier change returns only the part after it: TRP for 2016–2020 starts 2019-05-09, while TRP for 2017 alone has all 251 days. Bars are now fetched one month per request, as the existing cache does: 46 batches × 54 months, 24 minutes.
- **Alpaca and Alpha Vantage file history under the current ticker**, and Alpaca sometimes under the old one too. AmerisourceBergen's 2017 bars are in both COR and ABC, and Alpha Vantage's 2016 snapshot lists Facebook as META. Alpaca series repeating another's (day, volume) pairs, at least 20 days and half the shorter series, lose the repeated days: 146,823 days from 182 series. The pairs are kept in `aliases.csv` (FB ↔ META, CTL ↔ LUMN) and used for names, CIKs and share counts.
- **Same ticker, different company across the handover.** 68 symbols disagree on daily returns between WIKI and Alpaca in Jan–Mar 2016 (GOLD was Randgold in WIKI; B, BBT, COHR, CZR …). Their pre-2016 part becomes `symbol~YYYY`.
- **yfinance files a renamed company's whole history under its new ticker** (AXON = TASR, BALL = BLL, CBRE = CBG, BHC = VRX). Days that repeat a WIKI series are dropped.
- **Names come from the ticker's current owner** in Alpaca (FB is a ProShares ETF today, S is SentinelOne, HAWK is HawkEye 360). Names now come from the dated Alpha Vantage listing, then the alias's current name, then the WIKI run. The current Alpaca name and the current-ticker CIK are used only for companies still trading at the end of the data.
- **SEC share counts are unreliable for multi-class companies.** companyfacts.zip leaves out per-class facts, leaving SPG's 8,000 class-B shares and Fox's "1". Counts under 100,000 are dropped. Companies still trading use the yfinance history already in `market_data/top_performers/shares.json` from its first date (~2015) on, as the Alpaca runs do, and SEC counts before it. Dead companies use SEC counts only. 4,509 of 7,239 companies have counts; 78% have a CIK.
- **Stale bar cache.** `DailyBarCache` treats finished months as final, so `market_data/historical_cache/daily_bars/` must be deleted after any rebuild of `daily/`.

**Overlap check, 2016-01-04 → 2018-03-27:** 2,834 symbols are in both WIKI and Alpaca, with a median of 0.18% of days off by more than 0.5%. 197 disagree on more than 1% of days, mostly tickers that changed owners or were renamed (WIKI shows the owner at the time, Alpaca the current company). Dead tickers end at their real last trade: SHLD 2018-10-23 at $0.34, CELG 2019-11-20, MON 2018-06-06, TWX 2018-06-14, DELL~2013 2013-10-29.

**2018 rerun** (`uptrend_formation --year 2018 --data-source historical`, output in `top_performers_output/uptrend_formation_historical/2018`) vs the Alpaca run:

| Tier | Old universe | New | Added | Dropped |
|---|---|---|---|---|
| Large | 574 | 619 | 47 | 6 |
| Mid | 711 | 849 | 169 | 18 |
| Small | 564 | 780 | 227 | 20 |

- **Tiers agree for 1,788 of 1,805 shared names (99.1%).**
- **Added (443):** 139 stopped trading by 2020-06 (AABA, ANDV, AVP, BKS …), about 277 were acquired or delisted after 2020 so today's list lacks them (ABMD, ANSS, ALXN, ALTR …), and 25 are the 2018 tickers of later-renamed companies.
- **Dropped (44):** 28 are today's tickers of renamed companies, now carried under their 2018 tickers (ELV → ANTM, LUMN → CTL, COR → ABC, WOLF → CREE …). The other 16 are small names, plus SMCI, whose 2016–2019 history Alpaca no longer has (it moved to OTC in 2018).
- **Forward test (lift, old → new):**
  - trend_template: All 1.35 → 1.35, Large 1.40 → 1.39, Mid 1.46 → 1.50, Small 1.21 → 1.19.
  - top_decile_ret_120d: All 1.81 → 1.80.
  - early_momentum: Large 1.10 → 1.24.
  - top_decile_ret_250d: All 1.72 → 1.79.

  Adding dead companies to 2018 barely moves the screens' edge.

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

## Top-N yearly books on the historical data, 2014–2019 (2026-11-15)

Universes rebuilt with `uptrend_formation --data-source historical` for 2014–2019 (1,902 / 1,986 / 1,974 / 2,140 /
2,249 / 2,283 stocks on Jan 1). The top_n_by_year scripts (from `wave-a3-shadow`) ran through
`research/historical/run_top_n.py`, which swaps in `HistoricalData`, the historical cache, SEC CIKs from
`securities.csv` (not today's tickers), benchmarks SPY/QQQ only (IWM is not in the data) and `--today 2020-06-30`.
Results: `top_performers_output/uptrend_formation_historical/top_n_by_year/yearly_summary_2014_2019.csv`
(`ret_alpaca` = the survivor-only Alpaca run for 2017–2019).

Return per year (plain, no hedge):

| Book | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 |
|---|---|---|---|---|---|---|
| Large top 3 | 8.3 | 1.2 | 6.1 | 13.9 | -19.9 | 36.1 |
| Large top 5 | 7.2 | -9.5 | 10.6 | 11.6 | -11.8 | 28.9 |
| Large top 10 | 19.0 | 8.1 | 7.8 | 7.0 | -7.3 | 29.6 |
| Mid top 3 | 0.5 | 5.3 | -7.6 | 17.3 | -23.6 | 43.7 |
| Mid top 5 | 1.4 | 13.4 | 1.8 | 20.5 | -7.2 | 35.7 |
| Mid top 10 | 4.2 | 10.1 | -2.0 | 23.6 | -11.0 | 34.2 |
| Small top 3 | -23.6 | -8.7 | 12.6 | 21.1 | -0.3 | 19.2 |
| Small top 5 | -21.4 | 1.0 | 14.2 | 10.0 | 10.4 | 10.8 |
| Small top 10 | -4.8 | 0.8 | 22.6 | 14.0 | -5.0 | 5.8 |
| large_top3 | 51.6 | 1.6 | 8.4 | -8.6 | -14.3 | 14.1 |
| QQQ | 20.1 | 9.8 | 9.4 | 31.5 | -1.8 | 38.4 |

- **Why 2014–2017 trails QQQ:** QQQ beats the average stock of every tier by 8–13 points in most years, before and
  after 2018 alike. What differs is the books' edge over their own tier: about 0 in 2014–2017 against +10–14 points
  a year in 2018–2026, and the 2018+ edge is concentrated in 2020 and 2024, the two strongest momentum years. The rules
  were chosen on 2020–2026, so 2014–2017 is out of sample.
- **Survivorship:** against the survivor-only Alpaca run, Large and Small move a few points either way in 2017–2019;
  Mid falls 18–33 points in 2017 and 8–18 in 2019. The Mid list (fresh names first) is very sensitive to which names
  qualify: Mid top 3 in 2019 was +70.5%, +31.6% and +43.7% across the three data fixes below.
- **The short hedge** was on at 0 / 2 / 5 / 0 / 4 / 1 checkpoints; in 2016 it cost about 10 points (the February
  rebound).

Fixes made along the way:

- **One company under two tickers** (SWHC and SWBI, PCLN and BKNG, UTX and RTX, and WIKI's ON history under TRUE
  before TrueCar listed): `normalize.return_duplicate_years` finds pairs whose daily returns agree on 80%+ of the days
  either moved in a year (within 5 bp, or 1.5 cents of the traded price for cheap stocks); share classes agree on a
  third at most. `drop_return_duplicates` drops the duplicated years from the series that ends first, then has fewer
  days, then listed later (Tiingo), never SPY or QQQ. 157 series lose 296k days; the pairs go into `aliases.csv`.
  Before the fix the 2014–2015 books held both copies of one company 1–6 times a year.
- **Fundamentals on a tie in the filing date** (`sec_fundamentals.add_fundamental_factors`): a 10-K also files the
  year-ago quarter, and the unstable sort on `known` alone sometimes took that older quarter, which has no year-ago
  growth. Sorting by (known, quarter end) gives sales growth to about 20% more 2019 checkpoint rows (ZS, OKTA, EXAS
  among them). This also affects the Alpaca runs on `wave-a3-shadow`: Mid reclaim and any fundamentals filter there
  should be rerun after merging.

## Top-N yearly books, 2005–2013 (2026-11-15)

Same scripts and wrapper as 2014–2019, on the data after the closed-day fix below. Universes on Jan 1: 1,061 (2005),
1,191, 1,364, 1,498, 1,334, 1,377, 1,512, 1,575, 1,614 (2013). Results:
`top_n_by_year/yearly_summary_2005_2013.csv` (the row `hedge_on_checkpoints` gives the number of checkpoints the
hedge was on). How to use the data and its limits: `wiki_dataset_guide.md`.

Return per year (plain, no hedge):

| Book | 2005 | 2006 | 2007 | 2008 | 2009 | 2010 | 2011 | 2012 | 2013 |
|---|---|---|---|---|---|---|---|---|---|
| Large top 3 | 41.6 | 4.2 | -3.9 | -55.7 | -21.0 | -8.7 | -12.9 | 27.1 | 36.6 |
| Large top 5 | 51.1 | -16.4 | 12.2 | -59.1 | -33.5 | 1.4 | -11.1 | 24.5 | 26.0 |
| Large top 10 | 39.8 | -3.3 | 26.1 | -51.2 | -28.7 | 9.8 | -24.0 | 15.8 | 26.7 |
| Mid top 3 | – | – | – | – | – | 19.4 | -30.9 | -30.3 | 22.3 |
| Mid top 5 | – | – | – | – | – | 13.4 | -34.0 | -15.8 | 27.8 |
| Mid top 10 | – | – | – | – | – | 15.4 | -36.1 | -23.7 | 26.0 |
| Small top 3 | -8.5 | 5.0 | 7.2 | -53.3 | -31.7 | 0.6 | 8.8 | -3.3 | 9.3 |
| Small top 5 | -2.0 | 18.4 | 1.1 | -50.8 | -29.9 | 6.9 | 1.2 | -5.7 | 18.6 |
| Small top 10 | -1.2 | 16.1 | 10.8 | -50.1 | -29.3 | 10.5 | -4.6 | 2.0 | 27.2 |
| large_top3 | 39.5 | -20.0 | 21.8 | -55.6 | -33.7 | 27.4 | -23.3 | 15.5 | 20.4 |
| QQQ | 2.6 | 4.8 | 18.8 | -40.8 | 48.2 | 18.4 | 1.9 | 15.9 | 32.4 |
| hedge on (of 26 checkpoints) | 2 | 7 | 0 | 14 | 2 | 2 | 5 | 1 | 0 |

– = no trades: the Mid rule needs sales growth ≥ 25%, and a year-over-year figure from SEC XBRL filings (which start in
2009) exists only from 2010. Small's fundamentals checks (no dilution, prefer gross profit) switch off without data,
so Small runs on prices alone before 2010.

- **2005–2007 (pre-crisis):** Large beat QQQ by about 40 points in 2005 (housing, energy, Google) and Large top 10 by
  7 in 2007, but lost in the May–July 2006 commodity selloff. Small led in 2006. The spread between book sizes is
  large (2007: Large top 3 -3.9 vs top 10 +26.1), so one book's number says little on its own.
- **2008:** every book lost 9–18 points more than QQQ, holding materials and energy (MOS, CLF, CNX) into the second
  half. The hedge was on at 14 checkpoints and saved only 2–3 points.
- **2009, a momentum crash:** all books lost 21–34% while QQQ gained 48%. The names still trending after 2008 were
  defensive (APOL, ALK); when the market turned in March, money went to the beaten-down ones.
- **2010–2012:** mixed to bad. Large trailed QQQ in 2010 and 2011, beat it in 2012. Mid lost 16–36% in 2011 and 2012:
  it bleeds when only one or two names qualify, because the book puts equal weight on whatever qualifies. In 2011 the
  hedge cost another 8–13 points (August–December rebounds).
- **2013:** a calm uptrend; every book made 9–37% with 58–68% of trades winning, but only Large top 3 beat QQQ.
- **Survivorship:** none of the companies that died before 2014 are in the data (no LEH, BSC, WaMu), and tiers before
  2009 use each company's first SEC share count back-filled. The universe is also smaller (1,061–1,614 against
  1,900–2,300 from 2014). Read all of 2005–2013 as best cases.

Takeaway: before 2014 the rules have no reliable edge over QQQ. Large beats it in strong trending years (2005, 2007,
2012, 2013 top 3) and loses badly in the crash, the rebound and choppy years (2008, 2009, 2011). Mid, outside the
2020–2026 years it was tuned on, loses more often than not. The short hedge rarely helps: it is on in sharp dips that
reverse. A rule that pauses buying (or holds the index) after a deep drawdown is the obvious thing to test next.

**Closed-day fix (normalize.drop_closed_days):** WIKI's TAM has 48 bars dated on market holidays in 2003–2013
(e.g. 2006-01-02). Each one added a day on which no other stock had a price: checkpoints landed on it, QQQ's first
2006 price was blank, and the Mid reclaim features broke (2011 Mid made 9 trades instead of 65). Days on which fewer
than 100 stocks traded are now dropped; the rebuild removed exactly those 48 rows. 2014 reran unchanged, so 2014–2019
are unaffected. The first 2008–2010 results (commit 90d3f45) were on the bad data and are replaced by the table above.
