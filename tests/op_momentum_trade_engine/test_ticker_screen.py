from datetime import date, timedelta

import pandas as pd
import pytest

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.ticker_screen import (
    core_results,
    daily_stats,
    delisted_stocks,
    fetch_daily,
    is_fund,
    monitor_config,
    parse_args,
    rank,
    screen,
    stock_universe,
)
from alpha_tech_tracker.op_momentum_strategy.wave_setup_monitor import load_config

DAY = date(2026, 10, 1)
MODULE = "alpha_tech_tracker.op_momentum_strategy.analysis_scripts.ticker_screen"


def _daily(close, high, low, volume, sessions=130):
    index = [DAY + timedelta(days=i) for i in range(sessions)]
    return pd.DataFrame({"Close": close, "High": high, "Low": low, "Volume": volume}, index=index)


def _stats(rows):
    return pd.DataFrame(rows, columns=["ticker", "close", "dollar_vol", "range_pct"]).set_index("ticker")


class TestStockUniverse:
    def test_keeps_tradable_nyse_and_nasdaq_stocks(self):
        assets = [{"symbol": "AMD", "exchange": "NASDAQ", "tradable": True, "name": "Advanced Micro Devices"},
                  {"symbol": "XOM", "exchange": "NYSE", "tradable": True, "name": "Exxon Mobil"},
                  {"symbol": "OTCX", "exchange": "OTC", "tradable": True, "name": "Some OTC"},
                  {"symbol": "HALT", "exchange": "NYSE", "tradable": False, "name": "Halted"},
                  {"symbol": "BRK.B", "exchange": "NYSE", "tradable": True, "name": "Berkshire"}]

        assert stock_universe(assets) == ["AMD", "XOM"]

    def test_drops_funds(self):
        assets = [{"symbol": "TQQQ", "exchange": "NASDAQ", "tradable": True, "name": "ProShares UltraPro QQQ"},
                  {"symbol": "IBIT", "exchange": "NASDAQ", "tradable": True, "name": "iShares Bitcoin Trust ETF"}]

        assert stock_universe(assets) == []

    @pytest.mark.parametrize("name,expected", [("SPDR S&P 500 ETF Trust", True), ("Direxion Daily Semis 3X", True),
                                               ("NVIDIA Corporation", False), (None, False)])
    def test_is_fund(self, name, expected):
        assert is_fund(name) is expected


class TestDailyStats:
    def test_dollar_volume_and_range(self):
        stats = daily_stats({"AMD": _daily(100.0, 104.0, 99.0, 2_000_000)})

        assert stats.loc["AMD"].to_dict() == pytest.approx({"close": 100.0, "dollar_vol": 200_000_000.0, "range_pct": 5.0})

    def test_skips_short_history(self):
        assert daily_stats({"NEW": _daily(100.0, 104.0, 99.0, 1, sessions=20)}).empty


class TestScreen:
    def test_top_by_volume_then_range(self):
        stats = _stats([("A", 50.0, 3e9, 5.0), ("B", 50.0, 2e9, 3.0), ("C", 50.0, 1e9, 6.0)])

        assert screen(stats, top_volume=2, min_range=4.0, min_price=10.0).index.tolist() == ["A"]

    def test_price_floor_applies_before_the_volume_rank(self):
        stats = _stats([("PENNY", 5.0, 9e9, 9.0), ("A", 50.0, 1e9, 5.0)])

        assert screen(stats, top_volume=1, min_range=4.0, min_price=10.0).index.tolist() == ["A"]


