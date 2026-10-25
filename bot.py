import telebot, os, time, random, string, re, threading
from telebot import types
from dotenv import load_dotenv
from datetime import datetime
from pymongo import MongoClient
from http.server import HTTPServer, BaseHTTPRequestHandler

import dns.resolver
dns.resolver.default_resolver = dns.resolver.Resolver(configure=False)
dns.resolver.default_resolver.nameservers = ['8.8.8.8', '1.1.1.1']
dns.resolver.default_resolver.lifetime = 30.0

load_dotenv()

BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
WEB_APP_URL = os.getenv('WEB_APP_URL') or os.getenv('WEBAPP_URL', 'https://example.com')
MONGODB_URI = os.getenv('MONGODB_URI')
ADMIN_IDS = [int(x) for x in os.getenv('ADMIN_ID', '5925033073').split(',') if x.strip()]

MIN_WITHDRAW = 100
MIN_DEPOSIT = 10
REFERRAL_BONUS = 30
TELEBIRR_NUMBER = "0968940123"
CBE_NUMBER = "1000390803005"
ACCOUNT_NAME = "tazebew"
SUPPORT_USERNAME = "Tazikes"

if not BOT_TOKEN or not MONGODB_URI:
    print("❌ Missing env"); exit()

bot = telebot.TeleBot(BOT_TOKEN)

try:
    mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=30000, connectTimeoutMS=30000)
    mongo_client.admin.command('ping')
    db = mongo_client.get_database('abisinya')
    users_col = db['users']
    txns_col = db['transactions']
    print("✅ MongoDB connected (Bot)")
except Exception as e:
    print(f"❌ DB error: {e}"); exit()

def get_user(uid): return users_col.find_one({"id": str(uid)})

def ensure_user(message):
    uid = str(message.from_user.id)
    user = get_user(uid)
    if not user:
        u = message.from_user
        full_name = f"{u.first_name or ''} {u.last_name or ''}".strip() or f"Player {uid}"
        user = {
            "id": uid, "name": full_name, "username": u.username or "",
            "phone": "", "play_balance": 20.0, "win_balance": 0.0,
            "total_games": 0, "total_wins": 0,
            "referral_code": uid, "referred_by": None, "referral_credited": False,
            "lang": "am", "registered": False,
            "registered_at": datetime.utcnow().isoformat()
        }
        users_col.insert_one(user)
    return user

def gen_txn_id(): return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

def setup_bot_menu():
    commands = [
        types.BotCommand("start", "Start"),
        types.BotCommand("play", "Play Bingo"),
        types.BotCommand("balance", "Balance"),
        types.BotCommand("deposit", "Deposit"),
        types.BotCommand("withdraw", "Withdraw"),
        types.BotCommand("invite", "Invite"),
        types.BotCommand("history", "History"),
    ]
    try:
        bot.set_my_commands(commands)
        bot.set_chat_menu_button(menu_button=types.MenuButtonCommands())
    except: pass

