"""
Tests for refactored SimpleStrategy with StrategyConfig support.

Validates that:
1. New config-based initialization works
2. Legacy parameter-based initialization still works (backward compatibility)
3. All config values are correctly mapped to instance variables
"""

from alpha_tech_tracker.tsla_strategy import SimpleStrategy
from alpha_tech_tracker.strategy_config import (
    StrategyConfig,
    TradingInstrumentConfig,
    EntryTriggerConfig,
    ExitTriggerConfig,
    RiskManagementConfig,
)


class TestSimpleStrategyRefactored:
    """Test refactored SimpleStrategy with config support."""

    def test_legacy_initialization_still_works(self):
        """Old way of initialization should still work for backward compatibility."""
        strategy = SimpleStrategy(symbol="TSLA")

        assert strategy.symbol == "TSLA"
        assert strategy.asset_type == "option"
        # Should use default config values
        assert strategy.buy_trigger_up_waves_ratio == 0.4
        assert strategy.maximum_position_loss == 800.0

    def test_legacy_with_risk_reward_override(self):
        """Legacy parameter should override config default."""
        strategy = SimpleStrategy(symbol="AAPL", buy_trigger_risk_reward_ratio=1.5)

        assert strategy.symbol == "AAPL"
        assert strategy.buy_trigger_risk_reward_ratio == 1.5

    def test_new_config_based_initialization(self):
        """New config-based initialization should work."""
        config = StrategyConfig.conservative_tsla()
        strategy = SimpleStrategy(config=config)

        assert strategy.symbol == "TSLA"
        # Should use conservative config values
        assert strategy.buy_trigger_up_waves_ratio == 0.5
        assert strategy.buy_trigger_up_magnitude_ratio == 0.6
        assert strategy.maximum_position_loss == 500.0

    def test_config_stored_for_reference(self):
        """Config should be accessible after initialization."""
        config = StrategyConfig.aggressive_tsla()
        strategy = SimpleStrategy(config=config)

        assert strategy.config is not None
        assert strategy.config.instrument.symbol == "TSLA"
        assert strategy.config.entry.up_waves_ratio == 0.35

    def test_trading_instrument_config_mapped(self):
        """Trading instrument config should map to instance variables."""
        config = StrategyConfig(
            instrument=TradingInstrumentConfig(
                symbol="NVDA", asset_type="stock", option_strike_price_delta=40
            )
        )
        strategy = SimpleStrategy(config=config)

        assert strategy.symbol == "NVDA"
        assert strategy.asset_type == "stock"
        assert strategy.target_option_strike_price_delta == 40

    def test_entry_trigger_config_mapped(self):
        """Entry trigger config should map correctly."""
        config = StrategyConfig(
            instrument=TradingInstrumentConfig(symbol="AMZN"),
            entry=EntryTriggerConfig(
                up_waves_ratio=0.45, up_magnitude_ratio=0.55, risk_reward_ratio=1.4
            ),
        )
        strategy = SimpleStrategy(config=config)

        assert strategy.buy_trigger_up_waves_ratio == 0.45
        assert strategy.buy_trigger_up_magnitude_ratio == 0.55
        assert strategy.buy_trigger_risk_reward_ratio == 1.4

    def test_exit_trigger_config_mapped(self):
        """Exit trigger config should map correctly."""
        config = StrategyConfig(
            instrument=TradingInstrumentConfig(symbol="TSLA"),
            exit=ExitTriggerConfig(
                up_magnitude_ratio=0.40,
                down_wave_length_ratio=0.35,
                down_wave_pickup_steam_up_magnitude_ratio=0.25,
            ),
        )
        strategy = SimpleStrategy(config=config)

        assert strategy.waves_loosing_steam_up_magnitude_ratio == 0.40
        assert strategy.waves_loosing_steam_down_wave_length_ratio == 0.35
        assert (
            strategy.waves_loosing_steam_down_wave_pickup_steam_up_magnitude_ratio
            == 0.25
        )

    def test_risk_management_config_mapped(self):
        """Risk management config should map correctly."""
        config = StrategyConfig(
            instrument=TradingInstrumentConfig(symbol="TSLA"),
            risk=RiskManagementConfig(
                maximum_position_loss=1200.0,
                max_trades_per_day=3,
                trade_size=4,
                discounted_magnitudes_factor=0.75,
            ),
        )
        strategy = SimpleStrategy(config=config)

        assert strategy.maximum_position_loss == 1200.0
        assert strategy.max_trade_per_day == 3
        assert strategy.trade_size == 4
        assert strategy.discounted_magnitudues_factor == 0.75

    def test_market_data_config_mapped(self):
        """Market data config should map correctly."""
        config = StrategyConfig.default_for_symbol("TSLA")
        strategy = SimpleStrategy(config=config)

        assert strategy.moving_average_periods == [20, 50, 100, 200]
        assert strategy.market_data_timeout == 3600 * 7
        assert strategy.plot_market_data_candle_stick_chart == False

    def test_notification_config_mapped(self):
        """Notification config should map correctly."""
        config = StrategyConfig.default_for_symbol("TSLA")
        strategy = SimpleStrategy(config=config)

        # Default should use existing phone number
        assert strategy.send_to_phone_number == "4086130570"
        assert strategy.disabled_sending_sms == False
        assert strategy.only_send_real_time_trade_alert == True

    def test_advanced_signal_config_mapped(self):
        """Advanced signal config should map correctly."""
        config = StrategyConfig.default_for_symbol("TSLA")
        strategy = SimpleStrategy(config=config)

        assert strategy.bullish_up_wave_move_size == 50
        assert strategy.bullish_up_wave_magnitude_ratio == 0.51
        assert strategy.bullish_up_waves_ratio == 0.51
        assert isinstance(strategy.signal_trigger_params, dict)

    def test_portfolio_and_engine_initialized(self):
        """Portfolio and order engine should be initialized."""
        config = StrategyConfig.default_for_symbol("TSLA")
        strategy = SimpleStrategy(config=config)

        assert strategy.portfolio is not None
        assert strategy.order_engine is not None
        assert strategy.waves == []
        assert strategy.active_positions == {}

    def test_skip_historical_trades_flag(self):
        """skip_place_historical_trades flag should work."""
        config = StrategyConfig.default_for_symbol("TSLA")
        strategy = SimpleStrategy(config=config, skip_place_historical_trades=True)

        assert strategy.skip_place_historical_trades == True

    def test_trade_api_client_integration(self):
        """Trade API client should integrate with order engine."""
        config = StrategyConfig.default_for_symbol("TSLA")

        # Mock client (just needs to be not None)
        mock_client = object()
        strategy = SimpleStrategy(config=config, trade_api_client=mock_client)

        assert strategy.trade_api_client is mock_client
        assert strategy.order_engine.engine_name == "etrade"


