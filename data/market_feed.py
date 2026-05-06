"""
data/market_feed.py
───────────────────
Connects to Polymarket's API and fetches live market data.
"""

import aiohttp
import asyncio
import json
from loguru import logger


GAMMA_API = "https://gamma-api.polymarket.com"


class MarketFeed:
    def __init__(self):
        self.session = None

    async def start(self):
        self.session = aiohttp.ClientSession()
        logger.info("MarketFeed started")

    async def stop(self):
        if self.session:
            await self.session.close()
        logger.info("MarketFeed stopped")

    async def get_markets(self, limit=50):
        url = f"{GAMMA_API}/markets"
        params = {
            "active": "true",
            "closed": "false",
            "limit": limit,
            "order": "volume24hr",
            "ascending": "false"
        }
        try:
            async with self.session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.error(f"Failed to fetch markets: {resp.status}")
                    return []
                data = await resp.json()
                markets = data if isinstance(data, list) else data.get("markets", [])
                logger.info(f"Fetched {len(markets)} active markets")
                return markets
        except Exception as e:
            logger.error(f"Error fetching markets: {e}")
            return []

    def _parse_price(self, raw) -> float:
        """
        Safely parse a price value.
        Polymarket returns prices in many formats:
        - "0.65"
        - ["0.65", "0.35"]
        - 0.65
        """
        try:
            if isinstance(raw, (int, float)):
                return float(raw)
            if isinstance(raw, str):
                cleaned = raw.strip().strip("[]").split(",")[0].strip().strip("'\"")
                return float(cleaned)
            if isinstance(raw, list) and len(raw) > 0:
                return float(str(raw[0]).strip().strip("'\""))
        except Exception:
            pass
        return 0.0

    async def scan_all_markets(self):
        markets = await self.get_markets(limit=50)
        results = []

        for market in markets:
            try:
                question     = market.get("question", "Unknown")
                condition_id = market.get("conditionId") or market.get("condition_id", "")
                volume       = float(market.get("volume24hr") or market.get("volume") or 0)

                # ── Get YES price ──────────────────────────────
                yes_price = 0.0

                # Method 1: outcomePrices field
                outcome_prices = market.get("outcomePrices")
                if outcome_prices:
                    if isinstance(outcome_prices, list) and len(outcome_prices) > 0:
                        yes_price = self._parse_price(outcome_prices[0])
                    elif isinstance(outcome_prices, str):
                        yes_price = self._parse_price(outcome_prices)

                # Method 2: tokens list
                if yes_price <= 0:
                    tokens = market.get("tokens", [])
                    for t in tokens:
                        outcome = str(t.get("outcome", "")).lower()
                        if outcome == "yes":
                            yes_price = self._parse_price(
                                t.get("price") or t.get("lastTradePrice") or 0
                            )
                            break
                    if yes_price <= 0 and tokens:
                        yes_price = self._parse_price(
                            tokens[0].get("price") or tokens[0].get("lastTradePrice") or 0
                        )

                # Method 3: bestAsk / bestBid midpoint
                if yes_price <= 0:
                    best_ask = self._parse_price(market.get("bestAsk", 0))
                    best_bid = self._parse_price(market.get("bestBid", 0))
                    if best_ask > 0 and best_bid > 0:
                        yes_price = (best_ask + best_bid) / 2

                if yes_price <= 0 or yes_price >= 1:
                    continue

                # ── Get token ID ───────────────────────────────
                token_id = ""
                tokens = market.get("tokens", [])
                if tokens:
                    yes_token = next(
                        (t for t in tokens if str(t.get("outcome","")).lower() == "yes"),
                        tokens[0]
                    )
                    token_id = (
                        yes_token.get("token_id") or
                        yes_token.get("tokenId") or ""
                    )

                results.append({
                    "market_id":  condition_id,
                    "token_id":   token_id,
                    "question":   question,
                    "price":      yes_price,
                    "volume_24h": volume,
                    "end_date":   market.get("endDate", ""),
                })

            except Exception as e:
                logger.warning(f"Skipping market: {e}")
                continue

        logger.info(f"Scanned {len(results)} markets with prices")
        return results