from decimal import Decimal
import ipdb

from alpha_tech_tracker.strategy import SimpleStrategy

def test_create_an_instance_of_simple_strategy():
    new_strategy = SimpleStrategy()

    assert isinstance(new_strategy, SimpleStrategy)


def test_strategy_simulation():
    new_strategy = SimpleStrategy()


    new_strategy.simulate()
