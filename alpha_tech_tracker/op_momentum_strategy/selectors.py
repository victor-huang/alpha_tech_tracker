"""Pre-market ticker selection for the OpMomentum trade engine.

`TickerSelector` ranks the pool by the rolling composite score;
`WinRateTickerSelector` ranks by trailing EOD win rate for `--selector win-rate`.
Both are independent of `OpMomentumTradeEngine` — extracted verbatim from
trade_engine.py, which re-exports them.
"""
import hashlib
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pytz
from alpaca.data.enums import DataFeed

from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import (
    compute_signals_with_backtest,
    fetch_bars,
)
from alpha_tech_tracker.op_momentum_strategy.direction_aware_selector import (
    DualSideFloorSuppressor,
    compute_directional_stats,
    rank_tickers_direction_aware,
)
from alpha_tech_tracker.op_momentum_strategy.regime_engine import (
    _rank_tickers_by_eod_win_rate,
)
from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector import (
    ROLLING_LOOKBACK_DAYS,
    select_top_n,
)

from .config import BEARISH_MA200, OPENING_BARS, OPENING_START_TIME, STOP_PCT
from .contract_selector import _is_nyse_holiday
from .replay import _now_et, is_replay_mode

logger = logging.getLogger(__name__)


def _next_trading_day(d: date) -> date:
    """Return the nearest future weekday that is not a NYSE holiday."""
    candidate = d + timedelta(days=1)
    while candidate.weekday() >= 5 or _is_nyse_holiday(candidate):
        candidate += timedelta(days=1)
    return candidate


def _trading_days_in_range(start: date, end: date) -> list:
    """Return all weekdays that are not NYSE holidays between start and end (inclusive)."""
    days = []
    d = start
    while d <= end:
        if d.weekday() < 5 and not _is_nyse_holiday(d):
            days.append(d)
        d += timedelta(days=1)
    return days

ET = pytz.timezone("America/New_York")


