import logging

import pytest

from alpha_tech_tracker.op_momentum_strategy.wave_strategy.intents import Intent


class TestIntent:
    def test_defaults_to_a_notified_warning_level_intent_without_an_order(self):
        intent = Intent("enter", "BUY AMD")

        assert (intent.notify, intent.level, intent.order, intent.trade) == (True, logging.WARNING, None, None)

    def test_unknown_kind_is_an_error(self):
        with pytest.raises(ValueError):
            Intent("buy", "BUY AMD")

    def test_unknown_order_is_an_error(self):
        with pytest.raises(ValueError):
            Intent("enter", "BUY AMD", order="market")
