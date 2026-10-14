import datetime
from pandas import Series

from alpha_tech_tracker.wave import Wave
import ipdb


def is_sorted(x, order=-1):
    if order == 1:
        key = lambda x: x
    else:
        key = lambda x: -x

    """ check for descending order by default """
    return all([key(x[i]) <= key(x[i + 1]) for i in range(len(x) - 1)])


def moving_average(window, df):
    """
    data frame should has two series: time, and value
    :return: a time serires data frame of the moving average
    """

    ma_df = df.rolling(window).mean()
    ma_df.columns = ["mavg_{}".format(window)]
    return ma_df


def moving_average_summary(windows, df):
    """
    calculate multiple moving average based on specified window sizes
    :windows: a list of moving average window size. e.g [50, 100]
    :return: a data frame containing all moving average stats.
    """

    all_ma_df = None

    for moving_average_type in windows:
        ma_df = moving_average(moving_average_type, df)

        if all_ma_df is None:
            all_ma_df = ma_df
        else:
            all_ma_df = all_ma_df.join(ma_df)

    return all_ma_df


# TODO: need follow up, not working yet
def detect_moving_average_trend(df):
    """
    :return: "up". "down", "n/a"
    """

    all_moving_avg_df = moving_average_summary([20, 50, 150, 200], df)
    mv_labels = ["mavg_50", "mavg_150", "mavg_200"]

    # sort the df with latest date first
    all_moving_avg_df = df.join(all_moving_avg_df).sort_index(ascending=False, axis=0)

    up_trend_days = []
    down_trend_days = []
    num_of_days_mv_up_trend = 0
    num_of_days_mv_down_trend = 0
    later_day_trend = None  # is_sorted(all_moving_avg_df.iloc[0].values[1:])

    for index, row in all_moving_avg_df.iterrows():
        mv_prices = [row[l] for l in mv_labels]

        # decending order, mv20 > mv50 > mv150 > mv200
        if is_sorted(mv_prices):
            if later_day_trend is None or later_day_trend == "up":
                num_of_days_mv_up_trend += 1

            if later_day_trend and later_day_trend != "up":
                # reset is needed
                print("Switch to down {}".format(row))
                up_trend_days.append(num_of_days_mv_up_trend)
                num_of_days_mv_up_trend = 0
                num_of_days_mv_down_trend = 0

            later_day_trend = "up"
        elif is_sorted(mv_prices, 1):
            if later_day_trend is None or later_day_trend == "down":
                num_of_days_mv_down_trend += 1

            if later_day_trend and later_day_trend != "down":
                print("Switch to up {}".format(row))
                # reset is needed
                down_trend_days.append(num_of_days_mv_down_trend)
                num_of_days_mv_up_trend = 0
                num_of_days_mv_down_trend = 0

            later_day_trend = "down"
        else:
            if later_day_trend == "up":
                print("Switch to down {}".format(row))
                up_trend_days.append(num_of_days_mv_up_trend)

            if later_day_trend == "down":
                print("Switch to up {}".format(row))
                down_trend_days.append(num_of_days_mv_down_trend)

            num_of_days_mv_up_trend = 0
            num_of_days_mv_down_trend = 0
            later_day_trend = "n/a"

    return later_day_trend


### Reversal Patterns ###


def long_tail_reversal(close, open, high, low, trend="up", daily_movement_minimum=0.01):
    """
    try to detect if a chandle stick fall in the pattern of a doji, long-shadow and hammer
    :daily_movement_minimum: default to 0.01 (1%)
    """
    detected = False
    mid_point_magnatude_scaling = 0.8

    # the move range needs to be large than percentage  of open price
    if abs((high - low)) / open < daily_movement_minimum:
        return False

    if trend == "up":
        mid_point = (high - low) / 2.0 * mid_point_magnatude_scaling + low
        # both open and close need to above mid-point
        if open >= mid_point and close >= mid_point:
            detected = True
    else:
        mid_point = (high - low) / 2.0 * (1 + (1 - mid_point_magnatude_scaling)) + low
        if open <= mid_point and close <= mid_point:
            detected = True

    return detected


