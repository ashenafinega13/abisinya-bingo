import os
import re
import asyncio
import requests
from dotenv import load_dotenv

load_dotenv()

from aiohttp import web
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    WebAppInfo,
    BotCommand,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    CallbackQueryHandler,
)

TOKEN             = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID          = int(os.getenv("ADMIN_ID", "0"))
SERVER_URL        = (os.getenv("SERVER_URL") or "").rstrip("/")
WEBAPP_URL        = (os.getenv("WEBAPP_URL") or "").rstrip("/")
BOT_API_SECRET    = os.getenv("BOT_API_SECRET", "change-me")
BOT_PORT          = int(os.getenv("PORT", os.getenv("BOT_PORT", "8080")))
BOT_USERNAME      = os.getenv("BOT_USERNAME", "AbyssinaBingobot")

H = {"x-bot-secret": BOT_API_SECRET, "Content-Type": "application/json"}

def _safe(r):
    try: return r.json()
    except: return {}

def sv_upsert(uid, uname, fname, phone=None):
    try:
        r = requests.post(f"{SERVER_URL}/api/bot/user", headers=H, timeout=10, json={"telegramId": uid, "username": uname, "firstName": fname, "phone": phone})
        return _safe(r).get("user")
    except: return None

def sv_user(uid):
    try: return _safe(requests.get(f"{SERVER_URL}/api/bot/user/{uid}", headers=H, timeout=10)).get("user")
    except: return None

def sv_adj(uid, field, delta):
    try: return _safe(requests.post(f"{SERVER_URL}/api/bot/user/{uid}/adjust", headers=H, timeout=10, json={"field": field, "delta": delta})).get("user")
    except: return None

def sv_tx(data):
    try: return _safe(requests.post(f"{SERVER_URL}/api/bot/transaction", headers=H, timeout=10, json=data)).get("tx")
    except: return None

def sv_get_tx(tx_id):
    try: return _safe(requests.get(f"{SERVER_URL}/api/bot/transaction/{tx_id}", headers=H, timeout=10)).get("tx")
    except: return None

def sv_set_tx_status(tx_id, status):
    try: requests.post(f"{SERVER_URL}/api/bot/transaction/{tx_id}/status", headers=H, timeout=10, json={"status": status})
    except: pass

def game_url(uid, name): return f"{WEBAPP_URL}/game?uid={uid}&name={name}"
def profile_url(uid): return f"{WEBAPP_URL}/profile.html?uid={uid}&tab=history"

def main_kb(uid, name):
    return ReplyKeyboardMarkup([
        [KeyboardButton("🎯  Play Abisinya Bingo", web_app=WebAppInfo(url=game_url(uid, name)))],
        [KeyboardButton("☰  Menu"), KeyboardButton("👤  My Profile", web_app=WebAppInfo(url=profile_url(uid)))],
    ], resize_keyboard=True, is_persistent=True)

def menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💵 Check Balance", callback_data="m_balance"), InlineKeyboardButton("📱 Register", callback_data="m_register")],
        [InlineKeyboardButton("💰 Deposit", callback_data="m_deposit"), InlineKeyboardButton("📤 Withdraw", callback_data="m_withdraw")],
        [InlineKeyboardButton("🎮 How to Play", callback_data="m_help"), InlineKeyboardButton("👥 Invite Friends", callback_data="m_invite")],
        [InlineKeyboardButton("💬 Support", callback_data="m_support"), InlineKeyboardButton("📋 History", callback_data="m_history")],
        [InlineKeyboardButton("🏆 Leaderboard", callback_data="m_leaderboard"), InlineKeyboardButton("🌍 Language", callback_data="m_language")],
    ])

def contact_kb():
    return ReplyKeyboardMarkup([[KeyboardButton("📱 Share My Contact", request_contact=True)]], resize_keyboard=True, one_time_keyboard=True)

