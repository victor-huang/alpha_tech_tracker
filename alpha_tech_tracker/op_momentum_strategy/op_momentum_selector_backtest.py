import argparse
import pandas as pd
from datetime import date, datetime, timedelta

from alpaca.data.enums import DataFeed
from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import (
    build_bearish_regime_dates,
    build_qqq_extended_dates,
    build_qqq_or_alignment,
    compute_signals_with_backtest,
    fetch_bars,
    fetch_daily_bars,
)
from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector import (
    ACTIVELY_TRADE_TICKERS,
    DEFAULT_TICKERS,
    OPENING_BARS,
    OPENING_START_TIME,
    ROLLING_LOOKBACK_DAYS,
    STOP_PCT,
    compute_ticker_stats,
    score_ticker,
)

MIN_WINDOW_CAPITAL = 100.0
INITIAL_CAPITAL = 10_000.0
DOUBLEDOWN_START_MIN = 5  # min from OR close at which the DD check fires and addon enters


def _signal_dict_from_row(row) -> dict:
    or_range = row["or_high"] - row["or_low"]
    mid = row["midpoint"]
    entry = row["entry_price"]
    entry_vs_mid_pct = abs(entry - mid) / mid * 100 if mid != 0 else 0.0
    or_range_pct = or_range / entry * 100 if entry != 0 else 0.0
    return {
        "signal": row["signal"],
        "entry_vs_mid_pct": entry_vs_mid_pct,
        "or_range_pct": or_range_pct,
    }


def _normalize_windows(windows, opening_start_time, opening_bars):
    """
    Accept either a list of window dicts or fall back to the legacy single-window params.
    Each window dict: {"label": str, "opening_start": str, "opening_bars": int}
    """
    if windows:
        return windows
    return [
        {
            "label": "W1",
            "opening_start": opening_start_time,
            "opening_bars": opening_bars,
        }
    ]


def _compute_cap_pnl(row: dict, slot_capital: float) -> float:
    cap_pnl = (slot_capital / row["entry_price"]) * row["pnl"]
    for ep_key, pnl_key in (
        ("rev_entry_price", "rev_pnl"),
        ("br_entry_price", "br_pnl"),
        ("bru_entry_price", "bru_pnl"),
    ):
        ep = row.get(ep_key, 0)
        if ep:
            cap_pnl += (slot_capital / ep) * row.get(pnl_key, 0)
    return cap_pnl


def _compute_dd_deployed(rows: list) -> float:
    """
    Return the amount of freed capital redeployed into the DD addon leg for this window.

    Called after slot_capital is set on each row. The DD addon is still running when
    the next sequential window starts, so this amount must be deducted from the capital
    passed forward to that window.
    """
    winner = next((r for r in rows if "dd_freed_ranks" in r), None)
    if winner is None or winner.get("skipped"):
        return 0.0
    freed_rank_set = set(winner["dd_freed_ranks"])
    total = 0.0
    for r in rows:
        if r["rank"] not in freed_rank_set or r.get("skipped"):
            continue
        slot_cap = r.get("slot_capital", 0.0)
        if slot_cap > 0 and r.get("entry_price", 0) > 0:
            returned = slot_cap * (1.0 + r["pnl"] / r["entry_price"])
            total += max(0.0, returned)
    return total


def _apply_doubledown_window(rows: list) -> float:
    """
    Apply the double-down add-on P&L for a single window's rows.

    Requires slot_capital to be set on each row (called after _compute_cap_pnl).
    Mutates the winner row in-place (cap_pnl, dd_addon_cap_pnl, dd_freed_capital).
    Returns the addon dollar P&L added (0.0 if no DD fired).
    """
    winner = next((r for r in rows if "dd_freed_ranks" in r), None)
    if winner is None or winner.get("skipped"):
        return 0.0

    freed_rank_set = set(winner["dd_freed_ranks"])
    total_freed = 0.0
    for r in rows:
        if r["rank"] not in freed_rank_set or r.get("skipped"):
            continue
        slot_cap = r.get("slot_capital", 0.0)
        if slot_cap > 0 and r.get("entry_price", 0) > 0:
            returned = slot_cap * (1.0 + r["pnl"] / r["entry_price"])
            total_freed += max(0.0, returned)

    if total_freed <= 0:
        return 0.0

    addon_cap_pnl = total_freed * winner.get("dd_addon_pnl_pct", 0.0)
    winner["cap_pnl"] += addon_cap_pnl
    winner["dd_addon_cap_pnl"] = addon_cap_pnl
    winner["dd_freed_capital"] = total_freed

    # Fold DD addon into composite pnl_pct / success so the primary row's quality
    # score reflects the full day's performance (primary + REV + BRE + BRU + DD).
    dd_pct = winner.get("dd_addon_pnl_pct", 0.0) * 100  # fraction → percentage
    winner["pnl_pct"] = round(winner.get("pnl_pct", 0.0) + dd_pct, 3)
    winner["success"] = winner["pnl_pct"] > 0

    return addon_cap_pnl


def _apply_capital_flow(
    trade_rows: list,
    windows: list,
    initial_capital: float,
    weights: list,
    n: int,
    morning_split: list = None,
    min_capital: float = MIN_WINDOW_CAPITAL,
    compound: bool = False,
    enable_doubledown: bool = False,
) -> list:
    """
    Apply day-by-day capital flow across windows.

    Capital allocation rules:
      - First group (simultaneous): first len(morning_split) windows each get
        portfolio * morning_split[i] of capital deployed at the same time.
      - Sequential windows (remaining): each inherits all returned capital from
        the previous window (first_group_pnl flows into the first sequential
        window; each subsequent window gets the prior window's returned capital).
      - If a window's allocated capital < min_capital, it is skipped for that day
        and the available capital passes unchanged to the next sequential window.
      - compound=False (default): portfolio resets to initial_capital at the start
        of each day — isolates per-day strategy edge, good for strategy comparison.
      - compound=True: portfolio carries over day-to-day — reflects live account growth.

    DD capital recycling (enable_doubledown=True):
      For each sequential window Wk, available = base + pnl_acc - active_dd_capital,
      where active_dd_capital is the sum of freed capital from all preceding DDs whose
      winner has NOT yet exited by Wk's OR close time. If a DD exits before Wk starts,
      its capital naturally flows back in (no deduction). DD P&L is applied separately
      via _apply_doubledown() and does not affect sequential window sizing.

    Capital recycling between windows (timing-accurate):
      Each sequential window's available capital is computed from what has
      actually been returned by its drain time (OR close). Prior window trades
      that are still running at drain time have their slot_capital deducted;
      trades that exited before drain time contribute their cap_pnl. This
      matches live engine behaviour and correctly handles morning trades that
      hold past an afternoon window's start time.

    Mutates each trade row in-place, adding:
      - 'cap_pnl': actual dollar P&L for this trade given real capital allocation
      - 'window_capital': capital allocated to this window on this day
      - 'skipped': True if window was skipped due to insufficient capital

    Returns skip_log: list of dicts describing each window execution per day.
    """
    if morning_split is None:
        morning_split = [1.0]

    n_first = len(morning_split)
    window_labels = [w["label"] for w in windows]

    # OR close time (minutes from midnight) = drain time for each window.
    # Used both for DD leg lock-up detection and for sequential capital timing.
    drain_min: dict = {}
    for w in windows:
        h, m = map(int, w["opening_start"].split(":"))
        drain_min[w["label"]] = h * 60 + m + w["opening_bars"] * 5

    # Index trade_rows by (date, window) for fast lookup
    by_day_window = {}
    for row in trade_rows:
        key = (row["date"], row["window"])
        by_day_window.setdefault(key, []).append(row)

    trading_days = sorted({row["date"] for row in trade_rows})
    skip_log = []
    portfolio = initial_capital

    for d in trading_days:
        if not compound:
            portfolio = initial_capital

        # day_dds: list of (dd_deployed, winner_exit_min) for all DDs fired today.
        # Used by sequential windows to decide how much capital is still locked in DD.
        day_dds: list = []

        # --- First group: simultaneous windows, each gets portfolio * split[i] ---
        first_group_pnl = 0.0
        for i, label in enumerate(window_labels[:n_first]):
            win_capital = portfolio * morning_split[i]
            rows = by_day_window.get((d, label), [])
            skipped = win_capital < min_capital
            status = (
                "skipped_low_capital"
                if skipped
                else ("executed" if rows else "no_signal")
            )
            skip_log.append(
                {
                    "date": d,
                    "window": label,
                    "status": status,
                    "available_capital": round(win_capital, 2),
                    "picks": len(rows),
                }
            )
            win_pnl = 0.0
            for row in rows:
                row["window_capital"] = win_capital
                if skipped:
                    row["cap_pnl"] = 0.0
                    row["skipped"] = True
                else:
                    slot_capital = win_capital * weights[row["rank"] - 1]
                    row["slot_capital"] = slot_capital
                    row["cap_pnl"] = _compute_cap_pnl(row, slot_capital)
                    row["skipped"] = False
                    win_pnl += row["cap_pnl"]
            if enable_doubledown and not skipped:
                dd_dep = _compute_dd_deployed(rows)
                if dd_dep > 0:
                    winner = next((r for r in rows if "dd_freed_ranks" in r), None)
                    if winner is not None:
                        exit_min = (
                            drain_min[label] + (winner["bars_held"] + 1) * 5
                        )
                        day_dds.append((dd_dep, exit_min))
            first_group_pnl += win_pnl

        # --- Sequential windows ---
        # For each sequential window, available capital is computed from what has
        # actually been returned by its drain time, matching live engine behaviour:
        #   available = portfolio
        #             + cap_pnl for each prior row that exited before this drain
        #             - slot_capital for each prior row still running at this drain
        # This correctly handles morning trades that hold past an afternoon window's
        # start time — their capital is locked and unavailable until they close.
        seq_pnl = 0.0
        for i_seq, label in enumerate(window_labels[n_first:]):
            this_drain = drain_min[label]

            available = portfolio
            for prior_label in window_labels[:n_first + i_seq]:
                prior_drain = drain_min[prior_label]
                for row in by_day_window.get((d, prior_label), []):
                    if row.get("skipped"):
                        continue
                    # Add-on rows (BRE/BRU/REV) reuse freed capital from the primary
                    # slot — they don't deploy additional window capital, so they must
                    # not affect the available-capital calculation.
                    if (row.get("is_reversal") or row.get("is_bearish_reentry")
                            or row.get("is_bullish_reentry")):
                        continue
                    exit_time = prior_drain + row.get("bars_held", 0) * 5
                    if exit_time <= this_drain:
                        available += row.get("cap_pnl", 0.0)
                    else:
                        available -= row.get("slot_capital", 0.0)

            # Deduct capital from any DD legs still running at this window's drain.
            if enable_doubledown:
                for dd_dep, exit_min in day_dds:
                    if exit_min >= this_drain:
                        available -= dd_dep

            rows = by_day_window.get((d, label), [])
            skipped = available < min_capital
            status = (
                "skipped_low_capital"
                if skipped
                else ("executed" if rows else "no_signal")
            )
            skip_log.append(
                {
                    "date": d,
                    "window": label,
                    "status": status,
                    "available_capital": round(available, 2),
                    "picks": len(rows),
                }
            )
            win_pnl = 0.0
            for row in rows:
                row["window_capital"] = available
                if skipped:
                    row["cap_pnl"] = 0.0
                    row["skipped"] = True
                else:
                    slot_capital = available * weights[row["rank"] - 1]
                    row["slot_capital"] = slot_capital
                    row["cap_pnl"] = _compute_cap_pnl(row, slot_capital)
                    row["skipped"] = False
                    win_pnl += row["cap_pnl"]
            if enable_doubledown and not skipped:
                dd_dep = _compute_dd_deployed(rows)
                if dd_dep > 0:
                    winner = next((r for r in rows if "dd_freed_ranks" in r), None)
                    if winner is not None:
                        exit_min = (
                            drain_min[label] + (winner["bars_held"] + 1) * 5
                        )
                        day_dds.append((dd_dep, exit_min))
            if not skipped:
                seq_pnl += win_pnl

        portfolio += first_group_pnl + seq_pnl

    return skip_log


