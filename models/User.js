const mongoose = require('mongoose');

const UserSchema = new mongoose.Schema({
  telegramId: { type: Number, unique: true, required: true },
  username: String,
  firstName: String,
  phone: String,
  balance: { type: Number, default: 100 },      // playable balance
  winBalance: { type: Number, default: 0 },     // withdrawable
  language: { type: String, default: 'am' },
  referredBy: Number,
  createdAt: { type: Date, default: Date.now }
});

module.exports = mongoose.model('User', UserSchema);