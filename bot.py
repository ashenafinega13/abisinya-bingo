from dotenv import load_dotenv
load_dotenv()
import os
import re
import asyncio
import requests
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler


# ================================================================
# SECRETS — read from Render environment variables
# ================================================================
TOKEN             = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID          = int(os.getenv("ADMIN_ID", "0"))
SERVER_URL        = os.getenv("SERVER_URL")           # e.g. https://abisinya-bingo-server.onrender.com
WEBAPP_URL        = os.getenv("WEBAPP_URL")           # same as SERVER_URL (or your custom domain)
BOT_API_SECRET    = os.getenv("BOT_API_SECRET", "change-me")
BOT_PORT          = int(os.getenv("BOT_PORT", "8080"))
BOT_USERNAME      = os.getenv("BOT_USERNAME", "AbisinyaBingo_Bot")

H = {"x-bot-secret": BOT_API_SECRET, "Content-Type": "application/json"}

# ================================================================
# TALK TO THE NODE SERVER
# ================================================================
def sv_upsert(uid, uname, fname, phone=None):
    try:
        r = requests.post(f"{SERVER_URL}/api/bot/user", headers=H, timeout=10,
            json={"telegramId": uid, "username": uname, "firstName": fname, "phone": phone})
        return r.json().get("user")
    except Exception as e:
        print("sv_upsert error:", e); return None

def sv_user(uid):
    try:
        r = requests.get(f"{SERVER_URL}/api/bot/user/{uid}", headers=H, timeout=10)
        return r.json().get("user")
    except Exception as e:
        print("sv_user error:", e); return None

def sv_adj(uid, field, delta):
    try:
        r = requests.post(f"{SERVER_URL}/api/bot/user/{uid}/adjust", headers=H, timeout=10,
            json={"field": field, "delta": delta})
        return r.json().get("user")
    except Exception as e:
        print("sv_adj error:", e); return None

def sv_tx(data):
    try:
        r = requests.post(f"{SERVER_URL}/api/bot/transaction", headers=H, timeout=10, json=data)
        return r.json().get("tx")
    except Exception as e:
        print("sv_tx error:", e); return None

def sv_get_tx(tx_id):
    try:
        r = requests.get(f"{SERVER_URL}/api/bot/transaction/{tx_id}", headers=H, timeout=10)
        return r.json().get("tx")
    except Exception as e:
        print("sv_get_tx error:", e); return None

def sv_set_tx_status(tx_id, status):
    try:
        requests.post(f"{SERVER_URL}/api/bot/transaction/{tx_id}/status", headers=H, timeout=10,
            json={"status": status})
    except Exception as e:
        print("sv_set_tx_status error:", e)

# ================================================================
# GAME URL — players go STRAIGHT to the picker
# ================================================================
def game_url(uid, name):
    return f"{WEBAPP_URL}/game?uid={uid}&name={name}"

