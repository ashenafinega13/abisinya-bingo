const crypto = require('crypto');
const { AdminSession } = require('./models');

function verifyTelegramInitData(initData, botToken) {
  try {
    if (!initData) return null;
    const params = new URLSearchParams(initData);
    const hash = params.get('hash');
    if (!hash) return null;
    params.delete('hash');
    const checkString = [...params.entries()]
      .map(([k, v]) => `${k}=${v}`).sort().join('\n');
    const secret = crypto.createHmac('sha256', 'WebAppData').update(botToken).digest();
    const calc = crypto.createHmac('sha256', secret).update(checkString).digest('hex');
    if (calc !== hash) return null;
    const authDate = parseInt(params.get('auth_date')) || 0;
    if (!authDate || Date.now() / 1000 - authDate > 86400) return null;
    const user = JSON.parse(params.get('user') || '{}');
    return user.id ? user : null;
  } catch { return null; }
}

function requireTelegramUser(botToken) {
  return (req, res, next) => {
    const user = verifyTelegramInitData(req.headers['x-telegram-init-data'], botToken);
    if (!user) return res.status(401).json({ success: false, error: 'Invalid Telegram auth' });
    req.tgUser = user;
    next();
  };
}

async function requireAdmin(req, res, next) {
  const token = req.headers['x-admin-token'];
  if (!token) return res.status(401).json({ success: false, error: 'No token' });
  const s = await AdminSession.findOne({ token });
  if (!s || Date.now() > s.expires)
    return res.status(401).json({ success: false, error: 'Invalid token' });
  req.adminToken = token;
  next();
}

module.exports = { verifyTelegramInitData, requireTelegramUser, requireAdmin };