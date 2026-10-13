import os
import re
import requests
from datetime import datetime
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
WEBAPP_URL = os.getenv("WEBAPP_URL")           # node service URL
SERVER_URL = os.getenv("SERVER_URL")           # same as above
BOT_API_SECRET = os.getenv("BOT_API_SECRET", "change-me")
BOT_PORT = int(os.getenv("BOT_PORT", "8080"))
BOT_USERNAME = os.getenv("BOT_USERNAME", "AbisinyaBingo_Bot")

H = {"x-bot-secret": BOT_API_SECRET, "Content-Type": "application/json"}

# ---- Server helpers ----
def sv_user(uid):   return requests.get(f"{SERVER_URL}/api/bot/user/{uid}", headers=H).json().get("user")
def sv_upsert(uid, uname, fname, phone=None):
    return requests.post(f"{SERVER_URL}/api/bot/user", headers=H,
        json={"telegramId": uid, "username": uname, "firstName": fname, "phone": phone}).json()
def sv_adj(uid, field, delta):
    return requests.post(f"{SERVER_URL}/api/bot/user/{uid}/adjust", headers=H,
        json={"field": field, "delta": delta}).json()
def sv_tx(data):
    return requests.post(f"{SERVER_URL}/api/bot/transaction", headers=H, json=data).json()
def sv_upsert_tx(tx_id, status):
    return requests.post(f"{SERVER_URL}/api/bot/transaction/{tx_id}/status", headers=H,
        json={"status": status}).json()
def sv_get_tx(tx_id):
    return requests.get(f"{SERVER_URL}/api/bot/transaction/{tx_id}", headers=H).json().get("tx")

# ---- Text dict (shortened - keep your existing TEXTS) ----
TEXTS = { "am": { ... }, "en": { ... } }   # copy from previous bot.py

# ---- Menu ----
def game_url(uid, name):
    return f"{WEBAPP_URL}/bingo.html?uid={uid}&name={name}&game=game1"

