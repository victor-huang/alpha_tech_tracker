import argparse
import csv
import logging
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

import pytz
from alpaca.data.enums import DataFeed

from alpha_tech_tracker.trade_api.execution_client import ExecutionClient

from .config import TICKERS
from .contract_selector import TimePremiumContractSelector
from .models import _D, _stock_bid_ask

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")

_MARKET_OPEN = (9, 30)
_MARKET_CLOSE = (16, 0)
_LIQUID_SPREAD_THRESHOLD = _D("15")  # spread_pct above which quote is considered wide
_CACHE_MAXLEN = 6                     # 6 × 5-min snapshots = 30-min window
_RECENT_TRADE_MAX_AGE_SECONDS = 1800  # last trade older than this is considered stale


@dataclass
class ContractSpec:
    symbol: str       # full OCC symbol, e.g. "TSLA260410C00280000"
    option_type: str  # "call" or "put"


def _parse_occ_symbol(symbol: str) -> dict:
    """
    Parse an OCC option symbol into its components.
    e.g. "TSLA260410C00280000" → {ticker, expiry, option_type, strike}
    """
    m = re.match(r"^([A-Z]+)(\d{2})(\d{2})(\d{2})([CP])(\d+)$", symbol)
    if not m:
        return {}
    ticker, yy, mm, dd, cp, strike_raw = m.groups()
    expiry = date(2000 + int(yy), int(mm), int(dd))
    days_to_expiry = (expiry - date.today()).days
    strike = Decimal(strike_raw) / Decimal("1000")
    return {
        "ticker": ticker,
        "expiry": expiry,
        "expiry_str": str(expiry),
        "option_type": "call" if cp == "C" else "put",
        "strike": strike,
        "days_to_expiry": max(days_to_expiry, 0),
    }


class TradeEngineStrikeSelector:
    """
    Selects CALL and PUT contracts for monitoring by delegating to any selector
    that implements select(ticker, signal, stock_price) -> OCC symbol.

    Pass any compatible selector (e.g. TimePremiumContractSelector,
    ITMOptionContractSelector) to match whichever strategy the trade engine uses.
    Any object with a select_contracts(ticker, stock_price) -> list[ContractSpec]
    interface can be passed directly to OptionPriceMonitor instead.
    """

    def __init__(self, selector):
        self._selector = selector

    def select_contracts(self, ticker: str, stock_price: Decimal) -> list:
        specs = []
        for signal, option_type in [("BULLISH", "call"), ("BEARISH", "put")]:
            try:
                symbol = self._selector.select(ticker, signal, float(stock_price))
                specs.append(ContractSpec(symbol=symbol, option_type=option_type))
            except Exception:
                logger.warning(
                    "Could not select %s contract for %s at price=%s",
                    option_type,
                    ticker,
                    stock_price,
                )
        return specs


