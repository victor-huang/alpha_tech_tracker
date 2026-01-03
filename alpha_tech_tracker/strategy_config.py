"""
Strategy Configuration Classes

This module provides structured configuration objects for trading strategies,
making parameters more discoverable and maintainable.

Example Usage:
    # Create custom config
    entry_config = EntryTriggerConfig(
        up_waves_ratio=0.45,
        up_magnitude_ratio=0.55
    )

    # Use in strategy
    strategy = SimpleStrategy(
        symbol="TSLA",
        entry_config=entry_config
    )

    # Or use presets
    strategy = SimpleStrategy(
        symbol="TSLA",
        entry_config=EntryTriggerConfig.conservative()
    )
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class TradingInstrumentConfig:
    """
    Configuration for the trading instrument (stock or option).

    Attributes:
        symbol: Stock ticker symbol (e.g., "TSLA", "AMZN")
        asset_type: Type of asset to trade ("stock" or "option")
        option_strike_price_delta: How deep in-the-money for options (dollars above current price)
        option_expiry: Option expiration date in YYMMDD format (e.g., "240614" for June 14, 2024)
        option_type: Option type ("call" or "put")
        option_key: Alpaca-style option key (e.g., "2024-06-14 s165")

    Note:
        For options, strike_price_delta of 20-30 provides good leverage with lower risk.
        Weekly/monthly expirations provide different risk/reward profiles.
    """
    symbol: str
    asset_type: str = "option"  # "stock" or "option"
    option_strike_price_delta: int = 30  # dollars deep in the money
    option_expiry: str = "240614"  # YYMMDD format
    option_type: str = "call"  # "call" or "put"
    option_key: str = "2024-06-14 s165"  # Alpaca format

    @property
    def osi_key(self) -> str:
        """Generate OCC (Options Clearing Corporation) symbol for ETrade."""
        option_type_code = self.option_type[0].upper()
        # OSI format: SYMBOL--YYMMDDCPPPPPPPPP
        # Example: TSLA--240614C00165000
        target_strike_price = "0016500"  # This should be calculated from actual strike
        return f"{self.symbol}--{self.option_expiry}{option_type_code}{target_strike_price}"


@dataclass
class EntryTriggerConfig:
    """
    Configuration for entry (buy) signals based on wave analysis.

    Wave analysis identifies price momentum by tracking consecutive higher/lower moves.
    These ratios determine when momentum is strong enough to enter a position.

    Attributes:
        up_waves_ratio: Minimum ratio of up-waves to total waves (0.0-1.0)
            - Higher = more selective, requires stronger uptrend
            - Typical range: 0.3-0.5
            - Example: 0.4 means 40% of recent waves must be up-waves

        up_magnitude_ratio: Minimum ratio of up-movement to total movement (0.0-1.0)
            - Measures strength of price increases vs decreases
            - Typical range: 0.5-0.65
            - Example: 0.51 means upward moves must be 51% of total price movement

        risk_reward_ratio: Minimum risk/reward ratio to enter trade
            - Higher = more selective entries
            - Typical range: 1.0-2.0
            - Example: 1.3 means expected profit must be 1.3x the risk

        strong_buy_after_selloff_up_waves_ratio: Wave ratio for aggressive entry after pullback
        strong_buy_after_selloff_up_magnitude_ratio: Magnitude ratio for aggressive entry

    Presets:
        - conservative(): Higher thresholds, fewer trades, lower risk
        - moderate(): Balanced approach (default)
        - aggressive(): Lower thresholds, more trades, higher risk
    """
    up_waves_ratio: float = 0.4
    up_magnitude_ratio: float = 0.51
    risk_reward_ratio: float = 1.3
    strong_buy_after_selloff_up_waves_ratio: float = 0.5
    strong_buy_after_selloff_up_magnitude_ratio: float = 0.38

    @classmethod
    def conservative(cls):
        """Conservative entry: higher thresholds, fewer but higher-quality trades."""
        return cls(
            up_waves_ratio=0.5,
            up_magnitude_ratio=0.6,
            risk_reward_ratio=1.5
        )

    @classmethod
    def moderate(cls):
        """Moderate entry: balanced approach (default settings)."""
        return cls()

    @classmethod
    def aggressive(cls):
        """Aggressive entry: lower thresholds, more frequent trades."""
        return cls(
            up_waves_ratio=0.35,
            up_magnitude_ratio=0.48,
            risk_reward_ratio=1.1
        )


@dataclass
class ExitTriggerConfig:
    """
    Configuration for exit (sell) signals based on momentum loss.

    "Waves losing steam" detection identifies when upward momentum is fading,
    signaling it's time to take profits or cut losses.

    Attributes:
        up_magnitude_ratio: Maximum acceptable up-magnitude before considering exit
            - Lower = exit sooner when momentum weakens
            - Typical range: 0.3-0.45
            - Example: 0.38 means exit if up-moves drop below 38% of total movement

        down_wave_length_ratio: Maximum acceptable down-wave length relative to wave cycle
            - Prevents holding during prolonged downturns
            - Typical range: 0.3-0.5
            - Example: 0.38 means exit if down-waves exceed 38% of typical wave length

        down_wave_pickup_steam_up_magnitude_ratio: Threshold for detecting reversal recovery
            - Allows brief pullbacks without triggering exit
            - Typical range: 0.15-0.25
            - Example: 0.2 means don't exit if up-movement recovers above 20%

    Presets:
        - tight_stops(): Exit quickly when momentum weakens
        - balanced(): Moderate stop-loss approach (default)
        - loose_stops(): Ride out volatility, exit on major reversals only
    """
    up_magnitude_ratio: float = 0.38
    down_wave_length_ratio: float = 0.38
    down_wave_pickup_steam_up_magnitude_ratio: float = 0.2

    @classmethod
    def tight_stops(cls):
        """Exit quickly when momentum weakens - good for volatile markets."""
        return cls(
            up_magnitude_ratio=0.45,
            down_wave_length_ratio=0.3,
            down_wave_pickup_steam_up_magnitude_ratio=0.15
        )

    @classmethod
    def balanced(cls):
        """Balanced exit approach (default settings)."""
        return cls()

    @classmethod
    def loose_stops(cls):
        """Ride out volatility - good for strong trends."""
        return cls(
            up_magnitude_ratio=0.3,
            down_wave_length_ratio=0.5,
            down_wave_pickup_steam_up_magnitude_ratio=0.25
        )


@dataclass
class RiskManagementConfig:
    """
    Risk management parameters to limit losses and control position sizing.

    Attributes:
        maximum_position_loss: Stop-loss threshold in dollars
            - Automatically closes position if loss exceeds this amount
            - Typical range: $500-$2000 depending on account size
            - Example: 800 means close position if down $800

        max_trades_per_day: Maximum number of trades allowed per day
            - Prevents overtrading and excessive commissions
            - Typical range: 1-5 trades
            - Example: 2 means max 2 position entries per day

        trade_size: Number of contracts/shares per trade
            - Determines position sizing
            - Example: 2 means buy 2 option contracts or 2 shares

        discounted_magnitudes_factor: Risk adjustment factor for volatility
            - Lower = more conservative in volatile markets
            - Typical range: 0.7-0.9
            - Example: 0.8 means discount expected moves by 20%
    """
    maximum_position_loss: float = 800.0  # dollars
    max_trades_per_day: int = 2
    trade_size: int = 2  # contracts or shares
    discounted_magnitudes_factor: float = 0.80

    @classmethod
    def conservative(cls):
        """Conservative risk: tight stops, smaller positions."""
        return cls(
            maximum_position_loss=500.0,
            max_trades_per_day=1,
            trade_size=1,
            discounted_magnitudes_factor=0.7
        )

    @classmethod
    def aggressive(cls):
        """Aggressive risk: wider stops, larger positions."""
        return cls(
            maximum_position_loss=1500.0,
            max_trades_per_day=5,
            trade_size=3,
            discounted_magnitudes_factor=0.85
        )


@dataclass
class MarketDataConfig:
    """
    Market data processing and technical analysis configuration.

    Attributes:
        moving_average_periods: List of moving average periods for trend analysis
            - Standard periods: [20, 50, 100, 200] days
            - Used to identify support/resistance and trend strength

        market_data_timeout: Seconds to wait before assuming data feed is stale
            - Prevents trading on outdated data
            - Default: 7 hours (25200 seconds)
            - Trading halts if no data received within this window

        plot_candlestick_chart: Whether to generate candlestick charts
            - Useful for visual backtesting analysis
            - Set to False for production to save resources
    """
    moving_average_periods: List[int] = field(default_factory=lambda: [20, 50, 100, 200])
    market_data_timeout: int = 3600 * 7  # 7 hours in seconds
    plot_candlestick_chart: bool = False


@dataclass
class NotificationConfig:
    """
    Configuration for SMS and alert notifications.

    Attributes:
        phone_number: Phone number to receive trade alerts (format: "4086130570")
        disabled: If True, no SMS notifications will be sent
        only_real_time_alerts: If True, only send alerts for live trades (not backtests)

    Note:
        Requires Twilio configuration (see sms.py for setup)
    """
    phone_number: Optional[str] = None
    disabled: bool = False
    only_real_time_alerts: bool = True


@dataclass
class AdvancedSignalConfig:
    """
    Advanced signal detection parameters for specialized patterns.

    These parameters configure detection of specific technical patterns like
    gap moves, engulfing candles, and long-tail reversals.

    Attributes:
        bullish_up_wave_move_size: Minimum wave length for bullish signal
            - Measured in 5-minute intervals
            - Max wave length is 78 (full trading day)
            - Example: 50 means wave must span 50+ intervals

        bullish_up_wave_magnitude_ratio: Required upward momentum for bullish signal
        bullish_up_waves_ratio: Required proportion of up-waves for bullish signal

        signal_trigger_params: Dictionary of pattern-specific thresholds
            - gap_move: Large overnight gaps
            - long_tail_reversal_combo: Reversal candle patterns
            - engulfing_reversal: Engulfing candle patterns
    """
    bullish_up_wave_move_size: int = 50
    bullish_up_wave_magnitude_ratio: float = 0.51
    bullish_up_waves_ratio: float = 0.51
    signal_trigger_params: Dict[str, Dict[str, float]] = field(default_factory=lambda: {
        "gap_move": {"daily_movement_minimum": 0.5},  # 50% gap
        "long_tail_reversal_combo": {"daily_movement_minimum": 0.01 / (12 * 4)},
        "engulfing_reversal": {"daily_movement_minimum": 0.01 / (12 * 4)},
    })


@dataclass
class StrategyConfig:
    """
    Complete strategy configuration combining all parameter groups.

    This is the master config object that bundles all configuration categories.
    Use this for a fully configured strategy with clear parameter organization.

    Example:
        # Use defaults with overrides
        config = StrategyConfig(
            instrument=TradingInstrumentConfig(symbol="TSLA"),
            entry=EntryTriggerConfig.conservative(),
            risk=RiskManagementConfig.conservative()
        )

        # Or build from scratch
        config = StrategyConfig(
            instrument=TradingInstrumentConfig(
                symbol="AAPL",
                asset_type="stock"
            ),
            entry=EntryTriggerConfig(up_waves_ratio=0.45),
            exit=ExitTriggerConfig.tight_stops(),
            risk=RiskManagementConfig(maximum_position_loss=1000)
        )
    """
    instrument: TradingInstrumentConfig
    entry: EntryTriggerConfig = field(default_factory=EntryTriggerConfig)
    exit: ExitTriggerConfig = field(default_factory=ExitTriggerConfig)
    risk: RiskManagementConfig = field(default_factory=RiskManagementConfig)
    market_data: MarketDataConfig = field(default_factory=MarketDataConfig)
    notifications: NotificationConfig = field(default_factory=NotificationConfig)
    advanced_signals: AdvancedSignalConfig = field(default_factory=AdvancedSignalConfig)

    @classmethod
    def default_for_symbol(cls, symbol: str):
        """Create default configuration for a given symbol."""
        return cls(
            instrument=TradingInstrumentConfig(symbol=symbol)
        )

    @classmethod
    def conservative_tsla(cls):
        """Conservative TSLA trading configuration."""
        return cls(
            instrument=TradingInstrumentConfig(symbol="TSLA"),
            entry=EntryTriggerConfig.conservative(),
            exit=ExitTriggerConfig.tight_stops(),
            risk=RiskManagementConfig.conservative()
        )

    @classmethod
    def aggressive_tsla(cls):
        """Aggressive TSLA trading configuration."""
        return cls(
            instrument=TradingInstrumentConfig(symbol="TSLA"),
            entry=EntryTriggerConfig.aggressive(),
            exit=ExitTriggerConfig.loose_stops(),
            risk=RiskManagementConfig.aggressive()
        )
