import json
from datetime import date

import pandas as pd

from alpha_tech_tracker.research.historical import data as hd
from alpha_tech_tracker.research.historical import shares as hs
from alpha_tech_tracker.research.top_performers import pivot_bars

T = pd.Timestamp


def _daily(tmp_path, rows):
    folder = tmp_path / "daily"
    folder.mkdir(exist_ok=True)
    frame = pd.DataFrame(rows, columns=["symbol", "day", "close", "raw_close"])
    frame["day"] = pd.to_datetime(frame["day"])
    for col in ["open", "high", "low"]:
        frame[col] = frame["close"]
    frame["volume"] = 100.0
    frame["source"] = "alpaca"
    for year, part in frame.groupby(frame["day"].dt.year):
        part.to_pickle(folder / f"{year}.pkl")
    return hd.HistoricalData(str(tmp_path))


class TestDailyBars:
    def test_returns_alpaca_shape(self, tmp_path):
        data = _daily(tmp_path, [("CELG", "2018-01-02", 100.0, 100.0)])

        bars = data.daily_bars(["CELG"], date(2018, 1, 1), date(2018, 1, 31))

        assert bars.columns.tolist() == ["symbol", "timestamp", "close", "volume"]

    def test_timestamps_land_on_the_trading_day_after_pivot(self, tmp_path):
        data = _daily(tmp_path, [("CELG", "2018-01-02", 100.0, 100.0)])

        close, _ = pivot_bars(data.daily_bars(["CELG"], date(2018, 1, 1), date(2018, 1, 31)))

        assert close.index.tolist() == [T("2018-01-02")]

    def test_spans_year_files(self, tmp_path):
        data = _daily(tmp_path, [("X", "2017-12-29", 1.0, 1.0), ("X", "2018-01-02", 2.0, 2.0)])

        assert len(data.daily_bars(["X"], date(2017, 12, 1), date(2018, 1, 31))) == 2

    def test_only_requested_symbols(self, tmp_path):
        data = _daily(tmp_path, [("X", "2018-01-02", 1.0, 1.0), ("Y", "2018-01-02", 2.0, 2.0)])

        assert data.daily_bars(["Y"], date(2018, 1, 1), date(2018, 1, 31))["symbol"].tolist() == ["Y"]

    def test_missing_year_file_gives_no_rows(self, tmp_path):
        data = _daily(tmp_path, [("X", "2018-01-02", 1.0, 1.0)])

        assert data.daily_bars(["X"], date(2010, 1, 1), date(2010, 12, 31)).empty


class TestRawCloses:
    def test_last_raw_close_on_or_before_day(self, tmp_path):
        data = _daily(tmp_path, [("X", "2017-12-28", 1.0, 10.0), ("X", "2017-12-29", 1.0, 11.0),
                                 ("X", "2018-01-02", 1.0, 12.0)])

        assert data.raw_closes(["X"], date(2017, 12, 31)) == {"X": 11.0}

    def test_skips_symbol_without_recent_bar(self, tmp_path):
        data = _daily(tmp_path, [("X", "2017-11-01", 1.0, 10.0)])

        assert data.raw_closes(["X"], date(2017, 12, 31)) == {}


class TestListedStocks:
    def test_indexes_by_security_and_drops_funds(self, tmp_path):
        pd.DataFrame([{"security": "CELG", "symbol": "CELG", "name": "Celgene Corp"},
                      {"security": "SPY", "symbol": "SPY", "name": "SPDR S&P 500 ETF Trust"},
                      {"security": "WM~2008", "symbol": "WM", "name": "Washington Mutual"}]
                     ).to_csv(tmp_path / "securities.csv", index=False)
        pd.DataFrame([{"symbol": "CELG", "exchange": "NASDAQ"}]).to_pickle(tmp_path / "listings.pkl")

        stocks = hd.HistoricalData(str(tmp_path)).listed_stocks()

        assert stocks.index.tolist() == ["CELG", "WM~2008"]


class TestHistoricalShares:
    def _shares(self, tmp_path, sec_counts, yf_counts=None, last_days=None):
        (tmp_path / "shares.json").write_text(json.dumps(sec_counts))
        pd.DataFrame([{"security": s, "last_day": d} for s, d in (last_days or {}).items()],
                     columns=["security", "last_day"]).to_csv(tmp_path / "securities.csv", index=False)
        yf_path = tmp_path / "yf_shares.json"
        yf_path.write_text(json.dumps({s: {"fetched": "2026-11-01", "shares": c} for s, c in (yf_counts or {}).items()}))
        return hd.HistoricalShares(str(tmp_path), str(yf_path))

    def test_returns_sorted_series(self, tmp_path):
        shares = self._shares(tmp_path, {"X": {"2012-06-30": 200, "2011-12-31": 100}})

        assert shares.get("X", date(2026, 1, 1)).tolist() == [100.0, 200.0]

    def test_unknown_symbol_is_none(self, tmp_path):
        assert self._shares(tmp_path, {}).get("X") is None

    def test_falls_back_to_yfinance_for_company_still_trading(self, tmp_path):
        shares = self._shares(tmp_path, {}, {"BABA": {"2016-03-31": 2500}}, {"BABA": "2020-06-29"})

        assert shares.get("BABA").tolist() == [2500.0]

    def test_no_fallback_for_dead_company(self, tmp_path):
        shares = self._shares(tmp_path, {}, {"TWX": {"2016-03-31": 800}}, {"TWX": "2018-06-14"})

        assert shares.get("TWX") is None

    def test_yfinance_wins_from_its_first_date_and_sec_fills_before(self, tmp_path):
        shares = self._shares(tmp_path, {"X": {"2010-03-31": 100, "2016-03-31": 8000}}, {"X": {"2015-06-30": 999}},
                              {"X": "2020-06-29"})

        assert shares.get("X").tolist() == [100.0, 999.0]

    def test_uses_yfinance_entry_of_an_alias(self, tmp_path):
        shares = self._shares(tmp_path, {}, {"META": {"2016-03-31": 2900}}, {"FB": "2020-06-29"})
        pd.DataFrame([{"symbol": "META", "other": "FB"}]).to_csv(tmp_path / "aliases.csv", index=False)

        assert hd.HistoricalShares(str(tmp_path), str(tmp_path / "yf_shares.json")).get("FB").tolist() == [2900.0]