def _annotate_doubledown_addon(
    trade_rows: list,
    bars_by_date: dict,
    window_opening_times: dict,
    opening_bars_by_label: dict,
    doubledown_start_min: int = DOUBLEDOWN_START_MIN,
) -> None:
    """
    For each (date, window) group where rank-2+ positions stopped out before
    doubledown_start_min minutes after OR close, annotate the winner row with
    the add-on leg P&L.

    All picks in a window enter at OR close. The DD check fires at the fixed
    start time (OR close + doubledown_start_min) — not at the stopout bar.

    Add-on leg mechanics (backtested approximation):
    - Entry: close of the bar at OR close + doubledown_start_min.
    - Hard stop: entry ± 80% × (High − Low) of the check bar in the adverse
      direction — allows a small loss proportional to the bar's range.
    - Exit: winner's exit price (same trailing-stop path), or the hard stop
      price if the exit is beyond it.
    - P&L: signed return from addon_entry to effective exit (can be negative).

    At most one doubledown per window per day. All freed capital from multiple
    stopouts is combined into a single addon leg on the highest-ranked survivor.

    Mutates trade_rows in-place, adding to winner rows:
      dd_addon_pnl_pct        float  add-on return as fraction of addon entry (signed)
      dd_addon_stop_price     float  hard-stop price for the add-on leg
      dd_addon_effective_exit float  actual exit used (stop or winner exit)
      dd_addon_entry          float  add-on entry price
      dd_freed_ranks          list   ranks whose freed capital flows to the winner
    """
    stop_reasons = {"hard_stop", "fallback_20pct"}
    # 0-indexed bar index at OR close + doubledown_start_min
    dd_bars = doubledown_start_min // 5  # 5 min → 1, 15 min → 3, 50 min → 10

    by_day_window: dict = {}
    for row in trade_rows:
        key = (row["date"], row["window"])
        by_day_window.setdefault(key, []).append(row)

    for (d, label), rows in by_day_window.items():
        if len(rows) < 2:
            continue

        rows_by_rank = sorted(rows, key=lambda r: r["rank"])

        # Partition into stopouts and survivors at the 15-min mark.
        # A rank is only a "stopout" (capital freed) if it stopped early AND has no
        # reversal/re-entry — if it does, the capital was redeployed into that leg,
        # not freed for doubledown.
        def _has_reentry(r):
            return (
                r.get("rev_entry_price", 0) != 0
                or r.get("br_entry_price", 0) != 0
                or r.get("bru_entry_price", 0) != 0
            )

        stopouts = [
            r for r in rows_by_rank
            if r.get("exit_reason", "") in stop_reasons
            and r.get("bars_held", 999) <= dd_bars
            and not _has_reentry(r)
        ]
        survivors = [
            r for r in rows_by_rank
            if not (
                r.get("exit_reason", "") in stop_reasons
                and r.get("bars_held", 999) <= dd_bars
                and not _has_reentry(r)
            )
        ]

        if not stopouts or not survivors:
            continue

        # Winner = highest-ranked survivor (lowest rank number).
        # Freed capital from ALL stopouts flows to this one position.
        winner = survivors[0]

        # If the winner already exited before the addon entry bar, the addon
        # can't fire — there is no open position to add on to.
        if winner.get("bars_held", 0) < dd_bars:
            continue
        freed_ranks = [r["rank"] for r in stopouts]

        # Look up the doubledown bar close for the winner's ticker.
        opening_bars = opening_bars_by_label.get(label, 3)
        opening_start = window_opening_times.get(label)
        if opening_start is None:
            continue

        day_bars = bars_by_date.get(winner["ticker"], {}).get(d)
        if day_bars is None or day_bars.empty:
            continue

        or_close_time = (
            datetime.combine(d, opening_start) + timedelta(minutes=opening_bars * 5)
        ).time()
        post_or = day_bars[day_bars.index.time >= or_close_time]
        if len(post_or) <= dd_bars:
            continue

        addon_bar = post_or.iloc[dd_bars]
        addon_entry = float(addon_bar["Close"])
        if addon_entry == 0:
            continue

        exit_price = float(winner["exit_price"])
        bar_range = float(addon_bar["High"]) - float(addon_bar["Low"])
        if winner["signal"] == "BULLISH":
            stop_price = addon_entry - 0.80 * bar_range
            effective_exit = max(exit_price, stop_price)
            raw_pct = (effective_exit - addon_entry) / addon_entry
        else:
            stop_price = addon_entry + 0.80 * bar_range
            effective_exit = min(exit_price, stop_price)
            raw_pct = (addon_entry - effective_exit) / addon_entry

        winner["dd_addon_pnl_pct"] = raw_pct
        winner["dd_addon_entry"] = addon_entry
        winner["dd_addon_stop_price"] = stop_price
        winner["dd_addon_effective_exit"] = effective_exit
        winner["dd_freed_ranks"] = freed_ranks


