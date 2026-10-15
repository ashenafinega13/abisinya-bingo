require('dotenv').config();
const express = require('express');
const http = require('http');
const cors = require('cors');
const mongoose = require('mongoose');
const { Server } = require('socket.io');
const path = require('path');
const crypto = require('crypto');
const axios = require('axios');

const User = require('./models/User');
const Transaction = require('./models/Transaction');
const Game = require('./models/Game');
const Cartela = require('./models/Cartela');

const app = express();
const server = http.createServer(app);
const io = new Server(server, {
  cors: { origin: '*' },
  pingTimeout: 30000,
  pingInterval: 10000
});

const PORT = process.env.PORT || 3000;
const BOT_API_SECRET = process.env.BOT_API_SECRET || 'change-me';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || 'admin123';
const BOT_CALLBACK_URL = process.env.BOT_CALLBACK_URL || '';

// Secret admin path — generated from ADMIN_PASSWORD hash.
// Nothing routes to /admin.html by default — only this path works.
const ADMIN_SECRET_PATH = (() => {
  const h = crypto.createHash('sha256').update('adm-' + ADMIN_PASSWORD).digest('hex');
  return '/admin-panel-' + h.slice(0, 20);
})();

app.use(cors());
app.use(express.json({ limit: '1mb' }));

const PUBLIC_DIR = path.join(__dirname, 'public');
console.log('📁 Static files:', PUBLIC_DIR);
console.log('👑 Admin secret path:', ADMIN_SECRET_PATH);

// Static — but BLOCK the plain /admin.html path from being reachable
app.get('/admin.html', (req, res) => res.status(404).send('Not found'));

// Serve admin.html ONLY at the secret path
app.get(ADMIN_SECRET_PATH, (req, res) => {
  res.sendFile(path.join(PUBLIC_DIR, 'admin.html'));
});

app.use(express.static(PUBLIC_DIR));

// =============================================================
//                       MONGO
// =============================================================
mongoose.connect(process.env.MONGODB_URI)
  .then(() => console.log('✅ MongoDB connected'))
  .catch(e => console.error('❌ Mongo error:', e.message));

// =============================================================
//                       ROUND ENGINE
// =============================================================
const DEFAULT_SELECTION_SECONDS = 30;
const DEFAULT_CALL_INTERVAL_MS  = 4000;
const BETWEEN_ROUNDS_MS         = 8000;
const CARTELA_COUNT             = 600;
const DEFAULT_ENTRY_FEE         = 10;
const DEFAULT_PRIZE_PERCENT     = 0.8;

const state = {
  roundId: 0,
  phase: 'selection',
  selectionEndsAt: 0,
  calledNumbers: [],
  currentCall: null,
  players: new Map(),
  takenCartelas: new Set(),
  prizePool: 0,
  winner: null,
  cartelas: [],
  callTimer: null,
  phaseTimer: null,
  roundHistory: [],

  entryFee: DEFAULT_ENTRY_FEE,
  prizePct: DEFAULT_PRIZE_PERCENT,
  selectionSeconds: DEFAULT_SELECTION_SECONDS,
  callIntervalMs: DEFAULT_CALL_INTERVAL_MS
};

function generateCartela(cartelaId) {
  const cols = [];
  for (let c = 0; c < 5; c++) {
    const min = c * 15 + 1;
    const pool = Array.from({ length: 15 }, (_, i) => min + i);
    for (let i = pool.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [pool[i], pool[j]] = [pool[j], pool[i]];
    }
    cols.push(pool.slice(0, 5));
  }
  const grid = [];
  for (let r = 0; r < 5; r++) {
    const row = [];
    for (let c = 0; c < 5; c++) row.push(cols[c][r]);
    grid.push(row);
  }
  grid[2][2] = 0;
  return { id: cartelaId, grid };
}

console.log('🎴 Generating cartelas…');
for (let id = 1; id <= CARTELA_COUNT; id++) state.cartelas.push(generateCartela(id));
console.log(`✅ ${CARTELA_COUNT} cartelas ready`);

function letterOf(n) {
  if (n <= 15) return 'B';
  if (n <= 30) return 'I';
  if (n <= 45) return 'N';
  if (n <= 60) return 'G';
  return 'O';
}

