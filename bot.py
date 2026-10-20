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
    except Exception: return {}

def sv_upsert(uid, uname, fname, phone=None):
    try:
        r = requests.post(f"{SERVER_URL}/api/bot/user", headers=H, timeout=10,
            json={"telegramId": uid, "username": uname,
                  "firstName": fname, "phone": phone})
        return _safe(r).get("user")
    except Exception as e:
        print("sv_upsert:", e); return None

def sv_user(uid):
    try:
        r = requests.get(f"{SERVER_URL}/api/bot/user/{uid}", headers=H, timeout=10)
        return _safe(r).get("user")
    except Exception as e: return None

def sv_adj(uid, field, delta):
    try:
        r = requests.post(f"{SERVER_URL}/api/bot/user/{uid}/adjust", headers=H,
                          timeout=10, json={"field": field, "delta": delta})
        return _safe(r).get("user")
    except Exception as e: return None

def sv_tx(data):
    try:
        r = requests.post(f"{SERVER_URL}/api/bot/transaction", headers=H,
                          timeout=10, json=data)
        return _safe(r).get("tx")
    except Exception as e: return None

def sv_get_tx(tx_id):
    try:
        r = requests.get(f"{SERVER_URL}/api/bot/transaction/{tx_id}",
                         headers=H, timeout=10)
        return _safe(r).get("tx")
    except Exception as e: return None

def sv_set_tx_status(tx_id, status):
    try:
        requests.post(f"{SERVER_URL}/api/bot/transaction/{tx_id}/status",
                      headers=H, timeout=10, json={"status": status})
    except Exception as e: pass

def game_url(uid, name):
    return f"{WEBAPP_URL}/game?uid={uid}&name={name}"

def profile_url(uid, tab="history"):
    return f"{WEBAPP_URL}/profile.html?uid={uid}&tab={tab}"

# ================================================================
#                    KEYBOARDS
# ================================================================
def main_kb(uid, name):
    keyboard = [
        [KeyboardButton("🎯  Play Abisinya Bingo",
                        web_app=WebAppInfo(url=game_url(uid, name)))],
        [KeyboardButton("☰  Menu"),
         KeyboardButton("👤  My Profile",
                        web_app=WebAppInfo(url=profile_url(uid, "history")))],
    ]
    return ReplyKeyboardMarkup(
        keyboard, resize_keyboard=True, is_persistent=True,
        input_field_placeholder="Choose an action…"
    )

def menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💵 Check Balance",   callback_data="m_balance"),
         InlineKeyboardButton("📱 Register",        callback_data="m_register")],
        [InlineKeyboardButton("💰 Deposit",         callback_data="m_deposit"),
         InlineKeyboardButton("📤 Withdraw",        callback_data="m_withdraw")],
        [InlineKeyboardButton("🎮 How to Play",     callback_data="m_help"),
         InlineKeyboardButton("👥 Invite Friends",  callback_data="m_invite")],
        [InlineKeyboardButton("💬 Support",         callback_data="m_support"),
         InlineKeyboardButton("📋 History",         callback_data="m_history")],
        [InlineKeyboardButton("🏆 Leaderboard",     callback_data="m_leaderboard"),
         InlineKeyboardButton("🌍 Language",        callback_data="m_language")],
    ])

def contact_kb():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("📱 Share My Contact", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )

def deposit_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📲  Telebirr", callback_data="dep_telebirr")],
        [InlineKeyboardButton("🏦  CBE",      callback_data="dep_cbe")],
    ])

def withdraw_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📲  Telebirr", callback_data="wd_telebirr")],
        [InlineKeyboardButton("🏦  CBE",      callback_data="wd_cbe")],
    ])

def approval_kb(tx_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅  Approve", callback_data=f"approve_{tx_id}"),
        InlineKeyboardButton("❌  Reject",  callback_data=f"reject_{tx_id}")
    ]])

def language_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🇬🇧 English",   callback_data="lang_en")],
        [InlineKeyboardButton("🇪🇹 አማርኛ",     callback_data="lang_am")],
        [InlineKeyboardButton("🇪🇹 Oromiffa",  callback_data="lang_om")],
        [InlineKeyboardButton("🇪🇹 ትግርኛ",    callback_data="lang_ti")],
    ])

