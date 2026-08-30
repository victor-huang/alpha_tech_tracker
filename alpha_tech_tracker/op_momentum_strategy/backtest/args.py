"""Argument parsing for the selector backtest CLI.

The parser definition is extracted verbatim from op_momentum_selector_backtest.py.

Two pre-existing defects are fixed here because the move forces the scoping to be
made explicit:

1. `__main__` called `parser.error(...)` in four places, but `parser` was a local
   inside `_parse_args` and was never a module global — every one of those
   validation paths raised `NameError: name 'parser' is not defined` instead of a
   clean usage message. `arg_error()` now provides that entry point.
2. An unescaped `%` in the --doubledown help text made `--help` itself crash with
   `ValueError: unsupported format character`.
"""
import argparse

from ..op_momentum_selector import (
    OPENING_BARS,
    OPENING_START_TIME,
    ROLLING_LOOKBACK_DAYS,
    STOP_PCT,
)
from .constants import DOUBLEDOWN_START_MIN, INITIAL_CAPITAL, MIN_WINDOW_CAPITAL

_PARSER = None


def arg_error(message: str):
    """Report a post-parse validation failure the way argparse would.

    Prints usage plus `message` to stderr and exits with status 2.
    """
    parser = _PARSER if _PARSER is not None else build_parser()
    parser.error(message)