// =============================================================
//               WIN PATTERN CHECKER (NEW)
// =============================================================
// Returns { win: true, pattern: "row:2" | "col:3" | "diag:main" | "diag:anti" }
// Center (2,2) is FREE — auto-marked.
function evaluateWin(cartela, calledSet) {
  if (!cartela) return null;
  const g = cartela.grid;

  // ---- rows ----
  for (let r = 0; r < 5; r++) {
    let ok = true;
    for (let c = 0; c < 5; c++) {
      const n = g[r][c];
      if (n !== 0 && !calledSet.has(n)) { ok = false; break; }
    }
    if (ok) return { pattern: `row:${r}` };
  }

  // ---- columns ----
  for (let c = 0; c < 5; c++) {
    let ok = true;
    for (let r = 0; r < 5; r++) {
      const n = g[r][c];
      if (n !== 0 && !calledSet.has(n)) { ok = false; break; }
    }
    if (ok) return { pattern: `col:${c}` };
  }

  // ---- main diagonal (TL → BR) ----
  let okMain = true;
  for (let i = 0; i < 5; i++) {
    const n = g[i][i];
    if (n !== 0 && !calledSet.has(n)) { okMain = false; break; }
  }
  if (okMain) return { pattern: 'diag:main' };

  // ---- anti diagonal (TR → BL) ----
  let okAnti = true;
  for (let i = 0; i < 5; i++) {
    const n = g[i][4 - i];
    if (n !== 0 && !calledSet.has(n)) { okAnti = false; break; }
  }
  if (okAnti) return { pattern: 'diag:anti' };

  return null;
}

function publicState() {
  return {
    roundId: state.roundId,
    phase: state.phase,
    selectionEndsAt: state.selectionEndsAt,
    entryFee: state.entryFee,
    currentCall: state.currentCall,
    calledNumbers: state.calledNumbers,
    prizePool: state.prizePool,
    playerCount: state.players.size,
    players: [...state.players.entries()].map(([uid, p]) => ({
      userId: uid,
      firstName: p.firstName,
      cartelas: p.cartelas,
      hasBingo: false
    })),
    takenCartelas: [...state.takenCartelas],
    winner: state.winner,
    roundHistory: state.roundHistory.slice(-5),
    cartelaCount: CARTELA_COUNT
  };
}
function broadcastState() { io.emit('game-state', publicState()); }

function startSelectionPhase() {
  state.phase = 'selection';
  state.selectionEndsAt = Date.now() + state.selectionSeconds * 1000;
  state.calledNumbers = [];
  state.currentCall = null;
  state.players = new Map();
  state.takenCartelas = new Set();
  state.prizePool = 0;
  state.winner = null;
  state.roundId++;
  clearTimeout(state.phaseTimer);
  clearInterval(state.callTimer);
  console.log(`🟢 Round ${state.roundId}: selection (${state.selectionSeconds}s)`);
  broadcastState();
  state.phaseTimer = setTimeout(startRunningPhase, state.selectionSeconds * 1000);
}

function startRunningPhase() {
  if (state.players.size === 0) {
    console.log('⏳ No players — extending selection');
    state.selectionEndsAt = Date.now() + state.selectionSeconds * 1000;
    broadcastState();
    state.phaseTimer = setTimeout(startRunningPhase, state.selectionSeconds * 1000);
    return;
  }
  state.phase = 'running';
  broadcastState();
  console.log(`▶️ Round ${state.roundId}: running (${state.players.size} players)`);
  clearInterval(state.callTimer);
  state.callTimer = setInterval(callNextNumber, state.callIntervalMs);
  setTimeout(callNextNumber, 1000);
}

function callNextNumber() {
  if (state.phase !== 'running') return;
  if (state.calledNumbers.length >= 75) return finishRound(null);
  let n;
  do { n = Math.floor(Math.random() * 75) + 1; }
  while (state.calledNumbers.includes(n));
  state.calledNumbers.push(n);
  state.currentCall = n;
  io.emit('number-called', { number: n, all: state.calledNumbers });
  broadcastState();
  console.log(`📞 ${letterOf(n)}-${n}`);
}

