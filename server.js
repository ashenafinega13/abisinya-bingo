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
const io = new Server(server, {
  cors: { origin: '*' },
  pingTimeout: 30000,
  pingInterval: 10000
});

const PORT = process.env.PORT || 3000;
const BOT_API_SECRET = process.env.BOT_API_SECRET || 'change-me';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || 'admin123';
const BOT_CALLBACK_URL = process.env.BOT_CALLBACK_URL || '';

// =============================================================
// Middleware
// =============================================================
app.use(cors());
app.use(express.json({ limit: '1mb' }));
app.use(express.static(path.join(__dirname, 'public')));

// =============================================================
// MongoDB
// =============================================================
mongoose.connect(process.env.MONGODB_URI)
  .then(() => console.log('✅ MongoDB connected'))
  .catch(e => console.error('❌ Mongo error:', e.message));

// =============================================================
//                       ROUND ENGINE
// =============================================================
const SELECTION_SECONDS = 30;    // cartela pick window
const CALL_INTERVAL_MS  = 4000;  // 4s between numbers
const BETWEEN_ROUNDS_MS = 8000;  // pause showing winner
const CARTELA_COUNT     = 200;
const ENTRY_FEE         = 10;
const PRIZE_PERCENT     = 0.8;

const state = {
  roundId: 0,
  phase: 'selection',           // selection | running | finished
  selectionEndsAt: 0,
  calledNumbers: [],
  currentCall: null,
  players: new Map(),           // userId -> { firstName, cartelas:[id] }
  takenCartelas: new Set(),
  prizePool: 0,
  winner: null,
  cartelas: [],
  callTimer: null,
  phaseTimer: null,
  roundHistory: []
};

// ---------- Cartela generator ----------
function generateCartela(cartelaId) {
  const cols = [];
  for (let c = 0; c < 5; c++) {
    const min = c * 15 + 1;
    const pool = Array.from({ length: 15 }, (_, i) => min + i);
    // Fisher–Yates shuffle
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
  grid[2][2] = 0;               // FREE space
  return { id: cartelaId, grid };
}

for (let id = 1; id <= CARTELA_COUNT; id++) {
  state.cartelas.push(generateCartela(id));
}

// ---------- Public state (sent to clients) ----------
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

function broadcastState() {
  io.emit('game-state', publicState());
}

// ---------- Phase: selection ----------
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

// ---------- Phase: running ----------
function startRunningPhase() {
  if (state.players.size === 0) {
    // No players yet — extend the selection window instead of restarting
    console.log('⏳ No players — extending selection window');
    state.selectionEndsAt = Date.now() + SELECTION_SECONDS * 1000;
    broadcastState();
    state.phaseTimer = setTimeout(startRunningPhase, SELECTION_SECONDS * 1000);
    return;
  }
  state.phase = 'running';
  broadcastState();
  console.log(`▶️ Round ${state.roundId}: running with ${state.players.size} players`);

  state.callTimer = setInterval(callNextNumber, CALL_INTERVAL_MS);
  setTimeout(callNextNumber, 1000);
}

// ---------- Call next number ----------
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
  console.log(`📞 ${n}`);
}

// ---------- Winner check ----------
function checkWinner(cartelaId) {
  const cartela = state.cartelas.find(c => c.id === cartelaId);
  if (!cartela) return false;
  const called = new Set(state.calledNumbers);
  called.add(0);
  const corners = [
    cartela.grid[0][0], cartela.grid[0][4],
    cartela.grid[4][0], cartela.grid[4][4]
  ];
  return corners.every(x => called.has(x));
}

// ---------- Finish round ----------
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
      await User.updateOne(
        { telegramId: winner.userId },
        { $inc: { winBalance: prize } }
      );
      await Transaction.create({
        userId: winner.userId,
        type: 'win',
        amount: prize,
        status: 'approved',
        method: 'game',
        sms: `Round ${state.roundId}`
      });
    } catch (e) {
      console.error('winner credit error:', e.message);
    }

    // Include cartela grid for the winner modal
    const wc = state.cartelas.find(c => c.id === winner.cartelaId);
    const winnerPayload = {
      ...winner,
      cartelaGrid: wc ? wc.grid : null
    };

    io.emit('round-finished', winnerPayload);

    if (BOT_CALLBACK_URL) {
      axios.post(
        `${BOT_CALLBACK_URL}/winner`,
        winner,
        { headers: { 'x-bot-secret': BOT_API_SECRET }, timeout: 8000 }
      ).catch(() => {});
    }

    console.log(
      `🏆 ${winner.firstName} won ${prize} ETB on cartela #${winner.cartelaId}`
    );
  } else {
    io.emit('round-finished', null);
    console.log('😐 No winner — all 75 numbers called');
  }

  broadcastState();

  // Queue next round
  state.phaseTimer = setTimeout(startSelectionPhase, BETWEEN_ROUNDS_MS);
}

