const mongoose = require('mongoose');

const TxSchema = new mongoose.Schema({
  userId: { type: Number, index: true },
  type: { type: String, enum: ['deposit', 'withdraw', 'bet', 'win', 'refund'] },
  amount: Number,
  method: String,       // telebirr | cbe | game
  phone: String,
  sms: String,
  status: { type: String, default: 'pending' },
  // NEW fields for game history
  gameId: { type: Number, index: true },        // roundId
  cartelas: [Number],                            // cartela ids involved
  pattern: String,                                // '4-corners' etc
  createdAt: { type: Date, default: Date.now, index: true }
});

TxSchema.index({ userId: 1, createdAt: -1 });
TxSchema.index({ type: 1, status: 1 });

module.exports = mongoose.model('Transaction', TxSchema);