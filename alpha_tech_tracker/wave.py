import datetime
import pandas as pd
from pandas import Series

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

    @classmethod
    def yahoo_data_to_data_dict(cls, pands_series):
        return {
            'open': pands_series['Open'],
            'close': pands_series['Close'],
            'high': pands_series['High'],
            'low': pands_series['Low']
        }

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
        summary = {}

        if self.direction() == 'up':
            summary['movement_in_percentage'] = self.high / self.low - 1
        else:
            summary['movement_in_percentage'] = self.low / self.high - 1

        summary['length'] = len(self.df)

        return summary

    def is_create_new_wave(self, date, price_data_dict):
        minimum_wave_length = 7
        minimum_wave_price_change = 0.03 # wave needs ot be at leat 2% change of the lowest price
        bounce_threshold = 0.236 # fibonacci ratio

        if self.direction() == 'up':
            wave_end_date = self.high_date
        else:
            wave_end_date = self.low_date

        #  wave_length = len(self.df[self.start:wave_end_date])
        wave_length = len(self.df)

        if abs(self.high - self.low) / self.low < minimum_wave_price_change or wave_length < minimum_wave_length:
            return False

        if self.direction() == 'down' and self.low + self.price_range() * bounce_threshold < price_data_dict['close']:
            return True

        if self.direction() == 'up' and self.high - self.price_range() * bounce_threshold > price_data_dict['close']:
            return True


    def count(self, date, price_data_dict, skip_create_new_wave=False):
        #  if is_create_new_wave(date, price_data_dict):
        if self.is_create_new_wave(date, price_data_dict):
            if self.direction() == 'up':
                self.end = self.high_date
            else:
                self.end = self.low_date

            re_process_date_df = self.df[self.end + datetime.timedelta(days=1):self.df.index[-1]]
            re_process_date_df.loc[date] = price_data_dict
            self.df = self.df[self.start:self.end]

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
