"""Window-config and account-mode resolution for the trade engine CLI.

Extracted verbatim from op_momentum_trade_engine.py.
"""
from ..models import WindowConfig


def _parse_windows(args) -> list:
    """Parse --window and --morning-split into a list of WindowConfig objects."""
    if not args.window:
        return None

    raw_windows = [
        {"label": w[0], "opening_start": w[1], "opening_bars": int(w[2])}
        for w in args.window
    ]
    n_windows = len(raw_windows)

    if args.morning_split:
        raw_split = args.morning_split
        total_pct = sum(raw_split)
        if total_pct > 100.0 + 1e-6:
            raise SystemExit(
                f"--morning-split values sum to {total_pct:.1f}%% which exceeds 100%%."
            )
        if len(raw_split) > n_windows:
            raise SystemExit(
                f"--morning-split has {len(raw_split)} values but only {n_windows} window(s) defined."
            )
        fractions = [v / 100.0 for v in raw_split]
        n_first = len(fractions)
    else:
        fractions = [1.0]
        n_first = 1

    windows = []
    for i, w in enumerate(raw_windows):
        if i < n_first:
            windows.append(
                WindowConfig(
                    label=w["label"],
                    opening_start=w["opening_start"],
                    opening_bars=w["opening_bars"],
                    capital_fraction=fractions[i],
                    is_sequential=False,
                )
            )
        else:
            windows.append(
                WindowConfig(
                    label=w["label"],
                    opening_start=w["opening_start"],
                    opening_bars=w["opening_bars"],
                    capital_fraction=1.0,
                    is_sequential=True,
                )
            )
    return windows


def _resolve_is_paper(args) -> bool:
    """Return True unless --live is set. --live is the sole control for paper vs live account."""
    return not getattr(args, "live", False)
