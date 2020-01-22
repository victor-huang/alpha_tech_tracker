from decimal import Decimal
import ipdb

from alpha_tech_tracker.strategy import SimpleStrategy

def test_create_an_instance_of_simple_strategy():
    new_strategy = SimpleStrategy()

    assert isinstance(new_strategy, SimpleStrategy)


def test_strategy_simulation():
    new_strategy_1 = SimpleStrategy(symbol='AMZN')

    new_strategy_1.simulate(start='2019-06-10', end='2019-06-13', use_saved_data=False)
    # for QQQ  new_strategy_1.simulate(start='2019-10-23', end='2019-11-20', use_saved_data=False)

def test_export_data():
    new_strategy_1 = SimpleStrategy(symbol='NVDA')
    date_range = [
            ['2019-12-01', '2020-01-15']
    ]
    new_strategy_1.export_data_to_json('NVDA', date_range)


