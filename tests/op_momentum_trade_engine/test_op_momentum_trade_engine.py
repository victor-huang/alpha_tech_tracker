from argparse import Namespace
from unittest.mock import Mock, patch

from alpha_tech_tracker.op_momentum_strategy.contract_selector import (
    ITMOptionContractSelector,
    TimePremiumContractSelector,
)
from alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine import (
    _build_contract_selector,
    _build_market_data_client,
    _build_option_price_monitor,
    _build_sip_quote_client,
    _resolve_is_paper,
)
from alpha_tech_tracker.op_momentum_strategy.option_price_monitor import (
    OptionPriceMonitor,
    TradeEngineStrikeSelector,
)

from conftest import _make_alpaca_client


def _args(**kwargs):
    defaults = {
        "option_selector": "standard",
        "time_premium_pct_cap": 0.01,
        "collect_option_prices": False,
        "option_price_interval": 300,
        "tickers": None,
        "feed": "iex",
        "replay_date": None,
        "replay_start": None,
        "replay_end": None,
    }
    defaults.update(kwargs)
    return Namespace(**defaults)


class TestBuildContractSelector:
    def test_returns_itm_selector_when_option_selector_is_standard(self):
        client = _make_alpaca_client()
        selector = _build_contract_selector(_args(option_selector="standard"), client)
        assert isinstance(selector, ITMOptionContractSelector)

    def test_returns_time_premium_selector_when_option_selector_is_time_premium(self):
        client = _make_alpaca_client()
        selector = _build_contract_selector(_args(option_selector="time-premium"), client)
        assert isinstance(selector, TimePremiumContractSelector)

    def test_time_premium_selector_uses_pct_cap_from_args(self):
        client = _make_alpaca_client()
        selector = _build_contract_selector(
            _args(option_selector="time-premium", time_premium_pct_cap=0.02), client
        )
        from decimal import Decimal
        assert selector._time_premium_pct_cap == Decimal("0.02")


class TestBuildOptionPriceMonitor:
    def test_returns_none_when_collect_option_prices_is_false(self):
        client = _make_alpaca_client()
        selector = Mock()
        monitor = _build_option_price_monitor(
            _args(collect_option_prices=False), client, None, selector
        )
        assert monitor is None

    def test_returns_option_price_monitor_when_collect_option_prices_is_true(self):
        client = _make_alpaca_client()
        selector = Mock()
        monitor = _build_option_price_monitor(
            _args(collect_option_prices=True), client, ["TSLA"], selector
        )
        assert isinstance(monitor, OptionPriceMonitor)

    def test_monitor_wraps_contract_selector_in_trade_engine_strike_selector(self):
        client = _make_alpaca_client()
        selector = Mock()
        monitor = _build_option_price_monitor(
            _args(collect_option_prices=True), client, ["TSLA"], selector
        )
        assert isinstance(monitor._contract_selector, TradeEngineStrikeSelector)
        assert monitor._contract_selector._selector is selector

    def test_monitor_uses_interval_from_args(self):
        client = _make_alpaca_client()
        selector = Mock()
        monitor = _build_option_price_monitor(
            _args(collect_option_prices=True, option_price_interval=120),
            client, ["TSLA"], selector,
        )
        assert monitor._interval == 120

    def test_monitor_uses_default_tickers_when_none_provided(self):
        client = _make_alpaca_client()
        selector = Mock()
        with patch(
            # _build_option_price_monitor moved to the cli.clients module; the
            # default-ticker fallback resolves TICKERS from there.
            "alpha_tech_tracker.op_momentum_strategy.cli.clients.TICKERS",
            ["TSLA", "NVDA"],
        ):
            monitor = _build_option_price_monitor(
                _args(collect_option_prices=True), client, None, selector
            )
        assert monitor._tickers == ["TSLA", "NVDA"]


class TestResolveIsPaper:
    def test_default_is_paper(self):
        assert _resolve_is_paper(_args()) is True

    def test_live_flag_is_not_paper(self):
        assert _resolve_is_paper(_args(live=True)) is False

    def test_replay_without_live_is_paper(self):
        assert _resolve_is_paper(_args(replay_date="2026-04-01")) is True

    def test_replay_range_without_live_is_paper(self):
        assert _resolve_is_paper(_args(replay_start="2026-04-01", replay_end="2026-04-10")) is True

    def test_replay_with_live_flag_is_not_paper(self):
        assert _resolve_is_paper(_args(live=True, replay_date="2026-04-01")) is False

    def test_replay_range_with_live_flag_is_not_paper(self):
        assert _resolve_is_paper(_args(live=True, replay_start="2026-04-01", replay_end="2026-04-10")) is False


