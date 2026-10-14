require('dotenv').config();
const express = require('express');
const http = require('http');
const cors = require('cors');
const mongoose = require('mongoose');
const { Server } = require('socket.io');
const path = require('path');
const axios = require('axios');

const User = require('./models/User');
const Transaction = require('./models/Transaction');
const Game = require('./models/Game');
const Cartela = require('./models/Cartela');

const app = express();
const server = http.createServer(app);
const io = new Server(server, { cors: { origin: '*' } });

const PORT = process.env.PORT || 3000;
const BOT_API_SECRET = process.env.BOT_API_SECRET || 'change-me';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || 'admin123';
const BOT_CALLBACK_URL = process.env.BOT_CALLBACK_URL || '';

app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

mongoose.connect(process.env.MONGODB_URI)
  .then(() => console.log('✅ MongoDB connected'))
  .catch(e => console.error('❌ Mongo error:', e.message));

// =============================================================
//                   ROUND ENGINE STATE
// =============================================================
const SELECTION_SECONDS = 30;
const CALL_INTERVAL_MS  = 4000;
const BETWEEN_ROUNDS_MS = 8000;
const CARTELA_COUNT     = 200;
const ENTRY_FEE         = 10;
const PRIZE_PERCENT     = 0.8;

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
  roundHistory: []
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

function publicState() {
  return {
    roundId: state.roundId,
    phase: state.phase,
    selectionEndsAt: state.selectionEndsAt,
    entryFee: ENTRY_FEE,
    currentCall: state.currentCall,
    calledNumbers: state.calledNumbers,
    prizePool: state.prizePool,
    playerCount: state.players.size,
    takenCartelas: [...state.takenCartelas],
    winner: state.winner,
    roundHistory: state.roundHistory.slice(-5)
  };
}
function broadcastState() { io.emit('game-state', publicState()); }

function startSelectionPhase() {
  state.phase = 'selection';
  state.selectionEndsAt = Date.now() + SELECTION_SECONDS * 1000;
  state.calledNumbers = [];
  state.currentCall = null;
  state.players = new Map();
  state.takenCartelas = new Set();
  state.prizePool = 0;
  state.winner = null;
  state.roundId++;
  clearTimeout(state.phaseTimer);
  clearInterval(state.callTimer);
  console.log(`🟢 Round ${state.roundId}: selection (${SELECTION_SECONDS}s)`);
  broadcastState();
  state.phaseTimer = setTimeout(startRunningPhase, SELECTION_SECONDS * 1000);
}

function startRunningPhase() {
  if (state.players.size === 0) {
    // No players yet — extend the selection window by another 30 seconds
    // instead of restarting the whole round (which would reset the roundId)
    console.log('⏳ No players yet — extending selection window');
    state.selectionEndsAt = Date.now() + SELECTION_SECONDS * 1000;
    broadcastState();
    state.phaseTimer = setTimeout(startRunningPhase, SELECTION_SECONDS * 1000);
    return;
  }
  state.phase = 'running';
  broadcastState();
  state.callTimer = setInterval(callNextNumber, CALL_INTERVAL_MS);
  setTimeout(callNextNumber, 1000);
}

function callNextNumber() {
  if (state.phase !== 'running') return;
  if (state.calledNumbers.length >= 75) return finishRound(null);
  let n;
  do { n = Math.floor(Math.random() * 75) + 1; } while (state.calledNumbers.includes(n));
  state.calledNumbers.push(n);
  state.currentCall = n;
  io.emit('number-called', { number: n, all: state.calledNumbers });
  broadcastState();
  console.log(`📞 ${n}`);
}

function checkWinner(cartelaId) {
  const cartela = state.cartelas.find(c => c.id === cartelaId);
  if (!cartela) return false;
  const called = new Set(state.calledNumbers); called.add(0);
  const corners = [
    cartela.grid[0][0], cartela.grid[0][4],
    cartela.grid[4][0], cartela.grid[4][4]
  ];
  return corners.every(x => called.has(x));
}

