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

const ADMIN_SECRET_PATH = (() => {
  const h = crypto.createHash('sha256').update('adm-' + ADMIN_PASSWORD).digest('hex');
  return '/admin-panel-' + h.slice(0, 20);
})();

console.log('\n' + '='.repeat(64));
console.log('👑  ADMIN DASHBOARD URL');
console.log(`👑  https://abisinya-bingo-server.onrender.com${ADMIN_SECRET_PATH}`);
console.log('='.repeat(64) + '\n');

app.use(cors());
app.use(express.json({ limit: '1mb' }));

const PUBLIC_DIR = path.join(__dirname, 'public');

app.get('/admin.html', (req, res) => res.status(404).send('Not found'));
app.get(ADMIN_SECRET_PATH, (req, res) => res.sendFile(path.join(PUBLIC_DIR, 'admin.html')));
app.use(express.static(PUBLIC_DIR));

mongoose.connect(process.env.MONGODB_URI)
  .then(() => console.log('✅ MongoDB connected'))
  .catch(e => console.error('❌ Mongo error:', e.message));

// =============================================================
// ROUND ENGINE
// =============================================================
const DEFAULT_SELECTION_SECONDS = 30;
const DEFAULT_CALL_INTERVAL_MS  = 4000;
const BETWEEN_ROUNDS_MS         = 5000; // 5s between rounds
const CARTELA_COUNT             = 600;
const DEFAULT_ENTRY_FEE         = 10;
const DEFAULT_PRIZE_PERCENT     = 0.8;
const LATE_JOIN_GRACE_MS        = 15000;
const JACKPOT_CONTRIBUTION_PCT  = 0.1;

