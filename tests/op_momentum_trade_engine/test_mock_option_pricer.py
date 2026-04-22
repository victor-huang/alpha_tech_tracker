import logging
from unittest.mock import patch


from alpha_tech_tracker.op_momentum_strategy.mock_option_pricer import (
    mock_entry_price,
    mock_exit_price,
)

from conftest import _D

# OCC symbols used across tests
# strike=$90, call  → 10% ITM when stock=$100
_CALL_SYM = "TSLA990101C00090000"
# strike=$110, put  → 10% ITM when stock=$100
_PUT_SYM = "TSLA990101P00110000"

_DATE_PATH = "alpha_tech_tracker.op_momentum_strategy.option_price_monitor.date"


class TestMockEntryPrice:
    def test_call_intrinsic_plus_20pct_time_premium(self):
        # stock=$100 strike=$90 → intrinsic=$10, time_prem=$2, price=$12 → tick $0.10
        with patch(_DATE_PATH) as m:
            m.today.return_value = __import__("datetime").date(2026, 4, 1)
            m.side_effect = __import__("datetime").date
            price = mock_entry_price(_D("100"), _CALL_SYM, "call")
        assert price == _D("12.00")

    def test_put_intrinsic_plus_20pct_time_premium(self):
        # stock=$100 strike=$110 → intrinsic=$10, time_prem=$2, price=$12
        with patch(_DATE_PATH) as m:
            m.today.return_value = __import__("datetime").date(2026, 4, 1)
            m.side_effect = __import__("datetime").date
            price = mock_entry_price(_D("100"), _PUT_SYM, "put")
        assert price == _D("12.00")

    def test_result_is_quantized_to_10_cent_tick(self):
        # stock=$101, strike=$90 → intrinsic=$11, *1.20=$13.20 → $13.20 (already on tick)
        with patch(_DATE_PATH) as m:
            m.today.return_value = __import__("datetime").date(2026, 4, 1)
            m.side_effect = __import__("datetime").date
            price = mock_entry_price(_D("101"), _CALL_SYM, "call")
        assert price == _D("13.20")

    def test_custom_time_premium_ratio(self):
        # stock=$100, strike=$90 → intrinsic=$10, ratio=0.10 → price=$11
        with patch(_DATE_PATH) as m:
            m.today.return_value = __import__("datetime").date(2026, 4, 1)
            m.side_effect = __import__("datetime").date
            price = mock_entry_price(_D("100"), _CALL_SYM, "call", time_premium_ratio=_D("0.10"))
        assert price == _D("11.00")

    def test_invalid_occ_symbol_returns_zero(self):
        price = mock_entry_price(_D("100"), "INVALID", "call")
        assert price == _D("0")


class TestMockEntryPriceOTM:
    """OTM contracts should never reach mock_entry_price when MockContractSelector is used.
    These tests verify that the error path is guarded correctly.
    """

    def test_otm_call_returns_zero(self):
        # stock=$85 < strike=$90 → OTM call → returns $0 (trade skipped)
        with patch(_DATE_PATH) as m:
            m.today.return_value = __import__("datetime").date(2026, 4, 1)
            m.side_effect = __import__("datetime").date
            price = mock_entry_price(_D("85"), _CALL_SYM)
        assert price == _D("0")

    def test_otm_put_returns_zero(self):
        # stock=$115 > strike=$110 → OTM put → returns $0
        with patch(_DATE_PATH) as m:
            m.today.return_value = __import__("datetime").date(2026, 4, 1)
            m.side_effect = __import__("datetime").date
            price = mock_entry_price(_D("115"), _PUT_SYM)
        assert price == _D("0")

    def test_otm_call_logs_error(self, caplog):
        with patch(_DATE_PATH) as m:
            m.today.return_value = __import__("datetime").date(2026, 4, 1)
            m.side_effect = __import__("datetime").date
            with caplog.at_level(logging.ERROR):
                mock_entry_price(_D("85"), _CALL_SYM)
        assert "OTM contract at entry" in caplog.text

    def test_otm_put_logs_error(self, caplog):
        with patch(_DATE_PATH) as m:
            m.today.return_value = __import__("datetime").date(2026, 4, 1)
            m.side_effect = __import__("datetime").date
            with caplog.at_level(logging.ERROR):
                mock_entry_price(_D("115"), _PUT_SYM)
        assert "OTM contract at entry" in caplog.text

    def test_atm_call_returns_zero(self):
        # stock exactly at strike → intrinsic=0 → treated as OTM
        with patch(_DATE_PATH) as m:
            m.today.return_value = __import__("datetime").date(2026, 4, 1)
            m.side_effect = __import__("datetime").date
            price = mock_entry_price(_D("90"), _CALL_SYM)
        assert price == _D("0")


