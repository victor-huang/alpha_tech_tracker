# Strategy Configuration Guide

**Created:** 2026-01-03
**Phase:** 2.1 - Strategy Config Dataclasses

---

## Overview

The new `strategy_config.py` module provides structured, self-documenting configuration classes that replace the confusing initialization parameters in `SimpleStrategy`.

**Problem Solved:** Previously, `SimpleStrategy.__init__` had 40+ parameters scattered throughout the code with unclear purposes and relationships.

**Solution:** Organized configs into 7 logical groups with presets, docstrings, and sensible defaults.

---

## Configuration Groups

### 1. TradingInstrumentConfig
**What it controls:** The asset you're trading

```python
from alpha_tech_tracker.strategy_config import TradingInstrumentConfig

# Stock trading
stock_config = TradingInstrumentConfig(
    symbol="AAPL",
    asset_type="stock"
)

# Option trading
option_config = TradingInstrumentConfig(
    symbol="TSLA",
    asset_type="option",
    option_strike_price_delta=30,  # $30 in-the-money
    option_expiry="240614",         # June 14, 2024
    option_type="call"
)
```

**Key Parameters:**
- `option_strike_price_delta`: How deep in-the-money (20-40 typical)
- Smaller delta = less leverage, lower risk
- Larger delta = more leverage, higher risk

---

### 2. EntryTriggerConfig
**What it controls:** When to buy (enter positions)

```python
from alpha_tech_tracker.strategy_config import EntryTriggerConfig

# Use a preset
conservative_entry = EntryTriggerConfig.conservative()  # Fewer, higher-quality trades
aggressive_entry = EntryTriggerConfig.aggressive()     # More frequent trades

# Or customize
custom_entry = EntryTriggerConfig(
    up_waves_ratio=0.45,        # 45% of waves must be up-waves
    up_magnitude_ratio=0.55,    # 55% of price movement must be upward
    risk_reward_ratio=1.5       # Expected profit must be 1.5x the risk
)
```

**Key Parameters:**
- `up_waves_ratio`: Proportion of up-waves (0.3-0.5 typical)
  - 0.4 = 40% of recent waves must show upward momentum
  - Higher = more selective, waits for stronger trends

- `up_magnitude_ratio`: Strength of upward movement (0.48-0.65 typical)
  - 0.51 = upward price moves must be 51% of total movement
  - Higher = requires stronger momentum

- `risk_reward_ratio`: Minimum profit potential vs risk (1.0-2.0 typical)
  - 1.3 = expected profit must be 1.3x the potential loss
  - Higher = more selective entries

**Presets:**
- `conservative()`: 0.5 waves, 0.6 magnitude, 1.5 risk/reward
- `moderate()`: 0.4 waves, 0.51 magnitude, 1.3 risk/reward (default)
- `aggressive()`: 0.35 waves, 0.48 magnitude, 1.1 risk/reward

---

### 3. ExitTriggerConfig
**What it controls:** When to sell (exit positions)

```python
from alpha_tech_tracker.strategy_config import ExitTriggerConfig

# Use a preset
tight_stops = ExitTriggerConfig.tight_stops()      # Exit quickly
balanced = ExitTriggerConfig.balanced()            # Default
loose_stops = ExitTriggerConfig.loose_stops()      # Ride volatility

# Or customize
custom_exit = ExitTriggerConfig(
    up_magnitude_ratio=0.40,           # Exit if up-moves drop below 40%
    down_wave_length_ratio=0.35,       # Exit if down-waves exceed 35% of cycle
    down_wave_pickup_steam_up_magnitude_ratio=0.2  # Don't exit if recovery above 20%
)
```

**Key Parameters:**
- `up_magnitude_ratio`: Exit threshold for weakening momentum (0.3-0.45)
  - 0.38 = exit if upward movement drops below 38% of total
  - Lower = hold longer, higher = exit sooner

- `down_wave_length_ratio`: Max acceptable down-wave duration (0.3-0.5)
  - 0.38 = exit if down-waves span >38% of typical wave cycle
  - Prevents holding during prolonged downturns

