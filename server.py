from flask import Flask, jsonify
from flask_cors import CORS
from threading import Thread
from datetime import datetime

app = Flask(__name__)
CORS(app)

bot_state = {
    "running": True,
    "mode": "PAPER",
    "balance": 100.00,
    "day_pnl": 0.00,
    "trades_today": 0,
    "win_rate": 0.0,
    "scan_count": 0,
    "signals": [],
    "recent_trades": [],
    "last_scan": "",
    "markets_scanned": 0,
}

@app.route('/')
def home():
    return 'Polymarket Antigravity Bot is running!'

@app.route('/health')
def health():
    return jsonify({"status": "alive", "bot": "running"}), 200

@app.route('/api/state')
def state():
    return jsonify(bot_state), 200

def update_state(**kwargs):
    bot_state.update(kwargs)
    bot_state["last_scan"] = datetime.utcnow().strftime("%H:%M:%S")

def add_signal(signal):
    bot_state["signals"] = [{
        "question": signal.question[:50],
        "direction": signal.direction,
        "price": round(signal.current_price, 3),
        "fair": round(signal.fair_price, 3),
        "edge": round(signal.edge * 100, 1),
        "confidence": round(signal.confidence * 100, 0),
    }] + bot_state["signals"][:19]

def add_trade(order, pnl=0):
    bot_state["recent_trades"] = [{
        "direction": order.direction,
        "size": round(order.size_usdc, 2),
        "price": round(order.price, 3),
        "pnl": round(pnl, 2),
        "time": datetime.utcnow().strftime("%H:%M:%S"),
    }] + bot_state["recent_trades"][:19]

def run_server():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run_server)
    t.daemon = True
    t.start()