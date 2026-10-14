import argparse
from datetime import date

import pandas as pd
import pytest

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_setup_vs_buy_hold import (
    FIRST_BAR_STOP,
    buy_and_hold,
    compare,
    drive_long_trades,
    main,
    parse_period,
    strategy_result,
)

MARKET_TZ = "America/New_York"
MODULE = "alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_setup_vs_buy_hold"


def _session(day, rows):
    """5-min bars from 09:30 on `day`, rows of (open, high, low, close)."""
    index = pd.date_range(pd.Timestamp(f"{day} 09:30", tz=MARKET_TZ), periods=len(rows), freq="5min")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=index)


def _flat_history(day, bars=80, price=100.0, bar_range=1.0):
    """A session of flat bars before `day`, so the average 5-min bar range is `bar_range`."""
    rows = [(price, price + bar_range / 2, price - bar_range / 2, price)] * bars
    return _session(day, rows)


class TestParsePeriod:
    def test_parses_start_and_end(self):
        assert parse_period("2025-05-01:2025-09-29") == (date(2025, 5, 1), date(2025, 9, 29))

    def test_rejects_end_before_start(self):
        with pytest.raises(argparse.ArgumentTypeError):
            parse_period("2025-09-29:2025-05-01")

    def test_rejects_bad_format(self):
        with pytest.raises(argparse.ArgumentTypeError):
            parse_period("2025-05-01")


class TestDriveLongTrades:
    def _bars(self, rows):
        return pd.concat([_flat_history("2026-09-01"), _session("2026-09-02", rows)])

    def test_red_first_bar_is_not_traded(self):
        trades = drive_long_trades(self._bars([(101, 101.5, 99.5, 100), (100, 100.5, 99.8, 100.2), (100, 101, 99.9, 100.5)]))

        assert trades[trades.day == date(2026, 9, 2)].empty

    def test_first_bar_low_stop_fills_at_the_stop(self):
        trades = drive_long_trades(self._bars([(100, 101.2, 99.8, 101), (100.5, 100.6, 99.5, 100), (100, 102, 99.9, 101.5)]),
                                   cost_bps=0.0)

        tight = trades[(trades.day == date(2026, 9, 2)) & (trades.stop == FIRST_BAR_STOP)].iloc[0]
        assert tight.net_pct == pytest.approx((99.8 / 101 - 1) * 100)

    def test_wider_stop_holds_to_the_close(self):
        trades = drive_long_trades(self._bars([(100, 101.2, 99.8, 101), (100.5, 100.6, 99.5, 100), (100, 102, 99.9, 101.5)]),
                                   avg_bar_stop=2.0, cost_bps=0.0)

        wide = trades[(trades.day == date(2026, 9, 2)) & (trades.stop == "2x avg-bar stop")].iloc[0]
        assert wide.net_pct == pytest.approx((101.5 / 101 - 1) * 100)

    def test_costs_come_off_every_trade(self):
        rows = [(100, 101.2, 99.8, 101), (101, 101.6, 100.9, 101.5), (101.5, 102, 101.4, 101.5)]

        trades = drive_long_trades(self._bars(rows), cost_bps=5.0)

        tight = trades[(trades.day == date(2026, 9, 2)) & (trades.stop == FIRST_BAR_STOP)].iloc[0]
        assert tight.net_pct == pytest.approx((101.5 / 101 - 1) * 100 - 0.05)


class TestBuyAndHold:
    def test_return_from_first_open_to_last_close(self):
        bars = pd.concat([_session("2026-09-01", [(100, 101, 99, 100), (100, 110, 99, 110)]),
                          _session("2026-09-02", [(110, 111, 98, 99)])])

        result, _ = buy_and_hold(bars, date(2026, 9, 1), date(2026, 9, 2))

        assert result == pytest.approx(-1.0)

    def test_drawdown_from_the_highest_daily_close(self):
        bars = pd.concat([_session("2026-09-01", [(100, 111, 99, 110)]), _session("2026-09-02", [(110, 111, 98, 99)])])

        _, drawdown = buy_and_hold(bars, date(2026, 9, 1), date(2026, 9, 2))

        assert drawdown == pytest.approx(-10.0)


