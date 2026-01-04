"""
Unit tests for Portfolio critical paths.

Tests the money-touching P&L calculation and position tracking logic.
These tests ensure profit/loss calculations are accurate for both stocks and options.

Coverage Target: 90%+ (critical path)
"""

import pytest
from datetime import datetime, timedelta
from decimal import Decimal
from alpha_tech_tracker.portfolio import Position, Portfolio


class TestPosition:
    """Test Position model creation and attributes."""

    def test_create_stock_position(self):
        """Stock position should be created with required fields."""
        position = Position(
            symbol="AAPL",
            open_price=150.0,
            quantity=10,
            type="stock",
            open_order_id="order-123",
        )

        assert position.symbol == "AAPL"
        assert position.open_price == Decimal("150.0")
        assert position.quantity == 10
        assert position.type == "stock"
        assert position.status == "open"
        assert position.id is not None

    def test_create_option_position(self):
        """Option position should be created with option-specific fields."""
        position = Position(
            symbol="TSLA",
            open_price=5.0,
            quantity=2,
            type="option",
            strike_price=200.0,
            osi_key="TSLA--231013C00200000",
            open_order_id="order-456",
        )

        assert position.type == "option"
        assert position.strike_price == 200.0
        assert position.osi_key == "TSLA--231013C00200000"

    def test_position_defaults_to_open(self):
        """Position should default to 'open' status."""
        position = Position(
            symbol="MSFT", open_price=300.0, quantity=5, open_order_id="order-789"
        )

        assert position.status == "open"
        assert not hasattr(position, "close_price") or position.close_price is None
        assert position.closed_at is None

    def test_position_with_close_price(self):
        """Position can be created with close_price."""
        position = Position(
            symbol="AAPL",
            open_price=150.0,
            close_price=160.0,
            quantity=10,
            open_order_id="order-123",
        )

        assert position.close_price == Decimal("160.0")


class TestPortfolio:
    """Test Portfolio position management."""

    def test_create_empty_portfolio(self):
        """Portfolio should start empty."""
        portfolio = Portfolio()

        assert portfolio.positions == []

    def test_add_stock_position(self):
        """Should add stock position to portfolio."""
        portfolio = Portfolio()

        position = portfolio.add_position(
            symbol="AAPL",
            open_price=150.0,
            quantity=10,
            type="stock",
            open_order_id="order-123",
        )

        assert position is not None
        assert len(portfolio.positions) == 1
        assert portfolio.positions[0].symbol == "AAPL"

    def test_add_option_position(self):
        """Should add option position to portfolio."""
        portfolio = Portfolio()

        position = portfolio.add_position(
            symbol="TSLA",
            open_price=5.0,
            quantity=2,
            type="option",
            strike_price=200.0,
            osi_key="TSLA--231013C00200000",
            open_order_id="order-456",
        )

        assert position is not None
        assert position.type == "option"
        assert len(portfolio.positions) == 1

    def test_add_position_requires_open_order_id(self):
        """Adding position without open_order_id should raise error."""
        portfolio = Portfolio()

        with pytest.raises(ValueError, match="open_order_id can not be None"):
            portfolio.add_position(
                symbol="AAPL", open_price=150.0, quantity=10, open_order_id=None
            )

    def test_find_position_existing(self):
        """Should find position by ID."""
        portfolio = Portfolio()

        position = portfolio.add_position(
            symbol="AAPL", open_price=150.0, quantity=10, open_order_id="order-123"
        )

        found = portfolio.find_position(position.id)

        assert found is not None
        assert found.id == position.id
        assert found.symbol == "AAPL"

    def test_find_position_nonexistent(self):
        """Should return None for non-existent position ID."""
        portfolio = Portfolio()

        found = portfolio.find_position("fake-position-id")

        assert found is None

    def test_close_position(self):
        """Should close position and update status."""
        portfolio = Portfolio()

        position = portfolio.add_position(
            symbol="AAPL", open_price=150.0, quantity=10, open_order_id="order-123"
        )

        closed_position = portfolio.close_position(
            id=position.id, close_price=160.0, close_order_id="order-456"
        )

        assert closed_position is not None
        assert closed_position.status == "closed"
        assert closed_position.close_price == 160.0
        assert closed_position.closed_at is not None

    def test_close_nonexistent_position(self):
        """Closing non-existent position should return None."""
        portfolio = Portfolio()

        result = portfolio.close_position(
            id="fake-id", close_price=100.0, close_order_id="order-999"
        )

        assert result is None

    def test_multiple_positions_tracking(self):
        """Should correctly track multiple positions."""
        portfolio = Portfolio()

        positions = []
        for i in range(5):
            position = portfolio.add_position(
                symbol=f"STOCK{i}",
                open_price=100.0 + i,
                quantity=10,
                open_order_id=f"order-{i}",
            )
            positions.append(position)

        assert len(portfolio.positions) == 5

        # Find each position
        for position in positions:
            found = portfolio.find_position(position.id)
            assert found is not None
            assert found.id == position.id