class TickerSelector:
    """
    Selects the top N tickers using the momentum selector's composite scoring.

    If called before the opening range closes, falls back to the previous trading
    day so the engine still gets a ranked list to watch.
    """

    def __init__(
        self,
        tickers: list,
        top_n: int,
        stop_pct: float = float(STOP_PCT),
        opening_start_time: str = OPENING_START_TIME,
        opening_bars: int = OPENING_BARS,
        lookback_days: int = ROLLING_LOOKBACK_DAYS,
        regime_filter: bool = False,
        regime_ma: int = 8,
        alpaca_feed: DataFeed = DataFeed.SIP,
        score_feed: DataFeed = None,
        market_data_client=None,
        or_bar_lookback: int = 3,
        trailing_ma: str = "ma20",
        max_loss_pct: Optional[float] = None,
        armed_ma20_exit: bool = False,
        ma_momentum_gate: bool = False,
        score_entry_weight: float = 0.50,
        score_avg_win_weight: float = 0.30,
        score_win_rate_weight: float = 0.0,
        score_rel_strength_weight: float = 0.0,
        score_ev_trend_weight: float = 0.0,
        normalize_or_by_adr: bool = False,
        min_pool_vote_to_trade: int = 0,
        ev_trend_days: int = 15,
        min_ev: float = 0.0,
        dynamic_ev_gate: bool = False,
        dg_mode: str = "percentile",
        dg_bull_threshold: int = 10,
        dg_bear_threshold: int = 5,
        dg_bull_exclude_pct: float = 0.10,
        dg_neutral_exclude_pct: float = 0.25,
        dg_bear_exclude_pct: float = 0.40,
        dg_bull_min_wr: float = 0.30,
        dg_neutral_min_wr: float = 0.33,
        dg_bear_min_wr: float = 0.38,
        dg_bull_min_wl: float = 1.3,
        dg_neutral_min_wl: float = 1.5,
        dg_bear_min_wl: float = 1.8,
        adaptive_lookback: bool = False,
        al_bull_threshold: int = 10,
        al_bear_threshold: int = 5,
        al_bull_days: int = 20,
        al_neutral_days: int = 60,
        al_bear_days: int = 90,
        direction_split_ev_gate: bool = False,
        ds_bull_min_ev: float = 0.0,
        ds_neutral_min_ev: float = 0.0,
        ds_bear_min_ev: float = 0.0,
    ):
        self._tickers = tickers
        self._top_n = top_n
        self._stop_pct = stop_pct
        self._opening_start_time = opening_start_time
        self._opening_bars = opening_bars
        self._lookback_days = lookback_days
        self._regime_filter = regime_filter
        self._regime_ma = regime_ma
        self._alpaca_feed = alpaca_feed
        self._score_feed = score_feed if score_feed is not None else alpaca_feed
        self._market_data_client = market_data_client
        self._or_bar_lookback = or_bar_lookback
        self._trailing_ma = trailing_ma
        self._max_loss_pct = max_loss_pct
        self._armed_ma20_exit = armed_ma20_exit
        self._ma_momentum_gate = ma_momentum_gate
        self._score_entry_weight = score_entry_weight
        self._score_avg_win_weight = score_avg_win_weight
        self._score_win_rate_weight = score_win_rate_weight
        self._score_rel_strength_weight = score_rel_strength_weight
        self._score_ev_trend_weight = score_ev_trend_weight
        self._normalize_or_by_adr = normalize_or_by_adr
        self._min_pool_vote_to_trade = min_pool_vote_to_trade
        self._ev_trend_days = ev_trend_days
        self._adaptive_lookback = adaptive_lookback
        self._al_bear_days = al_bear_days
        self._dynamic_ev_gate_kwargs = dict(
            min_ev=min_ev,
            dynamic_ev_gate=dynamic_ev_gate,
            dg_mode=dg_mode,
            dg_bull_threshold=dg_bull_threshold,
            dg_bear_threshold=dg_bear_threshold,
            dg_bull_exclude_pct=dg_bull_exclude_pct,
            dg_neutral_exclude_pct=dg_neutral_exclude_pct,
            dg_bear_exclude_pct=dg_bear_exclude_pct,
            dg_bull_min_wr=dg_bull_min_wr,
            dg_neutral_min_wr=dg_neutral_min_wr,
            dg_bear_min_wr=dg_bear_min_wr,
            dg_bull_min_wl=dg_bull_min_wl,
            dg_neutral_min_wl=dg_neutral_min_wl,
            dg_bear_min_wl=dg_bear_min_wl,
            adaptive_lookback=adaptive_lookback,
            al_bull_threshold=al_bull_threshold,
            al_bear_threshold=al_bear_threshold,
            al_bull_days=al_bull_days,
            al_neutral_days=al_neutral_days,
            al_bear_days=al_bear_days,
            direction_split_ev_gate=direction_split_ev_gate,
            ds_bull_min_ev=ds_bull_min_ev,
            ds_neutral_min_ev=ds_neutral_min_ev,
            ds_bear_min_ev=ds_bear_min_ev,
        )
        self.rolling_stats: dict = {}
        self.dynamic_ev_gate_state: Optional[dict] = None
        self.direction_split_ev_state: Optional[dict] = None
        self.scoring_context: dict = {}

    def _selector_cache_path(self, target_date: date) -> Path:
        tickers_hash = hashlib.md5(",".join(sorted(self._tickers)).encode()).hexdigest()[:8]
        cache_dir = Path(__file__).parent.parent.parent / "market_data" / "cache"
        fname = (
            f"selector_{target_date}"
            f"_{self._opening_start_time.replace(':', '')}"
            f"_{self._opening_bars}bar"
            f"_lk{self._lookback_days}"
            f"_reg{int(self._regime_filter)}{self._regime_ma}"
            f"_stop{self._stop_pct}"
            f"_{tickers_hash}.json"
        )
        return cache_dir / fname

    def fetch_bars(self) -> dict:
        """Fetch and return bar data without running the selector. Can be passed to select()."""
        today = _now_et().date()
        _eff_lookback = max(self._lookback_days, 30)
        if self._adaptive_lookback:
            _eff_lookback = max(_eff_lookback, self._al_bear_days)
        fetch_start = today - timedelta(days=_eff_lookback + 5)
        bars_end = today - timedelta(days=1)
        if self._market_data_client is not None:
            return fetch_bars(
                self._tickers,
                fetch_start,
                bars_end,
                source="tradestation",
                market_data_client=self._market_data_client,
            )
        return fetch_bars(
            self._tickers,
            fetch_start,
            bars_end,
            source="alpaca",
            feed=self._score_feed,
        )

    def select(self, ticker_dfs: dict = None, direction: str = "LONG") -> list:
        today = _now_et().date()
        if ticker_dfs is None:
            ticker_dfs = self.fetch_bars()

        source = "tradestation" if self._market_data_client is not None else "alpaca"

        _scoring_kwargs = dict(
            score_entry_weight=self._score_entry_weight,
            score_avg_win_weight=self._score_avg_win_weight,
            score_win_rate_weight=self._score_win_rate_weight,
            score_rel_strength_weight=self._score_rel_strength_weight,
            score_ev_trend_weight=self._score_ev_trend_weight,
            normalize_or_by_adr=self._normalize_or_by_adr,
            min_pool_vote_to_trade=self._min_pool_vote_to_trade,
            ev_trend_days=self._ev_trend_days,
            ma_momentum_gate=self._ma_momentum_gate,
            **self._dynamic_ev_gate_kwargs,
        )

        if is_replay_mode():
            # In replay mode, recompute selector scores fresh using the replay
            # date as target_date so the 60-day lookback matches the backtest.
            logger.info("Replay mode: computing fresh selector scores for %s (%s/%dbar)", today, self._opening_start_time, self._opening_bars)
            result = select_top_n(
                n=self._top_n,
                tickers=self._tickers,
                lookback_days=self._lookback_days,
                opening_bars=self._opening_bars,
                bearish_ma200=BEARISH_MA200,
                stop_pct=self._stop_pct,
                source=source,
                target_date=today,
                ticker_dfs=ticker_dfs,
                opening_start_time=self._opening_start_time,
                regime_filter=self._regime_filter,
                regime_ma=self._regime_ma,
                or_bar_lookback=self._or_bar_lookback,
                trailing_ma=self._trailing_ma,
                max_loss_pct=self._max_loss_pct,
                armed_ma20_exit=self._armed_ma20_exit,
                feed=self._score_feed,
                **_scoring_kwargs,
            )
            picks = result["picks"]
        else:
            result = select_top_n(
                n=self._top_n,
                tickers=self._tickers,
                lookback_days=self._lookback_days,
                opening_bars=self._opening_bars,
                bearish_ma200=BEARISH_MA200,
                stop_pct=self._stop_pct,
                source=source,
                target_date=today,
                ticker_dfs=ticker_dfs,
                opening_start_time=self._opening_start_time,
                regime_filter=self._regime_filter,
                regime_ma=self._regime_ma,
                or_bar_lookback=self._or_bar_lookback,
                trailing_ma=self._trailing_ma,
                max_loss_pct=self._max_loss_pct,
                armed_ma20_exit=self._armed_ma20_exit,
                feed=self._score_feed,
                **_scoring_kwargs,
            )
            picks = result["picks"]

            if not picks:
                prev_day = today - timedelta(days=1)
                while prev_day.weekday() >= 5:
                    prev_day -= timedelta(days=1)
                logger.info(
                    "No picks for today (%s) — falling back to %s for pre-market selection",
                    today,
                    prev_day,
                )
                result = select_top_n(
                    n=self._top_n,
                    tickers=self._tickers,
                    lookback_days=self._lookback_days,
                    opening_bars=self._opening_bars,
                    bearish_ma200=BEARISH_MA200,
                    stop_pct=self._stop_pct,
                    source=source,
                    target_date=prev_day,
                    ticker_dfs=ticker_dfs,
                    opening_start_time=self._opening_start_time,
                    regime_filter=self._regime_filter,
                    regime_ma=self._regime_ma,
                    or_bar_lookback=self._or_bar_lookback,
                    trailing_ma=self._trailing_ma,
                    max_loss_pct=self._max_loss_pct,
                    armed_ma20_exit=self._armed_ma20_exit,
                    feed=self._score_feed,
                    **_scoring_kwargs,
                )
                picks = result["picks"]

        self.rolling_stats = result.get("rolling_stats", {})
        self.dynamic_ev_gate_state = result.get("dynamic_ev_gate")
        self.direction_split_ev_state = result.get("direction_split_ev")
        self.scoring_context = result.get("scoring_context", {})
        selected = [p["ticker"] for p in picks]
        logger.info(
            "Selector picks: %s | no_signal: %s | negative_ev: %s",
            [{p["ticker"]: f"score={p['score']} ev={p['ev_trade']}%"} for p in picks],
            result.get("no_signal", []),
            result.get("negative_ev", []),
        )
        return selected


