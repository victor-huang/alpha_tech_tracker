"""
Unit tests for OrderEngine critical paths.

Tests the money-touching order placement, execution, and tracking logic.
These tests ensure orders are created, tracked, and executed correctly.

Coverage Target: 90%+ (critical path)
"""

import pytest
from datetime import datetime
from alpha_tech_tracker.order_engine import Order, OrderEngine, MockOrderEngine


class TestOrder:
    """Test Order model creation and attributes."""

    def test_create_stock_order(self):
        """Stock order should be created with all required fields."""
        order = Order(
            asset_type="stock",
            symbol="AAPL",
            exchange="NASDAQ",
            side="buy",
            price=150.0,
            quantity=10,
            type="market",
        )

        assert order.asset_type == "stock"
        assert order.symbol == "AAPL"
        assert order.side == "buy"
        assert order.price == 150.0
        assert order.quantity == 10
        assert order.status == "open"
        assert order.id is not None  # UUID generated

    def test_create_option_order(self):
        """Option order should be created with option-specific fields."""
        order = Order(
            asset_type="option",
            symbol="TSLA",
            exchange="CBOE",
            side="buy",
            price=5.0,
            quantity=2,
            type="limit",
            strike_price=200.0,
            osi_key="TSLA--231013C00200000",
        )

        assert order.asset_type == "option"
        assert order.strike_price == 200.0
        assert order.osi_key == "TSLA--231013C00200000"

    def test_order_defaults(self):
        """Order should have sensible defaults."""
        order = Order(
            asset_type="stock",
            symbol="MSFT",
            exchange="NASDAQ",
            side="sell",
            price=300.0,
            quantity=5,
            type="limit",
        )

        assert order.status == "open"
        assert order.fee == 0
        assert order.cost == 0

    def test_option_type_call(self):
        """Option type should correctly identify CALL options."""
        order = Order(
            asset_type="option",
            symbol="TSLA",
            exchange="CBOE",
            side="buy",
            price=5.0,
            quantity=1,
            type="limit",
            osi_key="TSLA--231013C00200000",
        )

        assert order.option_type() == "call"

    def test_option_type_put(self):
        """Option type should correctly identify PUT options."""
        order = Order(
            asset_type="option",
            symbol="AAPL",
            exchange="CBOE",
            side="buy",
            price=3.0,
            quantity=1,
            type="limit",
            osi_key="AAPL--231015P00150000",
        )

        assert order.option_type() == "put"