def main_kb(uid, name):
    keyboard = [
        [KeyboardButton("🎯 Play Bingo", web_app=WebAppInfo(url=game_url(uid, name)))],
        [KeyboardButton("💰 Deposit"), KeyboardButton("📤 Withdraw")],
        [KeyboardButton("💵 Balance"),   KeyboardButton("👥 Invite")],
        [KeyboardButton("📋 History"),   KeyboardButton("💬 Support")],
        [KeyboardButton("📱 Register"),  KeyboardButton("🌍 Language")],
        [KeyboardButton("ℹ️ Help"),      KeyboardButton("🏆 Leaderboard")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)

# ---- Commands ----
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    sv_upsert(u.id, u.username or "", u.first_name or "")
    if context.args and context.args[0].isdigit():
        ref = int(context.args[0])
        if ref != u.id:
            sv_adj(ref, "balance", 30)
            try: await context.bot.send_message(ref, "🎉 New referral! +30 ETB")
            except: pass
    await update.message.reply_text("🎉 Welcome to Abisinya Bingo!", reply_markup=main_kb(u.id, u.first_name or "Player"))

async def balance_cmd(update, context):
    u = update.effective_user
    usr = sv_user(u.id) or {}
    await update.message.reply_text(
        f"💰 Balance: {usr.get('balance',0):.2f} ETB\n🏆 Win: {usr.get('winBalance',0):.2f} ETB")

# ---- Deposit / Withdraw flows ----
user_states = {}

async def handle_msg(update, context):
    u = update.effective_user
    txt = update.message.text.strip()
    sv_upsert(u.id, u.username or "", u.first_name or "")
    st = user_states.get(u.id, {})
    action = st.get("action")

    # reset on menu button
    if any(x in txt for x in ["🎯","💰","📤","💵","👥","📋","💬","📱","🌍","ℹ️","🏆"]):
        user_states.pop(u.id, None); action = None

    if action == "register":
        sv_upsert(u.id, u.username or "", u.first_name or "", txt)
        user_states.pop(u.id, None)
        await update.message.reply_text(f"✅ Registered: {txt}", reply_markup=main_kb(u.id, u.first_name or "Player"))
        return

    if action == "deposit":
        m = re.search(r"(\d+(?:[.,]\d+)?)", txt)
        amount = float(m.group(1).replace(",", "")) if m else 0
        if amount < 1: return await update.message.reply_text("⚠️ Invalid amount")
        r = sv_tx({"userId": u.id, "type": "deposit", "amount": amount,
                   "method": st.get("method"), "sms": txt, "status": "pending"})
        tx_id = r["tx"]["_id"]
        await context.bot.send_message(ADMIN_ID,
            f"🔔 DEPOSIT\n👤 {u.first_name} (@{u.username})\n🆔 {u.id}\n💰 {amount} ETB — {st.get('method')}\n🔖 {tx_id}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_{tx_id}"),
                InlineKeyboardButton("❌ Reject",  callback_data=f"reject_{tx_id}")]]))
        user_states.pop(u.id, None)
        await update.message.reply_text("✅ Sent to admin for approval.", reply_markup=main_kb(u.id, u.first_name or "Player"))
        return

    if action == "withdraw_amount":
        if not txt.isdigit(): return await update.message.reply_text("⚠️ Enter a number")
        amt = float(txt)
        usr = sv_user(u.id) or {}
        if amt < 100: return await update.message.reply_text("⚠️ Min 100 ETB")
        if amt > (usr.get("balance",0)+usr.get("winBalance",0)):
            return await update.message.reply_text("❌ Insufficient")
        user_states[u.id] = {"action":"withdraw_phone","amount":amt,"method":st.get("method")}
        await update.message.reply_text("📱 Send phone number:")
        return

    if action == "withdraw_phone":
        phone = txt.strip(); amt = st["amount"]
        r = sv_tx({"userId": u.id, "type": "withdraw", "amount": amt,
                   "method": st.get("method"), "phone": phone, "status": "pending"})
        tx_id = r["tx"]["_id"]
        await context.bot.send_message(ADMIN_ID,
            f"🔔 WITHDRAW\n👤 {u.first_name} (@{u.username})\n🆔 {u.id}\n💰 {amt} ETB — {st.get('method')}\n📱 {phone}\n🔖 {tx_id}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_{tx_id}"),
                InlineKeyboardButton("❌ Reject",  callback_data=f"reject_{tx_id}")]]))
        user_states.pop(u.id, None)
        await update.message.reply_text("✅ Withdrawal request sent.", reply_markup=main_kb(u.id, u.first_name or "Player"))
        return

    # simple menu handlers
    if "💰" in txt:
        await update.message.reply_text("Choose deposit method:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📲 Telebirr", callback_data="dep_telebirr")],
                                               [InlineKeyboardButton("🏦 CBE", callback_data="dep_cbe")]]))
    elif "📤" in txt:
        await update.message.reply_text("Choose withdraw method:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📲 Telebirr", callback_data="wd_telebirr")],
                                               [InlineKeyboardButton("🏦 CBE", callback_data="wd_cbe")]]))
    elif "💵" in txt:
        await balance_cmd(update, context)
    elif "📱" in txt:
        user_states[u.id] = {"action":"register"}
        await update.message.reply_text("📱 Send your phone number:")
    elif "👥" in txt:
        await update.message.reply_text(f"Invite link:\nhttps://t.me/{BOT_USERNAME}?start={u.id}")
    elif "ℹ️" in txt:
        await update.message.reply_text("Play 🎯, choose 1-4 cartelas, click BINGO on 4 corners!")

