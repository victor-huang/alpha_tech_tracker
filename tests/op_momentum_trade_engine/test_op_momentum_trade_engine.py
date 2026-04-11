from argparse import Namespace
from unittest.mock import Mock, patch

from alpha_tech_tracker.op_momentum_strategy.contract_selector import (
    ITMOptionContractSelector,
    TimePremiumContractSelector,
)
from alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine import (
    _build_contract_selector,
    _build_option_price_monitor,
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
            "alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine.TICKERS",
            ["TSLA", "NVDA"],
        ):
            monitor = _build_option_price_monitor(
                _args(collect_option_prices=True), client, None, selector
            )
        assert monitor._tickers == ["TSLA", "NVDA"]
