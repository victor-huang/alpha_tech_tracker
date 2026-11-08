from datetime import date

import pandas as pd
import pytest

from alpha_tech_tracker.research.top_performers import (
    DailyBarCache,
    PeriodWindow,
    SharesCache,
    compute_period_returns,
    default_range,
    market_cap_at,
    period_windows,
    pick_top_by_tier,
    quality_flags,
    render_markdown,
    tier_for,
)


def _frame(index, **columns):
    return pd.DataFrame(columns, index=pd.to_datetime(index))


class TestPeriodWindows:

    def test_months_in_range_are_complete_and_labelled(self):
        windows = period_windows("month", date(2026, 8, 15), date(2026, 9, 1), date(2026, 11, 7), False)

        assert [(w.label, w.start, w.end, w.is_complete) for w in windows] == [
            ("2026-08", date(2026, 8, 1), date(2026, 8, 31), True),
            ("2026-09", date(2026, 9, 1), date(2026, 9, 30), True),
        ]

    def test_quarter_label_and_bounds(self):
        windows = period_windows("quarter", date(2026, 5, 2), date(2026, 5, 2), date(2026, 11, 7), False)

        assert windows == [PeriodWindow("2026-Q2", date(2026, 4, 1), date(2026, 6, 30), True)]

    def test_in_progress_period_excluded_by_default(self):
        windows = period_windows("year", date(2025, 1, 1), date(2026, 11, 7), date(2026, 11, 7), False)

        assert [w.label for w in windows] == ["2025"]

    def test_in_progress_period_ends_today_when_included(self):
        windows = period_windows("year", date(2026, 1, 1), date(2026, 11, 7), date(2026, 11, 7), True)

        assert windows == [PeriodWindow("2026", date(2026, 1, 1), date(2026, 11, 7), False)]

    def test_quarter_rolls_into_next_year(self):
        windows = period_windows("quarter", date(2025, 10, 1), date(2025, 12, 31), date(2026, 11, 7), False)

        assert windows[0].end == date(2025, 12, 31)


class TestDefaultRange:

    @pytest.mark.parametrize("period, expected", [
        ("month", date(2026, 10, 1)),
        ("quarter", date(2026, 7, 1)),
        ("year", date(2025, 1, 1)),
    ])
    def test_is_last_completed_period(self, period, expected):
        assert default_range(period, date(2026, 11, 7)) == (expected, expected)


class TestTierFor:

    @pytest.mark.parametrize("cap, tier", [
        (50e9, "Large"),
        (10e9, "Large"),
        (5e9, "Mid"),
        (2e9, "Mid"),
        (1e9, "Small"),
        (299e6, None),
        (None, None),
    ])
    def test_boundaries(self, cap, tier):
        assert tier_for(cap) == tier


class TestComputePeriodReturns:

    def _window(self):
        return PeriodWindow("2026-02", date(2026, 2, 1), date(2026, 2, 28), True)

    def test_return_uses_last_close_before_period_as_base(self):
        close = _frame(["2026-01-30", "2026-02-02", "2026-02-27"], AAA=[10.0, 12.0, 15.0])
        dv = close * 1e6

        result = compute_period_returns(close, dv, self._window(), 2.0, 1e6, 0.9)

        assert result.loc[0, "ret"] == pytest.approx(0.5)
        assert result.loc[0, "base_date"] == date(2026, 1, 30)

    def test_sorted_best_first(self):
        close = _frame(["2026-01-30", "2026-02-27"], AAA=[10.0, 11.0], BBB=[10.0, 30.0])

        result = compute_period_returns(close, close * 1e6, self._window(), 2.0, 1e6, 0.9)

        assert result["symbol"].tolist() == ["BBB", "AAA"]

    def test_excludes_penny_stock_at_start(self):
        close = _frame(["2026-01-30", "2026-02-27"], AAA=[1.0, 5.0])

        result = compute_period_returns(close, close * 1e9, self._window(), 2.0, 1e6, 0.9)

        assert result.empty

    def test_excludes_illiquid_stock(self):
        close = _frame(["2026-01-30", "2026-02-27"], AAA=[10.0, 50.0])

        result = compute_period_returns(close, close * 10, self._window(), 2.0, 1e6, 0.9)

        assert result.empty

    def test_excludes_stock_missing_too_many_days(self):
        close = _frame(["2026-01-30", "2026-02-02", "2026-02-03", "2026-02-27"],
                       AAA=[10.0, None, None, 20.0], BBB=[10.0, 11.0, 12.0, 13.0])

        result = compute_period_returns(close, close.fillna(10) * 1e6, self._window(), 2.0, 1e6, 0.9)

        assert result["symbol"].tolist() == ["BBB"]