def run_selector_backtest(
    n: int,
    tickers: list,
    eval_start: date,
    eval_end: date,
    lookback_days: int = ROLLING_LOOKBACK_DAYS,
    opening_bars: int = OPENING_BARS,
    opening_start_time: str = OPENING_START_TIME,
    bearish_ma200: bool = False,
    stop_pct: float = STOP_PCT,
    source: str = "alpaca",
    trailing_ma: str = "ma20",
    max_loss_pct: float = None,
    armed_ma20_exit: bool = False,
    regime_filter: bool = False,
    regime_ma: int = 5,
    windows: list = None,
    dedup: bool = False,
    enable_reversal: bool = False,
    reversal_max_bars_held: int = 3,
    min_or_range: float = 0.0,
    min_or_range_windows: list = None,
    min_ma200_distance: float = 0.0,
    min_ma200_distance_windows: list = None,
    min_score: float = 0.0,
    min_ev: float = 0.0,
    or_bar_lookback: int = 3,
    enable_bearish_reentry: bool = False,
    bearish_reentry_max_bars: int = 3,
    enable_bullish_reentry: bool = False,
    bullish_reentry_max_bars: int = 5,
    close_top_pct: float = None,
    feed: DataFeed = None,
    enable_doubledown: bool = False,
    doubledown_start_min: int = DOUBLEDOWN_START_MIN,
    filter_flat_or: bool = True,
    qqq_align_filter: bool = False,
    qqq_align_threshold: float = 0.50,
    qqq_extend_days: int = 0,
    qqq_extend_pct: float = 0.05,
    qqq_extend_max_dd: float = 0.0,
) -> tuple:
    """
    Walk each trading day in [eval_start, eval_end], apply rolling selector
    scoring to pick top-N tickers per window, and record actual trade outcomes.

    windows: list of {"label", "opening_start", "opening_bars"} dicts.
             Falls back to single window from opening_start_time/opening_bars if omitted.
    dedup:   if True, skip a ticker in later windows if already picked by an earlier window that day.

    Returns (trade_rows, all_window_results, trading_days) where:
      - trade_rows: list of dicts, one per selected trade (includes "window" key)
      - all_window_results: {window_label: {ticker: results_df}}
      - trading_days: sorted list of date objects in the eval window
    """
    windows = _normalize_windows(windows, opening_start_time, opening_bars)
    n_windows = len(windows)

    fetch_start = eval_start - timedelta(days=lookback_days)
    print(f"Fetching bars for {len(tickers)} tickers ({eval_start} → {eval_end})...")
    all_bars = fetch_bars(tickers, fetch_start, eval_end, source=source, feed=feed)

    # Regime dates must cover the full fetch window (lookback + eval) so that rolling
    # stats for each day are computed on regime-filtered signals, matching the selector.
    bearish_regime_dates = (
        build_bearish_regime_dates(fetch_start, eval_end, source, regime_ma, feed=feed)
        if regime_filter
        else None
    )

    # Build per-window QQQ alignment skip sets (one pair per window opening config).
    qqq_align_by_window = {}
    if qqq_align_filter:
        built_configs = {}
        for win in windows:
            key = (win["opening_bars"], win["opening_start"])
            if key not in built_configs:
                built_configs[key] = build_qqq_or_alignment(
                    fetch_start, eval_end,
                    win["opening_bars"], win["opening_start"],
                    source, feed, qqq_align_threshold,
                )
            qqq_align_by_window[win["label"]] = built_configs[key]

        # Gate: if extend_days is set, only apply alignment filter on days where QQQ
        # has risen too much too fast. Intersection narrows the skip sets so that on
        # normal trending days the filter stays off.
        if qqq_extend_days > 0:
            extend_dates = build_qqq_extended_dates(
                fetch_start, eval_end,
                qqq_extend_days, qqq_extend_pct, qqq_extend_max_dd,
                source, feed,
            )
            for label in qqq_align_by_window:
                sb, sr = qqq_align_by_window[label]
                qqq_align_by_window[label] = (sb & extend_dates, sr & extend_dates)

    print(f"Pre-computing MA columns for {len(tickers)} tickers...")
    for ticker in tickers:
        df = all_bars.get(ticker, pd.DataFrame())
        if df.empty:
            continue
        df["MA20"] = df["Close"].rolling(20).mean()
        df["MA50"] = df["Close"].rolling(50).mean()
        df["MA200"] = df["Close"].rolling(200).mean()
        all_bars[ticker] = df

    print(f"Pre-computing signals for {n_windows} window(s)...")
    all_window_results = {}
    for win in windows:
        label = win["label"]
        results_for_window = {}
        for ticker in tickers:
            df = all_bars.get(ticker, pd.DataFrame())
            if df.empty:
                results_for_window[ticker] = pd.DataFrame()
                continue
            _qqq_sb, _qqq_sr = qqq_align_by_window.get(label, (None, None))
            results_for_window[ticker] = compute_signals_with_backtest(
                df,
                win["opening_bars"],
                bearish_ma200,
                stop_pct,
                opening_start_time=win["opening_start"],
                trailing_ma=trailing_ma,
                max_loss_pct=max_loss_pct,
                armed_ma20_exit=armed_ma20_exit,
                bearish_regime_dates=bearish_regime_dates,
                enable_reversal=enable_reversal,
                reversal_max_bars_held=reversal_max_bars_held,
                or_bar_lookback=or_bar_lookback,
                enable_bearish_reentry=enable_bearish_reentry,
                bearish_reentry_max_bars=bearish_reentry_max_bars,
                enable_bullish_reentry=enable_bullish_reentry,
                bullish_reentry_max_bars=bullish_reentry_max_bars,
                close_top_pct=win.get("close_top_pct", close_top_pct),
                filter_flat_or=filter_flat_or,
                qqq_align_skip_bull=_qqq_sb,
                qqq_align_skip_bear=_qqq_sr,
            )
        all_window_results[label] = results_for_window
        print(f"  [{label}] {win['opening_start']} / {win['opening_bars']} bars — done")

    trading_days = sorted(
        {
            d
            for df in all_bars.values()
            if not df.empty
            for d in df.index.date
            if eval_start <= d <= eval_end
        }
    )

    # Pre-group bars by date: replaces O(total_bars) index.date scan with O(1) dict lookup
    # in the or_bar_lookback scoring path, called 16 tickers × N windows × N days.
    bars_by_date = {
        ticker: {d_: g for d_, g in df.groupby(df.index.date)}
        for ticker, df in all_bars.items()
        if not df.empty
    }

    # Pre-filter primary-only signal rows per window per ticker: eliminates re-applying
    # the three is_reversal/is_bearish_reentry/is_bullish_reentry conditions every day.
    primary_window_results = {
        label: {
            ticker: (
                df[
                    (df["is_reversal"] != True)           # noqa: E712
                    & (df["is_bearish_reentry"] != True)  # noqa: E712
                    & (df["is_bullish_reentry"] != True)  # noqa: E712
                ]
                if not df.empty
                else df
            )
            for ticker, df in results_for_window.items()
        }
        for label, results_for_window in all_window_results.items()
    }

    # Pre-group all signal rows by (window, ticker, date): replaces linear date scan
    # in today_rows lookup with O(1) dict lookup.
    results_by_date = {
        label: {
            ticker: ({d_: g for d_, g in df.groupby("date")} if not df.empty else {})
            for ticker, df in results_for_window.items()
        }
        for label, results_for_window in all_window_results.items()
    }

    # Pre-parse window opening times (avoids strptime on every trading day).
    window_opening_times = {
        win["label"]: datetime.strptime(win["opening_start"], "%H:%M").time()
        for win in windows
    }

    trade_rows = []
    for d in trading_days:
        lookback_start = d - timedelta(days=lookback_days)
        picked_today = set()

        for win in windows:
            label = win["label"]
            full_results = all_window_results[label]

            rolling_stats = {}
            for ticker in tickers:
                primary_results = primary_window_results[label].get(ticker, pd.DataFrame())
                if primary_results.empty:
                    rolling_stats[ticker] = compute_ticker_stats(pd.DataFrame())
                    continue
                window_slice = primary_results[
                    (primary_results["date"] >= lookback_start)
                    & (primary_results["date"] < d)
                ]
                rolling_stats[ticker] = compute_ticker_stats(window_slice)

            scored = []
            opening_start_t = window_opening_times[label]
            for ticker in tickers:
                if dedup and ticker in picked_today:
                    continue
                today_rows = results_by_date[label].get(ticker, {}).get(d)
                if today_rows is None or today_rows.empty:
                    continue
                # Use primary (non-reversal) row for scoring; reversal row carries
                # the extra leg P&L that gets added to the capital sim below.
                primary_today = today_rows[
                    (today_rows["is_reversal"] != True)  # noqa: E712
                    & (today_rows["is_bearish_reentry"] != True)  # noqa: E712
                    & (today_rows["is_bullish_reentry"] != True)  # noqa: E712
                ]
                if primary_today.empty:
                    continue
                row = primary_today.iloc[0]
                rev_today = today_rows[today_rows["is_reversal"] == True]
                rev_row = rev_today.iloc[0] if not rev_today.empty else None
                br_today = today_rows[today_rows["is_bearish_reentry"] == True]
                br_row = br_today.iloc[0] if not br_today.empty else None
                bru_today = today_rows[today_rows["is_bullish_reentry"] == True]
                bru_row = bru_today.iloc[0] if not bru_today.empty else None
                sig = _signal_dict_from_row(row)
                if (
                    min_or_range_windows is None or label in min_or_range_windows
                ) and sig["or_range_pct"] < min_or_range:
                    continue
                if min_ma200_distance > 0 and (
                    min_ma200_distance_windows is None or label in min_ma200_distance_windows
                ):
                    ma200 = row.get("ma200", float("nan"))
                    entry_price = row.get("entry_price", 0.0)
                    if not pd.isna(ma200) and ma200 > 0:
                        pct_above_ma200 = (entry_price - ma200) / ma200 * 100
                        if pct_above_ma200 < min_ma200_distance:
                            continue
                if or_bar_lookback > 0:
                    day_df = bars_by_date.get(ticker, {}).get(d)
                    if day_df is not None:
                        pre_opening = day_df[day_df.index.time < opening_start_t].tail(
                            or_bar_lookback
                        )
                        if len(pre_opening) > 0:
                            avg_recent_bar_range = (
                                pre_opening["High"] - pre_opening["Low"]
                            ).mean()
                            or_range = row["or_high"] - row["or_low"]
                            if or_range < avg_recent_bar_range / 4:
                                entry = row["entry_price"]
                                sig["or_range_pct"] = (
                                    avg_recent_bar_range / entry * 100
                                    if entry != 0
                                    else 0.0
                                )
                stats = rolling_stats[ticker]
                if stats["ev_trade"] < min_ev:
                    continue
                s = score_ticker(sig, stats)
                if s == 0.0:
                    continue
                if s < min_score:
                    continue
                scored.append(
                    {
                        "ticker": ticker,
                        "score": round(s, 3),
                        "signal": row["signal"],
                        "entry_price": row["entry_price"],
                        "exit_price": row["exit_price"],
                        "or_high": float(row["or_high"]),
                        "or_low": float(row["or_low"]),
                        "midpoint": row["midpoint"],
                        "pnl": row["pnl"],
                        "success": bool(row["success"]),
                        "exit_reason": row["exit_reason"],
                        "entry_vs_mid_pct": round(sig["entry_vs_mid_pct"], 3),
                        "or_range_pct": round(sig["or_range_pct"], 3),
                        "rolling_ev": round(stats["ev_trade"], 3),
                        "rolling_win_rate": round(stats["win_rate"], 3),
                        "rev_pnl": float(rev_row["pnl"])
                        if rev_row is not None
                        else 0.0,
                        "rev_entry_price": float(rev_row["entry_price"])
                        if rev_row is not None
                        else 0.0,
                        "rev_exit_price": float(rev_row["exit_price"])
                        if rev_row is not None
                        else 0.0,
                        "rev_exit_reason": str(rev_row["exit_reason"])
                        if rev_row is not None
                        else "",
                        "br_pnl": float(br_row["pnl"]) if br_row is not None else 0.0,
                        "br_entry_price": float(br_row["entry_price"])
                        if br_row is not None
                        else 0.0,
                        "br_exit_price": float(br_row["exit_price"])
                        if br_row is not None
                        else 0.0,
                        "br_exit_reason": str(br_row["exit_reason"])
                        if br_row is not None
                        else "",
                        "bru_pnl": float(bru_row["pnl"])
                        if bru_row is not None
                        else 0.0,
                        "bru_entry_price": float(bru_row["entry_price"])
                        if bru_row is not None
                        else 0.0,
                        "bru_exit_price": float(bru_row["exit_price"])
                        if bru_row is not None
                        else 0.0,
                        "bru_exit_reason": str(bru_row["exit_reason"])
                        if bru_row is not None
                        else "",
                        "bars_held": int(row["bars_held"]),
                        "mins_held": int(row["mins_held"]),
                    }
                )

            scored.sort(key=lambda x: x["score"], reverse=True)
            for rank, pick in enumerate(scored[:n], 1):
                picked_today.add(pick["ticker"])
                primary_pnl_pct = pick["pnl"] / pick["entry_price"] * 100
                rev_pnl_pct = (
                    pick["rev_pnl"] / pick["rev_entry_price"] * 100
                    if pick["rev_entry_price"] != 0
                    else 0.0
                )
                br_pnl_pct = (
                    pick["br_pnl"] / pick["br_entry_price"] * 100
                    if pick["br_entry_price"] != 0
                    else 0.0
                )
                bru_pnl_pct = (
                    pick["bru_pnl"] / pick["bru_entry_price"] * 100
                    if pick["bru_entry_price"] != 0
                    else 0.0
                )
                combined_pnl_pct = (
                    primary_pnl_pct + rev_pnl_pct + br_pnl_pct + bru_pnl_pct
                )
                _h, _m = map(int, win["opening_start"].split(":"))
                _or_close_min = _h * 60 + _m + win["opening_bars"] * 5
                trade_rows.append(
                    {
                        "date": d,
                        "window": label,
                        "rank": rank,
                        "or_close_min": _or_close_min,
                        "pnl_pct": round(combined_pnl_pct, 3),
                        "success": combined_pnl_pct > 0,
                        # cap_pnl, window_capital, skipped filled in by _apply_capital_flow
                        "cap_pnl": 0.0,
                        "window_capital": 0.0,
                        "skipped": False,
                        **{
                            k: v
                            for k, v in pick.items()
                            if k
                            not in (
                                "success",
                                "br_pnl",
                                "br_entry_price",
                                "br_exit_price",
                                "br_exit_reason",
                                "bru_pnl",
                                "bru_entry_price",
                                "bru_exit_price",
                                "bru_exit_reason",
                            )
                        },
                        "br_pnl": pick["br_pnl"],
                        "br_entry_price": pick["br_entry_price"],
                        "br_exit_price": pick["br_exit_price"],
                        "br_exit_reason": pick["br_exit_reason"],
                        "bru_pnl": pick["bru_pnl"],
                        "bru_entry_price": pick["bru_entry_price"],
                        "bru_exit_price": pick["bru_exit_price"],
                        "bru_exit_reason": pick["bru_exit_reason"],
                    }
                )

    if enable_doubledown:
        opening_bars_by_label = {win["label"]: win["opening_bars"] for win in windows}
        _annotate_doubledown_addon(
            trade_rows, bars_by_date, window_opening_times, opening_bars_by_label,
            doubledown_start_min=doubledown_start_min,
        )

    return trade_rows, all_window_results, trading_days


