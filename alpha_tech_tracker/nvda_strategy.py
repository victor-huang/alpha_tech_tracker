from alpha_tech_tracker.strategy import SimpleStrategy
from alpha_tech_tracker.portfolio import Portfolio
from alpha_tech_tracker.order_engine import OrderEngine
from alpha_tech_tracker.wave import Wave

class NVDAStrategy(SimpleStrategy):
    def __init__(self, *, symbol='None'):
        # load 300 5-min interval data, so we can generate 200-d
        # moving average lines
        self.symbol = symbol
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
        self.sender_phone_number = '4086130570'
        self.plot_market_data_candle_stick_chart = False

        #  self.market_data_timeout = 300
        self.market_data_timeout = 900 # number of second not receiving 5min agg data
        self.maximum_position_loss = 3000

        self.buy_trigger_up_waves_ratio = 0.4
        self.buy_trigger_up_magnitude_ratio = 0.6
        self.buy_trigger_risk_reward_ratio = 1.5

        self.strong_buy_after_sell_off_up_waves_ratio = 0.5
        self.strong_buy_after_sell_off_up_magnitude_ratio = 0.38

        self.waves_loosing_steam_up_magnitude_ratio = 0.38
        self.waves_loosing_steam_down_wave_length_ratio = 0.38
        self.waves_loosing_steam_down_wave_pickup_steam_up_magnitude_ratio = 0.2

        self.moving_average_periods = [20, 50, 100, 200]
        self.discounted_magnitudues_factor = 0.95
        self.max_trade_per_day = 2

        self.bullish_up_wave_move_size = 100 # 78 is the max wave length
        self.bullish_up_wave_magnitude_ratio = 0.6
        self.bullish_up_waves_ratio = 0.6

        self.signal_trigger_params = {
            'gap_move': {
                'daily_movement_minimum': 0.5 # 50%

            },
            'long_tail_reversal_combo': {
                'daily_movement_minimum': 0.03 / (12 * 8)
            }

        }

    def signal_event_handler(self, signal):
        datetime_hash = signal.signaled_at

        if datetime_hash in self.signals_by_times:
            self.signals_by_times[datetime_hash].append(signal)
        else:
            self.signals_by_times[datetime_hash] = []

        if signal.trend == 'up':
            if self.is_market_open_within(3) and signal.name == 'long_tail_reversal_combo-up_trend':
                print("Skip buy condition check")
                return
            self.check_buy_condition()
        else:
            self.check_sell_condition()

    def upside_potential(self, current_price, waves=[]):
        waves_stats = Wave.waves_stats(waves)
        higest_price = max([ w.high for w in waves[-8:]])

        potential = higest_price - current_price

        return max([potential, 0]) * 1.8 * self.discounted_magnitudues_factor
        #  self.set_trace_at('2019-06-07 09:30:00-0400')
        #  self.set_trace_at('2018-02-20 10:00:00-0500')
        #  self.set_trace_at('2019-12-10 10:35:00-0500')
        #  if waves_stats['up_waves_ratio'] > self.bullish_up_waves_ratio and waves_stats['up_wave_move_length'] >= self.bullish_up_wave_move_size and waves_stats['up_magnitude_ratio'] > self.bullish_up_wave_magnitude_ratio:
            #  # up too much lately, take less risk
            #  return min(upside_magnitudes) * self.discounted_magnitudues_factor
        #  else:
            #  return max(upside_magnitudes) * self.discounted_magnitudues_factor

    def downside_risk(self, current_price, waves=[]):
        waves_stats = Wave.waves_stats(waves)
        lowest_price = min([ w.low for w in waves[-8:]])

        potential = abs(current_price - lowest_price) * 1.3

        return max([potential, 0.01]) * self.discounted_magnitudues_factor

        #  mavg_20_price = self.moving_avgs_df[-1:]['mavg_20'][0]

        #  last_up_wave = None
        #  last_down_wave = None

        #  for w in reversed(waves):
            #  if w.direction() == 'up' and last_up_wave == None:
                #  last_up_wave = w
            #  if w.direction() == 'down' and last_down_wave == None:
                #  last_down_wave = w
            #  if last_up_wave and last_down_wave:
                #  break

        #  if last_up_wave.low < current_price:
            #  last_wave_retrace_price = waves[-1].high - (last_down_wave.high - last_down_wave.low)
        #  else:
            #  last_wave_retrace_point = (last_up_wave.high - last_up_wave.low) * 0.5
            #  last_wave_retrace_price = last_up_wave.low + last_wave_retrace_point

        #  risk_price = last_wave_retrace_price
        #  #  if current_price < last_wave_retrace_price:
            #  #  last_n_price_data_df = self.market_data_df[-10:]
            #  #  risk_price = last_n_price_data_df['close'].min()
        #  #  else:
            #  #  risk_price = last_wave_retrace_price

        #  #  self.set_trace_at('2019-12-18 10:10:00-0500')
        #  if current_price - risk_price == 0:
            #  return 0.01
        #  else:
            #  return (current_price - risk_price) * 1.1

    def check_sell_condition(self):
        current_price = self.market_data_df[-1:]['close'][0]
        current_time_period = self.current_time_period()

        for position_id, targets in self.active_positions.items():
            waves = self.waves_for_last_n_period()
            waves_stats = Wave.waves_stats(waves)

            #  self.set_trace_at('2018-02-14 09:45:00-0500')
            if current_price >= targets['target_price'] or current_price <= targets['cut_loss_price'] or self.is_right_before_market_close() or self.is_maximum_loss_reached(position_id):

                if position_id not in self.active_order_to_position_map.values():
                    # close the position

                    position = self.portfolio.find_position(position_id)
                    open_order = self.order_engine.find_order(position.open_order_id)
                    print('[{}] - Close the position {} at price {}'.format(current_time_period, position_id, current_price))
                    self.send_sms_on_conditions(self.sender_phone_number, '[{}] Close {} at {}'.format(current_time_period, self.symbol, current_price))
                    strike_price = open_order.strike_price
                    option_price = current_price - strike_price
                    order_quantity = 1

                    new_order = self.order_engine.place(symbol=self.symbol, side='sell', asset_type='option',
                            price=option_price, quantity=order_quantity, type='limit', strike_price=strike_price)

                    self.active_order_to_position_map[new_order.id] = position_id
    