// Instant win check — which player(s) have a completed line right now
function findInstantWinners() {
  const calledSet = new Set(state.calledNumbers);
  calledSet.add(0);
  const winners = [];
  for (const [uid, player] of state.players.entries()) {
    for (const cid of player.cartelas) {
      const cartela = state.cartelas.find(c => c.id === cid);
      const w = evaluateWin(cartela, calledSet);
      if (w) {
        winners.push({
          userId: uid,
          firstName: player.firstName,
          cartelaId: cid,
          pattern: w.pattern
        });
      }
    }
  }
  return winners;
}

async function finishRound(winnerInfo) {
  state.phase = 'finished';
  clearInterval(state.callTimer);
  clearTimeout(state.phaseTimer);

  if (winnerInfo) {
    const prize = Math.floor(state.prizePool * state.prizePct);
    const winner = { ...winnerInfo, prize };
    state.winner = winner;
    state.roundHistory.push({ roundId: state.roundId, ...winner });

    try {
      await User.updateOne(
        { telegramId: winner.userId },
        { $inc: { winBalance: prize, totalWins: 1, totalEarnings: prize } }
      );
      await Transaction.create({
        userId: winner.userId,
        type: 'win',
        amount: prize,
        status: 'approved',
        method: 'game',
        gameId: state.roundId,
        cartelas: [winner.cartelaId],
        pattern: winner.pattern
      });
    } catch (e) { console.error('winner credit error:', e.message); }

    const wc = state.cartelas.find(c => c.id === winner.cartelaId);
    const winnerPayload = { ...winner, cartelaGrid: wc ? wc.grid : null };
    io.emit('round-finished', winnerPayload);

    if (BOT_CALLBACK_URL) {
      axios.post(`${BOT_CALLBACK_URL}/winner`, winner,
        { headers: { 'x-bot-secret': BOT_API_SECRET }, timeout: 8000 })
        .catch(() => {});
    }
    console.log(`🏆 ${winner.firstName} won ${prize} (${winner.pattern})`);
  } else {
    io.emit('round-finished', null);
    console.log('😐 No winner');
  }
  broadcastState();
  state.phaseTimer = setTimeout(startSelectionPhase, BETWEEN_ROUNDS_MS);
}

startSelectionPhase();

// =============================================================
//                       AUTH
// =============================================================
function botAuth(req, res, next) {
  if (req.headers['x-bot-secret'] !== BOT_API_SECRET)
    return res.status(403).json({ error: 'forbidden' });
  next();
}
function adminAuth(req, res, next) {
  if (req.headers['x-admin-pass'] !== ADMIN_PASSWORD)
    return res.status(403).json({ error: 'forbidden' });
  next();
}

// =============================================================
//                       LANDING
// =============================================================
app.get('/', (req, res) => {
  res.send(`
    <!DOCTYPE html>
    <html><head><meta charset="utf-8"><title>Abisinya Bingo</title>
    <style>body{font-family:system-ui;background:#0b0616;color:#f5f3ff;
      min-height:100vh;display:flex;align-items:center;justify-content:center;
      margin:0;padding:20px}
    .c{background:rgba(168,85,247,.1);border:1px solid rgba(168,85,247,.3);
       border-radius:16px;padding:32px;max-width:400px;text-align:center}
    h1{color:#ec4899;margin:0 0 8px}
    a{color:#22d3ee}
    </style></head><body>
    <div class="c">
      <h1>🎯 Abisinya Bingo</h1>
      <p style="color:#a78bfa">Round ${state.roundId} · ${state.phase} · ${state.players.size} players</p>
    </div></body></html>
  `);
});

// Game — direct entry: if running, spectator; if selection, picker
app.get('/game', (req, res) => {
  const q = req.url.includes('?') ? req.url.substring(req.url.indexOf('?')) : '';
  res.redirect('/bingo.html' + q);
});

// =============================================================
//                       PUBLIC / GAME
// =============================================================
app.get('/api/health', (req, res) => {
  res.json({
    status: 'ok',
    round: state.roundId,
    phase: state.phase,
    players: state.players.size,
    cartelaCount: CARTELA_COUNT,
    uptime: process.uptime()
  });
});

