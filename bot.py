import os
import re
import asyncio
import requests
from dotenv import load_dotenv

# Load .env BEFORE any os.getenv()
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

# ================================================================
#                        CONFIG
# ================================================================
TOKEN             = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID          = int(os.getenv("ADMIN_ID", "0"))
SERVER_URL        = (os.getenv("SERVER_URL") or "").rstrip("/")
WEBAPP_URL        = (os.getenv("WEBAPP_URL") or "").rstrip("/")
BOT_API_SECRET    = os.getenv("BOT_API_SECRET", "change-me")
# Render injects PORT; fall back to BOT_PORT (local) then 8080
BOT_PORT          = int(os.getenv("PORT", os.getenv("BOT_PORT", "8080")))
BOT_USERNAME      = os.getenv("BOT_USERNAME", "AbyssinaBingobot")

# Telegram bot username to deep-link back from WebApp → Bot
TG_BOT_FOR_LINKS  = BOT_USERNAME

H = {"x-bot-secret": BOT_API_SECRET, "Content-Type": "application/json"}

# ================================================================
#                        SERVER HELPERS
# ================================================================
def _safe_json(r):
    try:
        return r.json()
    except Exception:
        return {}

def sv_upsert(uid, uname, fname, phone=None):
    try:
        r = requests.post(
            f"{SERVER_URL}/api/bot/user", headers=H, timeout=10,
            json={"telegramId": uid, "username": uname, "firstName": fname, "phone": phone}
        )
        return _safe_json(r).get("user")
    except Exception as e:
        print("sv_upsert error:", e); return None

def sv_user(uid):
    try:
        r = requests.get(f"{SERVER_URL}/api/bot/user/{uid}", headers=H, timeout=10)
        return _safe_json(r).get("user")
    except Exception as e:
        print("sv_user error:", e); return None

def sv_adj(uid, field, delta):
    try:
        r = requests.post(
            f"{SERVER_URL}/api/bot/user/{uid}/adjust", headers=H, timeout=10,
            json={"field": field, "delta": delta}
        )
        return _safe_json(r).get("user")
    except Exception as e:
        print("sv_adj error:", e); return None

def sv_tx(data):
    try:
        r = requests.post(f"{SERVER_URL}/api/bot/transaction", headers=H,
                          timeout=10, json=data)
        return _safe_json(r).get("tx")
    except Exception as e:
        print("sv_tx error:", e); return None

def sv_get_tx(tx_id):
    try:
        r = requests.get(f"{SERVER_URL}/api/bot/transaction/{tx_id}",
                         headers=H, timeout=10)
        return _safe_json(r).get("tx")
    except Exception as e:
        print("sv_get_tx error:", e); return None

def sv_set_tx_status(tx_id, status):
    try:
        requests.post(
            f"{SERVER_URL}/api/bot/transaction/{tx_id}/status",
            headers=H, timeout=10, json={"status": status}
        )
    except Exception as e:
        print("sv_set_tx_status error:", e)

# ================================================================
#                        URL BUILDERS
# ================================================================
def game_url(uid, name):
    """Telegram WebApp URL → opens the picker screen directly."""
    return f"{WEBAPP_URL}/game?uid={uid}&name={name}"

def profile_url(uid):
    """Telegram WebApp URL → opens the profile/wallet page."""
    return f"{WEBAPP_URL}/profile.html?uid={uid}"

# ================================================================
#                        KEYBOARDS
# ================================================================
def main_kb(uid, name):
    keyboard = [
        [KeyboardButton("🎯 Play Abisinya Bingo",
                        web_app=WebAppInfo(url=game_url(uid, name)))],
        [KeyboardButton("👤 My Profile",
                        web_app=WebAppInfo(url=profile_url(uid)))],
        [KeyboardButton("💰 Deposit"), KeyboardButton("📤 Withdraw")],
        [KeyboardButton("💵 Check Balance"), KeyboardButton("👥 Invite Friends")],
        [KeyboardButton("📋 History"), KeyboardButton("💬 Support")],
        [KeyboardButton("📱 Register"), KeyboardButton("🌍 Language")],
        [KeyboardButton("ℹ️ Help"), KeyboardButton("🏆 Leaderboard")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)

def deposit_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📲 Telebirr", callback_data="dep_telebirr")],
        [InlineKeyboardButton("🏦 CBE", callback_data="dep_cbe")],
    ])