_HOLD_WINDOW_MINUTES: dict = {
    "+15m": 15, "+30m": 30, "+1h": 60,
    "+2h": 120, "+3h": 180, "+5h": 300, "EOD": None,
}


class WinRateTickerSelector:
    """
    Selects tickers by historical EOD win rate instead of composite score.
    LONG direction → top-N. SHORT direction → bottom-N (worst-first).

    When direction_aware=True (--direction-aware-scoring flag), uses signal-based
    directional win rates instead of hold-based EOD win rates.  Each ticker is
    ranked by direction_score = WR * (1 + avg_win_pct * 2) computed from the
    trailing 90-day bull (LONG) or bear (SHORT) signal history.

    Duck-typed with TickerSelector: exposes fetch_bars(), select(), and the
    same stat attrs so _run_window_selectors works identically for both.
    rolling_stats is populated with sentinel ev_trade=1.0 for each picked
    ticker so the drain's EV gate passes without filtering any picks.
    """

    _DIRECTION_AWARE_LOOKBACK_DAYS = 90
    _DIRECTION_AWARE_MIN_TRADES = 10
    _DIRECTION_AWARE_MIN_POOL_VALID = 3

    def __init__(
        self,
        tickers: list,
        top_n: int,
        or_start: str = OPENING_START_TIME,
        or_bars: int = OPENING_BARS,
        lookback_days: int = 20,
        alpaca_feed=None,
        score_feed=None,
        market_data_client=None,
        direction_aware: bool = False,
    ):
        self._tickers = tickers
        self._top_n = top_n
        self._or_start = or_start
        self._or_bars = or_bars
        self._lookback_days = lookback_days
        self._alpaca_feed = alpaca_feed or DataFeed.SIP
        self._score_feed = score_feed or self._alpaca_feed
        self._market_data_client = market_data_client
        self._direction_aware = direction_aware
        self.rolling_stats: dict = {}
        self.dynamic_ev_gate_state = None
        self.direction_split_ev_state = None
        self.scoring_context: dict = {}
        self._suppressor = DualSideFloorSuppressor() if direction_aware else None

    def fetch_bars(self) -> dict:
        today = _now_et().date()
        fetch_start = today - timedelta(days=self._lookback_days + 5)
        bars_end = today - timedelta(days=1)
        if self._market_data_client is not None:
            return fetch_bars(
                self._tickers, fetch_start, bars_end,
                source="tradestation", market_data_client=self._market_data_client,
            )
        return fetch_bars(
            self._tickers, fetch_start, bars_end,
            source="alpaca", feed=self._score_feed,
        )

    def _fetch_bars_direction_aware(self) -> dict:
        today = _now_et().date()
        fetch_start = today - timedelta(days=self._DIRECTION_AWARE_LOOKBACK_DAYS + 5)
        bars_end = today - timedelta(days=1)
        if self._market_data_client is not None:
            return fetch_bars(
                self._tickers, fetch_start, bars_end,
                source="tradestation", market_data_client=self._market_data_client,
            )
        return fetch_bars(
            self._tickers, fetch_start, bars_end,
            source="alpaca", feed=self._score_feed,
        )

    def _rank_direction_aware(self, ticker_dfs: dict, direction: str, today: date) -> list:
        long_window_dfs = self._fetch_bars_direction_aware()
        ticker_stats = {}
        for ticker, df in long_window_dfs.items():
            if df.empty:
                continue
            signals_df = compute_signals_with_backtest(
                df, self._or_bars, opening_start_time=self._or_start
            )
            if signals_df.empty:
                continue
            primary_df = signals_df[
                ~signals_df.get("is_reversal", False).astype(bool)
                & ~signals_df.get("is_bearish_reentry", False).astype(bool)
                & ~signals_df.get("is_bullish_reentry", False).astype(bool)
            ] if "is_reversal" in signals_df.columns else signals_df

            stats = compute_directional_stats(
                primary_df,
                target_date=today,
                lookback_days=self._DIRECTION_AWARE_LOOKBACK_DAYS,
                min_trades=self._DIRECTION_AWARE_MIN_TRADES,
            )

            if self._suppressor is not None:
                bull_wr = stats["bull"]["wr"] if stats["bull"] else 0.0
                bear_wr = stats["bear"]["wr"] if stats["bear"] else 0.0
                self._suppressor.update(ticker, bull_wr, bear_wr, today)
                if self._suppressor.is_suppressed(ticker, direction="LONG", as_of=today):
                    stats["bull"] = None
                if self._suppressor.is_suppressed(ticker, direction="SHORT", as_of=today):
                    stats["bear"] = None

            ticker_stats[ticker] = stats

        overall_wr = {
            ticker: (
                stats["bull"]["wr"] if stats.get("bull") else
                stats["bear"]["wr"] if stats.get("bear") else 0.0
            )
            for ticker, stats in ticker_stats.items()
        }
        ranked = rank_tickers_direction_aware(
            ticker_stats,
            direction=direction,
            min_pool_valid=self._DIRECTION_AWARE_MIN_POOL_VALID,
            fallback_overall_wr=overall_wr,
        )
        return [t for t, _ in ranked]

    def select(self, ticker_dfs: dict = None, direction: str = "LONG") -> list:
        if ticker_dfs is None:
            ticker_dfs = self.fetch_bars()

        today = _now_et().date()
        if self._direction_aware and direction in ("LONG", "SHORT"):
            picks = self._rank_direction_aware(ticker_dfs, direction, today)[:self._top_n]
        else:
            # CAUTION / NEUTRAL / non-directional: fall back to overall EOD WR ranking.
            ranked = _rank_tickers_by_eod_win_rate(
                ticker_dfs, today, self._or_start, self._or_bars, self._lookback_days
            )
            if direction == "SHORT":
                picks = [t for t, _ in list(reversed(ranked[-self._top_n:]))]
            else:
                picks = [t for t, _ in ranked[:self._top_n]]

        # Populate rolling_stats so the signal drain can gate and score picks.
        # ev_trade=1.0 ensures every pick passes the default min_ev=0.0 gate;
        # avg_win_pct/win_rate=0.0 lets the drain rank purely by entry position.
        self.rolling_stats = {
            ticker: {"ev_trade": 1.0, "avg_win_pct": 0.0, "win_rate": 0.0}
            for ticker in picks
        }
        logger.info(
            "WinRateTickerSelector [%s%s] top-%d: %s",
            direction,
            " dir-aware" if self._direction_aware else "",
            self._top_n,
            picks,
        )
        return picks