- `down_wave_pickup_steam_up_magnitude_ratio`: Recovery threshold (0.15-0.25)
  - 0.2 = don't exit if up-movement recovers above 20%
  - Allows brief pullbacks without triggering exits

**Presets:**
- `tight_stops()`: Exit fast (good for volatile markets)
- `balanced()`: Moderate exits (default)
- `loose_stops()`: Ride trends (good for strong uptrends)

---

### 4. RiskManagementConfig
**What it controls:** Position sizing and loss limits

```python
from alpha_tech_tracker.strategy_config import RiskManagementConfig

# Use a preset
conservative_risk = RiskManagementConfig.conservative()
aggressive_risk = RiskManagementConfig.aggressive()

# Or customize
custom_risk = RiskManagementConfig(
    maximum_position_loss=1000.0,  # Stop out at -$1000
    max_trades_per_day=3,          # Max 3 entries per day
    trade_size=2                   # 2 contracts/shares per trade
)
```

**Key Parameters:**
- `maximum_position_loss`: Hard stop-loss in dollars ($500-$2000 typical)
  - Position automatically closed if loss exceeds this
  - Should be 1-2% of account size

- `max_trades_per_day`: Prevents overtrading (1-5 typical)
  - Limits commission costs and emotional trading

- `trade_size`: Contracts or shares per trade (1-5 typical)
  - Smaller = less risk, larger = more risk

**Presets:**
- `conservative()`: $500 max loss, 1 trade/day, size 1
- Default: $800 max loss, 2 trades/day, size 2
- `aggressive()`: $1500 max loss, 5 trades/day, size 3

---

### 5. MarketDataConfig
**What it controls:** Technical indicators and data processing

```python
from alpha_tech_tracker.strategy_config import MarketDataConfig

config = MarketDataConfig(
    moving_average_periods=[20, 50, 100, 200],  # Standard MA periods
    market_data_timeout=3600 * 7,               # 7-hour timeout
    plot_candlestick_chart=False                # No charts in production
)
```

**Key Parameters:**
- `moving_average_periods`: MA periods for trend analysis
  - Standard: [20, 50, 100, 200] days
  - Used to identify support/resistance levels

- `market_data_timeout`: Stale data threshold (seconds)
  - 7 hours = 25200 seconds (default)
  - Prevents trading on outdated data

---

### 6. NotificationConfig
**What it controls:** SMS/email alerts

```python
from alpha_tech_tracker.strategy_config import NotificationConfig

config = NotificationConfig(
    phone_number="4086130570",
    disabled=False,              # Enable SMS
    only_real_time_alerts=True   # No backtest alerts
)
```

**Key Parameters:**
- `phone_number`: Where to send alerts
- `disabled`: Turn off all notifications
- `only_real_time_alerts`: Only alert for live trades (not backtests)

---

### 7. AdvancedSignalConfig
**What it controls:** Advanced pattern detection

```python
from alpha_tech_tracker.strategy_config import AdvancedSignalConfig

config = AdvancedSignalConfig(
    bullish_up_wave_move_size=50,  # Wave must span 50+ intervals
    bullish_up_wave_magnitude_ratio=0.51,
    bullish_up_waves_ratio=0.51
)
```

**Note:** These are advanced parameters for specific pattern detection. Most users can use defaults.

---

## Complete Strategy Configuration

### Option 1: Use Master Config with Presets

```python
from alpha_tech_tracker.strategy_config import StrategyConfig

# Conservative TSLA trading
config = StrategyConfig.conservative_tsla()

# Aggressive TSLA trading
config = StrategyConfig.aggressive_tsla()

# Default for any symbol
config = StrategyConfig.default_for_symbol("AAPL")
```

### Option 2: Mix Presets with Custom Settings