# ================================================================
# KEYBOARD
# ================================================================
def main_kb(uid, name):
    keyboard = [
        [KeyboardButton("🎯 Play Abisinya Bingo", web_app=WebAppInfo(url=game_url(uid, name)))],
        [KeyboardButton("💰 Deposit"), KeyboardButton("📤 Withdraw")],
        [KeyboardButton("💵 Check Balance"), KeyboardButton("👥 Invite Friends")],
        [KeyboardButton("📋 History"), KeyboardButton("💬 Support")],
        [KeyboardButton("📱 Register"), KeyboardButton("🌍 Language")],
        [KeyboardButton("ℹ️ Help"), KeyboardButton("🏆 Leaderboard")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)

# ================================================================
# USER STATES (what they're typing next)
# ================================================================
user_states = {}

# ================================================================
# /start
# ================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    sv_upsert(u.id, u.username or "", u.first_name or "")
    if context.args and context.args[0].isdigit():
        ref = int(context.args[0])
        if ref != u.id:
            sv_adj(ref, "balance", 30)
            try: await context.bot.send_message(ref, "🎉 አዲስ ጓደኛ ጋበዝክ! +30 ብር")
            except: pass
    await update.message.reply_text(
        "🎉 እንኳን ወደ Abisinya Bingo በደህና መጡ!\n\n🎯 Play ን ተጭነው ይጫወቱ።",
        reply_markup=main_kb(u.id, u.first_name or "Player")
    )

# ================================================================
# /balance
# ================================================================
async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    usr = sv_user(u.id) or {}
    await update.message.reply_text(
        f"💰 ቀሪ ሂሳብ: {usr.get('balance',0):.2f} ብር\n"
        f"🏆 የድል ሂሳብ: {usr.get('winBalance',0):.2f} ብር"
    )

# ================================================================
# MAIN MESSAGE HANDLER
# ================================================================
async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    u = update.effective_user
    txt = update.message.text.strip()
    sv_upsert(u.id, u.username or "", u.first_name or "")

    st = user_states.get(u.id, {})
    action = st.get("action")

    # if user pressed a menu button, cancel any pending action
    if any(x in txt for x in ["🎯","💰","📤","💵","👥","📋","💬","📱","🌍","ℹ️","🏆"]):
        user_states.pop(u.id, None)
        action = None

    # ---------- REGISTER ----------
    if action == "register":
        phone = txt.strip()
        sv_upsert(u.id, u.username or "", u.first_name or "", phone=phone)
        user_states.pop(u.id, None)
        await update.message.reply_text(f"✅ ተመዝግቧል: {phone}",
            reply_markup=main_kb(u.id, u.first_name or "Player"))
        return

    # ---------- DEPOSIT ----------
    if action == "deposit":
        m = re.search(r"(\d+(?:[.,]\d+)?)", txt)
        amount = float(m.group(1).replace(",", "")) if m else 0
        if amount < 1:
            await update.message.reply_text("⚠️ ትክክለኛ መጠን ያስገቡ")
            return
        tx = sv_tx({"userId": u.id, "type": "deposit", "amount": amount,
                    "method": st.get("method"), "sms": txt, "status": "pending"})
        tx_id = tx["_id"]
        method_label = "📲 TeleBirr" if st.get("method") == "telebirr" else "🏦 CBE"
        await context.bot.send_message(ADMIN_ID,
            f"🔔 አዲስ DEPOSIT\n👤 {u.first_name} (@{u.username or 'N/A'})\n"
            f"🆔 {u.id}\n💰 {amount} ETB — {method_label}\n🔖 Tx: {tx_id}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_{tx_id}"),
                InlineKeyboardButton("❌ Reject",  callback_data=f"reject_{tx_id}")
            ]]))
        user_states.pop(u.id, None)
        await update.message.reply_text("✅ ለአስተዳዳሪ ተልኳል።",
            reply_markup=main_kb(u.id, u.first_name or "Player"))
        return

    # ---------- WITHDRAW AMOUNT ----------
    if action == "withdraw_amount":
        if not txt.isdigit():
            await update.message.reply_text("⚠️ ቁጥር ብቻ ያስገቡ")
            return
        amt = float(txt)
        if amt < 100:
            await update.message.reply_text("⚠️ ዝቅተኛው 100 ETB ነው")
            return
        usr = sv_user(u.id) or {}
        total = (usr.get("balance") or 0) + (usr.get("winBalance") or 0)
        if amt > total:
            await update.message.reply_text(f"❌ ቀሪ ሂሳብ አይበቃም (ያለዎት: {total:.2f})")
            return
        user_states[u.id] = {"action": "withdraw_phone", "amount": amt,
                             "method": st.get("method")}
        await update.message.reply_text("📱 የስልክ ቁጥርዎን ያስገቡ:")
        return

    # ---------- WITHDRAW PHONE ----------
    if action == "withdraw_phone":
        phone = txt.strip()
        amt = st["amount"]
        tx = sv_tx({"userId": u.id, "type": "withdraw", "amount": amt,
                    "method": st.get("method"), "phone": phone, "status": "pending"})
        tx_id = tx["_id"]
        method_label = "📲 TeleBirr" if st.get("method") == "telebirr" else "🏦 CBE"
        await context.bot.send_message(ADMIN_ID,
            f"🔔 አዲስ WITHDRAW\n👤 {u.first_name} (@{u.username or 'N/A'})\n"
            f"🆔 {u.id}\n💰 {amt} ETB — {method_label}\n📱 {phone}\n🔖 Tx: {tx_id}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_{tx_id}"),
                InlineKeyboardButton("❌ Reject",  callback_data=f"reject_{tx_id}")
            ]]))
        user_states.pop(u.id, None)
        await update.message.reply_text("✅ የወጭ ጥያቄ ተልኳል።",
            reply_markup=main_kb(u.id, u.first_name or "Player"))
        return

    # ---------- MENU BUTTONS ----------
    if "🎯" in txt:
        await update.message.reply_text("🎯 Play ን ተጭነው ይጫወቱ!")
    elif "💰" in txt:
        await update.message.reply_text("የክፍያ አማራጭ ይምረጡ:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📲 Telebirr", callback_data="dep_telebirr")],
                [InlineKeyboardButton("🏦 CBE",      callback_data="dep_cbe")]
            ]))
    elif "📤" in txt:
        await update.message.reply_text("የወጭ አማራጭ ይምረጡ:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📲 Telebirr", callback_data="wd_telebirr")],
                [InlineKeyboardButton("🏦 CBE",      callback_data="wd_cbe")]
            ]))
    elif "💵" in txt:
        await balance_cmd(update, context)
    elif "👥" in txt:
        await update.message.reply_text(
            f"👥 የግብዣ ሊንክ:\nhttps://t.me/{BOT_USERNAME}?start={u.id}\n\n✨ 30 ብር ያግኙ!")
    elif "📋" in txt:
        await update.message.reply_text("📋 ታሪክ በቅርቡ ይመጣል።")
    elif "💬" in txt:
        await update.message.reply_text("💬 ድጋፍ: @Tazikes")
    elif "📱" in txt:
        user_states[u.id] = {"action": "register"}
        await update.message.reply_text("📱 የስልክ ቁጥርዎን ያስገቡ (ለምሳሌ 0912345678):")
    elif "🌍" in txt:
        await update.message.reply_text("🌐 Language: English | አማርኛ (በቅርቡ)")
    elif "ℹ️" in txt:
        await update.message.reply_text("ℹ️ እርዳታ:\n1. Play ይጫኑ\n2. 1-4 ካርቴላ ይምረጡ\n3. 4 ማዕዘኖች ሲሟሉ BINGO ይጫኑ")
    elif "🏆" in txt:
        await update.message.reply_text("🏆 Leaderboard በቅርቡ ይመጣል።")