class TestBuildMarketDataClient:
    def test_returns_none_for_alpaca_source(self):
        with patch("alpha_tech_tracker.op_momentum_strategy.config._load_config"):
            result = _build_market_data_client(_args(market_data_source="alpaca"))
        assert result is None

    def test_returns_none_when_market_data_source_missing(self):
        with patch("alpha_tech_tracker.op_momentum_strategy.config._load_config"):
            result = _build_market_data_client(_args())
        assert result is None

    def test_returns_tradestation_client_for_tradestation_source(self):
        from alpha_tech_tracker.trade_api.tradestation.market_data_client import (
            TradeStationMarketDataClient,
        )
        mock_ts_client = Mock()
        with patch("alpha_tech_tracker.op_momentum_strategy.config._load_config"), \
             patch(
                 "alpha_tech_tracker.trade_api.tradestation.client.TradeStationAPIClient",
                 return_value=mock_ts_client,
             ):
            mock_ts_client.verify_session.return_value = True
            result = _build_market_data_client(_args(market_data_source="tradestation"))

        assert isinstance(result, TradeStationMarketDataClient)
        mock_ts_client.restore_session.assert_called_once()

    def test_raises_when_tradestation_session_invalid(self):
        import pytest
        mock_ts_client = Mock()
        with patch("alpha_tech_tracker.op_momentum_strategy.config._load_config"), \
             patch(
                 "alpha_tech_tracker.trade_api.tradestation.client.TradeStationAPIClient",
                 return_value=mock_ts_client,
             ):
            mock_ts_client.verify_session.return_value = False
            with pytest.raises(RuntimeError, match="TradeStation session invalid"):
                _build_market_data_client(_args(market_data_source="tradestation"))


_TS_TOKENS_PATH = "alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine._build_sip_quote_client"
_TS_CLIENT_IMPORT = "alpha_tech_tracker.trade_api.tradestation.client.TradeStationAPIClient"
_TS_TOKENS_CONFIG = "alpha_tech_tracker.op_momentum_strategy.config._TRADESTATION_SESSION_TOKENS"
_TS_ENV_CONFIG = "alpha_tech_tracker.op_momentum_strategy.config.TRADESTATION_ENVIRONMENT"


class TestBuildSipQuoteClient:
    def test_returns_none_when_feed_is_not_iex(self):
        result = _build_sip_quote_client(_args(feed="sip"))
        assert result is None

    def test_returns_none_when_feed_attribute_missing(self):
        result = _build_sip_quote_client(Namespace())
        assert result is None

    def test_returns_none_when_no_access_token(self):
        with patch(_TS_TOKENS_CONFIG, {"access_token": ""}):
            result = _build_sip_quote_client(_args(feed="iex"))
        assert result is None

    def test_returns_none_when_tokens_dict_is_empty(self):
        with patch(_TS_TOKENS_CONFIG, {}):
            result = _build_sip_quote_client(_args(feed="iex"))
        assert result is None

    def test_returns_none_when_session_expired(self):
        mock_ts = Mock()
        mock_ts.verify_session.return_value = False
        with patch(_TS_TOKENS_CONFIG, {"access_token": "tok"}), \
             patch(_TS_ENV_CONFIG, "Live"), \
             patch(_TS_CLIENT_IMPORT, return_value=mock_ts):
            result = _build_sip_quote_client(_args(feed="iex"))
        assert result is None
        mock_ts.restore_session.assert_called_once()

    def test_returns_ts_client_when_session_valid(self):
        mock_ts = Mock()
        mock_ts.verify_session.return_value = True
        with patch(_TS_TOKENS_CONFIG, {"access_token": "tok"}), \
             patch(_TS_ENV_CONFIG, "Live"), \
             patch(_TS_CLIENT_IMPORT, return_value=mock_ts):
            result = _build_sip_quote_client(_args(feed="iex"))
        assert result is mock_ts

    def test_returns_none_when_ts_init_raises(self):
        with patch(_TS_TOKENS_CONFIG, {"access_token": "tok"}), \
             patch(_TS_ENV_CONFIG, "Live"), \
             patch(_TS_CLIENT_IMPORT, side_effect=Exception("import error")):
            result = _build_sip_quote_client(_args(feed="iex"))
        assert result is None
