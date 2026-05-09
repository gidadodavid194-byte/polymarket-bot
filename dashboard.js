// ── Config ────────────────────────────────────────────
const BOT_URL = 'https://polymarket-bot-4zuw.onrender.com';
const POLL_BOT = 15000;   // poll bot every 15s
const POLL_MKT = 20000;   // poll markets every 20s

// ── State ─────────────────────────────────────────────
let botState = null;
let liveMarkets = [];
let selectedMkt = null;
let connected = false;
let chart = null;
let priceHist = {};  // market_id -> {prices:[], labels:[]}
let activityCount = 0;
let lastScan = -1;
let modalAction = 'BUY'; // 'BUY' or 'SELL'

// ── Clock ─────────────────────────────────────────────
function updateClock() {
  document.getElementById('clock').textContent =
    new Date().toUTCString().slice(17, 25) + ' UTC';
}
setInterval(updateClock, 1000);
updateClock();

// ── Tabs ──────────────────────────────────────────────
function switchTab(name, btn) {
  document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
  document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
  document.getElementById('tab-' + name).classList.remove('hidden');
  btn.classList.add('active');
}

// ── Chart ─────────────────────────────────────────────
function initChart() {
  const ctx = document.getElementById('priceChart').getContext('2d');
  chart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: [],
      datasets: [{
        label: 'YES Price',
        data: [],
        borderColor: '#00ff88',
        backgroundColor: 'rgba(0,255,136,.04)',
        borderWidth: 1.5,
        pointRadius: 0,
        fill: true,
        tension: 0.3,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 300 },
      plugins: { legend: { display: false } },
      scales: {
        x: { display: false },
        y: {
          grid: { color: 'rgba(15,37,53,.6)' },
          ticks: {
            color: '#1e3a4a',
            font: { family: 'IBM Plex Mono', size: 9 },
            callback: v => (v * 100).toFixed(0) + '%'
          },
          min: 0, max: 1
        }
      }
    }
  });
}

function selectMarket(mkt) {
  selectedMkt = mkt;
  document.getElementById('chartTitle').textContent = mkt.question || 'Unknown';
  document.getElementById('chartPrice').textContent = (mkt.price || 0).toFixed(3);
  const vol = parseFloat(mkt.volume_24h || 0);
  document.getElementById('chartMeta').textContent =
    'Vol $' + (vol >= 1000 ? (vol/1000).toFixed(1)+'k' : vol.toFixed(0));

  // Track price
  const id = mkt.market_id;
  if (!priceHist[id]) priceHist[id] = { prices: [], labels: [] };
  const h = priceHist[id];
  h.prices.push(mkt.price);
  h.labels.push(new Date().toUTCString().slice(17, 25));
  if (h.prices.length > 80) { h.prices.shift(); h.labels.shift(); }

  chart.data.labels = h.labels;
  chart.data.datasets[0].data = h.prices;
  chart.update('none');

  // highlight selected row
  document.querySelectorAll('.mkt-row').forEach(r => r.classList.remove('selected'));
  const row = document.querySelector(`[data-mid="${id}"]`);
  if (row) row.classList.add('selected');

  // Load history from CLOB API
  if (mkt.token_id) loadMarketHistory(mkt.token_id, id);
}

async function loadMarketHistory(tokenId, marketId) {
  try {
    const res = await fetch(`https://clob.polymarket.com/prices-history?market=${tokenId}&interval=1d&fidelity=60`);
    if (!res.ok) return;
    const data = await res.json();
    if (data.history && data.history.length > 0) {
      const h = { prices: [], labels: [] };
      data.history.forEach(pt => {
        h.prices.push(pt.p);
        const d = new Date(pt.t * 1000);
        h.labels.push(d.toUTCString().slice(17, 25));
      });
      priceHist[marketId] = h;
      
      if (selectedMkt && selectedMkt.market_id === marketId) {
        chart.data.labels = h.labels;
        chart.data.datasets[0].data = h.prices;
        chart.update('none');
      }
    }
  } catch(e) {
    console.error("Failed to load history", e);
  }
}