def long_tail_reversal_combo(price_data, trend="up", daily_movement_minimum=0.01):
    """
    :price_data: a consecutive two days' price data array [(close, open, high, low)]
    :daily_movement_minimum: default to 0.01 (1%)
    """

    detected = False

    day_2_low = price_data[1][-1]
    day_1_close = price_data[0][0]
    day_2_high = price_data[1][-2]
    day_1_low = min([price_data[0][0], price_data[0][1]])
    day_1_high = max([price_data[0][0], price_data[0][1]])

    if trend == "up":
        if day_2_low < day_1_low and long_tail_reversal(
            *price_data[1], trend=trend, daily_movement_minimum=daily_movement_minimum
        ):
            detected = True
    else:
        if day_2_high > day_1_high and long_tail_reversal(
            *price_data[1], trend=trend, daily_movement_minimum=daily_movement_minimum
        ):
            detected = True

    return detected


def engulfing_reversal(price_data, trend="up", daily_movement_minimum=None):
    detected = False

    first_candle_size = abs(price_data[0][1] - price_data[0][0])
    second_candle_size = abs(price_data[1][1] - price_data[1][0])
    second_day_price_diff = price_data[1][0] - price_data[1][1]
    is_second_day_open_lower = price_data[1][1] < price_data[0][0]
    is_second_day_open_higher = price_data[1][1] > price_data[0][0]
    is_second_day_close_higher = (
        price_data[1][0] > price_data[0][0] and price_data[1][0] > price_data[0][1]
    )
    is_second_day_close_lower = (
        price_data[1][0] < price_data[0][1] and price_data[1][0] < price_data[0][0]
    )

    if (
        abs(price_data[1][3] - price_data[1][1])
        + abs(price_data[1][2] - price_data[1][0])
        > abs(second_day_price_diff) * 0.30
    ):
        return False

    if second_candle_size > first_candle_size:
        if (
            trend == "up"
            and second_day_price_diff > 0
            and is_second_day_open_lower
            and is_second_day_close_higher
        ):
            detected = True
        if (
            trend == "down"
            and second_day_price_diff < 0
            and is_second_day_open_higher
            and is_second_day_close_lower
        ):
            detected = True

    return detected


def piercing_reversal(price_data, trend="up", daily_movement_minimum=0.015):
    """
    trend="up" (piercing line): after a down candle, an up candle that opens below its close and closes above the
    middle of its body, but below its open.
    trend="down" (dark cloud cover): after an up candle, a down candle that opens above its close and closes below
    the middle of its body, but above its open. On 5-min bars it marked wave highs 50-100% of the time, though
    rarely (research/ticker_characteristic).
    :daily_movement_minimum: default to 0.015 (1.5%), the second candle's minimum body as a fraction of its open;
        on intraday bars pass the ticker's average bar range as a fraction of price
    """
    # data point order: close, open, high, low
    detected = False
    d = price_data

    firt_day_candle_mid_point = abs(d[0][0] - d[0][1]) / 2.0

    is_first_day_down = d[0][0] < d[0][1]
    is_first_day_up = d[0][0] > d[0][1]

    is_second_candle_close_above_mid_point = (
        d[1][0] > d[0][0] + firt_day_candle_mid_point
    )
    is_second_candle_open_below_firt_day_close = d[1][1] < d[0][0]
    is_close_below_first_candle_open = d[1][0] < d[0][1]

    # the last day's move range needs to be large than percentage  of open price
    if abs((d[1][0] - d[1][1])) / d[1][1] < daily_movement_minimum:
        return False

    if is_first_day_down and trend == "up":
        if (
            is_second_candle_close_above_mid_point
            and is_second_candle_open_below_firt_day_close
            and is_close_below_first_candle_open
        ):
            detected = True
    elif is_first_day_up and trend == "down":
        is_second_candle_open_above_first_day_close = d[1][1] > d[0][0]
        is_second_candle_close_below_mid_point = (
            d[1][0] < d[0][0] - firt_day_candle_mid_point
        )
        is_close_above_first_candle_open = d[1][0] > d[0][1]
        if (
            is_second_candle_open_above_first_day_close
            and is_second_candle_close_below_mid_point
            and is_close_above_first_candle_open
        ):
            detected = True

    return detected


