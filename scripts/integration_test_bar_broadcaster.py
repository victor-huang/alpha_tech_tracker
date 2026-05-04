"""
Integration test: BarBroadcaster → Unix socket → live trade engine (mock execution)

Uses the production BarBroadcaster from bar_broadcaster.py. TradeStationBarStream is
patched so its run() blocks on the broadcaster's stop_event instead of opening a live
WebSocket; 1-min CSV bars are fed directly via broadcaster._on_bar() to drive playback.

Usage:
  source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
  export PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker

  # Default: most recent date with 1-min data, top-2, $10k capital, 30x speed
  python scripts/integration_test_bar_broadcaster.py

  # Specific date / tickers / speed
  python scripts/integration_test_bar_broadcaster.py \
      --date 2026-04-08 --tickers AMD APP COIN --top 2 --capital 10000 --speed 60

Exits cleanly after all CSV bars have been replayed and EOD positions are closed.
"""

import argparse
import csv
import logging
import os
import tempfile
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional
from unittest.mock import MagicMock, patch

import pytz

ET = pytz.timezone("America/New_York")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("integration_test")

_LIVE_DATA_DIR = (
    Path(__file__).parent.parent
    / "alpha_tech_tracker"
    / "op_momentum_strategy"
    / "live_trade_market_data"
)
_DEFAULT_FEED = "iex"


# ---------------------------------------------------------------------------
# CSV bar loading
# ---------------------------------------------------------------------------