def _apply_doubledown(trade_rows: list) -> None:
    """
    Apply double-down add-on P&L across all windows in trade_rows.

    Called after _apply_capital_flow so that DD P&L is NOT recycled into
    sequential window (A1/A2) capital. The DD leg runs to its own natural
    exit (trailing stop or EOD) independently — A1/A2 use only the base
    primary-leg capital, not freed capital from the DD addon.
    """
    by_day_window: dict = {}
    for row in trade_rows:
        key = (row["date"], row["window"])
        by_day_window.setdefault(key, []).append(row)

    for rows in by_day_window.values():
        _apply_doubledown_window(rows)


def _apply_opportunity_pool(
    trade_rows: list,
    windows: list,
    initial_pool: float,
    compound: bool = False,
    doubledown_start_min: int = DOUBLEDOWN_START_MIN,
) -> None:
    """
    Deploy the opportunity pool on DD-eligible winner rows, recycling capital
    sequentially within each day across windows.

    Requires _annotate_doubledown_addon and _apply_capital_flow to have run first.
    Mutates winner rows in-place, adding:
      opp_deployed   float  capital deployed from pool at this window's DD
      opp_cap_pnl    float  dollar P&L from the deployment (signed)
      opp_returned   float  capital returned after exit (floor 0)
    Also folds opp_cap_pnl into winner["cap_pnl"] so weekly/monthly totals pick it up.
    """
    if initial_pool <= 0:
        return

    dd_bars = doubledown_start_min // 5
    window_labels = [w["label"] for w in windows]

    or_close_min_by_label = {}
    for w in windows:
        h, m = map(int, w["opening_start"].split(":"))
        or_close_min_by_label[w["label"]] = h * 60 + m + w["opening_bars"] * 5

    by_day_window: dict = {}
    for row in trade_rows:
        key = (row["date"], row["window"])
        by_day_window.setdefault(key, []).append(row)

    trading_days = sorted({row["date"] for row in trade_rows})
    pool = initial_pool

    for d in trading_days:
        if not compound:
            pool = initial_pool

        pool_exit_min = 0  # 0 = pool is free; set after each deployment

        for label in window_labels:
            or_close_min = or_close_min_by_label[label]
            dd_fire_min = or_close_min + dd_bars * 5

            if pool_exit_min > dd_fire_min:
                continue  # prior deployment still running — pool locked

            if pool <= 0:
                continue

            rows = by_day_window.get((d, label), [])
            winner = next(
                (r for r in rows if "dd_freed_ranks" in r and not r.get("skipped")),
                None,
            )
            if winner is None:
                continue

            if winner.get("bars_held", 0) < dd_bars:
                continue  # safety guard (annotation already enforces this)

            pnl_pct = winner.get("dd_addon_pnl_pct", 0.0)
            opp_cap_pnl = pool * pnl_pct
            opp_returned = max(pool + opp_cap_pnl, 0.0)

            winner["opp_deployed"] = pool
            winner["opp_cap_pnl"] = opp_cap_pnl
            winner["opp_returned"] = opp_returned
            winner["cap_pnl"] = winner.get("cap_pnl", 0.0) + opp_cap_pnl

            pool = opp_returned

            if winner.get("exit_reason") == "end_of_day":
                pool_exit_min = 960
            else:
                pool_exit_min = or_close_min + (winner["bars_held"] + 1) * 5


def _collect_baseline(
    all_window_results: dict, eval_start: date, eval_end: date
) -> pd.DataFrame:
    first_window_results = next(iter(all_window_results.values()))
    frames = []
    for ticker, df in first_window_results.items():
        if df.empty:
            continue
        window = df[(df["date"] >= eval_start) & (df["date"] <= eval_end)].copy()
        if window.empty:
            continue
        window["ticker"] = ticker
        frames.append(window)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _parse_weights(weights_input: list, n: int) -> list:
    """Return per-rank capital fractions for the top-n positions.

    When more weights than n are provided (e.g. --weights 50 30 20 with --top 2),
    the first n weights are used and the remainder is undeployed capital — matching
    the live engine's rank-indexed weight assignment.  The fractions are normalised
    relative to the *total* of all provided weights so the caller's intent (e.g.
    50%/30%/20%) is preserved; only n of them are returned.
    """
    if not weights_input:
        return [1.0 / n] * n
    total = sum(weights_input)
    fracs = [w / total for w in weights_input]
    if len(fracs) >= n:
        return fracs[:n]
    return [1.0 / n] * n


def _weights_label(weights: list, initial_capital: float) -> str:
    if len(set(round(w, 6) for w in weights)) == 1:
        return f"${initial_capital * weights[0]:,.0f}/slot × {len(weights)} slots"
    pcts = "/".join(f"{w * 100:.0f}%" for w in weights)
    return f"weighted {pcts} × {len(weights)} slots"


def _print_skip_log(skip_log: list, windows: list):
    if not skip_log:
        return
    sep = "\u2501" * 80
    print(f"\n{sep}")
    print(f"  WINDOW EXECUTION LOG")
    print(sep)
    print(f"  {'Date':<12} {'Window':<8} {'Status':<22} {'Capital':>10}  {'Picks':>5}")
    print(f"  {'─' * 76}")

    skipped_count = 0
    executed_count = 0
    no_signal_count = 0

    prev_date = None
    for entry in skip_log:
        d = entry["date"]
        if d != prev_date and prev_date is not None:
            print(f"  {'─' * 76}")
        prev_date = d

        status = entry["status"]
        cap = entry["available_capital"]
        picks = entry["picks"]

        if status == "skipped_low_capital":
            skipped_count += 1
            status_display = "SKIPPED (low capital)"
        elif status == "no_signal":
            no_signal_count += 1
            status_display = "no signal"
        else:
            executed_count += 1
            status_display = f"executed ({picks} picks)"

        print(
            f"  {str(d):<12} {entry['window']:<8} {status_display:<22} ${cap:>9,.2f}  {picks:>5}"
        )

    print(f"  {'─' * 76}")
    print(
        f"  Executed: {executed_count}  |  No signal: {no_signal_count}  |  Skipped (low capital): {skipped_count}"
    )
    print(sep)


_REENTRY_TYPES = [
    ("[REV]", "rev_entry_price", "rev_pnl", "rev_exit_price", "rev_exit_reason"),
    ("[BRE]", "br_entry_price", "br_pnl", "br_exit_price", "br_exit_reason"),
    ("[BRU]", "bru_entry_price", "bru_pnl", "bru_exit_price", "bru_exit_reason"),
]


def _print_reentry_subrow(
    row: dict,
    label: str,
    ep_key: str,
    pnl_key: str,
    exit_price_key: str,
    exit_reason_key: str,
    multi_window: bool,
):
    ep = row.get(ep_key, 0)
    if not ep:
        return None
    p = row[pnl_key]
    pct = p / ep * 100
    pnl_str = f"+${abs(p):.2f}" if p >= 0 else f"-${abs(p):.2f}"
    pct_str = f"+{abs(pct):.2f}%" if pct >= 0 else f"{pct:.2f}%"
    result = "WIN" if p > 0 else "LOSS"
    blank_win = f"{'':5} " if multi_window else ""
    print(
        f"  {'':12} {blank_win}{'':5} {'':6} "
        f"{label:<9} {'':>5}  "
        f"{'':>5} {'':>5}  "
        f"{ep:>7.2f} {row[exit_price_key]:>7.2f} "
        f"{pnl_str:>7} {pct_str:>7}  {result:<6}  {row[exit_reason_key]}"
    )
    return p, pct