// ── Trade Modal ───────────────────────────────────────
function openTradeModal() {
  if (!selectedMkt) return alert("Select a market first");
  document.getElementById('modalMktName').textContent = selectedMkt.question;
  document.getElementById('modalPrice').value = selectedMkt.price.toFixed(3);
  setModalAction('BUY');
  document.getElementById('tradeModal').classList.add('open');
}

function closeTradeModal() {
  document.getElementById('tradeModal').classList.remove('open');
}

function setModalAction(action) {
  modalAction = action;
  document.getElementById('modalBuyBtn').classList.toggle('active', action === 'BUY');
  document.getElementById('modalSellBtn').classList.toggle('active', action === 'SELL');
  const submitBtn = document.getElementById('modalSubmit');
  submitBtn.className = 'modal-btn confirm ' + (action === 'SELL' ? 'sell' : '');
  submitBtn.textContent = 'Confirm ' + action;
}

async function submitTrade() {
  if (!selectedMkt) return;
  const size = document.getElementById('modalSize').value;
  const price = document.getElementById('modalPrice').value;
  
  const payload = {
    market_id: selectedMkt.market_id,
    token_id: selectedMkt.token_id,
    question: selectedMkt.question,
    direction: modalAction,
    size: parseFloat(size),
    price: parseFloat(price)
  };

  try {
    const res = await fetch(BOT_URL + '/api/trade', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    addActivity(`Manual <b>${modalAction}</b> submitted for $${size} @ ${price}`, modalAction==='BUY'?'g':'r');
    closeTradeModal();
  } catch (e) {
    addActivity('Failed to submit manual trade: ' + e.message, 'r');
  }
}

// ── Render Live Markets ──────────────────────────────
function renderMarkets(markets) {
  const el = document.getElementById('mktList');
  if (!markets || !markets.length) {
    el.innerHTML = '<div class="empty-msg">No markets available</div>';
    return;
  }

  el.innerHTML = markets.map(m => {
    const price = parseFloat(m.price) || 0;
    const vol = parseFloat(m.volume_24h) || 0;
    const volStr = vol >= 1e6 ? '$' + (vol/1e6).toFixed(1) + 'M'
                 : vol >= 1e3 ? '$' + (vol/1e3).toFixed(1) + 'K'
                 : '$' + vol.toFixed(0);
    const q = (m.question || 'Unknown').replace(/"/g, '&quot;');
    const sel = selectedMkt && selectedMkt.market_id === m.market_id ? ' selected' : '';
    return `<div class="mkt-row${sel}" data-mid="${m.market_id}" onclick="selectMarket(${JSON.stringify(m).replace(/"/g, '&quot;')})">
      <div>
        <div class="mkt-name" title="${q}">${q}</div>
        <div class="price-bar"><div class="price-fill" style="width:${price*100}%"></div></div>
      </div>
      <div class="mkt-price">${price.toFixed(3)}<span style="color:var(--t2);font-weight:400;font-size:9px"> YES</span></div>
      <div class="mkt-vol">${volStr}</div>
      <div class="mkt-active">● Active</div>
    </div>`;
  }).join('');
}

// ── Render Signals ──────────────────────────────────
function renderSignals(sigs) {
  const el = document.getElementById('sigList');
  if (!sigs || !sigs.length) {
    el.innerHTML = '<div class="empty-msg">No signals — bot building price history (needs 5+ scans per market)…</div>';
    return;
  }
  el.innerHTML = sigs.map(s => {
    const isBuy = s.direction === 'BUY';
    return `<div class="sig-row ${isBuy ? 'buy' : 'sell'} flash">
      <div class="mkt-name" title="${s.question}">${s.question}</div>
      <div class="${isBuy ? 'dir-b' : 'dir-s'}">${s.direction}</div>
      <div style="color:var(--t2)">${s.price.toFixed(4)} <span style="color:var(--t3)">→</span> ${s.fair.toFixed(4)}</div>
      <div style="color:var(--green)">${s.edge}%</div>
      <div style="color:var(--t2)">${s.confidence}%</div>
      <div style="color:var(--t2);font-size:9px"><button class="trade-btn ${isBuy ? 'buy' : 'sell'}" onclick="prefillTrade()">${s.direction}</button></div>
    </div>`;
  }).join('');
}

function prefillTrade() {
  event.stopPropagation();
  alert("Please select the market from the Live Markets tab to trade manually.");
}

// ── Render Trades ────────────────────────────────────
function renderTrades(trades) {
  const el = document.getElementById('trdList');
  if (!trades || !trades.length) {
    el.innerHTML = '<div class="empty-msg">No trades yet — waiting for signals with sufficient edge</div>';
    return;
  }
  el.innerHTML = trades.map(t => {
    const isBuy = t.direction === 'BUY';
    const pnlClass = t.pnl >= 0 ? 'color:var(--green)' : 'color:var(--red)';
    return `<div class="trd-row flash">
      <div style="color:${isBuy ? 'var(--green)' : 'var(--red)'};font-weight:600">${t.direction}</div>
      <div style="color:var(--text)">$${t.size}</div>
      <div style="color:var(--text)">${t.price}</div>
      <div style="${pnlClass};font-weight:600">${t.pnl >= 0 ? '+' : ''}$${t.pnl}</div>
      <div style="color:var(--t2)">${t.status || 'FILLED'}</div>
      <div style="color:var(--t2);font-size:9px">${t.time || '—'}</div>
    </div>`;
  }).join('');
}

// ── Activity Feed ───────────────────────────────────
function addActivity(text, type) {
  type = type || 'b';
  const feed = document.getElementById('actFeed');
  // Clear empty msg on first entry
  if (activityCount === 0) feed.innerHTML = '';
  activityCount++;
  const div = document.createElement('div');
  div.className = 'act-item flash';
  div.innerHTML =
    `<div class="act-dot ${type}"></div>` +
    `<div><div class="act-text">${text}</div>` +
    `<div class="act-time">${new Date().toUTCString().slice(17, 25)} UTC</div></div>`;
  feed.insertBefore(div, feed.firstChild);
  while (feed.children.length > 50) feed.removeChild(feed.lastChild);
}

// ── Fetch live markets from Gamma API ───────────────
async function fetchGammaMarkets() {
  try {
    // Fetch from our own proxy — avoids CORS issues with Gamma API
    const r = await fetch(BOT_URL + '/api/markets', { mode: 'cors' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const markets = await r.json();

    if (!Array.isArray(markets) || markets.length === 0) {
      // Fallback: bot hasn't scanned yet — show waiting message
      document.getElementById('mktList').innerHTML =
        '<div class="empty-msg">Bot is starting — waiting for first market scan…</div>';
      return;
    }

    liveMarkets = markets;

    renderMarkets(liveMarkets);

    // Auto-select first market if none selected
    if (!selectedMkt && liveMarkets.length > 0) {
      selectMarket(liveMarkets[0]);
    } else if (selectedMkt) {
      // Update selected market price, do NOT trigger history load again
      const updated = liveMarkets.find(m => m.market_id === selectedMkt.market_id);
      if (updated) {
        document.getElementById('chartPrice').textContent = (updated.price || 0).toFixed(3);
      }
    }

    addActivity(`Fetched <b>${liveMarkets.length}</b> live markets from Polymarket`, 'g');
  } catch (e) {
    addActivity('Failed to fetch Gamma markets: ' + e.message, 'r');
  }
}

// ── Fetch bot state from our API ────────────────────
async function fetchBotState() {
  try {
    const r = await fetch(BOT_URL + '/api/state', { mode: 'cors' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    botState = await r.json();

    if (!connected) {
      connected = true;
      document.getElementById('connBadge').className = 'badge badge-live';
      document.getElementById('connTxt').textContent = 'LIVE';
      addActivity('Connected to bot API', 'g');
    }

    // Mode
    const mode = botState.mode || 'PAPER';
    document.getElementById('modeBadge').textContent =
      (mode === 'PAPER' ? '⚠ ' : '● ') + mode;

    // Halt
    const hb = document.getElementById('haltBanner');
    if (!botState.running && botState.halt_reason) {
      hb.style.display = 'block';
      hb.textContent = '🚨 BOT HALTED — ' + botState.halt_reason;
      document.getElementById('botStatus').textContent = 'HALTED';
      document.getElementById('botStatus').className = 'pb pb-r';
    } else {
      hb.style.display = 'none';
      document.getElementById('botStatus').textContent = 'RUNNING';
      document.getElementById('botStatus').className = 'pb pb-g';
    }

    // Metrics
    const bal = parseFloat(botState.balance) || 100;
    const pnl = parseFloat(botState.day_pnl) || 0;
    const trades = botState.trades_today || 0;
    const wr = parseFloat(botState.win_rate) || 0;

    document.getElementById('balance').textContent = '$' + bal.toFixed(2);
    const pe = document.getElementById('dayPnl');
    pe.textContent = (pnl >= 0 ? '+' : '-') + '$' + Math.abs(pnl).toFixed(2);
    pe.className = 'mv ' + (pnl >= 0 ? 'mv-a' : 'mv-r');
    document.getElementById('pnlSub').textContent = trades + ' trades today';
    document.getElementById('winRate').textContent =
      trades > 0 ? Math.round(wr * 100) + '%' : '—';

    // Top pills
    document.getElementById('tScan').textContent = botState.scan_count || 0;
    document.getElementById('tMkt').textContent = botState.markets_scanned || 0;
    document.getElementById('tSig').textContent = (botState.signals || []).length;
    document.getElementById('tTrd').textContent = trades;

    // Risk bars
    const lossPct = Math.abs(pnl) / Math.max(bal, 1) * 100;
    document.getElementById('lossVal').textContent = lossPct.toFixed(1) + '%';
    document.getElementById('lossBar').style.width = Math.min(lossPct * 20, 100) + '%';
    document.getElementById('lossBar').className =
      'rf ' + (lossPct > 4 ? 'rf-r' : lossPct > 2 ? 'rf-a' : 'rf-g');

    const sigs = botState.signals || [];
    if (sigs.length > 0) {
      const avgE = sigs.reduce((a, s) => a + parseFloat(s.edge), 0) / sigs.length;
      const avgC = sigs.reduce((a, s) => a + parseFloat(s.confidence), 0) / sigs.length;
      document.getElementById('edgeVal').textContent = avgE.toFixed(1) + '%';
      document.getElementById('edgeBar').style.width = Math.min(avgE * 10, 100) + '%';
      document.getElementById('confVal').textContent = avgC.toFixed(0) + '%';
      document.getElementById('confBar').style.width = Math.min(avgC, 100) + '%';
    }

    // Activity for new scans
    const sc = botState.scan_count || 0;
    if (sc !== lastScan) {
      lastScan = sc;
      addActivity(
        `Scan #${sc} — <b>${sigs.length}</b> signal(s), <b>${botState.markets_scanned || 0}</b> markets`,
        sigs.length > 0 ? 'g' : 'b'
      );
    }

    // Render signals & trades
    renderSignals(sigs);
    renderTrades(botState.recent_trades || []);

  } catch (e) {
    if (connected) {
      connected = false;
      document.getElementById('connBadge').className = 'badge badge-dead';
      document.getElementById('connTxt').textContent = 'RECONNECTING';
      addActivity('Bot connection lost — retrying…', 'r');
    }
  }
}

// ── Initialize ──────────────────────────────────────
initChart();
addActivity('Dashboard initialized — connecting to Polymarket & bot API…', 'b');
fetchGammaMarkets();
fetchBotState();
setInterval(fetchGammaMarkets, POLL_MKT);
setInterval(fetchBotState, POLL_BOT);
