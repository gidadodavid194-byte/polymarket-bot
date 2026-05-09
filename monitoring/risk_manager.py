"""
monitoring/risk_manager.py
──────────────────────────
Protects your capital.
Monitors all positions and stops the bot automatically
if daily losses exceed your limit.
"""

from loguru import logger
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional


@dataclass
class DailyStats:
    date: str = field(default_factory=lambda: date.today().isoformat())
    starting_balance: float = 0.0
    current_balance: float = 0.0
    total_traded: float = 0.0
    total_pnl: float = 0.0
    trades_placed: int = 0
    trades_won: int = 0
    trades_lost: int = 0
    bot_halted: bool = False


class RiskManager:
    def __init__(self, config):
        self.config = config
        self.stats = DailyStats()
        self.bot_running = True
        self.halt_reason: Optional[str] = None

    def set_starting_balance(self, balance: float):
        """Call this once at bot startup with your current USDC balance."""
        self.stats.starting_balance = balance
        self.stats.current_balance = balance
        logger.info(f"Starting balance set: ${balance:.2f} USDC")

    def update_balance(self, new_balance: float):
        """Update current balance and check risk limits."""
        self.stats.current_balance = new_balance
        self._check_daily_loss_limit()

    def record_trade(self, size_usdc: float, pnl: float):
        """Record a completed trade's result and update running balance."""
        self.stats.trades_placed += 1
        self.stats.total_traded += size_usdc
        self.stats.total_pnl += pnl
        self.stats.current_balance += pnl   # keep balance in sync with PnL

        if pnl > 0:
            self.stats.trades_won += 1
        else:
            self.stats.trades_lost += 1

        logger.info(
            f"Trade recorded — PnL: ${pnl:+.2f} | "
            f"Day total: ${self.stats.total_pnl:+.2f} | "
            f"Balance: ${self.stats.current_balance:.2f}"
        )

    def _check_daily_loss_limit(self):
        """
        Halt the bot if we've lost too much today.
        Daily loss limit is set in your .env file.
        """
        if self.stats.starting_balance <= 0:
            return

        loss_pct = (
            self.stats.starting_balance - self.stats.current_balance
        ) / self.stats.starting_balance

        if loss_pct >= self.config.daily_loss_limit_pct:
            reason = (
                f"Daily loss limit hit — lost "
                f"{loss_pct*100:.1f}% of starting balance "
                f"(limit is {self.config.daily_loss_limit_pct*100:.1f}%)"
            )
            self.halt_bot(reason)

    def check_trade_allowed(self, size_usdc: float) -> tuple[bool, str]:
        """
        Check if a new trade is allowed.
        Returns (allowed, reason).
        """
        # Bot halted
        if not self.bot_running:
            return False, f"Bot halted: {self.halt_reason}"

        # Trade too large
        if size_usdc > self.config.max_trade_size_usdc:
            return False, f"Trade size ${size_usdc:.2f} exceeds max ${self.config.max_trade_size_usdc:.2f}"

        # Not enough balance
        if size_usdc > self.stats.current_balance:
            return False, f"Insufficient balance — need ${size_usdc:.2f}, have ${self.stats.current_balance:.2f}"

        return True, "OK"

    def halt_bot(self, reason: str):
        """Stop the bot from placing any more trades."""
        self.bot_running = False
        self.halt_reason = reason
        self.stats.bot_halted = True
        logger.critical(f"BOT HALTED — {reason}")

    def resume_bot(self):
        """Manually resume the bot after a halt."""
        self.bot_running = True
        self.halt_reason = None
        self.stats.bot_halted = False
        logger.info("Bot resumed manually")

    def reset_daily_stats(self):
        """Call this at midnight to reset daily tracking."""
        logger.info(f"Daily stats reset — previous day PnL: ${self.stats.total_pnl:+.2f}")
        self.stats = DailyStats(
            starting_balance=self.stats.current_balance,
            current_balance=self.stats.current_balance,
        )

    def get_status(self) -> dict:
        """Return current risk status as a dictionary."""
        win_rate = 0.0
        if self.stats.trades_placed > 0:
            win_rate = self.stats.trades_won / self.stats.trades_placed

        return {
            "bot_running":       self.bot_running,
            "halt_reason":       self.halt_reason,
            "starting_balance":  self.stats.starting_balance,
            "current_balance":   self.stats.current_balance,
            "total_pnl":         round(self.stats.total_pnl, 2),
            "trades_placed":     self.stats.trades_placed,
            "win_rate":          round(win_rate, 3),
            "total_traded_usdc": round(self.stats.total_traded, 2),
            "date":              self.stats.date,
        }

    def print_status(self):
        """Print a clean status report to the terminal."""
        s = self.get_status()
        logger.info("─" * 50)
        logger.info(f"  Bot running    : {s['bot_running']}")
        logger.info(f"  Balance        : ${s['current_balance']:.2f}")
        logger.info(f"  Day PnL        : ${s['total_pnl']:+.2f}")
        logger.info(f"  Trades today   : {s['trades_placed']}")
        logger.info(f"  Win rate       : {s['win_rate']*100:.1f}%")
        logger.info(f"  Total traded   : ${s['total_traded_usdc']:.2f}")
        logger.info("─" * 50)