class TestMockExitPrice:
    def _entry_price(self, stock, symbol, option_type):
        with patch(_DATE_PATH) as m:
            m.today.return_value = __import__("datetime").date(2026, 4, 1)
            m.side_effect = __import__("datetime").date
            return mock_entry_price(_D(str(stock)), symbol, option_type)

    def test_stock_gain_increases_call_exit_price(self):
        # entry: stock=$100 → price=$12 (intrinsic=$10, tp=$2)
        # exit: stock=$102 → intrinsic=$12, tp=$2*0.95=$1.90, exit=$13.90 → $13.90
        with patch(_DATE_PATH) as m:
            m.today.return_value = __import__("datetime").date(2026, 4, 1)
            m.side_effect = __import__("datetime").date
            entry = mock_entry_price(_D("100"), _CALL_SYM, "call")
            exit_p = mock_exit_price(
                exit_stock_price=_D("102"),
                option_symbol=_CALL_SYM,
                option_type="call",
                entry_price=entry,
                entry_stock_price=_D("100"),
            )
        assert exit_p > entry

    def test_exit_price_equals_full_intrinsic_plus_time_premium(self):
        # time decay disabled (=1.0) → exit = exit_intrinsic + full entry time premium
        with patch(_DATE_PATH) as m:
            m.today.return_value = __import__("datetime").date(2026, 4, 1)
            m.side_effect = __import__("datetime").date
            entry = mock_entry_price(_D("100"), _CALL_SYM, "call")
            exit_p = mock_exit_price(
                exit_stock_price=_D("102"),
                option_symbol=_CALL_SYM,
                option_type="call",
                entry_price=entry,
                entry_stock_price=_D("100"),
            )
        # exit_iv=$12, tp=$2*1.0=$2.00 → exit=$14.00
        assert exit_p == _D("14.00")

    def test_stock_loss_decreases_put_exit_price(self):
        # put: entry stock=$100 strike=$110 → intrinsic=$10, price=$12
        # exit stock=$102 → put intrinsic=$8, tp=$2*0.95=$1.90 → exit=$9.90
        with patch(_DATE_PATH) as m:
            m.today.return_value = __import__("datetime").date(2026, 4, 1)
            m.side_effect = __import__("datetime").date
            entry = mock_entry_price(_D("100"), _PUT_SYM, "put")
            exit_p = mock_exit_price(
                exit_stock_price=_D("102"),
                option_symbol=_PUT_SYM,
                option_type="put",
                entry_price=entry,
                entry_stock_price=_D("100"),
            )
        assert exit_p < entry

    def test_flat_stock_exit_price_unchanged_with_no_time_decay(self):
        # stock unchanged → intrinsic unchanged; time decay disabled → tp fully retained
        with patch(_DATE_PATH) as m:
            m.today.return_value = __import__("datetime").date(2026, 4, 1)
            m.side_effect = __import__("datetime").date
            entry = mock_entry_price(_D("100"), _CALL_SYM, "call")
            exit_p = mock_exit_price(
                exit_stock_price=_D("100"),
                option_symbol=_CALL_SYM,
                option_type="call",
                entry_price=entry,
                entry_stock_price=_D("100"),
            )
        # intrinsic same ($10), tp=$2*1.0=$2.00 → exit=$12.00 (same as entry)
        assert exit_p == _D("12.00")

    def test_invalid_occ_symbol_returns_entry_price(self):
        result = mock_exit_price(
            exit_stock_price=_D("102"),
            option_symbol="INVALID",
            option_type="call",
            entry_price=_D("12.00"),
            entry_stock_price=_D("100"),
        )
        assert result == _D("12.00")
