"""
main.py
───────
The brain that connects everything.
Run this to start the bot:  py main.py
"""

import asyncio
from loguru import logger
from config import load_config
from data.market_feed import MarketFeed
from strategy.signal_engine import SignalEngine
from execution.order_manager import OrderManager
from monitoring.risk_manager import RiskManager
from monitoring.alerts import AlertSystem
from server import keep_alive

async def main(): 
    keep_alive()
    # ── Load config ───────────────────────────────────────────
    config = load_config()

    # ── Print startup banner ──────────────────────────────────
    mode = "PAPER" if config.paper_trading else "LIVE"
    logger.info("=" * 52)
    logger.info("  POLYMARKET ANTIGRAVITY BOT")
    logger.info(f"  Mode          : {mode}")
    logger.info(f"  Wallet        : {config.wallet_address[:10]}...")
    logger.info(f"  Max trade     : ${config.max_trade_size_usdc} USDC")
    logger.info(f"  Min edge      : {config.min_edge_threshold * 100:.1f}%")
    logger.info(f"  Scan interval : {config.scan_interval_seconds}s")
    logger.info(f"  Daily loss cap: {config.daily_loss_limit_pct * 100:.1f}%")
    logger.info("=" * 52)

    # ── Initialise all modules ────────────────────────────────
    feed    = MarketFeed()
    engine  = SignalEngine(min_edge=config.min_edge_threshold)
    orders  = OrderManager(config, paper_trading=config.paper_trading)
    risk    = RiskManager(config)
    alerts  = AlertSystem(config)

    # ── Start market feed ─────────────────────────────────────
    await feed.start()

    # ── Set starting balance ──────────────────────────────────
    # In paper mode we simulate $100 starting balance
    starting_balance = 100.0 if config.paper_trading else 0.0
    risk.set_starting_balance(starting_balance)

    # ── Send startup alert to Telegram ────────────────────────
    await alerts.send_startup(config.paper_trading)

    logger.info("Bot is running. Scanning markets every "
                f"{config.scan_interval_seconds} seconds...")
    logger.info("Press Ctrl+C to stop.\n")

    # ── Main loop ─────────────────────────────────────────────
    scan_count = 0
    try:
        while True:
            scan_count += 1
            logger.info(f"─── Scan #{scan_count} ───────────────────────")

            # Check if bot is still allowed to trade
            if not risk.bot_running:
                logger.warning(f"Bot halted: {risk.halt_reason}")
                await asyncio.sleep(60)
                continue

            # Step 1 — Fetch live market data
            markets = await feed.scan_all_markets()
            if not markets:
                logger.warning("No markets returned — retrying next scan")
                await asyncio.sleep(config.scan_interval_seconds)
                continue

            # Step 2 — Find signals
            signals = engine.scan_markets(markets)

            if not signals:
                logger.info("No signals this scan — waiting...")
            else:
                logger.info(f"{len(signals)} signal(s) found — evaluating...")

            # Step 3 — Place trades for valid signals
            for signal in signals:
                # Check risk manager allows this trade
                allowed, reason = risk.check_trade_allowed(
                    signal.edge * config.max_trade_size_usdc
                )
                if not allowed:
                    logger.warning(f"Trade blocked: {reason}")
                    continue

                # Send signal alert to Telegram
                await alerts.send_signal(signal)

                # Place the order
                order = await orders.place_order(signal)
                if order:
                    await alerts.send_trade_placed(order, config.paper_trading)

            # Step 4 — Print risk status every 5 scans
            if scan_count % 5 == 0:
                risk.print_status()

            # Step 5 — Send daily summary every 120 scans
            if scan_count % 120 == 0:
                await alerts.send_daily_summary(risk.get_status())

            # Wait before next scan
            await asyncio.sleep(config.scan_interval_seconds)

    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        await alerts.send_daily_summary(risk.get_status())

    finally:
        await feed.stop()
        logger.info("Bot shut down cleanly")


if __name__ == "__main__":
    asyncio.run(main())