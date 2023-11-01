from decimal import Decimal
import ipdb

from alpha_tech_tracker.tsla_strategy import SimpleStrategy
from alpha_tech_tracker.trade_api.etrade.client import EtradeAPIClient


def test_create_an_instance_of_simple_strategy():
    new_strategy = SimpleStrategy(symbol="TSLA")

    assert isinstance(new_strategy, SimpleStrategy)


def test_strategy_simulation():
    #  client = EtradeAPIClient(selected_account_id="")
    #  client.authorize_session()

    # price history: https://candlecharts.com/candlestick-chart-look-up/tsla-candlestick-chart/

    client = None
    new_strategy_1 = SimpleStrategy(symbol="TSLA", trade_api_client=client)

    #  return
    ## current test
    new_strategy_1.simulate(
        start="2023-10-10", end="2023-10-31", use_saved_data=False, stream_data=False
    )
    #  new_strategy_1.simulate(start='2023-8-18', end='2023-9-21', use_saved_data=False, stream_data=False)

    # Up price double, +$5795.00

    ### Dated tests from 2016 - 2019
    #  new_strategy_1.simulate(start='2016-12-1', end='2017-6-19', use_saved_data=False, stream_data=False)
    # Down +$2868.00
    #  new_strategy_1.simulate(start='2017-7-20', end='2018-3-26', use_saved_data=False, stream_data=False)
    # down +$326.00
    #  new_strategy_1.simulate(start='2018-12-10', end='2019-5-28', use_saved_data=False, stream_data=False)
    # up +$12032
    #  new_strategy_1.simulate(start='2019-10-7', end='2020-2-10', use_saved_data=False, stream_data=False)

    ### special time when volatity is huge, avoid!
    # down, Covid moment, -$9193.00
    #  new_strategy_1.simulate(start='2020-2-18', end='2020-3-16', use_saved_data=False, stream_data=False)
    # up, -$950
    #  new_strategy_1.simulate(start='2020-3-23', end='2020-6-8', use_saved_data=False, stream_data=False)
    # up, +$2582.00, loss money most of the time, +$13000 with 4k max loss,
    # new_strategy_1.simulate(start='2020-6-01', end='2020-8-31', use_saved_data=False, stream_data=False)

    # + 5k, + $4749.00, $+ 5226.00
    #  new_strategy_1.simulate(start='2023-1-1', end='2023-9-21', use_saved_data=False, stream_data=False)
    #  new_strategy_1.simulate(start='2021-1-1', end='2023-9-21', use_saved_data=False, stream_data=False)
    #  new_strategy_1.simulate(start='2023-2-1', end='2023-3-1', use_saved_data=False, stream_data=False)
    # + $535.00
    #  new_strategy_1.simulate(start='2022-9-1', end='2022-12-31', use_saved_data=False, stream_data=False)

    # up
    #  + $1215.00
    #  new_strategy_1.simulate(start='2023-8-18', end='2023-9-21', use_saved_data=False, stream_data=False)
    # + $1242.00
    #  new_strategy_1.simulate(start='2023-8-21', end='2023-9-12', use_saved_data=False, stream_data=False)

    #  new_strategy_1.simulate(start='2023-1-01', end='2023-2-16', use_saved_data=False, stream_data=False)
    #  +$1553.00
    #  new_strategy_1.simulate(start='2023-8-18', end='2023-9-18', use_saved_data=False, stream_data=False)
    # + $1898.00
    #  new_strategy_1.simulate(start='2023-5-16', end='2023-7-19', use_saved_data=False, stream_data=False)

    # + $866
    #  new_strategy_1.simulate(start='2022-9-6', end='2022-9-20', use_saved_data=False, stream_data=False)
    # + $703
    #  new_strategy_1.simulate(start='2022-7-22', end='2022-8-16', use_saved_data=False, stream_data=False)
    # + $6059
    #  new_strategy_1.simulate(start='2022-3-16', end='2022-3-28', use_saved_data=False, stream_data=False)

    #  up trend but only make $1
    #  new_strategy_1.simulate(start='2021-9-12', end='2021-10-24', use_saved_data=False, stream_data=False)

    #  loss 2k, -564
    #  new_strategy_1.simulate(start='2020-11-01', end='2021-1-1', use_saved_data=False, stream_data=False)

    #  down
    # - $533.00
    #  new_strategy_1.simulate(start='2023-7-18', end='2023-8-17', use_saved_data=False, stream_data=False)
    #  new_strategy_1.simulate(start='2022-9-18', end='2022-12-30', use_saved_data=False, stream_data=False)

    # - $448
    #  new_strategy_1.simulate(start='2022-10-28', end='2022-11-23', use_saved_data=False, stream_data=False)
    # - $372.00
    #  new_strategy_1.simulate(start='2022-12-1', end='2023-1-4', use_saved_data=False, stream_data=False)

    # + $456.00
    #  new_strategy_1.simulate(start='2022-12-01', end='2022-12-30', use_saved_data=False, stream_data=False)
    # + 792.00
    #  new_strategy_1.simulate(start='2022-10-14', end='2022-11-22', use_saved_data=False, stream_data=False)
    #  loss 10k
    #  new_strategy_1.simulate(start='2021-12-26', end='2022-2-6', use_saved_data=False, stream_data=False)
    #  loss 6k
    #  new_strategy_1.simulate(start='2021-1-01', end='2021-3-6', use_saved_data=False, stream_data=False)
    #  new_strategy_1.simulate(start='2021-1-01', end='2021-2-6', use_saved_data=False, stream_data=False)

    # bigest decline from 300 to 100, still mange to profit $51
    # after the latest split of 3:1
    #  new_strategy_1.simulate(start='2022-8-18', end='2022-12-28', use_saved_data=False, stream_data=False)

    #  range bound
    #  new_strategy_1.simulate(start='2023-2-14', end='2023-6-1', use_saved_data=False, stream_data=False)
    #  new_strategy_1.simulate(start='2023-6-16', end='2023-9-20', use_saved_data=False, stream_data=False)
    #  loss ~20k
    #  new_strategy_1.simulate(start='2021-10-24', end='2022-3-27', use_saved_data=False, stream_data=False)
    #  new_strategy_1.simulate(start='2021-11-10', end='2021-11-18', use_saved_data=False, stream_data=False)

    # - $1081
    #  new_strategy_1.simulate(start='2022-5-26', end='2022-7-20', use_saved_data=False, stream_data=False)
    #   $379.00
    #  new_strategy_1.simulate(start='2022-5-26', end='2022-6-9', use_saved_data=False, stream_data=False)

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