def _print_daily_table(
    trade_rows: list,
    n: int,
    initial_capital: float = INITIAL_CAPITAL,
    weights: list = None,
    multi_window: bool = False,
):
    def _fmt_bar_time(minutes: int) -> str:
        return f"{minutes // 60:02d}:{minutes % 60:02d}"

    def _entry_exit_times(row) -> tuple:
        or_close = row.get("or_close_min")
        if or_close is None:
            return "—", "—"
        entry_str = _fmt_bar_time(or_close)
        if row.get("exit_reason") == "end_of_day":
            exit_str = "16:00"
        else:
            exit_str = _fmt_bar_time(or_close + (row.get("bars_held", 0) + 1) * 5)
        return entry_str, exit_str

    weights = weights or _parse_weights(None, n)
    active_rows = [r for r in trade_rows if not r.get("skipped")]
    sep = "\u2501" * 110
    win_col = f"{'Win':<5} " if multi_window else ""
    print(f"\n{sep}")
    print(
        f"  {'Date':<12} {win_col}{'Rank':<5} {'Ticker':<6} {'Signal':<9} {'Score':>5}  "
        f"{'In':>5} {'Out':>5}  {'Entry':>7} {'Exit':>7} {'P&L$':>7} {'P&L%':>7}  {'Result':<6}  Exit Reason"
    )
    print(sep)

    current_date = None
    current_window = None
    day_pnl = 0.0
    day_pnl_pcts = []
    day_wins = 0
    day_losses = 0
    running_total = 0.0
    day_cap_pnl = 0.0
    portfolio = initial_capital

    for row in active_rows:
        row_date = row["date"]
        row_window = row["window"]

        if row_date != current_date:
            if current_date is not None:
                portfolio += day_cap_pnl
                _print_day_summary(
                    day_wins,
                    day_losses,
                    day_pnl,
                    day_pnl_pcts,
                    running_total,
                    day_cap_pnl,
                    initial_capital,
                    portfolio,
                    multi_window=multi_window,
                )
            current_date = row_date
            current_window = None
            day_pnl = 0.0
            day_pnl_pcts = []
            day_wins = 0
            day_losses = 0
            day_cap_pnl = 0.0

        if multi_window and row_window != current_window:
            if current_window is not None:
                print(f"  {'·' * 108}")
            current_window = row_window

        pnl = row["pnl"]
        pnl_pct = pnl / row["entry_price"] * 100
        result = "WIN" if pnl > 0 else "LOSS"
        pnl_str = f"+${abs(pnl):.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
        pnl_pct_str = f"+{abs(pnl_pct):.2f}%" if pnl_pct >= 0 else f"{pnl_pct:.2f}%"
        win_str = f"{row_window:<5} " if multi_window else ""
        t_in, t_out = _entry_exit_times(row)

        print(
            f"  {str(row_date):<12} {win_str}{row['rank']:<5} {row['ticker']:<6} "
            f"{row['signal']:<9} {row['score']:>5.2f}  "
            f"{t_in:>5} {t_out:>5}  "
            f"{row['entry_price']:>7.2f} {row['exit_price']:>7.2f} "
            f"{pnl_str:>7} {pnl_pct_str:>7}  {result:<6}  {row['exit_reason']}"
        )

        day_pnl += pnl
        day_pnl_pcts.append(pnl_pct)
        running_total += pnl
        day_cap_pnl += row["cap_pnl"]
        if pnl > 0:
            day_wins += 1
        else:
            day_losses += 1

        for (
            _label,
            _ep_key,
            _pnl_key,
            _exit_price_key,
            _exit_reason_key,
        ) in _REENTRY_TYPES:
            sub = _print_reentry_subrow(
                row,
                _label,
                _ep_key,
                _pnl_key,
                _exit_price_key,
                _exit_reason_key,
                multi_window,
            )
            if sub is not None:
                p, pct = sub
                day_pnl += p
                day_pnl_pcts.append(pct)
                running_total += p
                if p > 0:
                    day_wins += 1
                else:
                    day_losses += 1

        dd_cap_pnl = row.get("dd_addon_cap_pnl", 0.0)
        if dd_cap_pnl != 0.0:
            freed = row.get("dd_freed_capital", 0.0)
            addon_entry = row.get("dd_addon_entry", 0.0)
            freed_ranks = row.get("dd_freed_ranks", [])
            effective_exit = row.get("dd_addon_effective_exit", float(row["exit_price"]))
            if row["signal"] == "BULLISH":
                per_share = effective_exit - addon_entry
            else:
                per_share = addon_entry - effective_exit
            pnl_pct = per_share / addon_entry * 100 if addon_entry else 0.0
            pnl_str = f"+${per_share:.2f}" if per_share >= 0 else f"-${abs(per_share):.2f}"
            pct_str = f"+{pnl_pct:.2f}%" if pnl_pct >= 0 else f"{pnl_pct:.2f}%"
            outcome = "WIN" if per_share >= 0 else "LOSS"
            blank_win = f"{'':5} " if multi_window else ""
            ranks_str = "/".join(f"R{r}" for r in freed_ranks)
            print(
                f"  {'':12} {blank_win}{'':5} {'':6} "
                f"{'[DD]':<9} {'':>5}  "
                f"{addon_entry:>7.2f} {effective_exit:>7.2f} "
                f"{pnl_str:>7} {pct_str:>7}  {outcome:<6}  freed ${freed:.0f} ← {ranks_str}"
            )

        opp_cap_pnl = row.get("opp_cap_pnl")
        if opp_cap_pnl is not None:
            opp_deployed = row.get("opp_deployed", 0.0)
            opp_returned = row.get("opp_returned", 0.0)
            addon_entry = row.get("dd_addon_entry", 0.0)
            effective_exit = row.get("dd_addon_effective_exit", float(row["exit_price"]))
            if row["signal"] == "BULLISH":
                per_share = effective_exit - addon_entry
            else:
                per_share = addon_entry - effective_exit
            pnl_pct = per_share / addon_entry * 100 if addon_entry else 0.0
            pnl_str = f"+${per_share:.2f}" if per_share >= 0 else f"-${abs(per_share):.2f}"
            pct_str = f"+{pnl_pct:.2f}%" if pnl_pct >= 0 else f"{pnl_pct:.2f}%"
            outcome = "WIN" if opp_cap_pnl >= 0 else "LOSS"
            opp_net_str = (
                f"+${abs(opp_cap_pnl):.2f}" if opp_cap_pnl >= 0 else f"-${abs(opp_cap_pnl):.2f}"
            )
            blank_win = f"{'':5} " if multi_window else ""
            print(
                f"  {'':12} {blank_win}{'':5} {'':6} "
                f"{'[OPP]':<9} {'':>5}  "
                f"{addon_entry:>7.2f} {effective_exit:>7.2f} "
                f"{pnl_str:>7} {pct_str:>7}  {outcome:<6}  "
                f"pool ${opp_deployed:,.0f} → ${opp_returned:,.0f}  ({opp_net_str})"
            )

    if current_date is not None:
        portfolio += day_cap_pnl
        _print_day_summary(
            day_wins,
            day_losses,
            day_pnl,
            day_pnl_pcts,
            running_total,
            day_cap_pnl,
            initial_capital,
            portfolio,
            multi_window=multi_window,
        )

    print(sep)


def _print_day_summary(
    wins,
    losses,
    day_pnl,
    day_pnl_pcts,
    running_total,
    day_cap_pnl,
    initial_capital,
    portfolio,
    multi_window: bool = False,
):
    total = wins + losses
    if total == 0:
        return
    pnl_str = f"+${abs(day_pnl):.2f}" if day_pnl >= 0 else f"-${abs(day_pnl):.2f}"
    avg_pct = sum(day_pnl_pcts) / len(day_pnl_pcts)
    avg_pct_str = f"+{abs(avg_pct):.2f}%" if avg_pct >= 0 else f"{avg_pct:.2f}%"
    cap_pnl_str = (
        f"+${abs(day_cap_pnl):.2f}" if day_cap_pnl >= 0 else f"-${abs(day_cap_pnl):.2f}"
    )
    day_ret_pct = day_cap_pnl / initial_capital * 100
    day_ret_str = (
        f"+{abs(day_ret_pct):.2f}%" if day_ret_pct >= 0 else f"{day_ret_pct:.2f}%"
    )
    win_pad = "      " if multi_window else ""
    print(
        f"  {'':12} {win_pad}{'':5} {'':6} {'':9} {'':5}  "
        f"{'':>5} {'':>5}  {'':>7} {'':>7} {pnl_str:>7} {avg_pct_str:>7}  "
        f"{wins}W/{losses}L  │  cap: {cap_pnl_str} ({day_ret_str})  portfolio: ${portfolio:.2f}"
    )
    print(f"  {'─' * 108}")