class TestMarketCapAt:

    def test_median_shares_near_day_times_raw_close(self):
        shares = pd.Series([100.0, 110.0, 120.0], index=pd.to_datetime(["2025-11-01", "2025-12-15", "2026-01-20"]))

        assert market_cap_at(shares, date(2025, 12, 31), 5.0) == pytest.approx(550.0)

    def test_falls_back_to_latest_before_day_when_window_empty(self):
        shares = pd.Series([100.0, 200.0], index=pd.to_datetime(["2020-01-01", "2020-06-01"]))

        assert market_cap_at(shares, date(2025, 12, 31), 2.0) == pytest.approx(300.0)

    def test_none_without_shares(self):
        assert market_cap_at(None, date(2025, 12, 31), 5.0) is None


class TestQualityFlags:

    def _window(self):
        return PeriodWindow("2026-03", date(2026, 3, 1), date(2026, 3, 31), True)

    def test_clean_series_has_no_flags(self):
        prices = pd.Series([10.0, 10.5, 11.0], index=pd.to_datetime(["2026-02-27", "2026-03-02", "2026-03-03"]))

        assert quality_flags(prices, None, self._window()) == []

    def test_long_gap_flags_ticker_reuse(self):
        prices = pd.Series([10.0, 11.0], index=pd.to_datetime(["2026-03-02", "2026-03-30"]))

        assert "trading_gap" in quality_flags(prices, None, self._window())

    def test_bankruptcy_splice_flags_price_jump(self):
        prices = pd.Series([2.0, 40.0], index=pd.to_datetime(["2026-03-02", "2026-03-03"]))

        assert "price_jump" in quality_flags(prices, None, self._window())

    def test_share_count_jump_flagged(self):
        prices = pd.Series([10.0, 10.5], index=pd.to_datetime(["2026-03-02", "2026-03-03"]))
        shares = pd.Series([1e8, 5e8], index=pd.to_datetime(["2026-01-01", "2026-03-15"]))

        assert "share_count_jump" in quality_flags(prices, shares, self._window())


class TestPickTopByTier:

    def test_fills_each_tier_in_return_order_and_skips_micro_caps(self):
        window = PeriodWindow("2026", date(2026, 1, 1), date(2026, 11, 7), False)
        ranked = pd.DataFrame({
            "symbol": ["MICRO", "BIG1", "MID1", "SMALL1", "BIG2"],
            "ret": [5.0, 3.0, 2.0, 1.5, 1.0],
            "base_date": date(2025, 12, 31),
            "median_dollar_volume": 5e6,
        })
        caps = {"MICRO": 1e8, "BIG1": 5e10, "MID1": 5e9, "SMALL1": 1e9, "BIG2": 2e10}
        shares = {s: pd.Series([cap], index=pd.to_datetime(["2025-12-31"])) for s, cap in caps.items()}
        close = pd.DataFrame({s: [1.0, 1.0] for s in caps}, index=pd.to_datetime(["2025-12-31", "2026-01-02"]))

        rows = pick_top_by_tier(ranked, window, 1, shares.get, lambda syms, day: {s: 1.0 for s in syms},
                                close, pd.Series({s: s.lower() for s in caps}))

        assert [(r["tier"], r["symbol"]) for r in rows] == [("Large", "BIG1"), ("Mid", "MID1"), ("Small", "SMALL1")]


class TestSharesCache:

    def test_uses_fresh_cache_without_fetching(self, tmp_path, mocker):
        fetcher = mocker.Mock(return_value=pd.Series([5.0], index=pd.to_datetime(["2026-01-01"])))
        cache = SharesCache(str(tmp_path / "s.json"), fetcher=fetcher)
        cache.get("AAA", date(2026, 11, 1))
        cache.save()

        reloaded = SharesCache(str(tmp_path / "s.json"), fetcher=fetcher)
        series = reloaded.get("AAA", date(2026, 11, 7))

        assert fetcher.call_count == 1
        assert series.iloc[0] == 5.0

    def test_refetches_stale_entry(self, tmp_path, mocker):
        fetcher = mocker.Mock(return_value=None)
        cache = SharesCache(str(tmp_path / "s.json"), fetcher=fetcher)
        cache.get("AAA", date(2026, 1, 1))

        cache.get("AAA", date(2026, 11, 7))

        assert fetcher.call_count == 2

    def test_retries_after_rate_limit(self, tmp_path, mocker):
        fetcher = mocker.Mock(side_effect=[Exception("Too Many Requests"), None])
        sleep = mocker.Mock()
        cache = SharesCache(str(tmp_path / "s.json"), fetcher=fetcher, sleep=sleep)

        cache.get("AAA", date(2026, 11, 7))

        assert fetcher.call_count == 2
        sleep.assert_called_once()

    def test_rate_limited_lookup_is_not_cached(self, tmp_path, mocker):
        fetcher = mocker.Mock(side_effect=Exception("YFRateLimitError"))
        cache = SharesCache(str(tmp_path / "s.json"), fetcher=fetcher, sleep=mocker.Mock(), max_retries=2)

        assert cache.get("AAA", date(2026, 11, 7)) is None
        assert "AAA" not in cache._data