# Translations (Removed rooms)
T = {
    'am': {'welcome': "🎉 እንኳን ወደ Abisinya Bingo በደህና መጡ!", 'name': "ስም", 'id': "መለያ", 'balance': "ባላንስ", 'choose_below': "ከታች ካሉት አማራጮች ይምረጡ 👇", 'play': "🎯 Abisinya Bingo ይጫወቱ", 'deposit': "💰 ገንዘብ ማስገባት", 'withdraw': "💸 ገንዘብ ማውጣት", 'balance_btn': "🏦 ባላንስ ማየት", 'invite': "👥 ጓደኛ መጋበዝ", 'history': "📜 ታሪክ", 'support': "💬 ድጋፍ", 'register': "🔢 መመዝገብ", 'language': "🌐 ቋንቋ", 'help': "ℹ️ እርዳታ", 'leaderboard': "🏆 ደረጃ", 'your_balance': "የእርስዎ ባላንስ", 'play_bal': "🎮 Play", 'win_bal': "🏆 Win", 'total': "💰 ጠቅላላ", 'share_contact': "📱 ግንኙነት አጋራ", 'share_contact_prompt': "ከታች ያለውን <b>📱 ግንኙነት አጋራ</b> ቁልፍ ይጫኑ:", 'registered': "✅ በተሳካ ሁኔታ ተመዝግበዋል!", 'already_registered': "✅ አስቀድመው ተመዝግበዋል!", 'deposit_choose': "💳 የክፍያ ዘዴ ይምረጡ፦", 'send_txn': "📝 የTransaction/SMS ጽሑፍ ይላኩ", 'txn_example': "ለምሳሌ: <code>TB123456789 500</code>", 'deposit_sent': "✅ የገቢ ጥያቄ ተልኳል!", 'play_below': "👇 ጨዋታውን ለመጀመር ከታች ያለውን ሜኑ ይጫኑ:", 'withdraw_choose': "💸 የወጭ ዘዴ ይምረጡ:", 'to_self': "👤 ወደ ራስዎ", 'to_other': "👥 ወደ ሌላ ቁጥር", 'insufficient': "❌ Insufficient Balance", 'min_withdraw': "ዝቅተኛው የወጭ መጠን: {amt} ETB", 'wd_approved_req': "✅ Your withdrawal {amt} birr request approved", 'send_amount': "💰 የሚወጣውን መጠን ይላኩ (ቢያንስ {min} ETB):", 'send_phone': "📱 የቴሌብር ቁጥር ይላኩ:", 'invalid_amount': "❌ ትክክለኛ ቁጥር ያስገቡ።", 'invalid_phone': "❌ ትክክለኛ ቁጥር ያስገቡ።", 'unknown': "❓ ያልተለየ ትዕዛዝ።\n/start ይጫኑ።", 'pick_lang': "🌐 ቋንቋ ይምረጡ", 'lang_changed': "🇪🇹 ቋንቋ ወደ አማርኛ ተቀይሯል።", 'your_history': "የ{name} ታሪክ", 'deposits': "💰 ገቢዎች:", 'withdrawals': "💸 ወጮች:", 'no_txn': "📭 እስካሁን ግብይት የለም።", 'leaderboard_title': "🏆 ከፍተኛ አሸናፊዎች", 'no_winners': "📭 እስካሁን ማንም አልተመዘገበም።", 'support_msg': "ለእርዳታ ያግኙን", 'invite_msg': "👥 ጓደኞችዎን ይጋብዙ!", 'invite_bonus': "✨ ለእያንዳንዱ ጓደኛ <b>30 ETB</b> ያግኙ!", 'your_link': "🔗 የእርስዎ ሊንክ:", 'txn_ref': "የTransaction ቁጥር:", 'txn_pending': "⏳ Admin እስኪያጸድቅ ይጠብቁ።", 'not_registered': "❌ መጀመሪያ ማስመዝገብ ያስፈልጋል!", 'registered_phone': "📱 የተመዘገበ ስልክ:", 'help_title': "📋 የእርዳታ ማዕከል", 'help_list': "/start - ቦቱን ጀምር\n/play - ቢንጎ ተጫወት\n/balance - ባላንስ ተመልከት\n/deposit - ገንዘብ አስገባ\n/withdraw - ገንዘብ አውጣ\n/register - ስልክ አስመዝግብ\n/invite - ጓደኛ ጋብዝ\n/history - ታሪክ", 'ref_credited': "🎉 <b>አዲስ ጓደኛ ጋብዘዋል!</b>\n\n+{bonus} ETB ተጨምሯል።"},
    'en': {'welcome': "🎉 Welcome to Abisinya Bingo!", 'name': "Name", 'id': "ID", 'balance': "Balance", 'choose_below': "Choose below 👇", 'play': "🎯 Play Bingo", 'deposit': "💰 Deposit", 'withdraw': "💸 Withdraw", 'balance_btn': "🏦 Balance", 'invite': "👥 Invite", 'history': "📜 History", 'support': "💬 Support", 'register': "🔢 Register", 'language': "🌐 Language", 'help': "ℹ️ Help", 'leaderboard': "🏆 Rank", 'your_balance': "Balance", 'play_bal': "🎮 Play", 'win_bal': "🏆 Win", 'total': "💰 Total", 'share_contact': "📱 Share Contact", 'share_contact_prompt': "Tap <b>📱 Share Contact</b>:", 'registered': "✅ Registered!", 'already_registered': "✅ Already registered!", 'deposit_choose': "💳 Choose method:", 'send_txn': "📝 Send TXN text", 'txn_example': "Ex: <code>TB123456789 500</code>", 'deposit_sent': "✅ Deposit sent!", 'play_below': "👇 Tap the Menu below:", 'withdraw_choose': "💸 Withdraw method:", 'to_self': "👤 Self", 'to_other': "👥 Other", 'insufficient': "❌ Insufficient", 'min_withdraw': "Min: {amt} ETB", 'wd_approved_req': "✅ Withdrawal {amt} birr approved", 'send_amount': "💰 Amount (min {min} ETB):", 'send_phone': "📱 Telebirr phone:", 'invalid_amount': "❌ Invalid number.", 'invalid_phone': "❌ Invalid phone.", 'unknown': "❓ Unknown.\n/start", 'pick_lang': "🌐 Choose Language", 'lang_changed': "🇬🇧 English set.", 'your_history': "{name}'s History", 'deposits': "💰 Deposits:", 'withdrawals': "💸 Withdrawals:", 'no_txn': "📭 No transactions.", 'leaderboard_title': "🏆 Top Winners", 'no_winners': "📭 No one yet.", 'support_msg': "Contact us", 'invite_msg': "👥 Invite!", 'invite_bonus': "✨ Get <b>30 ETB</b>!", 'your_link': "🔗 Link:", 'txn_ref': "TXN ID:", 'txn_pending': "⏳ Pending...", 'not_registered': "❌ Register first!", 'registered_phone': "📱 Phone:", 'help_title': "📋 Help Center", 'help_list': "/start - Start\n/play - Play Bingo\n/balance - Balance\n/deposit - Deposit\n/withdraw - Withdraw\n/register - Register\n/invite - Invite\n/history - History", 'ref_credited': "🎉 <b>New friend joined!</b>\n\n+{bonus} ETB credited."},
    'ti': {'welcome': "🎉 እንቋዕ ናብ Abisinya Bingo ብደሓን መጻእኩም!", 'name': "ስም", 'id': "መለለዪ", 'balance': "ባላንስ", 'choose_below': "ካብ ኣማራጺታት ትሕቲ ምረጹ 👇", 'play': "🎯 Abisinya Bingo ተጻወት", 'deposit': "💰 ገንዘብ ኣእቱ", 'withdraw': "💸 ገንዘብ ኣውጽእ", 'balance_btn': "🏦 ባላንስ ርአ", 'invite': "👥 ኣሕዋት ዓድም", 'history': "📜 ታሪኽ", 'support': "💬 ደገፍ", 'register': "🔢 ተመዝገብ", 'language': "🌐 ቋንቋ", 'help': "ℹ️ ሓገዝ", 'leaderboard': "🏆 ደረጃ", 'your_balance': "ባላንስካ", 'play_bal': "🎮 Play", 'win_bal': "🏆 Win", 'total': "💰 ጠቕላላ", 'share_contact': "📱 ርክብ ኣካፍል", 'share_contact_prompt': "ነቲ <b>📱 ርክብ ኣካፍል</b> ጠውቕ:", 'registered': "✅ ብዓወት ተመዝጊብካ!", 'already_registered': "✅ ቀድሚሁ ተመዝጊብካ!", 'deposit_choose': "💳 ኣገባብ ክፍሊት ምረጽ:", 'send_txn': "📝 ጽሑፍ Transaction/SMS ስደድ", 'txn_example': "ኣብነት: <code>TB123456789 500</code>", 'deposit_sent': "✅ ሕቶ ኣታዊ ተላኢኹ!", 'play_below': "👇 ነቲ ሜኑ ቁልፊ ጠውቕ:", 'withdraw_choose': "💸 ኣገባብ ወጻኢ ምረጽ:", 'to_self': "👤 ናብ ርእስኻ", 'to_other': "👥 ናብ ካልእ ቁጽሪ", 'insufficient': "❌ Insufficient", 'min_withdraw': "ትሕቲ ወጻኢ: {amt} ETB", 'wd_approved_req': "✅ ሕቶ ወጻኢኻ {amt} birr ተቐቢሉ", 'send_amount': "💰 ወጻኢ መጠን ስደድ (min {min} ETB):", 'send_phone': "📱 ቁጽሪ Telebirr ስደድ:", 'invalid_amount': "❌ ቅኑዕ ቁጽሪ ኣእቱ።", 'invalid_phone': "❌ ቅኑዕ ቁጽሪ ኣእቱ።", 'unknown': "❓ ዘይተፈልጠ ትእዛዝ።\n/start ጠውቕ።", 'pick_lang': "🌐 ቋንቋ ምረጽ", 'lang_changed': "🇪🇹 ቋንቋ ናብ ትግርኛ ተቐይሩ።", 'your_history': "ታሪኽ {name}", 'deposits': "💰 ኣታዊታት:", 'withdrawals': "💸 ወጻኢታት:", 'no_txn': "📭 ክሳብ ሕጂ ግብይት የለን።", 'leaderboard_title': "🏆 ላዕለዎት ተዓወትቲ", 'no_winners': "📭 ክሳብ ሕጂ ዝተመዝገበ የለን።", 'support_msg': "ንሓገዝ ርኸቡና", 'invite_msg': "👥 ኣሕዋትካ ዓድም!", 'invite_bonus': "✨ ንነፍሲ ወከፍ ዓርኪ <b>30 ETB</b> ርኸብ!", 'your_link': "🔗 ሊንክካ:", 'txn_ref': "ቁጽሪ Transaction:", 'txn_pending': "⏳ ንፈቓድ admin ተጸበ።", 'not_registered': "❌ ቅድም ተመዝገብ!", 'registered_phone': "📱 ዝተመዝገበ ቁጽሪ:", 'help_title': "📋 ማእከል ሓገዝ", 'help_list': "/start - ጀምር\n/play - ተጻወት\n/balance - ባላንስ\n/deposit - ኣእቱ\n/withdraw - ኣውጽእ\n/register - ተመዝገብ\n/invite - ዓድም\n/history - ታሪኽ", 'ref_credited': "🎉 <b>ሓድሽ ዓርኪ ዓዲምካ!</b>\n\n+{bonus} ETB ተወሲኹ።"},
    'om': {'welcome': "🎉 Baga gara Abisinya Bingo nagaan dhuftan!", 'name': "Maqaa", 'id': "Eenyummaa", 'balance': "Baalaansii", 'choose_below': "Filannoo gadii keessaa filadhu 👇", 'play': "🎯 Abisinya Bingo Taphadhu", 'deposit': "💰 Maallaqa Galchi", 'withdraw': "💸 Maallaqa Baas", 'balance_btn': "🏦 Baalaansii Ilaali", 'invite': "👥 Hiriyoota Affeeri", 'history': "📜 Seenaa", 'support': "💬 Deeggarsa", 'register': "🔢 Galmaa'i", 'language': "🌐 Afaan", 'help': "ℹ️ Gargaarsa", 'leaderboard': "🏆 Sadarkaa", 'your_balance': "Baalaansii Kee", 'play_bal': "🎮 Play", 'win_bal': "🏆 Win", 'total': "💰 Waliigala", 'share_contact': "📱 Quunnamtii Qoodi", 'share_contact_prompt': "Isaa <b>📱 Quunnamtii Qoodi</b> tuqi:", 'registered': "✅ Milkaa'inaan galmaa'te!", 'already_registered': "✅ Duraan galmaa'teerta!", 'deposit_choose': "💳 Mala kaffaltii filadhu:", 'send_txn': "📝 Barruu Transaction/SMS ergi", 'txn_example': "Fkn: <code>TB123456789 500</code>", 'deposit_sent': "✅ Gaaffiin galii ergame!", 'play_below': "👇 Menu button tuqi:", 'withdraw_choose': "💸 Mala baasii filadhu:", 'to_self': "👤 Ofiif", 'to_other': "👥 Lakkoofsa Biroof", 'insufficient': "❌ Insufficient", 'min_withdraw': "Baasii xiqqaan: {amt} ETB", 'wd_approved_req': "✅ Gaaffiin baasii kee {amt} birr fudhatame", 'send_amount': "💰 Hanga baasii ergi (min {min} ETB):", 'send_phone': "📱 Lakkoofsa Telebirr ergi:", 'invalid_amount': "❌ Lakkoofsa sirrii galchi.", 'invalid_phone': "❌ Lakkoofsa sirrii galchi.", 'unknown': "❓ Ajaja hin beekamne.\n/start tuqi.", 'pick_lang': "🌐 Afaan filadhu", 'lang_changed': "🇪🇹 Afaan gara Afaan Oromoo jijjiirame.", 'your_history': "Seenaa {name}", 'deposits': "💰 Galiwwan:", 'withdrawals': "💸 Baasiiwwan:", 'no_txn': "📭 Ammaatti daldala hin jiru.", 'leaderboard_title': "🏆 Mo'attoota Olii", 'no_winners': "📭 Ammaatti namni hin galmaa'ne.", 'support_msg': "Gargaarsaaf nu quunnamaa", 'invite_msg': "👥 Hiriyoota kee affeeri!", 'invite_bonus': "✨ Hiriyoota tokkoon tokkoon <b>30 ETB</b> argadhu!", 'your_link': "🔗 Liinkii kee:", 'txn_ref': "ID Transaction:", 'txn_pending': "⏳ Eegaa admin mirkaneessu.", 'not_registered': "❌ Duraan galmaa'i!", 'registered_phone': "📱 Bilbila galmaa'e:", 'help_title': "📋 Giddu-gala Gargaarsa", 'help_list': "/start - Jalqabi\n/play - Taphadhu\n/balance - Baalaansii\n/deposit - Galchi\n/withdraw - Baasi\n/register - Galmaa'i\n/invite - Affeeri\n/history - Seenaa", 'ref_credited': "🎉 <b>Hiriyyaan haaraan dhufe!</b>\n\n+{bonus} ETB ida'ame."}
}