app.get('/api/game', (req, res) => {
  res.json({ success: true, ...publicState() });
});

app.get('/api/game-players', (req, res) => {
  const names = [...state.players.values()]
    .map(p => p.firstName).filter(Boolean).slice(0, 50);
  res.json({ success: true, names });
});

app.get('/api/my-cartelas/:userId', (req, res) => {
  const p = state.players.get(Number(req.params.userId));
  if (!p) return res.json({ success: true, cartelas: [] });
  const grids = state.cartelas.filter(c => p.cartelas.includes(c.id));
  res.json({ success: true, cartelas: grids, player: p });
});

app.post('/api/player/join', async (req, res) => {
  try {
    const { userId, firstName, cartelaIds } = req.body;
    if (state.phase !== 'selection')
      return res.status(400).json({ error: 'Selection closed — wait for next round' });
    if (!Array.isArray(cartelaIds) || cartelaIds.length < 1 || cartelaIds.length > 6)
      return res.status(400).json({ error: 'Choose 1 to 6 cartelas' });
    if (state.players.has(userId))
      return res.status(400).json({ error: 'Already joined this round' });

    for (const id of cartelaIds) {
      if (!Number.isInteger(id) || id < 1 || id > CARTELA_COUNT)
        return res.status(400).json({ error: `Invalid cartela ${id}` });
      if (state.takenCartelas.has(id))
        return res.status(400).json({ error: `Cartela ${id} already taken` });
    }

    const total = state.entryFee * cartelaIds.length;
    const u = await User.findOne({ telegramId: userId });
    if (!u) return res.status(404).json({ error: 'User not found — send /start to bot' });
    if (u.balance < total)
      return res.status(400).json({ error: `Need ${total} ETB (you have ${u.balance.toFixed(2)})` });

    u.balance -= total;
    u.totalGames = (u.totalGames || 0) + 1;
    await u.save();

    await Transaction.create({
      userId, type: 'bet', amount: total, status: 'approved',
      method: 'game', gameId: state.roundId, cartelas: cartelaIds
    });

    state.prizePool += total;
    state.players.set(userId, { firstName, cartelas: cartelaIds });
    cartelaIds.forEach(id => state.takenCartelas.add(id));

    const grids = state.cartelas.filter(c => cartelaIds.includes(c.id));
    broadcastState();
    res.json({ success: true, cartelas: grids, balance: u.balance, prizePool: state.prizePool });
  } catch (e) {
    console.error('join error:', e.message);
    res.status(500).json({ error: 'Server error' });
  }
});

app.post('/api/player/bingo', async (req, res) => {
  try {
    const { userId, cartelaId } = req.body;
    if (state.phase !== 'running')
      return res.status(400).json({ error: 'Game not running' });
    const player = state.players.get(userId);
    if (!player || !player.cartelas.includes(cartelaId))
      return res.status(400).json({ error: 'Not your cartela' });

    const calledSet = new Set(state.calledNumbers); calledSet.add(0);
    const cartela = state.cartelas.find(c => c.id === cartelaId);
    const w = evaluateWin(cartela, calledSet);
    if (!w) return res.status(400).json({ error: 'No complete line yet' });

    await finishRound({
      userId,
      firstName: player.firstName,
      cartelaId,
      pattern: w.pattern
    });
    res.json({ success: true, prize: state.winner ? state.winner.prize : 0, pattern: w.pattern });
  } catch (e) {
    res.status(500).json({ error: 'Server error' });
  }
});

