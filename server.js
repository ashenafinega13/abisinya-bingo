const express = require('express');
const http = require('http');
const { Server } = require('socket.io');
const mongoose = require('mongoose');
const cors = require('cors');
const rateLimit = require('express-rate-limit');
const crypto = require('crypto');
require('dotenv').config();

const dns = require('dns');
dns.setServers(['8.8.8.8', '1.1.1.1']);

const { User, Transaction, AdminSession, Round, AuditLog } = require('./models');
const { GameManager, generateCard } = require('./game/engine');
const { verifyTelegramInitData, requireTelegramUser, requireAdmin } = require('./auth');

const app = express();
app.set('trust proxy', 1); // Trust Render's reverse proxy for accurate rate limiting
const server = http.createServer(app);
const io = new Server(server, { cors: { origin: '*' } });
const PORT = process.env.PORT || 3000;
const BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
const MONGODB_URI = process.env.MONGODB_URI;
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD;

if (!BOT_TOKEN || !MONGODB_URI || !ADMIN_PASSWORD) {
  console.error('Missing env: TELEGRAM_BOT_TOKEN, MONGODB_URI, ADMIN_PASSWORD');
  process.exit(1);
}

app.use(cors());
app.use(express.json({ limit: '64kb' }));
app.use(express.static('public'));

const gameLimiter = rateLimit({ windowMs: 60_000, max: 60 });
const globalLimiter = rateLimit({ windowMs: 60_000, max: 180 });
const loginLimiter = rateLimit({ windowMs: 10 * 60_000, max: 20 });
app.use('/api/game', gameLimiter);
app.use('/api/wallet', gameLimiter);
app.use('/api/admin/login', loginLimiter);
app.use('/api/', globalLimiter);

// ─── Boot recovery ─────────────────────────────────────────────
async function bootRecovery() {
  const cutoff = new Date(Date.now() - 15 * 60_000);
  const stuck = await Round.find({
    phase: { $in: ['countdown', 'calling', 'gameover'] },
    startedAt: { $lt: cutoff }
  });

  for (const r of stuck) {
    if (r.phase === 'gameover' && r.winners?.length > 0) {
      const perWinner = Math.floor((r.totalPrize || 0) / r.winners.length);
      for (const w of r.winners) {
        await User.updateOne({ id: w.userId }, { $inc: { win_balance: perWinner, total_wins: 1 } });
      }
      await Round.updateOne({ _id: r._id }, { $set: { phase: 'settled', settledAt: new Date() } });
    } else {
      const byUser = {};
      for (const c of r.cards) byUser[c.userId] = (byUser[c.userId] || 0) + 1;
      const stake = 10;
      for (const [uid, count] of Object.entries(byUser)) {
        await User.updateOne({ id: uid }, { $inc: { play_balance: count * stake } });
      }
      await Round.updateOne({ _id: r._id }, { $set: { phase: 'crashed', settledAt: new Date() } });
    }
  }
}

mongoose.connect(MONGODB_URI, { serverSelectionTimeoutMS: 10_000, dbName: 'abisinya' })
  .then(async () => {
    console.log('✅ MongoDB connected');
    await bootRecovery();
  })
  .catch(err => { console.error('❌ DB:', err.message); process.exit(1); });

const gameManager = new GameManager(io);

// ─── Admin Auth ────────────────────────────────────────────────
app.post('/api/admin/login', async (req, res) => {
  if (req.body.password === ADMIN_PASSWORD) {
    const token = crypto.randomBytes(32).toString('hex');
    await AdminSession.create({ token, expires: Date.now() + 86_400_000 });
    res.json({ success: true, token });
  } else {
    res.status(401).json({ success: false, error: 'Wrong password' });
  }
});

app.get('/api/admin/verify', requireAdmin, (req, res) => res.json({ success: true }));

