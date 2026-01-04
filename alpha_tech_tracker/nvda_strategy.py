from alpha_tech_tracker.strategy import SimpleStrategy
from alpha_tech_tracker.portfolio import Portfolio
from alpha_tech_tracker.order_engine import OrderEngine
from alpha_tech_tracker.wave import Wave


class NVDAStrategy(SimpleStrategy):
    def __init__(self, *, symbol="None"):
        super().__init__(symbol=symbol)  # set the defaults

        # load 300 5-min interval data, so we can generate 200-d
        # moving average lines
        self.symbol = symbol
        self.open_side = "buy"
        self.close_side = "sell"
        self.asset_type = "option"
        self.target_option_expiry = "Weekly_2020"
        self.target_option_type = "put"
        self.osi_key = "{}-{}-{}".format(
            self.symbol, self.target_option_expiry, self.target_option_type
        )

        self.target_option_strike_price_delta = 20  # amount deep in the money

        self.signals_by_times = {}
        self.portfolio = Portfolio()
        self.active_positions = {}
        self.pending_positions_data_by_order = {}
        self.active_order_to_position_map = {}
        self.order_engine = OrderEngine()
        self.waves = []
        self.cached_waves_last_wave = {}
        self.disabled_sending_sms = False
        self.only_send_real_time_trade_alert = True
        self.sender_phone_number = "4086130570"
        self.plot_market_data_candle_stick_chart = False
        self.open_position_triggers = []
        self.close_position_triggers = []

        self.market_data_timeout = 900  # number of second not receiving 5min agg data
        self.maximum_position_loss = 3000

        self.buy_trigger_up_waves_ratio = 0.3
        self.buy_trigger_up_magnitude_ratio = 0.65
        self.buy_trigger_risk_reward_ratio = 1

        self.strong_buy_after_sell_off_up_magnitude_ratio = 0.52

        self.moving_average_periods = [20, 50, 100, 200]
        self.discounted_magnitudues_factor = 1.95
        self.max_trade_per_day = 2

        self.bullish_up_wave_move_size = 50  # 78 is the max wave length
        self.bullish_up_wave_magnitude_ratio = 0.6
        self.bullish_up_waves_ratio = 0.6

        self.signal_trigger_params = {
            "gap_move": {"daily_movement_minimum": 0.5},  # 50%
            "engulfing_reversal": {"daily_movement_minimum": None},
            "long_tail_reversal_combo": {"daily_movement_minimum": 0.03 / (12 * 8)},
        }

    def has_strong_buy_after_sell_off(self, waves_stats):
        return (
            waves_stats["up_magnitude_ratio"]
            > self.strong_buy_after_sell_off_up_magnitude_ratio
        )

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

    def upside_potential(self, current_price, waves=[]):
        waves_stats = Wave.waves_stats(waves)
        higest_price = max([w.high for w in waves[-8:]])

        potential = higest_price - current_price

        return max([potential, 0]) * 1.8 * self.discounted_magnitudues_factor

    def downside_risk(self, current_price, waves=[]):
        waves_stats = Wave.waves_stats(waves)
        lowest_price = min([w.low for w in waves[-8:]])

        potential = abs(current_price - lowest_price) * 1.3

        return max([potential, 0.01]) * self.discounted_magnitudues_factor