// =============================================================
//                    PROFILE / WALLET / LEADERBOARD
// =============================================================
app.get('/api/profile/:userId', async (req, res) => {
  try {
    const u = await User.findOne({ telegramId: Number(req.params.userId) });
    if (!u) return res.status(404).json({ error: 'not found' });
    res.json({
      success: true,
      user: {
        telegramId: u.telegramId, firstName: u.firstName, username: u.username,
        balance: u.balance, winBalance: u.winBalance,
        totalWins: u.totalWins || 0, totalEarnings: u.totalEarnings || 0,
        totalGames: u.totalGames || 0
      }
    });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

app.get('/api/history/:userId', async (req, res) => {
  try {
    const uid = Number(req.params.userId);
    const page = Math.max(1, Number(req.query.page) || 1);
    const limit = 20;
    const skip = (page - 1) * limit;
    const [txs, total] = await Promise.all([
      Transaction.find({ userId: uid }).sort({ createdAt: -1 }).skip(skip).limit(limit).lean(),
      Transaction.countDocuments({ userId: uid })
    ]);
    res.json({ success: true, page, totalPages: Math.ceil(total / limit), total, txs });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

app.get('/api/leaderboard', async (req, res) => {
  try {
    const range = req.query.range || 'all';
    let since = null;
    const now = new Date();
    if (range === 'day') since = new Date(now.getTime() - 24 * 60 * 60 * 1000);
    else if (range === 'week') since = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);

    let list;
    if (range === 'all') {
      list = await User.find({ totalWins: { $gt: 0 } })
        .sort({ totalEarnings: -1 }).limit(50)
        .select('firstName username telegramId totalWins totalEarnings').lean();
    } else {
      list = await Transaction.aggregate([
        { $match: { type: 'win', status: 'approved', createdAt: { $gte: since } } },
        { $group: { _id: '$userId', totalEarnings: { $sum: '$amount' }, totalWins: { $sum: 1 } } },
        { $sort: { totalEarnings: -1 } },
        { $limit: 50 },
        { $lookup: { from: 'users', localField: '_id', foreignField: 'telegramId', as: 'u' } },
        { $unwind: { path: '$u', preserveNullAndEmptyArrays: true } },
        { $project: {
          _id: 0, telegramId: '$_id',
          firstName: '$u.firstName', username: '$u.username',
          totalEarnings: 1, totalWins: 1
        }}
      ]);
    }
    res.json({ success: true, range, list });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// =============================================================
//                       BOT ENDPOINTS
// =============================================================
app.post('/api/bot/user', botAuth, async (req, res) => {
  try {
    const { telegramId, username, firstName, phone } = req.body;
    const update = { username, firstName };
    if (phone) update.phone = phone;
    const u = await User.findOneAndUpdate(
      { telegramId }, { $set: update }, { new: true, upsert: true }
    );
    res.json({ success: true, user: u });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

app.get('/api/bot/user/:id', botAuth, async (req, res) => {
  const u = await User.findOne({ telegramId: Number(req.params.id) });
  res.json({ success: true, user: u });
});

app.post('/api/bot/user/:id/adjust', botAuth, async (req, res) => {
  try {
    const { field, delta } = req.body;
    if (!['balance', 'winBalance'].includes(field))
      return res.status(400).json({ error: 'invalid field' });
    const u = await User.findOneAndUpdate(
      { telegramId: Number(req.params.id) },
      { $inc: { [field]: delta } }, { new: true }
    );
    res.json({ success: true, user: u });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

app.get('/api/bot/all-users', botAuth, async (req, res) => {
  const users = await User.find({}, { telegramId: 1, firstName: 1 });
  res.json({ success: true, users });
});

app.post('/api/bot/transaction', botAuth, async (req, res) => {
  const tx = await Transaction.create(req.body);
  res.json({ success: true, tx });
});

app.get('/api/bot/transaction/:id', botAuth, async (req, res) => {
  const tx = await Transaction.findById(req.params.id);
  res.json({ success: true, tx });
});

app.post('/api/bot/transaction/:id/status', botAuth, async (req, res) => {
  const tx = await Transaction.findByIdAndUpdate(
    req.params.id, { status: req.body.status }, { new: true }
  );
  res.json({ success: true, tx });
});

// Direct deposit/withdraw requests from the WebApp (not via bot)
app.post('/api/deposit/request', async (req, res) => {
  try {
    const { userId, amount, method, phone, sms } = req.body;
    if (!userId || !amount || amount < 1)
      return res.status(400).json({ error: 'invalid amount' });

    const tx = await Transaction.create({
      userId, type: 'deposit', amount, method, phone, sms, status: 'pending'
    });

    // Notify admin via bot
    if (BOT_CALLBACK_URL) {
      axios.post(`${BOT_CALLBACK_URL}/notify-tx`, {
        telegramId: userId, type: 'deposit', amount, status: 'pending'
      }, { headers: { 'x-bot-secret': BOT_API_SECRET }, timeout: 8000 })
        .catch(() => {});
    }
    res.json({ success: true, tx });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

app.post('/api/withdraw/request', async (req, res) => {
  try {
    const { userId, amount, method, phone } = req.body;
    if (!userId || !amount || amount < 100)
      return res.status(400).json({ error: 'min 100 ETB' });

    const u = await User.findOne({ telegramId: userId });
    if (!u) return res.status(404).json({ error: 'user not found' });
    if (amount > (u.balance + u.winBalance))
      return res.status(400).json({ error: 'exceeds available balance' });

    const tx = await Transaction.create({
      userId, type: 'withdraw', amount, method, phone, status: 'pending'
    });

    if (BOT_CALLBACK_URL) {
      axios.post(`${BOT_CALLBACK_URL}/notify-tx`, {
        telegramId: userId, type: 'withdraw', amount, status: 'pending'
      }, { headers: { 'x-bot-secret': BOT_API_SECRET }, timeout: 8000 })
        .catch(() => {});
    }
    res.json({ success: true, tx });
  } catch (e) { res.status(500).json({ error: e.message }); }
});
// =============================================================
//                       ADMIN
// =============================================================
app.get('/api/admin/stats', adminAuth, async (req, res) => {
  res.json({
    success: true,
    users: await User.countDocuments(),
    pendingTx: await Transaction.countDocuments({ status: 'pending' }),
    round: state.roundId, phase: state.phase,
    players: state.players.size, prizePool: state.prizePool,
    cartelaCount: CARTELA_COUNT
  });
});

app.get('/api/admin/users', adminAuth, async (req, res) => {
  const users = await User.find().sort({ createdAt: -1 }).limit(200);
  res.json({ success: true, users });
});

app.get('/api/admin/transactions', adminAuth, async (req, res) => {
  const txs = await Transaction.find().sort({ createdAt: -1 }).limit(200);
  res.json({ success: true, txs });
});

app.post('/api/admin/transaction/:id', adminAuth, async (req, res) => {
  try {
    const { action } = req.body;
    const tx = await Transaction.findById(req.params.id);
    if (!tx || tx.status !== 'pending')
      return res.status(400).json({ error: 'invalid tx' });

    if (action === 'approve') {
      if (tx.type === 'deposit')
        await User.updateOne({ telegramId: tx.userId }, { $inc: { balance: tx.amount } });
      else if (tx.type === 'withdraw')
        await User.updateOne({ telegramId: tx.userId }, { $inc: { winBalance: -tx.amount } });
      tx.status = 'approved';
    } else tx.status = 'rejected';
    await tx.save();

    if (BOT_CALLBACK_URL) {
      axios.post(`${BOT_CALLBACK_URL}/notify-tx`, {
        telegramId: tx.userId, type: tx.type, amount: tx.amount, status: tx.status
      }, { headers: { 'x-bot-secret': BOT_API_SECRET }, timeout: 8000 }).catch(() => {});
    }
    res.json({ success: true, tx });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

app.post('/api/admin/broadcast', adminAuth, (req, res) => {
  const { message } = req.body;
  if (!message) return res.status(400).json({ error: 'empty message' });
  io.emit('broadcast', { message });
  if (BOT_CALLBACK_URL) {
    axios.post(`${BOT_CALLBACK_URL}/broadcast`, { message },
      { headers: { 'x-bot-secret': BOT_API_SECRET }, timeout: 8000 }).catch(() => {});
  }
  res.json({ success: true });
});

app.post('/api/admin/call-one', adminAuth, (req, res) => {
  if (state.phase !== 'running')
    return res.status(400).json({ success: false, error: 'game not running' });
  callNextNumber();
  res.json({ success: true, number: state.currentCall });
});

app.get('/api/admin/round-players', adminAuth, (req, res) => {
  const players = [...state.players.entries()].map(([uid, p]) => ({
    userId: uid,
    firstName: p.firstName,
    cartelas: p.cartelas,
    hasBingo: false
  }));
  res.json({ success: true, players });
});

app.post('/api/admin/user/:uid/adjust', adminAuth, async (req, res) => {
  try {
    const { field, delta } = req.body;
    if (!['balance', 'winBalance'].includes(field))
      return res.status(400).json({ error: 'invalid field' });
    if (typeof delta !== 'number' || isNaN(delta))
      return res.status(400).json({ error: 'invalid amount' });
    const u = await User.findOneAndUpdate(
      { telegramId: Number(req.params.uid) },
      { $inc: { [field]: delta } }, { new: true }
    );
    if (!u) return res.status(404).json({ error: 'user not found' });
    res.json({ success: true, user: u });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

app.post('/api/admin/settings', adminAuth, (req, res) => {
  const { entryFee, prizePct, selectionSeconds, callIntervalMs } = req.body;
  if (typeof entryFee === 'number' && entryFee > 0) state.entryFee = entryFee;
  if (typeof prizePct === 'number' && prizePct > 0 && prizePct <= 100) state.prizePct = prizePct / 100;
  if (typeof selectionSeconds === 'number' && selectionSeconds >= 10 && selectionSeconds <= 300) state.selectionSeconds = selectionSeconds;
  if (typeof callIntervalMs === 'number' && callIntervalMs >= 1000 && callIntervalMs <= 20000) {
    state.callIntervalMs = callIntervalMs;
    if (state.phase === 'running') {
      clearInterval(state.callTimer);
      state.callTimer = setInterval(callNextNumber, state.callIntervalMs);
    }
  }
  res.json({ success: true, settings: {
    entryFee: state.entryFee, prizePct: state.prizePct * 100,
    selectionSeconds: state.selectionSeconds, callIntervalMs: state.callIntervalMs
  }});
});

app.get('/api/admin/settings', adminAuth, (req, res) => {
  res.json({ success: true, settings: {
    entryFee: state.entryFee, prizePct: state.prizePct * 100,
    selectionSeconds: state.selectionSeconds, callIntervalMs: state.callIntervalMs
  }});
});

app.post('/api/admin/force-new-round', adminAuth, (req, res) => {
  clearInterval(state.callTimer);
  clearTimeout(state.phaseTimer);
  startSelectionPhase();
  res.json({ success: true });
});

app.post('/api/admin/force-start', adminAuth, (req, res) => {
  if (state.phase === 'selection') {
    clearTimeout(state.phaseTimer);
    startRunningPhase();
  }
  res.json({ success: true });
});

app.post('/api/admin/stop-game', adminAuth, (req, res) => {
  clearInterval(state.callTimer);
  clearTimeout(state.phaseTimer);
  startSelectionPhase();
  res.json({ success: true });
});

// =============================================================
//                       SOCKET.IO
// =============================================================
io.on('connection', socket => {
  socket.emit('game-state', publicState());
  socket.on('join-room', () => socket.emit('game-state', publicState()));
  socket.on('disconnect', () => {});
});

// =============================================================
//                       404 FALLBACK
// =============================================================
app.use((req, res) => {
  console.log(`❓ 404: ${req.method} ${req.url}`);
  res.status(404).send(`
    <!DOCTYPE html><html><head><meta charset="utf-8"><title>Not Found</title>
    <style>body{font-family:system-ui;background:#0b0616;color:#f5f3ff;
      display:flex;min-height:100vh;align-items:center;justify-content:center;
      margin:0;padding:20px;text-align:center}
    .c{background:rgba(168,85,247,.1);border:1px solid rgba(168,85,247,.3);
       padding:24px;border-radius:12px;max-width:420px}
    a{color:#22d3ee}
    </style></head><body>
    <div class="c">
      <h2 style="color:#ec4899">404 — Not Found</h2>
      <p style="color:#a78bfa;font-size:14px">Path: <code>${req.url}</code></p>
      <p style="margin-top:16px"><a href="/">Home</a></p>
    </div></body></html>
  `);
});

// =============================================================
//                       START
// =============================================================
server.listen(PORT, () => {
  console.log(`🚀 Server on port ${PORT}`);
  console.log(`👑 Admin secret path: ${ADMIN_SECRET_PATH}`);
});