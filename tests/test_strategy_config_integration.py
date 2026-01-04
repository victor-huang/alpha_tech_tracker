"""
Integration tests demonstrating real-world config usage patterns.

These tests show how the config system will be used in practice.
"""

from alpha_tech_tracker.strategy_config import (
    StrategyConfig,
    TradingInstrumentConfig,
    EntryTriggerConfig,
    ExitTriggerConfig,
    RiskManagementConfig,
    NotificationConfig,
)


class TestRealWorldUsagePatterns:
    """Test configs as they would be used in actual trading scenarios."""

    def test_quick_start_with_preset(self):
        """Most common use case: start with a preset."""
        config = StrategyConfig.conservative_tsla()

        # Verify it's ready to use
        assert config.instrument.symbol == "TSLA"
        assert config.instrument.asset_type == "option"
        assert config.entry.up_waves_ratio > 0
        assert config.risk.maximum_position_loss > 0

    def test_customize_one_aspect(self):
        """Common pattern: use preset but tweak one area."""
        config = StrategyConfig(
            instrument=TradingInstrumentConfig(symbol="AAPL"),
            entry=EntryTriggerConfig.conservative(),
            exit=ExitTriggerConfig.balanced(),
            risk=RiskManagementConfig(maximum_position_loss=1200.0),  # Custom stop-loss
        )

        assert config.instrument.symbol == "AAPL"
        assert config.entry.up_waves_ratio == 0.5  # Conservative
        assert config.risk.maximum_position_loss == 1200.0  # Custom

    def test_volatile_stock_config(self):
        """Configuration for volatile stocks like TSLA, NVDA."""
        config = StrategyConfig(
            instrument=TradingInstrumentConfig(
                symbol="NVDA", option_strike_price_delta=40  # Deeper ITM for safety
            ),
            entry=EntryTriggerConfig.conservative(),  # Wait for clear signals
            exit=ExitTriggerConfig.tight_stops(),  # Exit fast
            risk=RiskManagementConfig(
                maximum_position_loss=600.0,  # Tight stop
                trade_size=1,  # Smaller position
            ),
        )

        assert config.instrument.option_strike_price_delta == 40
        assert config.risk.maximum_position_loss == 600.0
        assert config.risk.trade_size == 1

    def test_strong_uptrend_config(self):
        """Configuration for riding strong uptrends."""
        config = StrategyConfig(
            instrument=TradingInstrumentConfig(symbol="AAPL"),
            entry=EntryTriggerConfig.aggressive(),  # More entries
            exit=ExitTriggerConfig.loose_stops(),  # Hold longer
            risk=RiskManagementConfig(
                maximum_position_loss=1500.0, max_trades_per_day=4
            ),
        )

        assert config.entry.up_waves_ratio < 0.4  # More aggressive
        assert config.exit.up_magnitude_ratio < 0.35  # Hold longer
        assert config.risk.max_trades_per_day == 4

    def test_choppy_market_config(self):
        """Configuration for sideways/choppy markets."""
        config = StrategyConfig(
            instrument=TradingInstrumentConfig(symbol="SPY"),
            entry=EntryTriggerConfig.conservative(),  # Very selective
            exit=ExitTriggerConfig.tight_stops(),  # Quick exits
            risk=RiskManagementConfig.conservative(),  # Small positions
        )

        assert config.entry.risk_reward_ratio >= 1.5  # Need good risk/reward
        assert config.risk.maximum_position_loss == 500.0
        assert config.risk.max_trades_per_day == 1

    def test_backtesting_config(self):
        """Configuration for backtesting with notifications disabled."""
        config = StrategyConfig(
            instrument=TradingInstrumentConfig(symbol="TSLA"),
            notifications=NotificationConfig(disabled=True),  # No SMS during backtests
        )

        assert config.notifications.disabled == True

    def test_paper_trading_config(self):
        """Configuration for paper trading with alerts enabled."""
        config = StrategyConfig(
            instrument=TradingInstrumentConfig(symbol="AMZN"),
            entry=EntryTriggerConfig.moderate(),
            notifications=NotificationConfig(
                phone_number="5551234567", only_real_time_alerts=True
            ),
        )

        assert config.notifications.phone_number == "5551234567"
        assert config.notifications.only_real_time_alerts == True