# ================================================================
# CALLBACK BUTTONS (Approve / Reject / Deposit method / Withdraw method)
# ================================================================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q: return
    await q.answer()
    data = q.data
    u = q.from_user
    sv_upsert(u.id, u.username or "", u.first_name or "")

    # ---------- ADMIN APPROVE / REJECT ----------
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
                    await context.bot.send_message(tx["userId"],
                        f"✅ ጥያቄዎ ፀድቋል!\n💰 {tx['amount']} ETB ተጨምሯል።")
                except: pass
            elif tx["type"] == "withdraw":
                sv_adj(tx["userId"], "winBalance", -tx["amount"])
                try:
                    await context.bot.send_message(tx["userId"],
                        f"✅ የወጭ ጥያቄዎ ፀድቋል!\n💰 {tx['amount']} ETB")
                except: pass
        else:
            try:
                await context.bot.send_message(tx["userId"],
                    f"❌ ጥያቄዎ ተሰርዟል: {tx['amount']} ETB")
            except: pass

        await q.edit_message_text(
            f"{'✅' if status=='approved' else '❌'} {tx['type'].upper()} — {tx['amount']} ETB")
        return

    # ---------- DEPOSIT METHOD ----------
    if data == "dep_telebirr":
        user_states[u.id] = {"action": "deposit", "method": "telebirr"}
        await q.edit_message_text(
            "🏦 Telebirr\n👤 tazebew\n👉 0968940123\n\n📩 የSMS ይለጥፉ:")
    elif data == "dep_cbe":
        user_states[u.id] = {"action": "deposit", "method": "cbe"}
        await q.edit_message_text(
            "🏦 CBE\n👤 tazebew\n👉 1000390803005\n\n📩 የSMS ይለጥፉ:")

    # ---------- WITHDRAW METHOD ----------
    elif data == "wd_telebirr":
        user_states[u.id] = {"action": "withdraw_amount", "method": "telebirr"}
        await q.edit_message_text("🏦 Telebirr\n\n💰 የወጭ መጠን (min 100 ETB):")
    elif data == "wd_cbe":
        user_states[u.id] = {"action": "withdraw_amount", "method": "cbe"}
        await q.edit_message_text("🏦 CBE\n\n💰 የወጭ መጠን (min 100 ETB):")

# ================================================================
# WEBHOOKS — the Node server calls these
# ================================================================
async def notify_tx(request):
    if request.headers.get("x-bot-secret") != BOT_API_SECRET:
        return web.json_response({"ok": False}, status=403)
    d = await request.json()
    tg = request.app["tg_app"]
    try:
        await tg.bot.send_message(d["telegramId"],
            f"{'✅' if d['status']=='approved' else '❌'} {d['type']} {d['amount']} ETB — {d['status']}")
    except: pass
    return web.json_response({"ok": True})

async def broadcast_handler(request):
    if request.headers.get("x-bot-secret") != BOT_API_SECRET:
        return web.json_response({"ok": False}, status=403)
    d = await request.json()
    tg = request.app["tg_app"]
    try:
        r = requests.get(f"{SERVER_URL}/api/bot/all-users", headers=H, timeout=10)
        users = r.json().get("users", [])
        for usr in users:
            try: await tg.bot.send_message(usr["telegramId"], f"📢 {d['message']}")
            except: pass
    except Exception as e:
        print("broadcast err:", e)
    return web.json_response({"ok": True})

async def winner_handler(request):
    if request.headers.get("x-bot-secret") != BOT_API_SECRET:
        return web.json_response({"ok": False}, status=403)
    d = await request.json()
    tg = request.app["tg_app"]
    try:
        await tg.bot.send_message(d["userId"],
            f"🏆 እንኳን ደስ አለዎት!\n\n💰 {d['prize']} ETB\n🎫 ካርቴላ #{d['cartelaId']}")
    except: pass
    return web.json_response({"ok": True})

# ================================================================
# MAIN
# ================================================================
async def main():
    tg = ApplicationBuilder().token(TOKEN).build()
    tg.add_handler(CommandHandler("start", start))
    tg.add_handler(CommandHandler("balance", balance_cmd))
    tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    tg.add_handler(CallbackQueryHandler(button_handler))

    webapp = web.Application()
    webapp["tg_app"] = tg
    webapp.router.add_post("/notify-tx", notify_tx)
    webapp.router.add_post("/broadcast", broadcast_handler)
    webapp.router.add_post("/winner",    winner_handler)

    await tg.initialize()
    await tg.start()
    runner = web.AppRunner(webapp)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", BOT_PORT)
    await site.start()
    print(f"🤖 Bot running. Webhook on {BOT_PORT}")

    await tg.updater.start_polling()
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())