class TestConfigPresetIntegration:
    """Test that preset configs work correctly with SimpleStrategy."""

    def test_conservative_tsla_preset(self):
        """Conservative TSLA preset should have conservative values."""
        config = StrategyConfig.conservative_tsla()
        strategy = SimpleStrategy(config=config)

        # Entry should be selective
        assert strategy.buy_trigger_up_waves_ratio >= 0.5
        assert strategy.buy_trigger_risk_reward_ratio >= 1.5

        # Risk should be controlled
        assert strategy.maximum_position_loss <= 500.0
        assert strategy.trade_size <= 1

    def test_aggressive_tsla_preset(self):
        """Aggressive TSLA preset should have aggressive values."""
        config = StrategyConfig.aggressive_tsla()
        strategy = SimpleStrategy(config=config)

        # Entry should be permissive
        assert strategy.buy_trigger_up_waves_ratio <= 0.35

        # Risk should be higher
        assert strategy.maximum_position_loss >= 1500.0
        assert strategy.max_trade_per_day >= 5

    def test_default_for_symbol(self):
        """Default symbol config should use balanced defaults."""
        config = StrategyConfig.default_for_symbol("AAPL")
        strategy = SimpleStrategy(config=config)

        assert strategy.symbol == "AAPL"
        # Should use moderate defaults
        assert strategy.buy_trigger_up_waves_ratio == 0.4
        assert strategy.maximum_position_loss == 800.0


class TestBackwardCompatibility:
    """Ensure existing code patterns still work."""

    def test_existing_test_pattern_works(self):
        """Pattern from existing tests should still work."""
        new_strategy = SimpleStrategy(symbol="TSLA")
        assert isinstance(new_strategy, SimpleStrategy)

    def test_can_compare_old_and_new_approach(self):
        """Old and new approaches should produce same configuration."""
        # Old way
        strategy_old = SimpleStrategy(symbol="TSLA")

        # New way with defaults
        config = StrategyConfig.default_for_symbol("TSLA")
        strategy_new = SimpleStrategy(config=config)

        # Should have same configuration values
        assert strategy_old.symbol == strategy_new.symbol
        assert (
            strategy_old.buy_trigger_up_waves_ratio
            == strategy_new.buy_trigger_up_waves_ratio
        )
        assert strategy_old.maximum_position_loss == strategy_new.maximum_position_loss
        assert strategy_old.trade_size == strategy_new.trade_size


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_none_symbol_handled(self):
        """If no symbol or config provided, should use default."""
        strategy = SimpleStrategy()
        # Should create default config with symbol "None"
        assert strategy.symbol == "None"
        assert strategy.config is not None

    def test_config_overrides_symbol_parameter(self):
        """If both config and symbol provided, config should win."""
        config = StrategyConfig.default_for_symbol("AAPL")
        strategy = SimpleStrategy(config=config, symbol="TSLA")

        # Config should take precedence
        assert strategy.symbol == "AAPL"

    def test_phone_number_fallback(self):
        """If no phone number in config, should use default."""
        config = StrategyConfig.default_for_symbol("TSLA")
        # Config has phone_number=None
        strategy = SimpleStrategy(config=config)

        # Should fallback to hardcoded default
        assert strategy.send_to_phone_number == "4086130570"