user_states = {}

# ================================================================
#                    COMMANDS
# ================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message: return
    u = update.effective_user
    sv_upsert(u.id, u.username or "", u.first_name or "")

    if context.args and context.args[0].isdigit():
        ref = int(context.args[0])
        if ref != u.id:
            sv_adj(ref, "balance", 30)
            try:
                await context.bot.send_message(ref, "🎉 አዲስ ጓደኛ ጋበዝክ! +30 ብር")
            except Exception: pass

    name = u.first_name or "Player"
    await update.message.reply_text(
        f"👋 *ሰላም {name}!*\n\n"
        f"🎉 እንኳን ወደ *Abisinya Bingo* በደህና መጡ።\n\n"
        f"🎯 *Play* ን ተጭነው ይጫወቱ\n"
        f"☰ *Menu* ን ተጭነው ሁሉንም አማራጮች ያያሉ",
        parse_mode="Markdown",
        reply_markup=main_kb(u.id, name)
    )

async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    usr = sv_user(u.id) or {}
    play = usr.get("balance", 0); win = usr.get("winBalance", 0)
    await update.message.reply_text(
        f"💼 *የእርስዎ ዋሌት*\n\n🎯 Playable: *{play:.2f} ብር*\n🏆 Winnings: *{win:.2f} ብር*\n💵 *ጠቅላላ: {play+win:.2f} ብር}*",
        parse_mode="Markdown")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ *እርዳታ*\n\n1. 🎯 Play\n2. 1–4 ካርቴላ ይምረጡ\n3. JOIN\n4. BINGO ሲሆን ይጫኑ",
        parse_mode="Markdown")

async def debug_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await update.message.reply_text(
        f"🔧 *DEBUG*\n\n`SERVER_URL` = `{SERVER_URL}`\n`WEBAPP_URL` = `{WEBAPP_URL}`\n`BOT_USERNAME` = `{BOT_USERNAME}`\n\n*Play:* `{game_url(u.id, u.first_name or 'Player')}`",
        parse_mode="Markdown")

