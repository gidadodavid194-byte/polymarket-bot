"""
execution/order_manager.py
──────────────────────────
Places, tracks and cancels orders on Polymarket
via the official py-clob-client library.
In PAPER_TRADING mode it simulates orders without
touching real money.
"""

import asyncio
from loguru import logger
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass
class Order:
    market_id: str
    token_id: str
    direction: str        # "BUY" or "SELL"
    price: float
    size_usdc: float
    status: str = "PENDING"   # PENDING, FILLED, CANCELLED, FAILED
    order_id: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    filled_at: Optional[str] = None
    pnl: Optional[float] = None


class OrderManager:
    def __init__(self, config, paper_trading: bool = True):
        self.config = config
        self.paper_trading = paper_trading
        self.open_orders: list[Order] = []
        self.filled_orders: list[Order] = []
        self.client = None

        if paper_trading:
            logger.info("OrderManager running in PAPER TRADING mode")
        else:
            logger.info("OrderManager running in LIVE mode")
            self._init_client()

    def _init_client(self):
        """
        Initialise the real Polymarket CLOB client.
        Only runs when PAPER_TRADING=false.
        """
        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.constants import POLYGON

            self.client = ClobClient(
                host=self.config.clob_api_url,
                key=self.config.private_key,
                chain_id=POLYGON,
            )
            logger.info("CLOB client initialised successfully")

        except Exception as e:
            logger.error(f"Failed to initialise CLOB client: {e}")
            self.client = None

    def calculate_position_size(self, edge: float, confidence: float) -> float:
        """
        Kelly Criterion position sizing.
        Sizes each trade based on our edge and confidence.
        Never risks more than max_trade_size_usdc.

        Kelly formula: f = edge / odds
        We use a fractional Kelly (25%) to be conservative.
        """
        if edge <= 0 or confidence <= 0:
            return 0.0

        # Fractional Kelly — use 25% of full Kelly
        kelly_fraction = 0.25
        full_kelly = edge * confidence
        size = full_kelly * kelly_fraction * self.config.max_trade_size_usdc

        # Hard cap at max trade size
        size = min(size, self.config.max_trade_size_usdc)

        # Minimum trade size of $1
        if size < 1.0:
            return 0.0

        return round(size, 2)

    async def place_order(self, signal) -> Optional[Order]:
        """
        Place a trade based on a signal from the signal engine.
        In paper mode: simulates the order.
        In live mode: sends a real order to Polymarket.
        """
        size = self.calculate_position_size(signal.edge, signal.confidence)
        if size <= 0:
            logger.warning(f"Position size too small for {signal.question[:40]} — skipping")
            return None

        order = Order(
            market_id=signal.market_id,
            token_id=signal.token_id,
            direction=signal.direction,
            price=signal.current_price,
            size_usdc=size,
        )

        if self.paper_trading:
            return await self._paper_order(order, signal)
        else:
            return await self._live_order(order, signal)

    async def _paper_order(self, order: Order, signal) -> Order:
        """Simulate an order without touching real money."""
        order.status = "FILLED"
        order.order_id = f"PAPER-{datetime.utcnow().timestamp()}"
        order.filled_at = datetime.utcnow().isoformat()

        self.filled_orders.append(order)

        logger.info(
            f"[PAPER] {order.direction} ${order.size_usdc:.2f} USDC "
            f"@ {order.price:.3f} | {signal.question[:50]}"
        )
        return order

    async def _live_order(self, order: Order, signal) -> Optional[Order]:
        """Place a real limit order on Polymarket."""
        if not self.client:
            logger.error("CLOB client not initialised — cannot place live order")
            return None

        try:
            from py_clob_client.clob_types import OrderArgs, OrderType

            order_args = OrderArgs(
                token_id=order.token_id,
                price=order.price,
                size=order.size_usdc,
                side="BUY" if order.direction == "BUY" else "SELL",
            )

            response = self.client.create_and_post_order(order_args)

            order.order_id = response.get("orderID")
            order.status = "PENDING"
            self.open_orders.append(order)

            logger.info(
                f"[LIVE] {order.direction} ${order.size_usdc:.2f} USDC "
                f"@ {order.price:.3f} | order_id={order.order_id}"
            )
            return order

        except Exception as e:
            order.status = "FAILED"
            logger.error(f"Failed to place live order: {e}")
            return None

    async def cancel_order(self, order: Order):
        """Cancel an open order."""
        if self.paper_trading:
            order.status = "CANCELLED"
            logger.info(f"[PAPER] Cancelled order {order.order_id}")
            return

        try:
            self.client.cancel(order.order_id)
            order.status = "CANCELLED"
            self.open_orders.remove(order)
            logger.info(f"[LIVE] Cancelled order {order.order_id}")
        except Exception as e:
            logger.error(f"Failed to cancel order {order.order_id}: {e}")

    def get_summary(self) -> dict:
        """Return a summary of all trading activity."""
        total_traded = sum(o.size_usdc for o in self.filled_orders)
        return {
            "open_orders": len(self.open_orders),
            "filled_orders": len(self.filled_orders),
            "total_traded_usdc": round(total_traded, 2),
        }