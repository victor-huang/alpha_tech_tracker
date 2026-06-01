"""
Simulation tests for the MA OR screener live polling loop.

These tests exercise the full run_live() code path using past bar data
so we can verify that all the plumbing — warmup merge, MA recompute,
signal detection, notification, EOD summary, and latch dedup — works
correctly without hitting the network or sending real SMS.

Simulation design
-----------------
_now_et() is mocked to advance through three loop iterations:
  1. 09:30 ET  — before OR closes  → sleep, continue
  2. 09:50 ET  — inside collection window → fetch + detect signals
  3. 15:55 ET  — EOD  → send summary, sleep(60) → raises StopIteration

time.sleep() side_effect drives termination:
  call 1 (pre-OR sleep)    → None  (loop continues)
  call 2 (post-signal sleep) → None (loop continues)
  call 3 (EOD sleep(60))   → StopIteration (test exits cleanly)

Bar data
--------
All tickers use a synthetic two-day dataset:
  Prior day (247 bars):  close=100, vol=500K  →  establishes MA20/50/200 ≈ 100
                         and vol_20day_avg ≈ 500K for the collection window
  Today (OR + signal):   OR bars 09:30/09:35/09:40 bracket MA20 inside OR range;
                         09:45 bar close=101 > OR_mid(100), vol=2M > 500K avg
                         → fires a BULL signal on the 09:45 bar
"""
from datetime import date, datetime, time as dtime, timedelta
from unittest.mock import MagicMock, call, patch

import pandas as pd
import pytest
import pytz

from alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener import run_live

ET = pytz.timezone("America/New_York")
_MODULE = "alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener"

_SIM_DATE = date(2026, 5, 20)
_SIM_TICKERS = ["TSLA"]


# ─── Bar-building helpers ──────────────────────────────────────────────────────


def _ts(d, t):
    return ET.localize(datetime.combine(d, t))


def _make_prior_day_bars(target_date, close=100.0, vol=500_000, n_bars=247):
    """247 5-min bars on the day before target_date, at a constant close/vol."""
    prior = target_date - timedelta(days=1)
    timestamps = [
        _ts(prior, dtime(9, 30)) + timedelta(minutes=5 * i)
        for i in range(n_bars)
    ]
    c = [close] * n_bars
    v = [vol] * n_bars
    return pd.DataFrame(
        {"Open": c, "High": c, "Low": c, "Close": c, "Volume": v},
        index=timestamps,
    )


def _make_today_bars(target_date, or_bars=3, signal_bar_close=101.0,
                     or_high=103.0, or_low=97.0, signal_vol=2_000_000,
                     include_signal_bar=True):
    """
    Build today's bars:
      OR bars (or_bars × 5-min starting 09:30): close near OR_mid so MA20 sits inside OR
      Signal bar (09:45 with or_bars=3): close > OR_mid, high vol → BULL
    """
    rows = []
    base = _ts(target_date, dtime(9, 30))
    # OR bars
    for i in range(or_bars):
        t = base + timedelta(minutes=5 * i)
        rows.append({"ts": t, "Open": 100.0, "High": or_high if i == or_bars - 1 else 101.0,
                     "Low": or_low if i == 0 else 99.0, "Close": 100.0, "Volume": signal_vol})
    if include_signal_bar:
        signal_ts = base + timedelta(minutes=5 * or_bars)
        rows.append({"ts": signal_ts, "Open": signal_bar_close,
                     "High": signal_bar_close + 0.5, "Low": signal_bar_close - 0.5,
                     "Close": signal_bar_close, "Volume": signal_vol})
    df = pd.DataFrame(rows).set_index("ts")
    return df


def _make_full_warmup(target_date, tickers, vol=500_000):
    """Return {ticker: prior_day_bars} — no MA columns (raw, as fetch_bars returns)."""
    return {t: _make_prior_day_bars(target_date, vol=vol) for t in tickers + ["QQQ"]}


def _make_live_bars(target_date, tickers, signal_vol=2_000_000, include_signal_bar=True):
    """Return {ticker: today_bars} — raw, as market_data_client.fetch_bars() returns."""
    return {
        t: _make_today_bars(target_date, signal_vol=signal_vol,
                            include_signal_bar=include_signal_bar)
        for t in tickers + ["QQQ"]
    }


# ─── Mock helpers ──────────────────────────────────────────────────────────────


def _mock_now_et(target_date, times):
    """Return a callable that yields successive ET datetimes."""
    it = iter([ET.localize(datetime.combine(target_date, t)) for t in times])
    return lambda: next(it)


class _MockMarketDataClient:
    def __init__(self, bars_by_ticker):
        self._bars = bars_by_ticker

    def fetch_bars(self, tickers, start, end):
        return {t: self._bars.get(t, pd.DataFrame()) for t in tickers}


