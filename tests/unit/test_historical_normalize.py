import pandas as pd
import pytest

from alpha_tech_tracker.research.historical import normalize as nz

T = pd.Timestamp


def _rows(symbol, days, closes, volume=100.0, source="wiki", raw=None):
    n = len(days)
    closes = closes if isinstance(closes, list) else [closes] * n
    return pd.DataFrame({"symbol": symbol, "day": pd.to_datetime(days), "open": closes, "high": closes,
                         "low": closes, "close": closes, "volume": volume,
                         "raw_close": raw if raw is not None else closes, "source": source})


def _yf_raw(symbol, days, close, adj_close, splits=None, volume=100.0):
    n = len(days)
    return pd.DataFrame({"symbol": symbol, "day": pd.to_datetime(days), "open": close, "high": close, "low": close,
                         "close": close, "adj_close": adj_close, "volume": volume, "dividends": 0.0,
                         "splits": splits if splits is not None else [0.0] * n})


class TestYfinanceRows:
    def test_scales_prices_to_dividend_adjusted(self):
        out = nz.yfinance_rows(_yf_raw("X", ["2010-01-04"], 10.0, 9.0), nz.alpaca_rows("/nowhere"))

        assert out["close"].tolist() == [9.0]

    def test_raw_close_undoes_splits_after_the_day(self):
        raw = _yf_raw("X", ["2010-01-04", "2010-01-05"], [50.0, 100.0], [50.0, 100.0], splits=[0.0, 2.0])

        out = nz.yfinance_rows(raw, nz.alpaca_rows("/nowhere"))

        assert out["raw_close"].tolist() == [100.0, 100.0]

    def test_raw_close_undoes_splits_since_2016_from_alpaca(self):
        raw = _yf_raw("X", ["2010-01-04", "2016-01-04"], [25.0, 25.0], [25.0, 25.0])
        alpaca = _rows("X", ["2016-01-04"], 25.0, source="alpaca", raw=[100.0])

        out = nz.yfinance_rows(raw, alpaca)

        assert out["raw_close"].tolist() == [100.0, 100.0]

    def test_empty_input(self):
        assert nz.yfinance_rows(pd.DataFrame(), pd.DataFrame()).empty


class TestCombinePreHandover:
    def test_wiki_wins_on_shared_days(self):
        wiki = _rows("AN", ["2014-01-02"], 40.0)
        yf = _rows("AN", ["2014-01-02"], 41.0, source="yfinance")

        assert nz.combine_pre_handover(wiki, yf)["source"].tolist() == ["wiki"]

    def test_yfinance_fills_days_after_stale_wiki_ticker(self):
        wiki = _rows("AN", ["2014-01-02"], 40.0)
        yf = _rows("AN", ["2014-01-02", "2014-06-02"], 41.0, source="yfinance")

        out = nz.combine_pre_handover(wiki, yf)

        assert out["day"].tolist() == [T("2014-01-02"), T("2014-06-02")]

    def test_yfinance_supplies_symbol_wiki_lacks(self):
        out = nz.combine_pre_handover(_rows("A", ["2014-01-02"], 1.0), _rows("B", ["2010-01-04"], 2.0, source="yfinance"))

        assert sorted(out["symbol"]) == ["A", "B"]


class TestRescaleTo:
    def test_scales_older_onto_newer_basis(self):
        older = _rows("X", ["2015-12-31", "2016-01-04"], [10.0, 10.0])
        newer = _rows("X", ["2016-01-04"], 8.0, source="alpaca")

        assert nz.rescale_to(older, newer)["close"].tolist() == [8.0, 8.0]

    def test_keeps_dollar_volume(self):
        older = _rows("X", ["2016-01-04"], 10.0, volume=100.0)
        newer = _rows("X", ["2016-01-04"], 5.0, source="alpaca")

        out = nz.rescale_to(older, newer)

        assert (out["close"] * out["volume"]).tolist() == [1000.0]

    def test_symbol_without_overlap_is_unchanged(self):
        older = _rows("DEAD", ["2010-01-04"], 10.0)

        assert nz.rescale_to(older, _rows("X", ["2016-01-04"], 5.0))["close"].tolist() == [10.0]


class TestDropDuplicateHistories:
    def test_drops_yfinance_days_repeating_a_wiki_series(self):
        days = ["2012-01-03", "2012-01-04"]
        wiki = _rows("FB", days, 20.0, volume=[111.0, 222.0])
        yf = _rows("META", days + ["2016-01-04"], 20.0, volume=[111.0, 222.0, 333.0], source="yfinance")

        out = nz.drop_duplicate_histories(yf, wiki)

        assert out["day"].tolist() == [T("2016-01-04")]

    def test_keeps_unrelated_series(self):
        wiki = _rows("A", ["2012-01-03"], 20.0, volume=111.0)
        yf = _rows("B", ["2012-01-03"], 20.0, volume=999.0, source="yfinance")

        assert len(nz.drop_duplicate_histories(yf, wiki)) == 1