def push_reversal(price_data, trend="up", daily_movement_minimum=0.015):
    # data point order: close, open, high, low
    day1_price = price_data[0]
    day2_price = price_data[1]
    difference_tolerance = 0.2  # 20%
    candle_position_shift_tolerance = 0.005
    daily_price_movement_percentage = daily_movement_minimum  # at least 1.5%
    detected = False

    first_candle_direction = day1_price[0] - day1_price[1]
    second_candle_direction = day2_price[0] - day2_price[1]

    # a first candle with no body (a doji) has nothing to push back against
    if first_candle_direction == 0:
        return False

    day1_move_price_precentage = abs(first_candle_direction) / day1_price[0]
    day2_move_price_precentage = abs(second_candle_direction) / day2_price[0]

    # the first and second candle needs to move in differnet direction
    if first_candle_direction * second_candle_direction > 0:
        return False

    is_price_movement_within_range = (
        abs(day1_move_price_precentage - day2_move_price_precentage)
        / day1_move_price_precentage
        < difference_tolerance
    )
    is_daily_price_movement_large_enough = (
        day2_move_price_precentage > daily_price_movement_percentage
    )
    is_first_day_close_near_second_day_open = (
        abs(day1_price[0] - day2_price[1]) / day1_price[0]
        < candle_position_shift_tolerance
    )
    is_first_day_open_near_second_day_close = (
        abs(day1_price[1] - day2_price[0]) / day1_price[1]
        < candle_position_shift_tolerance
    )

    if (
        trend == "up"
        and second_candle_direction > 0
        and is_price_movement_within_range
        and is_daily_price_movement_large_enough
        and is_first_day_open_near_second_day_close
    ):
        detected = True

    if (
        trend == "down"
        and second_candle_direction < 0
        and is_price_movement_within_range
        and is_daily_price_movement_large_enough
        and is_first_day_open_near_second_day_close
    ):
        detected = True

    return detected


def confirmed_long_tail_reversal(price_data, trend="up", daily_movement_minimum=0.01):
    """
    a long tail reversal candle (doji, long shadow or hammer) confirmed by the next candle closing beyond it:
    above its high for trend="up", below its low for trend="down". The confirmation costs one candle; on 5-min
    bars it was the most reliable reversal signal at wave lows and highs for every ticker studied
    (research/ticker_characteristic). On intraday bars pass the ticker's average bar range as a fraction of
    price as `daily_movement_minimum`.
    :price_data: the long tail candle and the candle after it [(close, open, high, low), (close, open, high, low)]
    :daily_movement_minimum: default to 0.01 (1%), the long tail candle's minimum range as a fraction of its open
    """
    # data point order: close, open, high, low
    signal_candle = price_data[0]
    confirmation_candle = price_data[1]

    if not long_tail_reversal(
        *signal_candle, trend=trend, daily_movement_minimum=daily_movement_minimum
    ):
        return False

    if trend == "up":
        return confirmation_candle[0] > signal_candle[2]

    return confirmation_candle[0] < signal_candle[3]


