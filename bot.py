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

# ================================================================
# CONFIG
# ================================================================
TOKEN             = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID          = int(os.getenv("ADMIN_ID", "0"))
SERVER_URL        = (os.getenv("SERVER_URL") or "").rstrip("/")
WEBAPP_URL        = (os.getenv("WEBAPP_URL") or "").rstrip("/")
BOT_API_SECRET    = os.getenv("BOT_API_SECRET", "change-me")
BOT_PORT          = int(os.getenv("PORT", os.getenv("BOT_PORT", "8080")))
BOT_USERNAME      = os.getenv("BOT_USERNAME", "AbyssiniaBingobot")

H = {"x-bot-secret": BOT_API_SECRET, "Content-Type": "application/json"}

# ================================================================
# SERVER HELPERS
# ================================================================
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

def game_url(uid, name): 
    return f"{WEBAPP_URL}/bingo.html?uid={uid}&name={name}"

def profile_url(uid): 
    return f"{WEBAPP_URL}/profile.html?uid={uid}&tab=history"

# ================================================================
# KEYBOARDS
# ================================================================
def main_kb(uid, name):
    return ReplyKeyboardMarkup([
        [KeyboardButton("🎯 Play Abyssinia Bingo", web_app=WebAppInfo(url=game_url(uid, name)))],
        [KeyboardButton("☰ Menu"), KeyboardButton("👤 My Profile", web_app=WebAppInfo(url=profile_url(uid)))],
    ], resize_keyboard=True, is_persistent=True)