# ================================================================
#                    MESSAGE HANDLER
# ================================================================
async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.contact:
        u = update.effective_user
        phone = update.message.contact.phone_number
        sv_upsert(u.id, u.username or "", u.first_name or "", phone=phone)
        user_states.pop(u.id, None)
        await update.message.reply_text(
            f"✅ *ተመዝግቧል!*\n\n📱 `{phone}`",
            parse_mode="Markdown",
            reply_markup=main_kb(u.id, u.first_name or "Player"))
        return

    if not update.message or not update.message.text: return
    if not update.effective_user: return

    u = update.effective_user
    txt = update.message.text.strip()
    sv_upsert(u.id, u.username or "", u.first_name or "")

    state = user_states.get(u.id, {})
    action = state.get("action")

    if txt == "☰  Menu" or txt == "☰ Menu":
        user_states.pop(u.id, None)
        await update.message.reply_text(
            "☰ *MENU*\n\nምን ማድረግ ይፈልጋሉ?",
            parse_mode="Markdown", reply_markup=menu_kb())
        return

    if action == "register":
        phone = txt.strip()
        if not re.match(r"^\+?\d{9,15}$", phone):
            await update.message.reply_text("⚠️ Please send a valid phone number or share your contact.")
            return
        sv_upsert(u.id, u.username or "", u.first_name or "", phone=phone)
        user_states.pop(u.id, None)
        await update.message.reply_text(
            f"✅ *ተመዝግቧል!*\n\n📱 `{phone}`",
            parse_mode="Markdown",
            reply_markup=main_kb(u.id, u.first_name or "Player"))
        return

    if action == "deposit":
        m = re.search(r"(\d+(?:[.,]\d+)?)", txt)
        amount = float(m.group(1).replace(",", "")) if m else 0
        if amount < 1:
            await update.message.reply_text("⚠️ ትክክለኛ መጠን ያስገቡ (ለምሳሌ: 100)")
            return
        tx = sv_tx({"userId": u.id, "type": "deposit", "amount": amount,
                    "method": state.get("method", "unknown"), "sms": txt, "status": "pending"})
        if not tx:
            await update.message.reply_text("⚠️ ኔትወርክ ችግር።"); return
        tx_id = tx["_id"]
        method_label = "📲 Telebirr" if state.get("method") == "telebirr" else "🏦 CBE"
        await context.bot.send_message(
            ADMIN_ID,
            f"🔔 *አዲስ DEPOSIT*\n\n👤 {u.first_name}\n🆔 `{u.id}`\n💰 {amount:.2f} ETB — {method_label}\n🔖 Tx: `{tx_id}`",
            parse_mode="Markdown", reply_markup=approval_kb(tx_id))
        user_states.pop(u.id, None)
        await update.message.reply_text(
            f"✅ *ጥያቄዎ ተልኳል!*\n💰 {amount:.2f} ETB — {method_label}",
            parse_mode="Markdown", reply_markup=main_kb(u.id, u.first_name or "Player"))
        return

    if action == "withdraw_amount":
        if not txt.isdigit():
            await update.message.reply_text("⚠️ ቁጥር ብቻ ያስገቡ"); return
        amount = float(txt)
        if amount < 100:
            await update.message.reply_text("⚠️ ዝቅተኛው 100 ብር ነው።"); return
        usr = sv_user(u.id) or {}
        total = (usr.get("balance") or 0) + (usr.get("winBalance") or 0)
        if amount > total:
            await update.message.reply_text(f"❌ ቀሪ ሂሳብ አይበቃም! ያለዎት: {total:.2f}")
            return
        user_states[u.id] = {"action": "withdraw_phone", "amount": amount, "method": state.get("method", "unknown")}
        await update.message.reply_text("📱 የስልክ ቁጥርዎን ያስገቡ:")
        return

    if action == "withdraw_phone":
        phone = txt.strip()
        amount = state.get("amount", 0); method = state.get("method", "unknown")
        tx = sv_tx({"userId": u.id, "type": "withdraw", "amount": amount,
                    "method": method, "phone": phone, "status": "pending"})
        if not tx:
            await update.message.reply_text("⚠️ ኔትወርክ ችግር።"); return
        tx_id = tx["_id"]
        method_label = "📲 Telebirr" if method == "telebirr" else "🏦 CBE"
        await context.bot.send_message(
            ADMIN_ID,
            f"🔔 *አዲስ WITHDRAW*\n👤 {u.first_name}\n🆔 `{u.id}`\n💰 {amount:.2f} ETB — {method_label}\n📱 `{phone}`\n🔖 Tx: `{tx_id}`",
            parse_mode="Markdown", reply_markup=approval_kb(tx_id))
        user_states.pop(u.id, None)
        await update.message.reply_text("✅ *የወጭ ጥያቄዎ ተልኳል!*",
            parse_mode="Markdown", reply_markup=main_kb(u.id, u.first_name or "Player"))
        return

    if "🎯" in txt:
        await update.message.reply_text("🎯 *Play Abisinya Bingo* ን ተጭነው ይጫወቱ!", parse_mode="Markdown")
    elif "👤" in txt:
        await update.message.reply_text("👤 *My Profile* ን ይጫኑ።", parse_mode="Markdown")
    else:
        await update.message.reply_text("🤔 ካርቴላ ይምረጡ እና ይጫወቱ።",
            reply_markup=main_kb(u.id, u.first_name or "Player"))

