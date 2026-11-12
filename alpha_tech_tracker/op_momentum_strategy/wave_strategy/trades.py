"""Live trades (the backtest's exit rules, one bar at a time) and setup evaluation."""

from concurrent.futures import Future
from datetime import datetime

import pandas as pd

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward import analyze_bars
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_backtest import (
    DEFAULT_GIVEBACK,
    DEFAULT_GIVEBACK_ARM_R,
    signal_group,
)
from alpha_tech_tracker.op_momentum_strategy.wave_strategy.session import ET


class LiveTrade:
    """One alerted trade, exited by the rules of wave_risk_reward_backtest.TradeSimulator.run."""

    FIELDS = ("ticker", "setup", "signal", "exit_mode", "entry_time", "side", "entry", "stop", "target", "risk",
              "peak", "target_reached", "status", "last_bar", "exit_time", "exit_price", "outcome")

    def __init__(self, **fields):
        for name in self.FIELDS:
            setattr(self, name, fields.get(name))
        self.peak = self.entry if self.peak is None else self.peak
        self.target_reached = bool(self.target_reached)
        self.status = self.status or "open"

    @property
    def overnight(self):
        return self.exit_mode == "next open"

    def on_bar(self, bar, giveback=DEFAULT_GIVEBACK, arm_r=DEFAULT_GIVEBACK_ARM_R):
        """Apply one closed 5-min bar; returns the outcome when the trade exits on it, else None."""
        self.last_bar = bar["time"]
        if self.status != "open":
            return None
        side, entry, stop, target = self.side, self.entry, self.stop, self.target
        if stop is not None and ((bar["low"] <= stop) if side == 1 else (bar["high"] >= stop)):
            fill = min(bar["open"], stop) if side == 1 else max(bar["open"], stop)
            return self._close(bar["time"], fill, "stop")
        hit_target = target is not None and ((bar["high"] >= target) if side == 1 else (bar["low"] <= target))
        if self.exit_mode == "target" and hit_target:
            return self._close(bar["time"], target, "target")
        self.target_reached = bool(self.target_reached or hit_target)
        self.peak = max(self.peak, bar["close"]) if side == 1 else min(self.peak, bar["close"])
        if self.exit_mode == "giveback" or (self.exit_mode == "target-trail" and self.target_reached):
            move = (self.peak - entry) * side
            if move >= arm_r * self.risk and (self.peak - bar["close"]) * side >= giveback * move:
                return self._close(bar["time"], bar["close"], "giveback")
        return None

    def close_at(self, when, price, outcome):
        return self._close(when, price, outcome)

    def _close(self, when, price, outcome):
        self.status, self.exit_time, self.exit_price, self.outcome = "closed", when, float(price), outcome
        return outcome

    def pnl_pct(self, price=None):
        price = self.exit_price if price is None else price
        return self.side * (price - self.entry) / self.entry * 100

    def to_dict(self):
        out = {}
        for name in self.FIELDS:
            value = getattr(self, name)
            if isinstance(value, datetime):
                value = value.isoformat()
            elif hasattr(value, "item"):
                value = value.item()
            out[name] = value
        return out

    @classmethod
    def from_dict(cls, data):
        fields = dict(data)
        for name in ("entry_time", "last_bar", "exit_time"):
            if fields.get(name):
                fields[name] = pd.Timestamp(fields[name]).tz_convert(ET)
        return cls(**fields)


def fired_signals(ticker, spec, signals, bar_time):
    """The analyze_bars signals of one setup that fired on `bar_time`, as plain dicts."""
    fired = []
    for sig in signals:
        if sig["time"] != bar_time or not sig["risk_reward"]:
            continue
        if spec.groups is not None and signal_group(sig) not in spec.groups:
            continue
        rr = sig["risk_reward"]
        fired.append({"ticker": ticker, "setup": spec.name, "signal": sig["signal"], "time": sig["time"],
                      "price": float(sig["price"]), "stop": rr["stop"], "target": rr["target"], "risk": rr["risk"],
                      "rr": rr.get("rr")})
    return fired


def evaluate_setup(job):
    """Signals of one setup that fired on `bar_time`, from analyze_bars over the day's window.

    Top-level so a process pool can pickle it.
    """
    ticker, spec, frame, windows, bar_time = job
    return fired_signals(ticker, spec, analyze_bars(frame, spec.params, windows)["signals"], bar_time)


class InlineExecutor:
    """Runs jobs in the calling thread (tests, or --workers 0)."""

    def submit(self, fn, *args):
        future = Future()
        try:
            future.set_result(fn(*args))
        except Exception as error:  # surfaced through the future like a pool would
            future.set_exception(error)
        return future

    def shutdown(self, wait=True):
        pass
