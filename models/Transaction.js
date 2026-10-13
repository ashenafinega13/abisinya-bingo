const mongoose = require('mongoose');

const TransactionSchema = new mongoose.Schema({
  userId: { type: Number, index: true },
  type: { type: String, enum: ['deposit', 'withdraw', 'bet', 'win', 'refund'] },
  amount: Number,
  method: String,       // telebirr | cbe
  phone: String,
  sms: String,
  status: { type: String, default: 'pending' }, // pending | approved | rejected
  adminNote: String,
  createdAt: { type: Date, default: Date.now }
});

module.exports = mongoose.model('Transaction', TransactionSchema);