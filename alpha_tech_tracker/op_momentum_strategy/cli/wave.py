"""`--strategy wave-setups`: build and run a WaveStrategyRunner from the trade engine's arguments.

The runner trades the wave setup monitor's intraday signals; the monitor keeps running on its own (separate process,
state, CSV). The engine is intraday only: overnight setups in the config are not traded.
"""
import logging
import os
import signal
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime

from .daemon import _LOG_DIR

logger = logging.getLogger(__name__)


def wave_log_file():
    return os.path.join(_LOG_DIR, f"wave_strategy_engine_{date.today()}.log")


def wave_setups(args):
    """{ticker: [SetupSpec]} from --wave-config, plus the short tickers when shorts are on. Overnight setups stay in
    (the strategy runs intraday_only, as in the parity replays) and are never traded."""
    from ..wave_strategy.specs import load_config

    setups = load_config(args.wave_config)
    overnight = sorted(t for t, specs in setups.items() if any(s.overnight for s in specs))
    if overnight:
        logger.info("Overnight setups are not traded by the engine: %s", ", ".join(overnight))
    short_setups = wave_short_setups(args)
    for ticker in (args.short_tickers or list(setups)) if short_setups else []:
        setups.setdefault(ticker, [])
    return setups


def wave_short_setups(args):
    return [] if args.no_short_setups or args.short_gate == "off" else args.short_setups


def build_wave_runner(args, execution_client, mock):
    from ..wave_setup_monitor import build_market_data_client
    from ..wave_strategy.trades import InlineExecutor
    from ..wave_strategy_runner import WaveStrategyRunner

    setups = wave_setups(args)
    short_setups = wave_short_setups(args)
    executor = InlineExecutor() if args.workers == 0 else ProcessPoolExecutor(max_workers=args.workers)
    return WaveStrategyRunner(
        setups, build_market_data_client(args), execution_client=execution_client, mock=mock,
        balance=args.wave_balance, slots=args.wave_slots, state_file=args.wave_state_file, executor=executor,
        close_decision_bar=datetime.strptime(args.close_decision_bar, "%H:%M").time(), short_setups=short_setups,
        short_gate=args.short_gate, short_tickers=(args.short_tickers or list(setups)) if short_setups else [],
        drive_trail=args.drive_trail, drive_reentry=args.drive_reentry, trend_filters=args.trend_filters)


def run_wave_strategy(args, execution_client, mock):
    """Run one session. SIGTERM (daemon stop / restart) ends it like Ctrl-C: open positions stay in the state file
    for a same-session restart."""
    runner = build_wave_runner(args, execution_client, mock)

    def _stop(signum, frame):
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, _stop)
    try:
        runner.run()
    except KeyboardInterrupt:
        logger.info("Stopped")
    finally:
        signal.signal(signal.SIGTERM, previous)
