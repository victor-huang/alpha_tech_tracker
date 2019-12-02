import datetime
import pandas as pd
from pandas import Series

import ipdb

class Wave:
    def __init__(self, start, price_data_dict):
        self.start = start
        self.high = price_data_dict['high']
        self.low = price_data_dict['low']
        self.num_high = 1
        self.num_low = 1
        self.high_date = start
        self.low_date = start
        self.df = pd.DataFrame([price_data_dict], index=[start])
        self.end = None
        self.next_wave = None
        self.maximum_wave_length = 78 # a trading day has 78 5 mins intervals
        self.minimum_wave_length = 7
        self.minimum_wave_price_change = 0.03 / (12 * 8)# wave needs ot be at leat 2% change of the lowest price
        self.bounce_threshold = 0.236 # fibonacci ratio

    @classmethod
    def yahoo_data_to_data_dict(cls, pands_series):
        return {
            'open': pands_series['Open'],
            'close': pands_series['Close'],
            'high': pands_series['High'],
            'low': pands_series['Low']
        }

    @classmethod
    def waves_stats(cls, waves):
        number_of_up_waves = 0
        number_of_down_waves = 0
        total_up_wave_move = 0
        total_down_wave_move = 0
        up_wave_move_length = 0
        down_wave_move_length = 0
        strong_up_wave_index = -1
        strong_down_wave_index = -1

        for index, wave in enumerate(waves):
            wave_direction = wave.direction()
            wave_summary = wave.summary()

            if wave_direction == 'up':
                number_of_up_waves += 1
                total_up_wave_move += wave_summary['price_range']
                up_wave_move_length += wave_summary['length']
                if wave_summary['length'] > wave.maximum_wave_length * 0.6:
                    strong_up_wave_index = index

            if wave_direction == 'down':
                number_of_down_waves += 1
                total_down_wave_move += wave_summary['price_range']
                down_wave_move_length += wave_summary['length']
                if wave_summary['length'] > wave.maximum_wave_length * 0.6:
                    strong_down_wave_index = index

        return {
            'up_waves_ratio': number_of_up_waves / (number_of_down_waves + number_of_up_waves),
            'up_magnitude_ratio': total_up_wave_move / (total_up_wave_move + total_down_wave_move),
            'number_of_up_waves': number_of_up_waves,
            'number_of_down_waves': number_of_down_waves,
            'up_wave_move_length': up_wave_move_length,
            'down_wave_move_length': down_wave_move_length,
            'strong_up_wave_index': strong_up_wave_index,
            'strong_down_wave_index': strong_down_wave_index
        }


    def length(self):
        return len(self.df)

    def direction(self):
        if self.num_high + self.num_low < 3:
            return 'n/a'

        if self.num_high > self.num_low:
            return 'up'
        else:
            return 'down'

    def price_range(self):
        return abs(self.high - self.low)

    def summary(self):
        if self.end:
            end_time = self.end.isoformat()
        else:
            end_time = None

        summary = {
            'start': self.start.isoformat(),
            'end': end_time,
            'direction': self.direction()
        }

        if summary['direction'] == 'up':
            summary['movement_in_percentage'] = self.high / self.low - 1
        else:
            summary['movement_in_percentage'] = self.low / self.high - 1

        summary['length'] = self.length()
        summary['price_range'] = self.price_range()

        return summary

    def is_create_new_wave(self, date, price_data_dict):
        maximum_wave_length = self.maximum_wave_length
        minimum_wave_length = self.minimum_wave_length
        minimum_wave_price_change = self.minimum_wave_price_change
        bounce_threshold = self.bounce_threshold

        if self.direction() == 'up':
            wave_end_date = self.high_date
        else:
            wave_end_date = self.low_date

        #  wave_length = len(self.df[self.start:wave_end_date])
        wave_length = self.length()

        if wave_length >= maximum_wave_length:
            return True

        if abs(self.high - self.low) / self.low < minimum_wave_price_change or wave_length < minimum_wave_length:
            return False

        if self.direction() == 'down' and self.low + self.price_range() * bounce_threshold < price_data_dict['close']:
            return True

        if self.direction() == 'up' and self.high - self.price_range() * bounce_threshold > price_data_dict['close']:
            return True


    def count(self, date, price_data_dict, skip_create_new_wave=False, time_increment=datetime.timedelta(days=1)):

        #  if is_create_new_wave(date, price_data_dict):
        if self.is_create_new_wave(date, price_data_dict):
            if self.direction() == 'up':
                self.end = self.high_date
            else:
                self.end = self.low_date

            re_process_date_df = self.df[self.end + time_increment:self.df.index[-1]].copy()
            re_process_date_df.loc[date] = price_data_dict
            self.df = self.df[self.start:self.end].copy()

            new_wave = None

            for index, row in re_process_date_df.iterrows():
                if new_wave:
                    new_wave.count(index, row, skip_create_new_wave=True)
                else:
                    new_wave = Wave(index, row)

            self.next_wave = new_wave

            return new_wave
            # for down wave, find the next day's price after the low
            # for up wave, find hte next days' price after the high
            # set the end date for the wave
            # create a new wave with the start date, and back fill by account count without creating new wave
            # link the previouse wave to new wave
            # return the new wave
            #  # create a new wave
            #  new_wave = Wave()
        if price_data_dict['close'] > self.high:
            self.high = price_data_dict['close']
            self.num_high += 1
            self.high_date = date
        elif price_data_dict['close'] < self.low:
            self.low = price_data_dict['close']
            self.num_low += 1
            self.low_date = date

        self.df.loc[date] = price_data_dict