class TestPnLCalculations:
    """Test critical P&L calculation formulas."""

    def test_stock_profit_calculation(self):
        """Stock profit: (close_price - open_price) * quantity."""
        portfolio = Portfolio()

        position = portfolio.add_position(
            symbol="AAPL",
            open_price=150.0,
            quantity=10,
            type="stock",
            open_order_id="order-123",
        )

        portfolio.close_position(
            id=position.id, close_price=160.0, close_order_id="order-456"
        )

        pnl = portfolio.calculate_pnl()

        # Expected: (160 - 150) * 10 = 100
        assert pnl["pnl"] == Decimal("100")
        assert pnl["result"] == "profit"

    def test_stock_loss_calculation(self):
        """Stock loss: (close_price - open_price) * quantity."""
        portfolio = Portfolio()

        position = portfolio.add_position(
            symbol="AAPL",
            open_price=150.0,
            quantity=10,
            type="stock",
            open_order_id="order-123",
        )

        portfolio.close_position(
            id=position.id, close_price=140.0, close_order_id="order-456"
        )

        pnl = portfolio.calculate_pnl()

        # Expected: (140 - 150) * 10 = -100
        assert pnl["pnl"] == Decimal("-100")
        assert pnl["result"] == "loss"

    def test_option_profit_calculation(self):
        """Option profit: 100 * (close_price - open_price) * quantity."""
        portfolio = Portfolio()

        position = portfolio.add_position(
            symbol="TSLA",
            open_price=5.0,
            quantity=1,
            type="option",
            strike_price=200.0,
            osi_key="TSLA--231013C00200000",
            open_order_id="order-123",
        )

        portfolio.close_position(
            id=position.id, close_price=7.0, close_order_id="order-456"
        )

        pnl = portfolio.calculate_pnl()

        # Expected: 100 * (7 - 5) * 1 = 200
        assert pnl["pnl"] == Decimal("200")
        assert pnl["result"] == "profit"

    def test_option_loss_calculation(self):
        """Option loss: 100 * (close_price - open_price) * quantity."""
        portfolio = Portfolio()

        position = portfolio.add_position(
            symbol="TSLA",
            open_price=5.0,
            quantity=1,
            type="option",
            strike_price=200.0,
            osi_key="TSLA--231013C00200000",
            open_order_id="order-123",
        )

        portfolio.close_position(
            id=position.id, close_price=3.0, close_order_id="order-456"
        )

        pnl = portfolio.calculate_pnl()

        # Expected: 100 * (3 - 5) * 1 = -200
        assert pnl["pnl"] == Decimal("-200")
        assert pnl["result"] == "loss"

    def test_multiple_option_contracts_pnl(self):
        """P&L calculation should account for option multiplier (100 shares/contract)."""
        portfolio = Portfolio()

        position = portfolio.add_position(
            symbol="AAPL",
            open_price=10.0,
            quantity=3,  # 3 contracts
            type="option",
            strike_price=150.0,
            osi_key="AAPL--231015C00150000",
            open_order_id="order-123",
        )

        portfolio.close_position(
            id=position.id, close_price=12.0, close_order_id="order-456"
        )

        pnl = portfolio.calculate_pnl()

        # Expected: 100 * (12 - 10) * 3 = 600
        assert pnl["pnl"] == Decimal("600")

    def test_breakeven_position(self):
        """Position with no change should be 'even'."""
        portfolio = Portfolio()

        position = portfolio.add_position(
            symbol="AAPL",
            open_price=150.0,
            quantity=10,
            type="stock",
            open_order_id="order-123",
        )

        portfolio.close_position(
            id=position.id, close_price=150.0, close_order_id="order-456"
        )

        pnl = portfolio.calculate_pnl()

        assert pnl["pnl"] == Decimal("0")
        assert pnl["result"] == "even"


