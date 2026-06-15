"""
2026 P&L analysis: random pick from top-3 tickers, exit at RegimeEngine's hold window.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from datetime import date, datetime, timedelta
from collections import defaultdict, Counter

from alpaca.data.enums import DataFeed
from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import fetch_bars
from alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener import (
    _DEFAULT_OR_BARS,
    _DEFAULT_OR_START,
    _precompute_or_anchor_returns,
    _rank_tickers_by_eod_win_rate,
)
from alpha_tech_tracker.op_momentum_strategy.regime_engine import DailyRegimeMetrics, RegimeEngine

TICKERS = [
    "SNDK", "META", "SNOW", "PLTR", "MU", "LLY", "LUNR", "CRWD",
    "QCOM", "OKLO", "TSLA", "AVGO", "ARM", "AMD", "DDOG", "RDDT",
    "IONQ", "HOOD", "RKLB", "CLSK",
]
OR_START = _DEFAULT_OR_START
OR_BARS = _DEFAULT_OR_BARS
WR_LOOKBACK = 20
TOP_N = 3
REGIME_POOL = 8
FEED = DataFeed.SIP

ANALYSIS_START = date(2026, 1, 2)
ANALYSIS_END = date(2026, 6, 13)
FETCH_START = date(2025, 9, 15)

_HOLD_MAP = {
    "+15m": 15, "+30m": 30, "+1h": 60,
    "+2h": 120, "+3h": 180, "+5h": 300,
    "EOD": None, "": None,
}


def hold_minutes(s):
    """Parse regime hold_window string to integer minutes, or None for EOD."""
    s = (s or "EOD").strip()
    # handle ranges like "+15m–+30m" — take the later (larger) window
    for sep in ("–", "—", "/"):
        if sep in s:
            parts = [p.strip() for p in s.split(sep)]
            valid = [_HOLD_MAP[p] for p in parts if p in _HOLD_MAP and _HOLD_MAP[p] is not None]
            return max(valid) if valid else None
    return _HOLD_MAP.get(s, None)


or_close_t = (
    datetime.strptime(OR_START, "%H:%M") + timedelta(minutes=(OR_BARS - 1) * 5)
).time()


def ticker_return_at(day_df, h_min):
    """Return % gain from OR-close bar to the hold exit. None if data missing."""
    cc = "close" if "close" in day_df.columns else "Close"
    or_mask = day_df.index.time == or_close_t
    if not or_mask.any():
        return None
    entry = float(day_df[or_mask].iloc[0][cc])
    if entry <= 0:
        return None
    if h_min is None:
        exit_price = float(day_df.iloc[-1][cc])
    else:
        exit_t = (
            datetime.combine(day_df.index[0].date(), or_close_t) + timedelta(minutes=h_min)
        ).time()
        exit_mask = day_df.index.time >= exit_t
        if not exit_mask.any():
            return None
        exit_price = float(day_df[exit_mask].iloc[0][cc])
    return (exit_price - entry) / entry * 100.0


def build_day_metrics(top_n_tickers, day_df_map, d):
    """Build DailyRegimeMetrics for day d from the top-N pool's actual returns."""
    hold_ret = {h: [] for h in [15, 30, 60, 120, 180, 300, None]}
    for ticker in top_n_tickers:
        dd = day_df_map.get(ticker)
        if dd is None or dd.empty:
            continue
        cc = "close" if "close" in dd.columns else "Close"
        or_mask = dd.index.time == or_close_t
        if not or_mask.any():
            continue
        ent = float(dd[or_mask].iloc[0][cc])
        if ent <= 0:
            continue
        for h in hold_ret:
            if h is None:
                xp = float(dd.iloc[-1][cc])
            else:
                xt = (datetime.combine(d, or_close_t) + timedelta(minutes=h)).time()
                xm = dd.index.time >= xt
                if not xm.any():
                    continue
                xp = float(dd[xm].iloc[0][cc])
            hold_ret[h].append((xp - ent) / ent)

    eod = hold_ret[None]
    if not eod:
        return None
    wins = [r for r in eod if r > 0]
    losses = [r for r in eod if r <= 0]
    LBL = {15: "+15m", 30: "+30m", 60: "+1h", 120: "+2h", 180: "+3h", 300: "+5h", None: "EOD"}
    hc = {
        LBL[h]: len([r for r in hold_ret[h] if r > 0]) / len(hold_ret[h])
        for h in hold_ret if hold_ret[h]
    }
    return DailyRegimeMetrics(
        date=d,
        signal_count=len(top_n_tickers),
        eod_wr=len(wins) / len(eod),
        avg_gain=sum(eod) / len(eod),
        avg_win=sum(wins) / len(wins) if wins else 0.0,
        avg_loss=sum(losses) / len(losses) if losses else 0.0,
        hold_curve=hc,
    )