const state = {
  roundId: 0, phase: 'selection', selectionEndsAt: 0, calledNumbers: [], currentCall: null,
  players: new Map(), takenCartelas: new Set(), prizePool: 0, winner: null,
  cartelas: [], callTimer: null, phaseTimer: null, roundHistory: [],
  entryFee: DEFAULT_ENTRY_FEE, prizePct: DEFAULT_PRIZE_PERCENT,
  selectionSeconds: DEFAULT_SELECTION_SECONDS, callIntervalMs: DEFAULT_CALL_INTERVAL_MS,
  jackpot: 0, startedAt: 0
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

for (let id = 1; id <= CARTELA_COUNT; id++) state.cartelas.push(generateCartela(id));

function letterOf(n) {
  if (n <= 15) return 'B'; if (n <= 30) return 'I'; if (n <= 45) return 'N'; if (n <= 60) return 'G'; return 'O';
}

function evaluateWin(cartela, calledSet) {
  if (!cartela) return null;
  const g = cartela.grid;
  for (let r = 0; r < 5; r++) { let ok = true; for (let c = 0; c < 5; c++) { if (g[r][c] !== 0 && !calledSet.has(g[r][c])) { ok = false; break; } } if (ok) return { pattern: 'row:' + r }; }
  for (let c = 0; c < 5; c++) { let ok = true; for (let r = 0; r < 5; r++) { if (g[r][c] !== 0 && !calledSet.has(g[r][c])) { ok = false; break; } } if (ok) return { pattern: 'col:' + c }; }
  let ok = true; for (let i = 0; i < 5; i++) { if (g[i][i] !== 0 && !calledSet.has(g[i][i])) { ok = false; break; } } if (ok) return { pattern: 'diag:main' };
  ok = true; for (let i = 0; i < 5; i++) { if (g[i][4 - i] !== 0 && !calledSet.has(g[i][4 - i])) { ok = false; break; } } if (ok) return { pattern: 'diag:anti' };
  return null;
}

function publicState() {
  return {
    roundId: state.roundId, phase: state.phase, selectionEndsAt: state.selectionEndsAt,
    entryFee: state.entryFee, currentCall: state.currentCall, calledNumbers: state.calledNumbers,
    prizePool: state.prizePool, playerCount: state.players.size,
    players: [...state.players.entries()].map(([uid, p]) => ({ userId: uid, firstName: p.firstName, cartelas: p.cartelas })),
    takenCartelas: [...state.takenCartelas], winner: state.winner, cartelaCount: CARTELA_COUNT,
    jackpot: state.jackpot, startedAt: state.startedAt
  };
}
function broadcastState() { io.emit('game-state', publicState()); }

function startSelectionPhase() {
  state.phase = 'selection'; state.selectionEndsAt = Date.now() + state.selectionSeconds * 1000;
  state.calledNumbers = []; state.currentCall = null; state.players = new Map();
  state.takenCartelas = new Set(); state.prizePool = 0; state.winner = null; state.startedAt = 0;
  state.roundId++; clearTimeout(state.phaseTimer); clearInterval(state.callTimer);
  console.log(`🟢 Round ${state.roundId}: selection`);
  broadcastState();
  state.phaseTimer = setTimeout(startRunningPhase, state.selectionSeconds * 1000);
}

function startRunningPhase() {
  if (state.players.size === 0) {
    state.selectionEndsAt = Date.now() + state.selectionSeconds * 1000;
    broadcastState(); state.phaseTimer = setTimeout(startRunningPhase, state.selectionSeconds * 1000); return;
  }
  state.phase = 'running'; state.startedAt = Date.now(); broadcastState();
  console.log(`▶️ Round ${state.roundId}: running`);
  clearInterval(state.callTimer); state.callTimer = setInterval(callNextNumber, state.callIntervalMs);
  setTimeout(callNextNumber, 1000);
}

function callNextNumber() {
  if (state.phase !== 'running') return;
  if (state.calledNumbers.length >= 75) return finishRound(null);
  let n; do { n = Math.floor(Math.random() * 75) + 1; } while (state.calledNumbers.includes(n));
  state.calledNumbers.push(n); state.currentCall = n;
  io.emit('number-called', { number: n, all: state.calledNumbers });
  broadcastState();
}

async function finishRound(winnerInfo) {
  state.phase = 'finished'; clearInterval(state.callTimer); clearTimeout(state.phaseTimer);
  if (winnerInfo) {
    const prize = Math.floor(state.prizePool * state.prizePct);
    const winner = { ...winnerInfo, prize }; state.winner = winner;
    try {
      await User.updateOne({ telegramId: winner.userId }, { $inc: { winBalance: prize, totalWins: 1, totalEarnings: prize } });
      await Transaction.create({ userId: winner.userId, type: 'win', amount: prize, status: 'approved', method: 'game', gameId: state.roundId });
    } catch (e) { console.error(e); }
    const wc = state.cartelas.find(c => c.id === winner.cartelaId);
    io.emit('round-finished', { ...winner, cartelaGrid: wc ? wc.grid : null });
  } else { io.emit('round-finished', null); }
  
  const jackpotAdd = Math.floor(state.prizePool * JACKPOT_CONTRIBUTION_PCT);
  if (jackpotAdd > 0) state.jackpot += jackpotAdd;
  
  broadcastState();
  state.phaseTimer = setTimeout(startSelectionPhase, BETWEEN_ROUNDS_MS);
}

startSelectionPhase();

function botAuth(req, res, next) { if (req.headers['x-bot-secret'] !== BOT_API_SECRET) return res.status(403).json({ error: 'forbidden' }); next(); }
function adminAuth(req, res, next) { if (req.headers['x-admin-pass'] !== ADMIN_PASSWORD) return res.status(403).json({ error: 'forbidden' }); next(); }

app.get('/', (req, res) => res.redirect('/bingo.html'));
app.get('/game', (req, res) => res.redirect('/bingo.html' + (req.url.includes('?') ? req.url.substring(req.url.indexOf('?')) : '')));

app.get('/api/health', (req, res) => res.json({ status: 'ok', round: state.roundId, phase: state.phase, jackpot: state.jackpot }));
app.get('/api/game', (req, res) => res.json({ success: true, ...publicState() }));
app.get('/api/my-cartelas/:userId', (req, res) => {
  const p = state.players.get(Number(req.params.userId));
  if (!p) return res.json({ success: true, cartelas: [] });
  res.json({ success: true, cartelas: state.cartelas.filter(c => p.cartelas.includes(c.id)), player: p });
});

// === FIXED JOIN LOGIC ===
app.post('/api/player/join', async (req, res) => {
  try {
    const userId = req.body.userId; const firstName = req.body.firstName; const cartelaIds = req.body.cartelaIds;
    const graceActive = state.phase === 'running' && state.startedAt && (Date.now() - state.startedAt) < LATE_JOIN_GRACE_MS;
    if (state.phase !== 'selection' && !graceActive) return res.status(400).json({ error: 'Selection closed' });
    if (!Array.isArray(cartelaIds) || cartelaIds.length < 1 || cartelaIds.length > 4) return res.status(400).json({ error: 'Choose 1 to 4 cartelas' });
    if (state.players.has(userId)) return res.status(400).json({ error: 'Already joined' });

    for (const id of cartelaIds) {
      if (!Number.isInteger(id) || id < 1 || id > CARTELA_COUNT) return res.status(400).json({ error: 'Invalid cartela' });
      if (state.takenCartelas.has(id)) return res.status(400).json({ error: 'Cartela taken' });
    }

    const totalCost = state.entryFee * cartelaIds.length;
    let u = await User.findOne({ telegramId: userId });
    
    // Auto-create if missing
    if (!u) {
      u = await User.create({ telegramId: userId, firstName: firstName || 'Player', balance: 0, winBalance: 0 });
    }

    const userMoney = (u.balance || 0) + (u.winBalance || 0);
    
    // THE BUG FIX: Check if combined balance covers the total cost
    if (userMoney < totalCost) {
      return res.status(400).json({ error: `Need ${totalCost} ETB, but you only have ${userMoney.toFixed(2)} ETB total.` });
    }

    // Deduct from balance first, then winBalance if needed
    let remainingCost = totalCost;
    if (u.balance >= remainingCost) {
      u.balance -= remainingCost; remainingCost = 0;
    } else {
      remainingCost -= u.balance; u.balance = 0;
      u.winBalance -= remainingCost;
    }

    u.totalGames = (u.totalGames || 0) + 1;
    await u.save();

    await Transaction.create({ userId, type: 'bet', amount: totalCost, status: 'approved', method: 'game', gameId: state.roundId });

    state.prizePool += totalCost;
    state.players.set(userId, { firstName, cartelas: cartelaIds });
    cartelaIds.forEach(id => state.takenCartelas.add(id));

    broadcastState();
    res.json({ success: true, cartelas: state.cartelas.filter(c => cartelaIds.includes(c.id)), balance: u.balance + u.winBalance });
  } catch (e) {
    res.status(500).json({ error: 'Server error: ' + e.message });
  }
});

app.post('/api/player/bingo', async (req, res) => {
  const { userId, cartelaId } = req.body;
  if (state.phase !== 'running') return res.status(400).json({ error: 'Game not running' });
  const player = state.players.get(userId);
  if (!player || !player.cartelas.includes(cartelaId)) return res.status(400).json({ error: 'Not your cartela' });

  const calledSet = new Set(state.calledNumbers); calledSet.add(0);
  const cartela = state.cartelas.find(c => c.id === cartelaId);
  const w = evaluateWin(cartela, calledSet);
  if (!w) return res.status(400).json({ error: 'No complete line yet' });

  await finishRound({ userId, firstName: player.firstName, cartelaId, pattern: w.pattern });
  res.json({ success: true, prize: state.winner ? state.winner.prize : 0 });
});

app.get('/api/profile/:userId', async (req, res) => {
  const u = await User.findOne({ telegramId: Number(req.params.userId) });
  if (!u) return res.status(404).json({ error: 'not found' });
  res.json({ success: true, user: { telegramId: u.telegramId, firstName: u.firstName, balance: u.balance, winBalance: u.winBalance, totalWins: u.totalWins || 0, totalEarnings: u.totalEarnings || 0, totalGames: u.totalGames || 0 } });
});

app.get('/api/history/:userId', async (req, res) => {
  const page = Math.max(1, Number(req.query.page) || 1); const limit = 20;
  const txs = await Transaction.find({ userId: Number(req.params.userId) }).sort({ createdAt: -1 }).skip((page - 1) * limit).limit(limit).lean();
  const total = await Transaction.countDocuments({ userId: Number(req.params.userId) });
  res.json({ success: true, page, totalPages: Math.ceil(total / limit), total, txs });
});

// =============================================================
// BOT ENDPOINTS
// =============================================================
app.post('/api/bot/user', botAuth, async (req, res) => {
  const update = { username: req.body.username, firstName: req.body.firstName };
  if (req.body.phone) update.phone = req.body.phone;
  const u = await User.findOneAndUpdate({ telegramId: req.body.telegramId }, { $set: update }, { new: true, upsert: true });
  res.json({ success: true, user: u });
});
app.get('/api/bot/user/:id', botAuth, async (req, res) => res.json({ success: true, user: await User.findOne({ telegramId: Number(req.params.id) }) }));
app.post('/api/bot/user/:id/adjust', botAuth, async (req, res) => {
  const u = await User.findOneAndUpdate({ telegramId: Number(req.params.id) }, { $inc: { [req.body.field]: req.body.delta } }, { new: true });
  res.json({ success: true, user: u });
});
app.get('/api/bot/all-users', botAuth, async (req, res) => res.json({ success: true, users: await User.find({}, { telegramId: 1, firstName: 1 }) }));
app.post('/api/bot/transaction', botAuth, async (req, res) => res.json({ success: true, tx: await Transaction.create(req.body) }));
app.get('/api/bot/transaction/:id', botAuth, async (req, res) => res.json({ success: true, tx: await Transaction.findById(req.params.id) }));
app.post('/api/bot/transaction/:id/status', botAuth, async (req, res) => res.json({ success: true, tx: await Transaction.findByIdAndUpdate(req.params.id, { status: req.body.status }, { new: true }) }));

// =============================================================
// ADVANCED ADMIN DASHBOARD APIs
// =============================================================
app.get('/api/admin/stats', adminAuth, async (req, res) => {
  const totalUsers = await User.countDocuments();
  const totalRevenue = await Transaction.aggregate([{ $match: { type: 'deposit', status: 'approved' } }, { $group: { _id: null, total: { $sum: '$amount' } } }]);
  const totalPayouts = await Transaction.aggregate([{ $match: { type: 'withdraw', status: 'approved' } }, { $group: { _id: null, total: { $sum: '$amount' } } }]);
  const totalWins = await Transaction.aggregate([{ $match: { type: 'win' } }, { $group: { _id: null, total: { $sum: '$amount' } } }]);
  
  res.json({
    success: true, users: totalUsers, round: state.roundId, phase: state.phase,
    players: state.players.size, prizePool: state.prizePool, jackpot: state.jackpot,
    revenue: totalRevenue[0]?.total || 0, payouts: totalPayouts[0]?.total || 0, winsPaid: totalWins[0]?.total || 0
  });
});

app.get('/api/admin/users', adminAuth, async (req, res) => res.json({ success: true, users: await User.find().sort({ createdAt: -1 }).limit(200) }));

// Search specific user by ID
app.get('/api/admin/user/:uid', adminAuth, async (req, res) => {
  const u = await User.findOne({ telegramId: Number(req.params.uid) });
  const txs = await Transaction.find({ userId: Number(req.params.uid) }).sort({ createdAt: -1 }).limit(20);
  if (!u) return res.status(404).json({ error: 'User not found' });
  res.json({ success: true, user: u, txs });
});

// Get specific transaction lists
app.get('/api/admin/transactions', adminAuth, async (req, res) => res.json({ success: true, txs: await Transaction.find().sort({ createdAt: -1 }).limit(200) }));
app.get('/api/admin/deposits', adminAuth, async (req, res) => res.json({ success: true, txs: await Transaction.find({ type: 'deposit' }).sort({ createdAt: -1 }).limit(100) }));
app.get('/api/admin/withdrawals', adminAuth, async (req, res) => res.json({ success: true, txs: await Transaction.find({ type: 'withdraw' }).sort({ createdAt: -1 }).limit(100) }));

app.post('/api/admin/transaction/:id', adminAuth, async (req, res) => {
  const { action } = req.body; const tx = await Transaction.findById(req.params.id);
  if (!tx || tx.status !== 'pending') return res.status(400).json({ error: 'invalid tx' });
  if (action === 'approve') {
    if (tx.type === 'deposit') await User.updateOne({ telegramId: tx.userId }, { $inc: { balance: tx.amount } });
    if (tx.type === 'withdraw') await User.updateOne({ telegramId: tx.userId }, { $inc: { winBalance: -tx.amount } });
    tx.status = 'approved';
  } else tx.status = 'rejected';
  await tx.save();
  if (BOT_CALLBACK_URL) axios.post(BOT_CALLBACK_URL + '/notify-tx', { telegramId: tx.userId, type: tx.type, amount: tx.amount, status: tx.status }, { headers: { 'x-bot-secret': BOT_API_SECRET } }).catch(() => {});
  res.json({ success: true, tx });
});

// CLEAR HISTORY
app.post('/api/admin/clear-history', adminAuth, async (req, res) => {
  const type = req.body.type; // 'deposits', 'withdrawals', 'all'
  if (type === 'deposits') await Transaction.deleteMany({ type: 'deposit' });
  else if (type === 'withdrawals') await Transaction.deleteMany({ type: 'withdraw' });
  else await Transaction.deleteMany({});
  res.json({ success: true });
});

app.post('/api/admin/user/:uid/adjust', adminAuth, async (req, res) => {
  const u = await User.findOneAndUpdate({ telegramId: Number(req.params.uid) }, { $inc: { [req.body.field]: req.body.delta } }, { new: true });
  res.json({ success: true, user: u });
});

app.post('/api/admin/settings', adminAuth, (req, res) => {
  const b = req.body;
  if (typeof b.entryFee === 'number') state.entryFee = b.entryFee;
  if (typeof b.prizePct === 'number') state.prizePct = b.prizePct / 100;
  if (typeof b.selectionSeconds === 'number') state.selectionSeconds = b.selectionSeconds;
  if (typeof b.callIntervalMs === 'number') state.callIntervalMs = b.callIntervalMs;
  res.json({ success: true, settings: { entryFee: state.entryFee, prizePct: state.prizePct * 100, selectionSeconds: state.selectionSeconds, callIntervalMs: state.callIntervalMs } });
});

app.get('/api/admin/settings', adminAuth, (req, res) => res.json({ success: true, settings: { entryFee: state.entryFee, prizePct: state.prizePct * 100, selectionSeconds: state.selectionSeconds, callIntervalMs: state.callIntervalMs } }));

app.post('/api/admin/force-new-round', adminAuth, (req, res) => { clearInterval(state.callTimer); clearTimeout(state.phaseTimer); startSelectionPhase(); res.json({ success: true }); });
app.post('/api/admin/force-start', adminAuth, (req, res) => { if (state.phase === 'selection') { clearTimeout(state.phaseTimer); startRunningPhase(); } res.json({ success: true }); });
app.post('/api/admin/reset-jackpot', adminAuth, (req, res) => { state.jackpot = 0; broadcastState(); res.json({ success: true }); });

app.use((req, res) => res.status(404).send('<h2 style="text-align:center;margin-top:50px">404 Not Found</h2>'));

server.listen(PORT, () => { console.log(`🚀 Server on port ${PORT}`); });