class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'OK')
    def log_message(self, *args): pass

def _start_health_server():
    port = int(os.getenv('PORT', '8080'))
    try: HTTPServer(('0.0.0.0', port), _HealthHandler).serve_forever()
    except Exception as e: print(f"Health server error: {e}")

threading.Thread(target=_start_health_server, daemon=True).start()

def t(uid, key, **kwargs):
    user = get_user(uid) or {}
    lang = user.get('lang', 'am')
    text = T.get(lang, T['am']).get(key, T['am'].get(key, key))
    if kwargs:
        try: return text.format(**kwargs)
        except: return text
    return text

def get_action(text):
    if not text: return None
    if '🎯' in text or 'Bingo' in text or 'Taphadhu' in text: return 'play'
    if '💰' in text or 'ማስገባት' in text or 'Deposit' in text or 'Galchi' in text: return 'deposit'
    if '💸' in text or 'ማውጣት' in text or 'Withdraw' in text or 'Baas' in text: return 'withdraw'
    if '🏦' in text or 'ባላንስ' in text or 'Balance' in text or 'Baalaansii' in text: return 'balance_btn'
    if '👥' in text or 'መጋበዝ' in text or 'Invite' in text or 'Affeeri' in text: return 'invite'
    if '📜' in text or 'ታሪክ' in text or 'History' in text or 'Seenaa' in text: return 'history'
    if '💬' in text or 'ድጋፍ' in text or 'Support' in text or 'Deeggarsa' in text: return 'support'
    if '🔢' in text or 'መመዝገብ' in text or 'Register' in text or 'Galmaa' in text: return 'register'
    if '🌐' in text or 'ቋንቋ' in text or 'Language' in text or 'Afaan' in text: return 'language'
    if 'ℹ️' in text or 'እርዳታ' in text or 'Help' in text or 'Gargaarsa' in text: return 'help'
    if '🏆' in text or 'ደረጃ' in text or 'Rank' in text or 'Sadarkaa' in text: return 'leaderboard'
    return None

