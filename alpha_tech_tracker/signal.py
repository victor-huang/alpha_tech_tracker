from datetime import datetime
from decimal import Decimal
import uuid

import ipdb

class Signal(object):
    def __init__(self, *, name, category, symbol=None, signaled_at=datetime.now()):
        # caategory: marco, sector , assert, technical, fundmental, 
        self.id = uuid.uuid1()
        self.name = name
        self.symbol = symbol
        self.category = category
        self.signaled_at = datetime.now()

