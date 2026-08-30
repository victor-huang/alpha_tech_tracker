"""Module-level constants for the selector backtest.

Extracted verbatim from op_momentum_selector_backtest.py so that the CLI and
reporting layers can import them without importing the backtest module itself
(which would be circular).
"""
from datetime import datetime, timedelta

from alpha_tech_tracker.op_momentum_strategy.config import EOD_EXIT_TIME


MIN_WINDOW_CAPITAL = 100.0
INITIAL_CAPITAL = 10_000.0
DOUBLEDOWN_START_MIN = 5  # min from OR close at which the DD check fires and addon enters

# ── Regime-adaptive config ────────────────────────────────────────────────────
REGIME_VIX_HI = 22.0
REGIME_VIX_LO = 17.0
REGIME_MA_STRONG_SCORE = 3  # min count of MA8/20/50/200 QQQ price is above at 9:40 bar

# (bars, stop_pct) per regime bucket — from 2018-2025 cross-year sweep.
# See M1_WINDOW_SWEEP_FINDINGS.md "Regime-Segmented Config Sweep" sections.
REGIME_ADAPTIVE_CONFIGS = {
    "vix_hi_ma_strong":  (4, 0.4),  # VIX≥22 + MA≥3: high confidence (2020:114d, 2022:90d)
    "vix_hi_ma_weak":    (5, 0.5),  # VIX≥22 + MA≤2: medium confidence (2022:103d)
    "vix_mid_ma_strong": (6, 0.7),  # VIX17-22 + MA≥3: medium confidence (2021:69d, 2023:55d)
    "vix_mid_ma_weak":   (6, 0.5),  # VIX17-22 + MA≤2: medium confidence (2021:67d, 2023:53d)
    "vix_lo":            (5, 0.5),  # VIX<17 (calm): low confidence — use all-weather default
}
# ─────────────────────────────────────────────────────────────────────────────

# The replay cutoff feeds bars with open-timestamp < EOD_EXIT_TIME (15:55), so the last
# bar processed is the 15:50 bar (open 15:50, closes at 15:55).  Display its open-time
# to match the live engine's exit_time convention (which stamps the bar open, not close).
_EOD_DISPLAY_TIME = (
    datetime.strptime(EOD_EXIT_TIME, "%H:%M") - timedelta(minutes=5)
).strftime("%H:%M")