class OptionPriceMonitor:
    """
    Two-role module:

    Role 1 — Background collector:
        Runs every `interval_seconds` during market hours.
        For each ticker, selects the relevant CALL and PUT contracts,
        fetches live quotes, computes intrinsic/time value stats,
        and appends rows to per-day per-ticker CSV files.

    Role 2 — Pricing advisor:
        get_fair_price() returns a fair limit price within bid/ask using
        intrinsic value as a floor and the in-memory snapshot cache to
        estimate a reasonable time premium when the spread is wide or
        the bid is stale.

    Usage (standalone collector):
        monitor = OptionPriceMonitor(client, tickers, output_dir)
        monitor.start()
        ...
        monitor.stop()

    Usage (advisor only, no CSV collection):
        monitor = OptionPriceMonitor(client, tickers, output_dir)
        fair_price = monitor.get_fair_price(ticker, option_symbol, option_type, stock_price)
    """

    def __init__(
        self,
        client: ExecutionClient,
        tickers: list,
        output_dir: str = "market_data/options_price_data",
        contract_selector=None,
        interval_seconds: int = 300,
        feed: DataFeed = DataFeed.IEX,
    ):
        self._client = client
        self._tickers = tickers
        self._output_dir = output_dir
        self._interval = interval_seconds
        self._feed = feed
        self._contract_selector = contract_selector or TradeEngineStrikeSelector(
            TimePremiumContractSelector(client)
        )
        self._cache: dict = {}   # {option_symbol: deque of stat dicts}
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Background collection
    # ------------------------------------------------------------------

    def start(self):
        """Start background snapshot collection in a daemon thread."""
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._collection_loop, daemon=True, name="OptionPriceMonitor"
        )
        self._thread.start()
        logger.info(
            "OptionPriceMonitor started — %d tickers, interval=%ds",
            len(self._tickers),
            self._interval,
        )

    def stop(self):
        """Signal the background thread to exit."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("OptionPriceMonitor stopped")

    def _collection_loop(self):
        while not self._stop_event.is_set():
            now = datetime.now(ET)
            if self._is_market_hours(now):
                try:
                    self._snapshot_all_tickers()
                except Exception:
                    logger.exception("Error during option price snapshot")
            self._stop_event.wait(timeout=self._interval)

    def _is_market_hours(self, now: datetime) -> bool:
        open_h, open_m = _MARKET_OPEN
        close_h, close_m = _MARKET_CLOSE
        t = (now.hour, now.minute)
        return (open_h, open_m) <= t < (close_h, close_m)

    def _snapshot_all_tickers(self):
        for ticker in self._tickers:
            try:
                self._snapshot_ticker(ticker)
            except Exception:
                logger.warning("Snapshot failed for %s", ticker, exc_info=True)

    def _snapshot_ticker(self, ticker: str):
        raw_quote = self._client.get_stock_quote(ticker, feed=self._feed)
        bid_f, ask_f = _stock_bid_ask(raw_quote)
        stock_price = _D(str((bid_f + ask_f) / 2))

        specs = self._contract_selector.select_contracts(ticker, stock_price)
        for spec in specs:
            row = self._fetch_stats(ticker, spec, stock_price)
            if row:
                self._update_cache(spec.symbol, row)
                self._write_row(ticker, spec, row)

    # ------------------------------------------------------------------
    # Stats computation
    # ------------------------------------------------------------------

    def _fetch_stats(
        self, ticker: str, spec: ContractSpec, stock_price: Decimal
    ) -> Optional[dict]:
        try:
            q = self._client.get_option_quote_by_occ(spec.symbol)
            bid = _D(str(q["bid"]))
            ask = _D(str(q["ask"]))
        except Exception:
            logger.warning("Could not fetch option quote for %s", spec.symbol)
            return None

        parsed = _parse_occ_symbol(spec.symbol)
        if not parsed:
            logger.warning("Could not parse OCC symbol: %s", spec.symbol)
            return None

        strike = parsed["strike"]
        days_to_expiry = parsed["days_to_expiry"]

        mid = (bid + ask) / _D("2")
        if spec.option_type == "call":
            intrinsic = max(_D("0"), stock_price - strike)
        else:
            intrinsic = max(_D("0"), strike - stock_price)

        spread = ask - bid
        spread_pct = (spread / mid * _D("100")) if mid > _D("0") else _D("0")
        bid_time_value = bid - intrinsic
        ask_time_value = ask - intrinsic
        mid_time_value = mid - intrinsic
        daily_theta = (
            (mid_time_value / _D(str(days_to_expiry))).quantize(
                _D("0.0001"), rounding=ROUND_HALF_UP
            )
            if days_to_expiry > 0
            else _D("0")
        )

        # Determine expiry type: weekly (Friday) vs monthly (3rd Friday)
        expiry = parsed["expiry"]
        expiry_type = "weekly" if expiry.weekday() == 4 and not _is_third_friday(expiry) else "monthly"

        # Fetch last trade to get a transaction-based time value estimate.
        # Use it only when the trade is recent (within _RECENT_TRADE_MAX_AGE_SECONDS).
        last_trade_price = None
        last_trade_timestamp = None
        last_trade_time_value = None
        try:
            trade = self._client.get_option_latest_trade_by_occ(spec.symbol)
            if trade is not None:
                last_trade_price = float(_D(str(trade["price"])).quantize(_D("0.01"), rounding=ROUND_HALF_UP))
                last_trade_timestamp = trade["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
                age_seconds = (datetime.now(trade["timestamp"].tzinfo) - trade["timestamp"]).total_seconds()
                if age_seconds <= _RECENT_TRADE_MAX_AGE_SECONDS:
                    last_trade_time_value = float(
                        max(_D("0"), _D(str(trade["price"])) - intrinsic).quantize(_D("0.01"), rounding=ROUND_HALF_UP)
                    )
        except Exception:
            logger.warning("Could not fetch last trade for %s", spec.symbol)

        best_time_value = last_trade_time_value if last_trade_time_value is not None else float(mid_time_value)

        q = _D("0.01")
        return {
            "timestamp": datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S"),
            "ticker": ticker,
            "option_type": spec.option_type,
            "option_symbol": spec.symbol,
            "strike": float(strike),
            "expiry": parsed["expiry_str"],
            "expiry_type": expiry_type,
            "days_to_expiry": days_to_expiry,
            "stock_price": float(stock_price.quantize(q, rounding=ROUND_HALF_UP)),
            "bid": float(bid.quantize(q, rounding=ROUND_HALF_UP)),
            "ask": float(ask.quantize(q, rounding=ROUND_HALF_UP)),
            "mid": float(mid.quantize(q, rounding=ROUND_HALF_UP)),
            "intrinsic_value": float(intrinsic.quantize(q, rounding=ROUND_HALF_UP)),
            "bid_time_value": float(bid_time_value.quantize(q, rounding=ROUND_HALF_UP)),
            "ask_time_value": float(ask_time_value.quantize(q, rounding=ROUND_HALF_UP)),
            "mid_time_value": float(mid_time_value.quantize(q, rounding=ROUND_HALF_UP)),
            "last_trade_price": last_trade_price,
            "last_trade_timestamp": last_trade_timestamp,
            "last_trade_time_value": last_trade_time_value,
            "best_time_value": best_time_value,
            "spread_pct": float(spread_pct.quantize(_D("0.01"), rounding=ROUND_HALF_UP)),
            "daily_theta_approx": float(daily_theta),
        }

    # ------------------------------------------------------------------
    # Pricing advisor
    # ------------------------------------------------------------------

    def get_fair_price(
        self,
        ticker: str,
        option_symbol: str,
        option_type: str,
        stock_price: Decimal,
        penny_pilot: bool = True,
    ) -> Decimal:
        """
        Return a fair limit price within bid/ask using the algorithm:
          1. Compute intrinsic value as price floor.
          2. If spread is liquid (≤15%) and bid ≥ intrinsic: use mid.
          3. If bid < intrinsic (stale): use intrinsic + median_time_value from cache.
          4. If spread is wide (>15%): use intrinsic + median_time_value from cache.
          5. Clamp result to [bid, ask].
        """
        try:
            q = self._client.get_option_quote_by_occ(option_symbol)
            bid = _D(str(q["bid"]))
            ask = _D(str(q["ask"]))
        except Exception:
            logger.warning(
                "get_fair_price: could not fetch quote for %s, returning mid fallback",
                option_symbol,
            )
            return _D("0")

        mid = (bid + ask) / _D("2")
        if mid <= _D("0"):
            return _D("0")

        parsed = _parse_occ_symbol(option_symbol)
        if not parsed:
            return _quantize_option_price(mid, penny_pilot=penny_pilot)

        stock_price = stock_price.quantize(_D("0.01"), rounding=ROUND_HALF_UP)
        strike = parsed["strike"]
        if option_type == "call":
            intrinsic = max(_D("0"), stock_price - strike)
        else:
            intrinsic = max(_D("0"), strike - stock_price)

        spread_pct = (ask - bid) / mid * _D("100")

        if spread_pct <= _LIQUID_SPREAD_THRESHOLD and bid >= intrinsic:
            fair = mid
            reason = "liquid"
        else:
            median_tv = self._median_time_value(option_symbol)
            if median_tv is None:
                # No cache yet: conservative estimate using 20% of spread
                median_tv = (ask - bid) * _D("0.20")
                reason = "no_cache"
            else:
                reason = "stale_bid" if bid < intrinsic else "wide_spread"
            fair = intrinsic + median_tv

        # Hard floor: never price a sell below intrinsic value.
        # Clamping to max(bid, ...) is intentionally avoided here — if the market
        # maker's bid is below intrinsic we want to sit above it, not follow it down.
        fair = max(fair, intrinsic)
        fair = min(ask, fair)   # cap at ask; resting limit above ask is not useful
        if fair < intrinsic:
            # Only reachable when ask itself is below intrinsic (entire quote mispriced).
            logger.warning(
                "get_fair_price %s: entire quote is below intrinsic"
                " (bid=%s ask=%s intrinsic=%s) — best available=%s",
                option_symbol,
                bid.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
                ask.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
                intrinsic.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
                fair.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
            )
        fair = _quantize_option_price(fair, penny_pilot=penny_pilot)
        logger.info(
            "get_fair_price %s: bid=%s ask=%s intrinsic=%s spread_pct=%s%% → fair=%s (%s)",
            option_symbol,
            float(bid),
            float(ask),
            float(intrinsic.quantize(_D("0.01"), rounding=ROUND_HALF_UP)),
            float(spread_pct.quantize(_D("0.1"), rounding=ROUND_HALF_UP)),
            float(fair),
            reason,
        )
        return fair

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def _update_cache(self, option_symbol: str, row: dict):
        if option_symbol not in self._cache:
            self._cache[option_symbol] = deque(maxlen=_CACHE_MAXLEN)
        self._cache[option_symbol].append(row)

    def _median_time_value(self, option_symbol: str) -> Optional[Decimal]:
        snapshots = self._cache.get(option_symbol)
        if not snapshots:
            return None
        values = sorted(max(_D("0"), _D(str(s["best_time_value"]))) for s in snapshots)
        n = len(values)
        if n % 2 == 1:
            return values[n // 2]
        return (values[n // 2 - 1] + values[n // 2]) / _D("2")

    # ------------------------------------------------------------------
    # CSV persistence
    # ------------------------------------------------------------------

    _CSV_FIELDS = [
        "timestamp", "ticker", "option_type", "option_symbol",
        "strike", "expiry", "expiry_type", "days_to_expiry",
        "stock_price", "bid", "ask", "mid",
        "intrinsic_value", "bid_time_value", "ask_time_value", "mid_time_value",
        "last_trade_price", "last_trade_timestamp", "last_trade_time_value", "best_time_value",
        "spread_pct", "daily_theta_approx",
    ]

    def _write_row(self, ticker: str, spec: ContractSpec, row: dict):
        today_str = datetime.now(ET).strftime("%Y-%m-%d")
        day_dir = os.path.join(self._output_dir, today_str)
        os.makedirs(day_dir, exist_ok=True)

        filename = f"{ticker}_{spec.option_type}.csv"
        filepath = os.path.join(day_dir, filename)
        is_new = not os.path.exists(filepath)

        with open(filepath, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self._CSV_FIELDS)
            if is_new:
                writer.writeheader()
            writer.writerow({k: row[k] for k in self._CSV_FIELDS})


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _quantize_option_price(price: Decimal, penny_pilot: bool = True) -> Decimal:
    """
    Round an option limit price to the exchange-standard tick increment.

    Penny Pilot Program (penny_pilot=True, default — all strategy pool tickers):
      < $3.00  → nearest $0.01
      ≥ $3.00  → nearest $0.05

    Standard non-pilot schedule (penny_pilot=False):
      < $3.00  → nearest $0.05
      ≥ $3.00  → nearest $0.10

    Pool tickers (TSLA, NVDA, META, AMD, COIN, PLTR, RH*, etc.) are on Penny
    Pilot.  Tickers not enrolled in the program must use penny_pilot=False.
    """
    if penny_pilot:
        tick = _D("0.01") if price < _D("3") else _D("0.05")
    else:
        tick = _D("0.05") if price < _D("3") else _D("0.10")
    return (price / tick).to_integral_value(rounding=ROUND_HALF_UP) * tick


def _is_third_friday(d: date) -> bool:
    """Return True if d is the 3rd Friday of its month (standard monthly expiry)."""
    if d.weekday() != 4:
        return False
    return 15 <= d.day <= 21


# ------------------------------------------------------------------
# Standalone CLI
# ------------------------------------------------------------------

def _parse_args():
    parser = argparse.ArgumentParser(
        description="Option price monitor — collect bid/ask/intrinsic stats every N seconds"
    )
    parser.add_argument(
        "--tickers", nargs="+", default=None,
        help="Tickers to monitor (default: DEFAULT_TICKERS from config)",
    )
    parser.add_argument(
        "--interval", type=int, default=300,
        help="Snapshot interval in seconds (default: 300)",
    )
    parser.add_argument(
        "--output-dir", type=str, default="market_data/options_price_data",
        help="Output directory for CSV files",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args()


if __name__ == "__main__":
    from .config import _load_config

    args = _parse_args()
    _load_config()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    from alpha_tech_tracker.trade_api.alpaca_client.client import AlpacaAPIClient

    tickers = args.tickers or TICKERS
    client = AlpacaAPIClient(is_paper_trading=True)

    monitor = OptionPriceMonitor(
        client=client,
        tickers=tickers,
        output_dir=args.output_dir,
        interval_seconds=args.interval,
    )
    monitor.start()
    print(f"Collecting option price data for {len(tickers)} tickers every {args.interval}s")
    print(f"Output: {args.output_dir}")
    print("Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        monitor.stop()
        print("Stopped.")
