# The WIKI dataset and the 2003–2020 historical data: a guide for research

This guide covers what the Quandl WIKI dataset is, what it lacks, how this repo turned it (with yfinance, Alpaca, Tiingo, Alpha Vantage and SEC data) into one daily table for 2003-01 → 2020-06, and how to use that table in new research. The build history and per-phase results are in `historical_data_2005_2019_plan.md`; this file is the reference to read before using the data.

## 1. What WIKI is

**Quandl WIKI/PRICES** is a free, community-maintained end-of-day price table, now hosted by Nasdaq Data Link. It stopped updating on **2018-03-27** and is frozen.

| Property | Value |
|---|---|
| File | `market_data/historical/raw/wiki/WIKI_PRICES.zip` (463 MB; one 1.8 GB CSV inside), export of 2026-02-03 |
| Rows / tickers | 15.4M rows, 3,199 tickers |
| Dates | 1962-01-02 → 2018-03-27 |
| Granularity | **Daily only.** No intraday bars, no quotes, no fundamentals. |
| Universe | US common stocks, mostly larger and better-known names (~2,150 trading in 2005, ~2,900 in 2013) |
| Download | `python -m alpha_tech_tracker.research.historical.download wiki` (needs `NASDAQ_DATA_LINK_API_KEY` in `.env`, free key) |

**Columns:**

| Column | Meaning |
|---|---|
| `ticker` | Symbol, keyed by the ticker's **last owner in WIKI** (see quirks) |
| `date` | Trading day |
| `open, high, low, close, volume` | As traded, not adjusted |
| `ex-dividend` | Cash dividend going ex that day (0 otherwise) |
| `split_ratio` | Split taking effect that day (1 otherwise) |
| `adj_open, adj_high, adj_low, adj_close, adj_volume` | Adjusted for splits **and** dividends, on WIKI's 2018 basis |

Read it in chunks; the full CSV does not fit comfortably in memory with pandas:

```python
import zipfile, pandas as pd
with zipfile.ZipFile("market_data/historical/raw/wiki/WIKI_PRICES.zip") as z:
    with z.open(z.namelist()[0]) as f:
        for chunk in pd.read_csv(f, chunksize=3_000_000, parse_dates=["date"],
                                 keep_default_na=False, na_values=[""]):  # tickers NA / NAN / NULL are real
            ...
```

Most research should **not** read the raw file. Use the built table in section 4, which has the fixes below applied.

## 2. What WIKI gets wrong or lacks

