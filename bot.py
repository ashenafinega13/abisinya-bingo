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
#                        CONFIG
# ================================================================
TOKEN             = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID          = int(os.getenv("ADMIN_ID", "0"))
SERVER_URL        = (os.getenv("SERVER_URL") or "").rstrip("/")
WEBAPP_URL        = (os.getenv("WEBAPP_URL") or "").rstrip("/")
BOT_API_SECRET    = os.getenv("BOT_API_SECRET", "change-me")
BOT_PORT          = int(os.getenv("PORT", os.getenv("BOT_PORT", "8080")))
BOT_USERNAME      = os.getenv("BOT_USERNAME", "AbyssinaBingobot")

H = {"x-bot-secret": BOT_API_SECRET, "Content-Type": "application/json"}

# ================================================================
#                        SERVER HELPERS
# ================================================================
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
    except Exception as e:
        print("sv_user:", e); return None

def sv_adj(uid, field, delta):
    try:
        r = requests.post(f"{SERVER_URL}/api/bot/user/{uid}/adjust", headers=H,
                          timeout=10, json={"field": field, "delta": delta})
        return _safe(r).get("user")
    except Exception as e:
        print("sv_adj:", e); return None

def sv_tx(data):
    try:
        r = requests.post(f"{SERVER_URL}/api/bot/transaction", headers=H,
                          timeout=10, json=data)
        return _safe(r).get("tx")
    except Exception as e:
        print("sv_tx:", e); return None

def sv_get_tx(tx_id):
    try:
        r = requests.get(f"{SERVER_URL}/api/bot/transaction/{tx_id}",
                         headers=H, timeout=10)
        return _safe(r).get("tx")
    except Exception as e:
        print("sv_get_tx:", e); return None

def sv_set_tx_status(tx_id, status):
    try:
        requests.post(f"{SERVER_URL}/api/bot/transaction/{tx_id}/status",
                      headers=H, timeout=10, json={"status": status})
    except Exception as e:
        print("sv_set_tx_status:", e)

# ================================================================
#                        URL BUILDERS
# ================================================================
def game_url(uid, name):
    return f"{WEBAPP_URL}/game?uid={uid}&name={name}"

def profile_url(uid, tab="history"):
    return f"{WEBAPP_URL}/profile.html?uid={uid}&tab={tab}"

# ================================================================
#                        KEYBOARDS
# ================================================================
def main_kb(uid, name):
    """Compact keyboard: Play + Menu button."""
    keyboard = [
        [KeyboardButton("🎯 Play Abisinya Bingo",
                        web_app=WebAppInfo(url=game_url(uid, name)))],
        [KeyboardButton("☰ Menu"), KeyboardButton("👤 Profile",
                        web_app=WebAppInfo(url=profile_url(uid, "history")))],
    ]
    return ReplyKeyboardMarkup(
        keyboard, resize_keyboard=True, is_persistent=True,
        input_field_placeholder="Choose an action…"
    )

def menu_text():
    return (
        "📋 **Menu Options**\n\n"
        "• /register - ቁጥርዎን ይመዝግቡ (Register)\n"
        "• /play - ቢንጎ ይጫወቱ (Play)\n"
        "• /balance - የመለያ ቀሪ ሂሳብ ይፈትሹ (Balance)\n"
        "• /deposit - ገንዘብ ያስገቡ (Deposit)\n"
        "• /withdraw - ገንዘብ ያውጡ (Withdraw)\n"
        "• /howtoplay - አንዳንድ መጫወቻ ደንቦች (How to Play)\n"
        "• /invite - ጋብዝ (Invite)\n"
        "• /support - ድጋፍ (Support)\n"
        "• /language - ቋንቋ (Language)\n\n"
        "👇 You can also use the / commands below or tap the buttons."
    )

def contact_kb():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("📱 Share My Contact", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )

def deposit_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📲 Telebirr", callback_data="dep_telebirr")],
        [InlineKeyboardButton("🏦 CBE",      callback_data="dep_cbe")],
    ])

def withdraw_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📲 Telebirr", callback_data="wd_telebirr")],
        [InlineKeyboardButton("🏦 CBE",      callback_data="wd_cbe")],
    ])

def approval_kb(tx_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=f"approve_{tx_id}"),
        InlineKeyboardButton("❌ Reject",  callback_data=f"reject_{tx_id}")
    ]])