def withdraw_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📲 Telebirr", callback_data="wd_telebirr")],
        [InlineKeyboardButton("🏦 CBE", callback_data="wd_cbe")],
    ])

def approval_kb(tx_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{tx_id}"),
         InlineKeyboardButton("❌ Reject",  callback_data=f"reject_{tx_id}")]
    ])

# ================================================================
#                        USER STATE
# ================================================================
user_states = {}

# ================================================================
#                        COMMANDS
# ================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return
    u = update.effective_user
    sv_upsert(u.id, u.username or "", u.first_name or "")

    # Handle referral links: /start 123456
    if context.args and context.args[0].isdigit():
        ref = int(context.args[0])
        if ref != u.id:
            sv_adj(ref, "balance", 30)
            try:
                await context.bot.send_message(ref, "🎉 አዲስ ጓደኛ ጋበዝክ! +30 ብር")
            except Exception:
                pass

    await update.message.reply_text(
        "🎉 እንኳን ወደ Abisinya Bingo በደህና መጡ!\n\n"
        "🎯 Play ን ተጭነው ይጫወቱ።\n"
        "👤 My Profile ን ተጭነው ዋሌትዎን፣ ታሪክዎን እና ሊደርቦርድ ይመልከቱ።",
        reply_markup=main_kb(u.id, u.first_name or "Player")
    )

async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    usr = sv_user(u.id) or {}
    await update.message.reply_text(
        f"💰 ቀሪ ሂሳብ: {usr.get('balance', 0):.2f} ብር\n"
        f"🏆 የድል ሂሳብ: {usr.get('winBalance', 0):.2f} ብር"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ እርዳታ:\n\n"
        "1. 🎯 Play ይጫኑ\n"
        "2. 1–4 ካርቴላ ይምረጡ\n"
        "3. JOIN ይጫኑ\n"
        "4. 4 ማዕዘኖች ሲሟሉ BINGO ይጫኑ\n\n"
        "⚡ Auto-Bingo ን ካበሩ በራስ-ሰር ያሸንፋል።"
    )

async def debug_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await update.message.reply_text(
        f"🔧 DEBUG\n\n"
        f"SERVER_URL: {SERVER_URL}\n"
        f"WEBAPP_URL: {WEBAPP_URL}\n"
        f"BOT_USERNAME: {BOT_USERNAME}\n"
        f"Play URL: {game_url(u.id, u.first_name or 'Player')}\n"
        f"Profile URL: {profile_url(u.id)}"
    )

