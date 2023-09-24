from decimal import Decimal
import ipdb

from alpha_tech_tracker.tsla_strategy import SimpleStrategy

def test_create_an_instance_of_simple_strategy():
    new_strategy = SimpleStrategy(symbol='TSLA')

    assert isinstance(new_strategy, SimpleStrategy)


def test_strategy_simulation():
    new_strategy_1 = SimpleStrategy(symbol='TSLA')
    # price history: https://candlecharts.com/candlestick-chart-look-up/tsla-candlestick-chart/


    # + 5k, + $4749.00
    #  new_strategy_1.simulate(start='2023-1-1', end='2023-9-21', use_saved_data=False, stream_data=False)
    #  new_strategy_1.simulate(start='2021-1-1', end='2023-9-21', use_saved_data=False, stream_data=False)
    #  new_strategy_1.simulate(start='2023-2-1', end='2023-3-1', use_saved_data=False, stream_data=False)

    # up 
    #  + $1215.00
    #  new_strategy_1.simulate(start='2023-8-18', end='2023-9-21', use_saved_data=False, stream_data=False)
    #  new_strategy_1.simulate(start='2023-1-01', end='2023-2-16', use_saved_data=False, stream_data=False)
    #  +$1553.00
    #  new_strategy_1.simulate(start='2023-8-18', end='2023-9-18', use_saved_data=False, stream_data=False)
    # + $1898.00
    #  new_strategy_1.simulate(start='2023-5-16', end='2023-7-19', use_saved_data=False, stream_data=False)

    #  new_strategy_1.simulate(start='2023-5-16', end='2023-5-26', use_saved_data=False, stream_data=False)

    #  loss 2k
    #  new_strategy_1.simulate(start='2020-11-01', end='2021-1-1', use_saved_data=False, stream_data=False)

    #  up trend but only make $1
    #  new_strategy_1.simulate(start='2021-9-12', end='2021-10-24', use_saved_data=False, stream_data=False)

    #  down
    # - $533.00
    #  new_strategy_1.simulate(start='2023-7-18', end='2023-8-17', use_saved_data=False, stream_data=False)
    #  new_strategy_1.simulate(start='2022-9-18', end='2022-12-30', use_saved_data=False, stream_data=False)
    # + $456.00
    # new_strategy_1.simulate(start='2022-12-01', end='2022-12-30', use_saved_data=False, stream_data=False)
    #  new_strategy_1.simulate(start='2022-10-14', end='2022-11-22', use_saved_data=False, stream_data=False)
    #  loss 10k
    #  new_strategy_1.simulate(start='2021-12-26', end='2022-2-6', use_saved_data=False, stream_data=False)
    #  loss 6k
    #  new_strategy_1.simulate(start='2021-1-01', end='2021-3-6', use_saved_data=False, stream_data=False)
    new_strategy_1.simulate(start='2021-1-01', end='2021-2-6', use_saved_data=False, stream_data=False)

    # bigest decline from 300 to 100, still mange to profit $51
    # after the latest split of 3:1
    #  new_strategy_1.simulate(start='2022-8-18', end='2022-12-28', use_saved_data=False, stream_data=False)

    #  even
    #  new_strategy_1.simulate(start='2023-2-14', end='2023-6-1', use_saved_data=False, stream_data=False)
    #  new_strategy_1.simulate(start='2023-6-16', end='2023-9-20', use_saved_data=False, stream_data=False)
    #  loss ~20k
    #  new_strategy_1.simulate(start='2021-10-24', end='2022-3-27', use_saved_data=False, stream_data=False)
    #  new_strategy_1.simulate(start='2021-11-10', end='2021-11-18', use_saved_data=False, stream_data=False)


    # presplit 3:1 08/25/2022
    # - $136, $2247.00
    #  new_strategy_1.simulate(start='2022-3-1', end='2022-5-1', use_saved_data=False, stream_data=False)
    # up
    #  + $3482.00, + $5675.00
    #  new_strategy_1.simulate(start='2022-3-1', end='2022-4-5', use_saved_data=False, stream_data=False)
    #  + $3856.00  
    #  new_strategy_1.simulate(start='2022-3-15', end='2022-4-5', use_saved_data=False, stream_data=False)

    # down
    #  - $5331.00, -$5158.00
    #  new_strategy_1.simulate(start='2022-4-5', end='2022-5-25', use_saved_data=False, stream_data=False)


    return
