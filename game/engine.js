const crypto = require('crypto');
const { User, Round } = require('../models');

const COUNTDOWN_SECONDS = 30;
const POST_GAME_SECONDS = 10;
const MAX_CARDS = 3;

// ─── Seeded PRNG ───────────────────────────────────────────────
function mulberry32(seed) {
  let h = seed >>> 0;
  return () => {
    h = Math.imul(h ^ (h >>> 15), h | 1);
    h ^= h + Math.imul(h ^ (h >>> 7), h | 61);
    return ((h ^ (h >>> 14)) >>> 0) / 4294967296;
  };
}

function seedFrom(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

// ─── Card generation ───────────────────────────────────────────
function generateCard(cardNum, roundSeed) {
  const rng = mulberry32(seedFrom(`${roundSeed}:${cardNum}`));
  const cols = [];
  for (let c = 0; c < 5; c++) {
    const min = c * 15 + 1;
    const pool = Array.from({ length: 15 }, (_, i) => min + i);
    for (let i = pool.length - 1; i > 0; i--) {
      const j = Math.floor(rng() * (i + 1));
      [pool[i], pool[j]] = [pool[j], pool[i]];
    }
    cols.push(pool.slice(0, 5).sort((a, b) => a - b));
  }
  cols[2][2] = 'FREE';
  return cols;
}

// ─── Win verification ──────────────────────────────────────────
function checkWin(cardNum, roundSeed, calledNumbers) {
  const cols = generateCard(cardNum, roundSeed);
  const called = new Set(calledNumbers);
  const m = [];
  for (let r = 0; r < 5; r++) {
    const row = [];
    for (let c = 0; c < 5; c++) {
      const v = cols[c][r];
      row.push(v === 'FREE' || called.has(v));
    }
    m.push(row);
  }
  for (let r = 0; r < 5; r++)
    if (m[r].every(Boolean)) return { pattern: 'row', index: r, desc: `Row ${r + 1}` };
  for (let c = 0; c < 5; c++) {
    let ok = true;
    for (let r = 0; r < 5; r++) if (!m[r][c]) { ok = false; break; }
    if (ok) return { pattern: 'col', index: c, desc: `Col ${c + 1}` };
  }
  let d1 = true, d2 = true;
  for (let i = 0; i < 5; i++) {
    if (!m[i][i]) d1 = false;
    if (!m[i][4 - i]) d2 = false;
  }
  if (d1) return { pattern: 'diag1', desc: 'Diagonal 1' };
  if (d2) return { pattern: 'diag2', desc: 'Diagonal 2' };
  if (m[0][0] && m[0][4] && m[4][0] && m[4][4])
    return { pattern: 'corners', desc: '4 Corners' };
  return null;
}

// ─── Room ──────────────────────────────────────────────────────
class Room {
  constructor(id, config, io) {
    this.id = id;
    this.stake = config.stake;
    this.prizePerCard = Math.floor(config.stake * 0.8);
    this.maxCards = config.maxCards ?? MAX_CARDS;
    this.io = io;

    this.phase = 'idle';
    this.roundId = null;
    this.seed = null;
    this.seedHash = null;
    this.calledNumbers = [];
    this.takenCards = {};
    this.remainingTime = COUNTDOWN_SECONDS;
    this.countdownTimer = null;
    this.callTimer = null;
    this.autoOn = false;
    this.callInterval = 5;
    this._autoStartTimer = null;
    this._callBusy = false;
  }

  broadcast(event, payload) {
    this.io.to(`room:${this.id}`).emit(event, payload);
  }

  snapshot() {
    return {
      roomId: this.id,
      stake: this.stake,
      phase: this.phase,
      calledNumbers: this.calledNumbers,
      takenCards: Object.keys(this.takenCards).map(Number),
      remainingTime: this.remainingTime,
      callInterval: this.callInterval,
      autoOn: this.autoOn,
      seedHash: this.seedHash,
      players: new Set(Object.values(this.takenCards).map(String)).size
    };
  }

  clearAutoStart() {
    if (this._autoStartTimer) { clearTimeout(this._autoStartTimer); this._autoStartTimer = null; }
  }

  scheduleAutoStart(delayMs = 5000) {
    this.clearAutoStart();
    this._autoStartTimer = setTimeout(() => {
      if (this.phase === 'idle') this.start();
    }, delayMs);
  }

  async start() {
    if (this.phase !== 'idle') return;
    this.clearAutoStart();
    this.phase = 'countdown';
    this.roundId = crypto.randomBytes(8).toString('hex');
    this.seed = crypto.randomBytes(32).toString('hex');
    this.seedHash = crypto.createHash('sha256').update(this.seed).digest('hex');
    this.calledNumbers = [];
    this.takenCards = {};
    this.remainingTime = COUNTDOWN_SECONDS;

    await Round.create({
      roundId: this.roundId,
      roomId: this.id,
      phase: 'countdown',
      seed: this.seed,
      seedHash: this.seedHash,
      cards: [],
      calledNumbers: [],
      winners: [],
      startedAt: new Date()
    }).catch(() => {});

    this.broadcast('phase_change', { phase: 'countdown', roomId: this.id, seedHash: this.seedHash });
    this.broadcast('timer_tick', { remaining: this.remainingTime });

    this.countdownTimer = setInterval(() => {
      this.remainingTime--;
      this.broadcast('timer_tick', { remaining: this.remainingTime });
      if (this.remainingTime <= 0) {
        clearInterval(this.countdownTimer);
        this.countdownTimer = null;
        this.enterCalling();
      }
    }, 1000);
  }

  enterCalling() {
    if (Object.keys(this.takenCards).length === 0) {
      console.log(`[${this.id}] no cards selected, aborting round`);
      this.abortEmpty();
      return;
    }
    this.phase = 'calling';
    this.broadcast('phase_change', { phase: 'calling', roomId: this.id });
    Round.updateOne({ roundId: this.roundId }, { $set: { phase: 'calling' } }).catch(() => {});
    if (this.autoOn) this.startAutoCalling();
  }

  abortEmpty() {
    if (this.countdownTimer) clearInterval(this.countdownTimer);
    if (this.callTimer) clearInterval(this.callTimer);
    this.countdownTimer = null;
    this.callTimer = null;
    this.phase = 'idle';
    this.roundId = null;
    this.seed = null;
    this.seedHash = null;
    this.calledNumbers = [];
    this.remainingTime = COUNTDOWN_SECONDS;
    this.broadcast('reset_game', { roomId: this.id });
    this.scheduleAutoStart(3000);
  }

  startAutoCalling() {
    if (this.callTimer) clearInterval(this.callTimer);
    this._callBusy = false;
    this.callTimer = setInterval(async () => {
      if (this._callBusy) return;
      this._callBusy = true;
      try { await this.callNumber(); } finally { this._callBusy = false; }
    }, this.callInterval * 1000);
  }

  async callNumber() {
    if (this.phase !== 'calling') return;
    if (this.calledNumbers.length >= 75) { await this.end([]); return; }

    let n;
    do { n = Math.floor(Math.random() * 75) + 1; } while (this.calledNumbers.includes(n));
    this.calledNumbers.push(n);

    this.broadcast('number_called', {
      number: n,
      allCalled: this.calledNumbers,
      remaining: 75 - this.calledNumbers.length
    });

    Round.updateOne({ roundId: this.roundId }, { $set: { calledNumbers: this.calledNumbers } }).catch(() => {});

    // Auto-bingo check on every owned card
    for (const [cardNumStr, userId] of Object.entries(this.takenCards)) {
      const cardNum = Number(cardNumStr);
      const win = checkWin(cardNum, this.seed, this.calledNumbers);
      if (win) { await this.end([{ userId: String(userId), cardNum, ...win }]); return; }
    }
  }

  async end(winners) {
    if (this.phase === 'gameover' || this.phase === 'idle') return;
    if (this.countdownTimer) clearInterval(this.countdownTimer);
    if (this.callTimer) clearInterval(this.callTimer);
    this.countdownTimer = null;
    this.callTimer = null;
    this.phase = 'gameover';

    const cardsInPlay = Object.keys(this.takenCards).length;
    const totalPot = cardsInPlay * this.stake;
    const totalPrize = winners.length > 0 ? cardsInPlay * this.prizePerCard : 0;
    const rake = totalPot - totalPrize;
    const perWinner = winners.length > 0 ? Math.floor(totalPrize / winners.length) : 0;

    for (const w of winners) {
      const user = await User.findOne({ id: w.userId });
      w.name = user?.name || 'Player';
      w.prize = perWinner;
      if (perWinner > 0)
        await User.updateOne({ id: w.userId }, { $inc: { win_balance: perWinner, total_wins: 1 } });
    }

    const playerIds = [...new Set(Object.values(this.takenCards).map(String))];
    if (playerIds.length > 0)
      await User.updateMany({ id: { $in: playerIds } }, { $inc: { total_games: 1 } });

    await Round.updateOne({ roundId: this.roundId }, {
      $set: {
        phase: 'settled',
        endedAt: new Date(),
        settledAt: new Date(),
        winners: winners.map(w => ({
          userId: w.userId, name: w.name, cardNum: w.cardNum, prize: w.prize, pattern: w.desc
        })),
        totalPrize, rake
      }
    }).catch(() => {});

    this.broadcast('game_over', {
      roomId: this.id,
      winners,
      noWinner: winners.length === 0,
      totalPrize,
      winningCard: winners[0]?.cardNum,
      winDesc: winners[0]?.desc,
      winType: winners[0]?.pattern,
      winIndex: winners[0]?.index,
      seed: this.seed,
      seedHash: this.seedHash,
      calledCount: this.calledNumbers.length
    });

    setTimeout(() => this.reset(), POST_GAME_SECONDS * 1000);
  }

  reset() {
    this.phase = 'idle';
    this.roundId = null;
    this.seed = null;
    this.seedHash = null;
    this.calledNumbers = [];
    this.takenCards = {};
    this.remainingTime = COUNTDOWN_SECONDS;
    this.autoOn = false;
    this.broadcast('reset_game', { roomId: this.id });
    this.scheduleAutoStart(5000);
  }

  async refundAndCrash(reason) {
    if (this.countdownTimer) clearInterval(this.countdownTimer);
    if (this.callTimer) clearInterval(this.callTimer);
    this.countdownTimer = null;
    this.callTimer = null;

    const cardCount = Object.keys(this.takenCards).length;
    const userIds = [...new Set(Object.values(this.takenCards).map(String))];

    for (const uid of userIds) {
      const theirCards = Object.entries(this.takenCards).filter(([, v]) => String(v) === uid).length;
      if (theirCards > 0)
        await User.updateOne({ id: uid }, { $inc: { play_balance: theirCards * this.stake } });
    }

    if (this.roundId) {
      await Round.updateOne({ roundId: this.roundId }, {
        $set: { phase: 'crashed', endedAt: new Date(), settledAt: new Date() }
      }).catch(() => {});
    }
    console.log(`[${this.id}] crashed (${reason}): refunded ${cardCount} cards`);
    this.reset();
  }
}

// ─── Manager ───────────────────────────────────────────────────
class GameManager {
  constructor(io) {
    this.io = io;
    this.rooms = new Map();
    this.addRoom('bronze', { stake: 10, maxCards: 3 });
    this.addRoom('silver', { stake: 25, maxCards: 3 });
    this.addRoom('gold',   { stake: 50, maxCards: 2 });
  }

  addRoom(id, cfg) {
    this.rooms.set(id, new Room(id, cfg, this.io));
  }

  get(id) { return this.rooms.get(id); }
  list() { return [...this.rooms.values()].map(r => r.snapshot()); }

  async gracefulShutdown() {
    for (const room of this.rooms.values()) {
      if (room.phase === 'countdown' || room.phase === 'calling') {
        await room.refundAndCrash('server shutdown');
      }
    }
  }
}

module.exports = { GameManager, generateCard, checkWin };