# ── Fetch ────────────────────────────────────────────────────────────────────
print(f"\nFetching bars {FETCH_START} -> {ANALYSIS_END} for {len(TICKERS)} tickers ...")
ticker_bars = fetch_bars(
    TICKERS, FETCH_START, ANALYSIS_END, source="alpaca", feed=FEED, allow_intraday=False
)

all_days = sorted({
    row_date
    for df in ticker_bars.values() if not df.empty
    for row_date in df.index.normalize().unique().date
})

ticker_day_groups = {
    t: {d: df[df.index.date == d] for d in set(df.index.date)}
    for t, df in ticker_bars.items() if not df.empty
}
ticker_anchor_returns = _precompute_or_anchor_returns(ticker_day_groups, OR_START, OR_BARS)

eval_days = [d for d in all_days if ANALYSIS_START <= d <= ANALYSIS_END]
print(f"  {len(eval_days)} trading days in 2026 window\n")

# ── Pre-warm regime history from 2025 file ───────────────────────────────────
import json as _json

def _load_regime_file(path):
    try:
        with open(path) as f:
            return [DailyRegimeMetrics.from_dict(r) for r in _json.load(f)]
    except (FileNotFoundError, KeyError):
        return []

_prior_metrics = _load_regime_file("market_data/regime_state/regime_metrics_2025.json")
_prior_metrics.sort(key=lambda m: m.date)
# Keep only records before our analysis window (Dec 2025 tail)
_prior_metrics = [m for m in _prior_metrics if m.date < ANALYSIS_START]

print(f"Pre-warming regime engine with {len(_prior_metrics)} records from 2025 "
      f"({_prior_metrics[0].date} -> {_prior_metrics[-1].date})" if _prior_metrics else
      "No prior-year regime records found — starting cold")

# ── Sequential daily pass ─────────────────────────────────────────────────────
SKIP = {"SHORT", "NO_POSITION"}

daily_results = []
metrics_history = list(_prior_metrics)  # seed with prior-year tail

for d in eval_days:
    ranked = _rank_tickers_by_eod_win_rate(
        ticker_bars, d, OR_START, OR_BARS,
        lookback=WR_LOOKBACK,
        ticker_day_groups=ticker_day_groups,
        ticker_anchor_returns=ticker_anchor_returns,
    )
    top3 = [t for t, _ in ranked[:TOP_N]]
    top_pool = [t for t, _ in ranked[:REGIME_POOL]]

    engine = RegimeEngine.__new__(RegimeEngine)
    engine._history = sorted(metrics_history, key=lambda m: m.date)[-10:]
    regime = engine.get_current_regime(as_of_date=d)

    h_min = hold_minutes(regime.hold_window)
    trade = regime.direction not in SKIP

    rets = []
    if trade:
        for ticker in top3:
            dd = ticker_day_groups.get(ticker, {}).get(d)
            if dd is not None and not dd.empty:
                ret = ticker_return_at(dd, h_min)
                if ret is not None:
                    rets.append(ret)

    daily_results.append({
        "date": d,
        "top3": top3,
        "direction": regime.direction,
        "regime_type": regime.regime_type,
        "hold_window": regime.hold_window or "EOD",
        "source": regime.source,
        "trade": trade,
        "returns": rets,
        "avg_ret": sum(rets) / len(rets) if rets else None,
    })

    day_df_map = {t: ticker_day_groups.get(t, {}).get(d) for t in top_pool}
    day_df_map = {t: dd for t, dd in day_df_map.items() if dd is not None and not dd.empty}
    metrics = build_day_metrics(list(day_df_map.keys()), day_df_map, d)
    if metrics:
        metrics_history.append(metrics)


# ── Aggregation helpers ───────────────────────────────────────────────────────
def week_key(d):
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