class TestRenderMarkdown:

    def test_marks_in_progress_period_and_flags(self):
        rows = pd.DataFrame([{
            "period": "2026", "complete": False, "tier": "Large", "rank": 1, "symbol": "AAA",
            "return_pct": 120.0, "start_mcap_b": 12.3, "flags": "price_jump",
        }])

        md = render_markdown(rows, "year", 1)

        assert "## 2026 (in progress)" in md
        assert "AAA +120% (12.3B) [!price_jump]" in md


def _long_bars(rows):
    """rows: (symbol, 'YYYY-MM-DD', close) -> long bars as returned by the Alpaca fetcher."""
    return pd.DataFrame({
        "symbol": [r[0] for r in rows],
        "timestamp": pd.to_datetime([r[1] for r in rows]).tz_localize("America/New_York").tz_convert("UTC"),
        "close": [r[2] for r in rows],
        "volume": 1000.0,
    })


class TestDailyBarCache:

    def test_completed_month_is_read_from_disk_on_later_runs(self, tmp_path, mocker):
        fetch = mocker.Mock(return_value=_long_bars([("AAA", "2026-09-30", 10.0), ("AAA", "2026-10-30", 12.0)]))
        DailyBarCache(str(tmp_path), fetch).load(["AAA"], date(2026, 10, 1), date(2026, 10, 31), date(2026, 11, 7))

        close, _ = DailyBarCache(str(tmp_path), fetch).load(["AAA"], date(2026, 10, 1), date(2026, 10, 31),
                                                            date(2026, 11, 20))

        assert fetch.call_count == 1
        assert close["AAA"].tolist() == [10.0, 12.0]

    def test_in_progress_month_is_refetched_next_day(self, tmp_path, mocker):
        fetch = mocker.Mock(return_value=_long_bars([("AAA", "2026-11-02", 10.0)]))
        cache = DailyBarCache(str(tmp_path), fetch)
        cache.load(["AAA"], date(2026, 11, 1), date(2026, 11, 7), date(2026, 11, 7))

        cache.load(["AAA"], date(2026, 11, 1), date(2026, 11, 8), date(2026, 11, 8))

        assert fetch.call_count == 2

    def test_only_new_symbols_are_fetched_for_a_cached_month(self, tmp_path, mocker):
        fetch = mocker.Mock(side_effect=[
            _long_bars([("AAA", "2026-10-30", 12.0)]),
            _long_bars([("BBB", "2026-10-30", 5.0)]),
        ])
        cache = DailyBarCache(str(tmp_path), fetch)
        cache.load(["AAA"], date(2026, 10, 1), date(2026, 10, 31), date(2026, 11, 7))

        close, _ = cache.load(["AAA", "BBB"], date(2026, 10, 1), date(2026, 10, 31), date(2026, 11, 7))

        assert fetch.call_args_list[1][0][0] == ["BBB"]
        assert close.loc["2026-10-30"].tolist() == [12.0, 5.0]

    def test_adding_symbols_keeps_existing_ones_on_disk(self, tmp_path, mocker):
        fetch = mocker.Mock(side_effect=[
            _long_bars([("AAA", "2026-10-30", 12.0)]),
            _long_bars([("BBB", "2026-10-30", 5.0)]),
        ])
        DailyBarCache(str(tmp_path), fetch).load(["AAA"], date(2026, 10, 1), date(2026, 10, 31), date(2026, 11, 7))
        DailyBarCache(str(tmp_path), fetch).load(["AAA", "BBB"], date(2026, 10, 1), date(2026, 10, 31),
                                                 date(2026, 11, 7))

        close, _ = DailyBarCache(str(tmp_path), mocker.Mock()).load(
            ["AAA", "BBB"], date(2026, 10, 1), date(2026, 10, 31), date(2026, 11, 7))

        assert close.loc["2026-10-30"].tolist() == [12.0, 5.0]

    def test_older_month_is_rescaled_after_a_later_split(self, tmp_path, mocker):
        september_before_split = _long_bars([("AAA", "2026-08-31", 100.0), ("AAA", "2026-09-30", 120.0)])
        october_after_2_for_1 = _long_bars([("AAA", "2026-09-30", 60.0), ("AAA", "2026-10-30", 66.0)])
        fetch = mocker.Mock(side_effect=[september_before_split, october_after_2_for_1])
        cache = DailyBarCache(str(tmp_path), fetch)
        cache.load(["AAA"], date(2026, 9, 1), date(2026, 9, 30), date(2026, 10, 5))

        close, _ = cache.load(["AAA"], date(2026, 9, 1), date(2026, 10, 31), date(2026, 11, 7))

        assert close["AAA"].tolist() == [50.0, 60.0, 66.0]

    def test_seed_writes_only_fully_covered_months(self, tmp_path, mocker):
        bulk = _long_bars([("AAA", "2026-08-03", 9.0), ("AAA", "2026-09-30", 10.0), ("AAA", "2026-10-30", 11.0)])
        cache = DailyBarCache(str(tmp_path), mocker.Mock())

        written = cache.seed(bulk, date(2026, 11, 7), ["AAA"])

        assert written == [date(2026, 9, 1), date(2026, 10, 1)]