class TestSecurityTable:
    def _listing(self, symbol, name, source, start=None, end=None):
        return {"symbol": symbol, "name": name, "source": source,
                "start": T(start) if start else pd.NaT, "end": T(end) if end else pd.NaT}

    def test_names_dead_company_from_overlapping_listing_not_ticker_reuser(self):
        rows = pd.DataFrame({"symbol": ["FB", "FB"], "day": [T("2012-05-18"), T("2019-12-31")]})
        listings = pd.DataFrame([self._listing("FB", "Facebook Inc", "alphavantage", "2012-05-18", "2022-06-08"),
                                 dict(self._listing("FB", "ProShares S&P 500 Dynamic Buffer ETF", "alpaca"),
                                      status="active")])

        table = hs.security_table(rows, listings, pd.DataFrame(columns=["security", "name"]))

        assert table["name"].tolist() == ["Facebook Inc"]

    def test_renamed_ticker_named_from_its_alias(self):
        rows = pd.DataFrame({"symbol": ["FB"], "day": [T("2019-12-31")]})
        listings = pd.DataFrame([dict(self._listing("META", "Meta Platforms Inc", "alpaca"), status="active"),
                                 dict(self._listing("FB", "ProShares S&P 500 Dynamic Buffer ETF", "alpaca"),
                                      status="active")])

        table = hs.security_table(rows, listings, pd.DataFrame(columns=["security", "name"]), {"FB": ["META"]})

        assert table["name"].tolist() == ["Meta Platforms Inc"]

    def test_former_owner_named_from_wiki_run(self):
        rows = pd.DataFrame({"symbol": ["WM~2008"], "day": [T("2005-01-03")]})
        runs = pd.DataFrame([{"security": "WM~2008", "name": "Washington Mutual"}])

        listings = pd.DataFrame([dict(self._listing("WM", "Waste Management", "alpaca"), status="active")])

        table = hs.security_table(rows, listings, runs)

        assert table["name"].tolist() == ["Washington Mutual"]

    def test_alpaca_name_only_while_still_trading(self):
        rows = pd.DataFrame({"symbol": ["HAWK", "AAPL"], "day": [T("2018-06-14"), T("2020-06-29")]})
        listings = pd.DataFrame([dict(self._listing("HAWK", "HawkEye 360", "alpaca"), status="active"),
                                 dict(self._listing("AAPL", "Apple Inc", "alpaca"), status="active")])

        table = hs.security_table(rows, listings, pd.DataFrame(columns=["security", "name"]))

        assert table.set_index("security")["name"].to_dict() == {"AAPL": "Apple Inc", "HAWK": None}


class TestResolveCiks:
    def _table(self, security, symbol, name, still_trading=True):
        return pd.DataFrame([{"security": security, "symbol": symbol, "name": name, "still_trading": still_trading}])

    def test_current_ticker_for_active_owner(self):
        assert hs.resolve_ciks(self._table("AAPL", "AAPL", "Apple Inc"), {"AAPL"}, {"AAPL": 320193}, {}).tolist() == \
            [320193]

    def test_alias_cik_for_renamed_ticker(self):
        out = hs.resolve_ciks(self._table("FB", "FB", "Facebook"), {"META"}, {"META": 1326801}, {},
                              hs.alias_map(pd.DataFrame([{"symbol": "META", "other": "FB"}])))

        assert out.tolist() == [1326801]

    def test_name_for_dead_company_whose_ticker_was_reused(self):
        out = hs.resolve_ciks(self._table("HAWK", "HAWK", "Blackhawk Network", still_trading=False), {"HAWK"},
                              {"HAWK": 1750704}, {"BLACKHAWK NETWORK": 1411488})

        assert out.tolist() == [1411488]

    def test_name_for_inactive_ticker(self):
        out = hs.resolve_ciks(self._table("TWX", "TWX", "Time Warner Inc"), set(), {"TWX": 1},
                              {"TIME WARNER": 1105705})

        assert out.tolist() == [1105705]


class TestShareHistory:
    def _facts(self, rows):
        return {"facts": {"dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": rows}}}}}

    def test_reads_dei_share_counts_by_period_end(self):
        facts = self._facts([{"end": "2011-12-31", "val": 5_000_000, "filed": "2012-02-01", "form": "10-K"}])

        assert hs.share_history(facts).to_dict() == {T("2011-12-31"): 5_000_000.0}

    def test_drops_counts_of_one_small_share_class(self):
        facts = self._facts([{"end": "2011-12-31", "val": 8000, "filed": "2012-02-01", "form": "10-K"},
                             {"end": "2012-12-31", "val": 310_000_000, "filed": "2013-02-01", "form": "10-K"}])

        assert hs.share_history(facts).tolist() == [310_000_000.0]

    def test_no_counts_is_none(self):
        assert hs.share_history({"facts": {}}) is None

    def test_to_json_round_trips_dates(self):
        assert hs.to_json({"X": pd.Series([100.0], index=[T("2011-12-31")])}) == {"X": {"2011-12-31": 100}}