class TestMockOrderEngine:
    """Test MockOrderEngine for backtesting and simulation."""

    def test_place_stock_order(self):
        """Should place stock order and add to orders list."""
        engine = MockOrderEngine()

        order = engine.place(
            asset_type="stock",
            symbol="AAPL",
            side="buy",
            price=150.0,
            quantity=10,
            type="market",
        )

        assert order is not None
        assert order.symbol == "AAPL"
        assert order.status == "open"
        assert len(engine.orders) == 1

    def test_place_option_order_requires_strike_price(self):
        """Option order should require strike_price parameter."""
        engine = MockOrderEngine()

        with pytest.raises(ValueError, match="strike_price needs to be set for Option"):
            engine.place(
                asset_type="option",
                symbol="TSLA",
                side="buy",
                price=5.0,
                quantity=1,
                type="limit",
                # Missing strike_price!
            )

    def test_place_option_order_with_strike_price(self):
        """Option order with strike_price should succeed."""
        engine = MockOrderEngine()

        order = engine.place(
            asset_type="option",
            symbol="TSLA",
            side="buy",
            price=5.0,
            quantity=2,
            type="limit",
            strike_price=200.0,
            osi_key="TSLA--231013C00200000",
        )

        assert order is not None
        assert order.asset_type == "option"
        assert order.strike_price == 200.0
        assert len(engine.orders) == 1

    def test_find_order_existing(self):
        """Should find order by ID."""
        engine = MockOrderEngine()

        order = engine.place(
            asset_type="stock",
            symbol="MSFT",
            side="buy",
            price=300.0,
            quantity=5,
            type="market",
        )

        found = engine.find_order(order.id)

        assert found is not None
        assert found.id == order.id
        assert found.symbol == "MSFT"

    def test_find_order_nonexistent(self):
        """Should return None for non-existent order ID."""
        engine = MockOrderEngine()

        found = engine.find_order("fake-order-id")

        assert found is None

    def test_cancel_order(self):
        """Should cancel order and update status."""
        engine = MockOrderEngine()

        order = engine.place(
            asset_type="stock",
            symbol="AAPL",
            side="buy",
            price=150.0,
            quantity=10,
            type="limit",
        )

        result = engine.cancel(order.id)

        assert result == True
        assert order.status == "canceled"

    def test_cancel_nonexistent_order(self):
        """Canceling non-existent order should return False."""
        engine = MockOrderEngine()

        result = engine.cancel("fake-order-id")

        assert result == False

    def test_execute_stock_orders(self):
        """Should execute open stock orders and calculate cost."""
        engine = MockOrderEngine()

        order = engine.place(
            asset_type="stock",
            symbol="AAPL",
            side="buy",
            price=150.0,
            quantity=10,
            type="market",
        )

        executed = engine.execute_orders()

        assert len(executed) == 1
        assert order.status == "executed"
        assert order.executed_price == 150.0
        assert order.cost == 150.0  # price + fee (0)
        assert order.executed_at is not None

    def test_execute_option_orders(self):
        """Should execute option orders with correct cost (price * 100)."""
        engine = MockOrderEngine()

        order = engine.place(
            asset_type="option",
            symbol="TSLA",
            side="buy",
            price=5.0,
            quantity=1,
            type="limit",
            strike_price=200.0,
            osi_key="TSLA--231013C00200000",
        )

        executed = engine.execute_orders()

        assert len(executed) == 1
        assert order.status == "executed"
        assert order.cost == 500.0  # 5.0 * 100 + fee (0)

    def test_execute_only_open_orders(self):
        """Should only execute orders with status='open'."""
        engine = MockOrderEngine()

        order1 = engine.place(
            asset_type="stock",
            symbol="AAPL",
            side="buy",
            price=150.0,
            quantity=10,
            type="market",
        )

        order2 = engine.place(
            asset_type="stock",
            symbol="MSFT",
            side="buy",
            price=300.0,
            quantity=5,
            type="market",
        )

        # Cancel one order
        engine.cancel(order1.id)

        # Execute - should only execute order2
        executed = engine.execute_orders()

        assert len(executed) == 1
        assert executed[0].id == order2.id
        assert order1.status == "canceled"
        assert order2.status == "executed"

    def test_close_all_open_orders(self):
        """Should cancel all open orders."""
        engine = MockOrderEngine()

        order1 = engine.place(
            asset_type="stock",
            symbol="AAPL",
            side="buy",
            price=150.0,
            quantity=10,
            type="market",
        )

        order2 = engine.place(
            asset_type="stock",
            symbol="MSFT",
            side="buy",
            price=300.0,
            quantity=5,
            type="market",
        )

        engine.close_all_open_orders()

        assert order1.status == "canceled"
        assert order2.status == "canceled"

    def test_multiple_orders_tracking(self):
        """Should correctly track multiple orders."""
        engine = MockOrderEngine()

        orders = []
        for i in range(5):
            order = engine.place(
                asset_type="stock",
                symbol=f"STOCK{i}",
                side="buy",
                price=100.0 + i,
                quantity=10,
                type="market",
            )
            orders.append(order)

        assert len(engine.orders) == 5

        # Find each order
        for order in orders:
            found = engine.find_order(order.id)
            assert found is not None
            assert found.id == order.id


class TestOrderEngine:
    """Test OrderEngine wrapper/facade."""

    def test_create_mock_engine_default(self):
        """Should create MockOrderEngine by default."""
        engine = OrderEngine()

        assert engine.engine_name == "mock"
        assert isinstance(engine.engine, MockOrderEngine)

    def test_create_mock_engine_explicit(self):
        """Should create MockOrderEngine when specified."""
        engine = OrderEngine(engine_name="mock")

        assert engine.engine_name == "mock"
        assert isinstance(engine.engine, MockOrderEngine)

    def test_place_order_delegated(self):
        """OrderEngine.place should delegate to underlying engine."""
        engine = OrderEngine(engine_name="mock")

        order = engine.place(
            asset_type="stock",
            symbol="AAPL",
            side="buy",
            price=150.0,
            quantity=10,
            type="market",
        )

        assert order is not None
        assert order.symbol == "AAPL"

    def test_cancel_order_delegated(self):
        """OrderEngine.cancel should delegate to underlying engine."""
        engine = OrderEngine(engine_name="mock")

        order = engine.place(
            asset_type="stock",
            symbol="AAPL",
            side="buy",
            price=150.0,
            quantity=10,
            type="market",
        )

        result = engine.cancel(order.id)

        assert result == True
        assert order.status == "canceled"

    def test_execute_orders_delegated(self):
        """OrderEngine.execute_orders should delegate to MockOrderEngine."""
        engine = OrderEngine(engine_name="mock")

        order = engine.place(
            asset_type="stock",
            symbol="AAPL",
            side="buy",
            price=150.0,
            quantity=10,
            type="market",
        )

        executed = engine.execute_orders()

        assert len(executed) == 1
        assert order.status == "executed"

    def test_find_order_delegated(self):
        """OrderEngine.find_order should delegate to underlying engine."""
        engine = OrderEngine(engine_name="mock")

        order = engine.place(
            asset_type="stock",
            symbol="AAPL",
            side="buy",
            price=150.0,
            quantity=10,
            type="market",
        )

        found = engine.find_order(order.id)

        assert found is not None
        assert found.id == order.id

    def test_close_all_open_orders_delegated(self):
        """OrderEngine.close_all_open_orders should delegate."""
        engine = OrderEngine(engine_name="mock")

        order1 = engine.place(
            asset_type="stock",
            symbol="AAPL",
            side="buy",
            price=150.0,
            quantity=10,
            type="market",
        )

        order2 = engine.place(
            asset_type="stock",
            symbol="MSFT",
            side="buy",
            price=300.0,
            quantity=5,
            type="market",
        )

        engine.close_all_open_orders()

        assert order1.status == "canceled"
        assert order2.status == "canceled"


