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
    keyboard = [
        [KeyboardButton("🎲 Abisinya Bingo ይጫወቱ", web_app=WebAppInfo(url=game_url(uid, name)))],
        [KeyboardButton("💵 ገንዘብ ያስገቡ"), KeyboardButton("📤 ገንዘብ ያውጡ")],
        [KeyboardButton("💰 Check Balance"), KeyboardButton("👥 ጓደኛ ይጋብዙ")],
        [KeyboardButton("📜 ታሪክ"), KeyboardButton("💬 ድጋፍ")],
        [KeyboardButton("🌐 ቋንቋ"), KeyboardButton("❓ እርዳታ")],
        [KeyboardButton("☰ Menu"), KeyboardButton("🏆 ደረጃ ሰልፍ")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)

def menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("/withdraw", callback_data="cmd_withdraw"), InlineKeyboardButton("/howtoplay", callback_data="cmd_howtoplay")],
        [InlineKeyboardButton("/invite", callback_data="cmd_invite"), InlineKeyboardButton("/support", callback_data="cmd_support")],
        [InlineKeyboardButton("/balance", callback_data="cmd_balance"), InlineKeyboardButton("/deposit", callback_data="cmd_deposit")],
        [InlineKeyboardButton("❌ Close Menu", callback_data="close_menu")]
    ])

def contact_kb():
    return ReplyKeyboardMarkup([[KeyboardButton("📱 Share My Contact", request_contact=True)]], resize_keyboard=True, one_time_keyboard=True)

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

# ================================================================
#                        USER STATE
# ================================================================
user_states = {}

# ================================================================
#                        COMMANDS
# ================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    sv_upsert(u.id, u.username or "", u.first_name or "")
    await update.message.reply_text(
        f"👋 *ሰላም {u.first_name}!*\n\n🎉 እንኳን ወደ *Abisinya Bingo* በደህና መጡ።",
        parse_mode="Markdown", reply_markup=main_kb(u.id, u.first_name)
    )

async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 **Menu Options**\n\n"
        "• /register - ቁጥርዎን ይመዝግቡ\n"
        "• /play - ቢንጎ ይጫወቱ\n"
        "• /balance - ቀሪ ሂሳብ\n"
        "• /deposit - ገንዘብ ያስገቡ\n"
        "• /withdraw - ገንዘብ ያውጡ\n"
        "• /howtoplay - ደንቦች\n"
        "• /invite - ጋብዝ\n"
        "• /support - ድጋፍ\n"
        "• /language - ቋንቋ",
        parse_mode="Markdown", reply_markup=menu_kb()
    )