def main_reply_keyboard(uid):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(types.KeyboardButton(text=t(uid, 'play'), web_app=types.WebAppInfo(url=WEB_APP_URL)))
    markup.add(types.KeyboardButton(t(uid, 'deposit')), types.KeyboardButton(t(uid, 'withdraw')))
    markup.add(types.KeyboardButton(t(uid, 'balance_btn')), types.KeyboardButton(t(uid, 'invite')))
    markup.add(types.KeyboardButton(t(uid, 'history')), types.KeyboardButton(t(uid, 'support')))
    markup.add(types.KeyboardButton(t(uid, 'register')), types.KeyboardButton(t(uid, 'language')))
    markup.add(types.KeyboardButton(t(uid, 'help')), types.KeyboardButton(t(uid, 'leaderboard')))
    return markup

def webapp_inline_keyboard(uid):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(text=t(uid, 'play'), web_app=types.WebAppInfo(url=WEB_APP_URL)))
    return markup

def contact_button(uid):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton(text=t(uid, 'share_contact'), request_contact=True))
    return markup

def notify_admins(text, skip_id=None):
    for aid in ADMIN_IDS:
        if skip_id and str(aid) == str(skip_id): continue
        try: bot.send_message(aid, text, parse_mode='HTML')
        except: pass

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user = ensure_user(message)
    uid = str(message.from_user.id)
    args = message.text.split()
    if len(args) > 1 and not user.get('referred_by') and not user.get('referral_credited'):
        ref_code = args[1].strip()
        if ref_code and ref_code != uid:
            referrer = users_col.find_one({"referral_code": ref_code})
            if referrer:
                users_col.update_one({"id": uid}, {"$set": {"referred_by": ref_code, "referral_credited": True}})
                users_col.update_one({"id": referrer['id']}, {"$inc": {"play_balance": REFERRAL_BONUS}})
                try: bot.send_message(int(referrer['id']), t(referrer['id'], 'ref_credited', bonus=REFERRAL_BONUS), parse_mode='HTML')
                except: pass

    bot.send_message(message.chat.id, f"{t(uid,'welcome')}\n\n👤 {t(uid,'name')}: <b>{user['name']}</b>\n🆔 {t(uid,'id')}: <code>{user['id']}</code>\n💰 {t(uid,'balance')}: <b>{user['play_balance']:.2f} ETB</b>\n\n{t(uid,'choose_below')}", reply_markup=main_reply_keyboard(uid), parse_mode='HTML')
    bot.send_message(message.chat.id, t(uid,'play_below'), reply_markup=webapp_inline_keyboard(uid), parse_mode='HTML')