# ================================================================
#                    BUTTON HANDLER
# ================================================================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q: return
    await q.answer()
    data = q.data; u = q.from_user
    sv_upsert(u.id, u.username or "", u.first_name or "")

    if data.startswith("approve_") or data.startswith("reject_"):
        if u.id != ADMIN_ID: return
        action, tx_id = data.split("_", 1)
        tx = sv_get_tx(tx_id)
        if not tx:
            await q.edit_message_text("❌ Not found"); return
        status = "approved" if action == "approve" else "rejected"
        sv_set_tx_status(tx_id, status)
        if status == "approved":
            if tx["type"] == "deposit": sv_adj(tx["userId"], "balance", tx["amount"])
            elif tx["type"] == "withdraw": sv_adj(tx["userId"], "winBalance", -tx["amount"])
            try: await context.bot.send_message(tx["userId"], f"✅ ጥያቄዎ ፀድቋል: {tx['amount']:.2f} ETB")
            except Exception: pass
        else:
            try: await context.bot.send_message(tx["userId"], f"❌ ጥያቄዎ ተሰርዟል")
            except Exception: pass
        await q.edit_message_text(f"{'✅' if status == 'approved' else '❌'} {tx['type'].upper()} — {tx['amount']:.2f} ETB")
        return

    if data == "m_deposit":
        await q.edit_message_text("💰 *ገንዘብ ማስገባት*\n\nየክፍያ አማራጭ ይምረጡ:",
            parse_mode="Markdown", reply_markup=deposit_kb())
    elif data == "m_withdraw":
        await q.edit_message_text("📤 *የወጭ አማራጭ ይምረጡ:*",
            parse_mode="Markdown", reply_markup=withdraw_kb())
    elif data == "m_balance":
        usr = sv_user(u.id) or {}
        play = usr.get("balance", 0); win = usr.get("winBalance", 0)
        await q.edit_message_text(
            f"💼 *የእርስዎ ዋሌት*\n\n🎯 Playable: *{play:.2f} ብር*\n🏆 Winnings: *{win:.2f} ብር*\n💵 *ጠቅላላ: {play+win:.2f} ብር}*",
            parse_mode="Markdown")
    elif data == "m_invite":
        link = f"https://t.me/{BOT_USERNAME}?start={u.id}"
        await q.edit_message_text(f"👥 *የግብዣ ሊንክ*\n\n`{link}`", parse_mode="Markdown")
    elif data == "m_history":
        await q.edit_message_text("📋 ሙሉ ታሪክዎን ለማየት 👤 *My Profile* ን ይጫኑ።", parse_mode="Markdown")
    elif data == "m_support":
        await q.edit_message_text("💬 *ድጋፍ*\n\n👤 @Tazikes", parse_mode="Markdown")
    elif data == "m_register":
        user_states[u.id] = {"action": "register"}
        await q.edit_message_text("📱 *ስልክ ቁጥር ምዝገባ*\n\nከታች ያለውን *📱 Share My Contact* ይጫኑ ወይም ስልክ ቁጥርዎን ይላኩ።",
            parse_mode="Markdown")
        await context.bot.send_message(u.id, "👇 Tap below to share:", reply_markup=contact_kb())
    elif data == "m_language":
        await q.edit_message_text("🌐 ቋንቋ ይምረጡ:", reply_markup=language_kb())
    elif data == "m_help":
        await q.edit_message_text("ℹ️ *እርዳታ*\n\n1. 🎯 Play\n2. 1–4 ካርቴላ ይምረጡ\n3. JOIN\n4. BINGO ሲሆን ይጫኑ", parse_mode="Markdown")
    elif data == "m_leaderboard":
        await q.edit_message_text("🏆 👤 *My Profile* → 🏆 Leaderboard ን ይጫኑ።", parse_mode="Markdown")
    elif data == "dep_telebirr":
        user_states[u.id] = {"action": "deposit", "method": "telebirr"}
        await q.edit_message_text("🏦 *Telebirr*\n\n👤 tazebew\n👉 `0968940123`\n\n📩 SMS ይለጥፉ:", parse_mode="Markdown")
    elif data == "dep_cbe":
        user_states[u.id] = {"action": "deposit", "method": "cbe"}
        await q.edit_message_text("🏦 *CBE*\n\n👤 tazebew\n👉 `1000390803005`\n\n📩 SMS ይለጥፉ:", parse_mode="Markdown")
    elif data == "wd_telebirr":
        user_states[u.id] = {"action": "withdraw_amount", "method": "telebirr"}
        await q.edit_message_text("🏦 *Telebirr*\n\nየወጭ መጠን (min 100 ETB):", parse_mode="Markdown")
    elif data == "wd_cbe":
        user_states[u.id] = {"action": "withdraw_amount", "method": "cbe"}
        await q.edit_message_text("🏦 *CBE*\n\nየወጭ መጠን (min 100 ETB):", parse_mode="Markdown")
    elif data == "lang_en":
        await q.edit_message_text("✅ Language: English")
    elif data == "lang_am":
        await q.edit_message_text("✅ ቋንቋ: አማርኛ")
    elif data == "lang_om":
        await q.edit_message_text("✅ Afaan: Oromiffa")
    elif data == "lang_ti":
        await q.edit_message_text("✅ ቋንቋ: ትግርኛ")

