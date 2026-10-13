const mongoose = require('mongoose');
const CartelaSchema = new mongoose.Schema({
  cartelaId: Number, grid: [[Number]], owner: Number, gameId: String
});
module.exports = mongoose.model('Cartela', CartelaSchema);