# ================================================================
#                        MESSAGE HANDLER
# ================================================================
async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    if not update.effective_user:
        return

    u = update.effective_user
    txt = update.message.text.strip()
    sv_upsert(u.id, u.username or "", u.first_name or "")

    state = user_states.get(u.id, {})
    action = state.get("action")

    # Any menu tap cancels pending action
    is_menu = any(x in txt for x in
                  ["🎯","👤","💰","📤","💵","👥","📋","💬","📱","🌍","ℹ️","🏆"])
    if is_menu:
        user_states.pop(u.id, None)
        action = None

    # ---------- REGISTER ----------
    if action == "register":
        phone = txt.strip()
        sv_upsert(u.id, u.username or "", u.first_name or "", phone=phone)
        user_states.pop(u.id, None)
        await update.message.reply_text(
            f"✅ ተመዝግቧል: {phone}",
            reply_markup=main_kb(u.id, u.first_name or "Player")
        )
        return

    # ---------- DEPOSIT ----------
    if action == "deposit":
        m = re.search(r"(\d+(?:[.,]\d+)?)", txt)
        amount = float(m.group(1).replace(",", "")) if m else 0
        if amount < 1:
            await update.message.reply_text("⚠️ ትክክለኛ መጠን ያስገቡ (ለምሳሌ: 100)")
            return

        tx = sv_tx({
            "userId": u.id, "type": "deposit", "amount": amount,
            "method": state.get("method", "unknown"),
            "sms": txt, "status": "pending"
        })
        if not tx:
            await update.message.reply_text("⚠️ ኔትወርክ ችግር። እባክህ በድጋሚ ሞክር።")
            return
        tx_id = tx["_id"]
        method_label = "📲 TeleBirr" if state.get("method") == "telebirr" else "🏦 CBE"

        await context.bot.send_message(
            ADMIN_ID,
            f"🔔 **አዲስ DEPOSIT**\n\n"
            f"👤 {u.first_name} (@{u.username or 'N/A'})\n"
            f"🆔 `{u.id}`\n"
            f"💰 {amount:.2f} ETB — {method_label}\n"
            f"🔖 Tx: `{tx_id}`",
            parse_mode="Markdown",
            reply_markup=approval_kb(tx_id)
        )
        user_states.pop(u.id, None)
        await update.message.reply_text(
            "✅ ጥያቄዎ ለአስተዳዳሪ ተልኳል።",
            reply_markup=main_kb(u.id, u.first_name or "Player")
        )
        return

    # ---------- WITHDRAW: amount ----------
    if action == "withdraw_amount":
        if not txt.isdigit():
            await update.message.reply_text("⚠️ ቁጥር ብቻ ያስገቡ (ለምሳሌ: 100)")
            return
        amount = float(txt)
        if amount < 100:
            await update.message.reply_text("⚠️ ዝቅተኛው የወጭ መጠን 100 ብር ነው።")
            return

        usr = sv_user(u.id) or {}
        total = (usr.get("balance") or 0) + (usr.get("winBalance") or 0)
        if amount > total:
            await update.message.reply_text(
                f"❌ ቀሪ ሂሳብ አይበቃም!\n"
                f"💰 ያለዎት: {total:.2f} ብር\n"
                f"💸 የጠየቁት: {amount:.2f} ብር"
            )
            return

        user_states[u.id] = {
            "action": "withdraw_phone",
            "amount": amount,
            "method": state.get("method", "unknown")
        }
        await update.message.reply_text("📱 የስልክ ቁጥርዎን ያስገቡ:")
        return

    # ---------- WITHDRAW: phone ----------
    if action == "withdraw_phone":
        phone = txt.strip()
        amount = state.get("amount", 0)
        method = state.get("method", "unknown")

        tx = sv_tx({
            "userId": u.id, "type": "withdraw", "amount": amount,
            "method": method, "phone": phone, "status": "pending"
        })
        if not tx:
            await update.message.reply_text("⚠️ ኔትወርክ ችግር። እባክህ በድጋሚ ሞክር።")
            return
        tx_id = tx["_id"]
        method_label = "📲 TeleBirr" if method == "telebirr" else "🏦 CBE"

        await context.bot.send_message(
            ADMIN_ID,
            f"🔔 **አዲስ WITHDRAW**\n\n"
            f"👤 {u.first_name} (@{u.username or 'N/A'})\n"
            f"🆔 `{u.id}`\n"
            f"💰 {amount:.2f} ETB — {method_label}\n"
            f"📱 `{phone}`\n"
            f"🔖 Tx: `{tx_id}`",
            parse_mode="Markdown",
            reply_markup=approval_kb(tx_id)
        )
        user_states.pop(u.id, None)
        await update.message.reply_text(
            f"✅ የወጭ ጥያቄዎ ተልኳል።\n💰 {amount:.2f} ብር\n📱 {phone}",
            reply_markup=main_kb(u.id, u.first_name or "Player")
        )
        return

    # ---------- MENU BUTTONS ----------
    if "🎯" in txt:
        await update.message.reply_text("🎯 Play ን ተጭነው ይጫወቱ!")

    elif "👤" in txt or "Profile" in txt:
        await update.message.reply_text(
            "👤 My Profile ን ይጫኑ — ዋሌትዎን፣ ታሪክዎን እና ሊደርቦርድ ያያሉ።"
        )

    elif "💰" in txt or "Deposit" in txt:
        await update.message.reply_text(
            "💰 **ገንዘብ ማስገባት**\n\nየክፍያ አማራጭ ይምረጡ:",
            parse_mode="Markdown",
            reply_markup=deposit_kb()
        )

    elif "📤" in txt or "Withdraw" in txt:
        await update.message.reply_text(
            "📤 **የወጭ አማራጭ ይምረጡ:**",
            parse_mode="Markdown",
            reply_markup=withdraw_kb()
        )

    elif "💵" in txt or "Balance" in txt:
        await balance_cmd(update, context)

    elif "👥" in txt or "Invite" in txt:
        link = f"https://t.me/{BOT_USERNAME}?start={u.id}"
        await update.message.reply_text(
            f"👥 **የግብዣ ሊንክ**\n\n{link}\n\n"
            f"✨ ጓደኛዎን ይጋብዙ እና 30 ብር ያግኙ!",
            parse_mode="Markdown"
        )

    elif "📋" in txt or "History" in txt:
        await update.message.reply_text(
            "📋 ሙሉ ታሪክዎን ለማየት 👤 My Profile ን ይጫኑ።"
        )

    elif "💬" in txt or "Support" in txt:
        await update.message.reply_text("💬 **ድጋፍ**\n\n👤 @Tazikes", parse_mode="Markdown")

    elif "📱" in txt or "Register" in txt:
        user_states[u.id] = {"action": "register"}
        await update.message.reply_text(
            "📱 **ስልክ ቁጥር ምዝገባ**\n\n"
            "ስልክ ቁጥርዎን ያስገቡ:\n\nለምሳሌ: `0912345678`",
            parse_mode="Markdown"
        )

    elif "🌍" in txt or "Language" in txt:
        await update.message.reply_text("🌐 ቋንቋ: አማርኛ | English (በቅርቡ)")

    elif "ℹ️" in txt or "Help" in txt:
        await help_cmd(update, context)

    elif "🏆" in txt or "Leaderboard" in txt:
        await update.message.reply_text(
            "🏆 ሙሉ ሊደርቦርድ ለማየት 👤 My Profile → 🏆 Leaderboard ን ይጫኑ።"
        )

    else:
        await update.message.reply_text("ጥያቄዎን አልተረዳሁም። ከታች ያሉትን አዝራሮች ይጠቀሙ።",
                                        reply_markup=main_kb(u.id, u.first_name or "Player"))