class TestConfigModification:
    """Test that configs can be modified after creation."""

    def test_modify_entry_thresholds(self):
        """Adjust entry thresholds based on market conditions."""
        config = StrategyConfig.default_for_symbol("TSLA")

        # Start with defaults
        original_ratio = config.entry.up_waves_ratio

        # Adjust for more aggressive entries
        config.entry.up_waves_ratio = 0.35
        assert config.entry.up_waves_ratio == 0.35
        assert config.entry.up_waves_ratio != original_ratio

    def test_adjust_risk_limits(self):
        """Adjust risk parameters during trading."""
        config = StrategyConfig.default_for_symbol("AAPL")

        # Tighten stops after losses
        config.risk.maximum_position_loss = 500.0
        config.risk.max_trades_per_day = 1

        assert config.risk.maximum_position_loss == 500.0
        assert config.risk.max_trades_per_day == 1


class TestConfigSerialization:
    """Test that configs can be inspected and compared."""

    def test_config_values_accessible(self):
        """All config values should be easily accessible."""
        config = StrategyConfig.conservative_tsla()

        # Should be able to read all important values
        assert hasattr(config.instrument, "symbol")
        assert hasattr(config.entry, "up_waves_ratio")
        assert hasattr(config.exit, "up_magnitude_ratio")
        assert hasattr(config.risk, "maximum_position_loss")

    def test_compare_two_configs(self):
        """Should be able to compare config differences."""
        conservative = StrategyConfig.conservative_tsla()
        aggressive = StrategyConfig.aggressive_tsla()

        # Entry thresholds should be different
        assert conservative.entry.up_waves_ratio > aggressive.entry.up_waves_ratio

        # Risk limits should be different
        assert (
            conservative.risk.maximum_position_loss
            < aggressive.risk.maximum_position_loss
        )


class TestConfigValidation:
    """Test that configs maintain logical consistency."""

    def test_conservative_is_actually_conservative(self):
        """Conservative presets should have conservative values."""
        config = StrategyConfig.conservative_tsla()

        # Entry should be selective (high thresholds)
        assert config.entry.up_waves_ratio >= 0.5
        assert config.entry.risk_reward_ratio >= 1.5

        # Risk should be controlled (low limits)
        assert config.risk.maximum_position_loss <= 500.0
        assert config.risk.trade_size <= 1

    def test_aggressive_is_actually_aggressive(self):
        """Aggressive presets should have aggressive values."""
        config = StrategyConfig.aggressive_tsla()

        # Entry should be permissive (low thresholds)
        assert config.entry.up_waves_ratio <= 0.35

        # Risk should be higher (high limits)
        assert config.risk.maximum_position_loss >= 1500.0
        assert config.risk.max_trades_per_day >= 5

    def test_all_presets_are_valid(self):
        """All preset combinations should be valid configs."""
        configs = [
            StrategyConfig.default_for_symbol("TSLA"),
            StrategyConfig.conservative_tsla(),
            StrategyConfig.aggressive_tsla(),
        ]

        for config in configs:
            # All should have valid instruments
            assert config.instrument.symbol is not None
            assert config.instrument.asset_type in ["stock", "option"]

            # All should have positive risk limits
            assert config.risk.maximum_position_loss > 0
            assert config.risk.max_trades_per_day > 0

            # All ratios should be between 0 and 1
            assert 0 < config.entry.up_waves_ratio < 1
            assert 0 < config.entry.up_magnitude_ratio < 1
            assert 0 < config.exit.up_magnitude_ratio < 1


class TestConfigDocumentation:
    """Verify configs are self-documenting."""

    def test_dataclasses_have_docstrings(self):
        """All config classes should have docstrings."""
        assert EntryTriggerConfig.__doc__ is not None
        assert ExitTriggerConfig.__doc__ is not None
        assert RiskManagementConfig.__doc__ is not None

    def test_preset_methods_have_docstrings(self):
        """Preset factory methods should have docstrings."""
        assert EntryTriggerConfig.conservative.__doc__ is not None
        assert ExitTriggerConfig.tight_stops.__doc__ is not None
        assert RiskManagementConfig.conservative.__doc__ is not None
