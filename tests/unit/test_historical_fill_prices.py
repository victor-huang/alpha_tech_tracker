import json

import pandas as pd
import pytest

from alpha_tech_tracker.research.historical import fill_prices as fp

T = pd.Timestamp


def _listing(symbol, start, end=None, source="tiingo", status=None, name="Some Co", exchange="NYSE"):
    return {"symbol": symbol, "name": name, "exchange": exchange, "asset_type": "Stock", "start": T(start),
            "end": T(end) if end else pd.NaT, "status": status, "source": source}


def _alpaca(symbol, status="active", name="Some Co", exchange="NYSE"):
    return {"symbol": symbol, "name": name, "exchange": exchange, "asset_type": "Stock", "start": pd.NaT,
            "end": pd.NaT, "status": status, "source": "alpaca"}


def _runs(rows):
    return pd.DataFrame([{"symbol": s, "security": sec_id, "first_day": T(a), "last_day": T(b)}
                         for s, sec_id, a, b in rows])


NO_RUNS = pd.DataFrame({"symbol": pd.Series(dtype=str), "security": pd.Series(dtype=str),
                        "first_day": pd.Series(dtype="datetime64[ns]"), "last_day": pd.Series(dtype="datetime64[ns]")})


class TestYfinanceSymbols:
    def test_includes_listed_name_missing_from_wiki_that_still_trades(self):
        listings = pd.DataFrame([_listing("LIVE", "2000-01-01"), _alpaca("LIVE")])

        assert "LIVE" in fp.yfinance_symbols(listings, NO_RUNS)

    def test_skips_name_that_no_longer_trades(self):
        listings = pd.DataFrame([_listing("GONE", "2000-01-01", "2012-01-01"), _alpaca("GONE", status="inactive")])

        assert "GONE" not in fp.yfinance_symbols(listings, NO_RUNS)

    def test_skips_name_wiki_already_covers(self):
        listings = pd.DataFrame([_listing("AAPL", "1980-12-12"), _alpaca("AAPL")])
        runs = _runs([("AAPL", "AAPL", "2003-01-02", "2015-12-31")])

        assert "AAPL" not in fp.yfinance_symbols(listings, runs)

    def test_includes_stale_wiki_ticker_that_still_trades(self):
        listings = pd.DataFrame([_alpaca("AN")])
        runs = _runs([("AN", "AN", "2003-01-02", "2014-06-30")])

        assert "AN" in fp.yfinance_symbols(listings, runs)

    def test_always_includes_benchmarks(self):
        assert {"SPY", "QQQ"} <= set(fp.yfinance_symbols(pd.DataFrame([_alpaca("X")]), NO_RUNS))


class TestAlpacaSymbols:
    def test_includes_inactive_asset_on_listed_exchange(self):
        assert "CELG" in fp.alpaca_symbols(pd.DataFrame([_alpaca("CELG", status="inactive")]), NO_RUNS)

    def test_skips_otc_asset(self):
        assert "XYZ" not in fp.alpaca_symbols(pd.DataFrame([_alpaca("XYZ", exchange="OTC")]), NO_RUNS)

    def test_includes_symbol_listed_in_2016_2019_that_alpaca_does_not_list(self):
        listings = pd.DataFrame([_listing("TWX", "1992-03-19", "2018-06-14"), _alpaca("X")])

        assert "TWX" in fp.alpaca_symbols(listings, NO_RUNS)

    def test_includes_wiki_ticker_alive_in_2015(self):
        runs = _runs([("MON", "MON", "2003-01-02", "2015-12-31")])

        assert "MON" in fp.alpaca_symbols(pd.DataFrame([_alpaca("X")]), runs)


    def test_skips_share_class_symbol_from_wiki(self):
        runs = _runs([("BF_B", "BF_B", "2003-01-02", "2015-12-31")])

        assert "BF_B" not in fp.alpaca_symbols(pd.DataFrame([_alpaca("X")]), runs)


class TestMonthWindows:
    def test_one_window_per_month(self):
        from datetime import datetime

        windows = fp.month_windows(datetime(2016, 11, 1), datetime(2017, 1, 15))

        assert [(a.date().isoformat(), b.date().isoformat()) for a, b in windows] == [
            ("2016-11-01", "2016-11-30"), ("2016-12-01", "2016-12-31"), ("2017-01-01", "2017-01-15")]


class TestBatches:
    def test_splits_into_fixed_size_batches(self):
        assert fp.batches(["A", "B", "C"], 2) == [["A", "B"], ["C"]]


class TestYfinanceLong:
    def _wide(self):
        index = pd.to_datetime(["2010-01-04", "2010-01-05"])
        cols = ["Open", "High", "Low", "Close", "Adj Close", "Volume", "Dividends", "Stock Splits"]
        part = pd.DataFrame([[1, 2, 0.5, 1.5, 1.4, 100, 0, 0], [None] * 8], index=index, columns=cols)
        return pd.concat({"ABC": part}, axis=1)

    def test_turns_wide_frame_into_long_rows(self):
        out = fp.yfinance_long(self._wide(), ["ABC"])

        assert out[["symbol", "close", "adj_close", "volume"]].values.tolist() == [["ABC", 1.5, 1.4, 100]]

    def test_drops_rows_without_close(self):
        assert len(fp.yfinance_long(self._wide(), ["ABC"])) == 1

    def test_skips_symbol_missing_from_frame(self):
        assert fp.yfinance_long(self._wide(), ["ZZZ"]).empty


class TestRunBatches:
    def _fetch(self, batch):
        return pd.DataFrame({"symbol": batch, "day": T("2016-01-04")})

    def test_writes_one_file_per_batch(self, tmp_path):
        fp.run_batches(["A", "B", "C"], 2, str(tmp_path), self._fetch, sleep=lambda s: None)

        assert sorted(p.name for p in tmp_path.glob("batch_*.pkl")) == ["batch_0000.pkl", "batch_0001.pkl"]

    def test_skips_batches_already_on_disk(self, tmp_path, mocker):
        fp.run_batches(["A", "B", "C"], 2, str(tmp_path), self._fetch, sleep=lambda s: None)
        fetch = mocker.MagicMock()

        result = fp.run_batches(["A", "B", "C"], 2, str(tmp_path), fetch, sleep=lambda s: None)

        fetch.assert_not_called()
        assert result["already_done"] == 2

    def test_rerun_keeps_saved_batch_plan(self, tmp_path):
        fp.run_batches(["A", "B", "C"], 2, str(tmp_path), self._fetch, limit=0, sleep=lambda s: None)

        fp.run_batches(["A", "B", "C", "D"], 1, str(tmp_path), self._fetch, sleep=lambda s: None)

        assert json.loads((tmp_path / "batches.json").read_text()) == [["A", "B"], ["C"]]

    def test_stops_after_limit(self, tmp_path):
        result = fp.run_batches(["A", "B", "C"], 1, str(tmp_path), self._fetch, limit=1, sleep=lambda s: None)

        assert result["fetched"] == 1

    def test_retries_failed_batch(self, tmp_path, mocker):
        fetch = mocker.MagicMock(side_effect=[RuntimeError("throttled"), self._fetch(["A"])])

        fp.run_batches(["A"], 1, str(tmp_path), fetch, sleep=lambda s: None)

        assert fetch.call_count == 2

    def test_raises_after_last_retry(self, tmp_path, mocker):
        fetch = mocker.MagicMock(side_effect=RuntimeError("throttled"))

        with pytest.raises(RuntimeError):
            fp.run_batches(["A"], 1, str(tmp_path), fetch, sleep=lambda s: None)