def _stats_from_trades(trade_rows: list) -> dict:
    active = [r for r in trade_rows if not r.get("skipped")]
    total = len(active)
    if total == 0:
        return None
    wins = sum(1 for r in active if r["success"])
    losses = total - wins
    win_rate = wins / total
    win_pct_vals = [r["pnl_pct"] for r in active if r["success"]]
    loss_pct_vals = [abs(r["pnl_pct"]) for r in active if not r["success"]]
    avg_win_pct = sum(win_pct_vals) / len(win_pct_vals) if win_pct_vals else 0.0
    avg_loss_pct = sum(loss_pct_vals) / len(loss_pct_vals) if loss_pct_vals else 0.0
    ev = win_rate * avg_win_pct - (1 - win_rate) * avg_loss_pct
    net_pnl = sum(r["pnl"] for r in active)

    rev_rows = [r for r in active if r.get("rev_entry_price", 0)]
    rev_total = len(rev_rows)
    rev_wins = sum(1 for r in rev_rows if r.get("rev_pnl", 0) > 0)
    rev_losses = rev_total - rev_wins

    br_rows = [r for r in active if r.get("br_entry_price", 0)]
    br_total = len(br_rows)
    br_wins = sum(1 for r in br_rows if r.get("br_pnl", 0) > 0)
    br_losses = br_total - br_wins

    bru_rows = [r for r in active if r.get("bru_entry_price", 0)]
    bru_total = len(bru_rows)
    bru_wins = sum(1 for r in bru_rows if r.get("bru_pnl", 0) > 0)
    bru_losses = bru_total - bru_wins

    dd_rows = [r for r in active if r.get("dd_addon_cap_pnl", 0.0) != 0.0]
    dd_total = len(dd_rows)
    dd_wins = sum(1 for r in dd_rows if r.get("dd_addon_cap_pnl", 0.0) > 0)
    dd_losses = dd_total - dd_wins
    dd_net_cap_pnl = sum(r.get("dd_addon_cap_pnl", 0.0) for r in dd_rows)

    opp_rows = [r for r in active if r.get("opp_cap_pnl") is not None]
    opp_total = len(opp_rows)
    opp_wins = sum(1 for r in opp_rows if r.get("opp_cap_pnl", 0.0) > 0)
    opp_losses = opp_total - opp_wins
    opp_net_cap_pnl = sum(r.get("opp_cap_pnl", 0.0) for r in opp_rows)

    return {
        "total": total,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "avg_win_pct": avg_win_pct,
        "avg_loss_pct": avg_loss_pct,
        "ev": ev,
        "net_pnl": net_pnl,
        "rev_total": rev_total,
        "rev_wins": rev_wins,
        "rev_losses": rev_losses,
        "br_total": br_total,
        "br_wins": br_wins,
        "br_losses": br_losses,
        "bru_total": bru_total,
        "bru_wins": bru_wins,
        "bru_losses": bru_losses,
        "dd_total": dd_total,
        "dd_wins": dd_wins,
        "dd_losses": dd_losses,
        "dd_net_cap_pnl": dd_net_cap_pnl,
        "opp_total": opp_total,
        "opp_wins": opp_wins,
        "opp_losses": opp_losses,
        "opp_net_cap_pnl": opp_net_cap_pnl,
    }


def _print_stats_block(label: str, stats: dict):
    if stats is None:
        print(f"  {label}: no trades")
        return
    net_str = (
        f"+${stats['net_pnl']:.2f}"
        if stats["net_pnl"] >= 0
        else f"-${abs(stats['net_pnl']):.2f}"
    )
    ev_str = f"+{stats['ev']:.3f}%" if stats["ev"] >= 0 else f"{stats['ev']:.3f}%"
    print(f"\n  {label}")
    print(f"  {'─' * 48}")
    print(
        f"  Trades          : {stats['total']}  ({stats['wins']}W / {stats['losses']}L)"
    )
    if stats.get("rev_total", 0):
        print(
            f"  Reversals       : {stats['rev_total']}  ({stats['rev_wins']}W / {stats['rev_losses']}L)"
        )
    if stats.get("br_total", 0):
        print(
            f"  Bearish re-entry: {stats['br_total']}  ({stats['br_wins']}W / {stats['br_losses']}L)"
        )
    if stats.get("bru_total", 0):
        print(
            f"  Bullish re-entry: {stats['bru_total']}  ({stats['bru_wins']}W / {stats['bru_losses']}L)"
        )
    if stats.get("dd_total", 0):
        dd_net = stats["dd_net_cap_pnl"]
        dd_net_str = f"+${dd_net:.2f}" if dd_net >= 0 else f"-${abs(dd_net):.2f}"
        print(
            f"  Double-down     : {stats['dd_total']}  ({stats['dd_wins']}W / {stats['dd_losses']}L)"
            f"  net cap P&L: {dd_net_str}"
        )
    if stats.get("opp_total", 0):
        opp_net = stats["opp_net_cap_pnl"]
        opp_net_str = f"+${opp_net:.2f}" if opp_net >= 0 else f"-${abs(opp_net):.2f}"
        print(
            f"  Opportunity pool: {stats['opp_total']}  ({stats['opp_wins']}W / {stats['opp_losses']}L)"
            f"  net cap P&L: {opp_net_str}"
        )
    print(f"  Win rate        : {stats['win_rate'] * 100:.0f}%")
    print(f"  Avg win  %      : +{stats['avg_win_pct']:.2f}%  per trade")
    print(f"  Avg loss %      : -{stats['avg_loss_pct']:.2f}%  per trade")
    print(f"  EV / trade      : {ev_str}")
    print(f"  Net P&L (1 sh)  : {net_str}")


def _capital_stats_from_trades(trade_rows: list, initial_capital: float) -> dict:
    active = [r for r in trade_rows if not r.get("skipped")]
    total_cap_pnl = sum(r["cap_pnl"] for r in active)
    days_with_picks = set(r["date"] for r in active)

    daily_cap_pnls = {}
    for row in active:
        d = row["date"]
        daily_cap_pnls[d] = daily_cap_pnls.get(d, 0.0) + row["cap_pnl"]

    daily_returns = list(daily_cap_pnls.values())
    avg_daily_ret = sum(daily_returns) / len(daily_returns) if daily_returns else 0.0
    return {
        "initial_capital": initial_capital,
        "total_cap_pnl": total_cap_pnl,
        "total_return_pct": total_cap_pnl / initial_capital * 100,
        "final_portfolio": initial_capital + total_cap_pnl,
        "days_with_picks": len(days_with_picks),
        "avg_daily_ret": avg_daily_ret,
        "avg_daily_ret_pct": avg_daily_ret / initial_capital * 100,
    }


def _print_capital_stats_block(stats: dict, weights_label: str = ""):
    cap_pnl_str = (
        f"+${stats['total_cap_pnl']:.2f}"
        if stats["total_cap_pnl"] >= 0
        else f"-${abs(stats['total_cap_pnl']):.2f}"
    )
    ret_pct_str = (
        f"+{stats['total_return_pct']:.2f}%"
        if stats["total_return_pct"] >= 0
        else f"{stats['total_return_pct']:.2f}%"
    )
    avg_str = (
        f"+${stats['avg_daily_ret']:.2f}"
        if stats["avg_daily_ret"] >= 0
        else f"-${abs(stats['avg_daily_ret']):.2f}"
    )
    avg_pct_str = (
        f"+{stats['avg_daily_ret_pct']:.2f}%"
        if stats["avg_daily_ret_pct"] >= 0
        else f"{stats['avg_daily_ret_pct']:.2f}%"
    )
    label = f"${stats['initial_capital']:,.0f} initial"
    if weights_label:
        label += f" | {weights_label}"
    print(f"\n  CAPITAL SIMULATION  ({label})")
    print(f"  {'─' * 48}")
    print(f"  Total return ($)    : {cap_pnl_str}")
    print(f"  Total return (%)    : {ret_pct_str}")
    print(f"  Final portfolio     : ${stats['final_portfolio']:,.2f}")
    print(f"  Days with picks     : {stats['days_with_picks']}")
    print(f"  Avg daily return    : {avg_str}  ({avg_pct_str})")


def _print_per_window_stats(
    trade_rows: list,
    windows: list,
    initial_capital: float,
    morning_split: list,
):
    n_first = len(morning_split)
    split_pct = " / ".join(f"{s * 100:.0f}%" for s in morning_split)
    sep = "\u2501" * 80
    print(f"\n{sep}")
    print(
        f"  PER-WINDOW BREAKDOWN  (first group: {split_pct} of portfolio | sequential: inherits all returned capital)"
    )
    print(sep)
    print(
        f"  {'Window':<8} {'Start':<7} {'Bars':<5} {'Group':<12} {'Trades':>7}  {'W/L':<10} "
        f"{'WinRate':>8}  {'EV/trade':>9}  {'Cap P&L':>10}  {'Return%':>8}"
    )
    print(f"  {'─' * 78}")

    for i, win in enumerate(windows):
        label = win["label"]
        if i < n_first:
            group = f"first({morning_split[i] * 100:.0f}%)"
        else:
            group = "sequential"
        win_rows = [
            r for r in trade_rows if r["window"] == label and not r.get("skipped")
        ]
        if not win_rows:
            print(
                f"  {label:<8} {win['opening_start']:<7} {win['opening_bars']:<5} {group:<10} {'—':>7}"
            )
            continue
        stats = _stats_from_trades(win_rows)
        cap_stats = _capital_stats_from_trades(win_rows, initial_capital)
        ev_str = f"+{stats['ev']:.3f}%" if stats["ev"] >= 0 else f"{stats['ev']:.3f}%"
        cap_pnl_str = (
            f"+${cap_stats['total_cap_pnl']:.2f}"
            if cap_stats["total_cap_pnl"] >= 0
            else f"-${abs(cap_stats['total_cap_pnl']):.2f}"
        )
        ret_str = (
            f"+{cap_stats['total_return_pct']:.2f}%"
            if cap_stats["total_return_pct"] >= 0
            else f"{cap_stats['total_return_pct']:.2f}%"
        )
        wl = f"{stats['wins']}W/{stats['losses']}L"
        print(
            f"  {label:<8} {win['opening_start']:<7} {win['opening_bars']:<5} {group:<10} "
            f"{stats['total']:>7}  {wl:<10} {stats['win_rate'] * 100:>7.0f}%  "
            f"{ev_str:>9}  {cap_pnl_str:>10}  {ret_str:>8}"
        )
    print(sep)


def _period_capital_groups(trade_rows: list, initial_capital: float, key_fn) -> dict:
    active = [r for r in trade_rows if not r.get("skipped")]
    groups = {}
    for row in active:
        key = key_fn(row["date"])
        if key not in groups:
            groups[key] = {"picks": 0, "wins": 0, "losses": 0, "cap_pnl": 0.0}
        groups[key]["picks"] += 1
        groups[key]["cap_pnl"] += row["cap_pnl"]
        if row["success"]:
            groups[key]["wins"] += 1
        else:
            groups[key]["losses"] += 1
    return groups


