const mongoose = require('mongoose');

const UserSchema = new mongoose.Schema({
  id: { type: String, unique: true, index: true },
  name: String,
  username: String,
  phone: String,
  play_balance: { type: Number, default: 20 }, // 20 ETB Welcome Bonus
  win_balance:  { type: Number, default: 0 },
  total_games:  { type: Number, default: 0 },
  total_wins:   { type: Number, default: 0 },
  registered:   { type: Boolean, default: false },
  lang:         { type: String, default: 'am' },
  referred_by:  { type: String, default: null },
  referral_credited: { type: Boolean, default: false }
}, { collection: 'users', timestamps: true });

const TransactionSchema = new mongoose.Schema({
  id: { type: String, unique: true, index: true },
  type: { type: String, index: true }, // deposit | withdrawal
  user_id: { type: String, index: true },
  user_name: String,
  amount: Number,
  method: String, // Telebirr or CBE
  reference: String,
  phone: String,
  status: { type: String, index: true }, // pending | approved | rejected
  created: String,
  notified: { type: Boolean, default: false }
}, { collection: 'transactions' });

const AdminSessionSchema = new mongoose.Schema({
  token: { type: String, unique: true, index: true },
  expires: Number
}, { collection: 'admin_sessions' });

const RoundSchema = new mongoose.Schema({
  roundId:    { type: String, unique: true, index: true },
  roomId:     String,
  phase:      { type: String, index: true },
  seed:       String,
  seedHash:   String,
  cards:      [{ userId: String, cardNum: Number, ts: Date }],
  calledNumbers: [Number],
  winners:    [{ userId: String, name: String, cardNum: Number, prize: Number, pattern: String }],
  totalPrize: Number,
  rake:       Number,
  startedAt:  Date,
  endedAt:    Date,
  settledAt:  Date
}, { collection: 'rounds' });

const AuditLogSchema = new mongoose.Schema({
  ts: Date, actor: String, action: String, detail: Object
}, { collection: 'audit_logs' });

module.exports = {
  User: mongoose.model('User', UserSchema),
  Transaction: mongoose.model('Transaction', TransactionSchema),
  AdminSession: mongoose.model('AdminSession', AdminSessionSchema),
  Round: mongoose.model('Round', RoundSchema),
  AuditLog: mongoose.model('AuditLog', AuditLogSchema)
};