async function finishRound(winnerInfo) {
  state.phase = 'finished';
  clearInterval(state.callTimer);
  clearTimeout(state.phaseTimer);

  if (winnerInfo) {
    const prize = Math.floor(state.prizePool * PRIZE_PERCENT);
    const winner = { ...winnerInfo, prize };
    state.winner = winner;
    state.roundHistory.push({ roundId: state.roundId, ...winner });
    try {
      await User.updateOne({ telegramId: winner.userId }, { $inc: { winBalance: prize } });
      await Transaction.create({
        userId: winner.userId, type: 'win', amount: prize,
        status: 'approved', method: 'game', sms: `Round ${state.roundId}`
      });
    } catch (e) { console.error(e.message); }
    io.emit('round-finished', winner);
    if (BOT_CALLBACK_URL) {
      axios.post(`${BOT_CALLBACK_URL}/winner`, winner,
        { headers: { 'x-bot-secret': BOT_API_SECRET } }).catch(() => {});
    }
    console.log(`🏆 ${winner.firstName} won ${prize} on cartela ${winner.cartelaId}`);
  } else {
    io.emit('round-finished', null);
    console.log('😐 No winner');
  }
  broadcastState();
  state.phaseTimer = setTimeout(startSelectionPhase, BETWEEN_ROUNDS_MS);
}

startSelectionPhase();

// =============================================================
//                   AUTH MIDDLEWARE
// =============================================================
function botAuth(req, res, next) {
  if (req.headers['x-bot-secret'] !== BOT_API_SECRET) return res.status(403).json({ error: 'forbidden' });
  next();
}
function adminAuth(req, res, next) {
  if (req.headers['x-admin-pass'] !== ADMIN_PASSWORD) return res.status(403).json({ error: 'forbidden' });
  next();
}

// =============================================================
//                   REDIRECT + PUBLIC
// =============================================================
app.get('/game', (req, res) => {
  const q = req.url.includes('?') ? req.url.substring(req.url.indexOf('?')) : '';
  res.redirect('/bingo.html' + q);
});
app.get('/api/game', (req, res) => res.json({ success: true, ...publicState() }));
app.get('/api/health', (req, res) => res.json({ status: 'ok', round: state.roundId }));
app.get('/api/my-cartelas/:userId', (req, res) => {
  const p = state.players.get(Number(req.params.userId));
  if (!p) return res.json({ success: true, cartelas: [] });
  const grids = state.cartelas.filter(c => p.cartelas.includes(c.id));
  res.json({ success: true, cartelas: grids, player: p });
});

// =============================================================
//                   PLAYER ROUTES
// =============================================================
app.post('/api/player/join', async (req, res) => {
  const { userId, firstName, cartelaIds } = req.body;
  if (state.phase !== 'selection')
    return res.status(400).json({ error: 'selection closed, wait for next round' });
  if (!Array.isArray(cartelaIds) || cartelaIds.length < 1 || cartelaIds.length > 4)
    return res.status(400).json({ error: 'choose 1 to 4 cartelas' });
  for (const id of cartelaIds) {
    if (id < 1 || id > CARTELA_COUNT) return res.status(400).json({ error: 'invalid cartela' });
    if (state.takenCartelas.has(id)) return res.status(400).json({ error: `cartela ${id} taken` });
  }
  const total = ENTRY_FEE * cartelaIds.length;
  const u = await User.findOne({ telegramId: userId });
  if (!u) return res.status(404).json({ error: 'user not found' });
  if (u.balance < total) return res.status(400).json({ error: `need ${total} ETB` });
  u.balance -= total;
  await u.save();
  await Transaction.create({ userId, type: 'bet', amount: total, status: 'approved', method: 'game' });
  state.prizePool += total;
  state.players.set(userId, { firstName, cartelas: cartelaIds });
  cartelaIds.forEach(id => state.takenCartelas.add(id));
  const grids = state.cartelas.filter(c => cartelaIds.includes(c.id));
  broadcastState();
  res.json({ success: true, cartelas: grids, balance: u.balance, prizePool: state.prizePool });
});

app.post('/api/player/bingo', async (req, res) => {
  const { userId, cartelaId } = req.body;
  if (state.phase !== 'running') return res.status(400).json({ error: 'game not running' });
  const player = state.players.get(userId);
  if (!player || !player.cartelas.includes(cartelaId))
    return res.status(400).json({ error: 'not your cartela' });
  if (!checkWinner(cartelaId))
    return res.status(400).json({ error: 'invalid bingo claim' });
  await finishRound({ userId, firstName: player.firstName, cartelaId, pattern: '4-corners' });
  res.json({ success: true, prize: state.winner.prize });
});

