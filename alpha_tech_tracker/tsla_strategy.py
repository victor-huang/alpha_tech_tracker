from datetime import time
from datetime import datetime
from datetime import timezone
from datetime import timedelta
from decimal import Decimal
from contextlib import contextmanager

#  from functools import reduce
import pandas as pd
import pprint as pp

#  import numpy as np
import plotly.graph_objects as go

from alpha_tech_tracker.order_engine import OrderEngine
from alpha_tech_tracker.portfolio import Portfolio
from alpha_tech_tracker.signal import Signal
import alpha_tech_tracker.technical_analysis as ta
import alpha_tech_tracker.alpaca_engine as alpaca

# for running on Mac
# from alpha_tech_tracker.sms import send_sms_via_imessage as send_sms

# use Twillio to send
from alpha_tech_tracker.sms import send_sms

from alpha_tech_tracker.wave import Wave
from alpha_tech_tracker.alpaca_py_engine import DataAggregator
from alpha_tech_tracker.alpaca_py_engine import get_historical_stock_data
from alpha_tech_tracker.strategy_config import StrategyConfig


class Strategy(object):
    """
    Base class for all trading strategies.

    Defines the interface that all strategy implementations must follow.
    Strategies analyze market data, generate trading signals, and execute trades
    through the order engine.

    Key Responsibilities:
        - Market data processing (market_event_handler)
        - Signal generation (signal_event_handler)
        - Position entry/exit decisions (check_open/close_position_condition)
        - Order execution (order_event_handler)
        - Backtesting and simulation (simulate)

    Lifecycle:
        1. Initialize strategy with configuration
        2. Run simulation with historical data OR connect to live feed
        3. Process market events → Generate signals → Execute orders
        4. Manage open positions → Close when conditions met
        5. Track P&L in portfolio

    Subclass Requirements:
        All methods must be implemented by subclasses (currently abstract).
    """

    def __init__(self):
        """Initialize base strategy. Subclasses should override with config."""

    def simulate(self, *, start, end):
        """
        Run strategy simulation over historical data.

        Args:
            start: Start date (YYYY-MM-DD format)
            end: End date (YYYY-MM-DD format)

        Returns:
            Portfolio with P&L results

        Note:
            Subclasses should implement full backtesting logic including:
            - Loading historical market data
            - Processing each bar chronologically
            - Executing virtual trades
            - Computing final P&L
        """

    def check_open_position_condition(self):
        """
        Evaluate whether conditions are met to enter a new position.

        Returns:
            bool: True if should open position, False otherwise

        Note:
            Subclasses implement entry logic based on:
            - Technical indicators (moving averages, momentum)
            - Wave analysis (trend strength)
            - Risk/reward ratios
            - Maximum daily trade limits
        """

    def check_close_position_condition(self):
        """
        Evaluate whether conditions are met to close open positions.

        Returns:
            bool: True if should close positions, False otherwise

        Note:
            Subclasses implement exit logic based on:
            - Profit targets reached
            - Stop-loss triggered
            - Momentum fading ("waves losing steam")
            - Time-based exits
        """

    def close_all_open_positions(self):
        """
        Close all currently open positions immediately.

        Used for:
            - Emergency exits
            - End of day closes
            - Risk management overrides

        Note:
            Subclasses should iterate active_positions and place
            closing orders through order_engine.
        """

    def signal_event_handler(self):
        """
        Handle trading signal events.

        Called when a new trading signal is generated (buy/sell alert).
        Subclasses decide whether to act on the signal based on strategy rules.

        Typical Flow:
            1. Signal generated (e.g., "bullish reversal detected")
            2. This handler evaluates if signal should trigger trade
            3. If yes, place order through order_engine
        """

    def market_event_handler(self):
        """
        Handle market data events (new price bar received).

        Called for each new market data point (e.g., every 5-minute bar).
        This is the main processing loop for real-time trading.

        Typical Flow:
            1. New bar arrives (OHLCV data)
            2. Update technical indicators
            3. Update wave analysis
            4. Check entry/exit conditions
            5. Execute trades if conditions met
        """

    def order_event_handler(self):
        """
        Handle order execution events (fill confirmations).

        Called when orders are filled, partially filled, or rejected.
        Subclasses update portfolio and positions based on order status.

        Typical Flow:
            1. Order filled notification received
            2. Update position in portfolio
            3. Send alerts (SMS, etc.)
            4. Log trade details
        """