def nav_kb(uid, name):
    """Returns standard navigation inline buttons."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎮 Play Now", web_app=WebAppInfo(url=game_url(uid, name))), 
         InlineKeyboardButton("🔙 Main Menu", callback_data="m_menu")]
    ])

def menu_kb(uid, name):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 Play Game", web_app=WebAppInfo(url=game_url(uid, name)))],
        [InlineKeyboardButton("💰 Deposit", callback_data="m_deposit"), 
         InlineKeyboardButton("💸 Withdraw", callback_data="m_withdraw")],
        [InlineKeyboardButton("💵 Balance", callback_data="m_balance"), 
         InlineKeyboardButton("ℹ️ How to Play", callback_data="m_howtoplay")],
        [InlineKeyboardButton("👥 Invite", callback_data="m_invite"), 
         InlineKeyboardButton("🏆 Leaderboard", web_app=WebAppInfo(url=profile_url(uid)))],
        [InlineKeyboardButton("💬 Support", callback_data="m_support"), 
         InlineKeyboardButton("🌍 Language", callback_data="m_language")],
    ])

def contact_kb():
    return ReplyKeyboardMarkup([[KeyboardButton("📱 Share My Contact", request_contact=True)]], resize_keyboard=True, one_time_keyboard=True)

def deposit_kb(): 
    return InlineKeyboardMarkup([[InlineKeyboardButton("📲 Telebirr", callback_data="dep_telebirr")],[InlineKeyboardButton("🏦 CBE", callback_data="dep_cbe")]])

def withdraw_kb(): 
    return InlineKeyboardMarkup([[InlineKeyboardButton("📲 Telebirr", callback_data="wd_telebirr")],[InlineKeyboardButton("🏦 CBE", callback_data="wd_cbe")]])

def approval_kb(tx_id): 
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve", callback_data=f"approve_{tx_id}"), InlineKeyboardButton("❌ Reject", callback_data=f"reject_{tx_id}")]])

def language_kb(): 
    return InlineKeyboardMarkup([[InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")],[InlineKeyboardButton("🇪🇹 አማርኛ", callback_data="lang_am")]])

user_states = {}

# ================================================================
# COMMANDS
# ================================================================
async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    user_states.pop(u.id, None)
    await update.message.reply_text("☰ *Main Menu*\n\nChoose an option:", parse_mode="Markdown", reply_markup=menu_kb(u.id, u.first_name or "Player"))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    sv_upsert(u.id, u.username or "", u.first_name or "")
    if context.args and context.args[0].isdigit():
        ref = int(context.args[0])
        if ref != u.id:
            sv_adj(ref, "balance", 30)
            try: await context.bot.send_message(ref, "🎉 New friend invited! +30 ETB")
            except: pass
    name = u.first_name or "Player"
    await update.message.reply_text(f"👋 *Welcome to Abyssinia Bingo, {name}!*\n\nUse the buttons below to start playing.", parse_mode="Markdown", reply_markup=main_kb(u.id, name))

async def play_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await update.message.reply_text("🎯 Open Game:", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🎮 Play Now", web_app=WebAppInfo(url=game_url(u.id, u.first_name or "Player")))]], resize_keyboard=True))

async def deposit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_states[update.effective_user.id] = {"action": "deposit_choose"}
    await update.message.reply_text("💰 *Deposit*\n\nChoose method:", parse_mode="Markdown", reply_markup=deposit_kb())

async def withdraw_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_states[update.effective_user.id] = {"action": "withdraw_choose"}
    await update.message.reply_text("💸 *Withdraw*\n\nChoose method:", parse_mode="Markdown", reply_markup=withdraw_kb())

async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user; usr = sv_user(u.id) or {}
    await update.message.reply_text(f"💵 *Balance*\n\n🎯 Playable: *{usr.get('balance',0):.2f} ETB*\n🏆 Winnings: *{usr.get('winBalance',0):.2f} ETB*", parse_mode="Markdown", reply_markup=nav_kb(u.id, u.first_name or "Player"))

async def howtoplay_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ℹ️ *How to Play*\n\n1. Select your Cartelas.\n2. Pay the entry fee.\n3. Wait for numbers to be called.\n4. Complete a row/column/diagonal to win!\n5. Tap BINGO to claim.", parse_mode="Markdown")

async def invite_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await update.message.reply_text(f"👥 *Invite Friends*\n\n[👉 Click Here](https://t.me/{BOT_USERNAME}?start={u.id})", parse_mode="Markdown")

async def leaderboard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await update.message.reply_text("🏆 *Leaderboard*\n\nCheck the Profile tab in the game!", parse_mode="Markdown", reply_markup=nav_kb(u.id, u.first_name or "Player"))

async def support_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💬 *Support*\n\nContact @Tazikes.", parse_mode="Markdown")

async def language_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🌍 Language:", reply_markup=language_kb())

async def register_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_states[update.effective_user.id] = {"action": "register"}
    await update.message.reply_text("📱 Share your phone number:", reply_markup=contact_kb())

async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await update.message.reply_text(f"📋 *History*\n\n[👉 Click Here]({WEBAPP_URL}/profile.html?uid={u.id}&tab=history)", parse_mode="Markdown", reply_markup=nav_kb(u.id, u.first_name or "Player"))

# ================================================================
# MESSAGE HANDLERS
# ================================================================
async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.contact:
        u = update.effective_user; phone = update.message.contact.phone_number
        sv_upsert(u.id, u.username or "", u.first_name or "", phone=phone)
        user_states.pop(u.id, None)
        await update.message.reply_text(f"✅ Registered!\n📱 `{phone}`", parse_mode="Markdown", reply_markup=main_kb(u.id, u.first_name or "Player"))
        return

    if not update.message or not update.message.text: return
    u = update.effective_user; txt = update.message.text.strip(); sv_upsert(u.id, u.username or "", u.first_name or "")
    state = user_states.get(u.id, {}); action = state.get("action")

    if txt == "☰ Menu": 
        await menu_cmd(update, context)
        return
    
    if action == "deposit":
        m = re.search(r"(\d+(?:[.,]\d+)?)", txt); amount = float(m.group(1).replace(",", "")) if m else 0
        if amount < 1: return await update.message.reply_text("⚠️ Invalid amount.")
        tx = sv_tx({"userId": u.id, "type": "deposit", "amount": amount, "method": state.get("method"), "sms": txt, "status": "pending"})
        if not tx: return await update.message.reply_text("⚠️ Server error.")
        tx_id = tx["_id"]
        
        # ADMIN NOTIFICATION
        await context.bot.send_message(ADMIN_ID, f"🔔 *DEPOSIT*\n👤 {u.first_name}\n🆔 `{u.id}`\n💰 {amount:.2f} ETB\n🔖 `{tx_id}`", parse_mode="Markdown", reply_markup=approval_kb(tx_id))
        
        # NAVIGATION APPENDED TO SUCCESS MESSAGE
        user_states.pop(u.id, None)
        await update.message.reply_text(f"✅ Request sent!\nAdmin will approve shortly.", reply_markup=nav_kb(u.id, u.first_name or "Player"))
        return

    if action == "withdraw_amount":
        if not txt.isdigit(): return await update.message.reply_text("⚠️ Enter numbers.")
        amount = float(txt)
        if amount < 100: return await update.message.reply_text("⚠️ Min 100 ETB.")
        user_states[u.id] = {"action": "withdraw_phone", "amount": amount, "method": state.get("method")}
        await update.message.reply_text("📱 Enter phone number:")
        return

    if action == "withdraw_phone":
        phone = txt.strip(); amount = state.get("amount")
        tx = sv_tx({"userId": u.id, "type": "withdraw", "amount": amount, "method": state.get("method"), "phone": phone, "status": "pending"})
        if not tx: return await update.message.reply_text("⚠️ Server error.")
        tx_id = tx["_id"]
        
        # ADMIN NOTIFICATION
        await context.bot.send_message(ADMIN_ID, f"🔔 *WITHDRAW*\n👤 {u.first_name}\n🆔 `{u.id}`\n💰 {amount:.2f} ETB\n📱 `{phone}`\n🔖 `{tx_id}`", parse_mode="Markdown", reply_markup=approval_kb(tx_id))
        
        # NAVIGATION APPENDED TO SUCCESS MESSAGE
        user_states.pop(u.id, None)
        await update.message.reply_text("✅ Request sent!\nAdmin will process it shortly.", reply_markup=nav_kb(u.id, u.first_name or "Player"))
        return

    if txt == "💰 ገንዘብ ያስቀምጡ": await deposit_cmd(update, context)
    elif txt == "💸 ገንዘብ ያውጡ": await withdraw_cmd(update, context)
    else: await update.message.reply_text("🤔 Use the buttons below.", reply_markup=main_kb(u.id, u.first_name or "Player"))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer(); data = q.data; u = q.from_user; sv_upsert(u.id, u.username or "", u.first_name or "")
    
    if data == "m_menu":
        await q.edit_message_text("☰ *Main Menu*\n\nChoose an option:", parse_mode="Markdown", reply_markup=menu_kb(u.id, u.first_name or "Player"))
        return

    if data.startswith("approve_") or data.startswith("reject_"):
        if u.id != ADMIN_ID: return
        action, tx_id = data.split("_", 1); tx = sv_get_tx(tx_id)
        status = "approved" if action == "approve" else "rejected"; sv_set_tx_status(tx_id, status)
        if status == "approved":
            if tx["type"] == "deposit": sv_adj(tx["userId"], "balance", tx["amount"])
            elif tx["type"] == "withdraw": sv_adj(tx["userId"], "winBalance", -tx["amount"])
            try: 
                await context.bot.send_message(tx["userId"], f"✅ Request approved: {tx['amount']:.2f} ETB", reply_markup=nav_kb(tx["userId"], "Player"))
            except: pass
        else:
            try: 
                await context.bot.send_message(tx["userId"], f"❌ Request rejected.", reply_markup=nav_kb(tx["userId"], "Player"))
            except: pass
        await q.edit_message_text(f"{'✅' if status == 'approved' else '❌'} {tx['type'].upper()} — {tx['amount']:.2f} ETB"); return

    if data == "m_deposit": await deposit_cmd(update, context)
    elif data == "m_withdraw": await withdraw_cmd(update, context)
    elif data == "m_balance": await balance_cmd(update, context)
    elif data == "m_howtoplay": await howtoplay_cmd(update, context)
    elif data == "m_invite": await invite_cmd(update, context)
    elif data == "m_support": await support_cmd(update, context)
    elif data == "m_language": await language_cmd(update, context)
    elif data == "dep_telebirr": user_states[u.id] = {"action": "deposit", "method": "telebirr"}; await q.edit_message_text("🏦 *Telebirr*\n\nPaste SMS:", parse_mode="Markdown")
    elif data == "dep_cbe": user_states[u.id] = {"action": "deposit", "method": "cbe"}; await q.edit_message_text("🏦 *CBE*\n\nPaste SMS:", parse_mode="Markdown")
    elif data == "wd_telebirr": user_states[u.id] = {"action": "withdraw_amount", "method": "telebirr"}; await q.edit_message_text("🏦 *Telebirr*\n\nAmount (min 100):", parse_mode="Markdown")
    elif data == "wd_cbe": user_states[u.id] = {"action": "withdraw_amount", "method": "cbe"}; await q.edit_message_text("🏦 *CBE*\n\nAmount (min 100):", parse_mode="Markdown")
    elif data == "lang_en": await q.edit_message_text("✅ Language set to English", reply_markup=nav_kb(u.id, u.first_name or "Player"))
    elif data == "lang_am": await q.edit_message_text("✅ ቋንቋ አማርኛ ተቀይሯል", reply_markup=nav_kb(u.id, u.first_name or "Player"))

# ================================================================
# WEBHOOKS & MAIN
# ================================================================
async def notify_tx(request):
    if request.headers.get("x-bot-secret") != BOT_API_SECRET: return web.json_response({"ok": False}, status=403)
    d = await request.json(); tg = request.app["tg_app"]
    try: await tg.bot.send_message(d["telegramId"], f"{'✅' if d['status']=='approved' else '❌'} {d['type'].upper()}: {d['amount']:.2f} ETB")
    except: pass
    return web.json_response({"ok": True})

async def winner_handler(request):
    if request.headers.get("x-bot-secret") != BOT_API_SECRET: return web.json_response({"ok": False}, status=403)
    d = await request.json(); tg = request.app["tg_app"]
    try: await tg.bot.send_message(d["userId"], f"🏆 *You Won!*\n\n💰 *{d['prize']:.2f} ETB*", parse_mode="Markdown", reply_markup=nav_kb(d["userId"], "Winner"))
    except: pass
    return web.json_response({"ok": True})

async def post_init(app):
    commands = [
        BotCommand("menu", "☰ Main Menu"),
        BotCommand("start", "🚀 Start / Restart Bot"),
        BotCommand("play", "🎯 Play Abyssinia Bingo"),
        BotCommand("deposit", "💰 Deposit Funds"),
        BotCommand("withdraw", "💸 Withdraw Funds"),
        BotCommand("balance", "💵 Check Balance"),
        BotCommand("register", "📱 Register Phone"),
        BotCommand("history", "📋 History"),
        BotCommand("howtoplay", "ℹ️ How to play guide"),
        BotCommand("invite", "👥 Refer and Earn"),
        BotCommand("leaderboard", "🏆 View Top Players"),
        BotCommand("support", "💬 Contact Support"),
        BotCommand("language", "🌍 Change Language"),
    ]
    await app.bot.set_my_commands(commands)
    print("✅ Bot commands set successfully.")

async def main():
    tg = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    
    tg.add_handler(CommandHandler("menu", menu_cmd))
    tg.add_handler(CommandHandler("start", start))
    tg.add_handler(CommandHandler("play", play_cmd))
    tg.add_handler(CommandHandler("deposit", deposit_cmd))
    tg.add_handler(CommandHandler("withdraw", withdraw_cmd))
    tg.add_handler(CommandHandler("balance", balance_cmd))
    tg.add_handler(CommandHandler("register", register_cmd))
    tg.add_handler(CommandHandler("history", history_cmd))
    tg.add_handler(CommandHandler("howtoplay", howtoplay_cmd))
    tg.add_handler(CommandHandler("invite", invite_cmd))
    tg.add_handler(CommandHandler("leaderboard", leaderboard_cmd))
    tg.add_handler(CommandHandler("support", support_cmd))
    tg.add_handler(CommandHandler("language", language_cmd))
    
    tg.add_handler(MessageHandler(filters.CONTACT, handle_msg))
    tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    tg.add_handler(CallbackQueryHandler(button_handler))

    webapp = web.Application(); webapp["tg_app"] = tg
    webapp.router.add_post("/notify-tx", notify_tx)
    webapp.router.add_post("/winner", winner_handler)

    await tg.initialize(); await tg.start()
    runner = web.AppRunner(webapp); await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", BOT_PORT); await site.start()
    await tg.updater.start_polling()
    print("🤖 Abyssinia Bingo Bot running")
    await asyncio.Event().wait()

if __name__ == "__main__": asyncio.run(main())