const mongoose = require('mongoose');

const GameSchema = new mongoose.Schema({
  gameId: { type: String, unique: true },
  status: { type: String, default: 'waiting' }, // waiting | running | finished
  calledNumbers: [Number],
  currentCall: Number,
  entryFee: { type: Number, default: 10 },
  prizePool: { type: Number, default: 0 },
  players: [{
    userId: Number,
    firstName: String,
    cartelas: [Number], // cartela ids
    hasBingo: { type: Boolean, default: false }
  }],
  winners: [{
    userId: Number,
    firstName: String,
    cartelaId: Number,
    prize: Number,
    pattern: String
  }],
  startedAt: Date,
  endedAt: Date
});

module.exports = mongoose.model('Game', GameSchema);