// Kick off the first round
startSelectionPhase();

// =============================================================
//                       AUTH MIDDLEWARE
// =============================================================
function botAuth(req, res, next) {
  if (req.headers['x-bot-secret'] !== BOT_API_SECRET) {
    return res.status(403).json({ error: 'forbidden' });
  }
  next();
}
function adminAuth(req, res, next) {
  if (req.headers['x-admin-pass'] !== ADMIN_PASSWORD) {
    return res.status(403).json({ error: 'forbidden' });
  }
  next();
}

// =============================================================
//                       PUBLIC / GAME ROUTES
// =============================================================

// Redirect from /game → /bingo.html (keeps query params)
app.get('/game', (req, res) => {
  const q = req.url.includes('?')
    ? req.url.substring(req.url.indexOf('?'))
    : '';
  res.redirect('/bingo.html' + q);
});

// Health check
app.get('/api/health', (req, res) => {
  res.json({
    status: 'ok',
    round: state.roundId,
    phase: state.phase,
    players: state.players.size,
    uptime: process.uptime()
  });
});

// Full public state
app.get('/api/game', (req, res) => {
  res.json({ success: true, ...publicState() });
});

// Player names in current round (for the ticker)
app.get('/api/game-players', (req, res) => {
  const names = [...state.players.values()]
    .map(p => p.firstName)
    .filter(Boolean)
    .slice(0, 50);
  res.json({ success: true, names });
});

// Player's current cartelas
app.get('/api/my-cartelas/:userId', (req, res) => {
  const p = state.players.get(Number(req.params.userId));
  if (!p) return res.json({ success: true, cartelas: [] });
  const grids = state.cartelas.filter(c => p.cartelas.includes(c.id));
  res.json({ success: true, cartelas: grids, player: p });
});

// ---------- Player joins a round ----------
app.post('/api/player/join', async (req, res) => {
  try {
    const { userId, firstName, cartelaIds } = req.body;

    if (state.phase !== 'selection') {
      return res.status(400).json({ error: 'selection closed, wait for next round' });
    }
    if (!Array.isArray(cartelaIds) || cartelaIds.length < 1 || cartelaIds.length > 4) {
      return res.status(400).json({ error: 'choose 1 to 4 cartelas' });
    }
    if (state.players.has(userId)) {
      return res.status(400).json({ error: 'already joined this round' });
    }

    for (const id of cartelaIds) {
      if (!Number.isInteger(id) || id < 1 || id > CARTELA_COUNT) {
        return res.status(400).json({ error: `invalid cartela ${id}` });
      }
      if (state.takenCartelas.has(id)) {
        return res.status(400).json({ error: `cartela ${id} already taken` });
      }
    }

    const total = ENTRY_FEE * cartelaIds.length;
    const u = await User.findOne({ telegramId: userId });
    if (!u) return res.status(404).json({ error: 'user not found' });
    if (u.balance < total) {
      return res.status(400).json({ error: `need ${total} ETB (you have ${u.balance.toFixed(2)})` });
    }

    u.balance -= total;
    await u.save();

    await Transaction.create({
      userId,
      type: 'bet',
      amount: total,
      status: 'approved',
      method: 'game',
      sms: `Round ${state.roundId} · cartelas ${cartelaIds.join(',')}`
    });

    state.prizePool += total;
    state.players.set(userId, { firstName, cartelas: cartelaIds });
    cartelaIds.forEach(id => state.takenCartelas.add(id));

    const grids = state.cartelas.filter(c => cartelaIds.includes(c.id));

    broadcastState();

    res.json({
      success: true,
      cartelas: grids,
      balance: u.balance,
      prizePool: state.prizePool
    });
  } catch (e) {
    console.error('join error:', e.message);
    res.status(500).json({ error: 'server error' });
  }
});

