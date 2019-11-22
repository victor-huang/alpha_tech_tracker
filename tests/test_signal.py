from decimal import Decimal
import ipdb

from alpha_tech_tracker.signal import Signal

def test_create_an_instance_of_signal():
    new_signal = Signal(name='test-signal', category='macro', symbol='GOOGL')

    assert isinstance(new_signal, Signal)
    assert new_signal.name == 'test-signal'
    assert new_signal.category == 'macro'
    assert new_signal.symbol == 'GOOGL'
    assert new_signal.signaled_at != None