# ================================================================
#                    WEBHOOKS
# ================================================================
async def notify_tx(request):
    if request.headers.get("x-bot-secret") != BOT_API_SECRET:
        return web.json_response({"ok": False}, status=403)
    d = await request.json(); tg = request.app["tg_app"]
    try:
        icon = "✅" if d["status"] == "approved" else "❌"
        await tg.bot.send_message(d["telegramId"], f"{icon} *{d['type'].upper()}*: {d['amount']:.2f} ETB")
    except Exception: pass
    return web.json_response({"ok": True})

async def broadcast_handler(request):
    if request.headers.get("x-bot-secret") != BOT_API_SECRET:
        return web.json_response({"ok": False}, status=403)
    d = await request.json(); tg = request.app["tg_app"]
    try:
        r = requests.get(f"{SERVER_URL}/api/bot/all-users", headers=H, timeout=10)
        users = _safe(r).get("users", [])
        for usr in users:
            try: await tg.bot.send_message(usr["telegramId"], f"📢 {d['message']}")
            except Exception: pass
    except Exception as e: print("broadcast err:", e)
    return web.json_response({"ok": True})

async def winner_handler(request):
    if request.headers.get("x-bot-secret") != BOT_API_SECRET:
        return web.json_response({"ok": False}, status=403)
    d = await request.json(); tg = request.app["tg_app"]
    try:
        await tg.bot.send_message(d["userId"],
            f"🏆 *እንኳን ደስ አለዎት!*\n\n💰 *{d['prize']:.2f} ETB*\n🎫 ካርቴላ #{d['cartelaId']}",
            parse_mode="Markdown")
    except Exception: pass
    return web.json_response({"ok": True})

# ================================================================
#                    MAIN
# ================================================================
async def main():
    if not TOKEN:
        print("❌ TOKEN missing"); return
    print(f"🔧 SERVER_URL : {SERVER_URL}")
    print(f"🔧 WEBAPP_URL : {WEBAPP_URL}")
    print(f"🔧 BOT_PORT   : {BOT_PORT}")

    tg = ApplicationBuilder().token(TOKEN).build()
    tg.add_handler(CommandHandler("start",   start))
    tg.add_handler(CommandHandler("balance", balance_cmd))
    tg.add_handler(CommandHandler("help",    help_cmd))
    tg.add_handler(CommandHandler("debug",   debug_cmd))
    tg.add_handler(MessageHandler(filters.CONTACT, handle_msg))
    tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    tg.add_handler(CallbackQueryHandler(button_handler))

    webapp = web.Application()
    webapp["tg_app"] = tg
    webapp.router.add_post("/notify-tx",  notify_tx)
    webapp.router.add_post("/broadcast",  broadcast_handler)
    webapp.router.add_post("/winner",     winner_handler)
    webapp.router.add_get ("/",           lambda r: web.json_response({"ok": True}))

    await tg.initialize()
    await tg.start()
    runner = web.AppRunner(webapp)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", BOT_PORT)
    await site.start()
    print(f"🌐 Webhook on port {BOT_PORT}")
    await tg.updater.start_polling()
    print("🤖 Bot running")
    await asyncio.Event().wait()

if __name__ == "__main__":
    try: asyncio.run(main())
    except (KeyboardInterrupt, SystemExit): print("👋 Stopped")