class TestCoreResults:
    def test_overnight_counts_only_on_allowed_nights(self):
        legs = pd.DataFrame([("AMD", DAY, "drive long", 1.0), ("AMD", DAY, "overnight long", 2.0),
                             ("AMD", DAY + timedelta(days=1), "overnight long", -3.0)],
                            columns=["ticker", "day", "leg", "pct"])

        row = core_results(legs, {DAY: True, DAY + timedelta(days=1): False}).loc["AMD"]

        assert (row.drive_sum, row.night_sum, row.core_sum, row.core_per_trade) == (1.0, 2.0, 3.0, 1.5)

    def _legs_with_shorts(self):
        return pd.DataFrame([("AMD", DAY, "drive long", 1.0), ("AMD", DAY, "drive short + re-entry", 4.0),
                             ("AMD", DAY + timedelta(days=1), "drive short + re-entry", -1.0)],
                            columns=["ticker", "day", "leg", "pct"])

    def test_drive_short_every_day_and_on_gated_days(self):
        row = core_results(self._legs_with_shorts(), {}, short_days={DAY}).loc["AMD"]

        assert (row.short_trades, row.short_sum, row.gated_short_trades, row.gated_short_sum) == (2, 3.0, 1, 4.0)

    def test_score_is_the_core_sum_unless_shorts_are_ranked(self):
        scores = {mode: core_results(self._legs_with_shorts(), {}, {DAY}, mode).loc["AMD"]
                  for mode in ("none", "gated", "all")}

        assert {m: (r.score, r.score_trades) for m, r in scores.items()} == {"none": (1.0, 1), "gated": (5.0, 2),
                                                                             "all": (4.0, 3)}


class TestRank:
    def test_best_first_and_thin_history_last(self):
        passers = _stats([("A", 50.0, 3e9, 5.0), ("B", 50.0, 2e9, 5.0), ("NEW", 50.0, 1e9, 5.0)])
        results = pd.DataFrame({"score_trades": [70, 70, 5], "score": [1.0, 9.0, 50.0]}, index=["A", "B", "NEW"])

        assert rank(passers, results).index.tolist() == ["B", "A", "NEW"]


class TestMonitorConfig:
    def test_loads_in_the_monitor(self, tmp_path):
        picks = pd.DataFrame({"drive_sum": [12.345], "night_sum": [-1.0]}, index=["SNDK"])
        path = tmp_path / "config.json"
        path.write_text(pd.io.json.dumps(monitor_config(picks, DAY, DAY - timedelta(days=90))))

        assert [spec.name for spec in load_config(path)["SNDK"]] == ["drive long", "overnight always"]


class TestParseArgs:
    def test_defaults(self):
        args = parse_args([])

        assert (args.top_volume, args.min_range, args.min_price, args.lookback, args.picks,
                args.rank_shorts) == (150, 4.0, 10.0, 63, 5, "none")


class TestFetchDaily:
    def test_splits_each_batch_by_symbol(self, mocker):
        index = pd.MultiIndex.from_tuples([("AMD", pd.Timestamp("2026-10-01")), ("AMD", pd.Timestamp("2026-10-02")),
                                           ("MU", pd.Timestamp("2026-10-01"))], names=["symbol", "timestamp"])
        frame = pd.DataFrame({"close": [1.0, 2.0, 3.0], "high": 1.0, "low": 1.0, "volume": 1.0}, index=index)
        client = mocker.patch(f"{MODULE}.StockHistoricalDataClient").return_value
        client.get_stock_bars.return_value = mocker.Mock(df=frame)

        daily = fetch_daily(["AMD", "MU"], DAY, DAY + timedelta(days=1))

        assert (daily["AMD"]["Close"].tolist(), daily["MU"]["Close"].tolist()) == ([1.0, 2.0], [3.0])


class TestDelistedStocks:
    def test_former_nyse_and_nasdaq_stocks_not_listed_today(self):
        assets = [{"symbol": "BBBY", "exchange": "NASDAQ", "name": "Bed Bath & Beyond"},
                  {"symbol": "AMD", "exchange": "NASDAQ", "name": "Advanced Micro Devices"},
                  {"symbol": "XOTC", "exchange": "OTC", "name": "Some OTC"},
                  {"symbol": "OLDETF", "exchange": "NYSE", "name": "Old Fund ETF"}]

        assert delisted_stocks(assets, ["AMD"]) == ["BBBY"]
