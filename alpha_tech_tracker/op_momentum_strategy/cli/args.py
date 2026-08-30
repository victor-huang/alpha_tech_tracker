"""Argument parsing for the OpMomentum trade engine CLI.

`parse_args` is extracted verbatim from op_momentum_trade_engine.py — the flag
set, defaults, help text, and cross-flag validation are unchanged.
"""
import argparse

from ..config import (
    ARMED_MA20_EXIT,
    DAILY_MAX_LOSS_USD,
    MAX_ACTIVE_SYMBOLS,
    MAX_LOSS_PCT,
    OPENING_START_TIME,
    RANK_WEIGHTS,
    REGIME_FILTER,
    REGIME_MA,
    STOP_PCT,
    TRAILING_MA,
    TRAILING_MA_SWITCH,
    TRAILING_MA_SWITCH_FACTOR,
    TRAILING_MA_SWITCH_PERIOD,
    WS_RECONNECT_TIMEOUT_SECONDS,
)
from ..op_momentum_selector import ROLLING_LOOKBACK_DAYS as _DEFAULT_LOOKBACK_DAYS
from .daemon import _PID_FILE

def parse_args():
    parser = argparse.ArgumentParser(description="OpMomentum live trade engine")
    parser.add_argument(
        "action",
        choices=["run", "start", "stop", "status", "restart"],
        help="run: foreground | start: daemon | stop | status | restart",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        default=False,
        help="Use live trading account (default: paper trading)",
    )
    parser.add_argument(
        "--mock-trade-execution",
        action="store_true",
        default=False,
        help="Simulate order fills at mid bid/ask — no real orders placed",
    )
    parser.add_argument(
        "--no-notify",
        action="store_true",
        default=False,
        dest="no_notify",
        help="Suppress all SMS and Telegram notifications for this session",
    )
    parser.add_argument(
        "--force-run",
        action="store_true",
        default=False,
        help="Bypass the market-hours gate and run immediately regardless of day/time. "
             "For off-hours integration testing only.",
    )
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=None,
        help="Override ticker universe, e.g. --tickers NVDA CRWD",
    )
    parser.add_argument(
        "--ticker-set",
        choices=["V3", "AT"],
        default=None,
        help="Named ticker set: V3 (default pool) or AT (ACTIVELY_TRADE_TICKERS)",
    )
    parser.add_argument(
        "--stop-pct",
        type=float,
        default=float(STOP_PCT),
        help=f"Hard stop as fraction of OR range (default: {float(STOP_PCT)})",
    )
    parser.add_argument(
        "--trailing-ma",
        type=str,
        default=TRAILING_MA,
        choices=["ma20", "ma50", "both", "none"],
        help="Trailing MA stop: ma20, ma50, both, or none to disable (default: ma20)",
    )
    parser.add_argument(
        "--trailing-ma-switch",
        choices=["none", "after-arm", "after-target"],
        default=TRAILING_MA_SWITCH,
        dest="trailing_ma_switch",
        help="Upgrade trailing stop to a faster MA once a profit threshold is reached. "
        "after-arm: upgrade when favorable move >= 1x OR range. "
        "after-target: upgrade at factor x OR range (see --trailing-ma-switch-factor). "
        f"Default: {TRAILING_MA_SWITCH}.",
    )
    parser.add_argument(
        "--trailing-ma-switch-period",
        type=int,
        default=TRAILING_MA_SWITCH_PERIOD,
        dest="trailing_ma_switch_period",
        help=f"Period of the fast MA used after the switch threshold is hit (default: {TRAILING_MA_SWITCH_PERIOD}).",
    )
    parser.add_argument(
        "--trailing-ma-switch-factor",
        type=float,
        default=TRAILING_MA_SWITCH_FACTOR,
        dest="trailing_ma_switch_factor",
        help=f"OR-range multiplier for --trailing-ma-switch after-target (default: {TRAILING_MA_SWITCH_FACTOR}).",
    )
    parser.add_argument(
        "--max-loss-pct",
        type=float,
        default=MAX_LOSS_PCT,
        help="Per-trade max loss as a fraction of entry stock price (e.g. 0.02 = 2%%). Default: disabled.",
    )
    parser.add_argument(
        "--daily-max-loss",
        type=float,
        default=DAILY_MAX_LOSS_USD,
        help="Daily max-loss circuit breaker in dollars (e.g. 500). No new entries once realized P&L drops below -N. Default: disabled.",
    )
    parser.add_argument(
        "--ws-reconnect-timeout",
        type=int,
        default=WS_RECONNECT_TIMEOUT_SECONDS,
        help=f"Seconds without a bar before the WebSocket stream is reconnected (default: {WS_RECONNECT_TIMEOUT_SECONDS}).",
    )
    parser.add_argument(
        "--min-hold-minutes",
        type=int,
        default=None,
        dest="min_hold_minutes",
        help="Minimum minutes a position must be held before any exit mechanism "
        "(hard stop, fallback, trailing MA, max-loss, timed exit) can trigger. "
        "EOD close is never gated by this. Default: disabled (no minimum hold).",
    )
    parser.add_argument(
        "--armed-ma20-exit",
        action="store_true",
        default=ARMED_MA20_EXIT,
        help="Once hard stop is armed, use MA20 as trailing exit instead of hard_stop_price. Default: off.",
    )
    parser.add_argument(
        "--regime-filter",
        action="store_true",
        default=REGIME_FILTER,
        help="Suppress BULLISH signals on days when QQQ is below its N-day MA. Default: off.",
    )
    parser.add_argument(
        "--regime-ma",
        type=int,
        default=REGIME_MA,
        help=f"N-day MA period for QQQ regime filter (default: {REGIME_MA}).",
    )
    parser.add_argument(
        "--enable-regime-engine",
        action="store_true",
        default=False,
        help=(
            "Enable MASTER_REGIME_SUMMARY pattern-based regime engine. "
            "Instantiates RegimeEngine; direction filter applied to all signals. "
            "Unrelated to --regime-filter (QQQ MA). Default: off."
        ),
    )
    parser.add_argument(
        "--regime-hold",
        action="store_true",
        default=False,
        help="Apply regime hold window as timed exit. Requires --enable-regime-engine. Default: off.",
    )
    parser.add_argument(
        "--disable-ma-stops-for-regime-hold-only",
        action="store_true",
        default=False,
        dest="disable_ma_stops_for_regime_hold",
        help=(
            "Disable trailing MA stop (MA20/MA50) when --regime-hold is active. "
            "Hard stop always remains armed. Requires --regime-hold. Default: off."
        ),
    )
    parser.add_argument(
        "--selector",
        choices=["score-rank", "win-rate"],
        default="score-rank",
        dest="selector",
        help=(
            "Ticker selector algorithm. "
            "'score-rank' (default): composite score from 60-day rolling backtest. "
            "'win-rate': rank by historical EOD win rate; LONG=top-N, SHORT=bottom-N. "
            "Pair with --enable-regime-engine for direction-aware win-rate selection."
        ),
    )
    parser.add_argument(
        "--direction-aware-scoring",
        action="store_true",
        default=False,
        dest="direction_aware_scoring",
        help=(
            "Use direction-specific win-rate scoring for --selector win-rate. "
            "On LONG regime days rank by trailing bullish WR; on SHORT days by bearish WR. "
            "Requires --selector win-rate and --enable-regime-engine. Default: off."
        ),
    )
    parser.add_argument(
        "--rank-weighted-sizing",
        type=int,
        nargs="+",
        default=None,
        metavar="W",
        dest="rank_weighted_sizing",
        help=(
            "Weight position size by rank. Pass weights as integers, e.g. "
            "--rank-weighted-sizing 60 40 or --rank-weighted-sizing 50 25 25. "
            f"Defaults to equal sizing when omitted. Legacy default: {RANK_WEIGHTS}."
        ),
    )
    parser.add_argument(
        "--opening-start",
        type=str,
        default=OPENING_START_TIME,
        help=f"Opening window start time HH:MM ET, single-window mode only (default: {OPENING_START_TIME})",
    )
    parser.add_argument(
        "--window",
        action="append",
        nargs=3,
        metavar=("LABEL", "START", "BARS"),
        default=None,
        help="Define a named trading window: LABEL START BARS (e.g. --window M1 09:30 3). "
        "Repeat to add multiple windows. Overrides --opening-start when specified.",
    )
    parser.add_argument(
        "--morning-split",
        nargs="+",
        type=float,
        default=None,
        help="Capital split %% for the first (simultaneous) group of windows, e.g. --morning-split 100. "
        "Number of values determines first-group size; remaining windows are sequential "
        "(each reads live account balance at signal time). Default: 100%% for first window.",
    )
    parser.add_argument(
        "--pid-file",
        type=str,
        default=_PID_FILE,
        help=f"PID file path (default: {_PID_FILE})",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="Log file path (default: logs/op_momentum_YYYY-MM-DD.log)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    parser.add_argument(
        "--trade-type",
        type=str,
        default=None,
        choices=["options", "stock"],
        help="Trade type: options (live default) or stock (replay default)",
    )
    parser.add_argument(
        "--option-selector",
        type=str,
        default="standard",
        choices=["standard", "time-premium"],
        help="Option contract selector for live trading: "
        "'standard' uses ITMOptionContractSelector (fixed ±20%% ITM strike offset, default); "
        "'time-premium' uses TimePremiumContractSelector (shallowest ITM within DTE-adjusted time premium cap).",
    )
    parser.add_argument(
        "--time-premium-pct-cap",
        type=float,
        default=0.01,
        help="Max time premium as a fraction of stock price per reference DTE "
        "(default: 0.01 = 1%%). Only used when --option-selector time-premium is set. "
        "Threshold scales with DTE: 1%% / 5-day ref * actual DTE.",
    )
    parser.add_argument(
        "--collect-option-prices",
        action="store_true",
        default=False,
        help="Enable background option price collection and fair-price advisor. "
        "Writes 5-min snapshots to market_data/options_price_data/ and uses "
        "intrinsic value + cached time premium to compute entry/exit limit prices.",
    )
    parser.add_argument(
        "--record-tradestation-feed",
        action="store_true",
        default=False,
        dest="record_tradestation_feed",
        help="Record TradeStation 1-min and 5-min bar streams in parallel with the "
        "Alpaca feed. Writes CSVs to live_trade_market_data/{date}/tradestation_{ticker}_{timeframe}.csv. "
        "Requires valid TradeStation session tokens in config.json.",
    )
    parser.add_argument(
        "--option-price-interval",
        type=int,
        default=300,
        help="Snapshot interval in seconds for option price collection (default: 300)",
    )
    parser.add_argument(
        "--reversal",
        action="store_true",
        default=False,
        help="Enable reversal trade: if BEARISH primary stops out within N bars and "
        "price later crosses above OR high, enter BULLISH with midpoint as hard stop. Default: off.",
    )
    parser.add_argument(
        "--reversal-max-bars",
        type=int,
        default=3,
        dest="reversal_max_bars",
        help="Max bars_held for primary BEARISH trade to be eligible for reversal (default: 3).",
    )
    parser.add_argument(
        "--bearish-reentry",
        action="store_true",
        default=False,
        dest="bearish_reentry",
        help="Enable bearish re-entry: if BEARISH primary stops out within N bars and "
        "price later closes below OR low, re-enter short with midpoint as hard stop. Default: off.",
    )
    parser.add_argument(
        "--bearish-reentry-max-bars",
        type=int,
        default=3,
        dest="bearish_reentry_max_bars",
        help="Max bars_held for primary BEARISH trade to be eligible for bearish re-entry (default: 3).",
    )
    parser.add_argument(
        "--bullish-reentry",
        action="store_true",
        default=False,
        dest="bullish_reentry",
        help="Enable bullish re-entry: if BULLISH primary stops out within N bars and "
        "price later closes above OR high, re-enter long with midpoint as hard stop. Default: off.",
    )
    parser.add_argument(
        "--bullish-reentry-max-bars",
        type=int,
        default=5,
        dest="bullish_reentry_max_bars",
        help="Max bars_held for primary BULLISH trade to be eligible for bullish re-entry (default: 5).",
    )
    parser.add_argument(
        "--doubledown",
        action="store_true",
        default=False,
        help=(
            "Enable double-down add-on leg: when a co-pick stops out early, "
            "its freed capital is redeployed into the surviving position at a "
            "break-even hard stop. Fires once per window at OR close + doubledown-start."
        ),
    )
    parser.add_argument(
        "--doubledown-start",
        type=int,
        default=5,
        dest="doubledown_start_min",
        metavar="MINUTES",
        help=(
            "Minutes after OR close to fire the double-down check and enter the "
            "add-on leg. Must be a multiple of 5. Default: 5."
        ),
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=None,
        dest="capital",
        help=(
            "Starting capital for cap P&L simulation in replay mode (e.g. 10000). "
            "Used as window budget for all windows so per-trade cap P&L matches the "
            "selector backtest. Has no effect in live mode."
        ),
    )
    parser.add_argument(
        "--replay-date",
        type=str,
        default=None,
        dest="replay_date",
        help="Replay a single historical session (YYYY-MM-DD). Feeds cached 5-min bars through "
        "the live engine instead of a live WebSocket stream. Implies mock-trade-execution.",
    )
    parser.add_argument(
        "--replay-start",
        type=str,
        default=None,
        dest="replay_start",
        help="Start date for a multi-day replay range (YYYY-MM-DD). Must be paired with --replay-end.",
    )
    parser.add_argument(
        "--replay-end",
        type=str,
        default=None,
        dest="replay_end",
        help="End date for a multi-day replay range (YYYY-MM-DD). Must be paired with --replay-start.",
    )
    parser.add_argument(
        "--compound",
        action="store_true",
        default=False,
        dest="compound",
        help="In range replay mode, carry ending capital forward day-to-day instead of resetting each day.",
    )
    parser.add_argument(
        "--live-data-dir",
        type=str,
        default=None,
        dest="live_data_dir",
        help=(
            "Directory of recorded live-session bar CSVs. When combined with "
            "--replay-date or --replay-start/--replay-end, feeds real intraday data instead of "
            "Alpaca historical cache. Expects {dir}/{date}/{feed}_{ticker}_5min.csv (CsvLiveBarsSource format)."
        ),
    )
    parser.add_argument(
        "--live-data-feed",
        choices=["iex", "sip", "tradestation"],
        default=None,
        dest="live_data_feed",
        help=(
            "Feed prefix used to locate CSV files under --live-data-dir "
            "(e.g. 'tradestation' → tradestation_{ticker}_5min.csv). "
            "Defaults to the value of --feed when not set."
        ),
    )
    parser.add_argument(
        "--full-day",
        action="store_true",
        default=False,
        dest="full_day",
        help=(
            "Replay the full market session including the 15:55 bar; close_all "
            "records exits at 16:00. By default replay exits at 15:55 so the "
            "EOD close does not interfere when adding afternoon windows. Use "
            "--full-day when replaying a complete session to market close."
        ),
    )
    parser.add_argument(
        "--top",
        type=int,
        default=MAX_ACTIVE_SYMBOLS,
        dest="top",
        help=f"Number of top-ranked tickers to trade per window (default: {MAX_ACTIVE_SYMBOLS}).",
    )
    parser.add_argument(
        "--fixed-signal-alloc",
        action="store_true",
        default=False,
        dest="fixed_signal_alloc",
        help="Fixed capital per signal slot (capital / top-N) regardless of how many signals "
        "fire. Total deployed scales with signal count up to top-N × capital. Default: off.",
    )
    parser.add_argument(
        "--extend-collection-bars",
        type=int,
        default=2,
        dest="extend_collection_bars",
        help="Number of additional bars past the OR close to collect win-rate signals. "
        "Default 2: collect until 9:55 for M1 3-bar. "
        "Each extra bar extends the collection window by 5 min "
        "(e.g. --extend-collection-bars 0 → signals must fire on the OR close bar only).",
    )
    parser.add_argument(
        "--lookback",
        type=int,
        default=_DEFAULT_LOOKBACK_DAYS,
        dest="lookback",
        help=f"Rolling lookback window in days for pre-market ticker scoring (default: {_DEFAULT_LOOKBACK_DAYS}).",
    )
    parser.add_argument(
        "--min-ev",
        type=float,
        default=0.0,
        dest="min_ev",
        help="Skip ticker if rolling ev_trade < threshold (default: 0.0, matches backtest behavior).",
    )
    parser.add_argument(
        "--ma-momentum-gate",
        action="store_true",
        default=False,
        dest="ma_momentum_gate",
        help=(
            "Suppress signals where the OR range does not overlap both MA20 and MA50 "
            "in the signal direction (BULLISH: or_high >= MA20 and MA50; "
            "BEARISH: or_low <= MA20 and MA50). Default: off."
        ),
    )
    parser.add_argument(
        "--normalize-or-by-adr",
        action="store_true",
        default=False,
        dest="normalize_or_by_adr",
        help=(
            "Normalize each ticker's OR range pct by its prior 20-day ADR before "
            "scoring. Levels the playing field between high/low volatility tickers. "
            "Default: off."
        ),
    )
    parser.add_argument(
        "--score-entry-weight",
        type=float,
        default=0.50,
        dest="score_entry_weight",
        help="Scoring weight for entry_vs_mid_pct (default: 0.50).",
    )
    parser.add_argument(
        "--score-avg-win-weight",
        type=float,
        default=0.30,
        dest="score_avg_win_weight",
        help="Scoring weight for historical avg_win_pct (default: 0.30).",
    )
    parser.add_argument(
        "--score-win-rate-weight",
        type=float,
        default=0.0,
        dest="score_win_rate_weight",
        help="Scoring weight for rolling win_rate (default: 0.0).",
    )
    parser.add_argument(
        "--score-rel-strength-weight",
        type=float,
        default=0.0,
        dest="score_rel_strength_weight",
        help=(
            "Scoring weight for cross-sectional relative MA50 strength vs pool mean. "
            "Direction-aware: rewards BULLISH outperformers and BEARISH underperformers. "
            "Default: 0.0."
        ),
    )
    parser.add_argument(
        "--min-pool-vote",
        type=int,
        default=0,
        dest="min_pool_vote_to_trade",
        help=(
            "Skip day if fewer than N tickers in the pool have positive rolling EV. "
            "Default: 0 (off)."
        ),
    )
    parser.add_argument(
        "--score-ev-trend-weight",
        type=float,
        default=0.0,
        dest="score_ev_trend_weight",
        help="Scoring weight for ev_trend (recent EV minus full-window EV). Default: 0.0 (off).",
    )
    parser.add_argument(
        "--ev-trend-days",
        type=int,
        default=15,
        dest="ev_trend_days",
        help="Calendar days for the recent EV window used in ev_trend computation. Default: 15.",
    )
    parser.add_argument(
        "--qqq-or-weight",
        type=float,
        default=0.0,
        dest="qqq_or_weight",
        help=(
            "Score bonus/penalty based on QQQ opening-range direction: "
            "BULLISH signals are boosted when QQQ OR is positive, penalised when negative (and vice-versa). "
            "Default: 0.0 (off)."
        ),
    )
    parser.add_argument(
        "--dynamic-ev-gate",
        action="store_true",
        default=False,
        dest="dynamic_ev_gate",
        help=(
            "Apply regime-adaptive EV filter based on daily pool vote (default: off). "
            "Mode 'percentile' (default): exclude bottom N%% of pool by EV. "
            "Mode 'threshold': fixed WR/W-L floors per regime tier. "
            "Pass this to match the backtest, which defaults it ON."
        ),
    )
    parser.add_argument(
        "--dg-mode",
        type=str,
        default="percentile",
        choices=["percentile", "threshold"],
        dest="dg_mode",
        help="Gate mode for --dynamic-ev-gate. Default: percentile.",
    )
    parser.add_argument("--dg-bull-threshold", type=int, default=10, dest="dg_bull_threshold",
                        help="Pool vote at/above which bull-regime thresholds apply. Default: 10.")
    parser.add_argument("--dg-bear-threshold", type=int, default=5, dest="dg_bear_threshold",
                        help="Pool vote at/below which bear-regime thresholds apply. Default: 5.")
    parser.add_argument("--dg-bull-exclude-pct", type=float, default=0.10, dest="dg_bull_exclude_pct",
                        help="[percentile] Bottom fraction of pool excluded in bull regime. Default: 0.10.")
    parser.add_argument("--dg-neutral-exclude-pct", type=float, default=0.25, dest="dg_neutral_exclude_pct",
                        help="[percentile] Bottom fraction excluded in neutral regime. Default: 0.25.")
    parser.add_argument("--dg-bear-exclude-pct", type=float, default=0.40, dest="dg_bear_exclude_pct",
                        help="[percentile] Bottom fraction excluded in bear regime. Default: 0.40.")
    parser.add_argument("--dg-bull-min-wr", type=float, default=0.30, dest="dg_bull_min_wr",
                        help="[threshold] Minimum win rate in bull regime. Default: 0.30.")
    parser.add_argument("--dg-neutral-min-wr", type=float, default=0.33, dest="dg_neutral_min_wr",
                        help="[threshold] Minimum win rate in neutral regime. Default: 0.33.")
    parser.add_argument("--dg-bear-min-wr", type=float, default=0.38, dest="dg_bear_min_wr",
                        help="[threshold] Minimum win rate in bear regime. Default: 0.38.")
    parser.add_argument("--dg-bull-min-wl", type=float, default=1.3, dest="dg_bull_min_wl",
                        help="[threshold] Minimum W/L ratio in bull regime. Default: 1.3.")
    parser.add_argument("--dg-neutral-min-wl", type=float, default=1.5, dest="dg_neutral_min_wl",
                        help="[threshold] Minimum W/L ratio in neutral regime. Default: 1.5.")
    parser.add_argument("--dg-bear-min-wl", type=float, default=1.8, dest="dg_bear_min_wl",
                        help="[threshold] Minimum W/L ratio in bear regime. Default: 1.8.")
    parser.add_argument(
        "--adaptive-lookback",
        action="store_true",
        default=False,
        dest="adaptive_lookback",
        help=(
            "Shorten the rolling lookback in bull regimes and lengthen it in bear regimes, "
            "using the same pool-vote signal as --dynamic-ev-gate (default: off). "
            "Pass this to match the backtest, which defaults it ON."
        ),
    )
    parser.add_argument("--al-bull-threshold", type=int, default=10, dest="al_bull_threshold",
                        help="Pool vote for bull regime in adaptive lookback. Default: 10.")
    parser.add_argument("--al-bear-threshold", type=int, default=5, dest="al_bear_threshold",
                        help="Pool vote for bear regime in adaptive lookback. Default: 5.")
    parser.add_argument("--al-bull-days", type=int, default=20, dest="al_bull_days",
                        help="Lookback days in bull regime. Default: 20.")
    parser.add_argument("--al-neutral-days", type=int, default=60, dest="al_neutral_days",
                        help="Lookback days in neutral regime. Default: 60.")
    parser.add_argument("--al-bear-days", type=int, default=90, dest="al_bear_days",
                        help="Lookback days in bear regime. Default: 90.")
    parser.add_argument(
        "--direction-split-ev",
        action="store_true",
        default=False,
        dest="direction_split_ev_gate",
        help=(
            "Gate on direction-specific EV: a BULLISH signal requires ev_trade_bullish "
            ">= floor; a BEARISH signal requires ev_trade_bearish >= floor (regime floors "
            "via --ds-*-min-ev). Default: off. Pass this to match the backtest, which "
            "defaults it ON. Regime tiers reuse --dg-bull-threshold / --dg-bear-threshold."
        ),
    )
    parser.add_argument("--ds-bull-min-ev", type=float, default=0.0, dest="ds_bull_min_ev",
                        help="Min directional EV in bull regime. Default: 0.0.")
    parser.add_argument("--ds-neutral-min-ev", type=float, default=0.0, dest="ds_neutral_min_ev",
                        help="Min directional EV in neutral regime. Default: 0.0.")
    parser.add_argument("--ds-bear-min-ev", type=float, default=0.0, dest="ds_bear_min_ev",
                        help="Min directional EV in bear regime. Default: 0.0.")
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.0,
        dest="min_score",
        help=(
            "Skip a pick if its composite score (after QQQ-OR adjustment) is below this "
            "floor. Matches the backtest, which drops score < min_score by default. "
            "Default: 0.0 (drops negative-score, low-conviction picks). Set very negative "
            "to disable."
        ),
    )
    parser.add_argument(
        "--feed",
        choices=["sip", "iex"],
        default="sip",
        help="Alpaca data feed: 'sip' (consolidated, default) or 'iex' (free tier).",
    )
    parser.add_argument(
        "--score-feed",
        choices=["sip", "iex"],
        default=None,
        dest="score_feed",
        help=(
            "Alpaca feed used for the 60-day selector lookback (scoring). "
            "Defaults to --feed when not set. "
            "Useful for replay: --feed iex --score-feed sip runs intraday bars from "
            "IEX while scoring tickers against the SIP 60-day history."
        ),
    )
    parser.add_argument(
        "--market-data-source",
        choices=["alpaca", "tradestation", "local_ts_broadcast"],
        default=None,
        dest="market_data_source",
        help=(
            "Market data source for live bar streaming and warmup (default: alpaca). "
            "'tradestation' — direct TS HTTP stream, requires valid TS session tokens. "
            "'local_ts_broadcast' — receive bars from a running bar_broadcaster daemon "
            "over a Unix domain socket; requires bar_broadcaster.py to be started first. "
            "Can also be set via 'market_data_source' in config.json."
        ),
    )
    parser.add_argument(
        "--execution-broker",
        choices=["alpaca", "tradestation", "etrade"],
        default=None,
        dest="execution_broker",
        help="Execution broker for order placement (default: value from config.json, "
        "fallback alpaca). Overrides 'execution_broker' in config.json when set.",
    )
    parser.add_argument(
        "--reset-session",
        action="store_true",
        default=False,
        dest="reset_session",
        help="Delete today's session checkpoint before starting, ignoring any saved positions "
        "and capital state from prior runs today. Use this to restart the engine fresh "
        "after manually closing positions or when the prior session state is corrupt.",
    )
    parser.add_argument(
        "--no-reentry-after-next-window-returned",
        action="store_false",
        default=True,
        dest="reentry_after_next_window_returned",
        help=(
            "Disable BRU/REV re-entries from window N after window N+1 has fully returned "
            "its capital. Default (on): re-entries are allowed once window N+1 has no open "
            "positions, using the current available budget. Pass this flag to match strict "
            "backtest behavior (permanently block once window N+1 has ever opened)."
        ),
    )
    args = parser.parse_args()
    if args.rank_weighted_sizing and len(args.rank_weighted_sizing) != args.top:
        parser.error(
            f"--rank-weighted-sizing requires exactly --top weights "
            f"(got {len(args.rank_weighted_sizing)} weights, --top {args.top})"
        )
    return args