// =============================================================
//                   BOT ENDPOINTS
// =============================================================
app.post('/api/bot/user', botAuth, async (req, res) => {
  const { telegramId, username, firstName, phone } = req.body;
  const update = { username, firstName };
  if (phone) update.phone = phone;
  const u = await User.findOneAndUpdate({ telegramId }, { $set: update }, { new: true, upsert: true });
  res.json({ success: true, user: u });
});
app.get('/api/bot/user/:id', botAuth, async (req, res) => {
  res.json({ success: true, user: await User.findOne({ telegramId: Number(req.params.id) }) });
});
app.post('/api/bot/user/:id/adjust', botAuth, async (req, res) => {
  const u = await User.findOneAndUpdate({ telegramId: Number(req.params.id) },
    { $inc: { [req.body.field]: req.body.delta } }, { new: true });
  res.json({ success: true, user: u });
});
app.get('/api/bot/all-users', botAuth, async (req, res) => {
  res.json({ success: true, users: await User.find({}, { telegramId: 1 }) });
});
app.post('/api/bot/transaction', botAuth, async (req, res) => {
  res.json({ success: true, tx: await Transaction.create(req.body) });
});
app.get('/api/bot/transaction/:id', botAuth, async (req, res) => {
  res.json({ success: true, tx: await Transaction.findById(req.params.id) });
});
app.post('/api/bot/transaction/:id/status', botAuth, async (req, res) => {
  res.json({ success: true, tx: await Transaction.findByIdAndUpdate(req.params.id,
    { status: req.body.status }, { new: true }) });
});

// =============================================================
//                   ADMIN
// =============================================================
app.get('/api/admin/stats', adminAuth, async (req, res) => {
  res.json({ success: true,
    users: await User.countDocuments(),
    pendingTx: await Transaction.countDocuments({ status: 'pending' }),
    round: state.roundId, phase: state.phase });
});
app.get('/api/admin/users', adminAuth, async (req, res) => {
  res.json({ success: true, users: await User.find().sort({ createdAt: -1 }).limit(200) });
});
app.get('/api/admin/transactions', adminAuth, async (req, res) => {
  res.json({ success: true, txs: await Transaction.find().sort({ createdAt: -1 }).limit(200) });
});
app.post('/api/admin/transaction/:id', adminAuth, async (req, res) => {
  const tx = await Transaction.findById(req.params.id);
  if (!tx || tx.status !== 'pending') return res.status(400).json({ error: 'invalid' });
  if (req.body.action === 'approve') {
    if (tx.type === 'deposit') await User.updateOne({ telegramId: tx.userId }, { $inc: { balance: tx.amount } });
    if (tx.type === 'withdraw') await User.updateOne({ telegramId: tx.userId }, { $inc: { winBalance: -tx.amount } });
    tx.status = 'approved';
  } else tx.status = 'rejected';
  await tx.save();
  if (BOT_CALLBACK_URL)
    axios.post(`${BOT_CALLBACK_URL}/notify-tx`,
      { telegramId: tx.userId, type: tx.type, amount: tx.amount, status: tx.status },
      { headers: { 'x-bot-secret': BOT_API_SECRET } }).catch(() => {});
  res.json({ success: true, tx });
});
app.post('/api/admin/broadcast', adminAuth, (req, res) => {
  io.emit('broadcast', { message: req.body.message });
  if (BOT_CALLBACK_URL)
    axios.post(`${BOT_CALLBACK_URL}/broadcast`, { message: req.body.message },
      { headers: { 'x-bot-secret': BOT_API_SECRET } }).catch(() => {});
  res.json({ success: true });
});
app.post('/api/admin/force-new-round', adminAuth, (req, res) => {
  clearInterval(state.callTimer); clearTimeout(state.phaseTimer); startSelectionPhase();
  res.json({ success: true });
});

// =============================================================
//                   SOCKET.IO
// =============================================================
io.on('connection', socket => {
  socket.emit('game-state', publicState());
});

server.listen(PORT, () => console.log(`🚀 Server on ${PORT}`));