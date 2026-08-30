"""Construction of the market-data, quote, contract-selector and option-price
collaborators the trade engine needs, resolved from parsed CLI args.

Extracted verbatim from op_momentum_trade_engine.py.
"""
import logging

from alpaca.data.enums import DataFeed

from ..config import TICKERS
from ..contract_selector import ITMOptionContractSelector, TimePremiumContractSelector
from ..option_price_monitor import OptionPriceMonitor, TradeEngineStrikeSelector

logger = logging.getLogger(__name__)


def _build_sip_quote_client(args):
    """Return a TradeStation SIP client for parallel quote comparison when feed=IEX, or None.

    Skips if the TS session file is missing or expired — the Alpaca client
    will use its own IEX quote in that case.
    """
    if getattr(args, "feed", None) != "iex":
        return None
    from alpha_tech_tracker.op_momentum_strategy.config import (
        _TRADESTATION_SESSION_TOKENS,
        TRADESTATION_ENVIRONMENT,
    )
    if not _TRADESTATION_SESSION_TOKENS.get("access_token"):
        logger.debug("IEX feed: no TS session tokens found, skipping quote fallback")
        return None
    try:
        from alpha_tech_tracker.trade_api.tradestation.client import TradeStationAPIClient
        ts_client = TradeStationAPIClient(environment=TRADESTATION_ENVIRONMENT)
        ts_client.restore_session(_TRADESTATION_SESSION_TOKENS)
        if not ts_client.verify_session():
            logger.warning("IEX feed: TS session expired — SIP quote client disabled, run tradestation_auth.py to enable")
            return None
        logger.info("IEX feed: TradeStation SIP quote client enabled")
        return ts_client
    except Exception:
        logger.warning("IEX feed: failed to init TS SIP quote client — proceeding without it", exc_info=True)
        return None


def _build_market_data_client(args):
    """Return a MarketDataClient based on --market-data-source, or None for default Alpaca.

    Resolution order: CLI flag → config.json 'market_data_source' → 'alpaca'.
    """
    from alpha_tech_tracker.op_momentum_strategy.config import (
        _load_config,
        MARKET_DATA_SOURCE,
        TS_BROADCAST_SOCKET_PATH,
        _TRADESTATION_SESSION_TOKENS,
        TRADESTATION_ENVIRONMENT,
    )
    _load_config()
    source = getattr(args, "market_data_source", None) or MARKET_DATA_SOURCE

    if source == "tradestation":
        from alpha_tech_tracker.trade_api.tradestation.client import TradeStationAPIClient
        from alpha_tech_tracker.trade_api.tradestation.market_data_client import (
            TradeStationMarketDataClient,
        )
        ts_client = TradeStationAPIClient(environment=TRADESTATION_ENVIRONMENT)
        ts_client.restore_session(_TRADESTATION_SESSION_TOKENS)
        if not ts_client.verify_session():
            raise RuntimeError(
                "TradeStation session invalid — run tradestation_auth.py first"
            )
        logger.info("Market data source: TradeStation (env=%s)", TRADESTATION_ENVIRONMENT)
        return TradeStationMarketDataClient(ts_client)

    if source == "local_ts_broadcast":
        from alpha_tech_tracker.trade_api.tradestation.client import TradeStationAPIClient
        from alpha_tech_tracker.trade_api.local_ts_broadcast.market_data_client import (
            LocalTSBroadcastMarketDataClient,
        )
        ts_client = TradeStationAPIClient(environment=TRADESTATION_ENVIRONMENT)
        ts_client.restore_session(_TRADESTATION_SESSION_TOKENS)
        logger.info("Market data source: local_ts_broadcast (socket=%s)", TS_BROADCAST_SOCKET_PATH)
        return LocalTSBroadcastMarketDataClient(ts_client, socket_path=TS_BROADCAST_SOCKET_PATH)

    return None  # caller defaults to AlpacaMarketDataClient


def _build_option_price_monitor(args, client, tickers, contract_selector):
    if not args.collect_option_prices:
        return None
    if not getattr(args, "live", False):
        logger.warning(
            "--collect-option-prices requires --live; option contract lookups will "
            "fail with 401 on the paper account (paper account lacks options approval)"
        )
    return OptionPriceMonitor(
        client=client,
        tickers=tickers or TICKERS,
        interval_seconds=args.option_price_interval,
        contract_selector=TradeEngineStrikeSelector(contract_selector),
        feed=DataFeed.IEX if args.feed == "iex" else DataFeed.SIP,
    )


def _warn_replay_feed_mismatch(args):
    """Warn when --live-data-feed is set but --market-data-source isn't.

    --live-data-feed only swaps the *intraday* OR bars (read from recorded CSVs).
    Signal-engine warmup (90-day MA history) and ticker-selector scoring (60-day
    rolling stats) still come from Alpaca SIP unless --market-data-source is also
    set. Mixing TS intraday with Alpaca warmup/scoring routinely produces
    different picks than the live engine that recorded the CSVs.
    """
    if not args.live_data_dir or not args.live_data_feed:
        return
    if args.live_data_feed != "tradestation":
        return
    if getattr(args, "market_data_source", None) == "tradestation":
        return
    logger.warning(
        "Replay flag mismatch: --live-data-feed tradestation feeds OR bars from "
        "TS recordings, but --market-data-source is not set so signal-engine "
        "warmup and selector scoring fall back to Alpaca SIP. Picks may diverge "
        "from the live TS engine. Add --market-data-source tradestation to match."
    )


def _build_contract_selector(args, client):
    if args.option_selector == "time-premium":
        return TimePremiumContractSelector(
            client, time_premium_pct_cap=args.time_premium_pct_cap
        )
    return ITMOptionContractSelector(client)