### Survivorship: no company that died before 2014
- **No WIKI ticker ends before 2014.** Its 728 dead tickers ended in 2014 (102), 2015 (194), 2016 (216), 2017 (193) and 2018 (23).
- Missing: Lehman, Bear Stearns, Washington Mutual, Merrill Lynch, Wachovia, Countrywide, old GM (WIKI's `GM` starts at the 2010 IPO).
- **No free source fills this.** Tiingo's ticker list also lacks LEH, BSC, CFC and WaMu; Alpha Vantage's delisted list is nearly empty before 2013 and its `date=` parameter rejects dates before 2010.
- **Effect:** any backtest before 2014 is biased toward survivors. Treat its results as an **upper bound**. The bias is largest in Small caps and in crash years (2008).

### Coverage: about half the listed stocks
Operating stocks on NYSE/NASDAQ/AMEX on Jan 2 (listings from Tiingo + Alpha Vantage):

| Year | Listed | In WIKI | Missing, still listed today (filled from yfinance) | Missing and gone (no free source) |
|---|---|---|---|---|
| 2005 | 3,050 | 1,805 | 718 | 527 |
| 2008 | 3,824 | 2,091 | 896 | 837 |
| 2010 | 4,008 | 2,174 | 961 | 873 |
| 2013 | 4,512 | 2,440 | 1,105 | 967 |
| 2015 | 4,954 | 2,554 | 1,327 | 1,073 |

### Ticker and data quirks (all handled in the built table)
- **History is keyed by the ticker's last owner.** WIKI's `WM` is Waste Management back to 1962, not Washington Mutual; `GOLD` is Randgold, not Barrick. One ticker can hold two companies' histories with a gap between them.
- **Stale or stray rows.** Some live companies stop updating before 2018 (AN after 2017-08, ATI after 2017-04), then get a few stray days in 2018-03. DELL ends 2013-10-29 at ~$13.85, then has 42 zero-volume rows in 2015 at a flat $31.30; a backtest would book that as a +126% jump.
- **Renames show up as two tickers.** Some renamed companies appear under both tickers for overlapping periods (WIKI's ON Semiconductor prices also filed under TRUE before TrueCar listed; SWHC/SWBI, PCLN/BKNG, UTX/RTX, TMK/GL across the sources).
- **Bars on market holidays.** TAM has 48 rows dated on holidays in 2003–2013 (2006-01-02, 2008-12-25 ...). Each adds a day on which no other stock has a price, which shifts checkpoints and breaks rolling features.
- **Text tickers.** `NA`, `NAN` and `NULL` are real symbols; pandas reads them as missing unless told not to.
- **Adjusted basis.** `adj_*` is on WIKI's 2018 basis, not today's. Do not mix it with Alpaca's adjusted prices without rescaling.

## 3. How the repo builds one daily table from it

Code is in `alpha_tech_tracker/research/historical/`. Run each step from the repo root with `PYTHONPATH=.` and the venv active.

| Step | Command | What it does |
|---|---|---|
| 1. Download | `python -m alpha_tech_tracker.research.historical.download all` | WIKI zip, Tiingo ticker list, Alpha Vantage listing snapshots (2013–2020), SEC CIK lookups, Alpaca asset list, into `market_data/historical/raw/<source>/`. Skips files already there. |
| 2. Securities | `python -m alpha_tech_tracker.research.historical.securities` | Splits each ticker into companies (a gap over 365 days, or over 30 days with a 2× price break, starts a new company, labelled `symbol~YYYY`); attaches names and SEC CIKs. |
| 3. Fill prices | `python -m alpha_tech_tracker.research.historical.fill_prices yfinance alpaca` | yfinance for still-listed names WIKI lacks (before 2016); Alpaca for 2016 → 2020-06, fetched one month per request. |
| 4. Normalize | `python -m alpha_tech_tracker.research.historical.normalize` | Joins the sources into `daily/<year>.pkl` (rules below). |
| 5. Shares | `python -m alpha_tech_tracker.research.historical.shares` | Dated share counts into `shares.json` (SEC filings, plus yfinance history for live names). |
| 6. Check | `python -m alpha_tech_tracker.research.historical.validate overlap` / `panels <old_dir> <new_dir>` | WIKI vs Alpaca returns on shared days; panel comparison with an Alpaca run. |

**After any rebuild of `daily/`, delete `market_data/historical_cache/daily_bars/`.** The bar cache treats finished months as final and will otherwise serve stale bars.

**Normalize rules:**
- **Source by date:** WIKI through 2015-12-31 (yfinance only for days WIKI lacks), Alpaca from 2016-01-01. WIKI after 2015 is used only for the overlap check.
- **One basis:** older sources are rescaled onto Alpaca's (today's) adjusted basis by the ratio of adjusted closes on shared days in Jan–Mar 2016. When returns disagree there, the tickers are different companies and the older part becomes `symbol~YYYY`.
- **Junk rows dropped:** every row with zero volume (Alpaca pads dead tickers with flat bars; WIKI's DELL rows), and every day on which fewer than 100 stocks traded (TAM's holiday bars).
- **Same history under two tickers dropped:** Alpaca series repeating another's (day, volume) pairs; yfinance series repeating a WIKI series; and any two tickers whose daily returns agree within 5 bp (or 1.5 cents on cheap stocks) on 80%+ of moving days in a year. The series that ends first, or listed later, loses its shared days in that year. Share classes (GOOG/GOOGL) agree on a third of days at most and are kept. SPY and QQQ are never dropped. The pairs are kept in `aliases.csv`.

**Checks passed (2026-11-14/15):**
- 2,834 symbols in both WIKI and Alpaca for 2016-01 → 2018-03; median 0.18% of days off by more than 0.5%. The 197 that disagree more are mostly tickers that changed owners.
- Dead tickers end at their real last trade: SHLD 2018-10-23 at $0.34, CELG 2019-11-20, MON 2018-06-06, TWX 2018-06-14, DELL~2013 2013-10-29.
- 2018 rerun vs the Alpaca run: tiers agree for 99.1% of shared names; adding 443 dead or renamed names barely moves the screens' forward-test lifts.

## 4. The built data: what future research should read

Everything is under `market_data/historical/` (git-ignored; in the `historical-data-2005-2019` worktree it is a symlink to the main checkout).

| File | Contents |
|---|---|
| `daily/<year>.pkl` (2003–2020) | Long rows: `symbol, day, open, high, low, close, volume, raw_close, source`. `open/high/low/close/volume` are split + dividend adjusted on today's basis (matches Alpaca `Adjustment.ALL`). `raw_close` is the unadjusted close, for market cap. `source` is `wiki`, `yfinance` or `alpaca`. 15.9M rows, about 7,200 companies. |
| `securities.csv` | `security, first_day, last_day, symbol, name, still_trading, cik`. One row per company; `security` is `symbol` or `symbol~YYYY` for an earlier owner of a reused ticker. |
| `aliases.csv` | `symbol, other`: tickers that are the same company (renames, duplicate filings). |
| `shares.json` | Dated share counts in the format `SharesCache` reads; each count is dated by its filing day, so it is never seen early. |
| `raw/` | The untouched downloads. |

A year's file holds that calendar year. Daily bars only: **no intraday data** for any year before Alpaca's minute bars (about 2016).

### Using it

**a) Through the existing research scripts (preferred).** `HistoricalData` (`research/historical/data.py`) has the same methods as `AlpacaData` (`listed_stocks()`, `daily_bars(symbols, start, end)`, `raw_closes(symbols, day)`), so research code runs unchanged:

```bash
# yearly universe, tiers and screens
PYTHONPATH=. python -m alpha_tech_tracker.research.uptrend_formation --year 2012 --data-source historical \
    --out-dir alpha_tech_tracker/research/top_performers_output/uptrend_formation_historical

# any script built on selection_filters.prepare_inputs (top_n_books.py, large_top3_book.py, hedge_overlay.py ...)
PYTHONPATH=. python -m alpha_tech_tracker.research.historical.run_top_n <script.py> <script args>
```

`run_top_n` swaps in `HistoricalData`, the historical bar cache and panels, CIKs from `securities.csv` (correct for dead and reused tickers; no call to sec.gov), SPY/QQQ as the only benchmarks (IWM is not in the data) and a "today" of 2020-06-30. Keep the historical cache (`market_data/historical_cache/`) separate from the Alpaca cache: the two are on different adjustment bases.

**b) Directly, for a quick study:**

```python
from datetime import date

import pandas as pd
from alpha_tech_tracker.research.historical.data import HistoricalData

bars = pd.concat(pd.read_pickle(f"market_data/historical/daily/{y}.pkl") for y in (2007, 2008, 2009))
close = bars.pivot(index="day", columns="symbol", values="close")          # adjusted closes, wide
cap = bars.set_index(["day", "symbol"])["raw_close"]                       # x shares for market cap

# Alpaca's format: symbol, timestamp (UTC), close, volume. DELL~2013 is the Dell that went private in 2013.
HistoricalData().daily_bars(["AAPL", "DELL~2013"], date(2008, 1, 1), date(2008, 12, 31))
```

Read `securities.csv` with `keep_default_na=False, na_values=["", "null"]` (the `NA` ticker).

**c) Adding a new script.** Give it a `--data-source {alpaca,historical}` switch like `uptrend_formation`, or build inputs through `selection_filters.prepare_inputs` and run it via `run_top_n`. Never let a historical run fall back to yfinance or live SEC calls; those return today's tickers and today's companies.

## 5. What each year range can test

| Years | Price-only rules (e.g. Large) | Rules needing fundamentals (Mid reclaim, Small factors) | Trust |
|---|---|---|---|
| 2005–2008 | Yes; tiers use each company's first SEC share count back-filled | **No.** SEC XBRL filings start in 2009; Mid makes no trades, Small's fundamentals checks switch off | Upper bound: deaths before 2014 missing |
| 2009–2010 | Yes | 2009: no (no year-ago growth yet, Mid makes no trades). 2010: yes, 296 → 777 XBRL filers | Upper bound |
| 2011–2013 | Yes | Yes | Upper bound |
| 2014–2019 | Yes | Yes | Good: delisted names covered (WIKI to 2015, Alpaca from 2016) |
| 2020-01 → 2020-06 | Partial year only; use the Alpaca data for 2020+ | | |

Also not in the data: IWM (use SPY/QQQ), intraday bars, options, and anything after 2020-06-30.

Top-N book results already run on this data (2005–2019) are in `historical_data_2005_2019_plan.md` and `top_performers_output/uptrend_formation_historical/top_n_by_year/yearly_summary_*.csv`.

## 6. Checklist before trusting a result

1. **Which years?** Before 2014, say in the finding that it is survivor-biased and an upper bound.
2. **Does the rule need fundamentals?** Before 2011, check how many names actually had the data (a rule that silently switches off is a different rule).
3. **Market cap before 2009** uses back-filled share counts, so tier boundaries are approximate.
4. **Was the rule tuned on this period?** The current rules were chosen on 2020–2026; earlier years are out-of-sample.
5. **Duplicates:** if a book holds two names with identical returns, check `aliases.csv` and rebuild with the current `normalize.py`.
6. **Stale cache:** if prices look off after a rebuild, delete `market_data/historical_cache/daily_bars/`.
7. **Small samples:** Mid books in particular swing by tens of points with which few names qualify (Mid top 3 in 2019 ranged from +32% to +71% across data versions). Look at several years and book sizes, not one number.