class TestPnLSummary:
    """Test portfolio-level P&L summary calculations."""

    def test_empty_portfolio_pnl(self):
        """Empty portfolio should return default summary."""
        portfolio = Portfolio()

        pnl = portfolio.calculate_pnl()

        assert pnl["positions_pnl"] == []
        assert pnl["result"] is None
        assert pnl["pnl_percent"] is None
        assert pnl["number_of_profit_positions"] == 0
        assert pnl["number_of_loss_positions"] == 0

    def test_multiple_positions_pnl(self):
        """Should calculate aggregate P&L across multiple positions."""
        portfolio = Portfolio()

        # Profitable position: +100
        position1 = portfolio.add_position(
            symbol="AAPL",
            open_price=150.0,
            quantity=10,
            type="stock",
            open_order_id="order-1",
        )
        portfolio.close_position(
            id=position1.id, close_price=160.0, close_order_id="order-2"
        )

        # Loss position: -50
        position2 = portfolio.add_position(
            symbol="MSFT",
            open_price=300.0,
            quantity=5,
            type="stock",
            open_order_id="order-3",
        )
        portfolio.close_position(
            id=position2.id, close_price=290.0, close_order_id="order-4"
        )

        pnl = portfolio.calculate_pnl()

        # Total P&L: 100 + (-50) = 50
        assert pnl["pnl"] == Decimal("50")
        assert pnl["result"] == "profit"
        assert pnl["number_of_profit_positions"] == 1
        assert pnl["number_of_loss_positions"] == 1

    def test_max_profit_tracking(self):
        """Should track maximum profit position."""
        portfolio = Portfolio()

        # Small profit: +50
        position1 = portfolio.add_position(
            symbol="AAPL",
            open_price=100.0,
            quantity=10,
            type="stock",
            open_order_id="order-1",
        )
        portfolio.close_position(
            id=position1.id, close_price=105.0, close_order_id="order-2"
        )

        # Large profit: +200
        position2 = portfolio.add_position(
            symbol="MSFT",
            open_price=200.0,
            quantity=10,
            type="stock",
            open_order_id="order-3",
        )
        portfolio.close_position(
            id=position2.id, close_price=220.0, close_order_id="order-4"
        )

        pnl = portfolio.calculate_pnl()

        assert pnl["max_profit"] == Decimal("200")

    def test_max_loss_tracking(self):
        """Should track maximum loss position."""
        portfolio = Portfolio()

        # Small loss: -30
        position1 = portfolio.add_position(
            symbol="AAPL",
            open_price=100.0,
            quantity=10,
            type="stock",
            open_order_id="order-1",
        )
        portfolio.close_position(
            id=position1.id, close_price=97.0, close_order_id="order-2"
        )

        # Large loss: -150
        position2 = portfolio.add_position(
            symbol="MSFT",
            open_price=200.0,
            quantity=10,
            type="stock",
            open_order_id="order-3",
        )
        portfolio.close_position(
            id=position2.id, close_price=185.0, close_order_id="order-4"
        )

        pnl = portfolio.calculate_pnl()

        assert pnl["max_loss"] == Decimal("-150")

    def test_pnl_percent_calculation(self):
        """Should calculate P&L percentage correctly."""
        portfolio = Portfolio()

        position = portfolio.add_position(
            symbol="AAPL",
            open_price=100.0,
            quantity=10,
            type="stock",
            open_order_id="order-1",
        )
        portfolio.close_position(
            id=position.id, close_price=110.0, close_order_id="order-2"
        )

        pnl = portfolio.calculate_pnl()

        # Position P&L percent: (1100 / 1000) - 1 = 0.1 (10%)
        assert pnl["positions_pnl"][0]["pnl_percent"] == Decimal("0.1")

    def test_position_pnl_includes_osi_key(self):
        """Position P&L should include osi_key for options."""
        portfolio = Portfolio()

        position = portfolio.add_position(
            symbol="TSLA",
            open_price=5.0,
            quantity=1,
            type="option",
            osi_key="TSLA--231013C00200000",
            open_order_id="order-1",
        )
        portfolio.close_position(
            id=position.id, close_price=7.0, close_order_id="order-2"
        )

        pnl = portfolio.calculate_pnl()

        assert pnl["positions_pnl"][0]["osi_key"] == "TSLA--231013C00200000"