class TestDropSelfDuplicates:
    def test_drops_shorter_series_repeating_a_longer_one(self):
        days = ["2017-06-01", "2017-06-02"]
        rows = pd.concat([_rows("COR", days + ["2020-01-02"], 68.0, volume=[1.0, 2.0, 3.0], source="alpaca"),
                          _rows("ABC", days, 84.0, volume=[1.0, 2.0], source="alpaca")])

        out = nz.drop_self_duplicates(rows, min_days=2)

        assert out["symbol"].unique().tolist() == ["COR"]

    def test_keeps_series_sharing_a_volume_by_chance(self):
        rows = pd.concat([_rows("A", ["2017-06-01", "2017-06-02"], 1.0, volume=[5.0, 6.0], source="alpaca"),
                          _rows("B", ["2017-06-01", "2017-06-02"], 1.0, volume=[5.0, 9.0], source="alpaca"),
                          _rows("B", ["2017-06-05", "2017-06-06"], 1.0, volume=[7.0, 8.0], source="alpaca")])

        assert len(nz.drop_self_duplicates(rows, min_days=2)) == 6


class TestHandoverMismatches:
    def _days(self, n):
        return pd.bdate_range("2016-01-04", periods=n)

    def test_flags_different_company_on_the_same_ticker(self):
        days = self._days(12)
        older = _rows("GOLD", days, [70.0 + i for i in range(12)])
        newer = _rows("GOLD", days, [5.0 + (i % 2) for i in range(12)], source="alpaca")

        assert nz.handover_mismatches(older, newer) == {"GOLD"}

    def test_same_company_on_another_basis_matches(self):
        days = self._days(12)
        older = _rows("AAPL", days, [100.0 + i for i in range(12)])
        newer = _rows("AAPL", days, [(100.0 + i) / 2 for i in range(12)], source="alpaca")

        assert nz.handover_mismatches(older, newer) == set()

    def test_too_few_shared_days_is_not_flagged(self):
        days = self._days(3)
        older = _rows("X", days, [1.0, 2.0, 3.0])
        newer = _rows("X", days, [3.0, 1.0, 2.0], source="alpaca")

        assert nz.handover_mismatches(older, newer) == set()


class TestSplitMismatched:
    def test_relabels_older_rows_by_last_year(self):
        out = nz.split_mismatched(_rows("GOLD", ["2014-06-02", "2015-12-31"], 70.0), {"GOLD"})

        assert out["symbol"].unique().tolist() == ["GOLD~2015"]

    def test_leaves_other_symbols(self):
        assert nz.split_mismatched(_rows("AAPL", ["2015-12-31"], 1.0), {"GOLD"})["symbol"].tolist() == ["AAPL"]


class TestRealTrades:
    def test_drops_zero_volume_padding(self):
        rows = _rows("MON", ["2018-06-06", "2018-06-07"], 127.95, volume=[5e6, 0.0])

        assert nz._real_trades(rows)["day"].tolist() == [T("2018-06-06")]

    def test_drops_missing_close(self):
        rows = _rows("X", ["2010-01-04"], float("nan"))

        assert nz._real_trades(rows).empty


class TestAssignSecurities:
    def test_splits_ticker_reused_across_handover(self):
        rows = pd.concat([_rows("ADT", ["2015-06-01"], 40.0), _rows("ADT", ["2018-01-19"], 14.0, source="alpaca")])

        out = nz.assign_securities(rows)

        assert out["symbol"].tolist() == ["ADT~2015", "ADT"]

    def test_continuous_series_keeps_symbol(self):
        rows = pd.concat([_rows("AAPL", ["2015-12-31"], 100.0), _rows("AAPL", ["2016-01-04"], 101.0, source="alpaca")])

        assert nz.assign_securities(rows)["symbol"].tolist() == ["AAPL", "AAPL"]


class TestWriteYears:
    def test_round_trips_by_year(self, tmp_path):
        rows = _rows("X", ["2015-12-31", "2016-01-04"], 10.0)

        nz.write_years(rows, str(tmp_path))

        assert len(nz.load_years(str(tmp_path), 2015, 2016)) == 2

    @pytest.mark.parametrize("year", [2015, 2016])
    def test_one_file_per_year(self, tmp_path, year):
        nz.write_years(_rows("X", ["2015-12-31", "2016-01-04"], 10.0), str(tmp_path))

        assert (tmp_path / f"{year}.pkl").exists()
