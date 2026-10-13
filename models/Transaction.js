const mongoose = require('mongoose');
const TxSchema = new mongoose.Schema({
  userId: { type: Number, index: true },
  type: { type: String, enum: ['deposit','withdraw','bet','win','refund'] },
  amount: Number, method: String, phone: String, sms: String,
  status: { type: String, default: 'pending' },
  createdAt: { type: Date, default: Date.now }
});
module.exports = mongoose.model('Transaction', TxSchema);