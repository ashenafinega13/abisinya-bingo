const mongoose = require('mongoose');

const UserSchema = new mongoose.Schema({
  telegramId: { type: Number, unique: true, required: true, index: true },
  username: String,
  firstName: String,
  phone: String,
  balance: { type: Number, default: 100 },
  winBalance: { type: Number, default: 0 },
  language: { type: String, default: 'am' },
  referredBy: Number,
  // NEW aggregates for leaderboard
  totalWins: { type: Number, default: 0 },
  totalEarnings: { type: Number, default: 0 },
  totalGames: { type: Number, default: 0 },
  createdAt: { type: Date, default: Date.now, index: true }
});

module.exports = mongoose.model('User', UserSchema);