async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    usr = sv_user(u.id) or {}
    await update.message.reply_text(
        f"💼 *የእርስዎ ዋሌት*\n\n🎯 Playable:  *{usr.get('balance',0):.2f} ብር*\n🏆 Winnings:  *{usr.get('winBalance',0):.2f} ብር*",
        parse_mode="Markdown"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ℹ️ *እርዳታ*\n\n1. Play ይጫኑ\n2. ካርቴላ ይምረጡ\n3. BINGO ሲሆን ይጫኑ", parse_mode="Markdown")

# ================================================================
#                        MESSAGE HANDLER
# ================================================================
async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.contact:
        u = update.effective_user
        phone = update.message.contact.phone_number
        sv_upsert(u.id, u.username or "", u.first_name or "", phone=phone)
        await update.message.reply_text(f"✅ *ተመዝግቧል!*\n\n📱 `{phone}`", parse_mode="Markdown", reply_markup=main_kb(u.id, u.first_name))
        return

    if not update.message or not update.message.text: return
    u = update.effective_user
    txt = update.message.text.strip()
    sv_upsert(u.id, u.username or "", u.first_name or "")
    state = user_states.get(u.id, {})
    action = state.get("action")

    if txt == "☰ Menu": return await menu_cmd(update, context)
    if any(x in txt for x in ["🎲", "💵", "📤", "💰", "👥", "📜", "💬", "🌐", "❓", "🏆"]): user_states.pop(u.id, None); action = None

    if action == "register":
        sv_upsert(u.id, u.username or "", u.first_name or "", phone=txt.strip())
        user_states.pop(u.id, None)
        await update.message.reply_text(f"✅ *ተመዝግቧል!*", parse_mode="Markdown", reply_markup=main_kb(u.id, u.first_name))
        return

    if action == "deposit":
        m = re.search(r"(\d+(?:[.,]\d+)?)", txt); amount = float(m.group(1).replace(",", "")) if m else 0
        if amount < 1: return await update.message.reply_text("⚠️ ትክክለኛ መጠን ያስገቡ")
        tx = sv_tx({"userId": u.id, "type": "deposit", "amount": amount, "method": state.get("method"), "sms": txt, "status": "pending"})
        if not tx: return await update.message.reply_text("⚠️ ኔትወርክ ችግር።")
        await context.bot.send_message(ADMIN_ID, f"🔔 *DEPOSIT*\n👤 {u.first_name}\n💰 {amount:.2f} ETB\n🔖 Tx: `{tx['_id']}`", parse_mode="Markdown", reply_markup=approval_kb(tx['_id']))
        user_states.pop(u.id, None)
        await update.message.reply_text("✅ *ጥያቄዎ ተልኳል!*", parse_mode="Markdown", reply_markup=main_kb(u.id, u.first_name))
        return

    if action == "withdraw_amount":
        if not txt.isdigit(): return await update.message.reply_text("⚠️ ቁጥር ብቻ")
        amount = float(txt)
        if amount < 100: return await update.message.reply_text("⚠️ ዝቅተኛው 100 ብር")
        usr = sv_user(u.id) or {}
        if amount > (usr.get("balance",0) + usr.get("winBalance",0)): return await update.message.reply_text("❌ ቀሪ ሂሳብ አይበቃም!")
        user_states[u.id] = {"action": "withdraw_phone", "amount": amount, "method": state.get("method")}
        await update.message.reply_text("📱 የስልክ ቁጥርዎን ያስገቡ:")
        return

    if action == "withdraw_phone":
        tx = sv_tx({"userId": u.id, "type": "withdraw", "amount": state.get("amount"), "method": state.get("method"), "phone": txt.strip(), "status": "pending"})
        if not tx: return await update.message.reply_text("⚠️ ኔትወርክ ችግር።")
        await context.bot.send_message(ADMIN_ID, f"🔔 *WITHDRAW*\n👤 {u.first_name}\n💰 {state.get('amount'):.2f} ETB\n📱 `{txt.strip()}`\n🔖 Tx: `{tx['_id']}`", parse_mode="Markdown", reply_markup=approval_kb(tx['_id']))
        user_states.pop(u.id, None)
        await update.message.reply_text("✅ *የወጭ ጥያቄዎ ተልኳል!*", parse_mode="Markdown", reply_markup=main_kb(u.id, u.first_name))
        return

    # Text handlers for keyboard
    if "💵" in txt: await update.message.reply_text("💰 የክፍያ አማራጭ ይምረጡ:", reply_markup=deposit_kb())
    elif "📤" in txt: await update.message.reply_text("📤 የወጭ አማራጭ ይምረጡ:", reply_markup=withdraw_kb())
    elif "💰" in txt: await balance_cmd(update, context)
    elif "👥" in txt: await update.message.reply_text(f"👥 *የግብዣ ሊንክ*\n\n`https://t.me/{BOT_USERNAME}?start={u.id}`", parse_mode="Markdown")
    elif "📜" in txt: await update.message.reply_text("📜 ሙሉ ታሪክዎን ለማየት 👤 Profile ን ይጫኑ።")
    elif "💬" in txt: await update.message.reply_text("💬 *ድጋፍ*\n\n👤 @Tazikes", parse_mode="Markdown")
    elif "🌐" in txt: await update.message.reply_text("🌐 ቋንቋ ይምረጡ:")
    elif "❓" in txt: await help_cmd(update, context)
    elif "🏆" in txt: await update.message.reply_text("🏆 Leaderboard\n\n1. Player1\n2. Player2")
    else: await update.message.reply_text("ጥያቄዎን አልተረዳሁም። ☰ Menu ን ይጫኑ።", reply_markup=main_kb(u.id, u.first_name))

# ================================================================
#                        BUTTON HANDLER
# ================================================================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    u = q.from_user

    if data == "close_menu": return await q.edit_message_text("Menu closed.")
    if data == "cmd_withdraw": return await q.edit_message_text("📤 የወጭ አማራጭ ይምረጡ:", reply_markup=withdraw_kb())
    if data == "cmd_deposit": return await q.edit_message_text("💰 የክፍያ አማራጭ ይምረጡ:", reply_markup=deposit_kb())
    if data == "cmd_balance":
        usr = sv_user(u.id) or {}
        return await q.edit_message_text(f"💼 *ዋሌት*\n🎯 Playable: *{usr.get('balance',0):.2f} ብር*", parse_mode="Markdown")
    if data == "cmd_howtoplay": return await q.edit_message_text("🎯 1. Play\n2. ካርቴላ ይምረጡ\n3. BINGO")
    if data == "cmd_invite": return await q.edit_message_text(f"👥 *የግብዣ ሊንክ*\n\n`https://t.me/{BOT_USERNAME}?start={u.id}`", parse_mode="Markdown")
    if data == "cmd_support": return await q.edit_message_text("💬 *ድጋፍ*\n\n👤 @Tazikes", parse_mode="Markdown")

    if data == "dep_telebirr": user_states[u.id] = {"action": "deposit", "method": "telebirr"}; await q.edit_message_text("🏦 *Telebirr*\n\n📩 SMS ይለጥፉ:", parse_mode="Markdown")
    elif data == "dep_cbe": user_states[u.id] = {"action": "deposit", "method": "cbe"}; await q.edit_message_text("🏦 *CBE*\n\n📩 SMS ይለጥፉ:", parse_mode="Markdown")
    elif data == "wd_telebirr": user_states[u.id] = {"action": "withdraw_amount", "method": "telebirr"}; await q.edit_message_text("🏦 *Telebirr*\n\nየወጭ መጠን (min 100):", parse_mode="Markdown")
    elif data == "wd_cbe": user_states[u.id] = {"action": "withdraw_amount", "method": "cbe"}; await q.edit_message_text("🏦 *CBE*\n\nየወጭ መጠን (min 100):", parse_mode="Markdown")

    if data.startswith("approve_") or data.startswith("reject_"):
        if u.id != ADMIN_ID: return
        action, tx_id = data.split("_", 1); tx = sv_get_tx(tx_id)
        if not tx: return await q.edit_message_text("❌ Not found")
        status = "approved" if action == "approve" else "rejected"
        sv_set_tx_status(tx_id, status)
        if status == "approved":
            if tx["type"] == "deposit": sv_adj(tx["userId"], "balance", tx["amount"])
            elif tx["type"] == "withdraw": sv_adj(tx["userId"], "winBalance", -tx["amount"])
            try: await context.bot.send_message(tx["userId"], f"✅ ጥያቄዎ ፀድቋል! {tx['amount']:.2f} ETB")
            except: pass
        else:
            try: await context.bot.send_message(tx["userId"], f"❌ ጥያቄዎ ተሰርዟል")
            except: pass
        await q.edit_message_text(f"✅ Done" if status == "approved" else f"❌ Rejected")

# ================================================================
#                        WEBHOOKS & MAIN
# ================================================================
async def notify_tx(request):
    if request.headers.get("x-bot-secret") != BOT_API_SECRET: return web.json_response({"ok": False}, status=403)
    d = await request.json(); tg = request.app["tg_app"]
    try: await tg.bot.send_message(d["telegramId"], f"{'✅' if d['status']=='approved' else '❌'} {d['type']} {d['amount']} ETB")
    except: pass
    return web.json_response({"ok": True})

async def winner_handler(request):
    if request.headers.get("x-bot-secret") != BOT_API_SECRET: return web.json_response({"ok": False}, status=403)
    d = await request.json(); tg = request.app["tg_app"]
    try: await tg.bot.send_message(d["userId"], f"🏆 *እንኳን ደስ አለዎት!*\n💰 *{d['prize']:.2f} ETB*\n🎫 ካርቴላ #{d['cartelaId']}", parse_mode="Markdown")
    except: pass
    return web.json_response({"ok": True})

async def main():
    tg = ApplicationBuilder().token(TOKEN).build()
    tg.add_handler(CommandHandler("start", start))
    tg.add_handler(CommandHandler("menu", menu_cmd))
    tg.add_handler(CommandHandler("balance", balance_cmd))
    tg.add_handler(CommandHandler("help", help_cmd))
    tg.add_handler(CommandHandler("register", lambda u,c: u.message.reply_text("📱 Share:", reply_markup=contact_kb())))
    tg.add_handler(MessageHandler(filters.CONTACT, handle_msg))
    tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    tg.add_handler(CallbackQueryHandler(button_handler))

    webapp = web.Application()
    webapp["tg_app"] = tg
    webapp.router.add_post("/notify-tx", notify_tx)
    webapp.router.add_post("/winner", winner_handler)
    webapp.router.add_get("/", lambda r: web.json_response({"ok": True}))

    await tg.initialize(); await tg.start()
    runner = web.AppRunner(webapp); await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", BOT_PORT); await site.start()
    print("🤖 Bot running")
    await asyncio.Event().wait()

if __name__ == "__main__":
    try: asyncio.run(main())
    except (KeyboardInterrupt, SystemExit): pass