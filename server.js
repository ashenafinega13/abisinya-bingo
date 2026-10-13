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

// ============ MongoDB ============
mongoose.connect(process.env.MONGODB_URI)
  .then(() => console.log('✅ MongoDB connected'))
  .catch(e => console.error('❌ Mongo error:', e.message));

// ============ In-memory live game ============
const liveGames = new Map(); // gameId -> { state }

function generateCartela(cartelaId) {
  const cols = [];
  for (let c = 0; c < 5; c++) {
    const min = c * 15 + 1;
    const pool = Array.from({ length: 15 }, (_, i) => min + i);
    // Fisher-Yates
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
  grid[2][2] = 0; // FREE space
  return { cartelaId, grid };
}

// ============ Bot ↔ Server Auth Middleware ============
function botAuth(req, res, next) {
  const secret = req.headers['x-bot-secret'];
  if (secret !== BOT_API_SECRET) return res.status(403).json({ error: 'forbidden' });
  next();
}

// ============ REST: Bot endpoints ============

// Register / sync user from bot
app.post('/api/bot/user', botAuth, async (req, res) => {
  const { telegramId, username, firstName, phone } = req.body;
  const u = await User.findOneAndUpdate(
    { telegramId },
    { $set: { username, firstName, phone } },
    { new: true, upsert: true }
  );
  res.json({ success: true, user: u });
});

// Get user wallet
app.get('/api/bot/user/:id', botAuth, async (req, res) => {
  const u = await User.findOne({ telegramId: Number(req.params.id) });
  res.json({ success: true, user: u });
});

// Adjust balance (called by bot when approving tx)
app.post('/api/bot/user/:id/adjust', botAuth, async (req, res) => {
  const { field, delta } = req.body; // field: balance | winBalance
  const u = await User.findOneAndUpdate(
    { telegramId: Number(req.params.id) },
    { $inc: { [field]: delta } },
    { new: true }
  );
  res.json({ success: true, user: u });
});

// Log a transaction
app.post('/api/bot/transaction', botAuth, async (req, res) => {
  const tx = await Transaction.create(req.body);
  res.json({ success: true, tx });
});

// Update transaction status
app.post('/api/bot/transaction/:id/status', botAuth, async (req, res) => {
  const tx = await Transaction.findByIdAndUpdate(req.params.id, { status: req.body.status }, { new: true });
  res.json({ success: true, tx });
});

// List pending transactions
app.get('/api/bot/transactions/pending', botAuth, async (req, res) => {
  const txs = await Transaction.find({ status: 'pending' }).sort({ createdAt: -1 });
  res.json({ success: true, txs });
});

// Get a specific transaction
app.get('/api/bot/transaction/:id', botAuth, async (req, res) => {
  const tx = await Transaction.findById(req.params.id);
  res.json({ success: true, tx });
});

// ============ REST: Admin endpoints ============
function adminAuth(req, res, next) {
  if (req.headers['x-admin-pass'] !== ADMIN_PASSWORD) return res.status(403).json({ error: 'forbidden' });
  next();
}

app.get('/api/admin/stats', adminAuth, async (req, res) => {
  const [users, pendingTx, runningGames] = await Promise.all([
    User.countDocuments(),
    Transaction.countDocuments({ status: 'pending' }),
    Game.countDocuments({ status: 'running' })
  ]);
  res.json({ success: true, users, pendingTx, runningGames });
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
  const { action } = req.body; // approve | reject
  const tx = await Transaction.findById(req.params.id);
  if (!tx || tx.status !== 'pending') return res.status(400).json({ error: 'invalid tx' });

  if (action === 'approve') {
    if (tx.type === 'deposit') {
      await User.updateOne({ telegramId: tx.userId }, { $inc: { balance: tx.amount } });
    } else if (tx.type === 'withdraw') {
      await User.updateOne({ telegramId: tx.userId }, { $inc: { winBalance: -tx.amount } });
    }
    tx.status = 'approved';
  } else {
    tx.status = 'rejected';
  }
  await tx.save();

  // Notify bot to message user
  if (BOT_CALLBACK_URL) {
    axios.post(`${BOT_CALLBACK_URL}/notify-tx`, {
      telegramId: tx.userId,
      type: tx.type,
      amount: tx.amount,
      status: tx.status
    }, { headers: { 'x-bot-secret': BOT_API_SECRET } }).catch(() => {});
  }
  res.json({ success: true, tx });
});

// Broadcast to all running games
app.post('/api/admin/broadcast', adminAuth, async (req, res) => {
  const { message } = req.body;
  io.emit('broadcast', { message, ts: Date.now() });
  // Also notify bot
  if (BOT_CALLBACK_URL) {
    axios.post(`${BOT_CALLBACK_URL}/broadcast`, { message },
      { headers: { 'x-bot-secret': BOT_API_SECRET } }).catch(() => {});
  }
  res.json({ success: true });
});

// ============ Game Management ============

app.post('/api/admin/game/start', adminAuth, async (req, res) => {
  const { gameId, entryFee = 10 } = req.body;
  if (liveGames.has(gameId)) return res.status(400).json({ error: 'game exists' });

  // Create/prepare cartelas
  const COUNT = Number(req.body.cartelaCount || 200);
  let cartelas = await Cartela.find({ gameId });
  if (cartelas.length === 0) {
    const docs = [];
    for (let i = 1; i <= COUNT; i++) docs.push(generateCartela(i));
    await Cartela.insertMany(docs.map(d => ({ ...d, gameId })));
    cartelas = await Cartela.find({ gameId });
  }

  const state = {
    gameId,
    status: 'waiting',
    entryFee,
    calledNumbers: [],
    currentCall: null,
    cartelas: cartelas.map(c => ({ id: c.cartelaId, grid: c.grid })),
    assignments: new Map(),  // userId -> [cartelaIds]
    players: new Map(),      // userId -> { firstName, cartelas }
    winners: [],
    prizePool: 0
  };
  liveGames.set(gameId, state);
  io.emit('game-state', publicState(state));
  res.json({ success: true, gameId });
});

app.post('/api/admin/game/:gameId/call', adminAuth, async (req, res) => {
  const state = liveGames.get(req.params.gameId);
  if (!state || state.status !== 'running') return res.status(400).json({ error: 'game not running' });
  if (state.calledNumbers.length >= 75) return res.status(400).json({ error: 'all called' });

  let num;
  do { num = Math.floor(Math.random() * 75) + 1; } while (state.calledNumbers.includes(num));
  state.calledNumbers.push(num);
  state.currentCall = num;

  io.to(req.params.gameId).emit('number-called', { number: num, all: state.calledNumbers });
  io.emit('game-state', publicState(state));
  res.json({ success: true, number: num });
});

app.post('/api/admin/game/:gameId/status', adminAuth, async (req, res) => {
  const state = liveGames.get(req.params.gameId);
  if (!state) return res.status(404).json({ error: 'not found' });
  state.status = req.body.status;
  io.emit('game-state', publicState(state));
  if (state.status === 'finished') {
    await Game.findOneAndUpdate({ gameId: state.gameId },
      { status: 'finished', endedAt: new Date(), winners: state.winners, calledNumbers: state.calledNumbers },
      { upsert: true });
  }
  res.json({ success: true });
});

app.get('/api/admin/game/:gameId/state', adminAuth, (req, res) => {
  const state = liveGames.get(req.params.gameId);
  if (!state) return res.status(404).json({ error: 'not found' });
  res.json(publicState(state));
});

app.get('/api/admin/games', adminAuth, (req, res) => {
  const list = [...liveGames.values()].map(publicState);
  res.json({ success: true, games: list });
});

function publicState(s) {
  return {
    gameId: s.gameId,
    status: s.status,
    entryFee: s.entryFee,
    currentCall: s.currentCall,
    calledNumbers: s.calledNumbers,
    prizePool: s.prizePool,
    playerCount: s.players.size,
    winners: s.winners
  };
}

// ============ Player joins game ============
app.post('/api/player/join', async (req, res) => {
  const { userId, firstName, gameId, cartelaIds } = req.body;
  const state = liveGames.get(gameId);
  if (!state) return res.status(404).json({ error: 'game not found' });
  if (state.status === 'finished') return res.status(400).json({ error: 'game finished' });
  if (!Array.isArray(cartelaIds) || cartelaIds.length < 1 || cartelaIds.length > 4)
    return res.status(400).json({ error: 'cartela count must be 1-4' });

  // Validate cartelas exist and are unowned
  const allTaken = new Set();
  for (const [, p] of state.players) p.cartelas.forEach(c => allTaken.add(c));
  for (const id of cartelaIds) {
    if (id < 1 || id > state.cartelas.length) return res.status(400).json({ error: 'invalid cartela id' });
    if (allTaken.has(id)) return res.status(400).json({ error: `cartela ${id} already taken` });
  }

  // Deduct entry fee (cartelas * fee)
  const totalFee = state.entryFee * cartelaIds.length;
  const u = await User.findOne({ telegramId: userId });
  if (!u || u.balance < totalFee) return res.status(400).json({ error: 'insufficient balance' });
  u.balance -= totalFee;
  await u.save();

  state.prizePool += totalFee;
  state.players.set(userId, { firstName, cartelas: cartelaIds });

  // Send cartela grids to player via socket
  const grids = state.cartelas.filter(c => cartelaIds.includes(c.id));
  res.json({
    success: true,
    cartelas: grids,
    balance: u.balance,
    prizePool: state.prizePool,
    playerCount: state.players.size
  });

  io.emit('game-state', publicState(state));
});

// ============ BINGO claim ============
app.post('/api/player/bingo', async (req, res) => {
  const { userId, gameId, cartelaId } = req.body;
  const state = liveGames.get(gameId);
  if (!state || state.status !== 'running') return res.status(400).json({ error: 'not running' });

  const player = state.players.get(userId);
  if (!player || !player.cartelas.includes(cartelaId)) return res.status(400).json({ error: 'not your cartela' });

  const cartela = state.cartelas.find(c => c.id === cartelaId);
  const called = new Set(state.calledNumbers);
  called.add(0); // FREE space

  // Only 4-corners pattern (you can extend)
  const corners = [cartela.grid[0][0], cartela.grid[0][4], cartela.grid[4][0], cartela.grid[4][4]];
  const allMarked = corners.every(n => called.has(n));

  if (!allMarked) return res.status(400).json({ error: 'invalid bingo claim' });

  const prize = Math.floor(state.prizePool * 0.8);
  const winner = { userId, firstName: player.firstName, cartelaId, prize, pattern: '4-corners' };
  state.winners.push(winner);
  state.status = 'finished';

  // Credit winnings
  await User.updateOne({ telegramId: userId }, { $inc: { winBalance: prize } });

  // Record tx
  await Transaction.create({ userId, type: 'win', amount: prize, status: 'approved', method: 'game' });

  io.emit('bingo-claimed', winner);
  io.emit('game-state', publicState(state));

  // Notify bot
  if (BOT_CALLBACK_URL) {
    axios.post(`${BOT_CALLBACK_URL}/winner`, { ...winner, gameId },
      { headers: { 'x-bot-secret': BOT_API_SECRET } }).catch(() => {});
  }

  res.json({ success: true, prize });
});

// ============ Socket.IO ============
io.on('connection', socket => {
  socket.on('join-room', gameId => {
    socket.join(gameId);
    const state = liveGames.get(gameId);
    if (state) socket.emit('game-state', publicState(state));
  });
});

server.listen(PORT, () => console.log(`🚀 Server on ${PORT}`));

app.get('/api/bot/all-users', botAuth, async (req, res) => {
  const users = await User.find({}, { telegramId: 1 });
  res.json({ success: true, users });
});