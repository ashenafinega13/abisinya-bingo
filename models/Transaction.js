const mongoose = require('mongoose');

const TxSchema = new mongoose.Schema({
  userId: { type: Number, index: true },
  type: { type: String, enum: ['deposit', 'withdraw', 'bet', 'win', 'refund'] },
  amount: Number,
  method: String,
  phone: String,
  sms: String,
  status: { type: String, default: 'pending' },
  gameId: { type: Number, index: true },
  cartelas: [Number],
  pattern: String,
  createdAt: { type: Date, default: Date.now, index: true }
});

module.exports = mongoose.model('Transaction', TxSchema);