def _print_period_table(title: str, groups: dict, initial_capital: float):
    if not groups:
        return
    sep = "\u2501" * 72
    print(f"\n{sep}")
    print(f"  {title}")
    print(sep)
    print(
        f"  {'Period':<12} {'Picks':>6}  {'W/L':<11} {'Cap P&L$':>10}  {'Return%':>8}  Portfolio"
    )
    print(f"  {'─' * 68}")

    portfolio = initial_capital
    total_picks = total_wins = total_losses = 0
    total_cap_pnl = 0.0

    for key in sorted(groups):
        g = groups[key]
        portfolio += g["cap_pnl"]
        total_picks += g["picks"]
        total_wins += g["wins"]
        total_losses += g["losses"]
        total_cap_pnl += g["cap_pnl"]

        wl = f"{g['wins']}W/{g['losses']}L"
        pnl_s = (
            f"+${g['cap_pnl']:.2f}"
            if g["cap_pnl"] >= 0
            else f"-${abs(g['cap_pnl']):.2f}"
        )
        ret = g["cap_pnl"] / initial_capital * 100
        ret_s = f"+{ret:.2f}%" if ret >= 0 else f"{ret:.2f}%"
        print(
            f"  {key:<12} {g['picks']:>6}  {wl:<11} {pnl_s:>10}  {ret_s:>8}  ${portfolio:,.2f}"
        )

    print(f"  {'─' * 68}")
    total_pnl_s = (
        f"+${total_cap_pnl:.2f}"
        if total_cap_pnl >= 0
        else f"-${abs(total_cap_pnl):.2f}"
    )
    total_ret = total_cap_pnl / initial_capital * 100
    total_ret_s = f"+{total_ret:.2f}%" if total_ret >= 0 else f"{total_ret:.2f}%"
    print(
        f"  {'TOTAL':<12} {total_picks:>6}  {total_wins}W/{total_losses}L{'':<7} "
        f"{total_pnl_s:>10}  {total_ret_s:>8}  ${initial_capital + total_cap_pnl:,.2f}"
    )
    print(sep)


def _bnh_period_groups(daily_closes: pd.Series, initial_capital: float, key_fn) -> dict:
    if daily_closes.empty:
        return {}
    shares = initial_capital / daily_closes.iloc[0]
    groups = {}
    for d, close in daily_closes.items():
        key = key_fn(d)
        if key not in groups:
            groups[key] = {"last_close": close}
        groups[key]["last_close"] = close

    prev_value = initial_capital
    for key in sorted(groups):
        end_value = shares * groups[key]["last_close"]
        groups[key]["pnl"] = end_value - prev_value
        prev_value = end_value
    return groups


def _print_bnh_period_table(title: str, groups: dict, initial_capital: float):
    if not groups:
        return
    sep = "\u2501" * 60
    print(f"\n{sep}")
    print(f"  {title}")
    print(sep)
    print(f"  {'Period':<12} {'P&L$':>10}  {'Return%':>8}  Portfolio")
    print(f"  {'─' * 54}")

    portfolio = initial_capital
    total_pnl = 0.0
    for key in sorted(groups):
        pnl = groups[key]["pnl"]
        portfolio += pnl
        total_pnl += pnl
        pnl_s = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
        ret = pnl / initial_capital * 100
        ret_s = f"+{ret:.2f}%" if ret >= 0 else f"{ret:.2f}%"
        print(f"  {key:<12} {pnl_s:>10}  {ret_s:>8}  ${portfolio:,.2f}")

    print(f"  {'─' * 54}")
    total_pnl_s = f"+${total_pnl:.2f}" if total_pnl >= 0 else f"-${abs(total_pnl):.2f}"
    total_ret = total_pnl / initial_capital * 100
    total_ret_s = f"+{total_ret:.2f}%" if total_ret >= 0 else f"{total_ret:.2f}%"
    print(
        f"  {'TOTAL':<12} {total_pnl_s:>10}  {total_ret_s:>8}  ${initial_capital + total_pnl:,.2f}"
    )
    print(sep)


def _print_summary(
    trade_rows: list,
    baseline_df: pd.DataFrame,
    n: int,
    eval_start: date,
    eval_end: date,
    lookback_days: int,
    stop_pct: float,
    windows: list,
    initial_capital: float = INITIAL_CAPITAL,
    qqq_closes: pd.Series = None,
    weights: list = None,
    morning_split: list = None,
):
    sep = "\u2501" * 70
    print(f"\n{sep}")
    print(f"  SUMMARY — Selector Backtest")
    print(
        f"  {eval_start} → {eval_end}  |  top-{n}  |  {lookback_days}d rolling  |  stop-pct {stop_pct}"
    )
    print(sep)

    _print_stats_block(
        f"SELECTED  (top-{n} per window per day, scoring + EV gate)",
        _stats_from_trades(trade_rows),
    )

    if not baseline_df.empty:
        baseline_rows = [
            {
                "pnl": r["pnl"],
                "pnl_pct": r["pnl"] / r["entry_price"] * 100,
                "success": bool(r["success"]),
                "skipped": False,
            }
            for r in baseline_df.to_dict("records")
        ]
        _print_stats_block(
            "BASELINE  (all signals, no selection, first window only)",
            _stats_from_trades(baseline_rows),
        )

    if trade_rows:
        weights = weights or _parse_weights(None, n)
        wlabel = _weights_label(weights, initial_capital)
        _print_capital_stats_block(
            _capital_stats_from_trades(trade_rows, initial_capital), wlabel
        )

        if len(windows) > 1:
            _print_per_window_stats(
                trade_rows, windows, initial_capital, morning_split or [1.0]
            )

        def _week_key(d):
            iso = d.isocalendar()
            return f"{iso[0]}-W{iso[1]:02d}"

        def _month_key(d):
            return f"{d.year}-{d.month:02d}"

        _print_period_table(
            f"WEEKLY BREAKDOWN  (${initial_capital:,.0f} initial | {wlabel})",
            _period_capital_groups(trade_rows, initial_capital, _week_key),
            initial_capital,
        )
        if qqq_closes is not None and not qqq_closes.empty:
            _print_bnh_period_table(
                f"WEEKLY BREAKDOWN  QQQ buy-and-hold (${initial_capital:,.0f} initial)",
                _bnh_period_groups(qqq_closes, initial_capital, _week_key),
                initial_capital,
            )

        _print_period_table(
            f"MONTHLY BREAKDOWN  (${initial_capital:,.0f} initial | {wlabel})",
            _period_capital_groups(trade_rows, initial_capital, _month_key),
            initial_capital,
        )
        if qqq_closes is not None and not qqq_closes.empty:
            _print_bnh_period_table(
                f"MONTHLY BREAKDOWN  QQQ buy-and-hold (${initial_capital:,.0f} initial)",
                _bnh_period_groups(qqq_closes, initial_capital, _month_key),
                initial_capital,
            )

    print(f"\n{sep}\n")


def _print_opportunity_pool_block(
    trade_rows: list, initial_pool: float, compound: bool
):
    opp_rows = [r for r in trade_rows if not r.get("skipped") and r.get("opp_cap_pnl") is not None]
    if not opp_rows:
        return
    opp_total = len(opp_rows)
    opp_wins = sum(1 for r in opp_rows if r.get("opp_cap_pnl", 0.0) > 0)
    opp_losses = opp_total - opp_wins
    win_rate = opp_wins / opp_total * 100
    opp_net_cap_pnl = sum(r.get("opp_cap_pnl", 0.0) for r in opp_rows)
    final_balance = initial_pool + opp_net_cap_pnl
    pool_return_pct = opp_net_cap_pnl / initial_pool * 100 if initial_pool else 0.0

    net_str = f"+${opp_net_cap_pnl:.2f}" if opp_net_cap_pnl >= 0 else f"-${abs(opp_net_cap_pnl):.2f}"
    ret_str = f"+{pool_return_pct:.2f}%" if pool_return_pct >= 0 else f"{pool_return_pct:.2f}%"
    compound_note = "compounded" if compound else "resets daily"

    sep = "━" * 60
    print(f"\n{sep}")
    print(f"  OPPORTUNITY POOL  (${initial_pool:,.0f} initial | {compound_note})")
    print(f"  {'─' * 56}")
    print(f"  Deployments         : {opp_total}  ({opp_wins}W / {opp_losses}L)")
    print(f"  Win rate            : {win_rate:.0f}%")
    print(f"  Net cap P&L         : {net_str}")
    print(f"  Net pool return (%) : {ret_str}")
    if compound:
        final_str = f"${final_balance:,.2f}"
        print(f"  Final pool balance  : {final_str}")
    print(sep)


