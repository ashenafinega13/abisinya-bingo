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

const app = express();
const server = http.createServer(app);
const io = new Server(server, { cors: { origin: '*' } });

const PORT = process.env.PORT || 3000;
const BOT_API_SECRET = process.env.BOT_API_SECRET || 'change-me';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || 'admin123';
const BOT_CALLBACK_URL = process.env.BOT_CALLBACK_URL || '';

// Secure Admin Route
const ADMIN_SECRET_PATH = '/admin-panel-' + crypto.createHash('sha256').update('adm-' + ADMIN_PASSWORD).digest('hex').slice(0, 20);
console.log('\n👑 ADMIN URL: https://abisinya-bingo-server.onrender.com' + ADMIN_SECRET_PATH + '\n');

app.use(cors());
app.use(express.json({ limit: '1mb' }));
const PUBLIC_DIR = path.join(__dirname, 'public');
app.get('/admin.html', (req, res) => res.status(404).send('Not found'));
app.get(ADMIN_SECRET_PATH, (req, res) => res.sendFile(path.join(PUBLIC_DIR, 'admin.html')));
app.use(express.static(PUBLIC_DIR));

mongoose.connect(process.env.MONGODB_URI).then(() => console.log('✅ MongoDB connected'));

// --- GAME ENGINE STATE ---
const CARTELA_COUNT = 600;
const SELECTION_SECONDS = 30;
const CALL_INTERVAL_MS = 4000;
const LATE_JOIN_GRACE_MS = 15000; // 15 seconds to join after game starts
const BETWEEN_ROUNDS_MS = 8000;

const state = {
  roundId: 0,
  phase: 'selection', // selection | running | finished
  selectionEndsAt: 0,
  startedAt: 0,
  calledNumbers: [],
  currentCall: null,
  players: new Map(), // userId -> { firstName, cartelas }
  takenCartelas: new Set(),
  prizePool: 0,
  winner: null,
  cartelas: [],
  jackpot: 0,
  callTimer: null,
  phaseTimer: null,
  entryFee: 10,
  prizePct: 0.8,
  selectionSeconds: SELECTION_SECONDS,
  callIntervalMs: CALL_INTERVAL_MS
};

// Generate Cartelas
function generateCartela(id) {
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
  return { id, grid };
}
console.log('🎴 Generating cartelas...');
for (let id = 1; id <= CARTELA_COUNT; id++) state.cartelas.push(generateCartela(id));

function letterOf(n) { return n<=15?'B':n<=30?'I':n<=45?'N':n<=60?'G':'O'; }

function evaluateWin(cartela, calledSet) {
  const g = cartela.grid;
  for (let r=0;r<5;r++){ if(g[r].every(n=>n===0 || calledSet.has(n))) return { pattern: 'row:'+r }; }
  for (let c=0;c<5;c++){ if([0,1,2,3,4].every(r=>g[r][c]===0 || calledSet.has(g[r][c]))) return { pattern: 'col:'+c }; }
  if([0,1,2,3,4].every(i=>g[i][i]===0 || calledSet.has(g[i][i]))) return { pattern: 'diag:main' };
  if([0,1,2,3,4].every(i=>g[i][4-i]===0 || calledSet.has(g[i][4-i]))) return { pattern: 'diag:anti' };
  return null;
}

function publicState() {
  return {
    roundId: state.roundId, phase: state.phase,
    selectionEndsAt: state.selectionEndsAt, startedAt: state.startedAt,
    calledNumbers: state.calledNumbers, currentCall: state.currentCall,
    playerCount: state.players.size, prizePool: state.prizePool,
    takenCartelas: [...state.takenCartelas],
    winner: state.winner, jackpot: state.jackpot
  };
}
function broadcastState() { io.emit('game-state', publicState()); }

function startSelectionPhase() {
  state.phase = 'selection';
  state.selectionEndsAt = Date.now() + state.selectionSeconds * 1000;
  state.calledNumbers = [];
  state.currentCall = null;
  state.players.clear();
  state.takenCartelas.clear();
  state.prizePool = 0;
  state.winner = null;
  state.startedAt = 0;
  state.roundId++;
  clearTimeout(state.phaseTimer);
  clearInterval(state.callTimer);
  console.log(`🟢 Round ${state.roundId}: selection`);
  broadcastState();
  state.phaseTimer = setTimeout(startRunningPhase, state.selectionSeconds * 1000);
}

function startRunningPhase() {
  if (state.players.size === 0) {
    console.log('⏳ No players, extending selection');
    state.selectionEndsAt = Date.now() + state.selectionSeconds * 1000;
    broadcastState();
    state.phaseTimer = setTimeout(startRunningPhase, state.selectionSeconds * 1000);
    return;
  }
  state.phase = 'running';
  state.startedAt = Date.now();
  broadcastState();
  console.log(`▶️ Round ${state.roundId}: running`);
  state.callTimer = setInterval(callNextNumber, state.callIntervalMs);
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
}