```python
from alpha_tech_tracker.strategy_config import (
    StrategyConfig,
    TradingInstrumentConfig,
    EntryTriggerConfig,
    ExitTriggerConfig,
    RiskManagementConfig
)

config = StrategyConfig(
    instrument=TradingInstrumentConfig(symbol="AMZN"),
    entry=EntryTriggerConfig.conservative(),      # Preset
    exit=ExitTriggerConfig.balanced(),            # Preset
    risk=RiskManagementConfig(                    # Custom
        maximum_position_loss=1200.0,
        max_trades_per_day=2
    )
)
```

### Option 3: Fully Custom Configuration

```python
config = StrategyConfig(
    instrument=TradingInstrumentConfig(
        symbol="NVDA",
        asset_type="option",
        option_strike_price_delta=25
    ),
    entry=EntryTriggerConfig(
        up_waves_ratio=0.42,
        up_magnitude_ratio=0.53,
        risk_reward_ratio=1.4
    ),
    exit=ExitTriggerConfig(
        up_magnitude_ratio=0.40,
        down_wave_length_ratio=0.36
    ),
    risk=RiskManagementConfig(
        maximum_position_loss=900.0,
        max_trades_per_day=3,
        trade_size=2
    )
)
```

---

## Using Configs in Strategy (Phase 2.2)

**Next phase will refactor SimpleStrategy to accept these configs:**

```python
# Future usage (after Phase 2.2)
from alpha_tech_tracker.tsla_strategy import SimpleStrategy
from alpha_tech_tracker.strategy_config import StrategyConfig

config = StrategyConfig.conservative_tsla()
strategy = SimpleStrategy(config=config, trade_api_client=client)
strategy.simulate(start="2023-01-01", end="2023-12-31")
```

---

## Benefits of New Config System

✅ **Self-Documenting**: Each parameter has clear docstrings explaining purpose and typical ranges

✅ **Organized**: Related parameters grouped logically (entry vs exit vs risk)

✅ **Discoverable**: IDE autocomplete shows all available parameters

✅ **Type-Safe**: Dataclasses provide type hints for better tooling

✅ **Presets**: Common configurations (conservative, aggressive) built-in

✅ **Testable**: Easy to create config objects for testing different strategies

✅ **Maintainable**: Changes to config structure are centralized

---

## Parameter Tuning Quick Reference

### For Volatile Stocks (TSLA, NVDA)
```python
entry=EntryTriggerConfig.conservative(),  # Wait for clear signals
exit=ExitTriggerConfig.tight_stops(),     # Exit quickly
risk=RiskManagementConfig.conservative()  # Tight stops
```

### For Stable Stocks (AAPL, MSFT)
```python
entry=EntryTriggerConfig.moderate(),
exit=ExitTriggerConfig.balanced(),
risk=RiskManagementConfig(maximum_position_loss=1000)
```

### For Strong Uptrends
```python
entry=EntryTriggerConfig.aggressive(),     # More entries
exit=ExitTriggerConfig.loose_stops(),      # Ride the trend
risk=RiskManagementConfig.aggressive()     # Larger positions
```

### For Choppy/Sideways Markets
```python
entry=EntryTriggerConfig.conservative(),   # Very selective
exit=ExitTriggerConfig.tight_stops(),      # Quick exits
risk=RiskManagementConfig.conservative()   # Small positions
```

---

## Migration Notes

**Phase 2.2 will:**
1. Refactor `SimpleStrategy.__init__` to accept `StrategyConfig`
2. Map config fields to existing internal variables
3. Maintain backward compatibility (optional)
4. Update all tests to use new config system

**Phase 2.3 will:**
1. Add comprehensive docstrings to Strategy classes
2. Document trigger condition logic
3. Create decision flow diagrams

---

## Next Steps

- [ ] Phase 2.2: Refactor SimpleStrategy to use these configs
- [ ] Phase 2.3: Add docstrings to Strategy classes
- [ ] Phase 3: Write tests for config validation
- [ ] Update CLAUDE.md with config usage examples

---

## Questions?

The config system is designed to be intuitive, but if you have questions:
- Each dataclass has detailed docstrings
- Presets provide good starting points
- Parameter ranges are documented in attribute descriptions
- Examples show common usage patterns