def language_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🇬🇧 English",   callback_data="lang_en")],
        [InlineKeyboardButton("🇪🇹 አማርኛ",     callback_data="lang_am")],
        [InlineKeyboardButton("🇪🇹 Oromiffa",  callback_data="lang_om")],
        [InlineKeyboardButton("🇪🇹 ትግርኛ",    callback_data="lang_ti")],
    ])

# ================================================================
#                        USER STATE
# ================================================================
user_states = {}

# ================================================================
#                        COMMANDS
# ================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message: return
    u = update.effective_user
    sv_upsert(u.id, u.username or "", u.first_name or "")

    if context.args and context.args[0].isdigit():
        ref = int(context.args[0])
        if ref != u.id:
            sv_adj(ref, "balance", 30)
            try: await context.bot.send_message(ref, "🎉 +30 ብር")
            except: pass

    name = u.first_name or "Player"
    await update.message.reply_text(
        f"👋 *ሰላም {name}!*\n\n🎉 እንኳን ወደ *Abisinya Bingo* በደህና መጡ።",
        parse_mode="Markdown",
        reply_markup=main_kb(u.id, name)
    )

async def play_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await update.message.reply_text(
        f"👇 Tap the button below to open the game:",
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton("🎯 Open Game", web_app=WebAppInfo(url=game_url(u.id, u.first_name or "Player")))]],
            resize_keyboard=True, one_time_keyboard=True
        )
    )

async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    usr = sv_user(u.id) or {}
    play = usr.get("balance", 0)
    win  = usr.get("winBalance", 0)
    total = play + win
    await update.message.reply_text(
        f"💼 *የእርስዎ ዋሌት*\n\n"
        f"🎯 Playable: *{play:.2f} ብር*\n"
        f"🏆 Winnings: *{win:.2f} ብር*\n"
        f"━━━━━━━━━━━━━━\n"
        f"💵 *ጠቅላላ: {total:.2f} ብር}*",
        parse_mode="Markdown"
    )

async def how_to_play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎯 *እንዴት እንደሚጫወቱ*\n\n"
        "1. /play ን ይጫኑ\n"
        "2. ካርቴላ ይምረጡ\n"
        "3. አንድ ሙሉ መስመር ሲሟላ BINGO ይጫኑ\n\n"
        "⚡ Auto-Bingo ን ካበሩ ማሽኑ ራሱ ያሸንፋል።",
        parse_mode="Markdown"
    )

async def invite_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    link = f"https://t.me/{BOT_USERNAME}?start={u.id}"
    await update.message.reply_text(
        f"👥 *የግብዣ ሊንክ*\n\n`{link}`\n\n✨ ጓደኛ ይጋብዙ እና 30 ብር ያግኙ!",
        parse_mode="Markdown"
    )