@bot.message_handler(commands=['play'])
def cmd_play(message):
    uid = str(message.from_user.id); ensure_user(message)
    bot.send_message(message.chat.id, t(uid,'play_below'), reply_markup=webapp_inline_keyboard(uid), parse_mode='HTML')

@bot.message_handler(commands=['balance'])
def cmd_balance(message):
    uid = str(message.from_user.id); u = ensure_user(message)
    bot.send_message(message.chat.id, f"🏦 <b>{t(uid,'your_balance')}</b>\n\n{t(uid,'play_bal')}: <b>{u['play_balance']:.2f} ETB</b>\n{t(uid,'win_bal')}: <b>{u['win_balance']:.2f} ETB</b>\n{t(uid,'total')}: <b>{u['play_balance'] + u['win_balance']:.2f} ETB</b>", parse_mode='HTML')

@bot.message_handler(commands=['invite'])
def cmd_invite(message):
    uid = str(message.from_user.id); u = ensure_user(message)
    try: bot_username = bot.get_me().username
    except: bot_username = "Ethiobongo_bot"
    link = f"https://t.me/{bot_username}?start={u['referral_code']}"
    bot.send_message(message.chat.id, f"{t(uid,'invite_msg')}\n\n{t(uid,'invite_bonus')}\n\n{t(uid,'your_link')}\n<code>{link}</code>", parse_mode='HTML')

@bot.message_handler(commands=['language'])
def handle_language(message):
    uid = str(message.from_user.id); ensure_user(message)
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("🇪🇹 አማርኛ", callback_data="lang_am"), types.InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"))
    markup.add(types.InlineKeyboardButton("🇪🇹 ትግርኛ", callback_data="lang_ti"), types.InlineKeyboardButton("🇪🇹 Afaan Oromoo", callback_data="lang_om"))
    bot.send_message(message.chat.id, t(uid,'pick_lang'), reply_markup=markup, parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: call.data.startswith('lang_'))
def cb_language(call):
    uid = str(call.from_user.id); lang = call.data.replace('lang_', '')
    users_col.update_one({"id": uid}, {"$set": {"lang": lang}}, upsert=True)
    bot.answer_callback_query(call.id, "✅")
    bot.send_message(call.message.chat.id, t(uid,'lang_changed'))
    bot.send_message(call.message.chat.id, t(uid,'choose_below'), reply_markup=main_reply_keyboard(uid))

@bot.message_handler(commands=['register'])
def handle_register(message):
    uid = str(message.from_user.id); u = ensure_user(message)
    if u.get('registered'):
        bot.send_message(message.chat.id, f"{t(uid,'already_registered')}\n\n👤 {u['name']}\n📱 {u.get('phone','N/A')}", parse_mode='HTML', reply_markup=main_reply_keyboard(uid)); return
    bot.send_message(message.chat.id, f"🔢 <b>{t(uid,'register')}</b>\n\n{t(uid,'share_contact_prompt')}", reply_markup=contact_button(uid), parse_mode='HTML')

