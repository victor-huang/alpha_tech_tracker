import json
from datetime import date, datetime, timedelta

import pandas as pd
import pytest
import pytz

from alpha_tech_tracker.op_momentum_strategy.replay_simulater.build_replay_simulater import (
    TEMPLATE,
    config_setups,
    parse_args,
    pick_sessions,
    render,
    session_payload,
    system_trades,
)

ET = pytz.timezone("America/New_York")
DAY = date(2026, 11, 5)


def _trade(ticker, setup, exit_, day=DAY, entry="09:30", out="15:55", side=1, pct=1.0):
    return {"ticker": ticker, "setup": setup, "exit": exit_, "entry_time": f"{day} {entry}:00-05:00",
            "exit_time": f"{day} {out}:00-05:00", "side": side, "entry": 100.0, "exit_price": 101.0,
            "outcome": "eod", "net_pct": pct}


def _bars(days, sessions_per_day=78):
    rows, index = [], []
    for k, day in enumerate(days):
        for i in range(sessions_per_day):
            index.append(ET.localize(datetime.combine(day, datetime.min.time()) + timedelta(hours=9, minutes=30 + 5 * i)))
            price = 100.0 + k + i * 0.01
            rows.append({"open": price, "high": price + 0.5, "low": price - 0.5, "close": price, "vwap": price})
    return pd.DataFrame(rows, index=pd.DatetimeIndex(index))


class TestConfigSetups:
    def test_reads_setup_names(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"tickers": {"MRNA": [{"setup": "drive long", "report_total_pct": 1.0}, "pullback long"]}}))

        assert config_setups(path) == {"MRNA": ["drive long", "pullback long"]}


class TestSystemTrades:
    def test_keeps_configured_setups_at_their_fixed_exit(self):
        trades = pd.DataFrame([_trade("MRNA", "drive long", "eod"), _trade("MRNA", "drive long", "target"),
                               _trade("MRNA", "box break", "target")])

        kept = system_trades(trades, {"MRNA": ["drive long"]}, set())

        assert kept[["setup", "exit"]].values.tolist() == [["drive long", "eod"]]

    def test_drive_short_only_on_gated_days(self):
        trades = pd.DataFrame([_trade("MRNA", "drive short", "eod", side=-1),
                               _trade("MRNA", "drive short", "eod", day=DAY - timedelta(days=1), side=-1)])

        kept = system_trades(trades, {"MRNA": ["drive long"]}, {DAY})

        assert kept.day.tolist() == [DAY]

    def test_skips_overnight_setups(self):
        trades = pd.DataFrame([_trade("MRNA", "overnight always", "next open")])

        assert system_trades(trades, {"MRNA": ["overnight always"]}, set()).empty


class TestPickSessions:
    def _trades(self, n):
        days = [DAY - timedelta(days=k) for k in range(n)]
        return pd.DataFrame({"ticker": "MRNA", "day": days, "net_pct": [float(k) for k in range(n)]})

    def test_all_returns_every_ticker_day_in_date_order(self):
        picks = pick_sessions(self._trades(4), "all")

        assert [d for _, d in picks] == sorted(d for _, d in picks) and len(picks) == 4

    def test_sample_keeps_best_and_worst(self):
        trades = self._trades(40)

        picks = set(pick_sessions(trades, "sample"))

        best, worst = ("MRNA", DAY - timedelta(days=39)), ("MRNA", DAY)
        assert best in picks and worst in picks
        assert len(picks) <= 24


class TestSessionPayload:
    def test_bars_previous_session_and_signals(self):
        days = [DAY - timedelta(days=3), DAY - timedelta(days=2), DAY - timedelta(days=1), DAY]
        trades = pd.DataFrame([_trade("MRNA", "drive long", "eod")])

        payload = session_payload("MRNA", DAY, _bars(days), trades, gate_on=False)

        assert (payload["date"], payload["prevDate"], len(payload["bars"]), len(payload["prev"])) == (
            "2026-11-05", "2026-11-04", 78, 78)
        assert len(payload["bars"][0]) == 10 and payload["bars"][0][0] == "09:30"
        first_bar_ma200, first_bar_low = payload["bars"][0][8], payload["bars"][0][3]
        assert first_bar_ma200 is not None
        assert payload["signals"][0]["stop"] == first_bar_low
        assert (payload["signals"][0]["entryBar"], payload["signals"][0]["exitBar"]) == (0, 77)

    def test_none_without_a_previous_session(self):
        trades = pd.DataFrame([_trade("MRNA", "drive long", "eod")])

        assert session_payload("MRNA", DAY, _bars([DAY]), trades, gate_on=False) is None


class TestRender:
    def test_inserts_the_data_and_escapes_script_ends(self):
        page = render("<script>__DATA__</script>", [{"ticker": "</script>"}])

        assert page == '<script>[{"ticker":"<\\/script>"}]</script>'

    def test_template_has_one_placeholder(self):
        assert TEMPLATE.read_text().count("__DATA__") == 1


class TestParseArgs:
    def test_needs_config_or_tickers(self):
        with pytest.raises(SystemExit):
            parse_args(["--start", "2026-10-01", "--end", "2026-11-06"])

    def test_defaults(self):
        args = parse_args(["--tickers", "MRNA", "--start", "2026-10-01", "--end", "2026-11-06"])

        assert (args.setups, args.short_gate, args.sessions) == (["drive long", "pullback long"], "qqq-ma50-down10", "sample")