# ================================================================
#                        BUTTON HANDLER
# ================================================================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return
    await q.answer()
    data = q.data
    u = q.from_user
    sv_upsert(u.id, u.username or "", u.first_name or "")

    # ---------- ADMIN: Approve / Reject ----------
    if data.startswith("approve_") or data.startswith("reject_"):
        if u.id != ADMIN_ID:
            return
        action, tx_id = data.split("_", 1)
        tx = sv_get_tx(tx_id)
        if not tx:
            await q.edit_message_text("❌ Transaction not found")
            return

        status = "approved" if action == "approve" else "rejected"
        sv_set_tx_status(tx_id, status)

        if status == "approved":
            if tx["type"] == "deposit":
                sv_adj(tx["userId"], "balance", tx["amount"])
                try:
                    await context.bot.send_message(
                        tx["userId"],
                        f"✅ ጥያቄዎ ፀድቋል!\n💰 {tx['amount']:.2f} ETB ወደ ዋሌትዎ ተጨምሯል።"
                    )
                except Exception:
                    pass
            elif tx["type"] == "withdraw":
                sv_adj(tx["userId"], "winBalance", -tx["amount"])
                try:
                    await context.bot.send_message(
                        tx["userId"],
                        f"✅ የወጭ ጥያቄዎ ፀድቋል!\n💰 {tx['amount']:.2f} ETB"
                    )
                except Exception:
                    pass
        else:
            try:
                await context.bot.send_message(
                    tx["userId"],
                    f"❌ ጥያቄዎ ተሰርዟል: {tx['amount']:.2f} ETB"
                )
            except Exception:
                pass

        await q.edit_message_text(
            f"{'✅' if status == 'approved' else '❌'} "
            f"{tx['type'].upper()} — {tx['amount']:.2f} ETB"
        )
        return

    # ---------- Deposit method selection ----------
    if data == "dep_telebirr":
        user_states[u.id] = {"action": "deposit", "method": "telebirr"}
        await q.edit_message_text(
            "🏦 **Telebirr**\n\n"
            "👤 Name: tazebew\n"
            "👉 Account: 0968940123\n\n"
            "📩 የባንክ SMS ይለጥፉ:",
            parse_mode="Markdown"
        )
    elif data == "dep_cbe":
        user_states[u.id] = {"action": "deposit", "method": "cbe"}
        await q.edit_message_text(
            "🏦 **CBE**\n\n"
            "👤 Name: tazebew\n"
            "👉 Account: 1000390803005\n\n"
            "📩 የባንክ SMS ይለጥፉ:",
            parse_mode="Markdown"
        )

    # ---------- Withdraw method selection ----------
    elif data == "wd_telebirr":
        user_states[u.id] = {"action": "withdraw_amount", "method": "telebirr"}
        await q.edit_message_text(
            "🏦 **Telebirr**\n\nየወጭ መጠን (min 100 ETB):",
            parse_mode="Markdown"
        )
    elif data == "wd_cbe":
        user_states[u.id] = {"action": "withdraw_amount", "method": "cbe"}
        await q.edit_message_text(
            "🏦 **CBE**\n\nየወጭ መጠን (min 100 ETB):",
            parse_mode="Markdown"
        )