def _parse_args():
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
        "--compound",
        action="store_true",
        default=False,
        help="Compound capital across days (portfolio carries over). "
        "Default: reset to initial capital each day for clean per-day strategy evaluation.",
    )
    parser.add_argument(
        "--dedup",
        action="store_true",
        default=False,
        help="Skip a ticker in later windows if already picked by an earlier window that day.",
    )
    parser.add_argument(
        "--trailing-ma",
        choices=["ma20", "ma50", "both"],
        default="ma20",
        help="Trailing MA stop to use once MA is above hard stop (default: ma20).",
    )
    parser.add_argument(
        "--max-loss-pct",
        type=float,
        default=None,
        help="Per-trade max loss as a fraction of entry price (e.g. 0.02 = 2%%). Default: disabled.",
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
        "price later crosses above OR high, enter a BULLISH reversal with 15%% OR-range "
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
        "--doubledown",
        action="store_true",
        default=False,
        help=(
            "Enable double-down: if rank-2+ positions stop out within the doubledown window "
            "of OR close, deploy their returned capital into the highest-ranked survivor as a "
            "single add-on leg. Add-on entry = close of the doubledown bar; hard stop = "
            "entry ± 80% × bar range. Default: off."
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
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    _TICKER_SETS = {"V3": DEFAULT_TICKERS, "AT": ACTIVELY_TRADE_TICKERS}
    tickers = args.tickers or _TICKER_SETS.get(args.ticker_set, DEFAULT_TICKERS)
    eval_start = date.fromisoformat(args.start)
    eval_end = date.fromisoformat(args.end) if args.end else date.today()

    weights = _parse_weights(args.weights, args.top)

    if args.window:
        windows = []
        for w in args.window:
            if len(w) < 3:
                parser.error(
                    f"--window requires LABEL START BARS [CLOSE_TOP_PCT], got: {w}"
                )
            win = {"label": w[0], "opening_start": w[1], "opening_bars": int(w[2])}
            if len(w) > 3:
                win["close_top_pct"] = float(w[3])
            windows.append(win)
    else:
        windows = None

    resolved_windows = _normalize_windows(
        windows, args.opening_start, args.opening_bars
    )
    n_windows = len(resolved_windows)

    # Parse --morning-split: convert percentages to fractions, validate
    if args.morning_split:
        raw_split = args.morning_split
        total_pct = sum(raw_split)
        if total_pct > 100.0 + 1e-6:
            raise SystemExit(
                f"--morning-split values sum to {total_pct:.1f}% which exceeds 100%."
            )
        if len(raw_split) > n_windows:
            raise SystemExit(
                f"--morning-split has {len(raw_split)} values but only {n_windows} window(s) defined."
            )
        morning_split = [v / 100.0 for v in raw_split]
    else:
        morning_split = [1.0] if n_windows == 1 else None

    n_first = len(morning_split) if morning_split else 1

    print(f"\nSelector Backtest")
    print(f"  Eval window  : {eval_start} → {eval_end}")
    print(f"  Top-N        : {args.top}")
    print(f"  Weights      : {_weights_label(weights, args.capital)}")
    print(f"  Tickers      : {', '.join(tickers)}")
    print(f"  Lookback     : {args.lookback}d rolling")
    print(f"  Windows      : {n_windows} total")
    for i, w in enumerate(resolved_windows):
        if morning_split and i < len(morning_split):
            group_desc = f"simultaneous, {morning_split[i] * 100:.0f}% of portfolio"
            cap_approx = args.capital * morning_split[i]
        else:
            group_desc = "sequential, inherits all returned capital"
            cap_approx = None
        cap_str = f"  (~${cap_approx:,.0f})" if cap_approx is not None else ""
        ctp = w.get("close_top_pct")
        ctp_str = f", top/bottom {ctp * 100:.0f}%" if ctp is not None else ""
        print(
            f"    [{w['label']}] {w['opening_start']} / {w['opening_bars']} bars{ctp_str}  ({group_desc}){cap_str}"
        )
    print(f"  Min capital  : ${args.min_window_capital:.0f} per window (skip if below)")
    print(
        f"  Compounding  : {'on (portfolio carries over)' if args.compound else f'off (reset ${args.capital:,.0f} each day)'}"
    )
    print(f"  Dedup        : {'on' if args.dedup else 'off'}")
    print(f"  Stop pct     : {args.stop_pct}")
    print(f"  Trailing MA  : {args.trailing_ma}")
    print(
        f"  Max loss pct : {f'{args.max_loss_pct * 100:.1f}%' if args.max_loss_pct else 'disabled'}"
    )
    print(f"  Armed MA20   : {'on' if args.armed_ma20_exit else 'off'}")
    print(
        f"  Regime filter: {'QQQ MA' + str(args.regime_ma) if args.regime_filter else 'off'}"
    )
    if args.qqq_align_filter:
        if args.qqq_extend_days > 0:
            extend_desc = (
                f"threshold={args.qqq_align_threshold}, "
                f"gate={args.qqq_extend_days}d>{args.qqq_extend_pct * 100:.0f}%"
            )
            if args.qqq_extend_max_dd > 0:
                extend_desc += f" max-dd={args.qqq_extend_max_dd * 100:.0f}%"
        else:
            extend_desc = f"threshold={args.qqq_align_threshold} (fires every day)"
        print(f"  QQQ align    : on ({extend_desc})")
    else:
        print(f"  QQQ align    : off")
    print(
        f"  Reversal     : {'on (max bars_held=' + str(args.reversal_max_bars) + ')' if args.reversal else 'off'}"
    )
    print(
        f"  Bearish RE   : {'on (max bars_held=' + str(args.bearish_reentry_max_bars) + ')' if args.bearish_reentry else 'off'}"
    )
    print(
        f"  Bullish RE   : {'on (max bars_held=' + str(args.bullish_reentry_max_bars) + ')' if args.bullish_reentry else 'off'}"
    )
    if args.doubledown:
        print(f"  Double-down  : on (start +{args.doubledown_start_min}min, stop=80% bar-range on add-on)")
    else:
        print("  Double-down  : off")
    if args.opportunity_capital_pct > 0:
        _opp_initial = args.capital * args.opportunity_capital_pct / 100
        print(
            f"  Opp pool     : ${_opp_initial:,.0f} ({args.opportunity_capital_pct:.0f}% of initial capital)"
            + (" | compounded" if args.compound else " | resets daily")
        )
        if not args.doubledown:
            print("  WARNING: --opportunity-capital has no effect without --doubledown")
    else:
        print("  Opp pool     : disabled")
    if args.min_or_range > 0:
        wins_str = (
            ",".join(args.min_or_range_windows)
            if args.min_or_range_windows
            else "all windows"
        )
        min_or_range_desc = f"{args.min_or_range:.2f}% (windows: {wins_str})"
    else:
        min_or_range_desc = "disabled"
    print(f"  Min OR range : {min_or_range_desc}")
    if args.min_ma200_distance > 0:
        ma200_wins_str = (
            ",".join(args.min_ma200_distance_windows)
            if args.min_ma200_distance_windows
            else "all windows"
        )
        min_ma200_desc = f"{args.min_ma200_distance:.2f}% (windows: {ma200_wins_str})"
    else:
        min_ma200_desc = "disabled"
    print(f"  Min MA200 dist: {min_ma200_desc}")
    print(
        f"  Min score    : {f'{args.min_score:.3f}' if args.min_score > 0 else 'disabled'}"
    )
    print(
        f"  Min EV       : {f'{args.min_ev:.3f}%' if args.min_ev > 0 else 'disabled'}"
    )
    print(
        f"  OR bar lookback: {f'last {args.or_bar_lookback} bars' if args.or_bar_lookback > 0 else 'disabled'}"
    )
    print(
        f"  Close top pct: {f'top/bottom {args.close_top_pct * 100:.0f}% (global default, overridable per window)' if args.close_top_pct is not None else 'disabled (standard midpoint/bottom-30; per-window override via --window LABEL START BARS PCT)'}"
    )
    print(f"  Source       : {args.source}")
    alpaca_feed = DataFeed.IEX if args.feed == "iex" else DataFeed.SIP
    if args.source == "alpaca":
        print(f"  Alpaca feed  : {args.feed.upper()}")

    trade_rows, all_window_results, trading_days = run_selector_backtest(
        n=args.top,
        tickers=tickers,
        eval_start=eval_start,
        eval_end=eval_end,
        lookback_days=args.lookback,
        opening_bars=args.opening_bars,
        opening_start_time=args.opening_start,
        bearish_ma200=args.bearish_ma200,
        stop_pct=args.stop_pct,
        source=args.source,
        trailing_ma=args.trailing_ma,
        max_loss_pct=args.max_loss_pct,
        armed_ma20_exit=args.armed_ma20_exit,
        regime_filter=args.regime_filter,
        regime_ma=args.regime_ma,
        windows=windows,
        dedup=args.dedup,
        enable_reversal=args.reversal,
        reversal_max_bars_held=args.reversal_max_bars,
        enable_bearish_reentry=args.bearish_reentry,
        bearish_reentry_max_bars=args.bearish_reentry_max_bars,
        enable_bullish_reentry=args.bullish_reentry,
        bullish_reentry_max_bars=args.bullish_reentry_max_bars,
        min_or_range=args.min_or_range,
        min_or_range_windows=args.min_or_range_windows,
        min_ma200_distance=args.min_ma200_distance,
        min_ma200_distance_windows=args.min_ma200_distance_windows,
        min_score=args.min_score,
        min_ev=args.min_ev,
        or_bar_lookback=args.or_bar_lookback,
        close_top_pct=args.close_top_pct,
        feed=alpaca_feed,
        enable_doubledown=args.doubledown,
        doubledown_start_min=args.doubledown_start_min,
        qqq_align_filter=args.qqq_align_filter,
        qqq_align_threshold=args.qqq_align_threshold,
        qqq_extend_days=args.qqq_extend_days,
        qqq_extend_pct=args.qqq_extend_pct,
        qqq_extend_max_dd=args.qqq_extend_max_dd,
    )

    skip_log = _apply_capital_flow(
        trade_rows,
        resolved_windows,
        args.capital,
        weights,
        args.top,
        morning_split=morning_split,
        min_capital=args.min_window_capital,
        compound=args.compound,
        enable_doubledown=args.doubledown,
    )

    if args.doubledown:
        _apply_doubledown(trade_rows)

    if args.opportunity_capital_pct > 0 and args.doubledown:
        _opp_initial = args.capital * args.opportunity_capital_pct / 100
        _apply_opportunity_pool(
            trade_rows,
            resolved_windows,
            initial_pool=_opp_initial,
            compound=args.compound,
            doubledown_start_min=args.doubledown_start_min,
        )

    baseline_df = _collect_baseline(all_window_results, eval_start, eval_end)

    print("Fetching QQQ daily bars for comparison...")
    qqq_df = fetch_daily_bars(["QQQ"], eval_start, eval_end, source=args.source, feed=alpaca_feed).get(
        "QQQ", pd.DataFrame()
    )
    qqq_closes = qqq_df["Close"] if not qqq_df.empty else pd.Series(dtype=float)

    multi_window = n_windows > 1
    _print_daily_table(
        trade_rows, n=args.top, weights=weights, multi_window=multi_window
    )
    _print_summary(
        trade_rows,
        baseline_df,
        n=args.top,
        eval_start=eval_start,
        eval_end=eval_end,
        lookback_days=args.lookback,
        stop_pct=args.stop_pct,
        windows=resolved_windows,
        initial_capital=args.capital,
        qqq_closes=qqq_closes,
        weights=weights,
        morning_split=morning_split,
    )
    if args.opportunity_capital_pct > 0 and args.doubledown:
        _opp_initial = args.capital * args.opportunity_capital_pct / 100
        _print_opportunity_pool_block(trade_rows, _opp_initial, args.compound)

    if args.show_execution_log:
        _print_skip_log(skip_log, resolved_windows)