@bot.message_handler(content_types=['contact'])
def handle_contact(message):
    uid = str(message.from_user.id); u = ensure_user(message)
    if message.contact.user_id != message.from_user.id:
        bot.send_message(message.chat.id, "❌ Share your own contact only.", reply_markup=main_reply_keyboard(uid)); return
    phone = message.contact.phone_number
    if not phone.startswith('+'): phone = '+' + phone
    if u.get('registered'):
        bot.send_message(message.chat.id, t(uid,'already_registered'), reply_markup=main_reply_keyboard(uid)); return
    users_col.update_one({"id": uid}, {"$set": {"phone": phone, "registered": True}})
    u = get_user(uid)
    bot.send_message(message.chat.id, f"{t(uid,'registered')}\n\n👤 {u['name']}\n📱 {phone}\n💰 {t(uid,'balance')}: <b>{u['play_balance']:.2f} ETB</b>", parse_mode='HTML', reply_markup=main_reply_keyboard(uid))

def parse_deposit_text(text):
    text_clean = (text or "").strip()
    if not text_clean: return None, None
    amount, reference = None, None
    for pat in [r'transaction\s+number\s+is\s+([A-Z0-9]{6,})', r'transaction\s+(?:id|no)\s*[:\-]?\s*([A-Z0-9]{6,})', r'txn\s*[:\-]?\s*([A-Z0-9]{6,})', r'reference\s*[:\-]?\s*([A-Z0-9]{6,})']:
        m = re.search(pat, text_clean, re.IGNORECASE)
        if m: reference = m.group(1).upper(); break
    for pat in [r'you\s+have\s+received\s+ETB\s+(\d+(?:[.,]\d+)?)', r'received\s+ETB\s+(\d+(?:[.,]\d+)?)', r'credited\s+with\s+(?:ETB|Birr)\s+(\d+(?:[.,]\d+)?)', r'(?:ETB|Birr)\s+(\d+(?:[.,]\d+)?)']:
        m = re.search(pat, text_clean, re.IGNORECASE)
        if m:
            try:
                val = float(m.group(1).replace(',', ''))
                if 10 <= val <= 100000: amount = val; break
            except: pass
    if not amount:
        for p in reversed(text_clean.split()[-5:]):
            try:
                val = float(p.replace(',', ''))
                if 10 <= val <= 100000: amount = val; break
            except: pass
    return reference, amount

@bot.message_handler(commands=['deposit'])
def handle_deposit(message):
    uid = str(message.from_user.id); ensure_user(message)
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("📲 Telebirr", callback_data="dep_telebirr"), types.InlineKeyboardButton("🏦 CBE", callback_data="dep_cbe"))
    bot.send_message(message.chat.id, f"💳 <b>{t(uid,'deposit_choose')}</b>", reply_markup=markup, parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: call.data == "dep_telebirr")
def cb_dep_telebirr(call):
    uid = str(call.from_user.id); bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, f"📲 <b>Telebirr</b>\n\n📞 <code>{TELEBIRR_NUMBER}</code>\n👤 <b>{ACCOUNT_NAME}</b>\n\n{t(uid,'send_txn')}\n{t(uid,'txn_example')}", parse_mode='HTML')
    bot.register_next_step_handler(msg, process_deposit_reference, 'Telebirr')

@bot.callback_query_handler(func=lambda call: call.data == "dep_cbe")
def cb_dep_cbe(call):
    uid = str(call.from_user.id); bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, f"🏦 <b>CBE</b>\n\n🔢 <code>{CBE_NUMBER}</code>\n👤 <b>{ACCOUNT_NAME}</b>\n\n{t(uid,'send_txn')}\n{t(uid,'txn_example')}", parse_mode='HTML')
    bot.register_next_step_handler(msg, process_deposit_reference, 'CBE')

def process_deposit_reference(message, method):
    uid = str(message.from_user.id); text = message.text or ""
    reference, amount = parse_deposit_text(text)
    if not amount or amount < MIN_DEPOSIT:
        bot.send_message(message.chat.id, f"❌ {t(uid,'invalid_amount')}\n\n{t(uid,'txn_example')}", parse_mode='HTML', reply_markup=main_reply_keyboard(uid)); return
    if not reference: reference = gen_txn_id()
    u = ensure_user(message); txn_id = gen_txn_id()
    txns_col.insert_one({"id": txn_id, "type": "deposit", "user_id": u['id'], "user_name": u['name'], "amount": amount, "method": method, "reference": reference, "status": "pending", "created": datetime.utcnow().isoformat(), "notified": False})
    bot.send_message(message.chat.id, f"{t(uid,'deposit_sent')}\n\n🆔 <code>{txn_id}</code>\n💳 {method}\n💰 <b>{amount:.2f} ETB</b>\n{t(uid,'txn_ref')} <code>{reference}</code>\n\n{t(uid,'txn_pending')}", parse_mode='HTML', reply_markup=main_reply_keyboard(uid))
    notify_admins(f"💰 <b>New Deposit</b>\n\n👤 {u['name']} (<code>{u['id']}</code>)\n💳 {method}\n💰 {amount:.2f} ETB\n🔢 <code>{reference}</code>", skip_id=u['id'])

