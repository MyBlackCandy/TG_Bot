import os
import re
import psycopg2
import requests
import random
import asyncio
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- ⚙️ CONFIGURATION ---
TOKEN = os.getenv('TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
MASTER_ADMIN = os.getenv('ADMIN_ID')
MY_USDT_ADDR = os.getenv('USDT_ADDRESS')

# --- 🗄️ DATABASE SYSTEM ---
def get_db_connection():
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode='require')

def init_db():
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS customers (
        user_id BIGINT PRIMARY KEY, expire_date TIMESTAMP, username TEXT, first_name TEXT
    )''')
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

# --- 🔄 ส่วนที่ 1: AUTO VERIFY TASK (Background Job) ---
async def auto_verify_task(context: ContextTypes.DEFAULT_TYPE):
    try:
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('SELECT user_id, amount FROM pending_payments WHERE expire_at > %s', (datetime.now(),))
        pending = cursor.fetchall()
        if pending:
            url = "https://apilist.tronscan.org/api/token_trc20/transfers"
            params = {"limit": 20, "direction": "in", "relatedAddress": MY_USDT_ADDR}
            data = requests.get(url, params=params, timeout=10).json().get('token_transfers', [])
            for uid, amt in pending:
                for tx in data:
                    t_info = tx.get('tokenInfo', {})
                    if tx.get('to_address') == MY_USDT_ADDR and t_info.get('symbol') == 'USDT':
                        tx_amt = float(tx.get('quant', 0)) / (10 ** int(t_info.get('decimals', 6)))
                        tx_id = tx.get('transaction_id')
                        if abs(tx_amt - float(amt)) < 0.001:
                            cursor.execute('SELECT 1 FROM used_transactions WHERE tx_id=%s', (tx_id,))
                            if not cursor.fetchone():
                                cursor.execute('INSERT INTO used_transactions VALUES (%s, %s)', (tx_id, uid))
                                cursor.execute('SELECT expire_date FROM customers WHERE user_id=%s', (uid,))
                                old = cursor.fetchone()
                                base = old[0] if old and old[0] > datetime.now() else datetime.now()
                                new_exp = base + timedelta(days=30)
                                cursor.execute('''INSERT INTO customers (user_id, expire_date) VALUES (%s, %s) 
                                               ON CONFLICT (user_id) DO UPDATE SET expire_date=EXCLUDED.expire_date''', (uid, new_exp))
                                cursor.execute('DELETE FROM pending_payments WHERE user_id=%s', (uid,))
                                conn.commit()
                                await context.bot.send_message(chat_id=uid, text=f"✅ **支付成功!** 到期: `{new_exp.strftime('%Y-%m-%d %H:%M')}`")
        cursor.close(); conn.close()
    except Exception as e:
        print(f"TronScan Error: {e}")

# --- 🤖 ส่วนที่ 2: BOT LOGIC (Core Functions) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private': return
    amt = 100 + (random.randint(1, 99) / 100)
    exp = datetime.now() + timedelta(minutes=15)
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('INSERT INTO pending_payments VALUES (%s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET amount=EXCLUDED.amount, expire_at=EXCLUDED.expire_at', (update.message.from_user.id, amt, exp))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text(f"🚀 **黑糖果激活系统**\n💳 金额: `{amt:.2f}` USDT\n地址: `{MY_USDT_ADDR}`")

async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if str(uid) == str(MASTER_ADMIN): return await update.message.reply_text("👑 **主管理员 | 永久有效**")
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT expire_date FROM customers WHERE user_id = %s', (uid,))
    res = cursor.fetchone(); cursor.close(); conn.close()
    if res and res[0] > datetime.now():
        return await update.message.reply_text(f"✅ **权限状态: 正常**\n📅 到期: `{res[0].strftime('%Y-%m-%d %H:%M')}`")
    await update.message.reply_text("❌ **权限未激活**\n请私聊 /start")

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    match = re.match(r'^([+-])(\d+)$', text)
    if match:
        if not check_access(update.message.from_user.id, update.effective_chat.id): return
        amt = int(match.group(2)) if match.group(1) == '+' else -int(match.group(2))
        chat_id = update.effective_chat.id
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO history (chat_id, amount, user_name) VALUES (%s, %s, %s)', (chat_id, amt, update.message.from_user.first_name))
        conn.commit()
        cursor.execute('SELECT amount, user_name FROM history WHERE chat_id = %s ORDER BY timestamp ASC', (chat_id,))
        rows = cursor.fetchall()
        total = sum(r[0] for r in rows)
        count = len(rows)
        history_text = "...\n" if count > 5 else ""
        for r in rows[-5:]:
            sign = "+" if r[0] > 0 else ""
            history_text += f"{sign}{r[0]} ({r[1]})\n"
        cursor.close(); conn.close()
        await update.message.reply_text(f"📊 **账目汇总**\n━━━━━━━━━━━━\n{history_text}━━━━━━━━━━━━\n💰 **总额: {total}**")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📖 **帮助菜单**\n- /start: 激活权限\n- /check: 查看到期\n- จดบัญชี: พิมพ์ + หรือ - ตามด้วยตัวเลข")

# --- 🚀 RUN BOT (Register Handlers) ---
if __name__ == '__main__':
    init_db()
    app = Application.builder().token(TOKEN).build()
    if app.job_queue: app.job_queue.run_repeating(auto_verify_task, interval=30)
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check_status))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    
    app.run_polling()
