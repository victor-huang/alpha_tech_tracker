import csv
from collections import OrderedDict
from datetime import date

import pandas as pd
import pytest

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_setup_report import (
    REPORT_EXITS,
    build_report,
    period_totals,
    stats,
    week_start,
    write_outputs,
)

MARKET_TZ = "America/New_York"


def _trade(day, pnl, **extra):
    stamp = pd.Timestamp(day, tz=MARKET_TZ)
    return dict({"entry_time": stamp, "exit_time": stamp, "side": 1, "entry": 100.0, "exit": 101.0,
                 "outcome": "target", "net_pct": pnl}, **extra)


def _results(trades):
    setups = OrderedDict()
    for setup, exit_mode in REPORT_EXITS.items():
        setups[setup] = {exit_mode: list(trades) if setup == "drive long" else []}
    return OrderedDict(AMD=setups)


def _overviews():
    return OrderedDict(AMD={"sessions": 3, "buy_hold": 5.0, "overnight": 4.0, "in_session": 1.0,
                            "earnings": OrderedDict([(date(2026, 9, 2), -13.2)])})


class TestWeekStart:
    def test_returns_the_monday(self):
        assert week_start(date(2026, 9, 3)) == date(2026, 8, 31)


class TestPeriodTotals:
    def test_sums_by_week(self):
        trades = [_trade("2026-09-01 10:00", 1.0), _trade("2026-09-03 10:00", -0.5), _trade("2026-09-08 10:00", 2.0)]

        totals = period_totals(trades, week_start)

        assert totals == {date(2026, 8, 31): pytest.approx(0.5), date(2026, 9, 7): pytest.approx(2.0)}

    def test_sums_by_month(self):
        trades = [_trade("2026-08-31 10:00", 1.0), _trade("2026-09-01 10:00", 3.0)]

        assert period_totals(trades, lambda d: (d.year, d.month)) == {(2026, 8): 1.0, (2026, 9): 3.0}


class TestStats:
    def test_counts_trades_wins_and_total(self):
        result = stats([_trade("2026-09-01 10:00", 1.0), _trade("2026-09-02 10:00", -1.0)])

        assert result == {"trades": 2, "win": 0.5, "total": 0.0}


class TestBuildReport:
    def test_includes_summary_monthly_and_weekly_tables(self):
        report = build_report(_results([_trade("2026-09-01 10:00", 1.5)]), _overviews(),
                              date(2026, 9, 1), date(2026, 9, 30), 5)

        assert "| drive long (eod) | +1.50% |" in report
        assert "### Monthly (fixed exits)" in report
        assert "### Weekly (week starting) (fixed exits)" in report
        assert "| AMD | +5.00% | +4.00% | +1.00% | drive long +1.50% |" in report

    def test_lists_earnings_sessions(self):
        report = build_report(_results([_trade("2026-09-01 10:00", 1.5)]), _overviews(),
                              date(2026, 9, 1), date(2026, 9, 30), 5)

        assert "Earnings reaction sessions (close vs previous close): 2026-09-02 -13.20%." in report

    def test_splits_flagged_trades_into_earnings_and_other(self):
        trades = [_trade("2026-09-02 09:30", -4.0, earnings=True), _trade("2026-09-03 09:30", 1.0, earnings=False)]

        report = build_report(_results(trades), _overviews(), date(2026, 9, 1), date(2026, 9, 30), 5)

        assert "| drive long | 1 / -4.00% | 1 / +1.00% |" in report

    def test_notes_skipped_earnings_trades(self):
        report = build_report(_results([]), _overviews(), date(2026, 9, 1), date(2026, 9, 30), 5, earnings="skip")

        assert "Trades carrying an earnings reaction are skipped." in report


class TestWriteOutputs:
    def test_writes_report_trades_and_summary(self, tmp_path):
        out_dir = write_outputs(_results([_trade("2026-09-01 10:00", 1.5)]), _overviews(),
                                date(2026, 9, 1), date(2026, 9, 30), 5, tmp_path / "out")

        with (out_dir / "trades.csv").open() as handle:
            rows = list(csv.DictReader(handle))
        assert [(r["ticker"], r["setup"], r["exit"], r["net_pct"]) for r in rows] == [("AMD", "drive long", "eod", "1.5")]
        assert (out_dir / "report.md").exists()
        assert (out_dir / "summary.csv").exists()
