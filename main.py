import os
import re
import psycopg2
import requests
import random
import asyncio
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- CONFIG ---
TOKEN = os.getenv('TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
MASTER_ADMIN = os.getenv('ADMIN_ID')
MY_USDT_ADDR = os.getenv('USDT_ADDRESS')
TRON_API_KEY = os.getenv('TRONGRID_API_KEY')

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

# --- UTILS ---
def check_access(user_id, chat_id):
    if str(user_id) == str(MASTER_ADMIN): return True
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM customers WHERE user_id = %s AND expire_date > %s', (user_id, datetime.now()))
    is_customer = cursor.fetchone()
    if is_customer: 
        cursor.close(); conn.close(); return True
    cursor.execute('SELECT 1 FROM team_members WHERE member_id = %s AND allowed_chat_id = %s', (user_id, chat_id))
    res = cursor.fetchone(); cursor.close(); conn.close()
    return True if res else False

# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private': return
    amt = 100 + (random.randint(1, 99) / 100)
    exp = datetime.now() + timedelta(minutes=15)
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('INSERT INTO pending_payments VALUES (%s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET amount=EXCLUDED.amount, expire_at=EXCLUDED.expire_at', (update.message.from_user.id, amt, exp))
    conn.commit(); cursor.close(); conn.close()
    msg = f"🚀 **欢迎使用管理系统**\n💰 **金额:** `{amt:.2f}` USDT (TRC-20)\n🏦 `{MY_USDT_ADDR}`\n⏰ 15分钟内转账，系统将自动激活。"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT expire_date FROM customers WHERE user_id = %s', (user_id,))
    res = cursor.fetchone(); cursor.close(); conn.close()
    if res and res[0] > datetime.now():
        await update.message.reply_text(f"✅ **状态: 有效**\n📅 **到期:** `{res[0].strftime('%Y-%m-%d %H:%M')}`", parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ **权限已过期或未开通**")

async def add_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message: return
    leader_id = update.message.from_user.id
    chat_id = update.effective_chat.id
    if not check_access(leader_id, chat_id): return
    target = update.message.reply_to_message.from_user
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('INSERT INTO team_members VALUES (%s, %s, %s) ON CONFLICT (member_id) DO UPDATE SET allowed_chat_id=EXCLUDED.allowed_chat_id', (target.id, leader_id, chat_id))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text(f"✅ 已授权组员: {target.first_name}")

async def undo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not check_access(update.message.from_user.id, chat_id): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE id = (SELECT id FROM history WHERE chat_id = %s ORDER BY timestamp DESC LIMIT 1)', (chat_id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("↩️ 已撤回最后一条记录")

async def handle_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    chat_id = update.effective_chat.id
    if not check_access(update.message.from_user.id, chat_id): return
    match = re.match(r'^([+-])(\d+)$', update.message.text.strip())
    if match:
        amt = int(match.group(2)) if match.group(1) == '+' else -int(match.group(2))
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO history (chat_id, amount, user_name) VALUES (%s, %s, %s)', (chat_id, amt, update.message.from_user.first_name))
        conn.commit()
        cursor.execute('SELECT amount, user_name FROM history WHERE chat_id = %s ORDER BY timestamp ASC', (chat_id,))
        rows = cursor.fetchall(); cursor.close(); conn.close()
        total = sum(r[0] for r in rows)
        res = f"📋 记录\n" + "\n".join([f"{i+1}. {('+' if r[0]>0 else '')}{r[0]} ({r[1]})" for i, r in enumerate(rows[-10:])]) + f"\n💰 总金额: {total}"
        await update.message.reply_text(res)

# --- AUTO VERIFY TASK ---
async def auto_verify_task(context: ContextTypes.DEFAULT_TYPE):
    try:
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('SELECT user_id, amount FROM pending_payments WHERE expire_at > NOW()')
        pending = cursor.fetchall()
        if pending:
            url = f"https://api.trongrid.io/v1/accounts/{MY_USDT_ADDR}/transactions/trc20"
            data = requests.get(url, params={"limit": 20}, headers={"TRON-PRO-API-KEY": TRON_API_KEY} if TRON_API_KEY else {}).json()
            for uid, amt in pending:
                for tx in data.get('data', []):
                    if abs((int(tx['value'])/1000000) - float(amt)) < 0.0001:
                        cursor.execute('SELECT 1 FROM used_transactions WHERE tx_id=%s', (tx['transaction_id'],))
                        if not cursor.fetchone():
                            cursor.execute('INSERT INTO used_transactions VALUES (%s, %s)', (tx['transaction_id'], uid))
                            cursor.execute('SELECT expire_date FROM customers WHERE user_id=%s', (uid,))
                            old = cursor.fetchone()
                            new_exp = (old[0] if old and old[0] > datetime.now() else datetime.now()) + timedelta(days=30)
                            cursor.execute('INSERT INTO customers VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET expire_date=EXCLUDED.expire_date', (uid, new_exp))
                            cursor.execute('DELETE FROM pending_payments WHERE user_id=%s', (uid,))
                            conn.commit()
                            await context.bot.send_message(chat_id=uid, text=f"✅ **支付成功!** 到期: `{new_exp.strftime('%Y-%m-%d')}`", parse_mode='Markdown')
        cursor.close(); conn.close()
    except: pass

# --- MAIN ---
if __name__ == '__main__':
    init_db()
    app = Application.builder().token(TOKEN).build()
    if app.job_queue:
        app.job_queue.run_repeating(auto_verify_task, interval=30, first=10)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check_status))
    app.add_handler(CommandHandler("add", add_member))
    app.add_handler(CommandHandler("undo", undo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_calc))
    app.run_polling()
