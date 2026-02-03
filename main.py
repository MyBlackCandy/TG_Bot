import os
import re
import psycopg2
import requests
import random
import asyncio
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- ⚙️ CONFIG ---
TOKEN = os.getenv('TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
MASTER_ADMIN = os.getenv('ADMIN_ID')
MY_USDT_ADDR = os.getenv('USDT_ADDRESS')
TRON_API_KEY = os.getenv('TRONGRID_API_KEY')

# --- 🗄️ DATABASE & ACCESS ---
def get_db_connection():
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode='require')

def init_db():
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS customers (user_id BIGINT PRIMARY KEY, expire_date TIMESTAMP)')
    cursor.execute('CREATE TABLE IF NOT EXISTS team_members (member_id BIGINT PRIMARY KEY, leader_id BIGINT, allowed_chat_id BIGINT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS history (id SERIAL PRIMARY KEY, chat_id BIGINT, amount INTEGER, user_name TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    cursor.execute('CREATE TABLE IF NOT EXISTS used_transactions (tx_id TEXT PRIMARY KEY, user_id BIGINT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS pending_payments (user_id BIGINT PRIMARY KEY, amount DECIMAL, expire_at TIMESTAMP)')
    conn.commit(); cursor.close(); conn.close()

def check_access(user_id, chat_id):
    if str(user_id) == str(MASTER_ADMIN): return True
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM customers WHERE user_id = %s AND expire_date > %s', (user_id, datetime.now()))
    is_cust = cursor.fetchone()
    if is_cust: 
        cursor.close(); conn.close(); return True
    cursor.execute('SELECT 1 FROM team_members WHERE member_id = %s AND allowed_chat_id = %s', (user_id, chat_id))
    res = cursor.fetchone(); cursor.close(); conn.close()
    return True if res else False

# --- 🔄 AUTO VERIFY TASK ---
async def auto_verify_task(context: ContextTypes.DEFAULT_TYPE):
    try:
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('SELECT user_id, amount FROM pending_payments WHERE expire_at > NOW()')
        pending = cursor.fetchall()
        if pending:
            url = f"https://api.trongrid.io/v1/accounts/{MY_USDT_ADDR}/transactions/trc20"
            headers = {"TRON-PRO-API-KEY": TRON_API_KEY} if TRON_API_KEY else {}
            data = requests.get(url, params={"limit": 20}, headers=headers).json()
            for uid, amt in pending:
                for tx in data.get('data', []):
                    if abs((int(tx['value'])/1000000) - float(amt)) < 0.0001:
                        tx_id = tx['transaction_id']
                        cursor.execute('SELECT 1 FROM used_transactions WHERE tx_id=%s', (tx_id,))
                        if not cursor.fetchone():
                            cursor.execute('INSERT INTO used_transactions VALUES (%s, %s)', (tx_id, uid))
                            cursor.execute('SELECT expire_date FROM customers WHERE user_id=%s', (uid,))
                            old = cursor.fetchone()
                            new_exp = (old[0] if old and old[0] > datetime.now() else datetime.now()) + timedelta(days=30)
                            cursor.execute('INSERT INTO customers VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET expire_date=EXCLUDED.expire_date', (uid, new_exp))
                            cursor.execute('DELETE FROM pending_payments WHERE user_id=%s', (uid,))
                            conn.commit()
                            await context.bot.send_message(chat_id=uid, text=f"✅ **支付成功 / Success!**\nExpiry: `{new_exp.strftime('%Y-%m-%d %H:%M')}`")
        cursor.close(); conn.close()
    except: pass

# --- 🤖 HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # บอทจะตอบโต้เฉพาะในแชทส่วนตัวเท่านั้นสำหรับคำสั่งนี้
    if update.effective_chat.type != 'private': return
    
    # สุ่มยอดทศนิยมเพื่อใช้ในการตรวจสอบยอดโอน (Auto-Verify)
    amt = 100 + (random.randint(1, 99) / 100)
    exp = datetime.now() + timedelta(minutes=15)
    
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('INSERT INTO pending_payments VALUES (%s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET amount=EXCLUDED.amount, expire_at=EXCLUDED.expire_at', (update.message.from_user.id, amt, exp))
    conn.commit(); cursor.close(); conn.close()
    
    msg = (
        f"🚀 **黑糖果机器人管理系统 | AK Bot System**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💳 **权限激活 (续费/开通):**\n"
        f"• **金额:** `{amt:.2f}` USDT (TRC-20)\n"
        f"• **地址:** `{MY_USDT_ADDR}`\n"
        f"• **有效期:** 15 分钟内转账自动激活\n\n"
        
        f"📖 **使用方法简述 (Quick Guide):**\n"
        f"1️⃣ **记账:** 直接发送 `+100` 或 `-50` 进行记录\n"
        f"2️⃣ **查询:** 输入 `/show` 查看当前群组账单\n"
        f"3️⃣ **授权:** 回复成员消息输入 `/add` 进行授权\n"
        f"4️⃣ **帮助:** 输入 `/help` 查看所有详细指令\n\n"
        
        f"🆔 **您的 ID:** `{update.message.from_user.id}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ *请务必按照精准金额转账，包含小数点，系统将自动秒入账。*"
    )
    
    await update.message.reply_text(msg, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "📖 **黑糖果机器人详细指南 | Manual**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📊 **1. 日常记账 (群组内)**\n"
        "• 记录收入: `+1000` | 支出: `-500` \n"
        "• 查看账单: `/show` | 撤销: `/undo` \n\n"
        "👑 **2. 成员管理 (回复使用)**\n"
        "• 授权: `/add` | 取消: `/remove` \n"
        "• 重置: `/reset` (清空全群记录)\n\n"
        "💳 **3. 权限与 ID**\n"
        "• 查询到期: `/check` \n"
        "• **查询 ID: `/id`** \n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🛠 **Admin:** `/setadmin [ID] [Days]`"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

async def get_my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    msg = (f"🆔 **Telegram ID 信息**\n━━━━━━━━━━━━━━━\n"
           f"👤 **用户/Name:** {user.first_name}\n"
           f"🔢 **User ID:** `{user.id}`\n")
    if chat.type != 'private':
        msg += f"🏰 **Chat ID:** `{chat.id}`\n"
    msg += "━━━━━━━━━━━━━━━\n💡 *Long press ID to copy*"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not check_access(update.message.from_user.id, chat_id): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT amount, user_name FROM history WHERE chat_id = %s ORDER BY timestamp ASC', (chat_id,))
    rows = cursor.fetchall(); cursor.close(); conn.close()
    if not rows: return await update.message.reply_text("📋 **无记录 / No Records**")
    total, count = sum(r[0] for r in rows), len(rows)
    if count > 6:
        display = rows[-5:]
        history_text = "...\n" + "\n".join([f"{count-4+i}. {('+' if r[0]>0 else '')}{r[0]} ({r[1]})" for i, r in enumerate(display)])
    else:
        history_text = "\n".join([f"{i+1}. {('+' if r[0]>0 else '')}{r[0]} ({r[1]})" for i, r in enumerate(rows)])
    await update.message.reply_text(f"📊 **账目汇总 / Summary**\n━━━━━━━━━━━━━━━\n{history_text}\n━━━━━━━━━━━━━━━\n💰 **总额: {total}**", parse_mode='Markdown')

async def handle_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    chat_id = update.effective_chat.id
    if not check_access(update.message.from_user.id, chat_id): return
    match = re.match(r'^([+-])(\d+)$', update.message.text.strip())
    if match:
        amt = int(match.group(2)) if match.group(1) == '+' else -int(match.group(2))
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO history (chat_id, amount, user_name) VALUES (%s, %s, %s)', (chat_id, amt, update.message.from_user.first_name))
        conn.commit(); cursor.close(); conn.close()
        await show_history(update, context)

async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if str(uid) == str(MASTER_ADMIN):
        return await update.message.reply_text("👑 **身份: 主管理员 (Lifetime Admin)**")
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT expire_date FROM customers WHERE user_id = %s', (uid,))
    res = cursor.fetchone(); cursor.close(); conn.close()
    if res and res[0] > datetime.now():
        await update.message.reply_text(f"✅ **状态: 正常 / Active**\n📅 **到期:** `{res[0].strftime('%Y-%m-%d %H:%M')}`")
    else: await update.message.reply_text("❌ **权限已过期 / Unauthorized**")

async def undo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not check_access(update.message.from_user.id, chat_id): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE id = (SELECT id FROM history WHERE chat_id = %s ORDER BY timestamp DESC LIMIT 1)', (chat_id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("↩️ **已撤销 / Undo Done**")
    await show_history(update, context)

async def reset_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update.message.from_user.id, update.effective_chat.id): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE chat_id = %s', (update.effective_chat.id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("🧹 **已清空 / Reset Done**")

async def add_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message: return
    if not check_access(update.message.from_user.id, update.effective_chat.id): return
    t = update.message.reply_to_message.from_user
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('INSERT INTO team_members VALUES (%s, %s, %s) ON CONFLICT (member_id) DO UPDATE SET allowed_chat_id=EXCLUDED.allowed_chat_id', (t.id, update.message.from_user.id, update.effective_chat.id))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text(f"✅ **授权成功:** {t.first_name}")

async def remove_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message: return
    if not check_access(update.message.from_user.id, update.effective_chat.id): return
    t = update.message.reply_to_message.from_user
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM team_members WHERE member_id = %s AND allowed_chat_id = %s', (t.id, update.effective_chat.id))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text(f"🚫 **已取消:** {t.first_name}")

async def set_admin_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.from_user.id) != str(MASTER_ADMIN): return
    try:
        uid, days = int(context.args[0]), int(context.args[1])
        new_exp = datetime.now() + timedelta(days=days)
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO customers VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET expire_date=EXCLUDED.expire_date', (uid, new_exp))
        conn.commit(); cursor.close(); conn.close()
        await update.message.reply_text(f"👑 **手动授权成功**\nID: `{uid}`\nExpiry: `{new_exp.strftime('%Y-%m-%d')}`")
    except: await update.message.reply_text("Format: `/setadmin [ID] [Days]`")

# --- 🚀 RUN BOT ---
if __name__ == '__main__':
    init_db()
    app = Application.builder().token(TOKEN).build()
    if app.job_queue:
        app.job_queue.run_repeating(auto_verify_task, interval=30, first=10)
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("check", check_status))
    app.add_handler(CommandHandler("id", get_my_id))
    app.add_handler(CommandHandler("show", show_history))
    app.add_handler(CommandHandler("add", add_member))
    app.add_handler(CommandHandler("remove", remove_member))
    app.add_handler(CommandHandler("reset", reset_history))
    app.add_handler(CommandHandler("undo", undo))
    app.add_handler(CommandHandler("setadmin", set_admin_manual))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_calc))
    
    app.run_polling()