# good at up trend, good protection on sharp downtrend
# ok loos on long consolidation e.g (start='2019-08-06', end='2019-09-23')
class SimpleStrategy(Strategy):
    """
    Wave-based momentum trading strategy for options and stocks.

    **Strategy Overview:**
    Identifies price momentum by tracking "waves" (consecutive price movements in the same direction).
    Enters positions when upward momentum is strong and exits when momentum fades.

    **Best Performing Conditions:**
    ✅ Strong uptrends - Captures momentum with good protection
    ✅ Sharp downtrends - Exits quickly to limit losses
    ⚠️  Choppy/sideways markets - May incur small losses from whipsaws

    **Entry Logic (check_open_position_condition):**
    Opens position when ALL conditions met:
        1. **Wave Analysis**: Recent waves show strong upward momentum
           - up_waves_ratio >= threshold (e.g., 40% of waves are up-waves)
           - up_magnitude_ratio >= threshold (e.g., 51% of movement is upward)

        2. **Risk/Reward**: Favorable risk/reward ratio
           - Expected upside / expected downside >= threshold (e.g., 1.3x)

        3. **Risk Management**: Within risk limits
           - Daily trade limit not exceeded (max_trade_per_day)
           - No existing open positions (one position at a time)

    **Exit Logic (check_close_position_condition):**
    Closes position when ANY condition met:
        1. **Waves Losing Steam**: Momentum fading
           - Up-movement drops below threshold (e.g., < 38% upward)
           - Down-waves growing (indicating reversal)

        2. **Stop-Loss**: Maximum loss reached
           - Position loss >= maximum_position_loss (e.g., $800)

        3. **Time-Based**: Data timeout or end of day

    **Wave Analysis:**
    Waves track consecutive price movements:
        - Up-wave: Series of higher highs and higher lows
        - Down-wave: Series of lower highs and lower lows
        - Wave ends when price reverses beyond threshold (Fibonacci 23.6%)

    **Configuration:**
    Strategy behavior controlled by StrategyConfig with groups:
        - Entry triggers: When to buy (wave ratios, risk/reward)
        - Exit triggers: When to sell (momentum loss thresholds)
        - Risk management: Stop-loss, position sizing, trade limits
        - Instrument: Stock vs option, strike selection

    **Example Usage:**
        # Conservative configuration
        config = StrategyConfig.conservative_tsla()
        strategy = SimpleStrategy(config=config, trade_api_client=client)
        strategy.simulate(start="2023-01-01", end="2023-12-31")

        # Review results
        pnl = strategy.portfolio.calculate_pnl()
        print(f"Total P&L: ${pnl['pnl']}")
        print(f"Win rate: {pnl['number_of_profit_positions'] / len(strategy.portfolio.positions)}")

    **Backtesting:**
    Call simulate() with historical date range to backtest performance:
        - use_saved_data=True: Load from local JSON files
        - use_saved_data=False: Fetch from Alpaca API
        - stream_data=True: Simulate real-time bar-by-bar processing

    **Live Trading:**
    Connect to live data feed and API client:
        - DataAggregator streams 5-minute bars
        - market_event_handler processes each bar
        - Orders executed through trade_api_client (ETrade or Alpaca)

    Attributes:
        config (StrategyConfig): Complete strategy configuration
        symbol (str): Stock ticker being traded
        portfolio (Portfolio): Tracks all positions and P&L
        order_engine (OrderEngine): Handles order placement/execution
        waves (list[Wave]): Historical wave analysis
        active_positions (dict): Currently open positions

    Note:
        This strategy was originally designed for TSLA options but works with
        any liquid stock or option. Adjust config for different volatility profiles.
    """

    def __init__(
        self,
        *,
        config=None,
        symbol=None,
        buy_trigger_risk_reward_ratio=None,
        trade_api_client=None,
        skip_place_historical_trades=False,
    ):
        """
        Initialize SimpleStrategy with configuration.

        Args:
            config: StrategyConfig object with all parameters (recommended)
            symbol: Stock symbol (legacy, use config instead)
            buy_trigger_risk_reward_ratio: Risk/reward ratio (legacy, use config instead)
            trade_api_client: Trading API client (ETrade or Alpaca)
            skip_place_historical_trades: Skip order placement during backtesting

        Example:
            # New way (recommended):
            config = StrategyConfig.conservative_tsla()
            strategy = SimpleStrategy(config=config, trade_api_client=client)

            # Old way (backward compatible):
            strategy = SimpleStrategy(symbol="TSLA", trade_api_client=client)
        """
        # Backward compatibility: create config from legacy parameters
        if config is None:
            if symbol is None:
                symbol = "None"
            config = StrategyConfig.default_for_symbol(symbol)
            if buy_trigger_risk_reward_ratio is not None:
                config.entry.risk_reward_ratio = buy_trigger_risk_reward_ratio

        # Store config for reference
        self.config = config

        # Map config to instance variables (for existing code compatibility)
        # Trading Instrument
        self.symbol = config.instrument.symbol
        self.open_side = "buy"
        self.close_side = "sell"
        self.asset_type = config.instrument.asset_type
        self.target_option_strike_price_delta = (
            config.instrument.option_strike_price_delta
        )
        self.target_option_expiry = config.instrument.option_expiry
        self.target_option_type = config.instrument.option_type
        self.target_option_type_code = self.target_option_type[0].upper()
        self.target_strike_price = "0016500"  # TODO: Calculate from strike_price_delta
        self.osi_key = config.instrument.osi_key
        self.option_key = config.instrument.option_key

        # Portfolio and Order Management
        self.signals_by_times = {}
        self.portfolio = Portfolio()
        self.active_positions = {}
        self.pending_positions_data_by_order = {}
        self.active_order_to_position_map = {}

        self.trade_api_client = trade_api_client
        if self.trade_api_client:
            engine = OrderEngine(engine_name="etrade", client=self.trade_api_client)
        else:
            engine = OrderEngine()

        self.order_engine = engine
        self.waves = []
        self.cached_waves_last_wave = {}
        self.open_position_triggers = []
        self.close_position_triggers = [self.is_waves_loosing_steam]
        self.skip_place_historical_trades = skip_place_historical_trades

        # Notification Config
        self.send_to_phone_number = config.notifications.phone_number or "4086130570"
        self.disabled_sending_sms = config.notifications.disabled
        self.only_send_real_time_trade_alert = (
            config.notifications.only_real_time_alerts
        )

        # Market Data Config
        self.plot_market_data_candle_stick_chart = (
            config.market_data.plot_candlestick_chart
        )
        self.market_data_timeout = config.market_data.market_data_timeout
        self.moving_average_periods = config.market_data.moving_average_periods

        # Risk Management Config
        self.maximum_position_loss = config.risk.maximum_position_loss
        self.max_trade_per_day = config.risk.max_trades_per_day
        self.trade_size = config.risk.trade_size
        self.discounted_magnitudues_factor = config.risk.discounted_magnitudes_factor

        # Entry Trigger Config
        self.buy_trigger_up_waves_ratio = config.entry.up_waves_ratio
        self.buy_trigger_up_magnitude_ratio = config.entry.up_magnitude_ratio
        self.buy_trigger_risk_reward_ratio = config.entry.risk_reward_ratio
        self.strong_buy_after_sell_off_up_waves_ratio = (
            config.entry.strong_buy_after_selloff_up_waves_ratio
        )
        self.strong_buy_after_sell_off_up_magnitude_ratio = (
            config.entry.strong_buy_after_selloff_up_magnitude_ratio
        )

        # Exit Trigger Config
        self.waves_loosing_steam_up_magnitude_ratio = config.exit.up_magnitude_ratio
        self.waves_loosing_steam_down_wave_length_ratio = (
            config.exit.down_wave_length_ratio
        )
        self.waves_loosing_steam_down_wave_pickup_steam_up_magnitude_ratio = (
            config.exit.down_wave_pickup_steam_up_magnitude_ratio
        )

        # Advanced Signal Config
        self.bullish_up_wave_move_size = (
            config.advanced_signals.bullish_up_wave_move_size
        )
        self.bullish_up_wave_magnitude_ratio = (
            config.advanced_signals.bullish_up_wave_magnitude_ratio
        )
        self.bullish_up_waves_ratio = config.advanced_signals.bullish_up_waves_ratio
        self.signal_trigger_params = config.advanced_signals.signal_trigger_params

    def prepare_market_data(self):
        #  alpaca.get_historical_ochl_data('AMZN', start_date='2019-11-20', end_date='2019-11-23')
        # it has 4xx data points
        #  df = pd.read_json('./market_data/amzn_5min_sample.json')[:200]
        ipdb.set_trace()
        df = pd.read_json("./market_data/amzn_5min_2019-11-13_2019-11-23.json")
        #  df = alpaca.get_historical_ochl_data(self.symbol, start_date='2019-11-18', end_date='2019-11-23')[:200]

        close_price_df = df[["close"]].copy()
        moving_avgs_df = ta.moving_average_summary(
            self.moving_average_periods, close_price_df
        )
        self.market_data_df = df
        self.moving_avgs_df = moving_avgs_df

    def plot_data(self, df, chart_html_file_name="chart.html"):
        # getting y-axis to work
        # https://github.com/plotly/plotly.py/issues/932
        fig = go.Figure(
            data=[
                go.Candlestick(
                    x=df.index,
                    open=df["open"],
                    high=df["high"],
                    low=df["low"],
                    close=df["close"],
                )
            ],
            layout={"xaxis": {"rangeslider": {"visible": False}}},
        )
        fig.write_html(chart_html_file_name, auto_open=True)

    def set_trace_at(self, stop_at_time_str):
        if self.market_data_df[-1:].index[0] == datetime.strptime(
            stop_at_time_str, "%Y-%m-%d %H:%M:%S%z"
        ):
            ipdb.set_trace()

    def export_data_to_json(self, symbol, date_range=[], start="", end=""):
        for start, end in date_range:
            file_name = "./test_data/{}_{}_{}.json".format(symbol, start, end)
            end_date = datetime.strptime(end, "%Y-%m-%d")
            end_date_str = (end_date + timedelta(days=1)).strftime("%Y-%m-%d")
            print(file_name)
            df = alpaca.get_historical_ochl_data(
                symbol, start_date=start, end_date=end_date_str
            )
            df.to_json(file_name, orient="index")

    def read_data_from_files(self, symbol, date_range=[], start="", end=""):
        # for amazon
        date_range = [
            ["2018-01-01", "2018-03-31"],
            ["2018-04-01", "2018-06-30"],
            ["2018-06-01", "2018-08-31"],
            ["2018-09-01", "2018-12-31"],
            ["2019-01-01", "2019-03-31"],
            ["2019-04-01", "2019-06-30"],
            ["2019-06-01", "2019-08-31"],
            ["2019-09-01", "2019-12-31"],
        ]

        test_data_df_list = []

        for r_start, r_end in date_range:
            file_name = "./test_data/{}_{}_{}.json".format(symbol, r_start, r_end)
            print(file_name)
            df = pd.read_json(file_name, orient="index")
            if df[start:end].empty:
                continue

            test_data_df_list.append(df[start:end])
        # efficient way to constructing df: https://stackoverflow.com/questions/75956209/error-dataframe-object-has-no-attribute-append
        loaded_data_df = pd.concat(test_data_df_list)

        # set to Easten time zone
        loaded_data_df.index = loaded_data_df.index.tz_localize(0).tz_convert(
            "America/New_York"
        )
        return loaded_data_df

    # start='2019-11-13', end='2019-11-16' interestnig
    #  def simulate(self, *, start='2019-11-18', end='2019-11-23'):
    # down trend start='2019-07-22', end='2019-08-03'
    # down trend start='2019-11-08', end='2019-11-20'
    # down trend start='2019-05-23', end='2019-06-04'
    # up trend start='2019-09-30', end='2019-10-18')
    # up trend start='2019-06-03', end='2019-06-12'
    # up trend start='2019-06-28', end='2019-07-11')
    # up trend start='2019-03-08', end='2019-03-22' # highest profits
    # update trend start='2019-03-28', end='2019-04-24'
    # consolidation  start='2019-08-01', end='2019-09-17'
    # long uptrend test start='2019-03-13', end='2019-05-09'
    def simulate(
        self,
        *,
        start="2019-03-13",
        end="2019-05-09",
        use_saved_data=False,
        stream_data=False,
        market_data_file_date_rage=[],
    ):
        self.simulation_mode_on = True

        self.trade_counts_by_date = {}

        # the api need +1 day for end date
        end_date = datetime.strptime(end, "%Y-%m-%d")

        if use_saved_data:
            end_date_str = end_date.strftime("%Y-%m-%d")
            df = self.read_data_from_files(
                self.symbol,
                date_range=market_data_file_date_rage,
                start=start,
                end=end_date_str,
            )
        else:
            end_date_str = (end_date + timedelta(days=1)).strftime("%Y-%m-%d")
            df = get_historical_stock_data(self.symbol, start, end_date_str)

        #  df.to_json('./amzn_2018_01_2018_03.json', orient='table')
        #  self.export_data_to_json('AMZN')

        #  dfr = pd.read_json('./amzn_2018_01_2018_03.json',  orient='table')
        #  df.to_json('./amzn_5min_2019-11-13_2019-11-23')

        preload_data_period = 200
        #  future_market_data_df = df[preload_data_period + 1: preload_data_period + 200]
        future_market_data_df = df[1:]
        close_price_df = df[:preload_data_period][["close"]].copy()
        moving_avgs_df = ta.moving_average_summary(
            self.moving_average_periods, close_price_df
        )
        self.market_data_df = df[:1].copy()
        #  t_time = datetime.strptime('2019-11-22 13:45:00-0500', '%Y-%m-%d %H:%M:%S%z')
        #  self.market_data_df = df[:t_time].copy()
        self.moving_avgs_df = moving_avgs_df

        if self.plot_market_data_candle_stick_chart:
            self.plot_data(
                df,
                chart_html_file_name="{}_chart_{}.html".format(
                    self.symbol, start + "_" + end
                ),
            )  # graph on

        for period_index, (index_timestamp, market_data_row) in enumerate(
            self.market_data_generator(
                future_market_data_df.iterrows(), stream_data=stream_data
            )
        ):
            if self.is_after_hours(index_timestamp):
                continue
            if period_index <= preload_data_period:
                #  print(f"--------{period_index}")
                # preloading data until enough data to caculating moving average
                self.add_data_point_to_wave(index_timestamp, market_data_row)
                self.market_data_df.loc[index_timestamp] = market_data_row
                continue

            #  import ipdb; ipdb.set_trace()
            # generate signals

            print(
                "{}, price: {}, market_data_size: {}".format(
                    index_timestamp, market_data_row["close"], len(self.market_data_df)
                )
            )
            self.market_data_event_handler(index_timestamp, market_data_row)

            signals = self.generate_signals(index_timestamp, market_data_row)

            if signals:
                print([s.__dict__ for s in signals])

            [self.signal_event_handler(s) for s in signals]
            #  # process orders
            #  order_event_handler()
            executed_orders = self.order_engine.execute_orders()

            for order in executed_orders:
                self.order_event_handler(order)

        for p in self.portfolio.positions:
            if p.status == "open":
                p.close_price = Decimal(future_market_data_df[-1:]["close"][0])
                p.status == "closed"

        pln_info = self.portfolio.calculate_pnl()
        pp.pprint(pln_info)
        pnl_buckets = self.portfolio.bucket_positions_pnl_by_time()

        pd.set_option("display.max_rows", None)

        pp.pprint(pnl_buckets["daily"])
        pp.pprint(pnl_buckets["weekly"])
        pp.pprint(pnl_buckets["monthly"])

        pp.pprint(f"number_of_loss_positions: {pln_info['number_of_loss_positions']}")
        pp.pprint(
            f"number_of_profit_positions: {pln_info['number_of_profit_positions']}"
        )
        pp.pprint(f"pnl: {pln_info['pnl']}")

        return pln_info

    def market_data_generator(self, enumerator, stream_data=False):
        for x in enumerator:
            yield (x)

        if stream_data:
            for x in DataAggregator.build_mins_aggregated_data_generator(
                symbol=self.symbol, timeout=self.market_data_timeout
            ):
                yield (x)

    # TODO:
    # wave count accrose days, which should not happen in 5-mins in intervals
    # return: the waves from oldest to latest order
    def waves_anlyasis(
        self, last_n_period=78, df=None
    ):  # 78, 5-mins periods is a trading day, 120 is a bit more than a day and a half
        df = self.market_data_df[-last_n_period:]
        wave = None
        all_waves = []

        for timestamp_index, row in df.iterrows():
            if not wave:
                wave = Wave(timestamp_index, row)
                all_waves.append(wave)
            else:
                new_wave = wave.count(
                    timestamp_index, row, time_increment=timedelta(minutes=5)
                )

                if new_wave:
                    all_waves.append(new_wave)
                    wave = new_wave

        for w in all_waves[-20:]:
            summary = w.summary()
            print(summary)

        return all_waves

    def waves_for_last_n_period(self, n=120):
        all_waves = []
        total_time_period = 0
        last_wave = self.waves[-1]
        key = (last_wave, n)

        # leverage cache to speed things up a bit
        if key not in self.cached_waves_last_wave:
            for w in reversed(self.waves[-20:]):
                summary = w.summary()
                print(summary)
                total_time_period += summary["length"]
                all_waves.append(w)

                if total_time_period >= n:
                    break

            selected_waves_from_old_to_new = all_waves[::-1]
            self.cached_waves_last_wave[key] = selected_waves_from_old_to_new

            return selected_waves_from_old_to_new
        else:
            return self.cached_waves_last_wave[key]

    def add_data_point_to_wave(self, timestamp_index, current_data_row):
        if not self.waves:
            wave = Wave(timestamp_index, current_data_row)
            self.waves.append(wave)
        else:
            new_wave = self.waves[-1].count(
                timestamp_index, current_data_row, time_increment=timedelta(minutes=5)
            )
            if new_wave:
                self.waves.append(new_wave)

    def generate_signals(self, index_timestamp, current_data_row):
        price_data = self.df_to_price_data_array(
            self.get_latest_periods_market_data(index_timestamp, current_data_row, n=2)
        )
        reversal_fns = {
            "long_tail_reversal_combo": ta.long_tail_reversal_combo,
            "engulfing_reversal": ta.engulfing_reversal,
            #  'push_reversal': ta.push_reversal,
            "gap_move": ta.gap_move,
        }

        signals = []

        for name, detection_fn in reversal_fns.items():
            daily_movement_minimum = self.signal_trigger_params[name][
                "daily_movement_minimum"
            ]

            if detection_fn(
                price_data, trend="up", daily_movement_minimum=daily_movement_minimum
            ):
                # name, category, symbol=None, signaled_at=datetime.now()):
                signal_name = name + "-" + "up_trend"
                signals.append(
                    Signal(
                        name=signal_name,
                        category="ta",
                        trend="up",
                        symbol=self.symbol,
                        signaled_at=index_timestamp,
                    )
                )
            if detection_fn(
                price_data, trend="down", daily_movement_minimum=daily_movement_minimum
            ):
                signal_name = name + "-" + "down_trend"
                signals.append(
                    Signal(
                        name=signal_name,
                        category="ta",
                        trend="down",
                        symbol=self.symbol,
                        signaled_at=index_timestamp,
                    )
                )

        return signals

    def get_latest_periods_market_data(self, index_timestamp, current_data_row, n=5):
        total_peridos = len(self.market_data_df)
        last_n_periods_df = self.market_data_df[total_peridos - n :].copy()
        last_n_periods_df.loc[index_timestamp] = current_data_row

        return last_n_periods_df[len(last_n_periods_df) - n :]

    def df_to_price_data_array(self, df):
        return [
            [r["close"], r["open"], r["high"], r["low"]] for index, r in df.iterrows()
        ]

    # return the potential upside target in price
    def upside_potential(self, current_price, waves=[]):
        last_n_price_data_df = self.market_data_df[-20:]
        last_n_price_data_df["close"].max() - current_price

        waves_stats = Wave.waves_stats(waves)
        upside_magnitudes = [
            w.price_range() for w in waves[-5:] if w.direction() == "up"
        ] + [last_n_price_data_df["close"].max() - current_price]

        #  self.set_trace_at('2019-06-07 09:30:00-0400')
        #  self.set_trace_at('2018-02-20 10:00:00-0500')
        #  self.set_trace_at('2019-12-10 10:35:00-0500')
        if (
            waves_stats["up_waves_ratio"] > self.bullish_up_waves_ratio
            and waves_stats["up_wave_move_length"] >= self.bullish_up_wave_move_size
            and waves_stats["up_magnitude_ratio"] > self.bullish_up_wave_magnitude_ratio
        ):
            # up too much lately, take less risk
            return min(upside_magnitudes) * self.discounted_magnitudues_factor
        else:
            return max(upside_magnitudes) * self.discounted_magnitudues_factor

    def downside_risk(self, current_price, waves=[]):
        mavg_20_price = self.moving_avgs_df[-1:]["mavg_20"][0]

        if current_price < mavg_20_price:
            last_n_price_data_df = self.market_data_df[
                -3:
            ]  #  important to review when downside volatility is big
            risk_price = last_n_price_data_df["close"].min()
        else:
            risk_price = mavg_20_price

        if current_price - risk_price == 0:
            return 0.01
        else:
            return (current_price - risk_price) * 1.1

    def risk_reward_ratio(self, current_price, waves=[]):
        return self.upside_potential(current_price, waves=waves) / self.downside_risk(
            current_price, waves=waves
        )

    def has_strong_buy_after_sell_off(self, waves_stats):
        return (
            waves_stats["strong_up_wave_index"] > waves_stats["strong_down_wave_index"]
            and waves_stats["up_waves_ratio"]
            <= self.strong_buy_after_sell_off_up_waves_ratio
            and waves_stats["up_magnitude_ratio"]
            > self.strong_buy_after_sell_off_up_magnitude_ratio
        )

    def should_skip_place_historical_trade(self):
        return (
            datetime.now(timezone.utc) - self.current_time_period()
            > timedelta(minutes=10)
        ) and self.skip_place_historical_trades

    def check_open_position_condition(self):
        current_price = self.market_data_df[-1:]["close"][0]
        waves = self.waves_for_last_n_period()
        waves_stats = Wave.waves_stats(waves)

        print(
            "** Time at: {} , up: {}, down {}, ratio {}".format(
                self.current_time_period().isoformat(),
                self.upside_potential(current_price, waves=waves),
                self.downside_risk(current_price, waves=waves),
                self.risk_reward_ratio(current_price, waves=waves),
            )
        )

        if (
            self.risk_reward_ratio(current_price, waves=waves)
            > self.buy_trigger_risk_reward_ratio
            and not self.active_positions
            and not self.is_close_to_after_hours()
            and not self.is_right_before_market_close()
            and not self.should_skip_place_historical_trade()
        ):
            current_time_period = self.current_time_period()
            current_date = current_time_period.date()

            if current_date not in self.trade_counts_by_date:
                self.trade_counts_by_date[current_date] = 0
            elif self.trade_counts_by_date[current_date] >= self.max_trade_per_day:
                print("Maximum trade per day reached")
                return

            #  self.set_trace_at('2019-06-07 09:30:00-0400')

            #  self.set_trace_at('2019-04-16 09:55:00-0400')

            # current wave_length smaller than average weight lenght * 2
            last_3_waves_directions = [w.direction() for w in waves[-3:]]
            is_likely_at_end_of_a_up_wave = (
                (last_3_waves_directions == ["up", "up", "up"])
                and (waves[-1].length() > waves_stats["average_wave_length"] * 1.3)
                #  or (last_3_waves_directions[-1] == 'up') and (waves[-1].length() > waves_stats['average_wave_length'] * 1.5)
            )

            if (
                (
                    waves_stats["up_waves_ratio"] >= self.buy_trigger_up_waves_ratio
                    and waves_stats["up_magnitude_ratio"]
                    > self.buy_trigger_up_magnitude_ratio
                    and not is_likely_at_end_of_a_up_wave
                )
                or (
                    self.has_strong_buy_after_sell_off(waves_stats)
                    and not is_likely_at_end_of_a_up_wave
                )
                or self.check_all_open_position_triggers(waves=waves)
            ):
                for w in waves:
                    print(w.summary())

                pp.pprint(waves_stats)
                print(
                    f"is_likely_at_end_of_a_up_wave: {is_likely_at_end_of_a_up_wave}, {last_3_waves_directions[-1]}, last wave length: {waves[-1].length()}, avg wave length x2 {waves_stats['average_wave_length'] * 2} "
                )

                # open a new position
                self.open_position(
                    order_quantity=self.trade_size,
                    target_price=self.upside_potential(current_price, waves=waves)
                    + current_price,
                    cut_loss_price=current_price
                    - self.downside_risk(current_price, waves=waves),
                )

    def check_all_open_position_triggers(self, waves=[]):
        return any(fn(waves=waves) for fn in self.open_position_triggers)

    def check_all_close_position_triggers(
        self, *, position_id=None, target={}, waves=[], **kwargs
    ):
        kwargs["position_id"] = position_id
        kwargs["target"] = target
        kwargs["waves"] = waves

        return any(fn(**kwargs) for fn in self.close_position_triggers)

    def is_right_before_market_close(self):
        return self.market_data_df[-1:].index[0].strftime("%H:%M") == "15:55"

    def current_time_period(self):
        return self.market_data_df[-1:].index[0]

    def current_time_period_price(self):
        return self.market_data_df[-1:]["close"][0]

    def current_price(self):
        return Decimal(str(self.market_data_df[-1:]["close"][0]))

    def is_close_to_after_hours(self, current_timestamp=None):
        if not current_timestamp:
            current_time = self.current_time_period().time()
        else:
            current_time = current_timestamp.time()

        return current_time > time(15, 55)

    def is_after_hours(self, current_timestamp=None):
        if not current_timestamp:
            current_time = self.current_time_period()
        else:
            current_time = current_timestamp.time()

        return current_time > time(16, 0) or current_time < time(9, 30)

    def is_market_open_within(self, n_5_min_period):
        delta = n_5_min_period * 5
        current_time = self.current_time_period().time()

        return current_time >= time(9, 30) and current_time <= time(9, 30 + delta)

    def check_close_position_condition(self):
        current_price = self.current_price()
        current_time_period = self.current_time_period()

        for position_id, target in self.active_positions.items():
            waves = self.waves_for_last_n_period()
            waves_stats = Wave.waves_stats(waves)

            #  self.set_trace_at('2018-02-14 09:45:00-0500')
            if (
                current_price >= target["target_price"]
                or current_price <= target["cut_loss_price"]
                or self.is_right_before_market_close()
                or self.is_maximum_loss_reached(position_id)
                or self.check_all_close_position_triggers(
                    position_id=position_id, target=target, waves=waves
                )
            ):
                self.close_position(position_id)

                if (
                    self.is_right_before_market_close()
                    and self.order_engine.engine_name == "etrade"
                ):
                    # TODO: this doesn't cancel all open orders
                    #  self.close_all_open_orders()
                    pass

    def is_maximum_loss_reached(self, position_id):
        position = self.portfolio.find_position(position_id)

        print(
            f"******current loss: {((position.strike_price + position.open_price) - Decimal(self.current_time_period_price())) * 100} , open price: {position.open_price}, current price: {self.current_time_period_price()}"
        )
        # 1000
        # s 900  990
        # ca 120 - 900
        # self.target_option_strike_price_delta
        if (
            (position.strike_price + position.open_price)
            - Decimal(self.current_time_period_price())
        ) * 100 >= self.maximum_position_loss:
            return True

        return False

    def is_waves_loosing_steam(self, position_id=None, waves=[], target={}):
        num_of_waves = 3
        current_price = self.current_time_period_price()
        position_target_data = self.active_positions[position_id]
        last_few_waves = waves[-num_of_waves:]

        if len(last_few_waves) < num_of_waves:
            return None
        else:
            position = self.portfolio.find_position(position_id)
            waves_stats = Wave.waves_stats(last_few_waves)

            #  {'up_waves_ratio': 0.3333333333333333, 'up_magnitude_ratio': 0.1453418167288059, 'number_of_up_waves': 1, 'number_of_down_waves': 2, 'up_wave_move_length': 2, 'down_wave_move_length': 17, 'strong_up_wave_index': -1, 'strong_down_wave_index': -1}

            #  self.set_trace_at('2019-04-16 15:25:00-0400'), sharp sell off case
            is_sharp_sell_off = (
                waves_stats["up_magnitude_ratio"]
                < self.waves_loosing_steam_up_magnitude_ratio
                and waves_stats["down_wave_move_length"]
                / (
                    waves_stats["down_wave_move_length"]
                    + waves_stats["up_wave_move_length"]
                )
                < self.waves_loosing_steam_down_wave_length_ratio
            )

            is_down_wave_pickup_steam = (
                waves_stats["up_wave_move_length"] * 3
                < waves_stats["down_wave_move_length"]
                and waves_stats["up_magnitude_ratio"]
                < self.waves_loosing_steam_down_wave_pickup_steam_up_magnitude_ratio
            )

            #  self.set_trace_at('2019-12-10 10:00:00-0500')

            if (
                last_few_waves[0].start > position.open_at
                and position.open_price > current_price
                or is_down_wave_pickup_steam
            ):
                return True

    def close_all_open_positions(self):
        pass

    def close_all_open_orders(self):
        self.order_engine.close_all_open_orders()

    def signal_event_handler(self, signal):
        datetime_hash = signal.signaled_at

        if datetime_hash in self.signals_by_times:
            self.signals_by_times[datetime_hash].append(signal)
        else:
            self.signals_by_times[datetime_hash] = []

        if signal.trend == "up":
            if (
                self.is_market_open_within(3)
                and signal.name == "long_tail_reversal_combo-up_trend"
            ):
                print("Skip buy condition check")
                return
            self.check_open_position_condition()
        else:
            self.check_close_position_condition()

    def update_market_data_related_stats(self, index_timestamp, market_data_row):
        self.market_data_df.loc[index_timestamp] = market_data_row

        close_price_df = self.market_data_df[["close"]].copy()
        self.moving_avgs_df = ta.moving_average_summary(
            self.moving_average_periods, close_price_df
        )

        self.add_data_point_to_wave(index_timestamp, market_data_row)

    def market_data_event_handler(self, index_timestamp, market_data_row):
        #  print("Market data: {}".format(market_data_row))
        self.update_market_data_related_stats(index_timestamp, market_data_row)

        open_positions = [x for x in self.portfolio.positions if x.status == "open"]
        print(
            "# of active positions: {}, open positions: {}, pending positions {}".format(
                len(self.active_positions),
                len(open_positions),
                len(self.pending_positions_data_by_order),
            )
        )
        self.check_close_position_condition()

    def order_event_handler(self, order):
        if self.active_order_to_position_map[order.id] == None:
            # add position
            if self.simulation_mode_on:
                open_at = self.pending_positions_data_by_order[order.id][
                    "attempt_open_at"
                ]
            else:
                open_at = order.executed_at

            new_position = self.portfolio.add_position(
                symbol=order.symbol,
                open_price=Decimal(round(order.executed_price, 2)),
                type=self.asset_type,
                quantity=order.quantity,
                open_at=open_at,
                open_order_id=order.id,
                osi_key=order.osi_key,
                strike_price=order.strike_price,
            )

            self.pending_positions_data_by_order[order.id]
            self.active_positions[new_position.id] = (
                self.pending_positions_data_by_order[order.id]
            )
            del self.pending_positions_data_by_order[order.id]
            del self.active_order_to_position_map[order.id]
        else:
            # close position
            position_id = self.active_order_to_position_map[order.id]

            if self.simulation_mode_on:
                closed_at = self.current_time_period()
            else:
                closed_at = order.executed_at

            self.portfolio.close_position(
                id=position_id,
                close_price=Decimal(round(order.executed_price, 2)),
                closed_at=closed_at,
                close_order_id=order.id,
            )

            del self.active_order_to_position_map[order.id]
            del self.active_positions[position_id]

    def send_sms_on_conditions(self, phone_number, msg):
        if self.disabled_sending_sms:
            return

        current_time_period = self.current_time_period()
        if self.only_send_real_time_trade_alert:
            if datetime.now(timezone.utc) - timedelta(
                minutes=10
            ) <= current_time_period and current_time_period <= datetime.now(
                timezone.utc
            ) + timedelta(
                minutes=10
            ):
                send_sms(phone_number, msg)

        else:
            send_sms(phone_number, msg)

    def open_position(self, order_quantity=1, target_price=None, cut_loss_price=None):
        current_price = self.current_price()

        if self.target_option_type == "call":
            strike_price = current_price - self.target_option_strike_price_delta
            option_price = current_price - strike_price

            # TODO: need to check
            #  option_price = current_price

        else:
            strike_price = current_price + self.target_option_strike_price_delta
            option_price = strike_price - current_price

            # TODO: need to check
            #  option_price = current_price

        new_order = self.order_engine.place(
            symbol=self.symbol,
            side=self.open_side,
            asset_type=self.asset_type,
            price=Decimal(str(option_price)),
            quantity=order_quantity,
            type="smart_market",
            strike_price=Decimal(str(strike_price)),
            osi_key=self.osi_key,
            option_key=self.option_key,
        )

        current_time_period = self.current_time_period()

        self.pending_positions_data_by_order[new_order.id] = {
            "target_price": target_price,
            "cut_loss_price": cut_loss_price,
            "attempt_open_at": current_time_period,
        }

        self.active_order_to_position_map[new_order.id] = None
        print(
            "[{}] - Open {} position at stock price {}, target price: {}, cut loss at: {}".format(
                current_time_period,
                self.target_option_type,
                current_price,
                self.pending_positions_data_by_order[new_order.id]["target_price"],
                self.pending_positions_data_by_order[new_order.id]["cut_loss_price"],
            )
        )

        self.send_sms_on_conditions(
            self.send_to_phone_number,
            "[{}] Open {} {} at {}".format(
                current_time_period, self.target_option_type, self.symbol, current_price
            ),
        )

        current_date = current_time_period.date()
        self.trade_counts_by_date[current_date] += 1

    def close_position(self, position_id):
        if position_id in self.active_order_to_position_map.values():
            return

        current_price = self.current_price()
        current_time_period = self.current_time_period()
        position = self.portfolio.find_position(position_id)
        open_order = self.order_engine.find_order(position.open_order_id)

        print(
            "[{}] - Close the {} position {} at stock price {}".format(
                current_time_period,
                open_order.option_type(),
                position_id,
                current_price,
            )
        )

        self.send_sms_on_conditions(
            self.send_to_phone_number,
            "[{}] Close {} {} at {}".format(
                current_time_period,
                open_order.option_type(),
                self.symbol,
                current_price,
            ),
        )
        strike_price = open_order.strike_price

        if open_order.option_type() == "call":
            option_price = current_price - strike_price
        else:
            option_price = strike_price - current_price

        order_quantity = self.trade_size

        new_order = self.order_engine.place(
            symbol=self.symbol,
            side="sell",
            asset_type=self.asset_type,
            price=option_price,
            quantity=order_quantity,
            type="smart_market",
            strike_price=strike_price,
            osi_key=self.osi_key,
            option_key=self.option_key,
            #  option_key='2023-10-27 s230',
        )

        self.active_order_to_position_map[new_order.id] = position_id

    def buy_sell_trigger_condition_components(self, targets=[], waves=[]):
        pass

        # return true/false
        open_position_triggers = [func1, func2, func3]

        close_position_triggers = [func1, func2]

    @classmethod
    @contextmanager
    def optimize_params(cls, symbol, params={}):
        """
        TODO: need to figurt out the list of params we can set and how to control the index enumeration
        example usage:
            with SimpleStrategy.optimize_params(symbol='TSLA') as (strategy, params, pnl_data_collector):
                result = strategy.simulate(start='2023-8-18', end='2023-9-21', use_saved_data=False, stream_data=False)
                pnl_data_collector.append(result)
        """
        pnl_data_per_params = []

        for index in range(0, 1):
            buy_trigger_risk_reward_ratio = 0.8 + index / 10.0
            params = {"buy_trigger_risk_reward_ratio": 1.3}

            strategy = cls(
                symbol=symbol,
                buy_trigger_risk_reward_ratio=buy_trigger_risk_reward_ratio,
            )

            pnl_data_collector = []
            yield (strategy, params, pnl_data_collector)

            pnl_data_per_params.append(
                {
                    "param_id": str(params),
                    "pnl_data": pnl_data_collector[
                        0
                    ],  # assumed only have one pnl data point
                }
            )

        max_attr = max(pnl_data_per_params, key=lambda x: x["pnl_data"]["pnl"])
        print(max_attr)