def deposit_kb(): return InlineKeyboardMarkup([[InlineKeyboardButton("📲  Telebirr", callback_data="dep_telebirr")],[InlineKeyboardButton("🏦  CBE", callback_data="dep_cbe")]])
def withdraw_kb(): return InlineKeyboardMarkup([[InlineKeyboardButton("📲  Telebirr", callback_data="wd_telebirr")],[InlineKeyboardButton("🏦  CBE", callback_data="wd_cbe")]])
def approval_kb(tx_id): return InlineKeyboardMarkup([[InlineKeyboardButton("✅  Approve", callback_data=f"approve_{tx_id}"), InlineKeyboardButton("❌  Reject", callback_data=f"reject_{tx_id}")]])
def language_kb(): return InlineKeyboardMarkup([[InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")],[InlineKeyboardButton("🇪🇹 አማርኛ", callback_data="lang_am")]])

user_states = {}

async def menu_cmd(update, context):
    user_states.pop(update.effective_user.id, None)
    await update.message.reply_text("☰ *MENU*\n\nምን ማድረግ ይፈልጋሉ?", parse_mode="Markdown", reply_markup=menu_kb())

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    sv_upsert(u.id, u.username or "", u.first_name or "")
    if context.args and context.args[0].isdigit():
        ref = int(context.args[0])
        if ref != u.id: sv_adj(ref, "balance", 30); await context.bot.send_message(ref, "🎉 አዲስ ጓደኛ ጋበዝክ! +30 ብር")
    name = u.first_name or "Player"
    await update.message.reply_text(f"👋 *ሰላም {name}!*\n\n🎉 እንኳን ወደ *Abisinya Bingo* በደህና መጡ።", parse_mode="Markdown", reply_markup=main_kb(u.id, name))

async def play_cmd(update, context):
    u = update.effective_user
    await update.message.reply_text("🎯 Click the button below to open the game:", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🎯 Play Now", web_app=WebAppInfo(url=game_url(u.id, u.first_name or "Player")))]], resize_keyboard=True))

async def balance_cmd(update, context):
    u = update.effective_user; usr = sv_user(u.id) or {}; play = usr.get("balance", 0); win = usr.get("winBalance", 0); total = play + win
    await update.message.reply_text(f"💼 *የእርስዎ ዋሌት*\n\n🎯 Playable: *{play:.2f} ብር*\n🏆 Winnings: *{win:.2f} ብር*\n💵 *ጠቅላላ: {total:.2f} ብር*", parse_mode="Markdown")

async def register_cmd(update, context):
    user_states[update.effective_user.id] = {"action": "register"}
    await update.message.reply_text("📱 *ስልክ ቁጥር ምዝገባ*\n\nከታች ያለውን *📱 Share My Contact* ይጫኑ።", parse_mode="Markdown", reply_markup=contact_kb())

async def handle_msg(update, context):
    if update.message.contact:
        u = update.effective_user; phone = update.message.contact.phone_number
        sv_upsert(u.id, u.username or "", u.first_name or "", phone=phone)
        user_states.pop(u.id, None)
        await update.message.reply_text(f"✅ *ተመዝግቧል!*\n\n📱 `{phone}`", parse_mode="Markdown", reply_markup=main_kb(u.id, u.first_name or "Player"))
        return

    if not update.message or not update.message.text: return
    u = update.effective_user; txt = update.message.text.strip(); sv_upsert(u.id, u.username or "", u.first_name or "")
    state = user_states.get(u.id, {}); action = state.get("action")

    if txt in ["☰  Menu", "☰ Menu"]: await menu_cmd(update, context); return

    if action == "register":
        phone = txt.strip()
        if not re.match(r"^\+?\d{9,15}$", phone): await update.message.reply_text("⚠️ Invalid phone."); return
        sv_upsert(u.id, u.username or "", u.first_name or "", phone=phone)
        user_states.pop(u.id, None)
        await update.message.reply_text(f"✅ *ተመዝግቧል!*\n\n📱 `{phone}`", parse_mode="Markdown", reply_markup=main_kb(u.id, u.first_name or "Player"))
        return

    if action == "deposit":
        m = re.search(r"(\d+(?:[.,]\d+)?)", txt); amount = float(m.group(1).replace(",", "")) if m else 0
        if amount < 1: await update.message.reply_text("⚠️ Invalid amount."); return
        tx = sv_tx({"userId": u.id, "type": "deposit", "amount": amount, "method": state.get("method", "unknown"), "sms": txt, "status": "pending"})
        if not tx: await update.message.reply_text("⚠️ Network error."); return
        tx_id = tx["_id"]; method_label = "📲 Telebirr" if state.get("method") == "telebirr" else "🏦 CBE"
        await context.bot.send_message(ADMIN_ID, f"🔔 *DEPOSIT*\n👤 {u.first_name}\n🆔 `{u.id}`\n💰 {amount:.2f} ETB\n🔖 Tx: `{tx_id}`", parse_mode="Markdown", reply_markup=approval_kb(tx_id))
        user_states.pop(u.id, None)
        await update.message.reply_text(f"✅ *ጥያቄዎ ተልኳል!*\n💰 {amount:.2f} ETB", parse_mode="Markdown", reply_markup=main_kb(u.id, u.first_name or "Player"))
        return

    if action == "withdraw_amount":
        if not txt.isdigit(): await update.message.reply_text("⚠️ Enter numbers."); return
        amount = float(txt)
        if amount < 100: await update.message.reply_text("⚠️ Min 100 ETB."); return
        usr = sv_user(u.id) or {}; total = (usr.get("balance") or 0) + (usr.get("winBalance") or 0)
        if amount > total: await update.message.reply_text(f"❌ Insufficient: {total:.2f}"); return
        user_states[u.id] = {"action": "withdraw_phone", "amount": amount, "method": state.get("method", "unknown")}
        await update.message.reply_text("📱 የስልክ ቁጥርዎን ያስገቡ:"); return

    if action == "withdraw_phone":
        phone = txt.strip(); amount = state.get("amount", 0); method = state.get("method", "unknown")
        tx = sv_tx({"userId": u.id, "type": "withdraw", "amount": amount, "method": method, "phone": phone, "status": "pending"})
        if not tx: await update.message.reply_text("⚠️ Network error."); return
        tx_id = tx["_id"]; method_label = "📲 Telebirr" if method == "telebirr" else "🏦 CBE"
        await context.bot.send_message(ADMIN_ID, f"🔔 *WITHDRAW*\n👤 {u.first_name}\n🆔 `{u.id}`\n💰 {amount:.2f} ETB\n📱 `{phone}`\n🔖 Tx: `{tx_id}`", parse_mode="Markdown", reply_markup=approval_kb(tx_id))
        user_states.pop(u.id, None)
        await update.message.reply_text("✅ *የወጭ ጥያቄዎ ተልኳል!*", parse_mode="Markdown", reply_markup=main_kb(u.id, u.first_name or "Player"))
        return
    await update.message.reply_text("🤔 Use the keyboard buttons.", reply_markup=main_kb(u.id, u.first_name or "Player"))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer(); data = q.data; u = q.from_user; sv_upsert(u.id, u.username or "", u.first_name or "")
    if data.startswith("approve_") or data.startswith("reject_"):
        if u.id != ADMIN_ID: return
        action, tx_id = data.split("_", 1); tx = sv_get_tx(tx_id)
        if not tx: await q.edit_message_text("❌ Not found"); return
        status = "approved" if action == "approve" else "rejected"; sv_set_tx_status(tx_id, status)
        if status == "approved":
            if tx["type"] == "deposit": sv_adj(tx["userId"], "balance", tx["amount"])
            elif tx["type"] == "withdraw": sv_adj(tx["userId"], "winBalance", -tx["amount"])
            try: await context.bot.send_message(tx["userId"], f"✅ ጥያቄዎ ፀድቋል: {tx['amount']:.2f} ETB")
            except: pass
        else:
            try: await context.bot.send_message(tx["userId"], f"❌ ጥያቄዎ ተሰርዟል")
            except: pass
        await q.edit_message_text(f"{'✅' if status == 'approved' else '❌'} {tx['type'].upper()} — {tx['amount']:.2f} ETB"); return

    if data == "m_deposit": await q.edit_message_text("💰 *Deposit*\n\nChoose method:", parse_mode="Markdown", reply_markup=deposit_kb())
    elif data == "m_withdraw": await q.edit_message_text("📤 *Withdraw*\n\nChoose method:", parse_mode="Markdown", reply_markup=withdraw_kb())
    elif data == "m_balance": await balance_cmd(update, context)
    elif data == "m_invite": await q.edit_message_text(f"👥 *Invite Link*\n\n[👉 Click Here](https://t.me/{BOT_USERNAME}?start={u.id})", parse_mode="Markdown")
    elif data == "m_register": await q.edit_message_text("📱 Use /register to share contact.")
    elif data == "m_language": await q.edit_message_text("🌐 Language:", reply_markup=language_kb())
    elif data == "dep_telebirr": user_states[u.id] = {"action": "deposit", "method": "telebirr"}; await q.edit_message_text("🏦 *Telebirr*\n\nPaste SMS:", parse_mode="Markdown")
    elif data == "dep_cbe": user_states[u.id] = {"action": "deposit", "method": "cbe"}; await q.edit_message_text("🏦 *CBE*\n\nPaste SMS:", parse_mode="Markdown")
    elif data == "wd_telebirr": user_states[u.id] = {"action": "withdraw_amount", "method": "telebirr"}; await q.edit_message_text("🏦 *Telebirr*\n\nAmount (min 100):", parse_mode="Markdown")
    elif data == "wd_cbe": user_states[u.id] = {"action": "withdraw_amount", "method": "cbe"}; await q.edit_message_text("🏦 *CBE*\n\nAmount (min 100):", parse_mode="Markdown")
    elif data == "lang_en": await q.edit_message_text("✅ English")
    elif data == "lang_am": await q.edit_message_text("✅ አማርኛ")

async def notify_tx(request):
    if request.headers.get("x-bot-secret") != BOT_API_SECRET: return web.json_response({"ok": False}, status=403)
    d = await request.json(); tg = request.app["tg_app"]
    try: await tg.bot.send_message(d["telegramId"], f"{'✅' if d['status']=='approved' else '❌'} {d['type'].upper()}: {d['amount']:.2f} ETB")
    except: pass
    return web.json_response({"ok": True})

async def winner_handler(request):
    if request.headers.get("x-bot-secret") != BOT_API_SECRET: return web.json_response({"ok": False}, status=403)
    d = await request.json(); tg = request.app["tg_app"]
    try: await tg.bot.send_message(d["userId"], f"🏆 *እንኳን ደስ አለዎት!*\n\n💰 *{d['prize']:.2f} ETB*", parse_mode="Markdown")
    except: pass
    return web.json_response({"ok": True})

async def post_init(app):
    await app.bot.set_my_commands([
        BotCommand("menu", "☰ Main Menu"), BotCommand("play", "🎯 Play Game"), BotCommand("start", "🚀 Start Bot"),
        BotCommand("balance", "💵 Balance"), BotCommand("deposit", "💰 Deposit"), BotCommand("withdraw", "📤 Withdraw"),
        BotCommand("register", "📱 Register"), BotCommand("leaderboard", "🏆 Leaderboard"),
    ])
    print("✅ Bot commands set.")

async def main():
    tg = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    tg.add_handler(CommandHandler("menu", menu_cmd)); tg.add_handler(CommandHandler("start", start)); tg.add_handler(CommandHandler("play", play_cmd))
    tg.add_handler(CommandHandler("balance", balance_cmd)); tg.add_handler(CommandHandler("register", register_cmd))
    
    tg.add_handler(MessageHandler(filters.CONTACT, handle_msg)); tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    tg.add_handler(CallbackQueryHandler(button_handler))

    webapp = web.Application(); webapp["tg_app"] = tg
    webapp.router.add_post("/notify-tx", notify_tx); webapp.router.add_post("/winner", winner_handler)

    await tg.initialize(); await tg.start()
    runner = web.AppRunner(webapp); await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", BOT_PORT); await site.start()
    await tg.updater.start_polling()
    print("🤖 Bot running")
    await asyncio.Event().wait()

if __name__ == "__main__": asyncio.run(main())