# ---- Callback: admin approve/reject + deposit/withdraw methods ----
async def button_handler(update, context):
    q = update.callback_query; await q.answer()
    data = q.data; u = q.from_user

    if data.startswith("approve_") or data.startswith("reject_"):
        if u.id != ADMIN_ID: return
        action, tx_id = data.split("_", 1)
        tx = sv_get_tx(tx_id)
        if not tx: return await q.edit_message_text("❌ Not found")
        status = "approved" if action == "approve" else "rejected"
        sv_upsert_tx(tx_id, status)
        # Apply balance changes
        if status == "approved":
            if tx["type"] == "deposit":
                sv_adj(tx["userId"], "balance", tx["amount"])
                try: await context.bot.send_message(tx["userId"], f"✅ Deposit approved: +{tx['amount']} ETB")
                except: pass
            else:
                sv_adj(tx["userId"], "winBalance", -tx["amount"])
                try: await context.bot.send_message(tx["userId"], f"✅ Withdrawal approved: {tx['amount']} ETB")
                except: pass
        else:
            try: await context.bot.send_message(tx["userId"], f"❌ Your {tx['type']} was rejected.")
            except: pass
        await q.edit_message_text(f"{'✅' if status=='approved' else '❌'} {tx['type'].upper()} {tx['amount']} ETB")
        return

    if data == "dep_telebirr":
        user_states[u.id] = {"action":"deposit","method":"telebirr"}
        await q.edit_message_text("🏦 Telebirr: tazebew — 0968940123\nPaste your SMS:")
    elif data == "dep_cbe":
        user_states[u.id] = {"action":"deposit","method":"cbe"}
        await q.edit_message_text("🏦 CBE: tazebew — 1000390803005\nPaste your SMS:")
    elif data == "wd_telebirr":
        user_states[u.id] = {"action":"withdraw_amount","method":"telebirr"}
        await q.edit_message_text("Amount to withdraw (min 100):")
    elif data == "wd_cbe":
        user_states[u.id] = {"action":"withdraw_amount","method":"cbe"}
        await q.edit_message_text("Amount to withdraw (min 100):")

# ---- Local HTTP listener for callbacks from Node.js ----
async def notify_tx(request):
    if request.headers.get("x-bot-secret") != BOT_API_SECRET: return web.json_response({"ok":False}, status=403)
    d = await request.json()
    app = request.app["tg_app"]
    try:
        await app.bot.send_message(d["telegramId"],
            f"{'✅' if d['status']=='approved' else '❌'} {d['type']} {d['amount']} ETB — {d['status']}")
    except Exception: pass
    return web.json_response({"ok":True})

async def broadcast_handler(request):
    if request.headers.get("x-bot-secret") != BOT_API_SECRET: return web.json_response({"ok":False}, status=403)
    d = await request.json()
    app = request.app["tg_app"]
    # you'd need a list of users; keep a users table or query server
    usrs = requests.get(f"{SERVER_URL}/api/bot/all-users", headers=H).json().get("users", [])
    for usr in usrs:
        try: await app.bot.send_message(usr["telegramId"], f"📢 {d['message']}")
        except: pass
    return web.json_response({"ok":True})

async def winner_handler(request):
    if request.headers.get("x-bot-secret") != BOT_API_SECRET: return web.json_response({"ok":False}, status=403)
    d = await request.json(); app = request.app["tg_app"]
    try:
        await app.bot.send_message(d["userId"],
            f"🏆 You won {d['prize']} ETB on cartela {d['cartelaId']}!")
    except: pass
    return web.json_response({"ok":True})

# ---- Main ----
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
    webapp.router.add_post("/winner", winner_handler)

    await tg.initialize()
    await tg.start()
    runner = web.AppRunner(webapp); await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", BOT_PORT); await site.start()
    print(f"🤖 Bot running, webhook on {BOT_PORT}")
    await tg.updater.start_polling()
    # wait forever
    import asyncio; await asyncio.Event().wait()

if __name__ == "__main__":
    import asyncio; asyncio.run(main())