// ---------- Player claims BINGO ----------
app.post('/api/player/bingo', async (req, res) => {
  try {
    const { userId, cartelaId } = req.body;

    if (state.phase !== 'running') {
      return res.status(400).json({ error: 'game not running' });
    }
    const player = state.players.get(userId);
    if (!player || !player.cartelas.includes(cartelaId)) {
      return res.status(400).json({ error: 'not your cartela' });
    }
    if (!checkWinner(cartelaId)) {
      return res.status(400).json({ error: 'invalid bingo claim' });
    }

    await finishRound({
      userId,
      firstName: player.firstName,
      cartelaId,
      pattern: '4-corners'
    });

    res.json({ success: true, prize: state.winner ? state.winner.prize : 0 });
  } catch (e) {
    console.error('bingo error:', e.message);
    res.status(500).json({ error: 'server error' });
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
      { telegramId },
      { $set: update },
      { new: true, upsert: true }
    );
    res.json({ success: true, user: u });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.get('/api/bot/user/:id', botAuth, async (req, res) => {
  const u = await User.findOne({ telegramId: Number(req.params.id) });
  res.json({ success: true, user: u });
});

app.post('/api/bot/user/:id/adjust', botAuth, async (req, res) => {
  try {
    const { field, delta } = req.body;
    if (!['balance', 'winBalance'].includes(field)) {
      return res.status(400).json({ error: 'invalid field' });
    }
    const u = await User.findOneAndUpdate(
      { telegramId: Number(req.params.id) },
      { $inc: { [field]: delta } },
      { new: true }
    );
    res.json({ success: true, user: u });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
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
    req.params.id,
    { status: req.body.status },
    { new: true }
  );
  res.json({ success: true, tx });
});

// =============================================================
//                       ADMIN ENDPOINTS
// =============================================================
app.get('/api/admin/stats', adminAuth, async (req, res) => {
  res.json({
    success: true,
    users: await User.countDocuments(),
    pendingTx: await Transaction.countDocuments({ status: 'pending' }),
    round: state.roundId,
    phase: state.phase,
    players: state.players.size,
    prizePool: state.prizePool
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
    if (!tx || tx.status !== 'pending') {
      return res.status(400).json({ error: 'invalid tx' });
    }

    if (action === 'approve') {
      if (tx.type === 'deposit') {
        await User.updateOne(
          { telegramId: tx.userId },
          { $inc: { balance: tx.amount } }
        );
      } else if (tx.type === 'withdraw') {
        await User.updateOne(
          { telegramId: tx.userId },
          { $inc: { winBalance: -tx.amount } }
        );
      }
      tx.status = 'approved';
    } else {
      tx.status = 'rejected';
    }
    await tx.save();

    if (BOT_CALLBACK_URL) {
      axios.post(
        `${BOT_CALLBACK_URL}/notify-tx`,
        {
          telegramId: tx.userId,
          type: tx.type,
          amount: tx.amount,
          status: tx.status
        },
        { headers: { 'x-bot-secret': BOT_API_SECRET }, timeout: 8000 }
      ).catch(() => {});
    }

    res.json({ success: true, tx });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.post('/api/admin/broadcast', adminAuth, (req, res) => {
  const { message } = req.body;
  if (!message) return res.status(400).json({ error: 'empty message' });
  io.emit('broadcast', { message });
  if (BOT_CALLBACK_URL) {
    axios.post(
      `${BOT_CALLBACK_URL}/broadcast`,
      { message },
      { headers: { 'x-bot-secret': BOT_API_SECRET }, timeout: 8000 }
    ).catch(() => {});
  }
  res.json({ success: true });
});

// Force next round right now
app.post('/api/admin/force-new-round', adminAuth, (req, res) => {
  clearInterval(state.callTimer);
  clearTimeout(state.phaseTimer);
  startSelectionPhase();
  res.json({ success: true });
});

// Force start running (skip waiting for selection to end)
app.post('/api/admin/force-start', adminAuth, (req, res) => {
  if (state.phase === 'selection') {
    clearTimeout(state.phaseTimer);
    startRunningPhase();
  }
  res.json({ success: true });
});

// Games list (for admin table)
app.get('/api/admin/games', adminAuth, (req, res) => {
  res.json({ success: true, games: [publicState()] });
});

// =============================================================
//                       SOCKET.IO
// =============================================================
io.on('connection', socket => {
  console.log(`🔌 socket connected: ${socket.id}`);
  // Send current state immediately
  socket.emit('game-state', publicState());

  socket.on('join-room', () => {
    // Nothing extra to do — every client already receives broadcasts.
    socket.emit('game-state', publicState());
  });

  socket.on('disconnect', () => {
    console.log(`🔌 socket disconnected: ${socket.id}`);
  });
});

// =============================================================
//                       START SERVER
// =============================================================
server.listen(PORT, () => {
  console.log(`🚀 Server on port ${PORT}`);
  console.log(`📍 http://localhost:${PORT}`);
  console.log(`🎮 Game URL: http://localhost:${PORT}/game?uid=123&name=Test`);
  console.log(`👑 Admin:    http://localhost:${PORT}/admin.html`);
});