def volume_long_wick_reversal(
    close,
    open,
    high,
    low,
    volume,
    average_volume,
    trend="up",
    wick_ratio=0.5,
    volume_multiple=1.5,
    daily_movement_minimum=None,
):
    """
    a candle with a long wick on the reversal side traded on heavy volume: the lower wick for trend="up",
    the upper wick for trend="down", at least `wick_ratio` of the candle's range, on at least
    `volume_multiple` x `average_volume`. On 5-min bars the second most reliable reversal signal at wave lows
    and highs after confirmed_long_tail_reversal, with no wait for a confirming candle
    (research/ticker_characteristic); the wick alone, without the volume, is no signal.
    :average_volume: the reference volume, e.g. the mean volume of the previous 78 5-min bars
    :daily_movement_minimum: optional minimum range as a fraction of the open (default: no minimum)
    """
    candle_range = high - low
    if candle_range <= 0 or not average_volume:
        return False

    if daily_movement_minimum is not None and candle_range / open < daily_movement_minimum:
        return False

    # written as "not >=" so a missing (NaN) volume or average volume fails instead of passing
    if not volume >= average_volume * volume_multiple:
        return False

    if trend == "up":
        wick = min(open, close) - low
    else:
        wick = high - max(open, close)

    return wick / candle_range >= wick_ratio


def gap_move(price_data, trend="up", daily_movement_minimum=1):
    # data point order: close, open, high, low
    day1_price = price_data[0]
    day2_price = price_data[1]

    gap_percentage = daily_movement_minimum
    detected = False

    if trend == "up":
        if (
            day2_price[1] > (day1_price[2] * (1 + gap_percentage / 100.0))
            and day2_price[3] > day1_price[2]
        ):
            detected = True
    else:
        if (
            day2_price[1] < (day1_price[3] * (1 - gap_percentage / 100.0))
            and day2_price[2] < day1_price[3]
        ):
            detected = True

    return detected


def wave_detection(df):
    """detecte the length and the waves in the given data frame period"""
    """
    the wave object: {
        high: the hiest price,
        low: the lowest price,
        num_high: number of times high is updated
        num_low: number of time low is updated
        start: start date of the wave
        end: end date of the wave
    }
    """

    df = df.set_index("Date").rename(str.lower, axis="columns")
    wave = None
    all_waves = []

    for index, row in df.iterrows():
        date = datetime.datetime.strptime(index, "%Y-%m-%d").date()

        if not wave:
            wave = Wave(date, row)
            all_waves.append(wave)
        else:
            new_wave = wave.count(date, row)

            if new_wave:
                all_waves.append(new_wave)
                wave = new_wave

    return all_waves


def detect_reversal(df):
    def test(row):
        ipdb.set_trace()

    def map_price_data(rows, detection=push_reversal):
        price_data = [
            [rows[0]["Close"], rows[0]["Open"], rows[0]["High"], rows[0]["Low"]],
            [rows[1]["Close"], rows[1]["Open"], rows[1]["High"], rows[1]["Low"]],
        ]

        #  return long_tail_reversal_combo(price_data, trend='down')
        return detection(price_data, trend="up")

    def map_polygon_io_price_data(rows, detection=push_reversal):
        price_data = [
            [rows[0]["close"], rows[0]["open"], rows[0]["high"], rows[0]["low"]],
            [rows[1]["close"], rows[1]["open"], rows[1]["high"], rows[1]["low"]],
        ]

        #  return long_tail_reversal_combo(price_data, trend='down')
        return detection(price_data, trend="up")

    #  df['reversal'] = df.rolling(2, axis=0).apply(map_price_data)
    reversal_detected = []

    for index, row in df.iterrows():
        if index == 0:
            reversal_detected.append(False)
            continue

        rows = [df.iloc[index - 1], row]

        reversal_detected.append(
            map_polygon_io_price_data(rows, long_tail_reversal_combo)
        )

    df["reversal"] = Series(reversal_detected, index=df.index)

    #  df['reversal'] = df.rolling(2, axis=0).apply(map_price_data)
    #  df['reversal'] = pd.rolling_apply(df, 2, map_price_data)
    #  ipdb.set_trace()
