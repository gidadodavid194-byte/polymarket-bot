"""
server.py
─────────
Flask status server — keeps the dashboard alive on Render's free tier
and exposes live bot state via REST API.

Endpoints:
  GET /            — health-check string
  GET /health      — {"status": "alive"}
  GET /api/state   — full live bot state (balance, PnL, signals, trades …)
  GET /api/stats   — lightweight summary for polling dashboards
"""

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
from threading import Thread, Lock
from datetime import datetime
import os

app  = Flask(__name__)
CORS(app)

# ── Thread-safe state store ────────────────────────────────────────────────
_lock = Lock()

bot_state = {
    "running":         True,
    "mode":            "PAPER",
    "balance":         100.00,
    "day_pnl":         0.00,
    "trades_today":    0,
    "win_rate":        0.0,
    "scan_count":      0,
    "markets_scanned": 0,
    "signals":         [],
    "recent_trades":   [],
    "last_scan":       "",
    "halt_reason":     None,
}

_markets_data = []  # latest scanned markets from Gamma API


# ── Public helpers called by main.py ──────────────────────────────────────

def update_state(**kwargs):
    """Push any scalar fields into bot_state (thread-safe)."""
    with _lock:
        bot_state.update(kwargs)
        bot_state["last_scan"] = datetime.utcnow().strftime("%H:%M:%S UTC")


def add_signal(signal):
    """Prepend a new Signal to the signals list (keeps last 20)."""
    entry = {
        "question":   signal.question[:60],
        "direction":  signal.direction,
        "price":      round(signal.current_price, 4),
        "fair":       round(signal.fair_price, 4),
        "edge":       round(signal.edge * 100, 2),
        "confidence": round(signal.confidence * 100, 1),
        "reason":     signal.reason,
        "time":       datetime.utcnow().strftime("%H:%M:%S"),
    }
    with _lock:
        bot_state["signals"] = [entry] + bot_state["signals"][:19]


def add_trade(order, pnl: float = 0.0):
    """Prepend a filled order to recent_trades (keeps last 20)."""
    entry = {
        "direction": order.direction,
        "size":      round(order.size_usdc, 2),
        "price":     round(order.price, 4),
        "pnl":       round(pnl, 2),
        "status":    order.status,
        "time":      datetime.utcnow().strftime("%H:%M:%S"),
    }
    with _lock:
        bot_state["recent_trades"] = [entry] + bot_state["recent_trades"][:19]


def set_markets(markets_list):
    """Store latest scanned markets for dashboard display."""
    global _markets_data
    with _lock:
        _markets_data = markets_list[:100]


# ── Routes ────────────────────────────────────────────────────────────────

@app.route("/")
def home():
    return "Polymarket Antigravity Bot is running!"


@app.route("/dashboard")
def dashboard():
    """Serve the live trading dashboard."""
    return send_from_directory(os.path.dirname(__file__) or ".", "dashboard.html")


@app.route("/dashboard.css")
def dashboard_css():
    return send_from_directory(os.path.dirname(__file__) or ".", "dashboard.css")


@app.route("/dashboard.js")
def dashboard_js():
    return send_from_directory(os.path.dirname(__file__) or ".", "dashboard.js")


@app.route("/health")
def health():
    return jsonify({"status": "alive", "bot": "running"}), 200


@app.route("/api/state")
def state():
    with _lock:
        snapshot = dict(bot_state)
    return jsonify(snapshot), 200


@app.route("/api/stats")
def stats():
    """Lightweight summary for quick polling."""
    with _lock:
        snapshot = {
            "running":         bot_state["running"],
            "mode":            bot_state["mode"],
            "balance":         bot_state["balance"],
            "day_pnl":         bot_state["day_pnl"],
            "trades_today":    bot_state["trades_today"],
            "win_rate":        bot_state["win_rate"],
            "scan_count":      bot_state["scan_count"],
            "markets_scanned": bot_state["markets_scanned"],
            "last_scan":       bot_state["last_scan"],
        }
    return jsonify(snapshot), 200


@app.route("/api/markets")
def markets():
    """Return latest scanned live markets."""
    with _lock:
        data = list(_markets_data)
    return jsonify(data), 200


# ── Entry points ──────────────────────────────────────────────────────────

def run_server():
    app.run(host="0.0.0.0", port=8080, use_reloader=False)


def keep_alive():
    """Start the Flask server in a daemon thread so it doesn't block the bot."""
    t = Thread(target=run_server, name="flask-server")
    t.daemon = True
    t.start()