traded = [r for r in daily_results if r["trade"] and r["avg_ret"] is not None]
skipped = [r for r in daily_results if not r["trade"]]

monthly = defaultdict(list)
weekly = defaultdict(list)
for r in traded:
    monthly[r["date"].strftime("%Y-%m")].append(r)
    weekly[week_key(r["date"])].append(r)

W = 96

# ── Monthly table ─────────────────────────────────────────────────────────────
print(f"\n{'─'*W}")
print(f"  2026 Expected Return — Random pick from top-{TOP_N} | Exit = RegimeEngine hold window")
print(f"  SHORT direction -> no trade  |  entry at OR-close ({or_close_t})")
print(f"{'─'*W}")
print(f"\n  {'Month':<10} {'Days':>5} {'Traded':>7} {'WR':>6} {'AvgRet':>8} {'TotalRet':>9} {'CumRet':>9}  Hold (mode)")
print(f"  {'─'*84}")

cum = 0.0
all_month_keys = sorted({r["date"].strftime("%Y-%m") for r in daily_results})
for mk in all_month_keys:
    month_all = [r for r in daily_results if r["date"].strftime("%Y-%m") == mk]
    rows = monthly.get(mk, [])
    skp = sum(1 for r in month_all if not r["trade"])
    if not rows:
        print(f"  {mk:<10} {len(month_all):>5} {'—':>7} {'—':>6} {'—':>8} {'—':>9} {'—':>9}  (all {skp} skipped)")
        continue
    rets = [r["avg_ret"] for r in rows]
    wr = sum(1 for r in rets if r > 0) / len(rets) * 100
    avg = sum(rets) / len(rets)
    tot = sum(rets)
    cum += tot
    holds = [r["hold_window"] for r in rows]
    main_hold = max(set(holds), key=holds.count)
    skip_note = f"  ({skp} skip)" if skp else ""
    print(
        f"  {mk:<10} {len(month_all):>5} {len(rows):>7} {wr:>5.0f}%"
        f" {avg:>+7.2f}% {tot:>+8.1f}% {cum:>+8.1f}%  {main_hold}{skip_note}"
    )

print(f"  {'─'*84}")
if traded:
    all_rets = [r["avg_ret"] for r in traded]
    wr_all = sum(1 for r in all_rets if r > 0) / len(all_rets) * 100
    print(
        f"  {'YTD':<10} {len(daily_results):>5} {len(traded):>7} {wr_all:>5.0f}%"
        f" {sum(all_rets)/len(all_rets):>+7.2f}% {sum(all_rets):>+8.1f}%"
        f"           (additive, not compounded)"
    )

# ── Weekly table ──────────────────────────────────────────────────────────────
print(f"\n  {'Week':<12} {'Days':>4} {'WR':>6} {'AvgRet':>8} {'TotalRet':>9}  Tickers seen  Hold")
print(f"  {'─'*84}")
for wk in sorted(weekly.keys()):
    rows = weekly[wk]
    rets = [r["avg_ret"] for r in rows]
    wr = sum(1 for r in rets if r > 0) / len(rets) * 100
    avg = sum(rets) / len(rets)
    tot = sum(rets)
    week_tickers = sorted({t for r in rows for t in r["top3"]})
    holds = [r["hold_window"] for r in rows]
    main_hold = max(set(holds), key=holds.count)
    ticker_str = ",".join(week_tickers)
    print(f"  {wk:<12} {len(rows):>4} {wr:>5.0f}% {avg:>+7.2f}% {tot:>+8.1f}%  {ticker_str:<32}  {main_hold}")

# ── Regime breakdown ──────────────────────────────────────────────────────────
print(f"\n  {'─'*W}")
print(f"  Regime distribution across {len(eval_days)} trading days:")
dir_counts = Counter(r["direction"] for r in daily_results)
type_counts = Counter(r["regime_type"] for r in daily_results)
hold_counts = Counter(r["hold_window"] for r in traded)
for k, n in dir_counts.most_common():
    pct = n / len(eval_days) * 100
    print(f"    direction  {k:<22} {n:>3}d  ({pct:.0f}%)")
print()
for k, n in type_counts.most_common():
    print(f"    type       {k:<32} {n:>3}d")
print()
for k, n in hold_counts.most_common():
    print(f"    hold_win   {k:<12} {n:>3}d")
print()
