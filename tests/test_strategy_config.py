"""
Tests for strategy configuration dataclasses.

Validates that all config classes instantiate correctly, presets work,
and parameters have sensible defaults.
"""

import pytest
from alpha_tech_tracker.strategy_config import (
    TradingInstrumentConfig,
    EntryTriggerConfig,
    ExitTriggerConfig,
    RiskManagementConfig,
    MarketDataConfig,
    NotificationConfig,
    AdvancedSignalConfig,
    StrategyConfig,
)


class TestTradingInstrumentConfig:
    def test_default_creation(self):
        config = TradingInstrumentConfig(symbol="TSLA")
        assert config.symbol == "TSLA"
        assert config.asset_type == "option"
        assert config.option_strike_price_delta == 30
        assert config.option_type == "call"

    def test_stock_config(self):
        config = TradingInstrumentConfig(symbol="AAPL", asset_type="stock")
        assert config.symbol == "AAPL"
        assert config.asset_type == "stock"

    def test_osi_key_generation(self):
        config = TradingInstrumentConfig(
            symbol="TSLA", option_expiry="240614", option_type="call"
        )
        osi_key = config.osi_key
        assert osi_key.startswith("TSLA--")
        assert "240614C" in osi_key


class TestEntryTriggerConfig:
    def test_default_creation(self):
        config = EntryTriggerConfig()
        assert config.up_waves_ratio == 0.4
        assert config.up_magnitude_ratio == 0.51
        assert config.risk_reward_ratio == 1.3

    def test_conservative_preset(self):
        config = EntryTriggerConfig.conservative()
        assert config.up_waves_ratio == 0.5
        assert config.up_magnitude_ratio == 0.6
        assert config.risk_reward_ratio == 1.5
        # Conservative should be more selective (higher thresholds)
        assert config.up_waves_ratio > EntryTriggerConfig().up_waves_ratio

    def test_moderate_preset(self):
        config = EntryTriggerConfig.moderate()
        # Moderate should match defaults
        default = EntryTriggerConfig()
        assert config.up_waves_ratio == default.up_waves_ratio
        assert config.up_magnitude_ratio == default.up_magnitude_ratio

    def test_aggressive_preset(self):
        config = EntryTriggerConfig.aggressive()
        assert config.up_waves_ratio == 0.35
        assert config.up_magnitude_ratio == 0.48
        assert config.risk_reward_ratio == 1.1
        # Aggressive should be less selective (lower thresholds)
        assert config.up_waves_ratio < EntryTriggerConfig().up_waves_ratio

    def test_custom_values(self):
        config = EntryTriggerConfig(up_waves_ratio=0.45, up_magnitude_ratio=0.55)
        assert config.up_waves_ratio == 0.45
        assert config.up_magnitude_ratio == 0.55
        # Other params should use defaults
        assert config.risk_reward_ratio == 1.3


class TestExitTriggerConfig:
    def test_default_creation(self):
        config = ExitTriggerConfig()
        assert config.up_magnitude_ratio == 0.38
        assert config.down_wave_length_ratio == 0.38
        assert config.down_wave_pickup_steam_up_magnitude_ratio == 0.2

    def test_tight_stops_preset(self):
        config = ExitTriggerConfig.tight_stops()
        assert config.up_magnitude_ratio == 0.45
        assert config.down_wave_length_ratio == 0.3
        # Tight stops should exit sooner
        assert config.up_magnitude_ratio > ExitTriggerConfig().up_magnitude_ratio

    def test_balanced_preset(self):
        config = ExitTriggerConfig.balanced()
        default = ExitTriggerConfig()
        assert config.up_magnitude_ratio == default.up_magnitude_ratio

    def test_loose_stops_preset(self):
        config = ExitTriggerConfig.loose_stops()
        assert config.up_magnitude_ratio == 0.3
        assert config.down_wave_length_ratio == 0.5
        # Loose stops should hold longer
        assert config.up_magnitude_ratio < ExitTriggerConfig().up_magnitude_ratio


