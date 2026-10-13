const mongoose = require('mongoose');
const GameSchema = new mongoose.Schema({
  gameId: String, status: String,
  calledNumbers: [Number], winners: [Object],
  startedAt: Date, endedAt: Date
});
module.exports = mongoose.model('Game', GameSchema);