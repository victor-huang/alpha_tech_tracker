from datetime import datetime
from decimal import Decimal
import uuid

class Signal(object):
    def __init__(self, *, name, category, symbol=None, trend=None, signaled_at=datetime.now()):
        # caategory: marco, sector , assert, technical, fundmental, 
        self.id = uuid.uuid1()
        self.name = name
        self.symbol = symbol
        self.category = category
        self.trend = trend
        self.signaled_at = signaled_at

