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
from server import keep_alive, update_state, add_signal, add_trade, set_markets, get_manual_orders


async def main():
    # ── Start Flask status server ─────────────────────────────
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

    # Push initial state to dashboard
    update_state(
        mode=mode,
        running=True,
        balance=starting_balance,
        day_pnl=0.0,
    )

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

            # ── Check if bot is still allowed to trade ────────
            if not risk.bot_running:
                logger.warning(f"Bot halted: {risk.halt_reason}")
                update_state(
                    running=False,
                    halt_reason=risk.halt_reason,
                )
                await asyncio.sleep(60)
                continue

            # Step 1 — Fetch live market data ──────────────────
            markets = await feed.scan_all_markets()
            if not markets:
                logger.warning("No markets returned — retrying next scan")
                await asyncio.sleep(config.scan_interval_seconds)
                continue

            # ── Push live market data + scan progress to dashboard ─
            set_markets(markets)
            risk_status = risk.get_status()
            update_state(
                scan_count=scan_count,
                markets_scanned=len(markets),
                balance=risk_status["current_balance"],
                day_pnl=risk_status["total_pnl"],
                trades_today=risk_status["trades_placed"],
                win_rate=risk_status["win_rate"],
                running=risk.bot_running,
                halt_reason=risk.halt_reason,
            )

            # Step 2 — Find signals ────────────────────────────
            signals = engine.scan_markets(markets)

            if not signals:
                logger.info("No signals this scan — waiting...")
            else:
                logger.info(f"{len(signals)} signal(s) found — evaluating...")

            # Step 3 — Place trades for valid signals ──────────
            for signal in signals:
                # Push signal to dashboard immediately
                add_signal(signal)

                # Check risk manager allows this trade
                trade_size_usdc = signal.edge * config.max_trade_size_usdc
                allowed, reason = risk.check_trade_allowed(trade_size_usdc)
                if not allowed:
                    logger.warning(f"Trade blocked: {reason}")
                    continue

                # Send signal alert to Telegram
                await alerts.send_signal(signal)

                # Place the order
                order = await orders.place_order(signal)
                if order:
                    # Simulate simple PnL in paper mode:
                    # assume we exit at fair price → pnl = edge * size
                    simulated_pnl = round(signal.edge * order.size_usdc, 4)
                    order.pnl = simulated_pnl

                    # Record in risk manager
                    risk.record_trade(order.size_usdc, simulated_pnl)

                    # Update balance in risk manager
                    new_balance = (
                        risk_status["current_balance"] + simulated_pnl
                    )
                    risk.update_balance(new_balance)

                    # Push trade to dashboard
                    add_trade(order, pnl=simulated_pnl)

                    # Refresh risk status snapshot after trade
                    risk_status = risk.get_status()
                    update_state(
                        balance=risk_status["current_balance"],
                        day_pnl=risk_status["total_pnl"],
                        trades_today=risk_status["trades_placed"],
                        win_rate=risk_status["win_rate"],
                    )

                    await alerts.send_trade_placed(order, config.paper_trading)

            # Step 4 — Process Manual Orders ───────────────────
            manual_orders = get_manual_orders()
            for mo in manual_orders:
                logger.info(f"Processing manual order: {mo}")
                order = await orders.place_manual_order(
                    market_id=mo.get("market_id", ""),
                    token_id=mo.get("token_id", ""),
                    direction=mo.get("direction", "BUY").upper(),
                    price=float(mo.get("price", 0.5)),
                    size_usdc=float(mo.get("size", 10.0)),
                    question=mo.get("question", "Manual Trade")
                )
                
                if order:
                    # Fake PnL for paper mode manual trades just to see it work
                    if config.paper_trading:
                        # Random small PnL for visual feedback in dashboard
                        import random
                        simulated_pnl = round(float(mo.get("size", 10.0)) * random.uniform(-0.1, 0.2), 4)
                        order.pnl = simulated_pnl
                        risk.record_trade(order.size_usdc, simulated_pnl)
                        new_balance = risk_status["current_balance"] + simulated_pnl
                        risk.update_balance(new_balance)
                        
                    add_trade(order, pnl=getattr(order, 'pnl', 0.0))
                    
                    # Refresh risk status snapshot after trade
                    risk_status = risk.get_status()
                    update_state(
                        balance=risk_status["current_balance"],
                        day_pnl=risk_status["total_pnl"],
                        trades_today=risk_status["trades_placed"],
                        win_rate=risk_status["win_rate"],
                    )

            # Step 5 — Print risk status every 5 scans ─────────
            if scan_count % 5 == 0:
                risk.print_status()

            # Step 6 — Send daily summary every 120 scans ──────
            if scan_count % 120 == 0:
                await alerts.send_daily_summary(risk.get_status())

            # Wait before next scan
            await asyncio.sleep(config.scan_interval_seconds)

    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        update_state(running=False)
        await alerts.send_daily_summary(risk.get_status())

    except Exception as exc:
        logger.exception(f"Unexpected error in main loop: {exc}")
        update_state(running=False, halt_reason=str(exc))
        try:
            await alerts.send_error(str(exc))
        except Exception:
            pass

    finally:
        await feed.stop()
        logger.info("Bot shut down cleanly")


if __name__ == "__main__":
    asyncio.run(main())