class TestRiskManagementConfig:
    def test_default_creation(self):
        config = RiskManagementConfig()
        assert config.maximum_position_loss == 800.0
        assert config.max_trades_per_day == 2
        assert config.trade_size == 2
        assert config.discounted_magnitudes_factor == 0.80

    def test_conservative_preset(self):
        config = RiskManagementConfig.conservative()
        assert config.maximum_position_loss == 500.0
        assert config.max_trades_per_day == 1
        assert config.trade_size == 1
        # Conservative should have tighter risk controls
        assert (
            config.maximum_position_loss < RiskManagementConfig().maximum_position_loss
        )

    def test_aggressive_preset(self):
        config = RiskManagementConfig.aggressive()
        assert config.maximum_position_loss == 1500.0
        assert config.max_trades_per_day == 5
        assert config.trade_size == 3
        # Aggressive should have looser risk controls
        assert (
            config.maximum_position_loss > RiskManagementConfig().maximum_position_loss
        )

    def test_custom_values(self):
        config = RiskManagementConfig(
            maximum_position_loss=1000.0, max_trades_per_day=3
        )
        assert config.maximum_position_loss == 1000.0
        assert config.max_trades_per_day == 3


class TestMarketDataConfig:
    def test_default_creation(self):
        config = MarketDataConfig()
        assert config.moving_average_periods == [20, 50, 100, 200]
        assert config.market_data_timeout == 3600 * 7  # 7 hours
        assert config.plot_candlestick_chart == False

    def test_custom_ma_periods(self):
        config = MarketDataConfig(moving_average_periods=[10, 20, 50])
        assert config.moving_average_periods == [10, 20, 50]

    def test_timeout_in_seconds(self):
        config = MarketDataConfig()
        # 7 hours = 25200 seconds
        assert config.market_data_timeout == 25200


class TestNotificationConfig:
    def test_default_creation(self):
        config = NotificationConfig()
        assert config.phone_number is None
        assert config.disabled == False
        assert config.only_real_time_alerts == True

    def test_with_phone_number(self):
        config = NotificationConfig(phone_number="4086130570")
        assert config.phone_number == "4086130570"

    def test_disabled_notifications(self):
        config = NotificationConfig(disabled=True)
        assert config.disabled == True


class TestAdvancedSignalConfig:
    def test_default_creation(self):
        config = AdvancedSignalConfig()
        assert config.bullish_up_wave_move_size == 50
        assert config.bullish_up_wave_magnitude_ratio == 0.51
        assert config.bullish_up_waves_ratio == 0.51
        assert isinstance(config.signal_trigger_params, dict)

    def test_signal_trigger_params(self):
        config = AdvancedSignalConfig()
        params = config.signal_trigger_params
        assert "gap_move" in params
        assert "long_tail_reversal_combo" in params
        assert "engulfing_reversal" in params
        assert params["gap_move"]["daily_movement_minimum"] == 0.5


class TestStrategyConfig:
    def test_default_creation_requires_instrument(self):
        """StrategyConfig requires at least an instrument config."""
        instrument = TradingInstrumentConfig(symbol="TSLA")
        config = StrategyConfig(instrument=instrument)

        assert config.instrument.symbol == "TSLA"
        assert isinstance(config.entry, EntryTriggerConfig)
        assert isinstance(config.exit, ExitTriggerConfig)
        assert isinstance(config.risk, RiskManagementConfig)
        assert isinstance(config.market_data, MarketDataConfig)
        assert isinstance(config.notifications, NotificationConfig)
        assert isinstance(config.advanced_signals, AdvancedSignalConfig)

    def test_default_for_symbol(self):
        config = StrategyConfig.default_for_symbol("AAPL")
        assert config.instrument.symbol == "AAPL"
        # Should use default settings for all other configs
        assert config.entry.up_waves_ratio == 0.4
        assert config.risk.maximum_position_loss == 800.0

    def test_conservative_tsla_preset(self):
        config = StrategyConfig.conservative_tsla()
        assert config.instrument.symbol == "TSLA"
        # Should use conservative presets
        assert config.entry.up_waves_ratio == 0.5  # Conservative entry
        assert config.exit.up_magnitude_ratio == 0.45  # Tight stops
        assert config.risk.maximum_position_loss == 500.0  # Conservative risk

    def test_aggressive_tsla_preset(self):
        config = StrategyConfig.aggressive_tsla()
        assert config.instrument.symbol == "TSLA"
        # Should use aggressive presets
        assert config.entry.up_waves_ratio == 0.35  # Aggressive entry
        assert config.exit.up_magnitude_ratio == 0.3  # Loose stops
        assert config.risk.maximum_position_loss == 1500.0  # Aggressive risk

    def test_mixed_config(self):
        """Test mixing presets with custom configs."""
        config = StrategyConfig(
            instrument=TradingInstrumentConfig(symbol="NVDA"),
            entry=EntryTriggerConfig.conservative(),
            exit=ExitTriggerConfig.tight_stops(),
            risk=RiskManagementConfig(maximum_position_loss=1200.0),
        )

        assert config.instrument.symbol == "NVDA"
        assert config.entry.up_waves_ratio == 0.5  # Conservative
        assert config.exit.up_magnitude_ratio == 0.45  # Tight stops
        assert config.risk.maximum_position_loss == 1200.0  # Custom

    def test_all_configs_accessible(self):
        """Ensure all config groups are accessible from master config."""
        config = StrategyConfig.default_for_symbol("AMZN")

        # Test we can access all config groups
        assert hasattr(config, "instrument")
        assert hasattr(config, "entry")
        assert hasattr(config, "exit")
        assert hasattr(config, "risk")
        assert hasattr(config, "market_data")
        assert hasattr(config, "notifications")
        assert hasattr(config, "advanced_signals")

    def test_custom_full_config(self):
        """Test creating fully custom configuration."""
        config = StrategyConfig(
            instrument=TradingInstrumentConfig(symbol="GME", asset_type="stock"),
            entry=EntryTriggerConfig(up_waves_ratio=0.42, up_magnitude_ratio=0.53),
            exit=ExitTriggerConfig(up_magnitude_ratio=0.40),
            risk=RiskManagementConfig(
                maximum_position_loss=900.0, max_trades_per_day=3
            ),
            notifications=NotificationConfig(phone_number="5551234567", disabled=False),
        )

        assert config.instrument.symbol == "GME"
        assert config.instrument.asset_type == "stock"
        assert config.entry.up_waves_ratio == 0.42
        assert config.exit.up_magnitude_ratio == 0.40
        assert config.risk.maximum_position_loss == 900.0
        assert config.notifications.phone_number == "5551234567"