class TestOrderEngineEdgeCases:
    """Test edge cases and error conditions."""

    def test_execute_with_no_orders(self):
        """Executing with no orders should return empty list."""
        engine = MockOrderEngine()

        executed = engine.execute_orders()

        assert executed == []

    def test_execute_with_all_canceled(self):
        """Executing when all orders canceled should return empty list."""
        engine = MockOrderEngine()

        order1 = engine.place(
            asset_type="stock",
            symbol="AAPL",
            side="buy",
            price=150.0,
            quantity=10,
            type="market",
        )

        order2 = engine.place(
            asset_type="stock",
            symbol="MSFT",
            side="buy",
            price=300.0,
            quantity=5,
            type="market",
        )

        engine.cancel(order1.id)
        engine.cancel(order2.id)

        executed = engine.execute_orders()

        assert executed == []

    def test_double_execution(self):
        """Executing same orders twice should only execute open ones."""
        engine = MockOrderEngine()

        order = engine.place(
            asset_type="stock",
            symbol="AAPL",
            side="buy",
            price=150.0,
            quantity=10,
            type="market",
        )

        # First execution
        executed1 = engine.execute_orders()
        assert len(executed1) == 1
        assert order.status == "executed"

        # Second execution - should find no open orders
        executed2 = engine.execute_orders()
        assert len(executed2) == 0

    def test_cancel_already_executed_order(self):
        """Should handle canceling already executed order gracefully."""
        engine = MockOrderEngine()

        order = engine.place(
            asset_type="stock",
            symbol="AAPL",
            side="buy",
            price=150.0,
            quantity=10,
            type="market",
        )

        # Execute order
        engine.execute_orders()
        assert order.status == "executed"

        # Try to cancel (order already executed, but cancel should still work)
        result = engine.cancel(order.id)
        assert result == True
        assert order.status == "canceled"  # Status updated even though it was executed


class TestOrderCostCalculations:
    """Test cost calculations for different order types."""

    def test_stock_order_cost_calculation(self):
        """Stock order cost = price + fee."""
        engine = MockOrderEngine()

        order = engine.place(
            asset_type="stock",
            symbol="AAPL",
            side="buy",
            price=150.50,
            quantity=10,
            type="market",
        )

        engine.execute_orders()

        # Stock cost = price + fee
        assert order.cost == 150.50  # 150.50 + 0 (no fee)

    def test_option_order_cost_calculation(self):
        """Option order cost = price * 100 + fee."""
        engine = MockOrderEngine()

        order = engine.place(
            asset_type="option",
            symbol="TSLA",
            side="buy",
            price=5.75,
            quantity=1,
            type="limit",
            strike_price=200.0,
            osi_key="TSLA--231013C00200000",
        )

        engine.execute_orders()

        # Option cost = price * 100 + fee
        assert order.cost == 575.0  # 5.75 * 100 + 0 (no fee)

    def test_multiple_option_contracts_cost(self):
        """Cost calculation should account for option multiplier (100 shares/contract)."""
        engine = MockOrderEngine()

        order = engine.place(
            asset_type="option",
            symbol="AAPL",
            side="buy",
            price=10.0,
            quantity=3,  # 3 contracts
            type="limit",
            strike_price=150.0,
            osi_key="AAPL--231015C00150000",
        )

        engine.execute_orders()

        # Cost per contract = 10.0 * 100 = 1000
        # But we store cost per unit in order, so it's still 10.0 * 100
        assert order.cost == 1000.0