async function finishRound(winnerInfo) {
  state.phase = 'finished';
  clearInterval(state.callTimer);
  clearTimeout(state.phaseTimer);

  if (winnerInfo) {
    const prize = Math.floor(state.prizePool * state.prizePct);
    const winner = { ...winnerInfo, prize };
    state.winner = winner;
    try {
      await User.updateOne({ telegramId: winner.userId }, { $inc: { winBalance: prize, totalWins: 1, totalEarnings: prize } });
      await Transaction.create({ userId: winner.userId, type: 'win', amount: prize, status: 'approved', method: 'game', gameId: state.roundId, cartelas: [winner.cartelaId], pattern: winner.pattern });
    } catch(e) {}
    
    const wc = state.cartelas.find(c => c.id === winner.cartelaId);
    io.emit('round-finished', { ...winner, cartelaGrid: wc ? wc.grid : null });
    
    if (BOT_CALLBACK_URL) axios.post(`${BOT_CALLBACK_URL}/winner`, winner, { headers: { 'x-bot-secret': BOT_API_SECRET } }).catch(()=>{});
  } else {
    io.emit('round-finished', null);
  }

  state.jackpot += Math.floor(state.prizePool * 0.1);
  broadcastState();
  state.phaseTimer = setTimeout(startSelectionPhase, BETWEEN_ROUNDS_MS);
}

startSelectionPhase();

// --- ROUTES ---
function botAuth(req, res, next) { if (req.headers['x-bot-secret'] !== BOT_API_SECRET) return res.status(403).json({error:'forbidden'}); next(); }
function adminAuth(req, res, next) { if (req.headers['x-admin-pass'] !== ADMIN_PASSWORD) return res.status(403).json({error:'forbidden'}); next(); }

app.get('/api/game', (req, res) => res.json({ success: true, ...publicState() }));
app.get('/api/my-cartelas/:userId', (req, res) => {
  const p = state.players.get(Number(req.params.userId));
  if (!p) return res.json({ success: true, cartelas: [] });
  const grids = state.cartelas.filter(c => p.cartelas.includes(c.id));
  res.json({ success: true, cartelas: grids });
});

app.post('/api/player/join', async (req, res) => {
  try {
    const { userId, firstName, cartelaIds } = req.body;
    const graceActive = state.phase === 'running' && state.startedAt && (Date.now() - state.startedAt) < LATE_JOIN_GRACE_MS;
    if (state.phase !== 'selection' && !graceActive) return res.status(400).json({ error: 'Selection closed' });
    if (state.players.has(userId)) return res.status(400).json({ error: 'Already joined' });

    for (const id of cartelaIds) {
      if (state.takenCartelas.has(id)) return res.status(400).json({ error: `Cartela ${id} taken` });
    }

    const total = state.entryFee * cartelaIds.length;
    let u = await User.findOne({ telegramId: userId });
    if (!u) u = await User.create({ telegramId: userId, firstName, balance: 0 });
    if (u.balance < total) return res.status(400).json({ error: `Need ${total} ETB, have ${u.balance.toFixed(2)}` });

    u.balance -= total;
    u.totalGames = (u.totalGames || 0) + 1;
    await u.save();
    await Transaction.create({ userId, type: 'bet', amount: total, status: 'approved', method: 'game', gameId: state.roundId, cartelas: cartelaIds });

    state.prizePool += total;
    state.players.set(userId, { firstName, cartelas: cartelaIds });
    cartelaIds.forEach(id => state.takenCartelas.add(id));

    broadcastState();
    res.json({ success: true, cartelas: state.cartelas.filter(c => cartelaIds.includes(c.id)), balance: u.balance });
  } catch (e) { res.status(500).json({ error: 'Server error' }); }
});

app.post('/api/player/bingo', async (req, res) => {
  try {
    const { userId, cartelaId } = req.body;
    if (state.phase !== 'running') return res.status(400).json({ error: 'Not running' });
    const player = state.players.get(userId);
    if (!player || !player.cartelas.includes(cartelaId)) return res.status(400).json({ error: 'Not your cartela' });

    const calledSet = new Set(state.calledNumbers); calledSet.add(0);
    const w = evaluateWin(state.cartelas.find(c => c.id === cartelaId), calledSet);
    if (!w) return res.status(400).json({ error: 'No win yet' });

    await finishRound({ userId, firstName: player.firstName, cartelaId, pattern: w.pattern });
    res.json({ success: true, prize: state.winner.prize });
  } catch (e) { res.status(500).json({ error: 'Server error' }); }
});

// Bot endpoints
app.post('/api/bot/user', botAuth, async (req, res) => {
  const { telegramId, username, firstName, phone } = req.body;
  const update = { username, firstName };
  if (phone) update.phone = phone;
  res.json({ success: true, user: await User.findOneAndUpdate({ telegramId }, { $set: update }, { new: true, upsert: true }) });
});
app.get('/api/bot/user/:id', botAuth, async (req, res) => {
  res.json({ success: true, user: await User.findOne({ telegramId: Number(req.params.id) }) });
});
app.post('/api/bot/user/:id/adjust', botAuth, async (req, res) => {
  res.json({ success: true, user: await User.findOneAndUpdate({ telegramId: Number(req.params.id) }, { $inc: { [req.body.field]: req.body.delta } }, { new: true }) });
});
app.get('/api/bot/all-users', botAuth, async (req, res) => {
  res.json({ success: true, users: await User.find({}, { telegramId: 1, firstName: 1 }) });
});
app.post('/api/bot/transaction', botAuth, async (req, res) => {
  res.json({ success: true, tx: await Transaction.create(req.body) });
});
app.get('/api/bot/transaction/:id', botAuth, async (req, res) => {
  res.json({ success: true, tx: await Transaction.findById(req.params.id) });
});
app.post('/api/bot/transaction/:id/status', botAuth, async (req, res) => {
  res.json({ success: true, tx: await Transaction.findByIdAndUpdate(req.params.id, { status: req.body.status }, { new: true }) });
});

io.on('connection', socket => {
  socket.emit('game-state', publicState());
  socket.on('join-room', () => socket.emit('game-state', publicState()));
});
server.listen(PORT, () => console.log(`🚀 Server on ${PORT}`));