# ─── Simulation tests ──────────────────────────────────────────────────────────


class TestLiveScreenerSimulation:
    """
    End-to-end simulation of run_live() using synthetic historical bar data.
    The live polling loop is driven through three phases (pre-OR, active, EOD)
    before being stopped by a StopIteration from the mocked time.sleep.
    """

    # Three mock times that advance the loop through pre-OR → active → EOD
    _LOOP_TIMES = [dtime(9, 30), dtime(9, 50), dtime(15, 55)]
    # sleep side-effects: pre-OR sleep, post-signal sleep, EOD sleep → stop
    _SLEEP_EFFECTS = [None, None, StopIteration("sim done")]

    def _run_sim(self, tickers, warmup_bars, live_bars, dry_run=False,
                 extra_sleep_effects=None, loop_times=None):
        """
        Run run_live() with all external I/O mocked.

        Returns (notified_messages, mock_notify) so callers can assert on
        what SMS messages were sent.
        """
        notified = []
        sleep_effects = extra_sleep_effects or list(self._SLEEP_EFFECTS)
        times = loop_times or self._LOOP_TIMES
        client = _MockMarketDataClient(live_bars)

        with patch(f"{_MODULE}._now_et", side_effect=_mock_now_et(_SIM_DATE, times)), \
             patch(f"{_MODULE}.fetch_bars", return_value=warmup_bars), \
             patch(f"{_MODULE}.fetch_daily_bars",
                   return_value={t: pd.DataFrame() for t in tickers + ["QQQ"]}), \
             patch(f"{_MODULE}._notify", side_effect=notified.append), \
             patch(f"{_MODULE}.time") as mock_time:
            mock_time.sleep.side_effect = sleep_effects
            with pytest.raises(StopIteration):
                run_live(
                    tickers=tickers,
                    or_bars=3,
                    or_start="09:30",
                    collection_bars=3,
                    market_data_client=client,
                    poll_interval_sec=0,
                    dry_run=dry_run,
                )
        return notified, mock_time

    def test_signal_detected_and_sms_sent(self):
        warmup = _make_full_warmup(_SIM_DATE, _SIM_TICKERS)
        live = _make_live_bars(_SIM_DATE, _SIM_TICKERS, signal_vol=2_000_000)
        notified, _ = self._run_sim(_SIM_TICKERS, warmup, live)
        # at least the signal SMS should have been sent
        signal_msgs = [m for m in notified if "SIGNAL" in m]
        assert len(signal_msgs) >= 1

    def test_signal_sms_contains_ticker(self):
        warmup = _make_full_warmup(_SIM_DATE, _SIM_TICKERS)
        live = _make_live_bars(_SIM_DATE, _SIM_TICKERS, signal_vol=2_000_000)
        notified, _ = self._run_sim(_SIM_TICKERS, warmup, live)
        signal_msgs = [m for m in notified if "SIGNAL" in m]
        assert any("TSLA" in m for m in signal_msgs)

    def test_no_signal_when_volume_below_threshold(self):
        # collection_vol ≈ warmup vol (500K) → vol_ratio ≈ 1.0, but we need it > 1.0
        # Setting live vol = warmup vol means no edge → no BULL signal
        warmup = _make_full_warmup(_SIM_DATE, _SIM_TICKERS, vol=2_000_000)
        live = _make_live_bars(_SIM_DATE, _SIM_TICKERS, signal_vol=500_000)
        notified, _ = self._run_sim(_SIM_TICKERS, warmup, live)
        signal_msgs = [m for m in notified if "SIGNAL" in m]
        assert len(signal_msgs) == 0

    def test_eod_summary_sent(self):
        warmup = _make_full_warmup(_SIM_DATE, _SIM_TICKERS)
        live = _make_live_bars(_SIM_DATE, _SIM_TICKERS, signal_vol=2_000_000)
        notified, _ = self._run_sim(_SIM_TICKERS, warmup, live)
        # Summary is a separate _notify call that does not contain "SIGNAL"
        summary_msgs = [m for m in notified if "SIGNAL" not in m]
        assert len(summary_msgs) >= 1
        assert any("OR Screener" in m for m in summary_msgs)

    def test_eod_summary_reflects_signal_count(self):
        warmup = _make_full_warmup(_SIM_DATE, _SIM_TICKERS)
        live = _make_live_bars(_SIM_DATE, _SIM_TICKERS, signal_vol=2_000_000)
        notified, _ = self._run_sim(_SIM_TICKERS, warmup, live)
        summary_msgs = [m for m in notified if "OR Screener" in m]
        assert len(summary_msgs) == 1
        assert "1 signals" in summary_msgs[0] or "1 BULL" in summary_msgs[0]

    def test_signal_not_sent_twice_on_repeated_poll(self):
        """
        A second active-window poll for the same day must not re-fire the signal.
        Simulate two active-window iterations before EOD.
        """
        warmup = _make_full_warmup(_SIM_DATE, _SIM_TICKERS)
        live = _make_live_bars(_SIM_DATE, _SIM_TICKERS, signal_vol=2_000_000)

        # Two active-window iterations: 09:50 and 10:00, then EOD
        times = [dtime(9, 30), dtime(9, 50), dtime(10, 0), dtime(15, 55)]
        sleep_effects = [None, None, None, StopIteration("sim done")]
        notified, _ = self._run_sim(
            _SIM_TICKERS, warmup, live,
            loop_times=times, extra_sleep_effects=sleep_effects,
        )
        signal_msgs = [m for m in notified if "SIGNAL" in m and "TSLA" in m]
        assert len(signal_msgs) == 1

    def test_market_data_client_called_for_active_window_only(self):
        """
        market_data_client.fetch_bars() must only be called during the active
        window, not during the pre-OR phase.
        """
        warmup = _make_full_warmup(_SIM_DATE, _SIM_TICKERS)
        live = _make_live_bars(_SIM_DATE, _SIM_TICKERS)
        client = _MockMarketDataClient(live)
        mock_client = MagicMock(wraps=client)

        with patch(f"{_MODULE}._now_et",
                   side_effect=_mock_now_et(_SIM_DATE, self._LOOP_TIMES)), \
             patch(f"{_MODULE}.fetch_bars", return_value=warmup), \
             patch(f"{_MODULE}.fetch_daily_bars",
                   return_value={t: pd.DataFrame() for t in _SIM_TICKERS + ["QQQ"]}), \
             patch(f"{_MODULE}._notify"), \
             patch(f"{_MODULE}.time") as mock_time:
            mock_time.sleep.side_effect = list(self._SLEEP_EFFECTS)
            with pytest.raises(StopIteration):
                run_live(
                    tickers=_SIM_TICKERS,
                    or_bars=3,
                    or_start="09:30",
                    collection_bars=3,
                    market_data_client=mock_client,
                    poll_interval_sec=0,
                )
        # fetch_bars on the client must be called exactly once (the active window)
        assert mock_client.fetch_bars.call_count == 1

    def test_dry_run_calls_disable_notifications(self):
        """dry_run=True must call disable_notifications() so the real SMS is suppressed."""
        warmup = _make_full_warmup(_SIM_DATE, _SIM_TICKERS)
        live = _make_live_bars(_SIM_DATE, _SIM_TICKERS, signal_vol=2_000_000)

        with patch(f"{_MODULE}.disable_notifications") as mock_disable:
            self._run_sim(_SIM_TICKERS, warmup, live, dry_run=True)
        assert mock_disable.called

    def test_non_dry_run_does_not_call_disable_notifications(self):
        warmup = _make_full_warmup(_SIM_DATE, _SIM_TICKERS)
        live = _make_live_bars(_SIM_DATE, _SIM_TICKERS, signal_vol=2_000_000)

        with patch(f"{_MODULE}.disable_notifications") as mock_disable:
            self._run_sim(_SIM_TICKERS, warmup, live, dry_run=False)
        assert not mock_disable.called

    def test_pre_or_sleep_uses_poll_interval(self):
        """Before OR closes, the loop must sleep for poll_interval_sec."""
        warmup = _make_full_warmup(_SIM_DATE, _SIM_TICKERS)
        live = _make_live_bars(_SIM_DATE, _SIM_TICKERS)
        _, mock_time = self._run_sim(_SIM_TICKERS, warmup, live)
        # First sleep call should be poll_interval (0 in our sim)
        first_sleep_arg = mock_time.sleep.call_args_list[0]
        assert first_sleep_arg == call(0)

    def test_fetch_bars_called_on_startup_for_warmup(self):
        warmup = _make_full_warmup(_SIM_DATE, _SIM_TICKERS)
        live = _make_live_bars(_SIM_DATE, _SIM_TICKERS)

        with patch(f"{_MODULE}._now_et",
                   side_effect=_mock_now_et(_SIM_DATE, self._LOOP_TIMES)), \
             patch(f"{_MODULE}.fetch_bars", return_value=warmup) as mock_fetch, \
             patch(f"{_MODULE}.fetch_daily_bars",
                   return_value={t: pd.DataFrame() for t in _SIM_TICKERS + ["QQQ"]}), \
             patch(f"{_MODULE}._notify"), \
             patch(f"{_MODULE}.time") as mock_time:
            mock_time.sleep.side_effect = list(self._SLEEP_EFFECTS)
            with pytest.raises(StopIteration):
                run_live(
                    tickers=_SIM_TICKERS,
                    or_bars=3,
                    market_data_client=_MockMarketDataClient(live),
                    poll_interval_sec=0,
                )
        # Alpaca warmup fetch must happen once before the loop
        assert mock_fetch.call_count == 1