@bot.message_handler(commands=['withdraw'])
def handle_withdraw(message):
    uid = str(message.from_user.id); u = ensure_user(message)
    if not u.get('registered'): bot.send_message(message.chat.id, t(uid,'not_registered'), reply_markup=main_reply_keyboard(uid)); return
    if u['win_balance'] < MIN_WITHDRAW: bot.send_message(message.chat.id, f"{t(uid,'insufficient')}\n\n{t(uid,'win_bal')}: <b>{u['win_balance']:.2f} ETB</b>\n{t(uid,'min_withdraw', amt=MIN_WITHDRAW)}", parse_mode='HTML', reply_markup=main_reply_keyboard(uid)); return
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton(t(uid,'to_self'), callback_data="wd_self"), types.InlineKeyboardButton(t(uid,'to_other'), callback_data="wd_other"))
    bot.send_message(message.chat.id, f"💸 <b>{t(uid,'withdraw_choose')}</b>\n\n{t(uid,'win_bal')}: <b>{u['win_balance']:.2f} ETB</b>\n{t(uid,'min_withdraw', amt=MIN_WITHDRAW)}", reply_markup=markup, parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: call.data == "wd_self")
def cb_wd_self(call):
    uid = str(call.from_user.id); bot.answer_callback_query(call.id); u = get_user(uid)
    if u and u.get('phone'):
        msg = bot.send_message(call.message.chat.id, f"👤 <b>{t(uid,'to_self')}</b>\n\n{t(uid,'registered_phone')} <b>{u['phone']}</b>\n\n{t(uid,'send_amount', min=MIN_WITHDRAW)}", parse_mode='HTML', reply_markup=main_reply_keyboard(uid))
        bot.register_next_step_handler(msg, process_withdraw_amount_final, u['phone'])
    else:
        bot.send_message(call.message.chat.id, t(uid,'share_contact_prompt'), reply_markup=contact_button(uid), parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: call.data == "wd_other")
def cb_wd_other(call):
    uid = str(call.from_user.id); bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, f"👥 <b>{t(uid,'to_other')}</b>\n\n{t(uid,'send_phone')}", parse_mode='HTML')
    bot.register_next_step_handler(msg, process_wd_other_phone)

def process_wd_other_phone(message):
    uid = str(message.from_user.id); phone = (message.text or "").strip()
    if not phone.replace('+', '').isdigit() or len(phone) < 9:
        bot.send_message(message.chat.id, t(uid,'invalid_phone'), reply_markup=main_reply_keyboard(uid)); return
    msg = bot.send_message(message.chat.id, f"✅ <b>{phone}</b>\n\n{t(uid,'send_amount', min=MIN_WITHDRAW)}", parse_mode='HTML', reply_markup=main_reply_keyboard(uid))
    bot.register_next_step_handler(msg, process_withdraw_amount_final, phone)

def process_withdraw_amount_final(message, phone):
    uid = str(message.from_user.id)
    try: amount = float((message.text or "").strip())
    except: bot.send_message(message.chat.id, t(uid,'invalid_amount'), reply_markup=main_reply_keyboard(uid)); return
    u = ensure_user(message)
    if amount < MIN_WITHDRAW: bot.send_message(message.chat.id, f"{t(uid,'insufficient')}\n\n{t(uid,'min_withdraw', amt=MIN_WITHDRAW)}", parse_mode='HTML', reply_markup=main_reply_keyboard(uid)); return
    if amount > u['win_balance']: bot.send_message(message.chat.id, f"{t(uid,'insufficient')}\n\n{t(uid,'win_bal')}: <b>{u['win_balance']:.2f} ETB</b>", parse_mode='HTML', reply_markup=main_reply_keyboard(uid)); return

    result = users_col.update_one({"id": uid, "win_balance": {"$gte": amount}}, {"$inc": {"win_balance": -amount}})
    if result.modified_count == 0:
        bot.send_message(message.chat.id, f"{t(uid,'insufficient')}\n\n{t(uid,'win_bal')}: <b>{u['win_balance']:.2f} ETB</b>", parse_mode='HTML', reply_markup=main_reply_keyboard(uid)); return

    u = get_user(uid); txn_id = gen_txn_id()
    txns_col.insert_one({"id": txn_id, "type": "withdrawal", "user_id": u['id'], "user_name": u['name'], "amount": amount, "phone": phone, "status": "pending", "created": datetime.utcnow().isoformat(), "notified": False})
    bot.send_message(message.chat.id, f"{t(uid,'wd_approved_req', amt=f'{amount:.2f}')}\n\n🆔 <code>{txn_id}</code>\n📱 <b>{phone}</b>\n💰 <b>{amount:.2f} ETB</b>\n\n{t(uid,'txn_pending')}", parse_mode='HTML', reply_markup=main_reply_keyboard(uid))
    notify_admins(f"💸 <b>New Withdrawal</b>\n\n👤 {u['name']} (<code>{u['id']}</code>)\n💰 {amount:.2f} ETB\n📱 {phone}\n🆔 <code>{txn_id}</code>", skip_id=u['id'])

