"""
monitoring/alerts.py
────────────────────
Sends real-time alerts to your Telegram phone.
You get notified instantly when:
- A trade is placed
- A trade is filled
- The bot is halted
- Daily summary is ready
"""

import asyncio
from loguru import logger
from telegram import Bot
from telegram.error import TelegramError


class AlertSystem:
    def __init__(self, config):
        self.config = config
        self.bot = None
        self.chat_id = config.telegram_chat_id
        self.enabled = bool(
            config.telegram_bot_token and
            config.telegram_bot_token != "your_telegram_bot_token_here"
        )

        if self.enabled:
            self.bot = Bot(token=config.telegram_bot_token)
            logger.info("Telegram alerts enabled")
        else:
            logger.warning("Telegram alerts disabled — add token to .env to enable")

    async def send(self, message: str):
        """Send a message to your Telegram."""
        if not self.enabled:
            logger.info(f"[ALERT - no telegram] {message}")
            return

        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode="HTML"
            )
        except TelegramError as e:
            logger.error(f"Failed to send Telegram alert: {e}")

    async def send_startup(self, paper_trading: bool):
        mode = "PAPER" if paper_trading else "LIVE"
        await self.send(
            f"🤖 <b>Polymarket Bot Started</b>\n"
            f"Mode: <b>{mode}</b>\n"
            f"Antigravity strategy active ✅"
        )

    async def send_signal(self, signal):
        emoji = "📈" if signal.direction == "BUY" else "📉"
        await self.send(
            f"{emoji} <b>Signal Found</b>\n"
            f"<b>{signal.question[:60]}</b>\n"
            f"Direction : {signal.direction}\n"
            f"Price     : {signal.current_price:.3f}\n"
            f"Fair value: {signal.fair_price:.3f}\n"
            f"Edge      : {signal.edge*100:.1f}%\n"
            f"Confidence: {signal.confidence*100:.0f}%"
        )

    async def send_trade_placed(self, order, paper: bool):
        mode = "PAPER" if paper else "LIVE"
        emoji = "🟢" if order.direction == "BUY" else "🔴"
        await self.send(
            f"{emoji} <b>Trade Placed [{mode}]</b>\n"
            f"Direction : {order.direction}\n"
            f"Size      : ${order.size_usdc:.2f} USDC\n"
            f"Price     : {order.price:.3f}\n"
            f"Market    : {order.market_id[:20]}..."
        )

    async def send_halt_alert(self, reason: str):
        await self.send(
            f"🚨 <b>BOT HALTED</b>\n"
            f"Reason: {reason}\n"
            f"No more trades will be placed today."
        )

    async def send_daily_summary(self, status: dict):
        pnl = status['total_pnl']
        emoji = "✅" if pnl >= 0 else "❌"
        await self.send(
            f"{emoji} <b>Daily Summary</b>\n"
            f"Balance   : ${status['current_balance']:.2f}\n"
            f"Day PnL   : ${pnl:+.2f}\n"
            f"Trades    : {status['trades_placed']}\n"
            f"Win rate  : {status['win_rate']*100:.1f}%\n"
            f"Traded    : ${status['total_traded_usdc']:.2f}"
        )

    async def send_error(self, error: str):
        await self.send(
            f"⚠️ <b>Bot Error</b>\n"
            f"{error}"
        )