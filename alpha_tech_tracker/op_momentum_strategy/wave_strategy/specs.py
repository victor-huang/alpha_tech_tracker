"""Setup specs and the monitor config file: which setups each ticker trades and how each one exits."""

import csv
import json
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from alpaca.data.enums import DataFeed

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.ticker_stats_report import clamp_end_for_sip
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward import params_from_args
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_backtest import (
    parse_args as parse_backtest_args,
)
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_scan import BOX_GROUPS, SETUP_RUNS
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_setup_report import (
    DEFAULT_OUT_ROOT as SETUP_REPORT_ROOT,
    REPORT_EXITS,
    main as setup_report_main,
    top_setups_by_ticker,
)

logger = logging.getLogger(__name__)

DEFAULT_REFRESH_ROOT = SETUP_REPORT_ROOT / "monitor_refresh"
EXIT_TEXT = {
    "target": "exit at the target or the stop",
    "target-trail": "stop until the target, then trail (32% give-back)",
    "giveback": "stop, then trail once up 0.25R (32% give-back)",
    "eod": "hold to the close (stop only)",
}


@dataclass(frozen=True)
class SetupSpec:
    name: str
    exit_mode: str
    params: object
    groups: Optional[frozenset]

    @property
    def overnight(self):
        return self.exit_mode == "next open"


def build_setup_spec(name):
    """The analyze_bars options, signal groups and fixed exit for a setup-report setup name."""
    if name not in REPORT_EXITS:
        raise ValueError(f"unknown setup {name!r}; choose from {', '.join(REPORT_EXITS)}")
    box_labels = set(BOX_GROUPS.values())
    run = "box signals" if name in box_labels else name
    groups = frozenset(g for g, label in BOX_GROUPS.items() if label == name) if name in box_labels else None
    params = params_from_args(parse_backtest_args(["--start", "2000-01-01"] + SETUP_RUNS[run]))
    return SetupSpec(name, REPORT_EXITS[name], params, groups)


def generate_config(report_dir, tickers, top_n=3, types=None, min_trades=1, lookback_sessions=None):
    """Monitor config from a setup report folder: each ticker's top setups by fixed-exit total.

    `types` limits the setup types (e.g. long, overnight), `min_trades` is the trades a setup needs,
    and `lookback_sessions` ranks on the report's last N sessions only.
    """
    report_dir = Path(report_dir)
    with (report_dir / "trades.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    days = sorted({row["entry_time"][:10] for row in rows})
    if lookback_sessions:
        days = days[-lookback_sessions:]
        rows = [row for row in rows if row["entry_time"][:10] >= days[0]]
    ranked = top_setups_by_ticker(rows, top_n, types, min_trades)
    missing = [t for t in tickers if t not in ranked]
    if missing:
        raise ValueError(f"{', '.join(missing)} not in {report_dir}; run the setup report for them first")
    empty = [t for t in tickers if not ranked[t]]
    if empty:
        logger.warning("No setup made money for %s in %s; they are left out", ", ".join(empty), report_dir)
    return {
        "generated": date.today().isoformat(),
        "source": str(report_dir),
        "window": f"{days[0]}..{days[-1]}" if days else "",
        "top_n": top_n,
        "types": list(types) if types else "all",
        "min_trades": min_trades,
        "tickers": {t: [{"setup": s, "report_total_pct": round(total, 2)} for s, total in ranked[t]]
                    for t in tickers if ranked[t]},
    }


def refresh_report(tickers, lookback_sessions, workers):
    """Run the setup report over the trailing window ending today; returns its folder."""
    end = clamp_end_for_sip(date.today(), DataFeed.SIP)
    start = end - timedelta(days=int(lookback_sessions * 1.5) + 10)
    out_dir = DEFAULT_REFRESH_ROOT / f"{start}_{end}"
    print(f"Refreshing the setup report for {len(tickers)} tickers, {start}..{end} -> {out_dir}", flush=True)
    setup_report_main(["--tickers", *tickers, "--start", start.isoformat(), "--end", end.isoformat(),
                       "--workers", str(workers), "--out-dir", str(out_dir)])
    return out_dir


def load_config(path):
    """{ticker: [SetupSpec]} from a monitor config file."""
    config = json.loads(Path(path).read_text())
    return {ticker: [build_setup_spec(entry["setup"] if isinstance(entry, dict) else entry) for entry in setups]
            for ticker, setups in config["tickers"].items()}