class TestStrategyResult:
    def _trades(self):
        times = pd.date_range(pd.Timestamp("2026-09-01 09:35", tz=MARKET_TZ), periods=3, freq="1D")
        return pd.DataFrame({"day": [t.date() for t in times], "time": times, "net_pct": [2.0, -3.0, 1.0]})

    def test_sums_pnl_at_the_trade_size(self):
        result = strategy_result(self._trades(), date(2026, 9, 1), date(2026, 9, 3), size=10000)

        assert (result["P&L $"], result["return %"], result["trades"]) == (pytest.approx(0.0), pytest.approx(0.0), 3)

    def test_drawdown_as_percent_of_size(self):
        result = strategy_result(self._trades(), date(2026, 9, 1), date(2026, 9, 3), size=10000)

        assert result["max DD %"] == pytest.approx(-3.0)

    def test_only_trades_inside_the_period_count(self):
        result = strategy_result(self._trades(), date(2026, 9, 2), date(2026, 9, 2), size=10000)

        assert (result["trades"], result["P&L $"]) == (1, pytest.approx(-300.0))


class TestCompare:
    def test_buy_and_hold_row_leads_each_period(self, mocker):
        mocker.patch(f"{MODULE}.overnight_trades", return_value=pd.DataFrame(columns=["day", "time", "net_pct"]))
        bars = pd.concat([_flat_history("2026-09-01"), _session("2026-09-02", [(100, 101.2, 99.8, 101), (101, 102, 100.9, 101.5),
                                                                              (101.5, 102, 101.4, 102)])])

        table = compare(bars, [(date(2026, 9, 1), date(2026, 9, 2))], earnings_windows=None)

        assert table.iloc[0].strategy == "buy & hold"
        assert table["vs buy & hold $"].iloc[0] == 0.0


class TestMain:
    def test_fetches_with_warmup_and_prints_each_period(self, mocker, capsys):
        bars = pd.concat([_flat_history("2026-09-01"), _session("2026-09-02", [(100, 101.2, 99.8, 101), (101, 102, 100.9, 101.5),
                                                                              (101.5, 102, 101.4, 102)])])
        fetch = mocker.patch(f"{MODULE}.fetch_bars", return_value=bars)
        mocker.patch(f"{MODULE}.ticker_earnings_windows", return_value=None)
        mocker.patch(f"{MODULE}.overnight_trades", return_value=pd.DataFrame(columns=["day", "time", "net_pct"]))

        main(["snps", "--period", "2026-09-01:2026-09-02"])

        assert fetch.call_args.args[0] == "SNPS"
        assert fetch.call_args.args[1] < date(2025, 9, 1)
        assert "=== SNPS 09/01/2026-09/02/2026" in capsys.readouterr().out

    def test_since_drops_bars_before_the_listing(self, mocker):
        old = _session("2026-08-31", [(21.98, 21.98, 21.98, 21.98)] * 80)
        listed = _session("2026-09-01", [(150, 160, 149, 159), (159, 165, 158, 164), (164, 166, 163, 165)])
        mocker.patch(f"{MODULE}.fetch_bars", return_value=pd.concat([old, listed]))
        mocker.patch(f"{MODULE}.ticker_earnings_windows", return_value=None)
        compare_bars = mocker.patch(f"{MODULE}.compare", return_value=pd.DataFrame(columns=["period", "strategy"]))

        main(["SPCX", "--period", "2026-09-01:2026-09-01", "--since", "2026-09-01"])

        assert compare_bars.call_args.args[0].index.min() == pd.Timestamp("2026-09-01 09:30", tz=MARKET_TZ)
