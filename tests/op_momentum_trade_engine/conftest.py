from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock

import pandas as pd
import pytz

from alpha_tech_tracker.op_momentum_strategy.models import ActivePosition
from alpha_tech_tracker.op_momentum_strategy.signal_engine import LiveSignalEngine

ET = pytz.timezone("America/New_York")


def _D(x) -> Decimal:
    return Decimal(str(x))


def _make_alpaca_client():
    client = Mock()
    client._api_key = "test_key"
    client._secret_key = "test_secret"
    client._option_data_client = Mock()
    return client


def _make_active_position(
    signal="BULLISH",
    or_high=_D("105"),
    or_low=_D("95"),
    hard_stop_price=_D("103.5"),
    fallback_price=_D("103.0"),
):
    or_range = or_high - or_low
    return ActivePosition(
        ticker="NVDA",
        signal=signal,
        option_symbol="NVDA260328C00900000",
        entry_order_id="order-123",
        contracts=3,
        entry_stock_price=_D("104"),
        or_high=or_high,
        or_low=or_low,
        or_range=or_range,
        hard_stop_price=hard_stop_price,
        fallback_price=fallback_price,
    )


def _make_signal_engine_with_history(
    ticker: str, history_df: pd.DataFrame
) -> LiveSignalEngine:
    engine = LiveSignalEngine(
        tickers=[ticker],
        opening_bars=3,
        on_signal=None,
    )
    engine._history[ticker] = history_df
    return engine


def _make_mock_bars(ticker, highs, lows):
    bars = []
    for h, l in zip(highs, lows):
        bar = Mock()
        bar.symbol = ticker
        bar.high = h
        bar.low = l
        bar.open = (h + l) / 2.0
        bar.close = (h + l) / 2.0
        bar.volume = 1000.0
        bar.timestamp = datetime.now(ET)
        bars.append(bar)
    return bars


def _build_history_df(closes, ma20, ma50, ma200):
    today = datetime.now(ET).date()
    timestamps = [
        ET.localize(
            datetime.combine(today, datetime.min.time())
            + timedelta(hours=9, minutes=30 + i * 5)
        )
        for i in range(len(closes))
    ]
    df = pd.DataFrame(
        {
            "Open": closes,
            "High": [c + 1.0 for c in closes],
            "Low": [c - 1.0 for c in closes],
            "Close": closes,
            "Volume": [1000.0] * len(closes),
            "MA20": ma20,
            "MA50": ma50,
            "MA200": ma200,
        },
        index=timestamps,
    )
    return df


def _set_latest_bar(engine, ticker, close, ma50, ma20=None, high=None, low=None, open_=None):
    df = engine._history[ticker]
    new_ts = df.index[-1] + timedelta(minutes=5)
    new_row = df.iloc[-1].copy()
    new_row["Close"] = float(close)
    new_row["MA50"] = float(ma50)
    if ma20 is not None:
        new_row["MA20"] = float(ma20)
    if high is not None:
        new_row["High"] = float(high)
    if low is not None:
        new_row["Low"] = float(low)
    if open_ is not None:
        new_row["Open"] = float(open_)
    engine._history[ticker] = pd.concat(
        [df, pd.DataFrame([new_row], index=[new_ts])]
    )


def _make_option_quote(bid, ask):
    mid = (bid + ask) / 2
    return {"bid": bid, "ask": ask, "mid": mid}


def _make_stock_position(
    signal="BULLISH",
    or_high=_D("105"),
    or_low=_D("95"),
    hard_stop_price=_D("103.5"),
    fallback_price=_D("103.0"),
    shares=50,
):
    or_range = or_high - or_low
    return ActivePosition(
        ticker="NVDA",
        signal=signal,
        option_symbol="",
        entry_order_id="order-stk-1",
        contracts=0,
        entry_stock_price=_D("104"),
        or_high=or_high,
        or_low=or_low,
        or_range=or_range,
        hard_stop_price=hard_stop_price,
        fallback_price=fallback_price,
        trade_type="stock",
        shares=shares,
    )


def _make_closed_stock_position(signal, entry_mid, exit_mid, shares=10):
    pos = _make_stock_position(signal=signal, shares=shares)
    pos.is_closed = True
    pos.exit_reason = "trailing_stop_ma20"
    pos.entry_time = datetime.now(ET).replace(hour=9, minute=47)
    pos.exit_time = datetime.now(ET).replace(hour=10, minute=56)
    pos.simulated_entry_mid = _D(str(entry_mid))
    pos.simulated_exit_mid = _D(str(exit_mid))
    return pos


def _make_closed_position(signal, entry_mid, exit_mid, contracts=1):
    pos = _make_active_position(signal=signal)
    pos.is_closed = True
    pos.exit_reason = "trailing_stop_ma20"
    pos.entry_time = datetime.now(ET).replace(hour=9, minute=47)
    pos.exit_time = datetime.now(ET).replace(hour=10, minute=56)
    pos.simulated_entry_mid = _D(str(entry_mid))
    pos.simulated_exit_mid = _D(str(exit_mid))
    pos.contracts = contracts
    return pos