class TestConfigPresetConsistency:
    """Verify that presets maintain expected relationships."""

    def test_entry_preset_ordering(self):
        """Conservative should be more selective than aggressive."""
        conservative = EntryTriggerConfig.conservative()
        moderate = EntryTriggerConfig.moderate()
        aggressive = EntryTriggerConfig.aggressive()

        # Higher ratios = more selective = conservative
        assert conservative.up_waves_ratio > moderate.up_waves_ratio
        assert moderate.up_waves_ratio > aggressive.up_waves_ratio

        assert conservative.up_magnitude_ratio > moderate.up_magnitude_ratio
        assert moderate.up_magnitude_ratio > aggressive.up_magnitude_ratio

    def test_exit_preset_ordering(self):
        """Tight stops should exit sooner than loose stops."""
        tight = ExitTriggerConfig.tight_stops()
        balanced = ExitTriggerConfig.balanced()
        loose = ExitTriggerConfig.loose_stops()

        # Higher up_magnitude_ratio = hold longer before exiting
        assert loose.up_magnitude_ratio < balanced.up_magnitude_ratio
        assert balanced.up_magnitude_ratio < tight.up_magnitude_ratio

    def test_risk_preset_ordering(self):
        """Conservative should have lower limits than aggressive."""
        conservative = RiskManagementConfig.conservative()
        default = RiskManagementConfig()
        aggressive = RiskManagementConfig.aggressive()

        assert conservative.maximum_position_loss < default.maximum_position_loss
        assert default.maximum_position_loss < aggressive.maximum_position_loss

        assert conservative.max_trades_per_day < aggressive.max_trades_per_day
        assert conservative.trade_size < aggressive.trade_size


class TestConfigValueRanges:
    """Validate that config values are in sensible ranges."""

    def test_ratio_values_between_0_and_1(self):
        """All ratio parameters should be between 0 and 1."""
        entry = EntryTriggerConfig()
        exit = ExitTriggerConfig()

        assert 0 < entry.up_waves_ratio < 1
        assert 0 < entry.up_magnitude_ratio < 1
        assert 0 < exit.up_magnitude_ratio < 1
        assert 0 < exit.down_wave_length_ratio < 1

    def test_risk_values_positive(self):
        """Risk parameters should be positive."""
        risk = RiskManagementConfig()

        assert risk.maximum_position_loss > 0
        assert risk.max_trades_per_day > 0
        assert risk.trade_size > 0
        assert 0 < risk.discounted_magnitudes_factor < 1

    def test_market_data_timeout_reasonable(self):
        """Timeout should be reasonable (not too short or too long)."""
        config = MarketDataConfig()

        # Should be at least 1 hour, at most 24 hours
        assert 3600 <= config.market_data_timeout <= 86400
