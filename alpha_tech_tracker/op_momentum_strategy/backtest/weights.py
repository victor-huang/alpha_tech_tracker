"""Rank-weight parsing and normalization for the selector backtest.

`_parse_weights` is imported by ~19 analysis scripts via
op_momentum_selector_backtest, which re-exports it — do not remove that alias.
"""

def _effective_weights(weights: list, n_picks: int, fixed: bool = False) -> list:
    """Redistribute weights when fewer picks than configured top-N.

    When a day has fewer picks than the configured top-N (e.g. 2 picks with
    top-5 and weights [0.2, 0.2, 0.2, 0.2, 0.2]), redeploy the full window
    capital proportionally across the actual picks instead of leaving idle
    capital.  Weights are renormalized to sum to 1.0 over the actual picks.

    fixed=True: skip renormalization — each slot keeps its original weight
    fraction so idle capital stays undeployed (fixed-per-signal mode).
    """
    if n_picks == 0:
        return weights
    if fixed:
        return weights[:n_picks]
    if n_picks >= len(weights):
        return weights
    slice_ = weights[:n_picks]
    total = sum(slice_)
    if total <= 0:
        return [1.0 / n_picks] * n_picks
    return [w / total for w in slice_]


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