class TestPnLBucketing:
    """Test time-based P&L bucketing (daily/weekly/monthly)."""

    def test_daily_pnl_bucketing(self):
        """Should bucket P&L by day."""
        portfolio = Portfolio()

        now = datetime.now()
        yesterday = now - timedelta(days=1)

        # Today's position
        position1 = portfolio.add_position(
            symbol="AAPL",
            open_price=150.0,
            quantity=10,
            type="stock",
            open_order_id="order-1",
        )
        portfolio.close_position(
            id=position1.id, close_price=160.0, close_order_id="order-2", closed_at=now
        )

        # Yesterday's position
        position2 = portfolio.add_position(
            symbol="MSFT",
            open_price=300.0,
            quantity=5,
            type="stock",
            open_order_id="order-3",
        )
        portfolio.close_position(
            id=position2.id,
            close_price=310.0,
            close_order_id="order-4",
            closed_at=yesterday,
        )

        pnl_buckets = portfolio.bucket_positions_pnl_by_time()

        assert "daily" in pnl_buckets
        assert "weekly" in pnl_buckets
        assert "monthly" in pnl_buckets

    def test_weekly_pnl_bucketing(self):
        """Should bucket P&L by week."""
        portfolio = Portfolio()

        now = datetime.now()

        position = portfolio.add_position(
            symbol="AAPL",
            open_price=150.0,
            quantity=10,
            type="stock",
            open_order_id="order-1",
        )
        portfolio.close_position(
            id=position.id, close_price=160.0, close_order_id="order-2", closed_at=now
        )

        pnl_buckets = portfolio.bucket_positions_pnl_by_time()

        assert "weekly" in pnl_buckets
        assert len(pnl_buckets["weekly"]) > 0

    def test_monthly_pnl_bucketing(self):
        """Should bucket P&L by month."""
        portfolio = Portfolio()

        now = datetime.now()

        position = portfolio.add_position(
            symbol="AAPL",
            open_price=150.0,
            quantity=10,
            type="stock",
            open_order_id="order-1",
        )
        portfolio.close_position(
            id=position.id, close_price=160.0, close_order_id="order-2", closed_at=now
        )

        pnl_buckets = portfolio.bucket_positions_pnl_by_time()

        assert "monthly" in pnl_buckets
        assert len(pnl_buckets["monthly"]) > 0


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_decimal_precision(self):
        """P&L calculations should maintain decimal precision."""
        portfolio = Portfolio()

        position = portfolio.add_position(
            symbol="AAPL",
            open_price=150.55,
            quantity=10,
            type="stock",
            open_order_id="order-1",
        )
        portfolio.close_position(
            id=position.id, close_price=160.75, close_order_id="order-2"
        )

        pnl = portfolio.calculate_pnl()

        # Expected: (160.75 - 150.55) * 10 = 102.0
        assert pnl["pnl"] == Decimal("102.0")

    def test_large_quantity_pnl(self):
        """P&L calculation should handle large quantities."""
        portfolio = Portfolio()

        position = portfolio.add_position(
            symbol="AAPL",
            open_price=150.0,
            quantity=1000,
            type="stock",
            open_order_id="order-1",
        )
        portfolio.close_position(
            id=position.id, close_price=151.0, close_order_id="order-2"
        )

        pnl = portfolio.calculate_pnl()

        # Expected: (151 - 150) * 1000 = 1000
        assert pnl["pnl"] == Decimal("1000")

    def test_mixed_stock_and_option_positions(self):
        """Portfolio should handle mixed stock and option positions."""
        portfolio = Portfolio()

        # Stock position: +100
        stock_position = portfolio.add_position(
            symbol="AAPL",
            open_price=150.0,
            quantity=10,
            type="stock",
            open_order_id="order-1",
        )
        portfolio.close_position(
            id=stock_position.id, close_price=160.0, close_order_id="order-2"
        )

        # Option position: +200
        option_position = portfolio.add_position(
            symbol="TSLA",
            open_price=5.0,
            quantity=1,
            type="option",
            osi_key="TSLA--231013C00200000",
            open_order_id="order-3",
        )
        portfolio.close_position(
            id=option_position.id, close_price=7.0, close_order_id="order-4"
        )

        pnl = portfolio.calculate_pnl()

        # Total: 100 + 200 = 300
        assert pnl["pnl"] == Decimal("300")
        assert pnl["result"] == "profit"
        assert len(pnl["positions_pnl"]) == 2