def build_parser() -> argparse.ArgumentParser:
    """Construct (and memoize) the backtest argument parser."""
    parser = argparse.ArgumentParser(
        description="Backtest the op_momentum selector algorithm"
    )
    parser.add_argument(
        "--start", type=str, required=True, help="Eval start date YYYY-MM-DD"
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="Eval end date YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--top", type=int, default=3, help="Top-N picks per day (default: 3)"
    )
    parser.add_argument(
        "--tickers", nargs="+", default=None, help="Override default ticker list"
    )
    parser.add_argument(
        "--ticker-set",
        choices=["V3", "AT"],
        default=None,
        help="Named ticker set: V3 (default pool) or AT (ACTIVELY_TRADE_TICKERS)",
    )
    parser.add_argument(
        "--lookback",
        type=int,
        default=ROLLING_LOOKBACK_DAYS,
        help=f"Rolling lookback in calendar days (default: {ROLLING_LOOKBACK_DAYS})",
    )
    parser.add_argument(
        "--stop-pct",
        type=float,
        default=STOP_PCT,
        help=f"Hard stop as fraction of OR range (default: {STOP_PCT})",
    )
    parser.add_argument(
        "--source",
        choices=["alpaca", "yfinance"],
        default="alpaca",
        help="Market data source (default: alpaca)",
    )
    parser.add_argument(
        "--feed",
        choices=["iex", "sip"],
        default="sip",
        help="Alpaca data feed: 'sip' (consolidated, default) or 'iex' (free tier)",
    )
    parser.add_argument(
        "--bearish-ma200",
        action="store_true",
        default=False,
        help="Require price < MA200 for bearish signal",
    )
    parser.add_argument(
        "--ma-momentum-gate",
        action="store_true",
        default=False,
        dest="ma_momentum_gate",
        help=(
            "Gate signals on MA alignment. "
            "BULLISH: OR range must overlap or be above both 5-min MA20 and MA50, "
            "and the last OR bar must close above MA20 or MA50. "
            "BEARISH (mirror): OR range must overlap or be below both MAs, "
            "and the last OR bar must close below MA20."
        ),
    )
    parser.add_argument(
        "--ma-momentum-gate-in-scoring",
        action="store_true",
        default=False,
        dest="ma_momentum_gate_in_scoring",
        help=(
            "Apply the MA momentum gate at the selector scoring step (score=0 if gate fails), "
            "rather than filtering signals out of the backtest pool. "
            "Tickers that fail the gate are skipped by the top-N ranker but their signals "
            "remain visible in all_window_results. Same alignment rules as --ma-momentum-gate."
        ),
    )
    parser.add_argument(
        "--opening-bars",
        type=int,
        default=OPENING_BARS,
        help=f"Number of 5-min bars in opening period (default: {OPENING_BARS}). "
        "Used only when --window is not specified.",
    )
    parser.add_argument(
        "--opening-start",
        type=str,
        default=OPENING_START_TIME,
        help=f"Opening window start time HH:MM ET (default: {OPENING_START_TIME}). "
        "Used only when --window is not specified.",
    )
    parser.add_argument(
        "--window",
        action="append",
        nargs="+",
        metavar="PARAM",
        default=None,
        help="Define a trading window: LABEL START BARS [CLOSE_TOP_PCT] (e.g. M1 09:30 3 or A1 13:15 1 0.05). "
        "CLOSE_TOP_PCT is optional: if provided, BULLISH only when close >= OR_high - PCT*OR_range, "
        "BEARISH only when close <= OR_low + PCT*OR_range (overrides --close-top-pct for this window). "
        "Repeat to add multiple windows. When specified, overrides --opening-start/--opening-bars.",
    )
    parser.add_argument(
        "--window-ma-switch",
        action="append",
        nargs="+",
        metavar="PARAM",
        default=None,
        dest="window_ma_switch",
        help="Per-window trailing MA switch override: LABEL MODE [PERIOD] "
        "(e.g. --window-ma-switch A1 after-arm 8). "
        "MODE is one of: none, after-arm, after-target. "
        "PERIOD defaults to --trailing-ma-switch-period if omitted. "
        "Repeat to configure multiple windows.",
    )
    parser.add_argument(
        "--morning-split",
        nargs="+",
        type=float,
        default=None,
        help="Per-window split for the first (simultaneous) group as percentages, e.g. --morning-split 60 40. "
        "Must sum to ≤ 100. The number of values determines how many leading windows are simultaneous. "
        "Remaining windows run sequentially, each inheriting all returned capital. "
        "Default: single window gets 100%% of portfolio.",
    )
    parser.add_argument(
        "--min-window-capital",
        type=float,
        default=MIN_WINDOW_CAPITAL,
        help=f"Minimum capital required to execute a window (default: ${MIN_WINDOW_CAPITAL:.0f}). "
        "Windows with less available capital are skipped.",
    )
    parser.add_argument(
        "--show-execution-log",
        action="store_true",
        default=False,
        help="Print the window execution log showing which windows ran or were skipped each day. Default: off.",
    )
    parser.add_argument(
        "--csv-out",
        type=str,
        default=None,
        dest="csv_out",
        help="Write all non-skipped trade rows to a CSV file at this path.",
    )
    parser.add_argument(
        "--compound",
        action="store_true",
        default=False,
        help="Compound capital across days (portfolio carries over). "
        "Default: reset to initial capital each day for clean per-day strategy evaluation.",
    )
    parser.add_argument(
        "--fixed-signal-alloc",
        action="store_true",
        default=False,
        dest="fixed_signal_alloc",
        help="Fixed capital per signal slot (capital / top-N) regardless of how many signals "
        "fire. Idle capital stays undeployed on low-signal days; total deployed scales with "
        "signal count up to top-N × capital. Default: off (full capital always deployed).",
    )
    parser.add_argument(
        "--dedup",
        action="store_true",
        default=False,
        help="Skip a ticker in later windows if already picked by an earlier window that day.",
    )
    parser.add_argument(
        "--trailing-ma",
        choices=["ma20", "ma50", "both", "none"],
        default="ma20",
        help="Trailing MA stop to use once MA is above hard stop, or none to disable (default: ma20).",
    )
    parser.add_argument(
        "--trailing-ma-switch",
        choices=["none", "after-arm", "after-target"],
        default="none",
        dest="trailing_ma_switch",
        help="Upgrade trailing stop to a faster MA once a profit threshold is reached. "
        "after-arm: upgrade when price moves 1x OR range past entry. "
        "after-target: upgrade at factor x OR range (see --trailing-ma-switch-factor). "
        "Default: none.",
    )
    parser.add_argument(
        "--trailing-ma-switch-period",
        type=int,
        default=8,
        dest="trailing_ma_switch_period",
        help="Period of the fast MA used after the switch threshold is hit (default: 8). "
        "Common choices: 5, 8, 10. Only applies when --trailing-ma-switch is not none.",
    )
    parser.add_argument(
        "--trailing-ma-switch-factor",
        type=float,
        default=1.0,
        dest="trailing_ma_switch_factor",
        help="OR-range multiplier for --trailing-ma-switch after-target (default: 1.0).",
    )
    parser.add_argument(
        "--max-loss-pct",
        type=float,
        default=None,
        help="Per-trade max loss as a fraction of entry price (e.g. 0.02 = 2%%). Default: disabled.",
    )
    parser.add_argument(
        "--min-hold-bars",
        type=int,
        default=0,
        dest="min_hold_bars",
        help="Minimum bars to hold before fallback/hard-stop exits can fire (e.g. 3 = 15 min). "
        "max-loss-pct still exits immediately. Default: 0 (disabled).",
    )
    parser.add_argument(
        "--oracle-picks",
        action="store_true",
        default=False,
        dest="oracle_picks",
        help="Replace scoring with perfect-hindsight selection: pick top-N by actual realized P&L each day. "
        "No EV gate — includes all tickers with a valid signal. Shows theoretical maximum return.",
    )
    parser.add_argument(
        "--random-picks",
        action="store_true",
        default=False,
        dest="random_picks",
        help="Replace scoring with random selection from EV-positive tickers. "
        "Use as a baseline to measure how much the scoring formula contributes.",
    )
    parser.add_argument(
        "--random-seed",
        type=int,
        default=None,
        dest="random_seed",
        help="Seed for --random-picks to make runs reproducible. Default: None (different each run).",
    )
    parser.add_argument(
        "--dynamic-ev-gate",
        action="store_true",
        default=True,
        dest="dynamic_ev_gate",
        help="Apply regime-adaptive EV filter based on daily pool vote (default: on). "
        "Mode 'percentile' (default): exclude bottom N%% of pool by EV, adapts with market. "
        "Mode 'threshold': fixed WR/W/L floors per regime tier.",
    )
    parser.add_argument(
        "--no-dynamic-ev-gate",
        action="store_false",
        dest="dynamic_ev_gate",
        help="Disable the regime-adaptive EV filter (reverts to baseline behavior).",
    )
    parser.add_argument(
        "--dg-mode",
        type=str,
        default="percentile",
        choices=["percentile", "threshold"],
        dest="dg_mode",
        help="Gate mode for --dynamic-ev-gate. 'percentile': pool-relative EV floor (recommended). "
        "'threshold': fixed absolute WR/W/L floors. Default: percentile.",
    )
    parser.add_argument("--dg-bull-threshold", type=int, default=10, dest="dg_bull_threshold",
                        help="Pool vote count at or above which bull-regime thresholds apply. Default: 10.")
    parser.add_argument("--dg-bear-threshold", type=int, default=5, dest="dg_bear_threshold",
                        help="Pool vote count at or below which bear-regime thresholds apply. Default: 5.")
    parser.add_argument("--dg-bull-exclude-pct", type=float, default=0.10, dest="dg_bull_exclude_pct",
                        help="[percentile mode] Fraction of pool to exclude from bottom in bull regime. Default: 0.10.")
    parser.add_argument("--dg-neutral-exclude-pct", type=float, default=0.25, dest="dg_neutral_exclude_pct",
                        help="[percentile mode] Fraction of pool to exclude from bottom in neutral regime. Default: 0.25.")
    parser.add_argument("--dg-bear-exclude-pct", type=float, default=0.40, dest="dg_bear_exclude_pct",
                        help="[percentile mode] Fraction of pool to exclude from bottom in bear regime. Default: 0.40.")
    parser.add_argument("--dg-bull-min-wr", type=float, default=0.30, dest="dg_bull_min_wr",
                        help="[threshold mode] Minimum win rate in bull regime. Default: 0.30.")
    parser.add_argument("--dg-neutral-min-wr", type=float, default=0.33, dest="dg_neutral_min_wr",
                        help="[threshold mode] Minimum win rate in neutral regime. Default: 0.33.")
    parser.add_argument("--dg-bear-min-wr", type=float, default=0.38, dest="dg_bear_min_wr",
                        help="[threshold mode] Minimum win rate in bear regime. Default: 0.38.")
    parser.add_argument("--dg-bull-min-wl", type=float, default=1.3, dest="dg_bull_min_wl",
                        help="[threshold mode] Minimum W/L ratio in bull regime. Default: 1.3.")
    parser.add_argument("--dg-neutral-min-wl", type=float, default=1.5, dest="dg_neutral_min_wl",
                        help="[threshold mode] Minimum W/L ratio in neutral regime. Default: 1.5.")
    parser.add_argument("--dg-bear-min-wl", type=float, default=1.8, dest="dg_bear_min_wl",
                        help="[threshold mode] Minimum W/L ratio in bear regime. Default: 1.8.")
    parser.add_argument(
        "--adaptive-lookback",
        action="store_true",
        default=True,
        dest="adaptive_lookback",
        help="Shorten lookback window in bull regimes (more responsive) and lengthen in bear regimes "
        "(require more evidence). Uses same pool-vote signal as --dynamic-ev-gate (default: on).",
    )
    parser.add_argument(
        "--no-adaptive-lookback",
        action="store_false",
        dest="adaptive_lookback",
        help="Disable adaptive lookback (uses fixed --lookback window for all regimes).",
    )
    parser.add_argument("--al-bull-threshold", type=int, default=10, dest="al_bull_threshold",
                        help="Pool vote count for bull regime in adaptive lookback. Default: 10.")
    parser.add_argument("--al-bear-threshold", type=int, default=5, dest="al_bear_threshold",
                        help="Pool vote count for bear regime in adaptive lookback. Default: 5.")
    parser.add_argument("--al-bull-days", type=int, default=20, dest="al_bull_days",
                        help="Lookback days in bull regime. Default: 20.")
    parser.add_argument("--al-neutral-days", type=int, default=60, dest="al_neutral_days",
                        help="Lookback days in neutral regime. Default: 60.")
    parser.add_argument("--al-bear-days", type=int, default=90, dest="al_bear_days",
                        help="Lookback days in bear regime. Default: 90.")
    parser.add_argument(
        "--stale-cut-mins",
        type=int,
        default=0,
        dest="stale_cut_mins",
        help="Exit flat trades at this many minutes after entry if |P&L| < --stale-cut-threshold. "
        "E.g. 30 means check at the 30-min bar. Default: 0 (disabled).",
    )
    parser.add_argument(
        "--stale-cut-threshold",
        type=float,
        default=0.0,
        dest="stale_cut_threshold",
        help="P&L threshold (as %% of entry) for stale-cut. Trade is cut if |P&L| < threshold "
        "at --stale-cut-mins. E.g. 0.25 means exit if within ±0.25%% of entry. Default: 0.0 (disabled).",
    )
    parser.add_argument(
        "--armed-ma20-exit",
        action="store_true",
        default=False,
        help="Once hard stop is armed, use MA20 as the trailing exit. Default: off.",
    )
    parser.add_argument(
        "--regime-filter",
        action="store_true",
        default=False,
        help="Skip BULLISH signals on days when QQQ close is below its N-day MA. Default: off.",
    )
    parser.add_argument(
        "--regime-ma",
        type=int,
        default=5,
        help="N-day MA period for QQQ regime filter (default: 5).",
    )
    parser.add_argument(
        "--qqq-align-filter",
        action="store_true",
        default=False,
        dest="qqq_align_filter",
        help="Skip entries where QQQ's OR close position contradicts the signal direction. "
        "BULLISH skipped when QQQ OR_cpos <= threshold; BEARISH skipped when QQQ OR_cpos > threshold. "
        "Uses same OR window as the individual stock — no lookahead bias. Default: off.",
    )
    parser.add_argument(
        "--qqq-align-threshold",
        type=float,
        default=0.50,
        dest="qqq_align_threshold",
        help="QQQ OR close position threshold for alignment filter (default: 0.50). "
        "BULL skipped if QQQ OR_cpos <= this value; BEAR skipped if QQQ OR_cpos > this value.",
    )
    parser.add_argument(
        "--qqq-extend-days",
        type=int,
        default=0,
        dest="qqq_extend_days",
        help="Gate the QQQ align filter to only fire when QQQ has risen too much too fast. "
        "N = rolling window of prior trading-day closes (e.g. 5). "
        "0 = disabled (filter fires on all days). Requires --qqq-align-filter.",
    )
    parser.add_argument(
        "--qqq-extend-pct",
        type=float,
        default=0.05,
        dest="qqq_extend_pct",
        help="Cumulative return threshold for the overextension gate (default: 0.05 = 5%%). "
        "Filter only activates if QQQ's N-day prior return exceeds this value.",
    )
    parser.add_argument(
        "--qqq-extend-max-dd",
        type=float,
        default=0.0,
        dest="qqq_extend_max_dd",
        help="Max single-day drawdown allowed in the N-day window (default: 0.0 = disabled). "
        "If any day in the window closed down more than this fraction, the date is not "
        "considered overextended (there was consolidation). E.g. 0.01 = 1%% pullback allowed.",
    )
    parser.add_argument(
        "--weights",
        nargs="+",
        type=int,
        default=None,
        help="Position weights per rank (e.g. --weights 50 30 20). Must match --top count.",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=INITIAL_CAPITAL,
        help=f"Initial portfolio capital in dollars (default: {INITIAL_CAPITAL:,.0f}).",
    )
    parser.add_argument(
        "--reversal",
        action="store_true",
        default=False,
        help="Enable reversal trade: if BEARISH primary stops out within N bars and "
        "price later crosses above OR high, enter a BULLISH reversal with OR-midpoint "
        "hard stop. Default: off.",
    )
    parser.add_argument(
        "--reversal-max-bars",
        type=int,
        default=3,
        dest="reversal_max_bars",
        help="Max bars_held threshold for reversal eligibility (default: 3 = within 4 bars).",
    )
    parser.add_argument(
        "--bearish-reversal",
        action="store_true",
        default=False,
        dest="bearish_reversal",
        help="Enable bearish reversal trade: if BULLISH primary stops out within N bars and "
        "price later crosses below OR low, enter a BEARISH reversal with OR-midpoint "
        "hard stop. Default: off.",
    )
    parser.add_argument(
        "--bearish-reversal-max-bars",
        type=int,
        default=3,
        dest="bearish_reversal_max_bars",
        help="Max bars_held threshold for bearish reversal eligibility (default: 3).",
    )
    parser.add_argument(
        "--min-first-bar-range",
        type=float,
        default=None,
        dest="min_first_bar_range_pct",
        help="Rule 1: skip entry if the first 5-min bar of the opening window has a "
        "high-low range smaller than this fraction of the bar midpoint "
        "(e.g. 0.015 = 1.5%%). M1 only. Default: disabled.",
    )
    parser.add_argument(
        "--min-first-bar-volume",
        type=float,
        default=None,
        dest="min_first_bar_volume_mult",
        help="Rule 4: skip M1 entry if the 09:30 bar volume < mult × (20d avg daily vol / 78). "
        "E.g. 1.5 means opening bar must be 1.5× the expected per-bar volume. Default: disabled.",
    )
    parser.add_argument(
        "--min-or-vol-ratio",
        type=float,
        default=None,
        dest="min_or_vol_ratio",
        help="Skip entry if OR-window mean volume / 20d historical OR-window mean volume < threshold. "
        "Default: disabled.",
    )
    parser.add_argument(
        "--score-entry-weight",
        type=float,
        default=0.50,
        dest="score_entry_weight",
        help="Scoring weight for entry_vs_mid_pct (default: 0.50). Must satisfy: entry + vol_ratio + 0.30 + or_range <= 1.0.",
    )
    parser.add_argument(
        "--score-vol-ratio-weight",
        type=float,
        default=0.00,
        dest="score_vol_ratio_weight",
        help="Scoring weight for or_vol_ratio (default: 0.00). Remainder after entry + vol_ratio + avg_win goes to or_range_pct.",
    )
    parser.add_argument(
        "--score-avg-win-weight",
        type=float,
        default=0.30,
        dest="score_avg_win_weight",
        help="Scoring weight for avg_win_pct (default: 0.30). Remainder after entry + vol_ratio + avg_win + ev_trend goes to or_range_pct.",
    )
    parser.add_argument(
        "--score-ev-trend-weight",
        type=float,
        default=0.00,
        dest="score_ev_trend_weight",
        help="Scoring weight for ev_trend (recent EV − full-window EV). Positive = rewards accelerating tickers. Default: 0.00.",
    )
    parser.add_argument(
        "--ev-trend-days",
        type=int,
        default=15,
        dest="ev_trend_days",
        help="Calendar days for the recent EV window in ev_trend computation (default: 15).",
    )
    parser.add_argument(
        "--score-dist-52w-low-weight",
        type=float,
        default=0.00,
        dest="score_dist_52w_low_weight",
        help="Scoring weight for 52-week low proximity. Higher weight rewards tickers closer to their 52w low. Default: 0.00.",
    )
    parser.add_argument(
        "--score-dist-52w-high-weight",
        type=float,
        default=0.00,
        dest="score_dist_52w_high_weight",
        help="Scoring weight for 52-week high proximity (George & Hwang 2004). Rewards tickers near their 52w high for both BULLISH and BEARISH signals. Default: 0.00.",
    )
    parser.add_argument(
        "--score-streak-weight",
        type=float,
        default=0.00,
        dest="score_streak_weight",
        help="Scoring weight for consecutive-day streak penalty. Penalizes tickers with long up/down streaks (overextension). Default: 0.00.",
    )
    parser.add_argument(
        "--score-prev-day-vol-weight",
        type=float,
        default=0.00,
        dest="score_prev_day_vol_weight",
        help="Scoring weight for prior-day volume ratio (vol vs 20d avg). Rewards above-average volume activity. Default: 0.00.",
    )
    parser.add_argument(
        "--score-ma200-dist-weight",
        type=float,
        default=0.00,
        dest="score_ma200_dist_weight",
        help="Scoring weight for daily MA200 distance penalty. Penalizes tickers overextended above their 200-day MA. Default: 0.00.",
    )
    parser.add_argument(
        "--score-ma50-dist-weight",
        type=float,
        default=0.00,
        dest="score_ma50_dist_weight",
        help="Direction-aware scoring weight for daily MA50 distance. Rewards above-MA50 for BULLISH signals, below-MA50 for BEARISH signals. Default: 0.00.",
    )
    parser.add_argument(
        "--regime-scoring",
        action="store_true",
        default=False,
        dest="regime_scoring",
        help="Enable regime-adaptive scoring. Applies different weight profiles on bull vs bear days "
        "(classified by prior-day QQQ close vs 50d MA). Use --bull-* and --bear-* flags to set profiles.",
    )
    # Bull regime weight overrides (QQQ prior-close > 50d MA)
    # Research defaults: add ma50 momentum signal in confirmed uptrends
    parser.add_argument("--bull-score-entry-weight",    type=float, default=None, dest="regime_bull_entry_weight",
                        help="Entry weight in bull regime. Default: 0.70 (when --regime-scoring active).")
    parser.add_argument("--bull-score-vol-ratio-weight", type=float, default=None, dest="regime_bull_vol_ratio_weight",
                        help="Vol ratio weight in bull regime. Default: 0.15.")
    parser.add_argument("--bull-score-avg-win-weight",  type=float, default=None, dest="regime_bull_avg_win_weight",
                        help="Avg-win weight in bull regime. Default: 0.00.")
    parser.add_argument("--bull-score-ma50-dist-weight", type=float, default=None, dest="regime_bull_ma50_dist_weight",
                        help="MA50 distance weight in bull regime. Default: 0.10 (reward momentum leaders).")
    # Bear regime weight overrides (QQQ prior-close <= 50d MA)
    # Research defaults: fall back to E1 (best for bear/choppy years)
    parser.add_argument("--bear-score-entry-weight",    type=float, default=None, dest="regime_bear_entry_weight",
                        help="Entry weight in bear regime. Default: 0.80 (E1 baseline).")
    parser.add_argument("--bear-score-vol-ratio-weight", type=float, default=None, dest="regime_bear_vol_ratio_weight",
                        help="Vol ratio weight in bear regime. Default: 0.15.")
    parser.add_argument("--bear-score-avg-win-weight",  type=float, default=None, dest="regime_bear_avg_win_weight",
                        help="Avg-win weight in bear regime. Default: 0.00.")
    parser.add_argument("--bear-score-ma50-dist-weight", type=float, default=None, dest="regime_bear_ma50_dist_weight",
                        help="MA50 distance weight in bear regime. Default: 0.00 (ignore MA50 in bear).")
    parser.add_argument(
        "--direction-split-ev",
        action="store_true",
        default=True,
        dest="direction_split_ev_gate",
        help="Apply EV gate per signal direction (BULLISH/BEARISH separately). "
        "Excludes tickers with negative directional EV even if combined EV is positive. Default: on.",
    )
    parser.add_argument(
        "--no-direction-split-ev",
        action="store_false",
        dest="direction_split_ev_gate",
        help="Disable direction-split EV gate (uses combined EV for both directions).",
    )
    parser.add_argument("--ds-bull-min-ev", type=float, default=0.0, dest="ds_bull_min_ev",
                        help="Min directional EV required in bull regime (pool_vote >= bull_threshold). Default: 0.0.")
    parser.add_argument("--ds-neutral-min-ev", type=float, default=0.0, dest="ds_neutral_min_ev",
                        help="Min directional EV required in neutral regime. Default: 0.0.")
    parser.add_argument("--ds-bear-min-ev", type=float, default=0.0, dest="ds_bear_min_ev",
                        help="Min directional EV required in bear regime (pool_vote <= bear_threshold). Default: 0.0.")
    parser.add_argument(
        "--qqq-or-weight",
        type=float,
        default=0.30,
        dest="qqq_or_weight",
        help="Scoring weight for QQQ opening-range alignment (9:30-9:45). "
             "Positive values boost tickers whose signal direction matches QQQ OR; penalise opposing. "
             "Default: 0.30 (confirmed optimal across 2019-2026).",
    )
    parser.add_argument(
        "--qqq-regime-weight",
        type=float,
        default=0.0,
        dest="qqq_regime_weight",
        help=(
            "Scoring weight for QQQ daily MA regime. Boosts BEARISH signals (and penalises BULLISH) "
            "when QQQ is below its MA20/MA50, with strength scaling by tier: "
            "below MA20=0.33x, below MA50=0.67x, below MA50 + both MAs falling=1.0x. "
            "Uses prior trading day's MAs (no lookahead). Default: 0.0."
        ),
    )
    parser.add_argument(
        "--qqq-regime-slope-days",
        type=int,
        default=5,
        dest="qqq_regime_slope_days",
        help="Lookback days for QQQ MA slope computation (rising vs falling). Default: 5.",
    )
    parser.add_argument(
        "--qqq-regime-full-only",
        action="store_true",
        default=False,
        dest="qqq_regime_full_only",
        help=(
            "Only activate regime boost at the highest-confidence tier: "
            "QQQ < MA50 AND both MA20+MA50 trending down (factor=1.0). "
            "Skips the mild (0.33) and moderate (0.67) tiers. "
            "Reduces false signals during brief corrections in bull years."
        ),
    )
    parser.add_argument(
        "--qqq-regime-bearish-only",
        action="store_true",
        default=False,
        dest="qqq_regime_bearish_only",
        help=(
            "Asymmetric mode: only boost BEARISH signals in bearish regime, "
            "do not penalise BULLISH signals. "
            "Preserves bullish signal quality while giving BEARISH picks a better chance."
        ),
    )
    parser.add_argument(
        "--qqq-regime-ma200",
        action="store_true",
        default=False,
        dest="qqq_regime_ma200",
        help=(
            "Enable 5-tier MA200 regime system. Adds an acceleration zone (MA50→MA200) "
            "and a true-bear tier (below MA200 + both MAs falling). "
            "Tiers: 0.0/0.25/0.55/0.75/1.0 vs default 0.0/0.33/0.67/1.0. "
            "With --qqq-regime-full-only, fires only when QQQ < MA200 AND both MAs falling."
        ),
    )
    parser.add_argument(
        "--qqq-regime-recovery-floor",
        type=float,
        default=0.0,
        dest="qqq_regime_recovery_floor",
        help=(
            "After QQQ breaks below MA200, hold at least this factor floor during recovery "
            "until price reclaims MA200 AND MA20 slope turns positive. "
            "Models asymmetric recovery: decline is fast, recovery is slow. "
            "Default: 0.0 (off). Suggested: 0.25."
        ),
    )
    parser.add_argument(
        "--qqq-regime-no-bullish",
        action="store_true",
        default=False,
        dest="qqq_regime_no_bullish",
        help=(
            "On full-bear days (QQQ regime factor = 1.0), exclude all BULLISH signals from selection. "
            "Requires --qqq-regime-ma200 + --qqq-regime-full-only to define full-bear. "
            "Default: off."
        ),
    )
    parser.add_argument(
        "--qqq-regime-bear-entry-weight",
        type=float,
        default=None,
        dest="qqq_regime_bear_entry_weight",
        help=(
            "On full-bear days (QQQ regime factor = 1.0), override score_entry_weight to this value. "
            "Reduces the gap-up breakout bias when picking bearish plays in a bear market. "
            "Default: None (use --score-entry-weight)."
        ),
    )
    parser.add_argument(
        "--qqq-regime-bearish-ev-only",
        action="store_true",
        default=False,
        dest="qqq_regime_bearish_ev_only",
        help=(
            "On full-bear days (QQQ regime factor = 1.0), bypass the combined EV gate for BEARISH "
            "signals — only require ev_trade_bearish >= 0 (via --direction-split-ev, which is on by default). "
            "Allows tickers whose bearish-specific EV is positive even when the combined 90d EV is negative. "
            "Requires --qqq-regime-ma200 + --qqq-regime-full-only. Default: off."
        ),
    )
    parser.add_argument(
        "--qqq-regime-bear-ctp",
        type=float,
        default=None,
        dest="qqq_regime_bear_ctp",
        help=(
            "On full-bear days (QQQ regime factor = 1.0), use this value as the BEARISH OR threshold "
            "fraction instead of the default bottom-20%%. E.g. 0.40 = bottom 40%%. BULLISH threshold "
            "is unaffected. Requires --qqq-regime-ma200 + --qqq-regime-full-only. Default: None (off)."
        ),
    )
    parser.add_argument(
        "--qqq-regime-bear-ctp-20ma-cross-50ma",
        action="store_true",
        default=False,
        dest="qqq_regime_bear_ctp_ma_cross",
        help=(
            "Restrict --qqq-regime-bear-ctp to dates where the prior-day QQQ MA20 < MA50 "
            "(death cross active). CTP is disabled automatically once MA20 recovers above MA50, "
            "avoiding false triggers during short-lived V-shape dips. "
            "Requires --qqq-regime-bear-ctp. Default: off."
        ),
    )
    parser.add_argument(
        "--qqq-regime-bear-ctp-below-ma20-ma50",
        action="store_true",
        default=False,
        dest="qqq_regime_bear_ctp_below_ma",
        help=(
            "Use price-relative condition for --qqq-regime-bear-ctp instead of factor>=1.0: "
            "CTP activates whenever prior-day QQQ close < MA20 AND close < MA50. "
            "Fires earlier than the full-bear gate (no MA200/slope requirements), capturing "
            "fast V-shape crashes before structural bear is confirmed. "
            "Requires --qqq-regime-bear-ctp. Default: off."
        ),
    )
    parser.add_argument(
        "--qqq-regime-bear-ctp-below-ma200",
        action="store_true",
        default=False,
        dest="qqq_regime_bear_ctp_below_ma200",
        help=(
            "Use MA200-relative condition for --qqq-regime-bear-ctp: CTP activates whenever "
            "prior-day QQQ close < MA200, regardless of MA20/MA50 slope conditions. "
            "Broader than the full-bear gate (no slope requirements) but more selective than "
            "--qqq-regime-bear-ctp-below-ma20-ma50 (requires structural QQQ weakness). "
            "Automatically disables when QQQ recovers above MA200. "
            "Requires --qqq-regime-bear-ctp. Default: off."
        ),
    )
    parser.add_argument("--score-trend-align-weight", type=float, default=0.0,
                        dest="score_trend_align_weight",
                        help="Weight for direction-aware consecutive-streak scoring. Positive = reward "
                             "signals aligned with prior price momentum; penalizes counter-trend picks. "
                             "Normalized to [-1,+1] via streak/5. Default: 0.0.")
    parser.add_argument("--score-win-rate-weight", type=float, default=0.0,
                        dest="score_win_rate_weight",
                        help="Scoring weight for rolling win rate. Higher values favour consistent "
                             "tickers over lottery-style high-EV picks. Default: 0.0.")
    parser.add_argument("--entry-weight-bull", type=float, default=None,
                        dest="entry_weight_bull",
                        help="entry_vs_mid_pct weight in bull regime (pool_vote >= bull_threshold). "
                             "Default: same as --score-entry-weight.")
    parser.add_argument("--entry-weight-bear", type=float, default=None,
                        dest="entry_weight_bear",
                        help="entry_vs_mid_pct weight in bear regime (pool_vote <= bear_threshold). "
                             "Reduce to de-prioritise aggressive breakouts in choppy markets. "
                             "Default: same as --score-entry-weight.")
    parser.add_argument("--normalize-or-by-adr", action="store_true", default=False,
                        dest="normalize_or_by_adr",
                        help="Normalize or_range_pct by each ticker's rolling ADR before scoring. "
                             "Makes OR magnitude comparable across different-volatility stocks. Default: off.")
    parser.add_argument("--adr-days", type=int, default=20,
                        dest="adr_days",
                        help="Lookback days for rolling ADR computation used in --normalize-or-by-adr. Default: 20.")
    parser.add_argument("--min-pool-vote", type=int, default=0,
                        dest="min_pool_vote_to_trade",
                        help="Skip trading on days where fewer than N tickers have positive rolling EV. "
                             "0 = disabled (always trade). Default: 0.")
    parser.add_argument("--direction-regime-filter", action="store_true", default=False,
                        dest="direction_regime_filter",
                        help="In bull regime (pool_vote >= drf-bull-thresh), skip BEARISH picks. "
                             "In bear regime (pool_vote <= drf-bear-thresh), skip BULLISH picks. Default: off.")
    parser.add_argument("--drf-bull-thresh", type=int, default=10, dest="drf_bull_only_thresh",
                        help="Pool vote >= this → only BULLISH picks allowed. Default: 10.")
    parser.add_argument("--drf-bear-thresh", type=int, default=5, dest="drf_bear_only_thresh",
                        help="Pool vote <= this → only BEARISH picks allowed. Default: 5.")
    parser.add_argument(
        "--ev-shrink-k",
        type=float,
        default=0.0,
        dest="ev_shrink_k",
        help="Bayesian EV shrinkage factor k. Shrinks each ticker ev_trade toward pool mean: ev_s = (n*ev + k*pool_mean)/(n+k). 0=disabled. Try 5-10. Default: 0.0.",
    )
    parser.add_argument(
        "--score-frog-weight",
        type=float,
        default=0.0,
        dest="score_frog_weight",
        help="Frog-in-the-Pan path smoothness weight. Rewards tickers with consistent directional daily moves. Direction-aware. Default: 0.0.",
    )
    parser.add_argument(
        "--frog-days",
        type=int,
        default=60,
        dest="frog_days",
        help="Lookback days for Frog-in-the-Pan smoothness score. Default: 60.",
    )
    parser.add_argument(
        "--score-dir-ev-weight",
        type=float,
        default=0.0,
        dest="score_dir_ev_weight",
        help=(
            "Direction-specific historical EV weight. Uses ev_trade_bullish for BULLISH signals "
            "and ev_trade_bearish for BEARISH signals. Rewards tickers that historically perform "
            "well specifically in the direction being scored, not just overall. "
            "Typical range 0.05-0.20. Default: 0.0."
        ),
    )
    parser.add_argument(
        "--score-rel-strength-weight",
        type=float,
        default=0.0,
        dest="score_rel_strength_weight",
        help=(
            "Cross-sectional relative MA50 strength weight. Scores each ticker's MA50 distance "
            "relative to the pool mean that day. Positive = outperforming pool. "
            "Direction-aware: rewards BULLISH for outperforming, BEARISH for underperforming. "
            "Most effective in bear/choppy years where pool spread is wide. Default: 0.0."
        ),
    )
    parser.add_argument(
        "--score-recent-bear-ev-weight",
        type=float,
        default=0.00,
        dest="score_recent_bear_ev_weight",
        help="Recent bear EV weight. Rewards tickers with strong recent BEARISH trade EV. Default: 0.00.",
    )
    parser.add_argument(
        "--recent-bear-trades",
        type=int,
        default=7,
        dest="recent_bear_trades",
        help="Number of most recent BEARISH trades used to compute recent_bear_ev. Default: 7.",
    )
    parser.add_argument(
        "--score-or-bar-quality-weight",
        type=float,
        default=0.00,
        dest="score_or_bar_quality_weight",
        help="OR bar quality weight. Fraction of OR bars that close in signal direction. Default: 0.00.",
    )
    parser.add_argument(
        "--score-gap-weight",
        type=float,
        default=0.00,
        dest="score_gap_weight",
        help="Overnight gap weight. Direction-aware: gap down rewards BEARISH, gap up rewards BULLISH. Default: 0.00.",
    )
    parser.add_argument(
        "--min-entry-vs-mid",
        type=float,
        default=0.0,
        dest="min_entry_vs_mid",
        help="Skip ticker if entry_vs_mid_pct <= threshold. Filters weak-entry (near-midpoint) trades that "
             "tend to stall and exit via fallback. Default: 0.0 (disabled). Recommended: 0.80.",
    )
    parser.add_argument(
        "--score-gap-tiebreak",
        type=float,
        default=0.0,
        dest="score_gap_tiebreak",
        help="When score gap between #1 and #2 is < threshold, tiebreak by entry_vs_mid_pct instead. "
             "Default: 0.0 (disabled). Recommended: 0.50.",
    )
    parser.add_argument(
        "--min-or-range",
        type=float,
        default=0.0,
        dest="min_or_range",
        help="Skip ticker if OR range %% < threshold. Filters low-range tickers with tight stops. Default: 0.0 (disabled).",
    )
    parser.add_argument(
        "--min-or-range-windows",
        nargs="+",
        default=None,
        dest="min_or_range_windows",
        metavar="LABEL",
        help="Only apply --min-or-range to these window labels (e.g. --min-or-range-windows M1 M2). Default: apply to all windows.",
    )
    parser.add_argument(
        "--min-ma200-distance",
        type=float,
        default=0.0,
        dest="min_ma200_distance",
        help="Skip ticker if (entry - MA200) / MA200 %% < threshold. Filters entries too close to or below the 200-period MA. Default: 0.0 (disabled).",
    )
    parser.add_argument(
        "--min-ma200-distance-windows",
        nargs="+",
        default=None,
        dest="min_ma200_distance_windows",
        metavar="LABEL",
        help="Only apply --min-ma200-distance to these window labels (e.g. --min-ma200-distance-windows A1 A2). Default: apply to all windows.",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.0,
        dest="min_score",
        help="Skip ticker if score < threshold. Filters low-conviction picks. Default: 0.0 (disabled).",
    )
    parser.add_argument(
        "--min-ev",
        type=float,
        default=0.0,
        dest="min_ev",
        help="Skip ticker if rolling EV %% < threshold. Raises the EV gate above 0. Default: 0.0 (disabled).",
    )
    parser.add_argument(
        "--or-bar-lookback",
        type=int,
        default=3,
        dest="or_bar_lookback",
        help="If OR range < 1/4 of avg High-Low of last N bars before the window, use that avg as the effective OR range for scoring. Default: 3.",
    )
    parser.add_argument(
        "--close-top-pct",
        type=float,
        default=None,
        dest="close_top_pct",
        help=(
            "Tighter signal filter: BULLISH only if close >= OR_high - PCT * OR_range; "
            "BEARISH only if close <= OR_low + PCT * OR_range. "
            "Hard stop set to OR_low (bull) or OR_high (bear), pre-armed from bar 0. "
            "Example: --close-top-pct 0.05 requires close in top/bottom 5%% of the bar. "
            "Default: off (uses standard midpoint/bottom-30 conditions)."
        ),
    )
    parser.add_argument(
        "--bearish-reentry",
        action="store_true",
        default=False,
        dest="bearish_reentry",
        help="Enable bearish re-entry: if BEARISH primary stops out within N bars and "
        "price later closes below OR_low, re-enter short with midpoint as hard stop. "
        "Only fires when reversal did not fire. Default: off.",
    )
    parser.add_argument(
        "--bearish-reentry-max-bars",
        type=int,
        default=3,
        dest="bearish_reentry_max_bars",
        help="Max bars_held for the primary BEARISH trade to be eligible for re-entry (default: 3).",
    )
    parser.add_argument(
        "--bullish-reentry",
        action="store_true",
        default=False,
        dest="bullish_reentry",
        help="Enable bullish re-entry: if BULLISH primary stops out within N bars and "
        "price later closes above OR_high, re-enter long with midpoint as hard stop. Default: off.",
    )
    parser.add_argument(
        "--bullish-reentry-max-bars",
        type=int,
        default=5,
        dest="bullish_reentry_max_bars",
        help="Max bars_held for the primary BULLISH trade to be eligible for re-entry (default: 3).",
    )
    parser.add_argument(
        "--only-dates",
        type=str,
        default=None,
        dest="only_dates",
        help="Path to a file with YYYY-MM-DD dates (one per line). Only those trading days "
             "are evaluated; all others are skipped. Use with --start/--end spanning the full range.",
    )
    parser.add_argument(
        "--regime-adaptive",
        action="store_true",
        default=False,
        dest="regime_adaptive",
        help=(
            "Select M1 window bars and stop_pct per day based on prior VIX close and QQQ "
            "5-min MA alignment score at the 9:40 bar. Uses cross-year validated config table "
            "(see REGIME_ADAPTIVE_CONFIGS). The bars value in --window M1 is used as a fallback "
            "when VIX/QQQ data is unavailable. Incompatible with --doubledown."
        ),
    )
    parser.add_argument(
        "--doubledown",
        action="store_true",
        default=False,
        help=(
            "Enable double-down: if rank-2+ positions stop out within the doubledown window "
            "of OR close, deploy their returned capital into the highest-ranked survivor as a "
            "single add-on leg. Add-on entry = close of the doubledown bar; hard stop = "
            "entry ± 80%% × bar range. Default: off."
        ),
    )
    parser.add_argument(
        "--doubledown-start",
        type=int,
        default=DOUBLEDOWN_START_MIN,
        dest="doubledown_start_min",
        help=(
            f"Minutes from OR close at which the DD check fires and the add-on leg enters. "
            f"Stopouts that occurred before this mark are eligible to free capital. "
            f"Must be a multiple of 5. Default: {DOUBLEDOWN_START_MIN}."
        ),
    )
    parser.add_argument(
        "--opportunity-capital",
        type=float,
        default=0.0,
        dest="opportunity_capital_pct",
        help=(
            "Size of the opportunity pool as a percentage of initial capital "
            "(e.g. 50 = 50%%). Pool deploys on DD signals independently of "
            "window capital and recycles sequentially within the day. "
            "Requires --doubledown. Default: 0 (disabled)."
        ),
    )
    parser.add_argument(
        "--no-exit-at-bar-close",
        dest="exit_at_bar_close",
        action="store_false",
        default=True,
        help="Exit at the intrabar stop/fallback price instead of bar close. "
        "Default: exit at bar close (matches live engine behaviour).",
    )
    _PARSER = parser
    return parser


def _parse_args(argv=None):
    return build_parser().parse_args(argv)