@bot.message_handler(commands=['history'])
def h_history(message):
    uid = str(message.from_user.id); u = ensure_user(message)
    deps = list(txns_col.find({"user_id": uid, "type": "deposit"}).sort("_id", -1).limit(5))
    wds = list(txns_col.find({"user_id": uid, "type": "withdrawal"}).sort("_id", -1).limit(5))
    text = f"📜 <b>{t(uid,'your_history', name=u['name'])}</b>\n\n"
    if deps: text += f"<b>{t(uid,'deposits')}</b>\n" + "".join([f"{'✅' if tt['status']=='approved' else '❌' if tt['status']=='rejected' else '⏳'} {tt['amount']:.2f} ETB\n" for tt in deps]) + "\n"
    if wds: text += f"<b>{t(uid,'withdrawals')}</b>\n" + "".join([f"{'✅' if tt['status']=='approved' else '❌' if tt['status']=='rejected' else '⏳'} {tt['amount']:.2f} ETB\n" for tt in wds]) + "\n"
    if not deps and not wds: text += t(uid,'no_txn')
    bot.send_message(message.chat.id, text, parse_mode='HTML')

@bot.message_handler(commands=['help'])
def h_help(message):
    uid = str(message.from_user.id); ensure_user(message)
    bot.send_message(message.chat.id, f"{t(uid,'help_title')}\n\n{t(uid,'help_list')}", parse_mode='HTML')

@bot.message_handler(func=lambda m: get_action(m.text) == 'play')
def h_play_btn(message): cmd_play(message)

@bot.message_handler(func=lambda m: get_action(m.text) == 'deposit')
def h_dep_btn(message): handle_deposit(message)

@bot.message_handler(func=lambda m: get_action(m.text) == 'withdraw')
def h_wd_btn(message): handle_withdraw(message)

@bot.message_handler(func=lambda m: get_action(m.text) == 'balance_btn')
def h_bal_btn(message): cmd_balance(message)

@bot.message_handler(func=lambda m: get_action(m.text) == 'invite')
def h_inv_btn(message): cmd_invite(message)

@bot.message_handler(func=lambda m: get_action(m.text) == 'history')
def h_hist_btn(message): h_history(message)

@bot.message_handler(func=lambda m: get_action(m.text) == 'register')
def h_reg_btn(message): handle_register(message)

@bot.message_handler(func=lambda m: get_action(m.text) == 'language')
def h_lang_btn(message): handle_language(message)

@bot.message_handler(func=lambda m: get_action(m.text) == 'help')
def h_help_btn(message): h_help(message)

@bot.message_handler(func=lambda m: get_action(m.text) == 'support')
def h_sup_btn(message):
    uid = str(message.from_user.id); ensure_user(message)
    markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(f"📞 @{SUPPORT_USERNAME}", url=f"https://t.me/{SUPPORT_USERNAME}"))
    bot.send_message(message.chat.id, f"💬 <b>{t(uid,'support_msg')}</b>\n\n📞 @{SUPPORT_USERNAME}\n⏰ 24/7", reply_markup=markup, parse_mode='HTML')

@bot.message_handler(func=lambda m: get_action(m.text) == 'leaderboard')
def h_lead_btn(message):
    uid = str(message.from_user.id); ensure_user(message)
    sorted_u = list(users_col.find().sort("win_balance", -1).limit(5))
    text = f"<b>{t(uid,'leaderboard_title')}</b>\n\n"
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    for i, uu in enumerate(sorted_u): text += f"{medals[i]} <b>{uu.get('name','?')[:20]}</b> — {uu.get('win_balance',0):.2f} ETB\n"
    if not sorted_u: text += t(uid,'no_winners')
    bot.send_message(message.chat.id, text, parse_mode='HTML')

@bot.message_handler(func=lambda m: True)
def fallback(message):
    uid = str(message.from_user.id); ensure_user(message)
    bot.send_message(message.chat.id, t(uid,'unknown'))

def notify_txn_users():
    while True:
        try:
            time.sleep(5)
            pending = txns_col.find({"status": {"$in": ["approved", "rejected"]}, "notified": {"$ne": True}})
            for txn in pending:
                tid = txn.get('id'); uid = str(txn.get('user_id', ''))
                if not tid or not uid: continue
                try:
                    amount_str = f"{txn.get('amount', 0):.2f}"
                    if txn.get('type') == 'deposit' and txn['status'] == 'approved':
                        user = get_user(uid); bal = f"{user.get('play_balance', 0):.2f}" if user else "0.00"
                        bot.send_message(int(uid), f"✅ <b>ገቢ ያደረጉት {amount_str} ETB ወደ ዋሌትዎ ተደምሯል</b>\n\n💰 አዲስ ባላንስ: <b>{bal} ETB</b>", parse_mode='HTML')
                    elif txn.get('type') == 'withdrawal' and txn['status'] == 'approved':
                        bot.send_message(int(uid), f"✅ <b>ወጭዎ በተሳካ ሁኔታ ገብቷል!</b>\n\n💰 መጠን: <b>{amount_str} ETB</b>", parse_mode='HTML')
                    elif txn['status'] == 'rejected':
                        bot.send_message(int(uid), f"❌ <b>የ{txn.get('type')} ጥያቄዎ ተከልክሏል</b>\n\n💰 መጠን: <b>{amount_str} ETB</b>", parse_mode='HTML')
                    txns_col.update_one({"id": tid}, {"$set": {"notified": True}})
                except: txns_col.update_one({"id": tid}, {"$set": {"notified": True}})
        except: pass

if __name__ == '__main__':
    print("🤖 Bot started...")
    setup_bot_menu()
    threading.Thread(target=notify_txn_users, daemon=True).start()
    while True:
        try: bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e: print(f"⚠️ Error: {e}"); time.sleep(5)