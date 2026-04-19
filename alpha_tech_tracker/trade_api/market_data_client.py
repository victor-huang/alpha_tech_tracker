from abc import ABC, abstractmethod


class MarketDataClient(ABC):
    """
    Abstract interface for market data: historical bar warmup, real-time bar streaming,
    and catchup fetches.

    Callback contract for subscribe_bars: callback(bar) where bar has
        .symbol (str), .timestamp (tz-aware datetime),
        .open, .high, .low, .close, .volume (all float).
    Both Alpaca bar objects and _TSBar satisfy this contract.
    """

    @abstractmethod
    def warmup(self, tickers: list, start_dt, end_dt) -> dict:
        """
        Fetch historical 5-min bars for all tickers.
        Returns dict[symbol -> pd.DataFrame] with columns Open/High/Low/Close/Volume,
        DatetimeIndex in America/New_York timezone, market hours only (09:30–16:00).
        """

    @abstractmethod
    def fetch_bars(self, tickers: list, start_dt, end_dt) -> dict:
        """
        Fetch 5-min bars for a specific window (used for opening-range catchup).
        Same return shape as warmup().
        """

    @abstractmethod
    def subscribe_bars(self, callback, *tickers):
        """Register a sync callback(bar) to be called for each closed 1-min bar."""

    @abstractmethod
    def start(self):
        """Begin streaming. Called once after subscribe_bars()."""

    @abstractmethod
    def reconnect(self):
        """Tear down the active stream and restart without re-warmup."""

    @abstractmethod
    def stop(self):
        """Stop streaming."""