# ================================================================
#                        WEBHOOK ENDPOINTS
# ================================================================
async def notify_tx(request):
    if request.headers.get("x-bot-secret") != BOT_API_SECRET:
        return web.json_response({"ok": False}, status=403)
    d = await request.json()
    tg = request.app["tg_app"]
    try:
        icon = "✅" if d["status"] == "approved" else "❌"
        await tg.bot.send_message(
            d["telegramId"],
            f"{icon} {d['type']} {d['amount']:.2f} ETB — {d['status']}"
        )
    except Exception:
        pass
    return web.json_response({"ok": True})

async def broadcast_handler(request):
    if request.headers.get("x-bot-secret") != BOT_API_SECRET:
        return web.json_response({"ok": False}, status=403)
    d = await request.json()
    tg = request.app["tg_app"]
    try:
        r = requests.get(f"{SERVER_URL}/api/bot/all-users", headers=H, timeout=10)
        users = _safe_json(r).get("users", [])
        sent = 0
        for usr in users:
            try:
                await tg.bot.send_message(usr["telegramId"], f"📢 {d['message']}")
                sent += 1
            except Exception:
                pass
        print(f"📢 broadcast sent to {sent}/{len(users)} users")
    except Exception as e:
        print("broadcast err:", e)
    return web.json_response({"ok": True})

async def winner_handler(request):
    if request.headers.get("x-bot-secret") != BOT_API_SECRET:
        return web.json_response({"ok": False}, status=403)
    d = await request.json()
    tg = request.app["tg_app"]
    try:
        await tg.bot.send_message(
            d["userId"],
            f"🏆 **እንኳን ደስ አለዎት!**\n\n"
            f"💰 {d['prize']:.2f} ETB\n"
            f"🎫 ካርቴላ #{d['cartelaId']}\n\n"
            f"ወደ 👤 My Profile በመሄድ ያረጋግጡ።",
            parse_mode="Markdown"
        )
    except Exception:
        pass
    return web.json_response({"ok": True})

# ================================================================
#                        MAIN
# ================================================================
async def main():
    if not TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN is missing! Check your .env or Render env vars.")
        return
    if not SERVER_URL or not WEBAPP_URL:
        print("⚠️ SERVER_URL or WEBAPP_URL missing — WebApp buttons will not work.")

    print(f"🔧 SERVER_URL: {SERVER_URL}")
    print(f"🔧 WEBAPP_URL: {WEBAPP_URL}")
    print(f"🔧 BOT_PORT:   {BOT_PORT}")

    tg = ApplicationBuilder().token(TOKEN).build()

    # Commands
    tg.add_handler(CommandHandler("start",   start))
    tg.add_handler(CommandHandler("balance", balance_cmd))
    tg.add_handler(CommandHandler("help",    help_cmd))
    tg.add_handler(CommandHandler("debug",   debug_cmd))
    tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    tg.add_handler(CallbackQueryHandler(button_handler))

    # Webhook routes for Node server → Bot
    webapp = web.Application()
    webapp["tg_app"] = tg
    webapp.router.add_post("/notify-tx",  notify_tx)
    webapp.router.add_post("/broadcast",  broadcast_handler)
    webapp.router.add_post("/winner",     winner_handler)
    webapp.router.add_get ("/",           lambda r: web.json_response(
        {"ok": True, "service": "abisinya-bingo-bot"}))

    # Initialize Telegram
    await tg.initialize()
    await tg.start()

    # Start local HTTP server (Render needs a port bound)
    runner = web.AppRunner(webapp)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", BOT_PORT)
    await site.start()
    print(f"🌐 Webhook listening on port {BOT_PORT}")

    # Start polling
    await tg.updater.start_polling()
    print("🤖 Bot running — listening for Telegram updates…")

    # Run forever
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("👋 Bot stopped")