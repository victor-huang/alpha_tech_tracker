import numpy
from numpy.testing import assert_array_equal
import pandas as pd
import pytest
import ipdb


import alpha_tech_tracker.technical_analysis as ta
import alpha_tech_tracker.stock_price_data_loader as data_loader


def test_load_from_csv():
    data_loader.load_from_csv()
