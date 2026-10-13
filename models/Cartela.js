const mongoose = require('mongoose');

// B=1-15, I=16-30, N=31-45, G=46-60, O=61-75
const CartelaSchema = new mongoose.Schema({
  cartelaId: { type: Number, unique: true }, // 1..N
  grid: [[Number]],  // 5x5, center = 0 (FREE)
  owner: Number,     // telegramId of owner during a game
  gameId: String
});

module.exports = mongoose.model('Cartela', CartelaSchema);