"""
Driver script to validate TradeStation bar stream and historical bar fetch.

Tests:
  1. Fetch 1-min and 5-min historical bars for the first 3 default tickers
  2. Stream 1-min bars live for ALL default tickers; print each closed bar

Usage:
    PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
        python -m alpha_tech_tracker.trade_api.tradestation.ts_stream_driver

Requires config.json with valid tradestation_session tokens.
Run tradestation_auth.py first if needed:
    python -m alpha_tech_tracker.op_momentum_strategy.tradestation_auth --verify
"""

import logging
import signal
import sys
import threading
from datetime import datetime, timedelta, timezone

from alpha_tech_tracker.op_momentum_strategy.config import (
    _load_config,
    _TRADESTATION_SESSION_TOKENS,
    TRADESTATION_ENVIRONMENT,
)
from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector import DEFAULT_TICKERS
from alpha_tech_tracker.trade_api.tradestation.bar_stream import TradeStationBarStream
from alpha_tech_tracker.trade_api.tradestation.client import TradeStationAPIClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("ts_stream_driver")


def _build_client() -> TradeStationAPIClient:
    _load_config()
    client = TradeStationAPIClient(environment=TRADESTATION_ENVIRONMENT)
    client.restore_session(_TRADESTATION_SESSION_TOKENS)
    if not client.verify_session():
        logger.error("TradeStation session invalid — run tradestation_auth.py first")
        sys.exit(1)
    logger.info("TradeStation session OK (env=%s)", TRADESTATION_ENVIRONMENT)
    return client


def test_historical_bars(client: TradeStationAPIClient):
    logger.info("=" * 60)
    logger.info("HISTORICAL BAR FETCH TEST")
    logger.info("=" * 60)

    now_utc = datetime.now(tz=timezone.utc)
    # Use the most recent completed trading session: yesterday 09:30–16:00 ET
    # ET is UTC-4 (EDT) so 09:30 ET = 13:30 UTC, 16:00 ET = 20:00 UTC
    days_back = 1
    # Skip back further if today is Monday (look at Friday)
    if now_utc.weekday() == 0:
        days_back = 3
    session_date = (now_utc - timedelta(days=days_back)).date()
    start_utc = datetime(
        session_date.year, session_date.month, session_date.day,
        13, 30, tzinfo=timezone.utc
    )
    end_utc = datetime(
        session_date.year, session_date.month, session_date.day,
        20, 0, tzinfo=timezone.utc
    )

    logger.info("Session date: %s  (%s to %s UTC)", session_date, start_utc.time(), end_utc.time())
    logger.info("")

    test_tickers = DEFAULT_TICKERS[:3]
    all_ok = True

    for ticker in test_tickers:
        for interval, label in [(1, "1-min"), (5, "5-min")]:
            try:
                bars = client.get_historical_bars(
                    ticker, start_utc, end_utc, interval=interval
                )
            except Exception as e:
                logger.error("%s %s: FAILED — %s", ticker, label, e)
                all_ok = False
                continue

            if not bars:
                logger.warning("%s %s: 0 bars returned", ticker, label)
                all_ok = False
                continue

            logger.info(
                "%-6s %s: %3d bars  first=%s  last=%s  "
                "O=%.2f H=%.2f L=%.2f C=%.2f  vol=%d",
                ticker, label, len(bars),
                bars[0].timestamp.strftime("%H:%M"),
                bars[-1].timestamp.strftime("%H:%M"),
                bars[0].open, bars[0].high, bars[0].low, bars[0].close,
                int(bars[0].volume),
            )

    logger.info("")
    logger.info("Historical bar test: %s", "PASS" if all_ok else "FAIL")
    logger.info("")


def test_streaming(client: TradeStationAPIClient):
    logger.info("=" * 60)
    logger.info("LIVE BAR STREAM TEST")
    logger.info("Tickers (%d): %s", len(DEFAULT_TICKERS), DEFAULT_TICKERS)
    logger.info("Streaming 1-min bars — press Ctrl-C to stop")
    logger.info("(Outside market hours: only historical replay + heartbeats)")
    logger.info("=" * 60)

    bar_counts: dict = {t: 0 for t in DEFAULT_TICKERS}
    lock = threading.Lock()

    def on_bar(bar):
        with lock:
            bar_counts[bar.symbol] = bar_counts.get(bar.symbol, 0) + 1
            count = bar_counts[bar.symbol]
        logger.info(
            "BAR #%-3d  %-6s  %s  O=%.2f H=%.2f L=%.2f C=%.2f  vol=%d",
            count, bar.symbol,
            bar.timestamp.strftime("%Y-%m-%d %H:%M UTC"),
            bar.open, bar.high, bar.low, bar.close, int(bar.volume),
        )

    stream = TradeStationBarStream(client)
    stream.subscribe_bars(on_bar, *DEFAULT_TICKERS)

    def _shutdown(sig, frame):
        logger.info("")
        logger.info("Stopping stream...")
        stream.stop()
        with lock:
            counts = dict(sorted(bar_counts.items()))
        logger.info("Bars received per ticker: %s", counts)
        logger.info(
            "Tickers with 0 bars: %s",
            [t for t, c in counts.items() if c == 0],
        )
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    stream.run()


if __name__ == "__main__":
    client = _build_client()
    test_historical_bars(client)
    test_streaming(client)