# ================================================================
#                        MESSAGE HANDLER
# ================================================================
async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Contact sharing
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

    # MENU BUTTON CLICK
    if txt == "☰ Menu":
        user_states.pop(u.id, None)
        await update.message.reply_text(menu_text(), parse_mode="Markdown")
        return

    # PROFILE BUTTON CLICK
    if txt == "👤 Profile":
        await update.message.reply_text(
            "👇 Tap the button below to open your profile:",
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("👤 Open Profile", web_app=WebAppInfo(url=profile_url(u.id)))]],
                resize_keyboard=True, one_time_keyboard=True
            )
        )
        return

    state = user_states.get(u.id, {})
    action = state.get("action")

    # Registration manual input
    if action == "register":
        phone = txt.strip()
        if not re.match(r"^\+?\d{9,15}$", phone):
            await update.message.reply_text("⚠️ Please send a valid phone number or share your contact.")
            return
        sv_upsert(u.id, u.username or "", u.first_name or "", phone=phone)
        user_states.pop(u.id, None)
        await update.message.reply_text(
            f"✅ *ተመዝግቧል!*\n\n📱 `{phone}`",
            parse_mode="Markdown", reply_markup=main_kb(u.id, u.first_name or "Player"))
        return

    # Deposit SMS input
    if action == "deposit":
        m = re.search(r"(\d+(?:[.,]\d+)?)", txt)
        amount = float(m.group(1).replace(",", "")) if m else 0
        if amount < 1:
            await update.message.reply_text("⚠️ ትክክለኛ መጠን ያስገቡ (ለምሳሌ: 100)")
            return
        tx = sv_tx({
            "userId": u.id, "type": "deposit", "amount": amount,
            "method": state.get("method", "unknown"), "sms": txt, "status": "pending"
        })
        if not tx:
            await update.message.reply_text("⚠️ ኔትወርክ ችግር።"); return
        tx_id = tx["_id"]
        method_label = "📲 Telebirr" if state.get("method") == "telebirr" else "🏦 CBE"
        await context.bot.send_message(
            ADMIN_ID,
            f"🔔 *አዲስ DEPOSIT*\n\n👤 {u.first_name} (@{u.username or 'N/A'})\n🆔 `{u.id}`\n💰 {amount:.2f} ETB — {method_label}\n🔖 Tx: `{tx_id}`",
            parse_mode="Markdown", reply_markup=approval_kb(tx_id)
        )
        user_states.pop(u.id, None)
        await update.message.reply_text(
            f"✅ *ጥያቄዎ ተልኳል!*\n\n💰 {amount:.2f} ETB — {method_label}\n⏳ አስተዳዳሪው ሲያጸድቅ ወደ ዋሌትዎ ይገባል።",
            parse_mode="Markdown", reply_markup=main_kb(u.id, u.first_name or "Player")
        )
        return

    # Withdraw amount input
    if action == "withdraw_amount":
        if not txt.isdigit():
            await update.message.reply_text("⚠️ ቁጥር ብቻ ያስገቡ"); return
        amount = float(txt)
        if amount < 100:
            await update.message.reply_text("⚠️ ዝቅተኛው 100 ብር ነው።"); return
        usr = sv_user(u.id) or {}
        total = (usr.get("balance") or 0) + (usr.get("winBalance") or 0)
        if amount > total:
            await update.message.reply_text(f"❌ ቀሪ ሂሳብ አይበቃም! (ያለዎት: {total:.2f})"); return
        user_states[u.id] = {"action": "withdraw_phone", "amount": amount, "method": state.get("method", "unknown")}
        await update.message.reply_text("📱 የስልክ ቁጥርዎን ያስገቡ:")
        return

    # Withdraw phone input
    if action == "withdraw_phone":
        phone = txt.strip()
        amount = state.get("amount", 0)
        method = state.get("method", "unknown")
        tx = sv_tx({
            "userId": u.id, "type": "withdraw", "amount": amount,
            "method": method, "phone": phone, "status": "pending"
        })
        if not tx:
            await update.message.reply_text("⚠️ ኔትወርክ ችግር።"); return
        tx_id = tx["_id"]
        method_label = "📲 Telebirr" if method == "telebirr" else "🏦 CBE"
        await context.bot.send_message(
            ADMIN_ID,
            f"🔔 *አዲስ WITHDRAW*\n\n👤 {u.first_name} (@{u.username or 'N/A'})\n🆔 `{u.id}`\n💰 {amount:.2f} ETB — {method_label}\n📱 `{phone}`\n🔖 Tx: `{tx_id}`",
            parse_mode="Markdown", reply_markup=approval_kb(tx_id)
        )
        user_states.pop(u.id, None)
        await update.message.reply_text(
            f"✅ *የወጭ ጥያቄዎ ተልኳል!*",
            parse_mode="Markdown", reply_markup=main_kb(u.id, u.first_name or "Player")
        )
        return

    # Fallback
    await update.message.reply_text(
        "🤔 ካርቴላ ይምረጡ እና ይጫወቱ። /play",
        reply_markup=main_kb(u.id, u.first_name or "Player")
    )

# ================================================================
#                        BUTTON HANDLER
# ================================================================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q: return
    await q.answer()
    data = q.data
    u = q.from_user
    sv_upsert(u.id, u.username or "", u.first_name or "")

    if data.startswith("approve_") or data.startswith("reject_"):
        if u.id != ADMIN_ID: return
        action, tx_id = data.split("_", 1)
        tx = sv_get_tx(tx_id)
        if not tx:
            await q.edit_message_text("❌ Transaction not found"); return
        status = "approved" if action == "approve" else "rejected"
        sv_set_tx_status(tx_id, status)
        if status == "approved":
            if tx["type"] == "deposit":
                sv_adj(tx["userId"], "balance", tx["amount"])
                try: await context.bot.send_message(tx["userId"], f"✅ ጥያቄዎ ፀድቋል! +{tx['amount']:.2f} ETB", parse_mode="Markdown")
                except: pass
            elif tx["type"] == "withdraw":
                sv_adj(tx["userId"], "winBalance", -tx["amount"])
                try: await context.bot.send_message(tx["userId"], f"✅ የወጭ ጥያቄዎ ፀድቋል! -{tx['amount']:.2f} ETB", parse_mode="Markdown")
                except: pass
        else:
            try: await context.bot.send_message(tx["userId"], f"❌ ጥያቄዎ ተሰርዟል", parse_mode="Markdown")
            except: pass
        await q.edit_message_text(f"{'✅' if status == 'approved' else '❌'} {tx['type'].upper()} — {tx['amount']:.2f} ETB")
        return

    if data == "dep_telebirr":
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
    elif data == "lang_en": await q.edit_message_text("✅ Language: English")
    elif data == "lang_am": await q.edit_message_text("✅ ቋንቋ: አማርኛ")
    elif data == "lang_om": await q.edit_message_text("✅ Afaan: Oromiffa")
    elif data == "lang_ti": await q.edit_message_text("✅ ቋንቋ: ትግርኛ")