def _load_merged_bars(replay_date: date, tickers: List[str],
                      data_dir: Path = _LIVE_DATA_DIR,
                      feed: str = _DEFAULT_FEED) -> list:
    """
    Load 1-min bars for all tickers from CSV, merge and sort by timestamp.
    Returns a list of _TSBar objects ready to pass to broadcaster._on_bar().
    """
    from alpha_tech_tracker.trade_api.tradestation.bar_stream import _TSBar

    all_bars = []
    for ticker in tickers:
        csv_path = data_dir / str(replay_date) / f"{feed}_{ticker}_1min.csv"
        if not csv_path.exists():
            logger.warning("No 1-min CSV for %s at %s", ticker, csv_path)
            continue
        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts = ET.localize(datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S"))
                all_bars.append(_TSBar(
                    symbol=ticker,
                    timestamp=ts,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                ))
        logger.info("Loaded %d 1-min bars for %s", sum(1 for b in all_bars if b.symbol == ticker), ticker)
    all_bars.sort(key=lambda b: b.timestamp)
    return all_bars


# ---------------------------------------------------------------------------
# Playback thread
# ---------------------------------------------------------------------------

def _playback_bars(broadcaster, bars: list, replay_date: date,
                   speed: float, bars_sent: list):
    """
    Feed _TSBar objects into broadcaster._on_bar() at simulated speed,
    advancing the replay clock with each bar.

    Sends a synthetic 16:00 flush bar per ticker at the end so the signal
    engine finalises the 15:50-15:54 minute buffer before EOD exit pricing.
    """
    from alpha_tech_tracker.op_momentum_strategy.replay import set_replay_clock

    logger.info("Waiting for first client connection before starting playback...")
    while True:
        with broadcaster._clients_lock:
            if broadcaster._clients:
                break
        if broadcaster._stop_event.is_set():
            return
        time.sleep(0.05)

    logger.info("Starting playback: %d total 1-min bars", len(bars))

    prev_ts: Optional[datetime] = None
    for bar in bars:
        if broadcaster._stop_event.is_set():
            return
        set_replay_clock(lambda t=bar.timestamp: t)
        if prev_ts is not None:
            gap = (bar.timestamp - prev_ts).total_seconds()
            if gap > 0:
                broadcaster._stop_event.wait(gap / speed)
        prev_ts = bar.timestamp
        broadcaster._on_bar(bar)
        bars_sent[0] += 1

    # Flush the 15:50-15:54 minute buffer so mock exit pricing uses the true
    # last close rather than the 5-minute-stale 15:45-period close.
    from alpha_tech_tracker.trade_api.tradestation.bar_stream import _TSBar
    flush_ts = ET.localize(
        datetime.combine(replay_date, datetime.strptime("16:00", "%H:%M").time())
    )
    set_replay_clock(lambda t=flush_ts: t)
    seen: set = set()
    for bar in reversed(bars):
        if bar.symbol not in seen:
            seen.add(bar.symbol)
            broadcaster._on_bar(_TSBar(
                symbol=bar.symbol,
                timestamp=flush_ts,
                open=bar.close, high=bar.close,
                low=bar.close, close=bar.close,
                volume=0,
            ))
            bars_sent[0] += 1
        if len(seen) == len({b.symbol for b in bars}):
            break
    time.sleep(0.05)

    eod = ET.localize(
        datetime.combine(replay_date, datetime.strptime("16:05", "%H:%M").time())
    )
    set_replay_clock(lambda: eod)
    logger.info("Playback complete — %d bars sent; clock advanced to %s", bars_sent[0], eod)


# ---------------------------------------------------------------------------
# Broadcaster thread
# ---------------------------------------------------------------------------

def _run_broadcaster(broadcaster, bars: list, replay_date: date,
                     speed: float, bars_sent: list):
    """
    Run in a daemon thread.  Patches TradeStationBarStream so run() blocks on
    broadcaster._stop_event, starts the real BarBroadcaster (socket + accept +
    heartbeat), then drives playback via _playback_bars().
    """
    threading.Thread(
        target=_playback_bars,
        args=(broadcaster, bars, replay_date, speed, bars_sent),
        name="csv-playback",
        daemon=True,
    ).start()

    with patch(
        "alpha_tech_tracker.op_momentum_strategy.bar_broadcaster.TradeStationBarStream"
    ) as MockStream:
        mock_stream = MagicMock()
        mock_stream.run.side_effect = lambda: broadcaster._stop_event.wait()
        MockStream.return_value = mock_stream
        broadcaster.start()  # blocks until broadcaster.stop() is called


# ---------------------------------------------------------------------------
# AlpacaCacheFeedClient
# ---------------------------------------------------------------------------

def _aggregate_to_5min(one_min_bars: list, tickers: list, start_dt, end_dt) -> dict:
    """
    Aggregate 1-min _TSBar objects into 5-min OHLCV DataFrames for the OR catchup.
    Returns {ticker: DataFrame(index=period_start, columns=[Open,High,Low,Close,Volume])}.
    """
    import pandas as pd
    from collections import defaultdict

    result = {}
    for ticker in tickers:
        buckets: dict = defaultdict(list)
        for bar in one_min_bars:
            if bar.symbol != ticker:
                continue
            ts = bar.timestamp
            if ts < start_dt or ts >= end_dt:
                continue
            minutes_since_start = int((ts - start_dt).total_seconds() // 60)
            period_start = start_dt + timedelta(minutes=(minutes_since_start // 5) * 5)
            buckets[period_start].append(bar)

        if not buckets:
            continue

        rows = []
        for period_start in sorted(buckets):
            bucket = buckets[period_start]
            rows.append({
                "timestamp": period_start,
                "Open": bucket[0].open,
                "High": max(b.high for b in bucket),
                "Low": min(b.low for b in bucket),
                "Close": bucket[-1].close,
                "Volume": sum(b.volume for b in bucket),
            })
        df = pd.DataFrame(rows).set_index("timestamp")
        result[ticker] = df
    return result


class AlpacaCacheFeedClient:
    """
    MarketDataClient that uses the Alpaca bar cache for warmup/scoring and the
    BarBroadcaster Unix socket for live bar delivery.

    warmup() uses multi-day Alpaca daily bars (clipped to day before replay date).
    fetch_bars() aggregates 1-min CSV bars into 5-min bars for the OR catchup.
    subscribe_bars/start/stop delegate to LocalTSBroadcastMarketDataClient.
    """

    def __init__(self, socket_path: str, one_min_bars: list, replay_date):
        from alpha_tech_tracker.trade_api.local_ts_broadcast.market_data_client import (
            LocalTSBroadcastMarketDataClient,
        )
        self._local = LocalTSBroadcastMarketDataClient(None, socket_path=socket_path)
        self._one_min_bars = one_min_bars
        self._replay_date = replay_date

    def warmup(self, tickers: list, start_dt, end_dt) -> dict:
        from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import fetch_bars
        from alpha_tech_tracker.trade_api.alpaca_client.client import DataFeed
        # Always clip to the day before the replay date so the history never
        # contains same-day intraday bars (which block OR catchup injection).
        end_date = self._replay_date - timedelta(days=1)
        return fetch_bars(tickers, start_dt.date(), end_date, source="alpaca", feed=DataFeed.SIP)

    def fetch_bars(self, tickers: list, start_dt, end_dt) -> dict:
        # Called by the OR catchup with an intraday time range (e.g. 09:30–09:45).
        # Aggregate the pre-loaded 1-min CSV bars into 5-min OHLCV DataFrames.
        return _aggregate_to_5min(self._one_min_bars, tickers, start_dt, end_dt)

    def subscribe_bars(self, callback, *tickers):
        self._local.subscribe_bars(callback, *tickers)

    def start(self):
        self._local.start()

    def stop(self):
        self._local.stop()

    def seconds_since_last_message(self) -> float:
        return self._local.seconds_since_last_message()


# ---------------------------------------------------------------------------
# Mock execution client
# ---------------------------------------------------------------------------

def _make_mock_alpaca_client(capital: float) -> MagicMock:
    client = MagicMock()
    client.get_accounts.return_value = {"buying_power": capital}
    client.get_stock_quote.return_value = {
        "QuoteResponse": {"QuoteData": [{"All": {"bid": 100.0, "ask": 101.0, "last": 100.5}}]}
    }
    return client


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def _available_dates() -> list:
    if not _LIVE_DATA_DIR.exists():
        return []
    return sorted(
        d.name for d in _LIVE_DATA_DIR.iterdir()
        if d.is_dir() and (d / f"{_DEFAULT_FEED}_AMD_1min.csv").exists()
    )


def _tickers_for_date(replay_date: date, feed: str = _DEFAULT_FEED) -> list:
    date_dir = _LIVE_DATA_DIR / str(replay_date)
    return sorted(
        f.stem.replace(f"{feed}_", "").replace("_1min", "")
        for f in date_dir.glob(f"{feed}_*_1min.csv")
    )


def _parse_args():
    available = _available_dates()
    default_date = available[-1] if available else "2026-04-08"
    parser = argparse.ArgumentParser(
        description="Integration test: BarBroadcaster → socket → trade engine (mock)",
    )
    parser.add_argument("--date", default=default_date,
                        help=f"Replay date YYYY-MM-DD (available: {available})")
    parser.add_argument("--tickers", nargs="+", default=None,
                        help="Tickers to broadcast (default: all with 1-min CSV for date)")
    parser.add_argument("--top", type=int, default=2,
                        help="Top-N tickers the engine will select (default: 2)")
    parser.add_argument("--capital", type=float, default=10_000.0,
                        help="Paper capital (default: 10000)")
    parser.add_argument("--speed", type=float, default=30.0,
                        help="Playback speed multiplier (default: 30×)")
    parser.add_argument("--window", default="09:30",
                        help="Opening window start time (default: 09:30)")
    parser.add_argument("--opening-bars", type=int, default=3,
                        help="Opening range bar count (default: 3 = 15-min OR)")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = _parse_args()
    replay_date = date.fromisoformat(args.date)

    tickers = args.tickers or _tickers_for_date(replay_date)
    if not tickers:
        logger.error("No 1-min CSV data found for %s in %s", replay_date, _LIVE_DATA_DIR)
        return

    logger.info(
        "Integration test — date=%s  tickers=%s  top=%d  capital=$%.0f  speed=%.0fx",
        replay_date, tickers, args.top, args.capital, args.speed,
    )

    socket_path = tempfile.mktemp(dir="/tmp", prefix="ts_integ_", suffix=".sock")

    from alpha_tech_tracker.op_momentum_strategy.replay import set_replay_clock, clear_replay_clock
    from alpha_tech_tracker.op_momentum_strategy.bar_broadcaster import BarBroadcaster
    from alpha_tech_tracker.op_momentum_strategy.trade_engine import OpMomentumTradeEngine
    from alpha_tech_tracker.op_momentum_strategy.models import WindowConfig

    # Pin clock to session open for engine initialisation.
    replay_open = ET.localize(
        datetime.combine(replay_date, datetime.strptime("09:30", "%H:%M").time())
    )
    set_replay_clock(lambda: replay_open)

    bars = _load_merged_bars(replay_date, tickers)
    bars_sent = [0]

    broadcaster = BarBroadcaster(MagicMock(), tickers, socket_path=socket_path)
    threading.Thread(
        target=_run_broadcaster,
        args=(broadcaster, bars, replay_date, args.speed, bars_sent),
        name="broadcaster",
        daemon=True,
    ).start()
    time.sleep(0.1)  # let socket bind before engine tries to connect

    market_data_client = AlpacaCacheFeedClient(
        socket_path=socket_path, one_min_bars=bars, replay_date=replay_date
    )
    engine = OpMomentumTradeEngine(
        alpaca_client=_make_mock_alpaca_client(args.capital),
        is_paper=True,
        mock_trade_execution=True,
        market_data_client=market_data_client,
        replay_capital=args.capital,
        top_n=args.top,
        trade_type="stock",
        windows=[
            WindowConfig(
                label="M1",
                opening_start=args.window,
                opening_bars=args.opening_bars,
                capital_fraction=1.0,
                is_sequential=False,
            )
        ],
        force_run=True,
    )

    try:
        engine.run(tickers_override=tickers)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        clear_replay_clock()
        broadcaster.stop()
        try:
            os.unlink(socket_path)
        except FileNotFoundError:
            pass

    logger.info(
        "Integration test complete — %d bars broadcast for %s on %s",
        bars_sent[0], tickers, replay_date,
    )


if __name__ == "__main__":
    main()
