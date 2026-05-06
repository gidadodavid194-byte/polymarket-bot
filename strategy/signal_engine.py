"""
strategy/signal_engine.py
─────────────────────────
The antigravity signal engine.
Finds markets where the price has dropped or spiked too far
and bets it will snap back to its true probability.
That's the core antigravity / mean-reversion strategy.
"""

import numpy as np
from loguru import logger
from dataclasses import dataclass
from typing import Optional


@dataclass
class Signal:
    market_id: str
    token_id: str
    question: str
    current_price: float
    fair_price: float
    edge: float
    direction: str        # "BUY" or "SELL"
    confidence: float
    reason: str


class SignalEngine:
    def __init__(self, min_edge: float = 0.03):
        self.min_edge = min_edge
        self.price_history = {}   # market_id -> list of past prices
        self.history_size = 20    # how many prices to remember

    def update_price_history(self, market_id: str, price: float):
        """Store price history for each market."""
        if market_id not in self.price_history:
            self.price_history[market_id] = []
        self.price_history[market_id].append(price)
        # Keep only the last N prices
        if len(self.price_history[market_id]) > self.history_size:
            self.price_history[market_id].pop(0)

    def calculate_fair_price(self, market_id: str, current_price: float) -> Optional[float]:
        """
        Calculate what we think the TRUE price should be.
        Uses the moving average of recent prices as our estimate
        of fair value. If current price is far from the average,
        that's our trading opportunity.
        """
        history = self.price_history.get(market_id, [])

        if len(history) < 5:
            # Not enough history yet
            return None

        # Fair price = average of recent prices
        fair_price = float(np.mean(history))
        return fair_price

    def calculate_edge(self, current_price: float, fair_price: float, direction: str) -> float:
        """
        Edge = how much we expect to profit per dollar risked.
        BUY edge:  fair_price - current_price  (we buy cheap)
        SELL edge: current_price - fair_price  (we sell expensive)
        """
        if direction == "BUY":
            return fair_price - current_price
        else:
            return current_price - fair_price

    def calculate_confidence(self, history: list, edge: float) -> float:
        """
        Confidence score between 0 and 1.
        Higher when: edge is large, price history is stable,
        and the current price is a clear outlier.
        """
        if len(history) < 5:
            return 0.0

        std = float(np.std(history))
        if std == 0:
            return 0.0

        # How many standard deviations away is the current price?
        z_score = abs(edge) / std

        # Confidence rises with z-score but caps at 1.0
        confidence = min(z_score / 3.0, 1.0)
        return round(confidence, 3)

    def analyse_market(self, market: dict) -> Optional[Signal]:
        """
        Analyse one market and return a Signal if there's an opportunity,
        or None if the market looks fairly priced.
        """
        market_id    = market["market_id"]
        token_id     = market["token_id"]
        question     = market["question"]
        current_price = market["price"]
        volume_24h   = market.get("volume_24h", 0)

        # Skip very low volume markets — hard to trade
        if volume_24h < 1000:
            return None

        # Skip markets priced at extremes — nearly resolved
        if current_price < 0.02 or current_price > 0.98:
            return None

        # Update our price memory
        self.update_price_history(market_id, current_price)

        # Calculate fair price from history
        fair_price = self.calculate_fair_price(market_id, current_price)
        if fair_price is None:
            return None

        # Determine direction
        if current_price < fair_price:
            direction = "BUY"    # price dropped too low — buy expecting recovery
        else:
            direction = "SELL"   # price spiked too high — sell expecting drop

        # Calculate edge
        edge = self.calculate_edge(current_price, fair_price, direction)

        # Skip if edge is too small
        if edge < self.min_edge:
            return None

        # Calculate confidence
        history = self.price_history.get(market_id, [])
        confidence = self.calculate_confidence(history, edge)

        # Skip low confidence signals
        if confidence < 0.3:
            return None

        reason = (
            f"Price {current_price:.3f} vs fair {fair_price:.3f} "
            f"— {direction} signal with {edge*100:.1f}% edge"
        )

        logger.info(f"Signal found: {question[:50]} | {reason}")

        return Signal(
            market_id=market_id,
            token_id=token_id,
            question=question,
            current_price=current_price,
            fair_price=fair_price,
            edge=edge,
            direction=direction,
            confidence=confidence,
            reason=reason,
        )

    def scan_markets(self, markets: list) -> list[Signal]:
        """
        Scan all markets and return all valid signals found.
        """
        signals = []
        for market in markets:
            signal = self.analyse_market(market)
            if signal:
                signals.append(signal)

        logger.info(f"Signal scan complete — {len(signals)} signals found from {len(markets)} markets")
        return signals