# ================================================================
#                        WEBHOOKS & MAIN
# ================================================================
async def notify_tx(request):
    if request.headers.get("x-bot-secret") != BOT_API_SECRET:
        return web.json_response({"ok": False}, status=403)
    d = await request.json()
    tg = request.app["tg_app"]
    try:
        icon = "✅" if d["status"] == "approved" else "❌"
        await tg.bot.send_message(d["telegramId"], f"{icon} *{d['type'].upper()}*\n\n💰 {d['amount']:.2f} ETB — {d['status']}", parse_mode="Markdown")
    except: pass
    return web.json_response({"ok": True})

async def winner_handler(request):
    if request.headers.get("x-bot-secret") != BOT_API_SECRET:
        return web.json_response({"ok": False}, status=403)
    d = await request.json()
    tg = request.app["tg_app"]
    try:
        await tg.bot.send_message(d["userId"], f"🏆 *እንኳን ደስ አለዎት!*\n\n💰 *{d['prize']:.2f} ETB*\n🎫 ካርቴላ #{d['cartelaId']}", parse_mode="Markdown")
    except: pass
    return web.json_response({"ok": True})

async def post_init(app):
    commands = [
        BotCommand("start", "ብቀን ይጀምሩ (Start)"),
        BotCommand("play", "ቢንጎ ይጫወቱ (Play)"),
        BotCommand("balance", "የመለያ ቀሪ ሂሳብ ይፈትሹ"),
        BotCommand("deposit", "ገንዘብ ያስገቡ"),
        BotCommand("withdraw", "ገንዘብ ያውጡ"),
        BotCommand("register", "ቁጥርዎን ይመዝግቡ"),
        BotCommand("howtoplay", "መጫወቻ ደንቦች"),
        BotCommand("invite", "ጓደኛ ይጋብዙ"),
        BotCommand("language", "ቋንቋ ይቀይሩ"),
    ]
    await app.bot.set_my_commands(commands)

async def main():
    if not TOKEN: return
    tg = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    
    tg.add_handler(CommandHandler("start", start))
    tg.add_handler(CommandHandler("play", play_cmd))
    tg.add_handler(CommandHandler("balance", balance_cmd))
    tg.add_handler(CommandHandler("register", lambda u,c: u.message.reply_text("📱 Share your contact below:", reply_markup=contact_kb())))
    tg.add_handler(CommandHandler("deposit", lambda u,c: u.message.reply_text("💰 የክፍያ አማራጭ ይምረጡ:", reply_markup=deposit_kb())))
    tg.add_handler(CommandHandler("withdraw", lambda u,c: u.message.reply_text("📤 የወጭ አማራጭ ይምረጡ:", reply_markup=withdraw_kb())))
    tg.add_handler(CommandHandler("howtoplay", how_to_play))
    tg.add_handler(CommandHandler("invite", invite_cmd))
    tg.add_handler(CommandHandler("language", lambda u,c: u.message.reply_text("🌐 ቋንቋ ይምረጡ:", reply_markup=language_kb())))
    
    tg.add_handler(MessageHandler(filters.CONTACT, handle_msg))
    tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    tg.add_handler(CallbackQueryHandler(button_handler))

    webapp = web.Application()
    webapp["tg_app"] = tg
    webapp.router.add_post("/notify-tx", notify_tx)
    webapp.router.add_post("/winner", winner_handler)
    webapp.router.add_get("/", lambda r: web.json_response({"ok": True}))

    await tg.initialize()
    await tg.start()
    runner = web.AppRunner(webapp)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", BOT_PORT)
    await site.start()
    print("🤖 Bot running")
    await asyncio.Event().wait()

if __name__ == "__main__":
    try: asyncio.run(main())
    except (KeyboardInterrupt, SystemExit): pass