app.get('/api/admin/dashboard', requireAdmin, async (req, res) => {
  const [totalPlayers, pendD, pendW, depAgg, wdAgg] = await Promise.all([
    User.countDocuments(),
    Transaction.countDocuments({ type: 'deposit', status: 'pending' }),
    Transaction.countDocuments({ type: 'withdrawal', status: 'pending' }),
    Transaction.aggregate([{ $match: { type: 'deposit', status: 'approved' } }, { $group: { _id: null, t: { $sum: '$amount' } } }]),
    Transaction.aggregate([{ $match: { type: 'withdrawal', status: 'approved' } }, { $group: { _id: null, t: { $sum: '$amount' } } }])
  ]);
  res.json({ success: true, data: {
    totalPlayers, pendingDeposits: pendD, pendingWithdrawals: pendW,
    totalDeposits: depAgg[0]?.t || 0,
    totalWithdrawals: wdAgg[0]?.t || 0,
    rooms: gameManager.list()
  }});
});

// ─── Admin User Management (NEW) ───────────────────────────────
app.delete('/api/admin/users/:id', requireAdmin, async (req, res) => {
  try {
    await User.deleteOne({ id: req.params.id });
    await Transaction.deleteMany({ user_id: req.params.id }); // Cleanup history
    res.json({ success: true });
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

app.post('/api/admin/users/:id/clear', requireAdmin, async (req, res) => {
  try {
    // Reset balances and stats, but keep the user profile
    await User.updateOne({ id: req.params.id }, { 
      $set: { play_balance: 0, win_balance: 0, total_games: 0, total_wins: 0 } 
    });
    await Transaction.deleteMany({ user_id: req.params.id }); // Wipe transaction history
    res.json({ success: true });
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

app.get('/api/admin/users', requireAdmin, async (req, res) => {
  res.json({ success: true, data: await User.find({}).sort({ play_balance: -1 }) });
});

// ─── Admin Transactions ────────────────────────────────────────
app.get('/api/admin/transactions', requireAdmin, async (req, res) => {
  const filter = {};
  if (req.query.type) filter.type = req.query.type;
  if (req.query.status) filter.status = req.query.status;
  if (req.query.method) filter.method = req.query.method; // Filter by CBE or Telebirr
  
  res.json({ success: true, data: await Transaction.find(filter).sort({ created: -1 }).limit(200) });
});

app.post('/api/admin/transactions/:id/approve', requireAdmin, async (req, res) => {
  const txn = await Transaction.findOneAndUpdate(
    { id: req.params.id, status: 'pending' },
    { $set: { status: 'approved' } },
    { new: true }
  );
  if (!txn) return res.status(409).json({ success: false, error: 'Already processed' });
  
  if (txn.type === 'deposit') {
    await User.updateOne({ id: String(txn.user_id) }, { $inc: { play_balance: txn.amount } });
    // REAL-TIME WALLET UPDATE
    io.to(`user:${txn.user_id}`).emit('wallet_updated', { 
      type: 'deposit', 
      amount: txn.amount,
      message: `✅ Deposit Approved! +${txn.amount} ETB added.`
    });
  }
  await AuditLog.create({ ts: new Date(), actor: 'admin', action: 'txn_approve', detail: { id: txn.id, type: txn.type } }).catch(() => {});
  res.json({ success: true });
});

app.post('/api/admin/transactions/:id/reject', requireAdmin, async (req, res) => {
  const txn = await Transaction.findOneAndUpdate(
    { id: req.params.id, status: 'pending' },
    { $set: { status: 'rejected' } },
    { new: true }
  );
  if (!txn) return res.status(409).json({ success: false, error: 'Already processed' });
  
  if (txn.type === 'withdrawal') {
    await User.updateOne({ id: String(txn.user_id) }, { $inc: { win_balance: txn.amount } });
  }
  // REAL-TIME WALLET UPDATE (Refund)
  io.to(`user:${txn.user_id}`).emit('wallet_updated', { 
    type: 'rejected', 
    amount: txn.amount,
    message: `❌ Your ${txn.type} request was rejected.`
  });
  await AuditLog.create({ ts: new Date(), actor: 'admin', action: 'txn_reject', detail: { id: txn.id, type: txn.type } }).catch(() => {});
  res.json({ success: true });
});

// ─── Admin Broadcast ───────────────────────────────────────────
app.post('/api/admin/broadcast', requireAdmin, async (req, res) => {
  const { message } = req.body;
  if (!message) return res.status(400).json({ success: false });
  const users = await User.find({}, { id: 1 });
  let sent = 0;
  for (let i = 0; i < users.length; i++) {
    try {
      const r = await fetch(`https://api.telegram.org/bot${BOT_TOKEN}/sendMessage`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ chat_id: users[i].id, text: `📢 <b>ማስታወቂያ</b>\n\n${message}`, parse_mode: 'HTML' })
      });
      const d = await r.json();
      if (d.ok) sent++;
    } catch (e) {}
    if (i % 25 === 24) await new Promise(r => setTimeout(r, 1000));
  }
  res.json({ success: true, sent });
});

// ─── Wallet & Game Endpoints ───────────────────────────────────
const tg = requireTelegramUser(BOT_TOKEN);

app.get('/api/wallet/me', tg, async (req, res) => {
  const u = await User.findOne({ id: String(req.tgUser.id) });
  res.json({ success: true, data: u || { play_balance: 0, win_balance: 0 } });
});

app.get('/api/wallet/history', tg, async (req, res) => {
  res.json({ success: true, data: await Transaction.find({ user_id: String(req.tgUser.id) }).sort({ created: -1 }).limit(50) });
});

app.post('/api/game/select-card', tg, async (req, res) => {
  const userId = String(req.tgUser.id);
  const { roomId, cardNum } = req.body;
  const room = gameManager.get(roomId);
  if (!room) return res.status(400).json({ success: false, error: 'Unknown room' });
  if (!Number.isInteger(cardNum) || cardNum < 1 || cardNum > 600)
    return res.status(400).json({ success: false, error: 'Invalid card' });
  if (room.phase !== 'countdown')
    return res.status(400).json({ success: false, error: 'Selection closed' });

  const existingOwner = room.takenCards[cardNum];
  if (existingOwner && String(existingOwner) !== userId)
    return res.status(409).json({ success: false, error: 'Card already taken' });
  if (String(existingOwner) === userId)
    return res.json({ success: true, alreadyOwned: true });

  const myCount = Object.values(room.takenCards).filter(v => String(v) === userId).length;
  if (myCount >= room.maxCards)
    return res.status(400).json({ success: false, error: `Max ${room.maxCards} cards` });

  const updated = await User.findOneAndUpdate(
    { id: userId, play_balance: { $gte: room.stake } },
    { $inc: { play_balance: -room.stake } },
    { new: true }
  );
  if (!updated) return res.status(400).json({ success: false, error: 'Insufficient balance' });

  room.takenCards[cardNum] = userId;

  await Round.updateOne(
    { roundId: room.roundId },
    { $push: { cards: { userId, cardNum, ts: new Date() } } }
  ).catch(() => {});

  io.to(`room:${roomId}`).emit('taken_cards', Object.keys(room.takenCards).map(Number));
  res.json({
    success: true,
    data: {
      play_balance: updated.play_balance,
      win_balance: updated.win_balance,
      card: { cardNum, layout: generateCard(cardNum, room.seed) }
    }
  });
});

app.post('/api/game/deselect-card', tg, async (req, res) => {
  const userId = String(req.tgUser.id);
  const { roomId, cardNum } = req.body;
  const room = gameManager.get(roomId);
  if (!room || String(room.takenCards[cardNum]) !== userId)
    return res.status(403).json({ success: false, error: 'Not your card' });
  if (room.phase !== 'countdown')
    return res.status(400).json({ success: false, error: 'Selection closed' });

  delete room.takenCards[cardNum];
  const updated = await User.findOneAndUpdate({ id: userId }, { $inc: { play_balance: room.stake } }, { new: true });
  io.to(`room:${roomId}`).emit('taken_cards', Object.keys(room.takenCards).map(Number));
  res.json({ success: true, data: { play_balance: updated.play_balance } });
});

app.get('/api/leaderboard', async (req, res) => {
  const users = await User.find().sort({ win_balance: -1 }).limit(10);
  res.json({ success: true, data: users.map(u => ({ name: u.name, win_balance: u.win_balance })) });
});

app.get('/healthz', (req, res) => res.json({
  status: 'ok',
  rooms: gameManager.list().map(r => ({ id: r.roomId, phase: r.phase, cards: r.takenCards.length }))
}));

// ─── Admin Room Controls ───────────────────────────────────────
app.post('/api/admin/rooms/:id/start', requireAdmin, async (req, res) => {
  const room = gameManager.get(req.params.id);
  if (!room) return res.status(404).json({ success: false });
  await room.start();
  res.json({ success: true });
});

app.post('/api/admin/rooms/:id/stop', requireAdmin, async (req, res) => {
  const room = gameManager.get(req.params.id);
  if (!room) return res.status(404).json({ success: false });
  await room.refundAndCrash('admin stop');
  res.json({ success: true });
});

app.post('/api/admin/rooms/:id/call', requireAdmin, async (req, res) => {
  const room = gameManager.get(req.params.id);
  if (!room || room.phase !== 'calling') return res.status(400).json({ success: false });
  await room.callNumber();
  res.json({ success: true });
});

app.post('/api/admin/rooms/:id/auto', requireAdmin, (req, res) => {
  const room = gameManager.get(req.params.id);
  if (!room) return res.status(404).json({ success: false });
  const { autoOn, interval } = req.body;
  if (typeof autoOn !== 'undefined') room.autoOn = !!autoOn;
  if (interval) room.callInterval = Number(interval);
  if (room.autoOn && room.phase === 'calling') room.startAutoCalling();
  else if (!room.autoOn && room.callTimer) { clearInterval(room.callTimer); room.callTimer = null; }
  res.json({ success: true });
});

// ─── Socket ────────────────────────────────────────────────────
io.use((socket, next) => {
  const user = verifyTelegramInitData(socket.handshake.auth?.initData, BOT_TOKEN);
  if (!user) return next(new Error('unauthorized'));
  socket.userId = String(user.id);
  next();
});

io.on('connection', socket => {
  socket.join(`user:${socket.userId}`);

  socket.on('subscribe', ({ roomId }) => {
    const room = gameManager.get(roomId);
    if (!room) return;
    socket.leaveAll();
    socket.join(`room:${roomId}`);
    socket.join(`user:${socket.userId}`); 

    const myCards = Object.entries(room.takenCards)
      .filter(([, uid]) => String(uid) === socket.userId)
      .map(([n]) => Number(n));

    socket.emit('init_state', {
      ...room.snapshot(),
      myCards,
      cards: (room.phase !== 'idle' && room.seed)
        ? myCards.reduce((acc, n) => { acc[n] = generateCard(n, room.seed); return acc; }, {})
        : {}
    });
  });

  socket.on('claim_bingo', async (data) => {
    const room = gameManager.get('main');
    if (!room) return;
    const result = await room.claimBingo(socket.userId, data.cardNum);
    if (!result.success) socket.emit('card_error', { message: result.msg });
  });

  socket.on('unsubscribe', () => socket.leaveAll());
});

// ─── Graceful Shutdown ─────────────────────────────────────────
let shuttingDown = false;
async function shutdown(signal) {
  if (shuttingDown) return;
  shuttingDown = true;
  console.log(`[shutdown] ${signal}`);
  try { await gameManager.gracefulShutdown(); } catch (e) { console.error(e); }
  server.close(() => mongoose.connection.close().then(() => process.exit(0)));
  setTimeout(() => process.exit(1), 15_000);
}
process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT',  () => shutdown('SIGINT'));

server.listen(PORT, () => console.log(`🚀 Server on port ${PORT}`));